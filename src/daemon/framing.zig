const std = @import("std");

const header_bytes = 4;
const max_frame_bytes = 1024 * 1024;
pub const interactive_frame_timeout_ms: i32 = 5;

pub fn writeFrame(fd: std.posix.fd_t, payload: []const u8) !void {
    const encoded = try encodeFrameAlloc(std.heap.page_allocator, payload);
    defer std.heap.page_allocator.free(encoded);
    const deadline_ns = std.time.nanoTimestamp() + @as(i128, interactive_frame_timeout_ms) * @as(i128, std.time.ns_per_ms);
    try writeAllWithDeadline(fd, encoded, deadline_ns);
}

pub fn writeFrameFile(file: std.fs.File, payload: []const u8) !void {
    const encoded = try encodeFrameAlloc(std.heap.page_allocator, payload);
    defer std.heap.page_allocator.free(encoded);
    try writeAllFile(file, encoded);
}

pub fn readFrameFromFileAlloc(allocator: std.mem.Allocator, file: std.fs.File) ![]u8 {
    var header: [header_bytes]u8 = undefined;
    try readExactFile(file, &header);
    const payload_len = std.mem.readInt(u32, &header, .big);
    if (payload_len > max_frame_bytes) return error.Oversize;
    const payload = try allocator.alloc(u8, payload_len);
    errdefer allocator.free(payload);
    try readExactFile(file, payload);
    return payload;
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

pub fn readFrameAlloc(allocator: std.mem.Allocator, fd: std.posix.fd_t) ![]u8 {
    var header: [header_bytes]u8 = undefined;
    try readExact(fd, &header);
    const payload_len = std.mem.readInt(u32, &header, .big);
    if (payload_len > max_frame_bytes) return error.Oversize;
    const payload = try allocator.alloc(u8, payload_len);
    errdefer allocator.free(payload);
    try readExact(fd, payload);
    return payload;
}

pub fn readFrameAllocWithTimeout(allocator: std.mem.Allocator, fd: std.posix.fd_t, timeout_ms: i32) ![]u8 {
    if (timeout_ms <= 0) return error.Timeout;
    const deadline_ns = std.time.nanoTimestamp() + @as(i128, timeout_ms) * @as(i128, std.time.ns_per_ms);
    var header: [header_bytes]u8 = undefined;
    try readExactWithDeadline(fd, &header, deadline_ns);
    const payload_len = std.mem.readInt(u32, &header, .big);
    if (payload_len > max_frame_bytes) return error.Oversize;
    const payload = try allocator.alloc(u8, payload_len);
    errdefer allocator.free(payload);
    try readExactWithDeadline(fd, payload, deadline_ns);
    return payload;
}

fn encodeFrameAlloc(allocator: std.mem.Allocator, payload: []const u8) ![]u8 {
    if (payload.len > max_frame_bytes) return error.Oversize;
    const encoded = try allocator.alloc(u8, header_bytes + payload.len);
    std.mem.writeInt(u32, encoded[0..header_bytes], @as(u32, @intCast(payload.len)), .big);
    @memcpy(encoded[header_bytes..], payload);
    return encoded;
}

fn readExact(fd: std.posix.fd_t, buffer: []u8) !void {
    var offset: usize = 0;
    while (offset < buffer.len) {
        const n = try std.posix.read(fd, buffer[offset..]);
        if (n == 0) return error.ConnectionClosed;
        offset += n;
    }
}

fn readExactWithDeadline(fd: std.posix.fd_t, buffer: []u8, deadline_ns: i128) !void {
    var offset: usize = 0;
    while (offset < buffer.len) {
        try waitForFdDeadline(fd, std.posix.POLL.IN, deadline_ns);
        const n = try std.posix.read(fd, buffer[offset..]);
        if (n == 0) return error.ConnectionClosed;
        offset += n;
    }
}

/// Poll before each bounded write. Small chunks avoid a single large blocking
/// write after readiness has been observed.
fn writeAllWithDeadline(fd: std.posix.fd_t, bytes: []const u8, deadline_ns: i128) !void {
    var remaining = bytes;
    while (remaining.len > 0) {
        try waitForFdDeadline(fd, std.posix.POLL.OUT, deadline_ns);
        const chunk_len = @min(remaining.len, 4096);
        const written = try std.posix.write(fd, remaining[0..chunk_len]);
        if (written == 0) return error.ConnectionClosed;
        remaining = remaining[written..];
    }
}

fn waitForFdDeadline(fd: std.posix.fd_t, events: i16, deadline_ns: i128) !void {
    const remaining_ns = deadline_ns - std.time.nanoTimestamp();
    if (remaining_ns <= 0) return error.Timeout;
    const rounded_ms = @divTrunc(remaining_ns + @as(i128, std.time.ns_per_ms) - 1, @as(i128, std.time.ns_per_ms));
    const timeout_ms: i32 = @intCast(@min(rounded_ms, std.math.maxInt(i32)));
    var poll_fds = [_]std.posix.pollfd{.{ .fd = fd, .events = events, .revents = 0 }};
    if (try std.posix.poll(&poll_fds, timeout_ms) == 0) return error.Timeout;
    if ((poll_fds[0].revents & (std.posix.POLL.ERR | std.posix.POLL.NVAL)) != 0) return error.ConnectionClosed;
    if ((poll_fds[0].revents & events) == 0 and (poll_fds[0].revents & std.posix.POLL.HUP) != 0) return error.ConnectionClosed;
}
