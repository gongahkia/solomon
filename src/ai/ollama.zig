const std = @import("std");

pub const default_host = "127.0.0.1";
pub const default_port: u16 = 11434;

pub const Status = struct {
    installed: bool,
    daemon_running: bool,
};

pub fn detect(allocator: std.mem.Allocator) !Status {
    return .{
        .installed = isInstalled(allocator),
        .daemon_running = isDaemonRunning(allocator, default_host, default_port),
    };
}

pub fn isInstalled(allocator: std.mem.Allocator) bool {
    const result = std.process.Child.run(.{
        .allocator = allocator,
        .argv = &.{ "ollama", "--version" },
        .max_output_bytes = 4096,
        .expand_arg0 = .expand,
    }) catch return false;
    defer allocator.free(result.stdout);
    defer allocator.free(result.stderr);
    return switch (result.term) {
        .Exited => |code| code == 0,
        else => false,
    };
}

pub fn isDaemonRunning(allocator: std.mem.Allocator, host: []const u8, port: u16) bool {
    return httpGetOk(allocator, host, port, "/api/tags") catch false;
}

fn httpGetOk(allocator: std.mem.Allocator, host: []const u8, port: u16, path: []const u8) !bool {
    var stream = try std.net.tcpConnectToHost(allocator, host, port);
    defer stream.close();
    const request = try std.fmt.allocPrint(
        allocator,
        "GET {s} HTTP/1.1\r\nHost: {s}:{d}\r\nConnection: close\r\n\r\n",
        .{ path, host, port },
    );
    defer allocator.free(request);
    try stream.writeAll(request);

    var buffer: [512]u8 = undefined;
    const read_len = try stream.read(&buffer);
    if (read_len == 0) return false;
    const status = parseHttpStatus(buffer[0..read_len]) orelse return false;
    return status >= 200 and status < 300;
}

pub fn parseHttpStatus(response: []const u8) ?u16 {
    const line_end = std.mem.indexOf(u8, response, "\r\n") orelse response.len;
    const line = response[0..line_end];
    if (!std.mem.startsWith(u8, line, "HTTP/")) return null;
    var parts = std.mem.splitScalar(u8, line, ' ');
    _ = parts.next() orelse return null;
    const code_text = parts.next() orelse return null;
    return std.fmt.parseInt(u16, code_text, 10) catch null;
}

test "parses http status" {
    try std.testing.expectEqual(@as(?u16, 200), parseHttpStatus("HTTP/1.1 200 OK\r\n"));
    try std.testing.expectEqual(@as(?u16, 404), parseHttpStatus("HTTP/1.1 404 Not Found\r\n"));
    try std.testing.expect(parseHttpStatus("bad") == null);
}
