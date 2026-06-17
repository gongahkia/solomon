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
++ "\n";

pub const PromptInput = struct {
    shell: []const u8 = "",
    cwd: []const u8 = "",
    request: []const u8,
};

pub const Confidence = enum {
    low,
    medium,
    high,

    pub fn label(self: Confidence) []const u8 {
        return switch (self) {
            .low => "low",
            .medium => "medium",
            .high => "high",
        };
    }
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

pub fn commandConfidence(command: []const u8) Confidence {
    if (hasShellControl(command)) return .low;
    var tokens = std.mem.tokenizeAny(u8, command, " \t\r\n");
    const first = tokens.next() orelse return .low;
    if (isReadOnlyCommand(first)) return .high;
    return .medium;
}

pub fn candidateOutputAlloc(allocator: std.mem.Allocator, command: []const u8) ![]u8 {
    return std.fmt.allocPrint(allocator, "candidate: {s}\nconfidence: {s}\nconfirm: required\n", .{ command, commandConfidence(command).label() });
}

fn hasShellControl(command: []const u8) bool {
    return std.mem.indexOfAny(u8, command, "|;&><`") != null or
        std.mem.indexOf(u8, command, "$(") != null;
}

fn isReadOnlyCommand(command: []const u8) bool {
    inline for (.{ "ls", "pwd", "git", "rg", "grep", "find", "du", "df", "cat", "head", "tail", "sed", "awk", "ps", "wc", "sort", "uniq" }) |name| {
        if (std.mem.eql(u8, command, name)) return true;
    }
    return false;
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

test "scores and renders candidates" {
    try std.testing.expectEqual(Confidence.high, commandConfidence("ls -lhS"));
    try std.testing.expectEqual(Confidence.low, commandConfidence("cat file | grep x"));
    const output = try candidateOutputAlloc(std.testing.allocator, "ls -lhS");
    defer std.testing.allocator.free(output);
    try std.testing.expectEqualStrings("candidate: ls -lhS\nconfidence: high\nconfirm: required\n", output);
}
