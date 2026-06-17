const std = @import("std");
const types = @import("types.zig");

pub const header_bytes = 4;

pub const FrameError = error{
    LengthMismatch,
    Oversize,
    Truncated,
};

pub fn encodeAlloc(allocator: std.mem.Allocator, payload: []const u8) ![]u8 {
    if (payload.len > types.max_frame_bytes) return error.Oversize;

    const frame = try allocator.alloc(u8, header_bytes + payload.len);
    std.mem.writeInt(u32, frame[0..header_bytes], @as(u32, @intCast(payload.len)), .big);
    @memcpy(frame[header_bytes..], payload);
    return frame;
}

pub fn decode(frame: []const u8) FrameError![]const u8 {
    if (frame.len < header_bytes) return error.Truncated;

    const payload_len = std.mem.readInt(u32, frame[0..header_bytes], .big);
    if (payload_len > types.max_frame_bytes) return error.Oversize;

    const total_len = header_bytes + @as(usize, payload_len);
    if (frame.len < total_len) return error.Truncated;
    if (frame.len != total_len) return error.LengthMismatch;

    return frame[header_bytes..total_len];
}

test "roundtrips payload" {
    const allocator = std.testing.allocator;
    const payload = "{\"cwd\":\"/tmp\"}";
    const encoded = try encodeAlloc(allocator, payload);
    defer allocator.free(encoded);

    const decoded = try decode(encoded);
    try std.testing.expectEqualStrings(payload, decoded);
}

test "rejects malformed frames" {
    try std.testing.expectError(error.Truncated, decode(&.{ 0, 0, 0 }));
    try std.testing.expectError(error.Truncated, decode(&.{ 0, 0, 0, 4, 'o', 'k' }));
    try std.testing.expectError(error.LengthMismatch, decode(&.{ 0, 0, 0, 1, 'o', 'k' }));
    try std.testing.expectError(error.Oversize, decode(&.{ 0, 16, 0, 1 }));
}

test "fuzz-style random payload roundtrip" {
    const allocator = std.testing.allocator;
    var prng = std.Random.DefaultPrng.init(0x5158495341);
    const random = prng.random();
    var payload: [1024]u8 = undefined;

    for (0..256) |_| {
        const len = random.intRangeAtMost(usize, 0, payload.len);
        random.bytes(payload[0..len]);

        const encoded = try encodeAlloc(allocator, payload[0..len]);
        defer allocator.free(encoded);

        const decoded = try decode(encoded);
        try std.testing.expectEqualSlices(u8, payload[0..len], decoded);
    }
}

test "roundtrips boundary payload sizes" {
    const allocator = std.testing.allocator;
    const sizes = [_]usize{ 0, 1, header_bytes, 1024, @as(usize, types.max_frame_bytes) };

    for (sizes) |size| {
        const payload = try allocator.alloc(u8, size);
        defer allocator.free(payload);
        @memset(payload, 0xa5);

        const encoded = try encodeAlloc(allocator, payload);
        defer allocator.free(encoded);

        try std.testing.expectEqual(@as(usize, header_bytes + size), encoded.len);
        try std.testing.expectEqual(@as(u32, @intCast(size)), std.mem.readInt(u32, encoded[0..header_bytes], .big));
        try std.testing.expectEqualSlices(u8, payload, try decode(encoded));
    }
}

test "detects corrupted length headers" {
    const allocator = std.testing.allocator;
    const encoded = try encodeAlloc(allocator, "abcd");
    defer allocator.free(encoded);

    var short = try allocator.dupe(u8, encoded);
    defer allocator.free(short);
    std.mem.writeInt(u32, short[0..header_bytes], 3, .big);
    try std.testing.expectError(error.LengthMismatch, decode(short));

    var long = try allocator.dupe(u8, encoded);
    defer allocator.free(long);
    std.mem.writeInt(u32, long[0..header_bytes], 5, .big);
    try std.testing.expectError(error.Truncated, decode(long));

    var oversized = try allocator.dupe(u8, encoded);
    defer allocator.free(oversized);
    std.mem.writeInt(u32, oversized[0..header_bytes], types.max_frame_bytes + 1, .big);
    try std.testing.expectError(error.Oversize, decode(oversized));
}

test "fuzz decoder invariants" {
    return std.testing.fuzz({}, fuzzDecode, .{
        .corpus = &.{
            "",
            "\x00\x00\x00\x00",
            "\x00\x00\x00\x01x",
            "\x00\x10\x00\x01",
        },
    });
}

fn fuzzDecode(_: void, input: []const u8) !void {
    const payload = decode(input) catch |err| switch (err) {
        error.Truncated, error.LengthMismatch, error.Oversize => return,
    };
    try std.testing.expect(input.len >= header_bytes);
    const payload_len = std.mem.readInt(u32, input[0..header_bytes], .big);
    try std.testing.expect(payload_len <= types.max_frame_bytes);
    try std.testing.expectEqual(header_bytes + @as(usize, payload_len), input.len);
    try std.testing.expectEqualSlices(u8, input[header_bytes..], payload);
}
