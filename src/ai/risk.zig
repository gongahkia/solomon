const std = @import("std");
const prod_guard = @import("../daemon/modules/prod_guard.zig");

pub const Risk = enum {
    low,
    medium,
    high,

    pub fn label(self: Risk) []const u8 {
        return switch (self) {
            .low => "low",
            .medium => "medium",
            .high => "high",
        };
    }
};

pub const Explanation = struct {
    risk: Risk,
    source: []const u8,
    pattern: []const u8,
};

pub const default_prompt =
    \\You are shisa risk. Classify one shell command as low, medium, or high risk.
    \\Output only one label: low, medium, or high.
    \\
    \\Rules:
    \\- high means destructive or likely irreversible.
    \\- medium means mutating, privileged, or hard to inspect.
    \\- low means read-only or harmless.
    \\
    \\Command: {{command}}
++ "\n";

pub fn explain(command: []const u8) Explanation {
    if (prod_guard.destructivePattern(command)) |pattern| {
        return .{ .risk = .high, .source = "rules", .pattern = pattern };
    }
    if (isBorderline(command)) return .{ .risk = .medium, .source = "rules", .pattern = "borderline" };
    return .{ .risk = .low, .source = "rules", .pattern = "-" };
}

pub fn outputAlloc(allocator: std.mem.Allocator, command: []const u8) ![]u8 {
    const result = explain(command);
    return std.fmt.allocPrint(allocator, "risk: {s}\nsource: {s}\npattern: {s}\n", .{ result.risk.label(), result.source, result.pattern });
}

pub fn outputExplanationAlloc(allocator: std.mem.Allocator, result: Explanation) ![]u8 {
    return std.fmt.allocPrint(allocator, "risk: {s}\nsource: {s}\npattern: {s}\n", .{ result.risk.label(), result.source, result.pattern });
}

pub fn promptWithCommandAlloc(allocator: std.mem.Allocator, command: []const u8) ![]u8 {
    const marker = "{{command}}";
    if (std.mem.indexOf(u8, default_prompt, marker)) |index| {
        var out: std.ArrayList(u8) = .empty;
        errdefer out.deinit(allocator);
        try out.appendSlice(allocator, default_prompt[0..index]);
        try out.appendSlice(allocator, command);
        try out.appendSlice(allocator, default_prompt[index + marker.len ..]);
        return out.toOwnedSlice(allocator);
    }
    return std.fmt.allocPrint(allocator, "{s}\nCommand: {s}\n", .{ default_prompt, command });
}

pub fn parseSlmRisk(raw: []const u8) ?Risk {
    const trimmed = std.mem.trim(u8, raw, " \t\r\n.:-`\"'");
    if (startsWithIgnoreCase(trimmed, "low")) return .low;
    if (startsWithIgnoreCase(trimmed, "medium")) return .medium;
    if (startsWithIgnoreCase(trimmed, "high")) return .high;
    return null;
}

fn startsWithIgnoreCase(value: []const u8, prefix: []const u8) bool {
    if (value.len < prefix.len) return false;
    return std.ascii.eqlIgnoreCase(value[0..prefix.len], prefix);
}

fn isBorderline(command: []const u8) bool {
    if (std.mem.indexOfAny(u8, command, "|;&><`") != null) return true;
    if (std.mem.indexOf(u8, command, "$(") != null) return true;
    var tokens = std.mem.tokenizeAny(u8, command, " \t\r\n");
    const first = tokens.next() orelse return false;
    inline for (.{ "sudo", "chmod", "chown", "mv", "cp", "rsync", "find", "xargs", "kill", "pkill" }) |name| {
        if (std.mem.eql(u8, first, name)) return true;
    }
    return false;
}

test "explains risk with prod guard blocklist" {
    const destructive = explain("rm -rf /tmp/x");
    try std.testing.expectEqual(Risk.high, destructive.risk);
    try std.testing.expectEqualStrings("rm -rf", destructive.pattern);

    const safe = explain("kubectl get pods");
    try std.testing.expectEqual(Risk.low, safe.risk);
    try std.testing.expectEqualStrings("-", safe.pattern);

    const borderline = explain("sudo systemctl status sshd");
    try std.testing.expectEqual(Risk.medium, borderline.risk);
    try std.testing.expectEqualStrings("borderline", borderline.pattern);
}

test "renders risk output" {
    const output = try outputAlloc(std.testing.allocator, "terraform destroy");
    defer std.testing.allocator.free(output);
    try std.testing.expectEqualStrings("risk: high\nsource: rules\npattern: terraform destroy\n", output);
}

test "parses slm risk labels" {
    try std.testing.expectEqual(Risk.low, parseSlmRisk("low\n").?);
    try std.testing.expectEqual(Risk.medium, parseSlmRisk("Medium risk").?);
    try std.testing.expectEqual(Risk.high, parseSlmRisk("HIGH").?);
    try std.testing.expect(parseSlmRisk("unknown") == null);
}
