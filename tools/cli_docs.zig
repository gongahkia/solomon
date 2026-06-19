const std = @import("std");

const max_help_bytes = 128 * 1024;

pub fn main() !void {
    var gpa_impl = std.heap.GeneralPurposeAllocator(.{}){};
    defer _ = gpa_impl.deinit();
    const allocator = gpa_impl.allocator();

    const args = try std.process.argsAlloc(allocator);
    defer std.process.argsFree(allocator, args);
    if (args.len < 3) return error.MissingCliDocsArgs;

    const docs = try generateAlloc(allocator, args[1]);
    defer allocator.free(docs);

    var file = try std.fs.cwd().createFile(args[2], .{ .truncate = true });
    defer file.close();
    try file.writeAll(docs);
}

pub fn generateAlloc(allocator: std.mem.Allocator, shisa_path: []const u8) ![]u8 {
    const root_help = try runRequiredHelp(allocator, &.{ shisa_path, "--help" });
    defer allocator.free(root_help);

    const commands = try parseCommandNamesAlloc(allocator, root_help);
    defer freeCommandNames(allocator, commands);

    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);
    try out.appendSlice(allocator,
        \\# CLI Reference
        \\
        \\Generated from `shisa --help` with `zig build cli-docs`.
        \\
        \\## `shisa`
        \\
    );
    try out.append(allocator, '\n');
    try writeHelpBlock(allocator, &out, root_help);

    var wrote_command_help = false;
    for (commands) |command| {
        const help = try runOptionalHelp(allocator, &.{ shisa_path, command, "--help" }) orelse continue;
        defer allocator.free(help);
        if (std.mem.eql(u8, std.mem.trim(u8, help, " \t\r\n"), std.mem.trim(u8, root_help, " \t\r\n"))) continue;
        if (!wrote_command_help) {
            try out.appendSlice(allocator, "## Command Help\n\n");
            wrote_command_help = true;
        }
        try appendFmt(allocator, &out, "### `shisa {s}`\n\n", .{command});
        try writeHelpBlock(allocator, &out, help);
    }

    if (!wrote_command_help) {
        try out.appendSlice(allocator, "## Command Help\n\nNo command-specific help is currently exposed.\n");
    }

    const docs = try out.toOwnedSlice(allocator);
    return singleTrailingNewlineAlloc(allocator, docs);
}

fn singleTrailingNewlineAlloc(allocator: std.mem.Allocator, docs: []u8) ![]u8 {
    errdefer allocator.free(docs);
    const trimmed = std.mem.trimRight(u8, docs, "\n");
    if (trimmed.len + 1 == docs.len) return docs;
    const normalized = try allocator.alloc(u8, trimmed.len + 1);
    @memcpy(normalized[0..trimmed.len], trimmed);
    normalized[trimmed.len] = '\n';
    allocator.free(docs);
    return normalized;
}

fn runRequiredHelp(allocator: std.mem.Allocator, argv: []const []const u8) ![]u8 {
    const result = try std.process.Child.run(.{
        .allocator = allocator,
        .argv = argv,
        .max_output_bytes = max_help_bytes,
    });
    defer allocator.free(result.stderr);
    if (!exitedZero(result.term)) {
        allocator.free(result.stdout);
        return error.HelpCommandFailed;
    }
    return result.stdout;
}

fn runOptionalHelp(allocator: std.mem.Allocator, argv: []const []const u8) !?[]u8 {
    const result = try std.process.Child.run(.{
        .allocator = allocator,
        .argv = argv,
        .max_output_bytes = max_help_bytes,
    });
    defer allocator.free(result.stderr);
    if (!exitedZero(result.term) or result.stdout.len == 0) {
        allocator.free(result.stdout);
        return null;
    }
    return result.stdout;
}

fn exitedZero(term: std.process.Child.Term) bool {
    return switch (term) {
        .Exited => |code| code == 0,
        else => false,
    };
}

fn parseCommandNamesAlloc(allocator: std.mem.Allocator, help: []const u8) ![][]u8 {
    var commands: std.ArrayList([]u8) = .empty;
    errdefer freeCommandNames(allocator, commands.items);

    var in_commands = false;
    var lines = std.mem.splitScalar(u8, help, '\n');
    while (lines.next()) |raw_line| {
        const line = std.mem.trimRight(u8, raw_line, "\r");
        if (std.mem.eql(u8, std.mem.trim(u8, line, " \t"), "commands:")) {
            in_commands = true;
            continue;
        }
        if (!in_commands) continue;
        if (line.len == 0) break;
        if (leadingSpaces(line) != 2) continue;
        const body = line[2..];
        const end = std.mem.indexOfAny(u8, body, " \t") orelse body.len;
        if (end == 0) continue;
        try commands.append(allocator, try allocator.dupe(u8, body[0..end]));
    }

    return commands.toOwnedSlice(allocator);
}

fn leadingSpaces(line: []const u8) usize {
    var count: usize = 0;
    while (count < line.len and line[count] == ' ') : (count += 1) {}
    return count;
}

fn freeCommandNames(allocator: std.mem.Allocator, commands: []const []u8) void {
    for (commands) |command| allocator.free(command);
    allocator.free(commands);
}

fn writeHelpBlock(allocator: std.mem.Allocator, out: *std.ArrayList(u8), help: []const u8) !void {
    const trimmed = std.mem.trimRight(u8, help, "\n");
    try out.appendSlice(allocator, "```text\n");
    try out.appendSlice(allocator, trimmed);
    try out.appendSlice(allocator, "\n```\n\n");
}

fn appendFmt(allocator: std.mem.Allocator, out: *std.ArrayList(u8), comptime format: []const u8, args: anytype) !void {
    const text = try std.fmt.allocPrint(allocator, format, args);
    defer allocator.free(text);
    try out.appendSlice(allocator, text);
}

test "parses root command names" {
    const help =
        \\usage: shisa <command> [options]
        \\
        \\commands:
        \\  ai            local AI helpers: bench
        \\  import-starship <path>
        \\                translate starship.toml to shisa.toml
        \\  vouch         verify VOUCHES governance file
        \\
        \\options:
        \\  -h, --help    print help
        \\
    ;
    const commands = try parseCommandNamesAlloc(std.testing.allocator, help);
    defer freeCommandNames(std.testing.allocator, commands);
    try std.testing.expectEqual(@as(usize, 3), commands.len);
    try std.testing.expectEqualStrings("ai", commands[0]);
    try std.testing.expectEqualStrings("import-starship", commands[1]);
    try std.testing.expectEqualStrings("vouch", commands[2]);
}
