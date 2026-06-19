const std = @import("std");

pub const Input = struct {
    last_command: []const u8 = "",
    stderr: []const u8 = "",
    exit_code: i32 = 1,
};

pub const Suggestion = struct {
    rule_id: []const u8,
    command: []const u8,
};

const Rule = struct {
    id: []const u8,
    command_prefix: []const u8 = "",
    stderr_needles: []const []const u8,
    suggestion: []const u8,
};

const rules = [_]Rule{
    .{
        .id = "stale-i18n-catalog",
        .stderr_needles = &.{ "i18n/", "differ" },
        .suggestion = "zig build i18n-extract",
    },
    .{
        .id = "stale-cli-docs",
        .stderr_needles = &.{ "docs/cli.md", "differ" },
        .suggestion = "zig build cli-docs",
    },
    .{
        .id = "stale-plugin-api-docs",
        .stderr_needles = &.{ "docs/plugin-api.md", "differ" },
        .suggestion = "zig build plugin-api-docs",
    },
    .{
        .id = "stale-protocol-schema",
        .stderr_needles = &.{ "docs/protocol/v1.schema.json", "differ" },
        .suggestion = "zig build schema",
    },
    .{
        .id = "git-not-repo",
        .stderr_needles = &.{"fatal: not a git repository"},
        .suggestion = "git status --show-toplevel",
    },
    .{
        .id = "port-in-use",
        .stderr_needles = &.{"address already in use"},
        .suggestion = "lsof -nP -iTCP -sTCP:LISTEN",
    },
    .{
        .id = "zig-test-summary",
        .command_prefix = "zig build test",
        .stderr_needles = &.{"Build Summary:"},
        .suggestion = "zig build test --summary all",
    },
};

pub fn suggest(input: Input) ?Suggestion {
    if (input.exit_code == 0) return null;
    for (rules) |rule| {
        if (rule.command_prefix.len > 0 and !startsWithToken(input.last_command, rule.command_prefix)) continue;
        if (!containsAllIgnoreCase(input.stderr, rule.stderr_needles)) continue;
        return .{
            .rule_id = rule.id,
            .command = rule.suggestion,
        };
    }
    return null;
}

pub fn formatHintAlloc(allocator: std.mem.Allocator, suggestion: Suggestion) ![]u8 {
    return std.fmt.allocPrint(allocator, "shisa: try `{s}`?\n", .{suggestion.command});
}

fn startsWithToken(value: []const u8, prefix: []const u8) bool {
    const trimmed = std.mem.trim(u8, value, " \t\r\n");
    if (!std.mem.startsWith(u8, trimmed, prefix)) return false;
    return trimmed.len == prefix.len or std.ascii.isWhitespace(trimmed[prefix.len]);
}

fn containsAllIgnoreCase(haystack: []const u8, needles: []const []const u8) bool {
    for (needles) |needle| {
        if (!containsIgnoreCase(haystack, needle)) return false;
    }
    return true;
}

fn containsIgnoreCase(haystack: []const u8, needle: []const u8) bool {
    if (needle.len == 0) return true;
    if (needle.len > haystack.len) return false;
    var index: usize = 0;
    while (index + needle.len <= haystack.len) : (index += 1) {
        if (asciiEqIgnoreCase(haystack[index .. index + needle.len], needle)) return true;
    }
    return false;
}

fn asciiEqIgnoreCase(left: []const u8, right: []const u8) bool {
    if (left.len != right.len) return false;
    for (left, right) |a, b| {
        if (std.ascii.toLower(a) != std.ascii.toLower(b)) return false;
    }
    return true;
}

test "suggests stale i18n catalog fix" {
    const suggestion = suggest(.{
        .exit_code = 1,
        .last_command = "zig build test",
        .stderr = "i18n/shisa.pot zig-out/shisa.pot differ: char 1",
    }).?;
    try std.testing.expectEqualStrings("stale-i18n-catalog", suggestion.rule_id);
    try std.testing.expectEqualStrings("zig build i18n-extract", suggestion.command);
}

test "suggests test summary for zig test failures" {
    const suggestion = suggest(.{
        .exit_code = 1,
        .last_command = "zig build test --seed 1",
        .stderr = "Build Summary: 166/168 steps succeeded; 1 failed",
    }).?;
    try std.testing.expectEqualStrings("zig-test-summary", suggestion.rule_id);
    try std.testing.expectEqualStrings("zig build test --summary all", suggestion.command);
}

test "formats one-line hint" {
    const hint = try formatHintAlloc(std.testing.allocator, .{
        .rule_id = "port-in-use",
        .command = "lsof -nP -iTCP -sTCP:LISTEN",
    });
    defer std.testing.allocator.free(hint);
    try std.testing.expectEqualStrings("shisa: try `lsof -nP -iTCP -sTCP:LISTEN`?\n", hint);
}

test "does not suggest on success or no match" {
    try std.testing.expect(suggest(.{ .exit_code = 0, .stderr = "docs/cli.md differ" }) == null);
    try std.testing.expect(suggest(.{ .exit_code = 1, .stderr = "unmatched" }) == null);
}
