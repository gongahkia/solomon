const std = @import("std");
const common = @import("common.zig");

const ImportPlan = common.ImportPlan;
const StarshipImport = common.StarshipImport;
const max_config_bytes = common.max_config_bytes;
const parseImportArgs = common.parseImportArgs;
const applyImportPlan = common.applyImportPlan;
const collectUnmappedKeys = common.collectUnmappedKeys;
const appendModule = common.appendModule;
const mapStarshipModule = common.mapStarshipModule;
const renderImportedConfigAlloc = common.renderImportedConfigAlloc;

pub fn importStarshipCmd(allocator: std.mem.Allocator, args: []const []const u8) !void {
    const options = try parseImportArgs(args, true);

    const source = try std.fs.cwd().readFileAlloc(allocator, options.source_path.?, max_config_bytes);
    defer allocator.free(source);

    var plan = try importStarshipPlanAlloc(allocator, source);
    defer plan.deinit(allocator);
    try applyImportPlan(allocator, &plan, options);
}

fn importStarshipAlloc(allocator: std.mem.Allocator, source: []const u8) ![]u8 {
    var imported = StarshipImport{};
    defer imported.deinit(allocator);

    if (try starshipFormatAlloc(allocator, source)) |format| {
        defer allocator.free(format);
        try scanStarshipFormat(allocator, format, &imported);
    } else {
        try scanStarshipTables(allocator, source, &imported);
    }

    if (imported.modules.items.len == 0) {
        inline for (.{ .cwd, .git_branch, .language_versions, .exit_status, .jobs, .cmd_duration, .user_host }) |module_id| {
            try appendModule(allocator, &imported, module_id);
        }
    }

    return renderImportedConfigAlloc(allocator, imported);
}

fn importStarshipPlanAlloc(allocator: std.mem.Allocator, source: []const u8) !ImportPlan {
    const output = try importStarshipAlloc(allocator, source);
    var plan = ImportPlan{
        .target_toml = output,
        .source_name = "Starship",
        .docs_path = "docs/migration-starship.md",
    };
    errdefer plan.deinit(allocator);
    try collectUnmappedKeys(allocator, &plan);
    return plan;
}

fn starshipFormatAlloc(allocator: std.mem.Allocator, source: []const u8) !?[]u8 {
    var offset: usize = 0;
    while (offset <= source.len) {
        const rest = source[offset..];
        const line_len = std.mem.indexOfScalar(u8, rest, '\n') orelse rest.len;
        const line = rest[0..line_len];
        const trimmed = std.mem.trim(u8, line, " \t\r");
        if (trimmed.len != 0 and trimmed[0] == '[') return null;
        if (std.mem.startsWith(u8, trimmed, "format")) {
            const eq_index = std.mem.indexOfScalar(u8, trimmed, '=') orelse return null;
            const value = std.mem.trim(u8, trimmed[eq_index + 1 ..], " \t\r");
            return parseTomlStringAlloc(allocator, value);
        }
        offset += line_len + 1;
        if (offset > source.len) break;
    }
    return null;
}

fn parseTomlStringAlloc(allocator: std.mem.Allocator, value: []const u8) !?[]u8 {
    if (value.len >= 6 and std.mem.startsWith(u8, value, "\"\"\"") and std.mem.endsWith(u8, value, "\"\"\"")) {
        return try allocator.dupe(u8, value[3 .. value.len - 3]);
    }
    if (value.len < 2 or value[0] != '"') return null;

    var out: std.ArrayList(u8) = .empty;
    errdefer out.deinit(allocator);

    var index: usize = 1;
    while (index < value.len) : (index += 1) {
        const byte = value[index];
        if (byte == '"') return try out.toOwnedSlice(allocator);
        if (byte == '\\') {
            index += 1;
            if (index >= value.len) return null;
            switch (value[index]) {
                '"' => try out.append(allocator, '"'),
                '\\' => try out.append(allocator, '\\'),
                'n' => try out.append(allocator, '\n'),
                'r' => try out.append(allocator, '\r'),
                't' => try out.append(allocator, '\t'),
                else => try out.append(allocator, value[index]),
            }
        } else {
            try out.append(allocator, byte);
        }
    }
    return null;
}

fn scanStarshipFormat(allocator: std.mem.Allocator, format: []const u8, imported: *StarshipImport) !void {
    var index: usize = 0;
    while (index < format.len) : (index += 1) {
        if (format[index] != '$') continue;
        index += 1;
        const start = index;
        while (index < format.len and isStarshipModuleByte(format[index])) : (index += 1) {}
        if (index == start) continue;
        try mapStarshipModule(allocator, format[start..index], imported);
        index -= 1;
    }
}

fn scanStarshipTables(allocator: std.mem.Allocator, source: []const u8, imported: *StarshipImport) !void {
    var offset: usize = 0;
    while (offset <= source.len) {
        const rest = source[offset..];
        const line_len = std.mem.indexOfScalar(u8, rest, '\n') orelse rest.len;
        const line = rest[0..line_len];
        const trimmed = std.mem.trim(u8, line, " \t\r");
        if (trimmed.len > 2 and trimmed[0] == '[' and trimmed[trimmed.len - 1] == ']') {
            const name = std.mem.trim(u8, trimmed[1 .. trimmed.len - 1], " \t\r");
            if (!std.mem.startsWith(u8, name, "[") and std.mem.indexOfScalar(u8, name, '.') == null) {
                try mapStarshipModule(allocator, name, imported);
            }
        }
        offset += line_len + 1;
        if (offset > source.len) break;
    }
}

fn isStarshipModuleByte(byte: u8) bool {
    return std.ascii.isAlphanumeric(byte) or byte == '_';
}

test "imports starship format into shisa modules" {
    const source =
        \\format = "$directory$git_branch$git_status$python$nodejs$status$jobs$cmd_duration$hostname$time$character"
        \\
    ;
    const output = try importStarshipAlloc(std.testing.allocator, source);
    defer std.testing.allocator.free(output);

    try std.testing.expect(std.mem.indexOf(u8, output, "modules = [\"cwd\", \"git_branch\", \"language_versions\", \"exit_status\", \"jobs\", \"cmd_duration\", \"user_host\", \"time\"]") != null);
    try std.testing.expect(std.mem.indexOf(u8, output, "detect = [\"python\", \"node\"]") != null);
    try std.testing.expect(std.mem.indexOf(u8, output, "[modules.time]") != null);
}

test "imports starship table fallback and records unsupported modules" {
    const source =
        \\[directory]
        \\[aws]
        \\[git_branch]
        \\
    ;
    const output = try importStarshipAlloc(std.testing.allocator, source);
    defer std.testing.allocator.free(output);

    try std.testing.expect(std.mem.indexOf(u8, output, "modules = [\"cwd\", \"git_branch\"]") != null);
    try std.testing.expect(std.mem.indexOf(u8, output, "Unsupported Starship modules: aws") != null);
}
