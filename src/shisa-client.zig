const std = @import("std");
const builtin = @import("builtin");
const frame = @import("proto/frame.zig");
const types = @import("proto/types.zig");

pub fn requestAlloc(allocator: std.mem.Allocator, socket_path: []const u8, payload: []const u8) ![]u8 {
    if (builtin.os.tag == .windows) return requestNamedPipeAlloc(allocator, socket_path, payload);

    var stream = try std.net.connectUnixSocket(socket_path);
    defer stream.close();

    const encoded = try frame.encodeAlloc(allocator, payload);
    defer allocator.free(encoded);
    const file = std.fs.File{ .handle = stream.handle };
    try writeAllFile(file, encoded);

    return readFrameFromFileAlloc(allocator, file);
}

fn requestNamedPipeAlloc(allocator: std.mem.Allocator, pipe_path: []const u8, payload: []const u8) ![]u8 {
    var pipe = try std.fs.openFileAbsolute(pipe_path, .{ .mode = .read_write });
    defer pipe.close();

    const encoded = try frame.encodeAlloc(allocator, payload);
    defer allocator.free(encoded);
    try writeAllFile(pipe, encoded);

    return readFrameFromFileAlloc(allocator, pipe);
}

pub fn readFrameAlloc(allocator: std.mem.Allocator, fd: std.posix.fd_t) ![]u8 {
    return readFrameFromFileAlloc(allocator, .{ .handle = fd });
}

fn readFrameFromFileAlloc(allocator: std.mem.Allocator, file: std.fs.File) ![]u8 {
    var header: [frame.header_bytes]u8 = undefined;
    try readExactFile(file, &header);

    const payload_len = std.mem.readInt(u32, &header, .big);
    if (payload_len > types.max_frame_bytes) return error.Oversize;

    const payload = try allocator.alloc(u8, payload_len);
    errdefer allocator.free(payload);
    try readExactFile(file, payload);
    return payload;
}

pub fn writeAll(fd: std.posix.fd_t, bytes: []const u8) !void {
    try writeAllFile(.{ .handle = fd }, bytes);
}

fn writeAllFile(file: std.fs.File, bytes: []const u8) !void {
    var remaining = bytes;
    while (remaining.len > 0) {
        const written = try file.write(remaining);
        remaining = remaining[written..];
    }
}

fn readExactFile(file: std.fs.File, buffer: []u8) !void {
    var offset: usize = 0;
    while (offset < buffer.len) {
        const n = try file.read(buffer[offset..]);
        if (n == 0) return error.ConnectionClosed;
        offset += n;
    }
}

fn clientTestServer(listener: *std.net.Server) !void {
    const connection = try listener.accept();
    defer connection.stream.close();

    const request = try readFrameAlloc(std.heap.page_allocator, connection.stream.handle);
    defer std.heap.page_allocator.free(request);
    if (!std.mem.eql(u8, request, "ping")) return error.BadRequest;

    const response = try frame.encodeAlloc(std.heap.page_allocator, "ok");
    defer std.heap.page_allocator.free(response);
    try writeAll(connection.stream.handle, response);
}

test "requestAlloc roundtrips framed payload over unix socket" {
    if (builtin.os.tag == .windows) return error.SkipZigTest;

    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-client-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};

    const socket_path = try std.fmt.allocPrint(allocator, "{s}/shisa.sock", .{dir_path});
    defer allocator.free(socket_path);

    try std.fs.cwd().makePath(dir_path);
    const address = try std.net.Address.initUnix(socket_path);
    var listener = try address.listen(.{});
    defer listener.deinit();
    defer std.fs.deleteFileAbsolute(socket_path) catch {};

    const thread = try std.Thread.spawn(.{}, clientTestServer, .{&listener});

    const response = try requestAlloc(allocator, socket_path, "ping");
    defer allocator.free(response);
    try std.testing.expectEqualStrings("ok", response);

    thread.join();
}
