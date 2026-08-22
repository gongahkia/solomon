const std = @import("std");

pub const max_config_bytes = 1024 * 1024;
pub const max_command_output_bytes = 1024 * 1024;

pub const Status = enum {
    verified,
    mismatch,
    unknown,
    not_configured,
};

pub const KubernetesContract = struct {
    context: ?[]u8 = null,
    namespace: ?[]u8 = null,
    cluster_server: ?[]u8 = null,

    fn deinit(self: *KubernetesContract, allocator: std.mem.Allocator) void {
        if (self.context) |value| allocator.free(value);
        if (self.namespace) |value| allocator.free(value);
        if (self.cluster_server) |value| allocator.free(value);
        self.* = .{};
    }
};

pub const TerraformContract = struct {
    workspace: ?[]u8 = null,

    fn deinit(self: *TerraformContract, allocator: std.mem.Allocator) void {
        if (self.workspace) |value| allocator.free(value);
        self.* = .{};
    }
};

pub const Contract = struct {
    name: []u8,
    kubernetes: ?KubernetesContract = null,
    terraform: ?TerraformContract = null,

    fn deinit(self: *Contract, allocator: std.mem.Allocator) void {
        allocator.free(self.name);
        if (self.kubernetes) |*value| value.deinit(allocator);
        if (self.terraform) |*value| value.deinit(allocator);
        self.* = undefined;
    }
};

pub const ContractSet = struct {
    contracts: std.ArrayList(Contract) = .empty,

    pub fn deinit(self: *ContractSet, allocator: std.mem.Allocator) void {
        for (self.contracts.items) |*contract| contract.deinit(allocator);
        self.contracts.deinit(allocator);
        self.* = .{};
    }

    pub fn find(self: *const ContractSet, name: []const u8) ?*const Contract {
        for (self.contracts.items) |*contract| {
            if (std.mem.eql(u8, contract.name, name)) return contract;
        }
        return null;
    }
};

const Section = enum { kubernetes, terraform };

/// Parses the deliberately small targets.toml format. Profiles only accept named
/// Kubernetes and Terraform expectations; project-local files are never loaded.
pub fn parseContracts(allocator: std.mem.Allocator, source: []const u8) !ContractSet {
    var set = ContractSet{};
    errdefer set.deinit(allocator);

    var active_contract: ?usize = null;
    var active_section: ?Section = null;
    var lines = std.mem.splitScalar(u8, source, '\n');
    while (lines.next()) |raw_line| {
        const line = std.mem.trim(u8, stripComment(raw_line), " \t\r");
        if (line.len == 0) continue;

        if (line[0] == '[') {
            if (line.len < 3 or line[line.len - 1] != ']') return error.InvalidTargetConfig;
            const header = line[1 .. line.len - 1];
            const parsed = try parseHeader(header);
            active_contract = try ensureContract(&set, allocator, parsed.name);
            active_section = parsed.section;
            continue;
        }

        const equals = std.mem.indexOfScalar(u8, line, '=') orelse return error.InvalidTargetConfig;
        const key = std.mem.trim(u8, line[0..equals], " \t");
        const value = try parseTomlString(line[equals + 1 ..]);
        const contract_index = active_contract orelse return error.InvalidTargetConfig;
        const section = active_section orelse return error.InvalidTargetConfig;
        try setValue(&set.contracts.items[contract_index], allocator, section, key, value);
    }

    if (set.contracts.items.len == 0) return error.EmptyTargetConfig;
    return set;
}

pub fn loadContracts(allocator: std.mem.Allocator, path: []const u8) !ContractSet {
    const source = std.fs.cwd().readFileAlloc(allocator, path, max_config_bytes) catch |err| switch (err) {
        error.FileNotFound => return error.TargetConfigNotFound,
        else => return err,
    };
    defer allocator.free(source);
    return parseContracts(allocator, source);
}

pub fn defaultConfigPathAlloc(allocator: std.mem.Allocator) ![]u8 {
    const xdg = std.process.getEnvVarOwned(allocator, "XDG_CONFIG_HOME") catch |err| switch (err) {
        error.EnvironmentVariableNotFound => null,
        else => return err,
    };
    if (xdg) |base| {
        defer allocator.free(base);
        return std.fmt.allocPrint(allocator, "{s}/shisa/targets.toml", .{base});
    }
    const home = try std.process.getEnvVarOwned(allocator, "HOME");
    defer allocator.free(home);
    return std.fmt.allocPrint(allocator, "{s}/.config/shisa/targets.toml", .{home});
}

const Header = struct {
    name: []const u8,
    section: Section,
};

fn parseHeader(header: []const u8) !Header {
    const prefix = "contracts.";
    if (!std.mem.startsWith(u8, header, prefix)) return error.InvalidTargetConfig;
    const remainder = header[prefix.len..];
    const dot = std.mem.lastIndexOfScalar(u8, remainder, '.') orelse return error.InvalidTargetConfig;
    const name = remainder[0..dot];
    if (name.len == 0 or !validName(name)) return error.InvalidTargetConfig;
    const section_name = remainder[dot + 1 ..];
    const section: Section = if (std.mem.eql(u8, section_name, "kubernetes"))
        .kubernetes
    else if (std.mem.eql(u8, section_name, "terraform"))
        .terraform
    else
        return error.InvalidTargetConfig;
    return .{ .name = name, .section = section };
}

fn validName(name: []const u8) bool {
    for (name) |byte| {
        if (!std.ascii.isAlphanumeric(byte) and byte != '-' and byte != '_') return false;
    }
    return true;
}

fn ensureContract(set: *ContractSet, allocator: std.mem.Allocator, name: []const u8) !usize {
    for (set.contracts.items, 0..) |contract, index| {
        if (std.mem.eql(u8, contract.name, name)) return index;
    }
    try set.contracts.append(allocator, .{ .name = try allocator.dupe(u8, name) });
    return set.contracts.items.len - 1;
}

fn setValue(contract: *Contract, allocator: std.mem.Allocator, section: Section, key: []const u8, value: []const u8) !void {
    switch (section) {
        .kubernetes => {
            if (contract.kubernetes == null) contract.kubernetes = .{};
            const kubernetes = &contract.kubernetes.?;
            if (std.mem.eql(u8, key, "context")) {
                try replaceValue(allocator, &kubernetes.context, value);
            } else if (std.mem.eql(u8, key, "namespace")) {
                try replaceValue(allocator, &kubernetes.namespace, value);
            } else if (std.mem.eql(u8, key, "cluster_server")) {
                try replaceValue(allocator, &kubernetes.cluster_server, value);
            } else {
                return error.InvalidTargetConfig;
            }
        },
        .terraform => {
            if (contract.terraform == null) contract.terraform = .{};
            const terraform = &contract.terraform.?;
            if (std.mem.eql(u8, key, "workspace")) {
                try replaceValue(allocator, &terraform.workspace, value);
            } else {
                return error.InvalidTargetConfig;
            }
        },
    }
}

fn replaceValue(allocator: std.mem.Allocator, field: *?[]u8, value: []const u8) !void {
    const copy = try allocator.dupe(u8, value);
    if (field.*) |old| allocator.free(old);
    field.* = copy;
}

fn parseTomlString(raw: []const u8) ![]const u8 {
    const value = std.mem.trim(u8, raw, " \t\r");
    if (value.len < 2 or value[0] != '"' or value[value.len - 1] != '"') return error.InvalidTargetConfig;
    const body = value[1 .. value.len - 1];
    if (std.mem.indexOfScalar(u8, body, '\\') != null) return error.InvalidTargetConfig;
    return body;
}

fn stripComment(line: []const u8) []const u8 {
    var quoted = false;
    for (line, 0..) |byte, index| {
        if (byte == '"') quoted = !quoted;
        if (byte == '#' and !quoted) return line[0..index];
    }
    return line;
}

pub const FieldCheck = struct {
    expected: ?[]const u8,
    observed: ?[]u8,
    source: []const u8,
    status: Status,

    fn deinit(self: *FieldCheck, allocator: std.mem.Allocator) void {
        if (self.observed) |value| allocator.free(value);
        self.* = undefined;
    }
};

pub const KubernetesInspection = struct {
    context: FieldCheck,
    namespace: FieldCheck,
    cluster_server: FieldCheck,
    status: Status,

    fn deinit(self: *KubernetesInspection, allocator: std.mem.Allocator) void {
        self.context.deinit(allocator);
        self.namespace.deinit(allocator);
        self.cluster_server.deinit(allocator);
        self.* = undefined;
    }
};

pub const TerraformInspection = struct {
    workspace: FieldCheck,
    local_lock_present: bool,
    status: Status,

    fn deinit(self: *TerraformInspection, allocator: std.mem.Allocator) void {
        self.workspace.deinit(allocator);
        self.* = undefined;
    }
};

pub const Inspection = struct {
    contract: []const u8,
    observed_at_unix: i64,
    kubernetes: ?KubernetesInspection = null,
    terraform: ?TerraformInspection = null,

    pub fn deinit(self: *Inspection, allocator: std.mem.Allocator) void {
        if (self.kubernetes) |*value| value.deinit(allocator);
        if (self.terraform) |*value| value.deinit(allocator);
        self.* = undefined;
    }
};

pub const Invocation = struct {
    family: Family,
    kube_overrides: KubeOverrides = .{},
};

pub const Family = enum { kubernetes, terraform };

pub const KubeOverrides = struct {
    context: ?[]const u8 = null,
    namespace: ?[]const u8 = null,
    has_kubeconfig_override: bool = false,
};

pub fn parseInvocation(argv: []const []const u8) !Invocation {
    if (argv.len == 0) return error.MissingCommand;
    const executable = std.fs.path.basename(argv[0]);
    if (std.mem.eql(u8, executable, "kubectl") or std.mem.eql(u8, executable, "helm")) {
        return .{ .family = .kubernetes, .kube_overrides = try parseKubeOverrides(argv[1..]) };
    }
    if (std.mem.eql(u8, executable, "terraform") or std.mem.eql(u8, executable, "tofu")) return .{ .family = .terraform };
    return error.UnsupportedCommand;
}

fn parseKubeOverrides(args: []const []const u8) !KubeOverrides {
    var overrides = KubeOverrides{};
    var index: usize = 0;
    while (index < args.len) : (index += 1) {
        const arg = args[index];
        if (std.mem.eql(u8, arg, "--context") or std.mem.eql(u8, arg, "--kube-context")) {
            if (index + 1 >= args.len) return error.MissingCommandOptionValue;
            index += 1;
            overrides.context = args[index];
        } else if (std.mem.startsWith(u8, arg, "--context=")) {
            overrides.context = arg["--context=".len..];
        } else if (std.mem.startsWith(u8, arg, "--kube-context=")) {
            overrides.context = arg["--kube-context=".len..];
        } else if (std.mem.eql(u8, arg, "--namespace") or std.mem.eql(u8, arg, "-n")) {
            if (index + 1 >= args.len) return error.MissingCommandOptionValue;
            index += 1;
            overrides.namespace = args[index];
        } else if (std.mem.startsWith(u8, arg, "--namespace=")) {
            overrides.namespace = arg["--namespace=".len..];
        } else if (arg.len > 2 and std.mem.startsWith(u8, arg, "-n")) {
            overrides.namespace = arg[2..];
        } else if (std.mem.eql(u8, arg, "--kubeconfig") or std.mem.startsWith(u8, arg, "--kubeconfig=")) {
            overrides.has_kubeconfig_override = true;
        }
    }
    return overrides;
}

pub fn inspect(allocator: std.mem.Allocator, contract: *const Contract, cwd: []const u8, overrides: KubeOverrides) !Inspection {
    var result = Inspection{
        .contract = contract.name,
        .observed_at_unix = std.time.timestamp(),
    };
    errdefer result.deinit(allocator);

    if (contract.kubernetes) |kubernetes| {
        result.kubernetes = try inspectKubernetes(allocator, kubernetes, overrides);
    }
    if (contract.terraform) |terraform| {
        result.terraform = try inspectTerraform(allocator, terraform, cwd);
    }
    return result;
}

const KubeConfig = struct {
    @"current-context": []const u8 = "",
    contexts: []const ContextEntry = &.{},
    clusters: []const ClusterEntry = &.{},
};

const ContextEntry = struct {
    name: []const u8 = "",
    context: struct {
        cluster: []const u8 = "",
        namespace: []const u8 = "",
    } = .{},
};

const ClusterEntry = struct {
    name: []const u8 = "",
    cluster: struct {
        server: []const u8 = "",
    } = .{},
};

const KubeObservation = struct {
    context: ?[]u8 = null,
    namespace: ?[]u8 = null,
    cluster_server: ?[]u8 = null,

    fn deinit(self: *KubeObservation, allocator: std.mem.Allocator) void {
        if (self.context) |value| allocator.free(value);
        if (self.namespace) |value| allocator.free(value);
        if (self.cluster_server) |value| allocator.free(value);
        self.* = .{};
    }
};

fn inspectKubernetes(allocator: std.mem.Allocator, contract: KubernetesContract, overrides: KubeOverrides) !KubernetesInspection {
    if (overrides.has_kubeconfig_override) return unknownKubernetes(contract, overrides);
    const observation = try readKubeObservation(allocator, overrides);
    const context_source = if (overrides.context != null) "command context flag" else "kubectl config view";
    const namespace_source = if (overrides.namespace != null) "command namespace flag" else "kubectl config view";
    const context = makeField(contract.context, observation.context, context_source);
    const namespace = makeField(contract.namespace, observation.namespace, namespace_source);
    const cluster_server = makeField(contract.cluster_server, observation.cluster_server, "kubectl config view");
    return .{
        .context = context,
        .namespace = namespace,
        .cluster_server = cluster_server,
        .status = combineStatuses(&.{ context.status, namespace.status, cluster_server.status }),
    };
}

fn unknownKubernetes(contract: KubernetesContract, overrides: KubeOverrides) KubernetesInspection {
    const source = if (overrides.has_kubeconfig_override) "unsupported --kubeconfig override" else "kubectl config view";
    const context = makeField(contract.context, null, source);
    const namespace = makeField(contract.namespace, null, source);
    const cluster_server = makeField(contract.cluster_server, null, source);
    return .{
        .context = context,
        .namespace = namespace,
        .cluster_server = cluster_server,
        .status = combineStatuses(&.{ context.status, namespace.status, cluster_server.status }),
    };
}

fn readKubeObservation(allocator: std.mem.Allocator, overrides: KubeOverrides) !KubeObservation {
    const result = std.process.Child.run(.{
        .allocator = allocator,
        .argv = &.{ "kubectl", "config", "view", "-o", "json" },
        .max_output_bytes = max_command_output_bytes,
        .expand_arg0 = .expand,
    }) catch return .{};
    defer allocator.free(result.stderr);
    defer allocator.free(result.stdout);
    if (!exitedZero(result.term)) return .{};

    return parseKubeObservation(allocator, result.stdout, overrides) catch return .{};
}

fn parseKubeObservation(allocator: std.mem.Allocator, source: []const u8, overrides: KubeOverrides) !KubeObservation {
    var parsed = std.json.parseFromSlice(KubeConfig, allocator, source, .{ .ignore_unknown_fields = true }) catch return .{};
    defer parsed.deinit();
    const context_name = overrides.context orelse nonEmpty(parsed.value.@"current-context") orelse return .{};
    const context_entry = findContext(parsed.value.contexts, context_name) orelse return .{};
    const namespace = overrides.namespace orelse nonEmpty(context_entry.context.namespace) orelse "default";
    const cluster = findCluster(parsed.value.clusters, context_entry.context.cluster);

    var observation = KubeObservation{};
    errdefer observation.deinit(allocator);
    observation.context = try allocator.dupe(u8, context_name);
    observation.namespace = try allocator.dupe(u8, namespace);
    if (cluster) |value| if (nonEmpty(value.cluster.server)) |server| {
        observation.cluster_server = try allocator.dupe(u8, server);
    };
    return observation;
}

fn findContext(contexts: []const ContextEntry, name: []const u8) ?ContextEntry {
    for (contexts) |context| if (std.mem.eql(u8, context.name, name)) return context;
    return null;
}

fn findCluster(clusters: []const ClusterEntry, name: []const u8) ?ClusterEntry {
    for (clusters) |cluster| if (std.mem.eql(u8, cluster.name, name)) return cluster;
    return null;
}

fn inspectTerraform(allocator: std.mem.Allocator, contract: TerraformContract, cwd: []const u8) !TerraformInspection {
    const observed = try readTerraformWorkspace(allocator, cwd);
    const source = if (try envWorkspaceAlloc(allocator)) |workspace| blk: {
        allocator.free(workspace);
        break :blk "TF_WORKSPACE";
    } else ".terraform/environment or local state";
    const workspace = makeField(contract.workspace, observed, source);
    return .{
        .workspace = workspace,
        .local_lock_present = try terraformLockPresent(allocator, cwd),
        .status = workspace.status,
    };
}

fn readTerraformWorkspace(allocator: std.mem.Allocator, cwd: []const u8) !?[]u8 {
    if (try envWorkspaceAlloc(allocator)) |workspace| return @as(?[]u8, workspace);
    const paths = [_][]const u8{
        ".terraform/environment",
        ".terraform/terraform.tfstate",
        "terraform.tfstate",
    };
    for (paths, 0..) |relative, index| {
        const path = try std.fs.path.join(allocator, &.{ cwd, relative });
        defer allocator.free(path);
        const source = std.fs.cwd().readFileAlloc(allocator, path, max_config_bytes) catch |err| switch (err) {
            error.FileNotFound => continue,
            else => return err,
        };
        defer allocator.free(source);
        if (index == 0) {
            const workspace = nonEmpty(std.mem.trim(u8, source, " \t\r\n")) orelse continue;
            return @as(?[]u8, try allocator.dupe(u8, workspace));
        }
        const State = struct { current_workspace: []const u8 = "", workspace: []const u8 = "" };
        var parsed = std.json.parseFromSlice(State, allocator, source, .{ .ignore_unknown_fields = true }) catch continue;
        defer parsed.deinit();
        const workspace = nonEmpty(parsed.value.current_workspace) orelse nonEmpty(parsed.value.workspace) orelse continue;
        return @as(?[]u8, try allocator.dupe(u8, workspace));
    }
    return null;
}

fn envWorkspaceAlloc(allocator: std.mem.Allocator) !?[]u8 {
    const workspace = std.process.getEnvVarOwned(allocator, "TF_WORKSPACE") catch |err| switch (err) {
        error.EnvironmentVariableNotFound => return null,
        else => return err,
    };
    if (nonEmpty(workspace) == null) {
        allocator.free(workspace);
        return null;
    }
    return workspace;
}

fn terraformLockPresent(allocator: std.mem.Allocator, cwd: []const u8) !bool {
    const paths = [_][]const u8{
        ".terraform.tfstate.lock.info",
        "terraform.tfstate.lock.info",
        ".terraform/terraform.tfstate.lock.info",
    };
    for (paths) |relative| {
        const path = try std.fs.path.join(allocator, &.{ cwd, relative });
        defer allocator.free(path);
        std.fs.cwd().access(path, .{}) catch |err| switch (err) {
            error.FileNotFound => continue,
            else => return err,
        };
        return true;
    }
    return false;
}

fn makeField(expected: ?[]const u8, observed: ?[]u8, source: []const u8) FieldCheck {
    return .{
        .expected = expected,
        .observed = observed,
        .source = source,
        .status = fieldStatus(expected, observed),
    };
}

fn fieldStatus(expected: ?[]const u8, observed: ?[]const u8) Status {
    if (expected == null) return .not_configured;
    if (observed == null) return .unknown;
    return if (std.mem.eql(u8, expected.?, observed.?)) .verified else .mismatch;
}

fn combineStatuses(statuses: []const Status) Status {
    var configured = false;
    var unknown = false;
    for (statuses) |status| switch (status) {
        .mismatch => return .mismatch,
        .unknown => {
            configured = true;
            unknown = true;
        },
        .verified => configured = true,
        .not_configured => {},
    };
    if (!configured) return .not_configured;
    return if (unknown) .unknown else .verified;
}

fn nonEmpty(value: []const u8) ?[]const u8 {
    return if (value.len == 0) null else value;
}

fn exitedZero(term: std.process.Child.Term) bool {
    return switch (term) {
        .Exited => |code| code == 0,
        else => false,
    };
}

test "parses a Kubernetes and Terraform target contract" {
    var contracts = try parseContracts(std.testing.allocator,
        \\[contracts.payments-prod.kubernetes]
        \\context = "payments-admin"
        \\namespace = "payments"
        \\cluster_server = "https://prod.example"
        \\
        \\[contracts.payments-prod.terraform]
        \\workspace = "production"
    );
    defer contracts.deinit(std.testing.allocator);

    const contract = contracts.find("payments-prod").?;
    try std.testing.expectEqualStrings("payments-admin", contract.kubernetes.?.context.?);
    try std.testing.expectEqualStrings("production", contract.terraform.?.workspace.?);
}

test "rejects untrusted target names and unknown properties" {
    try std.testing.expectError(error.InvalidTargetConfig, parseContracts(std.testing.allocator,
        \\[contracts.prod.team.kubernetes]
        \\context = "prod"
    ));
    try std.testing.expectError(error.InvalidTargetConfig, parseContracts(std.testing.allocator,
        \\[contracts.prod.kubernetes]
        \\credential = "secret"
    ));
}

test "invocation parsing observes Kubernetes overrides and rejects unknown executables" {
    const invocation = try parseInvocation(&.{ "kubectl", "--context=prod", "-n", "payments", "get", "pods" });
    try std.testing.expectEqual(Family.kubernetes, invocation.family);
    try std.testing.expectEqualStrings("prod", invocation.kube_overrides.context.?);
    try std.testing.expectEqualStrings("payments", invocation.kube_overrides.namespace.?);
    try std.testing.expectError(error.UnsupportedCommand, parseInvocation(&.{"./deploy.sh"}));
}

test "Kubernetes observation applies explicit context and namespace flags" {
    const source =
        \\{
        \\  "current-context": "staging",
        \\  "contexts": [
        \\    {"name": "staging", "context": {"cluster": "staging-cluster", "namespace": "default"}},
        \\    {"name": "prod", "context": {"cluster": "prod-cluster", "namespace": "payments"}}
        \\  ],
        \\  "clusters": [
        \\    {"name": "prod-cluster", "cluster": {"server": "https://prod.example"}}
        \\  ]
        \\}
    ;
    var observed = try parseKubeObservation(std.testing.allocator, source, .{ .context = "prod", .namespace = "releases" });
    defer observed.deinit(std.testing.allocator);
    try std.testing.expectEqualStrings("prod", observed.context.?);
    try std.testing.expectEqualStrings("releases", observed.namespace.?);
    try std.testing.expectEqualStrings("https://prod.example", observed.cluster_server.?);
}

test "field status distinguishes configured state from unknown observations" {
    try std.testing.expectEqual(Status.verified, fieldStatus("prod", "prod"));
    try std.testing.expectEqual(Status.mismatch, fieldStatus("prod", "staging"));
    try std.testing.expectEqual(Status.unknown, fieldStatus("prod", null));
    try std.testing.expectEqual(Status.not_configured, fieldStatus(null, "prod"));
}
