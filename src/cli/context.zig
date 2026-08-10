const std = @import("std");
const cli_util = @import("util.zig");
const client = @import("../shisa-client.zig");
const paths = @import("../daemon/paths.zig");
const proto = @import("../proto/types.zig");

pub const help_text =
    \\usage: shisa context [--socket PATH] [--cwd PATH] [--json]
    \\
    \\Print a JSON snapshot of daemon-cached Git, language, and cloud context.
    \\The API is local and read-only: it never starts probes, reads the environment,
    \\or makes network requests. --json is accepted for explicit scripting use.
    \\
;

const ContextConfig = struct {
    help: bool = false,
    socket_path: ?[]const u8 = null,
    cwd: ?[]const u8 = null,
};

const ContextRequest = struct {
    v: u32 = proto.version,
    op: []const u8 = "context",
    cwd: []const u8,
    request_id: []const u8 = "context-cli",
};

const ErrorEnvelope = struct {
    @"error": ?struct { code: []const u8 } = null,
};

pub fn contextCmd(allocator: std.mem.Allocator, args: []const []const u8) !void {
    const config = try parseArgs(args);
    if (config.help) {
        try std.fs.File.stdout().writeAll(help_text);
        return;
    }

    const cwd = if (config.cwd) |path| path else try std.fs.cwd().realpathAlloc(allocator, ".");
    defer if (config.cwd == null) allocator.free(cwd);
    const socket_path = if (config.socket_path) |path| path else try paths.defaultSocketPath(allocator);
    defer if (config.socket_path == null) allocator.free(socket_path);
    const payload = try proto.encodeAlloc(allocator, ContextRequest{ .cwd = cwd });
    defer allocator.free(payload);

    const response = try client.requestAlloc(allocator, socket_path, payload);
    defer allocator.free(response);
    var parsed = try std.json.parseFromSlice(ErrorEnvelope, allocator, response, .{ .ignore_unknown_fields = true });
    defer parsed.deinit();
    try std.fs.File.stdout().writeAll(response);
    try std.fs.File.stdout().writeAll("\n");
    if (parsed.value.@"error" != null) return error.ContextRequestFailed;
}

fn parseArgs(args: []const []const u8) !ContextConfig {
    var config: ContextConfig = .{};
    var index: usize = 0;
    while (index < args.len) : (index += 1) {
        const arg = args[index];
        if (std.mem.eql(u8, arg, "--help") or std.mem.eql(u8, arg, "-h")) {
            config.help = true;
        } else if (std.mem.eql(u8, arg, "--socket")) {
            config.socket_path = try cli_util.nextValue(args, &index);
        } else if (std.mem.eql(u8, arg, "--cwd")) {
            config.cwd = try cli_util.nextValue(args, &index);
        } else if (std.mem.eql(u8, arg, "--json")) {
            // JSON is the only output format; keeping the flag makes scripts explicit.
        } else {
            return error.UnknownContextArgument;
        }
    }
    return config;
}

test "context arguments accept socket cwd and json" {
    const config = try parseArgs(&.{ "--socket", "/tmp/shisa.sock", "--cwd", "/repo", "--json" });
    try std.testing.expectEqualStrings("/tmp/shisa.sock", config.socket_path.?);
    try std.testing.expectEqualStrings("/repo", config.cwd.?);
}

test "context arguments reject unknown flags" {
    try std.testing.expectError(error.UnknownContextArgument, parseArgs(&.{"--watch"}));
}

test "context request is compact JSON" {
    const payload = try proto.encodeAlloc(std.testing.allocator, ContextRequest{ .cwd = "/repo" });
    defer std.testing.allocator.free(payload);
    try std.testing.expectEqualStrings("{\"v\":2,\"op\":\"context\",\"cwd\":\"/repo\",\"request_id\":\"context-cli\"}", payload);
}
