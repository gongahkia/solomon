const std = @import("std");
const explain = @import("explain.zig");
const nextcmd = @import("nextcmd.zig");
const nl2cmd = @import("nl2cmd.zig");

const fixture_path = "test/fixtures/ai/prompt-regression.json";

const PromptRegressionCase = struct {
    kind: []const u8,
    input: []const u8 = "",
    shell: []const u8 = "",
    cwd: []const u8 = "",
    last_command: []const u8 = "",
    last_exit: i32 = 0,
    history: []const u8 = "",
    raw: []const u8,
    expected: []const u8,
};

pub fn runFixture(allocator: std.mem.Allocator, path: []const u8) !usize {
    const source = try std.fs.cwd().readFileAlloc(allocator, path, 256 * 1024);
    defer allocator.free(source);
    var parsed = try std.json.parseFromSlice([]PromptRegressionCase, allocator, source, .{ .ignore_unknown_fields = true });
    defer parsed.deinit();
    for (parsed.value) |case| try runCase(allocator, case);
    return parsed.value.len;
}

fn runCase(allocator: std.mem.Allocator, case: PromptRegressionCase) !void {
    if (std.mem.eql(u8, case.kind, "explain")) return runExplainCase(allocator, case);
    if (std.mem.eql(u8, case.kind, "nextcmd")) return runNextcmdCase(allocator, case);
    if (std.mem.eql(u8, case.kind, "nl2cmd")) return runNl2cmdCase(allocator, case);
    return error.UnknownPromptRegressionKind;
}

fn runExplainCase(allocator: std.mem.Allocator, case: PromptRegressionCase) !void {
    const flags = try explain.flagContextAlloc(allocator, case.input);
    defer allocator.free(flags);
    const prompt = try explain.promptWithInputAlloc(allocator, explain.default_prompt, case.input, flags);
    defer allocator.free(prompt);
    try expectContains(prompt, case.input);
    try expectContains(prompt, flags);

    const cleaned = try explain.cleanExplanationAlloc(allocator, case.raw);
    defer allocator.free(cleaned);
    try std.testing.expectEqualStrings(case.expected, cleaned);
}

fn runNextcmdCase(allocator: std.mem.Allocator, case: PromptRegressionCase) !void {
    const context = try nextcmd.buildContextAlloc(allocator, .{
        .cwd = case.cwd,
        .last_command = case.last_command,
        .last_exit = case.last_exit,
        .history_source = case.history,
        .history_limit = 20,
    });
    defer allocator.free(context);
    const prompt = try nextcmd.promptWithContextAlloc(allocator, nextcmd.default_prompt, context);
    defer allocator.free(prompt);
    try expectContains(prompt, case.cwd);
    try expectContains(prompt, case.last_command);

    const cleaned = try nextcmd.cleanSuggestionAlloc(allocator, case.raw);
    defer allocator.free(cleaned);
    try std.testing.expectEqualStrings(case.expected, cleaned);
}

fn runNl2cmdCase(allocator: std.mem.Allocator, case: PromptRegressionCase) !void {
    const request = nl2cmd.detectInput(case.input) orelse return error.MissingPromptRegressionInput;
    const prompt = try nl2cmd.promptWithInputAlloc(allocator, nl2cmd.default_prompt, .{
        .shell = case.shell,
        .cwd = case.cwd,
        .request = request,
    });
    defer allocator.free(prompt);
    try expectContains(prompt, case.shell);
    try expectContains(prompt, request);

    const cleaned = try nl2cmd.cleanCommandAlloc(allocator, case.raw);
    defer allocator.free(cleaned);
    try std.testing.expectEqualStrings(case.expected, cleaned);
}

fn expectContains(haystack: []const u8, needle: []const u8) !void {
    if (needle.len == 0) return;
    try std.testing.expect(std.mem.indexOf(u8, haystack, needle) != null);
}

test "prompt regression fixture snapshots cleaned model outputs" {
    try std.testing.expectEqual(@as(usize, 3), try runFixture(std.testing.allocator, fixture_path));
}
