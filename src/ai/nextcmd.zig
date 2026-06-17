const std = @import("std");

pub const default_prompt_path = "prompts/nextcmd.md";

pub const ContextInput = struct {
    cwd: []const u8,
    last_command: []const u8 = "",
    last_exit: i32 = 0,
    history_source: []const u8 = "",
    history_limit: usize = 20,
};

pub fn promptWithContextAlloc(allocator: std.mem.Allocator, template: []const u8, context: []const u8) ![]u8 {
    const marker = "{{context}}";
    if (std.mem.indexOf(u8, template, marker)) |index| {
        var out: std.ArrayList(u8) = .empty;
        errdefer out.deinit(allocator);
        try out.appendSlice(allocator, template[0..index]);
        try out.appendSlice(allocator, context);
        try out.appendSlice(allocator, template[index + marker.len ..]);
        return out.toOwnedSlice(allocator);
    }
    return std.fmt.allocPrint(allocator, "{s}\n{s}", .{ template, context });
}

pub fn readDefaultPromptAlloc(allocator: std.mem.Allocator) ![]u8 {
    return std.fs.cwd().readFileAlloc(allocator, default_prompt_path, 256 * 1024);
}

pub fn buildContextAlloc(allocator: std.mem.Allocator, input: ContextInput) ![]u8 {
    const history = try historySliceAlloc(allocator, input.history_source, input.history_limit);
    defer freeStringList(allocator, history);

    var out: std.ArrayList(u8) = .empty;
    errdefer out.deinit(allocator);
    try appendLine(allocator, &out, "cwd", input.cwd);
    try appendIntLine(allocator, &out, "last_exit", input.last_exit);
    try appendLine(allocator, &out, "last_command", input.last_command);
    try out.appendSlice(allocator, "history:\n");
    for (history) |entry| {
        try out.appendSlice(allocator, "- ");
        try out.appendSlice(allocator, entry);
        try out.append(allocator, '\n');
    }
    return out.toOwnedSlice(allocator);
}

pub fn historySliceAlloc(allocator: std.mem.Allocator, source: []const u8, limit: usize) ![][]u8 {
    var items: std.ArrayList([]u8) = .empty;
    errdefer {
        for (items.items) |entry| allocator.free(entry);
        items.deinit(allocator);
    }

    var lines = std.mem.splitScalar(u8, source, '\n');
    while (lines.next()) |raw_line| {
        const parsed = parseHistoryLine(raw_line) orelse continue;
        try items.append(allocator, try allocator.dupe(u8, parsed));
    }
    if (items.items.len <= limit) return items.toOwnedSlice(allocator);

    const start = items.items.len - limit;
    for (items.items[0..start]) |entry| allocator.free(entry);
    const kept = try allocator.dupe([]u8, items.items[start..]);
    items.deinit(allocator);
    return kept;
}

pub fn parseHistoryLine(raw_line: []const u8) ?[]const u8 {
    const line = std.mem.trim(u8, raw_line, " \t\r\n");
    if (line.len == 0) return null;
    if (std.mem.startsWith(u8, line, ": ")) {
        if (std.mem.indexOfScalar(u8, line, ';')) |index| {
            const command = std.mem.trim(u8, line[index + 1 ..], " \t\r\n");
            return if (command.len == 0) null else command;
        }
    }
    if (std.mem.startsWith(u8, line, "- cmd:")) {
        const command = std.mem.trim(u8, line["- cmd:".len..], " \t\r\n\"");
        return if (command.len == 0) null else command;
    }
    return line;
}

fn appendLine(allocator: std.mem.Allocator, out: *std.ArrayList(u8), key: []const u8, value: []const u8) !void {
    try out.appendSlice(allocator, key);
    try out.appendSlice(allocator, ": ");
    try out.appendSlice(allocator, value);
    try out.append(allocator, '\n');
}

fn appendIntLine(allocator: std.mem.Allocator, out: *std.ArrayList(u8), key: []const u8, value: i32) !void {
    const line = try std.fmt.allocPrint(allocator, "{s}: {d}\n", .{ key, value });
    defer allocator.free(line);
    try out.appendSlice(allocator, line);
}

fn freeStringList(allocator: std.mem.Allocator, items: []const []u8) void {
    for (items) |entry| allocator.free(entry);
    allocator.free(items);
}

test "parses shell history lines" {
    try std.testing.expectEqualStrings("git status", parseHistoryLine(": 1710000000:0;git status").?);
    try std.testing.expectEqualStrings("ls -la", parseHistoryLine("ls -la").?);
    try std.testing.expectEqualStrings("cargo test", parseHistoryLine("- cmd: cargo test").?);
    try std.testing.expect(parseHistoryLine("  ") == null);
}

test "builds nextcmd context" {
    const context = try buildContextAlloc(std.testing.allocator, .{
        .cwd = "/repo",
        .last_command = "zig build test",
        .last_exit = 1,
        .history_source = "git status\nzig build test\n",
        .history_limit = 1,
    });
    defer std.testing.allocator.free(context);
    try std.testing.expect(std.mem.indexOf(u8, context, "cwd: /repo\n") != null);
    try std.testing.expect(std.mem.indexOf(u8, context, "last_exit: 1\n") != null);
    try std.testing.expect(std.mem.indexOf(u8, context, "- zig build test\n") != null);
    try std.testing.expect(std.mem.indexOf(u8, context, "- git status\n") == null);
}

test "interpolates prompt context" {
    const prompt = try promptWithContextAlloc(std.testing.allocator, "A\n{{context}}\nB", "cwd: /repo\n");
    defer std.testing.allocator.free(prompt);
    try std.testing.expectEqualStrings("A\ncwd: /repo\n\nB", prompt);
}

test "default nextcmd prompt has context marker" {
    const prompt = try readDefaultPromptAlloc(std.testing.allocator);
    defer std.testing.allocator.free(prompt);
    try std.testing.expect(std.mem.indexOf(u8, prompt, "{{context}}") != null);
    try std.testing.expect(std.mem.indexOf(u8, prompt, "Suggestion:") != null);
}
