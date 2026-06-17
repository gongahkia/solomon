const std = @import("std");
const prod_guard = @import("../daemon/modules/prod_guard.zig");

pub const Risk = enum {
    low,
    high,

    pub fn label(self: Risk) []const u8 {
        return switch (self) {
            .low => "low",
            .high => "high",
        };
    }
};

pub const Explanation = struct {
    risk: Risk,
    source: []const u8,
    pattern: []const u8,
};

pub fn explain(command: []const u8) Explanation {
    if (prod_guard.destructivePattern(command)) |pattern| {
        return .{ .risk = .high, .source = "rules", .pattern = pattern };
    }
    return .{ .risk = .low, .source = "rules", .pattern = "-" };
}

pub fn outputAlloc(allocator: std.mem.Allocator, command: []const u8) ![]u8 {
    const result = explain(command);
    return std.fmt.allocPrint(allocator, "risk: {s}\nsource: {s}\npattern: {s}\n", .{ result.risk.label(), result.source, result.pattern });
}

test "explains risk with prod guard blocklist" {
    const destructive = explain("rm -rf /tmp/x");
    try std.testing.expectEqual(Risk.high, destructive.risk);
    try std.testing.expectEqualStrings("rm -rf", destructive.pattern);

    const safe = explain("kubectl get pods");
    try std.testing.expectEqual(Risk.low, safe.risk);
    try std.testing.expectEqualStrings("-", safe.pattern);
}

test "renders risk output" {
    const output = try outputAlloc(std.testing.allocator, "terraform destroy");
    defer std.testing.allocator.free(output);
    try std.testing.expectEqualStrings("risk: high\nsource: rules\npattern: terraform destroy\n", output);
}
