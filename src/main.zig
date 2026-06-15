const std = @import("std");

pub fn main() !void {
    try std.fs.File.stdout().writeAll("shisa\n");
}

test "smoke" {
    try std.testing.expect(true);
}
