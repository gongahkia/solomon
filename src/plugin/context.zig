const std = @import("std");

pub const max_announce_bytes: usize = 4096;

pub const Function = enum {
    announce,
};

pub fn parseFunctionName(name: []const u8) ?Function {
    if (std.mem.eql(u8, name, "ctx:announce") or std.mem.eql(u8, name, "announce")) return .announce;
    return null;
}

pub fn validateFunctionInput(function: Function, input: []const u8) !void {
    return switch (function) {
        .announce => validateAnnounce(input),
    };
}

pub fn validateAnnounce(input: []const u8) !void {
    if (input.len > max_announce_bytes) return error.ContextInputTooLarge;
    if (!std.unicode.utf8ValidateSlice(input)) return error.InvalidContextUtf8;
    for (input) |byte| {
        if (byte == 0x7f or (byte < 0x20 and byte != '\n' and byte != '\t')) return error.InvalidContextControl;
    }
}

test "parses ctx function names" {
    try std.testing.expectEqual(Function.announce, parseFunctionName("ctx:announce").?);
    try std.testing.expectEqual(Function.announce, parseFunctionName("announce").?);
    try std.testing.expect(parseFunctionName("ctx:exec") == null);
}

test "validates ctx announce input" {
    try validateFunctionInput(.announce, "risk tier prod\n");
    try std.testing.expectError(error.InvalidContextControl, validateFunctionInput(.announce, "bad\x00message"));
    try std.testing.expectError(error.InvalidContextUtf8, validateFunctionInput(.announce, "\xff"));

    const too_large = try std.testing.allocator.alloc(u8, max_announce_bytes + 1);
    defer std.testing.allocator.free(too_large);
    @memset(too_large, 'x');
    try std.testing.expectError(error.ContextInputTooLarge, validateFunctionInput(.announce, too_large));
}

test "fuzz ctx bridge function inputs" {
    return std.testing.fuzz({}, fuzzContextFunctionInput, .{
        .corpus = &.{
            "",
            "risk tier prod",
            "line\nnext",
            "\x00",
            "\x1b[31m",
            "\xff",
        },
    });
}

fn fuzzContextFunctionInput(_: void, input: []const u8) !void {
    if (input.len > max_announce_bytes + 512) return;
    inline for (std.meta.fields(Function)) |field| {
        const function: Function = @enumFromInt(field.value);
        validateFunctionInput(function, input) catch |err| switch (err) {
            error.ContextInputTooLarge,
            error.InvalidContextUtf8,
            error.InvalidContextControl,
            => {},
            else => return err,
        };
    }
}
