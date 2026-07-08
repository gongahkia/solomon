const std = @import("std");
const cli_util = @import("util.zig");
const client = @import("../shisa-client.zig");
const cloud_ctx_module = @import("../daemon/modules/cloud_ctx.zig");
const daemon_json = @import("../daemon/json.zig");
const paths = @import("../daemon/paths.zig");
const risk_tier_module = @import("../daemon/modules/risk_tier.zig");

pub fn cloudCmd(allocator: std.mem.Allocator, args: []const []const u8) !void {
    if (args.len >= 1 and std.mem.eql(u8, args[0], "preexec")) {
        const config = try parseCloudPreexecArgs(args[1..]);
        try cloudPreexec(allocator, config);
        return;
    }
    if (args.len == 1 and std.mem.eql(u8, args[0], "audit")) {
        try cloudAudit(allocator);
        return;
    }
    if (args.len == 1 and std.mem.eql(u8, args[0], "doctor")) {
        try cloudDoctor(allocator);
        return;
    }
    if (args.len != 2 or !std.mem.eql(u8, args[0], "explain")) return error.UnknownCloudArgument;
    const home = std.process.getEnvVarOwned(allocator, "HOME") catch |err| switch (err) {
        error.EnvironmentVariableNotFound => null,
        else => return err,
    };
    defer if (home) |value| allocator.free(value);
    const output = try cloudExplainAlloc(allocator, args[1], home);
    defer allocator.free(output);
    try std.fs.File.stdout().writeAll(output);
}

fn cloudDoctor(allocator: std.mem.Allocator) !void {
    const home = std.process.getEnvVarOwned(allocator, "HOME") catch |err| switch (err) {
        error.EnvironmentVariableNotFound => null,
        else => return err,
    };
    defer if (home) |value| allocator.free(value);
    const aws_profile = std.process.getEnvVarOwned(allocator, "AWS_PROFILE") catch |err| switch (err) {
        error.EnvironmentVariableNotFound => null,
        else => return err,
    };
    defer if (aws_profile) |value| allocator.free(value);
    const kubeconfig = std.process.getEnvVarOwned(allocator, "KUBECONFIG") catch |err| switch (err) {
        error.EnvironmentVariableNotFound => null,
        else => return err,
    };
    defer if (kubeconfig) |value| allocator.free(value);

    const output = try cloudDoctorAlloc(allocator, home, aws_profile, kubeconfig);
    defer allocator.free(output);
    try std.fs.File.stdout().writeAll(output);
}

fn cloudDoctorAlloc(allocator: std.mem.Allocator, home: ?[]const u8, aws_profile_env: ?[]const u8, kubeconfig_env: ?[]const u8) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);

    var cache = cloud_ctx_module.Cache{};
    defer cache.deinit(allocator);

    const aws_profile = try cloud_ctx_module.awsProfileAlloc(allocator, aws_profile_env, home);
    defer if (aws_profile) |value| allocator.free(value);
    try cli_util.appendFmt(allocator, &out, "aws_profile: {s}\n", .{aws_profile orelse "-"});

    const gcp_path = try cloud_ctx_module.gcpConfigPathAlloc(allocator, home);
    defer if (gcp_path) |value| allocator.free(value);
    try appendCloudPathLine(allocator, &out, "gcp_config", gcp_path);
    const gcp_project = try cache.gcpProjectAlloc(allocator, home);
    defer if (gcp_project) |value| allocator.free(value);
    try cli_util.appendFmt(allocator, &out, "gcp_project: {s}\n", .{gcp_project orelse "-"});

    const azure_path = try cloud_ctx_module.azureProfilePathAlloc(allocator, home);
    defer if (azure_path) |value| allocator.free(value);
    try appendCloudPathLine(allocator, &out, "azure_profile", azure_path);
    const azure_subscription = try cache.azureSubscriptionAlloc(allocator, home);
    defer if (azure_subscription) |value| allocator.free(value);
    try cli_util.appendFmt(allocator, &out, "azure_subscription: {s}\n", .{azure_subscription orelse "-"});

    const kube_path = try cloud_ctx_module.kubeConfigPathAlloc(allocator, kubeconfig_env, home);
    defer if (kube_path) |value| allocator.free(value);
    try appendCloudPathLine(allocator, &out, "kubeconfig", kube_path);
    const kube_context = try cache.kubeContextAlloc(allocator, kubeconfig_env, home);
    defer if (kube_context) |value| allocator.free(value);
    try cli_util.appendFmt(allocator, &out, "kube_context: {s}\n", .{kube_context orelse "-"});

    return out.toOwnedSlice(allocator);
}

fn appendCloudPathLine(allocator: std.mem.Allocator, out: *std.ArrayList(u8), label: []const u8, path: ?[]const u8) !void {
    if (path) |value| {
        try cli_util.appendFmt(allocator, out, "{s}: {s} {s}\n", .{ label, cli_util.pathAccessStatus(value), value });
    } else {
        try cli_util.appendFmt(allocator, out, "{s}: missing\n", .{label});
    }
}

fn cloudAudit(allocator: std.mem.Allocator) !void {
    const home = try std.process.getEnvVarOwned(allocator, "HOME");
    defer allocator.free(home);
    const output = try cloudAuditAlloc(allocator, home);
    defer allocator.free(output);
    try std.fs.File.stdout().writeAll(output);
}

fn cloudAuditAlloc(allocator: std.mem.Allocator, home: []const u8) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);
    const cloud_path = try cloudRequestAuditPathAlloc(allocator, home);
    defer allocator.free(cloud_path);
    try appendAuditFileIfExists(allocator, &out, cloud_path);
    const prod_path = try prodGuardAuditPathAlloc(allocator, home);
    defer allocator.free(prod_path);
    try appendAuditFileIfExists(allocator, &out, prod_path);
    return out.toOwnedSlice(allocator);
}

fn appendAuditFileIfExists(allocator: std.mem.Allocator, out: *std.ArrayList(u8), path: []const u8) !void {
    const contents = std.fs.cwd().readFileAlloc(allocator, path, cli_util.max_config_bytes) catch |err| switch (err) {
        error.FileNotFound => return,
        else => return err,
    };
    defer allocator.free(contents);
    try out.appendSlice(allocator, contents);
}

fn cloudRequestAuditPathAlloc(allocator: std.mem.Allocator, home: []const u8) ![]u8 {
    return std.fmt.allocPrint(allocator, "{s}/.local/state/shisa/cloud_requests.jsonl", .{home});
}

fn prodGuardAuditPathAlloc(allocator: std.mem.Allocator, home: []const u8) ![]u8 {
    return std.fmt.allocPrint(allocator, "{s}/.local/state/shisa/prod_guard.jsonl", .{home});
}

const CloudPreexec = struct {
    socket_path: ?[]const u8 = null,
    shell: []const u8 = "",
    command: []const u8,
    force: bool = false,
};

const CloudPreexecResponse = struct {
    v: u32 = 1,
    allow: bool = true,
    confirm: []const u8 = "",
    tier: []const u8 = "unknown",
    destructive_pattern: []const u8 = "-",
    warning: []const u8 = "",
};

fn parseCloudPreexecArgs(args: []const []const u8) !CloudPreexec {
    var parsed = CloudPreexec{ .command = "" };
    var i: usize = 0;
    while (i < args.len) : (i += 1) {
        const arg = args[i];
        if (std.mem.eql(u8, arg, "--socket")) {
            parsed.socket_path = try cli_util.nextValue(args, &i);
        } else if (std.mem.eql(u8, arg, "--shell")) {
            parsed.shell = try cli_util.nextValue(args, &i);
        } else if (std.mem.eql(u8, arg, "--force")) {
            parsed.force = true;
        } else if (std.mem.eql(u8, arg, "--")) {
            parsed.command = try cli_util.nextValue(args, &i);
            if (i + 1 != args.len) return error.UnknownCloudArgument;
        } else if (parsed.command.len == 0) {
            parsed.command = arg;
        } else {
            return error.UnknownCloudArgument;
        }
    }
    if (parsed.command.len == 0) return error.MissingValue;
    return parsed;
}

fn cloudPreexec(allocator: std.mem.Allocator, config: CloudPreexec) !void {
    const socket_path = if (config.socket_path) |path| path else try paths.defaultSocketPath(allocator);
    defer if (config.socket_path == null) allocator.free(socket_path);
    const payload = try buildCloudPreexecPayload(allocator, config);
    defer allocator.free(payload);
    const response = client.requestAlloc(allocator, socket_path, payload) catch return;
    defer allocator.free(response);
    try enforceCloudPreexecResponse(allocator, response);
}

fn buildCloudPreexecPayload(allocator: std.mem.Allocator, config: CloudPreexec) ![]u8 {
    const cwd = try std.fs.cwd().realpathAlloc(allocator, ".");
    defer allocator.free(cwd);
    const escaped_cwd = try daemon_json.escapeAlloc(allocator, cwd);
    defer allocator.free(escaped_cwd);
    const escaped_shell = try daemon_json.escapeAlloc(allocator, config.shell);
    defer allocator.free(escaped_shell);
    const escaped_command = try daemon_json.escapeAlloc(allocator, config.command);
    defer allocator.free(escaped_command);
    return std.fmt.allocPrint(
        allocator,
        "{{\"v\":1,\"kind\":\"preexec\",\"cwd\":\"{s}\",\"shell\":\"{s}\",\"command\":\"{s}\",\"force\":{}}}",
        .{ escaped_cwd, escaped_shell, escaped_command, config.force },
    );
}

fn cloudExplainAlloc(allocator: std.mem.Allocator, value: []const u8, home: ?[]const u8) ![]u8 {
    var rules = try risk_tier_module.loadUserRulesAlloc(allocator, home);
    defer if (rules) |*loaded| loaded.deinit(allocator);
    const reason = risk_tier_module.explain(value, rules);
    const pattern = if (reason.pattern.len == 0) "-" else reason.pattern;
    return std.fmt.allocPrint(
        allocator,
        "value: {s}\ntier: {s}\nsource: {s}\npattern: {s}\n",
        .{ value, risk_tier_module.tierName(reason.tier), risk_tier_module.sourceName(reason.source), pattern },
    );
}

fn enforceCloudPreexecResponse(allocator: std.mem.Allocator, response: []const u8) !void {
    var parsed = try std.json.parseFromSlice(CloudPreexecResponse, allocator, response, .{ .ignore_unknown_fields = true });
    defer parsed.deinit();
    if (parsed.value.warning.len != 0) try printCloudPreexecWarning(parsed.value.warning);
    if (parsed.value.allow) return;
    if (parsed.value.confirm.len == 0) return error.PreexecDenied;
    try promptTierConfirmation(parsed.value);
}

fn printCloudPreexecWarning(warning: []const u8) !void {
    const stderr = std.fs.File.stderr();
    try stderr.writeAll("shisa warning: ");
    try stderr.writeAll(warning);
    try stderr.writeAll("\n");
}

fn promptTierConfirmation(decision: CloudPreexecResponse) !void {
    const stderr = std.fs.File.stderr();
    try stderr.writeAll("shisa prod_guard: ");
    try stderr.writeAll(decision.destructive_pattern);
    try stderr.writeAll(" in ");
    try stderr.writeAll(decision.tier);
    try stderr.writeAll("; type ");
    try stderr.writeAll(decision.confirm);
    try stderr.writeAll(" to proceed: ");

    var buffer: [128]u8 = undefined;
    const n = try std.fs.File.stdin().read(&buffer);
    const answer = std.mem.trim(u8, buffer[0..n], " \t\r\n");
    if (!std.mem.eql(u8, answer, decision.confirm)) return error.PreexecDenied;
}

fn copyFixtureToPath(allocator: std.mem.Allocator, source_path: []const u8, dest_path: []u8) !void {
    defer allocator.free(dest_path);
    const source = try std.fs.cwd().readFileAlloc(allocator, source_path, cli_util.max_config_bytes);
    defer allocator.free(source);
    if (std.fs.path.dirname(dest_path)) |parent| try std.fs.cwd().makePath(parent);
    var file = try std.fs.createFileAbsolute(dest_path, .{ .truncate = true });
    defer file.close();
    try file.writeAll(source);
}

test "cloud preexec args parse" {
    const parsed = try parseCloudPreexecArgs(&.{ "--socket", "/tmp/shisa.sock", "--shell", "zsh", "--force", "--", "kubectl delete pod x" });
    try std.testing.expectEqualStrings("/tmp/shisa.sock", parsed.socket_path.?);
    try std.testing.expectEqualStrings("zsh", parsed.shell);
    try std.testing.expect(parsed.force);
    try std.testing.expectEqualStrings("kubectl delete pod x", parsed.command);
}

test "cloud preexec response allows safe command" {
    try enforceCloudPreexecResponse(std.testing.allocator, "{\"v\":1,\"allow\":true}");
}

test "cloud preexec response denies without confirm token" {
    try std.testing.expectError(error.PreexecDenied, enforceCloudPreexecResponse(std.testing.allocator, "{\"v\":1,\"allow\":false}"));
}

test "cloud preexec payload escapes command" {
    const payload = try buildCloudPreexecPayload(std.testing.allocator, .{ .shell = "zsh", .command = "echo \"prod\"" });
    defer std.testing.allocator.free(payload);
    try std.testing.expect(std.mem.indexOf(u8, payload, "\"command\":\"echo \\\"prod\\\"\"") != null);
}

test "cloud audit reads prod guard jsonl" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-audit-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};

    const cloud_path = try cloudRequestAuditPathAlloc(allocator, dir_path);
    defer allocator.free(cloud_path);
    if (std.fs.path.dirname(cloud_path)) |parent| try std.fs.cwd().makePath(parent);
    {
        var file = try std.fs.createFileAbsolute(cloud_path, .{});
        defer file.close();
        try file.writeAll("{\"kind\":\"preexec\"}\n");
    }

    const prod_path = try prodGuardAuditPathAlloc(allocator, dir_path);
    defer allocator.free(prod_path);
    {
        var file = try std.fs.createFileAbsolute(prod_path, .{});
        defer file.close();
        try file.writeAll("{\"tier\":\"prod\"}\n");
    }

    const output = try cloudAuditAlloc(allocator, dir_path);
    defer allocator.free(output);
    try std.testing.expectEqualStrings("{\"kind\":\"preexec\"}\n{\"tier\":\"prod\"}\n", output);
}

test "cloud doctor reports config status" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-cloud-doctor-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};

    try copyFixtureToPath(allocator, "test/fixtures/cloud/aws-config-default", try std.fmt.allocPrint(allocator, "{s}/.aws/config", .{dir_path}));
    try copyFixtureToPath(allocator, "test/fixtures/cloud/gcloud-config", try std.fmt.allocPrint(allocator, "{s}/.config/gcloud/configurations/config_default", .{dir_path}));
    try copyFixtureToPath(allocator, "test/fixtures/cloud/azureProfile.json", try std.fmt.allocPrint(allocator, "{s}/.azure/azureProfile.json", .{dir_path}));
    try copyFixtureToPath(allocator, "test/fixtures/cloud/kubeconfig-with-namespace.yaml", try std.fmt.allocPrint(allocator, "{s}/.kube/config", .{dir_path}));

    const output = try cloudDoctorAlloc(allocator, dir_path, null, null);
    defer allocator.free(output);
    try std.testing.expect(std.mem.indexOf(u8, output, "aws_profile: default\n") != null);
    try std.testing.expect(std.mem.indexOf(u8, output, "gcp_project: test-project\n") != null);
    try std.testing.expect(std.mem.indexOf(u8, output, "azure_subscription: prod-sub\n") != null);
    try std.testing.expect(std.mem.indexOf(u8, output, "kube_context: prod/default\n") != null);
}

test "cloud explain output shows reason" {
    const output = try cloudExplainAlloc(std.testing.allocator, "api-prd-use1", null);
    defer std.testing.allocator.free(output);

    try std.testing.expect(std.mem.indexOf(u8, output, "tier: prod\n") != null);
    try std.testing.expect(std.mem.indexOf(u8, output, "source: default\n") != null);
    try std.testing.expect(std.mem.indexOf(u8, output, "pattern: *-prd-*\n") != null);
}
