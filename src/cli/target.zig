const std = @import("std");
const target = @import("../target.zig");

pub const help_text =
    \\usage: shisa target <list|inspect|run> [options]
    \\
    \\Verify the effective local target for a direct Kubernetes or Terraform command.
    \\Shisa never switches contexts, writes credentials, or changes global config.
    \\
    \\commands:
    \\  list                         list configured target contracts
    \\  inspect <name> [--json]       print expected, observed, source, and verdict
    \\  run <name> -- <command ...>   verify then run kubectl, helm, terraform, or tofu
    \\
    \\options:
    \\  --config PATH                use this targets.toml instead of the user config
    \\
    \\default config: ~/.config/shisa/targets.toml
    \\
;

const Command = enum { list, inspect, run };

const Args = struct {
    command: Command,
    name: ?[]const u8 = null,
    config_path: ?[]const u8 = null,
    json: bool = false,
    child_argv: []const []const u8 = &.{},
};

pub fn command(allocator: std.mem.Allocator, args: []const []const u8) !void {
    if (args.len == 0 or isHelp(args[0])) {
        try std.fs.File.stdout().writeAll(help_text);
        return;
    }

    const parsed = try parseArgs(args);
    const path = if (parsed.config_path) |value| try allocator.dupe(u8, value) else try target.defaultConfigPathAlloc(allocator);
    defer allocator.free(path);
    var contracts = try target.loadContracts(allocator, path);
    defer contracts.deinit(allocator);

    switch (parsed.command) {
        .list => try listContracts(contracts),
        .inspect => try inspectContract(allocator, &contracts, parsed.name.?, parsed.json, .{}),
        .run => try runContract(allocator, &contracts, parsed.name.?, parsed.child_argv),
    }
}

fn listContracts(contracts: target.ContractSet) !void {
    const stdout = std.fs.File.stdout();
    for (contracts.contracts.items) |contract| {
        try stdout.writeAll(contract.name);
        try stdout.writeAll("\n");
    }
}

fn inspectContract(allocator: std.mem.Allocator, contracts: *const target.ContractSet, name: []const u8, json: bool, overrides: target.KubeOverrides) !void {
    const contract = contracts.find(name) orelse return error.UnknownTargetContract;
    const cwd = try std.fs.cwd().realpathAlloc(allocator, ".");
    defer allocator.free(cwd);
    var inspection = try target.inspect(allocator, contract, cwd, overrides);
    defer inspection.deinit(allocator);
    if (json) {
        var serialized = std.Io.Writer.Allocating.init(allocator);
        defer serialized.deinit();
        try std.json.Stringify.value(inspection, .{}, &serialized.writer);
        try std.fs.File.stdout().writeAll(serialized.written());
        try std.fs.File.stdout().writeAll("\n");
    } else {
        try printInspection(inspection);
    }
}

fn runContract(allocator: std.mem.Allocator, contracts: *const target.ContractSet, name: []const u8, child_argv: []const []const u8) !void {
    const invocation = try target.parseInvocation(child_argv);
    const contract = contracts.find(name) orelse return error.UnknownTargetContract;
    const cwd = try std.fs.cwd().realpathAlloc(allocator, ".");
    defer allocator.free(cwd);
    var inspection = try target.inspect(allocator, contract, cwd, invocation.kube_overrides);
    defer inspection.deinit(allocator);

    const status = switch (invocation.family) {
        .kubernetes => if (inspection.kubernetes) |value| value.status else target.Status.not_configured,
        .terraform => if (inspection.terraform) |value| value.status else target.Status.not_configured,
    };
    if (status != .verified) {
        try std.fs.File.stderr().writeAll("shisa: target contract is not verified; refusing to start command\n");
        try printInspectionTo(std.fs.File.stderr(), inspection);
        return error.TargetContractNotVerified;
    }

    var child = std.process.Child.init(child_argv, allocator);
    child.stdin_behavior = .Inherit;
    child.stdout_behavior = .Inherit;
    child.stderr_behavior = .Inherit;
    child.expand_arg0 = .expand;
    const term = try child.spawnAndWait();
    if (!exitedZero(term)) return error.ChildCommandFailed;
}

fn printInspection(inspection: target.Inspection) !void {
    try printInspectionTo(std.fs.File.stdout(), inspection);
}

fn printInspectionTo(file: std.fs.File, inspection: target.Inspection) !void {
    var rendered = std.Io.Writer.Allocating.init(std.heap.page_allocator);
    defer rendered.deinit();
    const writer = &rendered.writer;
    try writer.print("contract {s} (observed now)\n", .{inspection.contract});
    if (inspection.kubernetes) |kubernetes| {
        try writer.print("kubernetes: {s}\n", .{@tagName(kubernetes.status)});
        try printField(writer, "  context", kubernetes.context);
        try printField(writer, "  namespace", kubernetes.namespace);
        try printField(writer, "  cluster server", kubernetes.cluster_server);
    }
    if (inspection.terraform) |terraform| {
        try writer.print("terraform: {s}; local lock: {s}\n", .{ @tagName(terraform.status), if (terraform.local_lock_present) "present" else "absent" });
        try printField(writer, "  workspace", terraform.workspace);
    }
    try file.writeAll(rendered.written());
}

fn printField(writer: anytype, label: []const u8, field: target.FieldCheck) !void {
    const expected = field.expected orelse "(not configured)";
    const observed = field.observed orelse "(unavailable)";
    try writer.print("{s}: {s}; expected={s}; observed={s}; source={s}\n", .{ label, @tagName(field.status), expected, observed, field.source });
}

fn parseArgs(args: []const []const u8) !Args {
    const verb = if (std.mem.eql(u8, args[0], "list"))
        Command.list
    else if (std.mem.eql(u8, args[0], "inspect"))
        Command.inspect
    else if (std.mem.eql(u8, args[0], "run"))
        Command.run
    else
        return error.UnknownTargetCommand;

    var parsed = Args{ .command = verb };
    var index: usize = 1;
    while (index < args.len) : (index += 1) {
        const arg = args[index];
        if (std.mem.eql(u8, arg, "--config")) {
            if (index + 1 >= args.len) return error.MissingTargetConfigPath;
            index += 1;
            parsed.config_path = args[index];
        } else if (std.mem.eql(u8, arg, "--json")) {
            if (verb != .inspect) return error.UnknownTargetArgument;
            parsed.json = true;
        } else if (std.mem.eql(u8, arg, "--")) {
            if (verb != .run or index + 1 >= args.len) return error.MissingCommand;
            parsed.child_argv = args[index + 1 ..];
            index = args.len;
        } else if (arg.len > 0 and arg[0] == '-') {
            return error.UnknownTargetArgument;
        } else if (parsed.name == null and verb != .list) {
            parsed.name = arg;
        } else {
            return error.UnknownTargetArgument;
        }
    }

    if ((verb == .inspect or verb == .run) and parsed.name == null) return error.MissingTargetName;
    if (verb == .run and parsed.child_argv.len == 0) return error.MissingCommand;
    return parsed;
}

fn isHelp(arg: []const u8) bool {
    return std.mem.eql(u8, arg, "--help") or std.mem.eql(u8, arg, "-h");
}

fn exitedZero(term: std.process.Child.Term) bool {
    return switch (term) {
        .Exited => |code| code == 0,
        else => false,
    };
}

test "target command arguments require a named inspect contract" {
    const inspect = try parseArgs(&.{ "inspect", "payments-prod", "--json" });
    try std.testing.expectEqualStrings("payments-prod", inspect.name.?);
    try std.testing.expect(inspect.json);
    try std.testing.expectError(error.MissingTargetName, parseArgs(&.{"inspect"}));
}

test "target run keeps the child command after the separator" {
    const run = try parseArgs(&.{ "run", "payments-prod", "--", "kubectl", "get", "pods" });
    try std.testing.expectEqual(Command.run, run.command);
    try std.testing.expectEqual(@as(usize, 3), run.child_argv.len);
}
