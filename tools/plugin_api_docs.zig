const std = @import("std");

const max_source_bytes = 512 * 1024;
const marker = "/// plugin-api:";

pub fn main() !void {
    var gpa_impl = std.heap.GeneralPurposeAllocator(.{}){};
    defer _ = gpa_impl.deinit();
    const allocator = gpa_impl.allocator();

    const args = try std.process.argsAlloc(allocator);
    defer std.process.argsFree(allocator, args);
    if (args.len < 3) return error.MissingPluginApiDocsArgs;

    const docs = try generateAlloc(allocator, args[2..]);
    defer allocator.free(docs);

    var file = try std.fs.cwd().createFile(args[1], .{ .truncate = true });
    defer file.close();
    try file.writeAll(docs);
}

pub fn generateAlloc(allocator: std.mem.Allocator, source_paths: []const []const u8) ![]u8 {
    var entries: std.ArrayList(Entry) = .empty;
    defer {
        freeEntries(allocator, entries.items);
        entries.deinit(allocator);
    }

    for (source_paths) |path| {
        const source = try std.fs.cwd().readFileAlloc(allocator, path, max_source_bytes);
        defer allocator.free(source);
        try parseSource(allocator, source, &entries);
    }

    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);
    try out.appendSlice(allocator,
        \\# Plugin API Reference
        \\
        \\Generated from `/// plugin-api:` annotations in `src/plugin/*.zig` with `zig build plugin-api-docs`.
        \\
    );
    try out.append(allocator, '\n');

    var current_section: ?[]const u8 = null;
    for (entries.items) |entry| {
        if (current_section == null or !std.mem.eql(u8, current_section.?, entry.section)) {
            if (current_section != null) try out.append(allocator, '\n');
            current_section = entry.section;
            try appendFmt(allocator, &out,
                \\## {s}
                \\
                \\| Name | Type | Default | Notes |
                \\| --- | --- | --- | --- |
                \\
            , .{sectionTitle(entry.section)});
        }
        try appendFmt(allocator, &out, "| `{s}` | {s} | {s} | {s} |\n", .{ entry.name, entry.type_name, entry.default_value, entry.notes });
    }

    return out.toOwnedSlice(allocator);
}

const Entry = struct {
    section: []u8,
    name: []u8,
    type_name: []u8,
    default_value: []u8,
    notes: []u8,
};

fn parseSource(allocator: std.mem.Allocator, source: []const u8, entries: *std.ArrayList(Entry)) !void {
    var lines = std.mem.splitScalar(u8, source, '\n');
    while (lines.next()) |line| {
        const trimmed = std.mem.trimLeft(u8, line, " \t");
        if (!std.mem.startsWith(u8, trimmed, marker)) continue;
        const payload = std.mem.trim(u8, trimmed[marker.len..], " \t\r");
        const entry = try parseEntry(allocator, payload);
        errdefer freeEntry(allocator, entry);
        try entries.append(allocator, entry);
    }
}

fn parseEntry(allocator: std.mem.Allocator, payload: []const u8) !Entry {
    var parts: [5][]const u8 = undefined;
    var count: usize = 0;
    var split = std.mem.splitScalar(u8, payload, '|');
    while (split.next()) |part| {
        if (count == parts.len) return error.InvalidPluginApiAnnotation;
        parts[count] = std.mem.trim(u8, part, " \t\r");
        if (parts[count].len == 0) return error.InvalidPluginApiAnnotation;
        count += 1;
    }
    if (count != parts.len) return error.InvalidPluginApiAnnotation;
    return .{
        .section = try allocator.dupe(u8, parts[0]),
        .name = try allocator.dupe(u8, parts[1]),
        .type_name = try allocator.dupe(u8, parts[2]),
        .default_value = try allocator.dupe(u8, parts[3]),
        .notes = try allocator.dupe(u8, parts[4]),
    };
}

fn freeEntries(allocator: std.mem.Allocator, entries: []Entry) void {
    for (entries) |entry| freeEntry(allocator, entry);
}

fn freeEntry(allocator: std.mem.Allocator, entry: Entry) void {
    allocator.free(entry.section);
    allocator.free(entry.name);
    allocator.free(entry.type_name);
    allocator.free(entry.default_value);
    allocator.free(entry.notes);
}

fn sectionTitle(section: []const u8) []const u8 {
    if (std.mem.eql(u8, section, "manifest")) return "Manifest Fields";
    if (std.mem.eql(u8, section, "capability")) return "Capabilities";
    if (std.mem.eql(u8, section, "entrypoint")) return "Entry Points";
    if (std.mem.eql(u8, section, "gate")) return "Capability Gate";
    if (std.mem.eql(u8, section, "sandbox")) return "Lua Sandbox";
    return section;
}

fn appendFmt(allocator: std.mem.Allocator, out: *std.ArrayList(u8), comptime format: []const u8, args: anytype) !void {
    const text = try std.fmt.allocPrint(allocator, format, args);
    defer allocator.free(text);
    try out.appendSlice(allocator, text);
}

test "parses plugin api annotations" {
    const source =
        \\/// plugin-api: manifest | name | string | required | lowercase id.
        \\pub const x = 1;
        \\    /// plugin-api: capability | exec | false or string array | false | exact allow-list.
        \\
    ;
    var entries: std.ArrayList(Entry) = .empty;
    defer {
        freeEntries(std.testing.allocator, entries.items);
        entries.deinit(std.testing.allocator);
    }
    try parseSource(std.testing.allocator, source, &entries);
    try std.testing.expectEqual(@as(usize, 2), entries.items.len);
    try std.testing.expectEqualStrings("manifest", entries.items[0].section);
    try std.testing.expectEqualStrings("exec", entries.items[1].name);
}
