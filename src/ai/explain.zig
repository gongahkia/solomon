const std = @import("std");

pub const default_prompt_path = "prompts/explain.md";
pub const default_prompt =
    \\You are shisa explain. Explain one shell command for a terminal prompt UI.
    \\
    \\Rules:
    \\- Keep it concise.
    \\- Explain what the command does.
    \\- Explain each detected flag.
    \\- Mention risk only when relevant.
    \\- Do not suggest running the command.
    \\
    \\Command:
    \\{{command}}
    \\
    \\Detected flags:
    \\{{flags}}
    \\
    \\Output format:
    \\summary: <one sentence>
    \\flags:
    \\- <flag>: <meaning>
    \\risk: <low|medium|high>
++ "\n";

pub fn readDefaultPromptAlloc(allocator: std.mem.Allocator) ![]u8 {
    if (std.fs.cwd().readFileAlloc(allocator, default_prompt_path, 256 * 1024)) |value| return value else |_| {}
    return allocator.dupe(u8, default_prompt);
}

pub fn flagContextAlloc(allocator: std.mem.Allocator, command: []const u8) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    errdefer out.deinit(allocator);
    var tokens = std.mem.tokenizeAny(u8, command, " \t\r\n");
    const executable = tokens.next() orelse return allocator.dupe(u8, "-\n");
    var wrote = false;
    while (tokens.next()) |token| {
        if (!std.mem.startsWith(u8, token, "-") or std.mem.eql(u8, token, "--")) continue;
        if (wrote) try out.append(allocator, '\n');
        wrote = true;
        try out.appendSlice(allocator, "- ");
        try out.appendSlice(allocator, token);
        try out.appendSlice(allocator, ": ");
        try out.appendSlice(allocator, flagMeaning(executable, token));
    }
    if (!wrote) try out.appendSlice(allocator, "-");
    try out.append(allocator, '\n');
    return out.toOwnedSlice(allocator);
}

pub fn promptWithInputAlloc(allocator: std.mem.Allocator, template: []const u8, command: []const u8, flags: []const u8) ![]u8 {
    const with_command = try replaceMarkerAlloc(allocator, template, "{{command}}", command);
    defer allocator.free(with_command);
    return replaceMarkerAlloc(allocator, with_command, "{{flags}}", flags);
}

pub fn cleanExplanationAlloc(allocator: std.mem.Allocator, raw: []const u8) ![]u8 {
    return allocator.dupe(u8, std.mem.trim(u8, raw, " \t\r\n`"));
}

fn flagMeaning(executable: []const u8, flag: []const u8) []const u8 {
    if (std.mem.eql(u8, executable, "ls")) {
        if (std.mem.indexOfScalar(u8, flag, 'l') != null) return "long listing format";
        if (std.mem.indexOfScalar(u8, flag, 'a') != null) return "include hidden files";
        if (std.mem.indexOfScalar(u8, flag, 'S') != null) return "sort by size";
        if (std.mem.indexOfScalar(u8, flag, 'h') != null) return "human-readable sizes";
    }
    if (std.mem.eql(u8, executable, "tar")) {
        if (std.mem.indexOfScalar(u8, flag, 'x') != null) return "extract archive";
        if (std.mem.indexOfScalar(u8, flag, 'f') != null) return "use archive file argument";
    }
    if (std.mem.eql(u8, executable, "rm")) {
        if (std.mem.indexOfScalar(u8, flag, 'r') != null) return "recursive";
        if (std.mem.indexOfScalar(u8, flag, 'f') != null) return "force without prompting";
    }
    if (std.mem.eql(u8, executable, "git")) {
        if (std.mem.eql(u8, flag, "-m")) return "commit message";
        if (std.mem.eql(u8, flag, "-C")) return "run as if started in the given path";
    }
    return "unknown flag";
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

test "embedded explain prompt matches checked-in prompt" {
    const prompt = try std.fs.cwd().readFileAlloc(std.testing.allocator, default_prompt_path, 256 * 1024);
    defer std.testing.allocator.free(prompt);
    try std.testing.expectEqualStrings(prompt, default_prompt);
}

test "builds flag context" {
    const flags = try flagContextAlloc(std.testing.allocator, "ls -lhS");
    defer std.testing.allocator.free(flags);
    try std.testing.expect(std.mem.indexOf(u8, flags, "- -lhS: long listing format") != null);
}

test "builds explain prompt" {
    const prompt = try promptWithInputAlloc(std.testing.allocator, "cmd={{command}}\nflags={{flags}}", "tar -xf app.tar", "- -xf: extract archive\n");
    defer std.testing.allocator.free(prompt);
    try std.testing.expectEqualStrings("cmd=tar -xf app.tar\nflags=- -xf: extract archive\n", prompt);
}
