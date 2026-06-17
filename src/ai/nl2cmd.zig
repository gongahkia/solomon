const std = @import("std");

pub const prefix = "?? ";
pub const default_prompt_path = "prompts/nl2cmd.md";
pub const default_prompt =
    \\You are shisa nl2cmd. Convert a natural-language request into one safe shell command.
    \\
    \\Rules:
    \\- Output only the command.
    \\- Do not include explanations, markdown, comments, or surrounding quotes.
    \\- Prefer read-only commands unless the request explicitly asks for a write.
    \\- If the request is ambiguous or unsafe, output nothing.
    \\
    \\Shell: {{shell}}
    \\cwd: {{cwd}}
    \\Request: {{request}}
    \\
    \\Examples:
    \\
    \\Shell: zsh
    \\cwd: /repo
    \\Request: show changed files
    \\Suggestion:
    \\git diff --stat
    \\
    \\Shell: bash
    \\cwd: /tmp
    \\Request: list files by size
    \\Suggestion:
    \\ls -lhS
    \\
    \\Shell: zsh
    \\cwd: /repo
    \\Request: delete everything
    \\Suggestion:
++ "\n";

pub const PromptInput = struct {
    shell: []const u8 = "",
    cwd: []const u8 = "",
    request: []const u8,
};

pub fn detectInput(input: []const u8) ?[]const u8 {
    if (!std.mem.startsWith(u8, input, prefix)) return null;
    return std.mem.trim(u8, input[prefix.len..], " \t\r\n");
}

pub fn readDefaultPromptAlloc(allocator: std.mem.Allocator) ![]u8 {
    if (std.fs.cwd().readFileAlloc(allocator, default_prompt_path, 256 * 1024)) |value| return value else |_| {}
    return allocator.dupe(u8, default_prompt);
}

pub fn promptWithInputAlloc(allocator: std.mem.Allocator, template: []const u8, input: PromptInput) ![]u8 {
    const with_shell = try replaceMarkerAlloc(allocator, template, "{{shell}}", input.shell);
    defer allocator.free(with_shell);
    const with_cwd = try replaceMarkerAlloc(allocator, with_shell, "{{cwd}}", input.cwd);
    defer allocator.free(with_cwd);
    return replaceMarkerAlloc(allocator, with_cwd, "{{request}}", input.request);
}

pub fn cleanCommandAlloc(allocator: std.mem.Allocator, raw: []const u8) ![]u8 {
    var lines = std.mem.splitScalar(u8, raw, '\n');
    while (lines.next()) |line| {
        var trimmed = std.mem.trim(u8, line, " \t\r\n");
        if (trimmed.len == 0) continue;
        if (std.mem.startsWith(u8, trimmed, "```")) continue;
        trimmed = std.mem.trim(u8, trimmed, "`");
        if (trimmed.len == 0) continue;
        if (std.mem.startsWith(u8, trimmed, "Suggestion:")) {
            trimmed = std.mem.trim(u8, trimmed["Suggestion:".len..], " \t\r\n`");
            if (trimmed.len == 0) continue;
        }
        if ((trimmed[0] == '"' and trimmed[trimmed.len - 1] == '"') or
            (trimmed[0] == '\'' and trimmed[trimmed.len - 1] == '\''))
        {
            trimmed = std.mem.trim(u8, trimmed[1 .. trimmed.len - 1], " \t\r\n");
        }
        return allocator.dupe(u8, trimmed);
    }
    return allocator.dupe(u8, "");
}

fn replaceMarkerAlloc(allocator: std.mem.Allocator, source: []const u8, marker: []const u8, value: []const u8) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    errdefer out.deinit(allocator);
    var start: usize = 0;
    while (std.mem.indexOf(u8, source[start..], marker)) |relative_index| {
        const index = start + relative_index;
        try out.appendSlice(allocator, source[start..index]);
        try out.appendSlice(allocator, value);
        start = index + marker.len;
    }
    try out.appendSlice(allocator, source[start..]);
    return out.toOwnedSlice(allocator);
}

test "detects nl2cmd prefix" {
    try std.testing.expectEqualStrings("list files", detectInput("?? list files").?);
    try std.testing.expectEqualStrings("", detectInput("?? ").?);
    try std.testing.expect(detectInput("echo ?? list files") == null);
    try std.testing.expect(detectInput(" ?? list files") == null);
}

test "builds nl2cmd prompt" {
    const prompt = try promptWithInputAlloc(std.testing.allocator, "shell={{shell}}\ncwd={{cwd}}\nrequest={{request}}\n", .{
        .shell = "zsh",
        .cwd = "/repo",
        .request = "list files",
    });
    defer std.testing.allocator.free(prompt);
    try std.testing.expectEqualStrings("shell=zsh\ncwd=/repo\nrequest=list files\n", prompt);
}

test "embedded nl2cmd prompt matches checked-in prompt" {
    const prompt = try std.fs.cwd().readFileAlloc(std.testing.allocator, default_prompt_path, 256 * 1024);
    defer std.testing.allocator.free(prompt);
    try std.testing.expectEqualStrings(prompt, default_prompt);
}

test "cleans nl2cmd command" {
    const command = try cleanCommandAlloc(std.testing.allocator, "Suggestion: `ls -lhS`\nextra\n");
    defer std.testing.allocator.free(command);
    try std.testing.expectEqualStrings("ls -lhS", command);
}
