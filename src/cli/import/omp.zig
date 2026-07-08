const std = @import("std");
const cli_util = @import("../util.zig");
const shisa_config = @import("../../config.zig");
const common = @import("common.zig");

const ImportPlan = common.ImportPlan;
const StarshipImport = common.StarshipImport;
const max_config_bytes = common.max_config_bytes;
const parseImportArgs = common.parseImportArgs;
const applyImportPlan = common.applyImportPlan;
const addSidecarOwned = common.addSidecarOwned;
const collectUnmappedKeys = common.collectUnmappedKeys;
const appendModule = common.appendModule;
const appendRightModule = common.appendRightModule;
const appendUnsupported = common.appendUnsupported;
const containsModule = common.containsModule;
const containsAnyModule = common.containsAnyModule;
const appendLanguage = common.appendLanguage;
const appendTomlString = common.appendTomlString;

pub const OmpSegment = struct {
    kind: ?[]u8 = null,
    template: ?[]u8 = null,
    foreground: ?[]u8 = null,
    background: ?[]u8 = null,

    fn deinit(self: OmpSegment, allocator: std.mem.Allocator) void {
        if (self.kind) |kind| allocator.free(kind);
        if (self.template) |template| allocator.free(template);
        if (self.foreground) |foreground| allocator.free(foreground);
        if (self.background) |background| allocator.free(background);
    }
};

pub const OmpBlock = struct {
    block_type: ?[]u8 = null,
    alignment: ?[]u8 = null,
    segments: std.ArrayList(OmpSegment) = .empty,

    fn deinit(self: *OmpBlock, allocator: std.mem.Allocator) void {
        if (self.block_type) |block_type| allocator.free(block_type);
        if (self.alignment) |alignment| allocator.free(alignment);
        for (self.segments.items) |segment| segment.deinit(allocator);
        self.segments.deinit(allocator);
    }
};

pub const OmpTheme = struct {
    blocks: std.ArrayList(OmpBlock) = .empty,
    palette: std.ArrayList(OmpPaletteEntry) = .empty,

    pub fn deinit(self: *OmpTheme, allocator: std.mem.Allocator) void {
        for (self.blocks.items) |*block| block.deinit(allocator);
        self.blocks.deinit(allocator);
        for (self.palette.items) |entry| entry.deinit(allocator);
        self.palette.deinit(allocator);
    }
};

pub const OmpPaletteEntry = struct {
    name: []u8,
    value: []u8,

    fn deinit(self: OmpPaletteEntry, allocator: std.mem.Allocator) void {
        allocator.free(self.name);
        allocator.free(self.value);
    }
};

pub fn parseOmpTheme(allocator: std.mem.Allocator, source: []const u8) !OmpTheme {
    const trimmed = std.mem.trim(u8, source, " \t\r\n");
    if (trimmed.len == 0) return error.InvalidOmpTheme;
    if (trimmed[0] == '{') return parseOmpJsonTheme(allocator, source);
    return parseOmpYamlTheme(allocator, source);
}

fn parseOmpJsonTheme(allocator: std.mem.Allocator, source: []const u8) !OmpTheme {
    var parsed = try std.json.parseFromSlice(std.json.Value, allocator, source, .{ .ignore_unknown_fields = true });
    defer parsed.deinit();

    const root = switch (parsed.value) {
        .object => |object| object,
        else => return error.InvalidOmpTheme,
    };
    const blocks_value = root.get("blocks") orelse return error.InvalidOmpTheme;
    const blocks = switch (blocks_value) {
        .array => |array| array,
        else => return error.InvalidOmpTheme,
    };

    var theme = OmpTheme{};
    errdefer theme.deinit(allocator);
    if (root.get("palette")) |palette_value| {
        const palette = switch (palette_value) {
            .object => |object| object,
            else => return error.InvalidOmpTheme,
        };
        var iterator = palette.iterator();
        while (iterator.next()) |entry| {
            switch (entry.value_ptr.*) {
                .string => |value| try appendOmpPaletteEntry(allocator, &theme, entry.key_ptr.*, value),
                else => {},
            }
        }
    }
    for (blocks.items) |block_value| {
        const block_object = switch (block_value) {
            .object => |object| object,
            else => continue,
        };
        var block = OmpBlock{};
        errdefer block.deinit(allocator);
        if (jsonStringField(block_object, "type")) |value| try setOwned(allocator, &block.block_type, value);
        if (jsonStringField(block_object, "alignment")) |value| try setOwned(allocator, &block.alignment, value);
        if (block_object.get("segments")) |segments_value| {
            const segments = switch (segments_value) {
                .array => |array| array,
                else => return error.InvalidOmpTheme,
            };
            for (segments.items) |segment_value| {
                const segment_object = switch (segment_value) {
                    .object => |object| object,
                    else => continue,
                };
                var segment = OmpSegment{};
                errdefer segment.deinit(allocator);
                if (jsonStringField(segment_object, "type")) |value| try setOwned(allocator, &segment.kind, value);
                if (jsonStringField(segment_object, "template")) |value| try setOwned(allocator, &segment.template, value);
                if (jsonStringField(segment_object, "foreground")) |value| try setOwned(allocator, &segment.foreground, value);
                if (jsonStringField(segment_object, "background")) |value| try setOwned(allocator, &segment.background, value);
                try block.segments.append(allocator, segment);
            }
        }
        try theme.blocks.append(allocator, block);
    }
    return theme;
}

fn jsonStringField(object: std.json.ObjectMap, key: []const u8) ?[]const u8 {
    const value = object.get(key) orelse return null;
    return switch (value) {
        .string => |string| string,
        else => null,
    };
}

fn parseOmpYamlTheme(allocator: std.mem.Allocator, source: []const u8) !OmpTheme {
    var theme = OmpTheme{};
    errdefer theme.deinit(allocator);

    var in_blocks = false;
    var in_palette = false;
    var in_segments = false;
    var current_block_index: ?usize = null;
    var current_segment_index: ?usize = null;
    var block_item_indent: usize = 0;

    var lines = std.mem.splitScalar(u8, source, '\n');
    while (lines.next()) |raw_line| {
        const without_comment = stripYamlComment(std.mem.trimRight(u8, raw_line, "\r"));
        if (std.mem.trim(u8, without_comment, " \t").len == 0) continue;
        const indent = leadingSpaces(without_comment);
        const trimmed = std.mem.trim(u8, without_comment[indent..], " \t");

        if (indent == 0 and std.mem.eql(u8, trimmed, "palette:")) {
            in_palette = true;
            in_blocks = false;
            in_segments = false;
            continue;
        }
        if (in_palette) {
            if (indent == 0) {
                in_palette = false;
            } else {
                if (yamlKeyValue(trimmed)) |kv| try appendOmpPaletteEntry(allocator, &theme, kv.key, yamlScalar(kv.value));
                continue;
            }
        }

        if (indent == 0 and std.mem.eql(u8, trimmed, "blocks:")) {
            in_blocks = true;
            in_palette = false;
            in_segments = false;
            continue;
        }
        if (!in_blocks) continue;

        if (std.mem.startsWith(u8, trimmed, "-")) {
            const item = std.mem.trim(u8, trimmed[1..], " \t");
            if (in_segments and indent > block_item_indent) {
                const block_index = current_block_index orelse return error.InvalidOmpTheme;
                try theme.blocks.items[block_index].segments.append(allocator, .{});
                current_segment_index = theme.blocks.items[block_index].segments.items.len - 1;
                if (yamlKeyValue(item)) |kv| {
                    try applyOmpYamlSegmentField(allocator, &theme.blocks.items[block_index].segments.items[current_segment_index.?], kv.key, kv.value);
                }
            } else {
                try theme.blocks.append(allocator, .{});
                current_block_index = theme.blocks.items.len - 1;
                current_segment_index = null;
                block_item_indent = indent;
                in_segments = false;
                if (yamlKeyValue(item)) |kv| try applyOmpYamlBlockField(allocator, &theme.blocks.items[current_block_index.?], kv.key, kv.value);
            }
            continue;
        }

        const block_index = current_block_index orelse continue;
        if (yamlKeyValue(trimmed)) |kv| {
            if (std.mem.eql(u8, kv.key, "segments")) {
                in_segments = true;
                current_segment_index = null;
            } else if (in_segments) {
                if (current_segment_index) |segment_index| {
                    try applyOmpYamlSegmentField(allocator, &theme.blocks.items[block_index].segments.items[segment_index], kv.key, kv.value);
                }
            } else {
                try applyOmpYamlBlockField(allocator, &theme.blocks.items[block_index], kv.key, kv.value);
            }
        }
    }
    return theme;
}

const YamlKeyValue = struct {
    key: []const u8,
    value: []const u8,
};

fn yamlKeyValue(line: []const u8) ?YamlKeyValue {
    const colon = std.mem.indexOfScalar(u8, line, ':') orelse return null;
    const key = std.mem.trim(u8, line[0..colon], " \t");
    if (key.len == 0) return null;
    return .{ .key = key, .value = std.mem.trim(u8, line[colon + 1 ..], " \t") };
}

fn yamlScalar(value: []const u8) []const u8 {
    if (value.len >= 2 and ((value[0] == '"' and value[value.len - 1] == '"') or (value[0] == '\'' and value[value.len - 1] == '\''))) {
        return value[1 .. value.len - 1];
    }
    return value;
}

fn applyOmpYamlBlockField(allocator: std.mem.Allocator, block: *OmpBlock, key: []const u8, value: []const u8) !void {
    if (std.mem.eql(u8, key, "type")) {
        try setOwned(allocator, &block.block_type, yamlScalar(value));
    } else if (std.mem.eql(u8, key, "alignment")) {
        try setOwned(allocator, &block.alignment, yamlScalar(value));
    }
}

fn applyOmpYamlSegmentField(allocator: std.mem.Allocator, segment: *OmpSegment, key: []const u8, value: []const u8) !void {
    if (std.mem.eql(u8, key, "type")) {
        try setOwned(allocator, &segment.kind, yamlScalar(value));
    } else if (std.mem.eql(u8, key, "template")) {
        try setOwned(allocator, &segment.template, yamlScalar(value));
    } else if (std.mem.eql(u8, key, "foreground")) {
        try setOwned(allocator, &segment.foreground, yamlScalar(value));
    } else if (std.mem.eql(u8, key, "background")) {
        try setOwned(allocator, &segment.background, yamlScalar(value));
    }
}

pub fn appendOmpPaletteEntry(allocator: std.mem.Allocator, theme: *OmpTheme, name: []const u8, value: []const u8) !void {
    const owned_name = try allocator.dupe(u8, name);
    errdefer allocator.free(owned_name);
    const owned_value = try allocator.dupe(u8, value);
    errdefer allocator.free(owned_value);
    try theme.palette.append(allocator, .{ .name = owned_name, .value = owned_value });
}

fn setOwned(allocator: std.mem.Allocator, target: *?[]u8, value: []const u8) !void {
    if (target.*) |owned| allocator.free(owned);
    target.* = try allocator.dupe(u8, value);
}

fn stripYamlComment(line: []const u8) []const u8 {
    var quote: ?u8 = null;
    for (line, 0..) |byte, index| {
        if (quote) |active| {
            if (byte == active) quote = null;
        } else if (byte == '"' or byte == '\'') {
            quote = byte;
        } else if (byte == '#') {
            return line[0..index];
        }
    }
    return line;
}

fn leadingSpaces(line: []const u8) usize {
    var index: usize = 0;
    while (index < line.len and line[index] == ' ') : (index += 1) {}
    return index;
}

pub fn scanOmpTheme(allocator: std.mem.Allocator, theme: OmpTheme, imported: *StarshipImport) !void {
    for (theme.blocks.items) |block| {
        for (block.segments.items) |segment| {
            if (segment.kind) |kind| try mapOmpSegment(allocator, kind, imported);
        }
    }
}

fn mapOmpSegment(allocator: std.mem.Allocator, name: []const u8, imported: *StarshipImport) !void {
    if (std.mem.eql(u8, name, "path")) {
        try appendModule(allocator, imported, .cwd);
    } else if (std.mem.eql(u8, name, "git") or
        std.mem.eql(u8, name, "jujutsu") or
        std.mem.eql(u8, name, "mercurial") or
        std.mem.eql(u8, name, "sapling") or
        std.mem.eql(u8, name, "svn") or
        std.mem.eql(u8, name, "fossil") or
        std.mem.eql(u8, name, "plastic"))
    {
        try appendModule(allocator, imported, .git_branch);
    } else if (std.mem.eql(u8, name, "python")) {
        imported.python = true;
        try appendModule(allocator, imported, .language_versions);
    } else if (std.mem.eql(u8, name, "node")) {
        imported.node = true;
        try appendModule(allocator, imported, .language_versions);
    } else if (std.mem.eql(u8, name, "go")) {
        imported.go = true;
        try appendModule(allocator, imported, .language_versions);
    } else if (std.mem.eql(u8, name, "rust")) {
        imported.rust = true;
        try appendModule(allocator, imported, .language_versions);
    } else if (std.mem.eql(u8, name, "status")) {
        try appendModule(allocator, imported, .exit_status);
    } else if (std.mem.eql(u8, name, "executiontime")) {
        try appendModule(allocator, imported, .cmd_duration);
    } else if (std.mem.eql(u8, name, "session")) {
        try appendModule(allocator, imported, .user_host);
    } else if (std.mem.eql(u8, name, "aws") or
        std.mem.eql(u8, name, "gcp") or
        std.mem.eql(u8, name, "az") or
        std.mem.eql(u8, name, "kubectl"))
    {
        try appendModule(allocator, imported, .cloud_ctx);
    } else if (std.mem.eql(u8, name, "terraform") or std.mem.eql(u8, name, "pulumi")) {
        try appendModule(allocator, imported, .iac_workspace);
    } else if (std.mem.eql(u8, name, "time")) {
        try appendModule(allocator, imported, .time);
    } else if (!isIgnoredOmpSegment(name)) {
        try appendUnsupported(allocator, imported, name);
    }
}

fn isIgnoredOmpSegment(name: []const u8) bool {
    return std.mem.eql(u8, name, "text") or
        std.mem.eql(u8, name, "shell") or
        std.mem.eql(u8, name, "os") or
        std.mem.eql(u8, name, "upgrade");
}

pub const OmpImportResult = struct {
    config: []u8,
    theme: ?[]u8 = null,
    notes: ?[]u8 = null,

    pub fn deinit(self: OmpImportResult, allocator: std.mem.Allocator) void {
        allocator.free(self.config);
        if (self.theme) |theme| allocator.free(theme);
        if (self.notes) |notes| allocator.free(notes);
    }
};

pub fn importOhMyPoshCmd(allocator: std.mem.Allocator, args: []const []const u8) !void {
    const options = try parseImportArgs(args, true);

    const source = try std.fs.cwd().readFileAlloc(allocator, options.source_path.?, max_config_bytes);
    defer allocator.free(source);

    var plan = try importOhMyPoshPlanAlloc(allocator, source);
    defer plan.deinit(allocator);
    try applyImportPlan(allocator, &plan, options);
}

fn importOhMyPoshPlanAlloc(allocator: std.mem.Allocator, source: []const u8) !ImportPlan {
    const result = try importOhMyPoshResultAlloc(allocator, source);
    var plan = ImportPlan{
        .target_toml = result.config,
        .source_name = "Oh My Posh",
        .docs_path = "docs/migration-oh-my-posh.md",
    };
    errdefer plan.deinit(allocator);
    if (result.theme) |theme| try addSidecarOwned(allocator, &plan, "oh-my-posh-theme.toml", theme);
    if (result.notes) |notes| try addSidecarOwned(allocator, &plan, "migration-notes.md", notes);
    try collectUnmappedKeys(allocator, &plan);
    return plan;
}

pub fn importOhMyPoshResultAlloc(allocator: std.mem.Allocator, source: []const u8) !OmpImportResult {
    var theme = try parseOmpTheme(allocator, source);
    defer theme.deinit(allocator);

    var imported = StarshipImport{};
    defer imported.deinit(allocator);
    try scanOmpTheme(allocator, theme, &imported);

    if (imported.modules.items.len == 0) {
        inline for (.{ .cwd, .git_branch, .language_versions, .exit_status, .cmd_duration, .user_host }) |module_id| {
            try appendModule(allocator, &imported, module_id);
        }
    }

    const imported_theme = try renderOmpImportedThemeAlloc(allocator, theme);
    errdefer if (imported_theme) |owned| allocator.free(owned);
    const config = try renderOmpImportedConfigAlloc(allocator, imported, theme, if (imported_theme != null) "./oh-my-posh-theme.toml" else null);
    errdefer allocator.free(config);
    const notes = try renderOmpMigrationNotesAlloc(allocator, theme, imported);
    errdefer if (notes) |owned| allocator.free(owned);
    return .{ .config = config, .theme = imported_theme, .notes = notes };
}

fn renderOmpImportedConfigAlloc(allocator: std.mem.Allocator, imported: StarshipImport, theme: OmpTheme, theme_path: ?[]const u8) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);

    try out.appendSlice(allocator, "version = 1\ntheme = ");
    try appendTomlString(allocator, &out, theme_path orelse "plain");
    try out.appendSlice(allocator, "\n\n");
    try appendOmpLayoutComments(allocator, &out, theme);
    try out.appendSlice(allocator, "[prompt]\nmodules = [");
    for (imported.modules.items, 0..) |module_id, index| {
        if (index != 0) try out.appendSlice(allocator, ", ");
        try cli_util.appendFmt(allocator, &out, "\"{s}\"", .{shisa_config.moduleIdName(module_id)});
    }
    try out.appendSlice(allocator, "]\n");
    if (imported.right_modules.items.len != 0) {
        try out.appendSlice(allocator, "right_modules = [");
        for (imported.right_modules.items, 0..) |module_id, index| {
            if (index != 0) try out.appendSlice(allocator, ", ");
            try cli_util.appendFmt(allocator, &out, "\"{s}\"", .{shisa_config.moduleIdName(module_id)});
        }
        try out.appendSlice(allocator, "]\n");
    }

    if (containsAnyModule(imported, .language_versions) and (imported.python or imported.node or imported.rust or imported.go)) {
        try out.appendSlice(allocator, "\n[modules.language_versions]\ndetect = [");
        var count: usize = 0;
        if (imported.python) try appendLanguage(allocator, &out, &count, "python");
        if (imported.node) try appendLanguage(allocator, &out, &count, "node");
        if (imported.rust) try appendLanguage(allocator, &out, &count, "rust");
        if (imported.go) try appendLanguage(allocator, &out, &count, "go");
        try out.appendSlice(allocator, "]\n");
    }

    if (containsAnyModule(imported, .time)) {
        try out.appendSlice(allocator, "\n[modules.time]\nformat = \"24h\"\nutc = true\n");
    }

    if (imported.unsupported.items.len != 0) {
        try out.appendSlice(allocator, "\n# Unsupported Oh My Posh segments: ");
        for (imported.unsupported.items, 0..) |name, index| {
            if (index != 0) try out.appendSlice(allocator, ", ");
            try out.appendSlice(allocator, name);
        }
        try out.append(allocator, '\n');
    }

    return out.toOwnedSlice(allocator);
}

fn renderOmpMigrationNotesAlloc(allocator: std.mem.Allocator, theme: OmpTheme, imported: StarshipImport) !?[]u8 {
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);

    var count: usize = 0;
    try out.appendSlice(allocator, "# Oh My Posh Migration Notes\n\n");

    if (imported.unsupported.items.len != 0) {
        count += imported.unsupported.items.len;
        try out.appendSlice(allocator, "## Unsupported Segments\n\n");
        for (imported.unsupported.items) |name| {
            try cli_util.appendFmt(allocator, &out, "- `{s}`: {s}\n", .{ name, ompUnsupportedReason(name) });
        }
        try out.append(allocator, '\n');
    }

    var template_count: usize = 0;
    for (theme.blocks.items) |block| {
        for (block.segments.items) |segment| {
            const kind = segment.kind orelse continue;
            if (ompModuleForSegment(kind) == null) continue;
            const template = segment.template orelse continue;
            const layout = try translateOmpTemplateLayoutAlloc(allocator, template);
            defer if (layout) |owned| owned.deinit(allocator);
            if (layout == null) {
                if (template_count == 0) try out.appendSlice(allocator, "## Untranslated Templates\n\n");
                template_count += 1;
                count += 1;
                try cli_util.appendFmt(allocator, &out, "- `{s}`: template requires manual port.\n", .{kind});
            }
        }
    }
    if (template_count != 0) try out.append(allocator, '\n');

    var color_count: usize = 0;
    for (theme.blocks.items) |block| {
        for (block.segments.items) |segment| {
            const kind = segment.kind orelse continue;
            if (segment.foreground) |foreground| {
                if (resolveOmpColorRgb(theme, foreground, 0) == null) {
                    if (color_count == 0) try out.appendSlice(allocator, "## Unresolved Colors\n\n");
                    color_count += 1;
                    count += 1;
                    try cli_util.appendFmt(allocator, &out, "- `{s}` foreground `{s}` could not be resolved.\n", .{ kind, foreground });
                }
            }
            if (segment.background) |background| {
                if (resolveOmpColorRgb(theme, background, 0) == null) {
                    if (color_count == 0) try out.appendSlice(allocator, "## Unresolved Colors\n\n");
                    color_count += 1;
                    count += 1;
                    try cli_util.appendFmt(allocator, &out, "- `{s}` background `{s}` could not be resolved.\n", .{ kind, background });
                }
            }
        }
    }

    if (count == 0) return null;
    return try out.toOwnedSlice(allocator);
}

fn ompUnsupportedReason(name: []const u8) []const u8 {
    if (std.mem.eql(u8, name, "battery")) return "No core battery module.";
    if (std.mem.eql(u8, name, "docker")) return "Docker context differs from Shisa container provenance.";
    if (std.mem.eql(u8, name, "ipify")) return "No core public-IP module.";
    if (std.mem.eql(u8, name, "sysinfo")) return "No core CPU/RAM module.";
    if (std.mem.eql(u8, name, "project")) return "No package/project metadata core module yet.";
    if (std.mem.eql(u8, name, "http")) return "Network calls are not imported into prompt hot path.";
    if (std.mem.eql(u8, name, "spotify")) return "Media status belongs in a plugin.";
    if (std.mem.eql(u8, name, "wakatime")) return "External service calls belong in a plugin.";
    if (std.mem.eql(u8, name, "taskwarrior")) return "Task manager integrations belong in a plugin.";
    return "No Shisa core mapping; recreate as a plugin or omit.";
}

fn appendOmpLayoutComments(allocator: std.mem.Allocator, out: *std.ArrayList(u8), theme: OmpTheme) !void {
    try appendOmpLayoutComment(allocator, out, theme, false);
    try appendOmpLayoutComment(allocator, out, theme, true);
}

fn appendOmpLayoutComment(allocator: std.mem.Allocator, out: *std.ArrayList(u8), theme: OmpTheme, right: bool) !void {
    try cli_util.appendFmt(allocator, out, "# Oh My Posh {s} layout: ", .{if (right) "right" else "left"});
    var count: usize = 0;
    for (theme.blocks.items) |block| {
        if (ompBlockIsRight(block) != right) continue;
        for (block.segments.items) |segment| {
            const kind = segment.kind orelse continue;
            if (count != 0) try out.appendSlice(allocator, ", ");
            count += 1;
            try out.appendSlice(allocator, kind);
        }
    }
    try out.append(allocator, '\n');
}

fn ompBlockIsRight(block: OmpBlock) bool {
    if (block.alignment) |alignment| {
        if (std.mem.eql(u8, alignment, "right")) return true;
    }
    if (block.block_type) |block_type| {
        if (std.mem.eql(u8, block_type, "rprompt")) return true;
    }
    return false;
}

fn renderOmpImportedThemeAlloc(allocator: std.mem.Allocator, theme: OmpTheme) !?[]u8 {
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);

    var emitted = StarshipImport{};
    defer emitted.deinit(allocator);

    const mapped_palette = mapOmpPalette(theme);
    try out.appendSlice(allocator, "version = 1\nname = \"oh-my-posh-imported\"\nextends = \"plain\"\n");
    if (mapped_palette.has_source) try appendMappedOmpPalette(allocator, &out, mapped_palette);
    var count: usize = 0;
    for (theme.blocks.items) |block| {
        for (block.segments.items) |segment| {
            const kind = segment.kind orelse continue;
            const module_id = ompModuleForSegment(kind) orelse continue;
            if (containsModule(emitted, module_id)) continue;
            const layout = if (segment.template) |template| try translateOmpTemplateLayoutAlloc(allocator, template) else null;
            defer if (layout) |owned| owned.deinit(allocator);
            const fg_ref = try translateOmpColorRefAlloc(allocator, theme, mapped_palette, segment.foreground);
            defer if (fg_ref) |owned| allocator.free(owned);
            const bg_ref = try translateOmpColorRefAlloc(allocator, theme, mapped_palette, segment.background);
            defer if (bg_ref) |owned| allocator.free(owned);
            const has_layout = if (layout) |owned| owned.prefix.len != 0 or owned.suffix.len != 0 else false;
            if (!has_layout and fg_ref == null and bg_ref == null) continue;
            try appendModule(allocator, &emitted, module_id);
            try cli_util.appendFmt(allocator, &out, "\n[segments.{s}]\n", .{shisa_config.moduleIdName(module_id)});
            if (fg_ref) |value| {
                try out.appendSlice(allocator, "fg = ");
                try appendTomlString(allocator, &out, value);
                try out.append(allocator, '\n');
            }
            if (bg_ref) |value| {
                try out.appendSlice(allocator, "bg = ");
                try appendTomlString(allocator, &out, value);
                try out.append(allocator, '\n');
            }
            if (layout) |owned| if (owned.prefix.len != 0) {
                try out.appendSlice(allocator, "prefix = ");
                try appendTomlString(allocator, &out, owned.prefix);
                try out.append(allocator, '\n');
            };
            if (layout) |owned| if (owned.suffix.len != 0) {
                try out.appendSlice(allocator, "suffix = ");
                try appendTomlString(allocator, &out, owned.suffix);
                try out.append(allocator, '\n');
            };
            count += 1;
        }
    }
    if (count == 0) return null;
    return try out.toOwnedSlice(allocator);
}

fn ompModuleForSegment(name: []const u8) ?shisa_config.ModuleId {
    if (std.mem.eql(u8, name, "path")) return .cwd;
    if (std.mem.eql(u8, name, "git") or
        std.mem.eql(u8, name, "jujutsu") or
        std.mem.eql(u8, name, "mercurial") or
        std.mem.eql(u8, name, "sapling") or
        std.mem.eql(u8, name, "svn") or
        std.mem.eql(u8, name, "fossil") or
        std.mem.eql(u8, name, "plastic")) return .git_branch;
    if (std.mem.eql(u8, name, "python") or
        std.mem.eql(u8, name, "node") or
        std.mem.eql(u8, name, "go") or
        std.mem.eql(u8, name, "rust")) return .language_versions;
    if (std.mem.eql(u8, name, "status")) return .exit_status;
    if (std.mem.eql(u8, name, "executiontime")) return .cmd_duration;
    if (std.mem.eql(u8, name, "session")) return .user_host;
    if (std.mem.eql(u8, name, "aws") or
        std.mem.eql(u8, name, "gcp") or
        std.mem.eql(u8, name, "az") or
        std.mem.eql(u8, name, "kubectl")) return .cloud_ctx;
    if (std.mem.eql(u8, name, "terraform") or std.mem.eql(u8, name, "pulumi")) return .iac_workspace;
    if (std.mem.eql(u8, name, "time")) return .time;
    return null;
}

pub const Rgb = struct {
    r: u8,
    g: u8,
    b: u8,
};

pub const Oklab = struct {
    l: f64,
    a: f64,
    b: f64,
};

pub const ShisaPaletteSlot = struct {
    name: []const u8,
    target: Rgb,
    fallback: Rgb,
};

const shisa_palette_slots = [_]ShisaPaletteSlot{
    .{ .name = "fg", .target = .{ .r = 255, .g = 255, .b = 255 }, .fallback = .{ .r = 255, .g = 255, .b = 255 } },
    .{ .name = "muted", .target = .{ .r = 128, .g = 128, .b = 128 }, .fallback = .{ .r = 128, .g = 128, .b = 128 } },
    .{ .name = "accent", .target = .{ .r = 0, .g = 255, .b = 255 }, .fallback = .{ .r = 0, .g = 255, .b = 255 } },
    .{ .name = "success", .target = .{ .r = 0, .g = 170, .b = 0 }, .fallback = .{ .r = 0, .g = 170, .b = 0 } },
    .{ .name = "warning", .target = .{ .r = 255, .g = 170, .b = 0 }, .fallback = .{ .r = 255, .g = 170, .b = 0 } },
    .{ .name = "danger", .target = .{ .r = 255, .g = 0, .b = 0 }, .fallback = .{ .r = 255, .g = 0, .b = 0 } },
};

pub const MappedOmpPalette = struct {
    has_source: bool = false,
    colors: [shisa_palette_slots.len]Rgb = defaultShisaPaletteColors(),
};

fn defaultShisaPaletteColors() [shisa_palette_slots.len]Rgb {
    var colors: [shisa_palette_slots.len]Rgb = undefined;
    for (shisa_palette_slots, 0..) |slot, index| colors[index] = slot.fallback;
    return colors;
}

pub fn mapOmpPalette(theme: OmpTheme) MappedOmpPalette {
    var mapped = MappedOmpPalette{};
    if (theme.palette.items.len == 0) return mapped;
    mapped.has_source = true;
    var filled = [_]bool{false} ** shisa_palette_slots.len;
    for (shisa_palette_slots, 0..) |slot, index| {
        if (findOmpPaletteRgb(theme, slot.name)) |rgb| {
            mapped.colors[index] = rgb;
            filled[index] = true;
        }
    }
    for (shisa_palette_slots, 0..) |slot, index| {
        if (filled[index]) continue;
        if (nearestOmpPaletteRgbAvoiding(theme, slot.target, mapped.colors, filled)) |rgb| {
            mapped.colors[index] = rgb;
            filled[index] = true;
        }
    }
    return mapped;
}

fn appendMappedOmpPalette(allocator: std.mem.Allocator, out: *std.ArrayList(u8), mapped: MappedOmpPalette) !void {
    try out.appendSlice(allocator, "\n[palette]\n");
    for (shisa_palette_slots, 0..) |slot, index| {
        try cli_util.appendFmt(allocator, out, "{s} = ", .{slot.name});
        try appendRgbHexString(allocator, out, mapped.colors[index]);
        try out.append(allocator, '\n');
    }
}

fn translateOmpColorRefAlloc(allocator: std.mem.Allocator, theme: OmpTheme, mapped: MappedOmpPalette, value: ?[]const u8) !?[]u8 {
    const raw = value orelse return null;
    const rgb = resolveOmpColorRgb(theme, raw, 0) orelse return null;
    if (mapped.has_source) {
        const slot = nearestMappedPaletteSlot(mapped, rgb);
        return try std.fmt.allocPrint(allocator, "@{s}", .{slot});
    }
    return try rgbHexAlloc(allocator, rgb);
}

pub fn nearestMappedPaletteSlot(mapped: MappedOmpPalette, rgb: Rgb) []const u8 {
    const target = rgbToOklab(rgb);
    var best_index: usize = 0;
    var best_distance = oklabDistanceSquared(target, rgbToOklab(mapped.colors[0]));
    for (mapped.colors[1..], 1..) |candidate, offset| {
        const distance = oklabDistanceSquared(target, rgbToOklab(candidate));
        if (distance < best_distance) {
            best_distance = distance;
            best_index = offset;
        }
    }
    return shisa_palette_slots[best_index].name;
}

fn nearestOmpPaletteRgb(theme: OmpTheme, target: Rgb) ?Rgb {
    return nearestOmpPaletteRgbAvoiding(theme, target, defaultShisaPaletteColors(), [_]bool{false} ** shisa_palette_slots.len);
}

fn nearestOmpPaletteRgbAvoiding(theme: OmpTheme, target: Rgb, used_colors: [shisa_palette_slots.len]Rgb, used: [shisa_palette_slots.len]bool) ?Rgb {
    const target_lab = rgbToOklab(target);
    var best: ?Rgb = null;
    var best_distance: f64 = 0;
    for (theme.palette.items) |entry| {
        const rgb = resolveOmpColorRgb(theme, entry.value, 0) orelse continue;
        if (rgbIsUsed(rgb, used_colors, used)) continue;
        const distance = oklabDistanceSquared(target_lab, rgbToOklab(rgb));
        if (best == null or distance < best_distance) {
            best = rgb;
            best_distance = distance;
        }
    }
    return best;
}

fn rgbIsUsed(rgb: Rgb, used_colors: [shisa_palette_slots.len]Rgb, used: [shisa_palette_slots.len]bool) bool {
    for (used, 0..) |is_used, index| {
        if (is_used and std.meta.eql(rgb, used_colors[index])) return true;
    }
    return false;
}

fn findOmpPaletteRgb(theme: OmpTheme, name: []const u8) ?Rgb {
    for (theme.palette.items) |entry| {
        if (std.mem.eql(u8, entry.name, name)) return resolveOmpColorRgb(theme, entry.value, 0);
    }
    return null;
}

fn resolveOmpColorRgb(theme: OmpTheme, value: []const u8, depth: u8) ?Rgb {
    if (depth > 8) return null;
    const trimmed = std.mem.trim(u8, value, " \t\r\n");
    if (std.mem.startsWith(u8, trimmed, "p:")) {
        const name = trimmed[2..];
        for (theme.palette.items) |entry| {
            if (std.mem.eql(u8, entry.name, name)) return resolveOmpColorRgb(theme, entry.value, depth + 1);
        }
        return null;
    }
    if (parseHexColor(trimmed)) |rgb| return rgb;
    if (parseAnsiColor(trimmed)) |rgb| return rgb;
    return namedOmpColor(trimmed);
}

fn parseHexColor(value: []const u8) ?Rgb {
    if (value.len == 7 and value[0] == '#') {
        return .{
            .r = parseHexByte(value[1], value[2]) orelse return null,
            .g = parseHexByte(value[3], value[4]) orelse return null,
            .b = parseHexByte(value[5], value[6]) orelse return null,
        };
    }
    if (value.len == 4 and value[0] == '#') {
        const r = parseHexDigit(value[1]) orelse return null;
        const g = parseHexDigit(value[2]) orelse return null;
        const b = parseHexDigit(value[3]) orelse return null;
        return .{ .r = r * 17, .g = g * 17, .b = b * 17 };
    }
    return null;
}

fn parseHexByte(high: u8, low: u8) ?u8 {
    const high_value = parseHexDigit(high) orelse return null;
    const low_value = parseHexDigit(low) orelse return null;
    return high_value * 16 + low_value;
}

fn parseHexDigit(byte: u8) ?u8 {
    if (byte >= '0' and byte <= '9') return byte - '0';
    if (byte >= 'a' and byte <= 'f') return byte - 'a' + 10;
    if (byte >= 'A' and byte <= 'F') return byte - 'A' + 10;
    return null;
}

fn parseAnsiColor(value: []const u8) ?Rgb {
    const index = std.fmt.parseInt(u8, value, 10) catch return null;
    const base = [_]Rgb{
        .{ .r = 0, .g = 0, .b = 0 },
        .{ .r = 128, .g = 0, .b = 0 },
        .{ .r = 0, .g = 128, .b = 0 },
        .{ .r = 128, .g = 128, .b = 0 },
        .{ .r = 0, .g = 0, .b = 128 },
        .{ .r = 128, .g = 0, .b = 128 },
        .{ .r = 0, .g = 128, .b = 128 },
        .{ .r = 192, .g = 192, .b = 192 },
        .{ .r = 128, .g = 128, .b = 128 },
        .{ .r = 255, .g = 0, .b = 0 },
        .{ .r = 0, .g = 255, .b = 0 },
        .{ .r = 255, .g = 255, .b = 0 },
        .{ .r = 0, .g = 0, .b = 255 },
        .{ .r = 255, .g = 0, .b = 255 },
        .{ .r = 0, .g = 255, .b = 255 },
        .{ .r = 255, .g = 255, .b = 255 },
    };
    if (index < 16) return base[index];
    if (index <= 231) {
        const cube = index - 16;
        const steps = [_]u8{ 0, 95, 135, 175, 215, 255 };
        return .{
            .r = steps[cube / 36],
            .g = steps[(cube / 6) % 6],
            .b = steps[cube % 6],
        };
    }
    const gray: u8 = 8 + (index - 232) * 10;
    return .{ .r = gray, .g = gray, .b = gray };
}

fn namedOmpColor(value: []const u8) ?Rgb {
    if (std.mem.eql(u8, value, "black")) return .{ .r = 0, .g = 0, .b = 0 };
    if (std.mem.eql(u8, value, "red")) return .{ .r = 128, .g = 0, .b = 0 };
    if (std.mem.eql(u8, value, "green")) return .{ .r = 0, .g = 128, .b = 0 };
    if (std.mem.eql(u8, value, "yellow")) return .{ .r = 128, .g = 128, .b = 0 };
    if (std.mem.eql(u8, value, "blue")) return .{ .r = 0, .g = 0, .b = 128 };
    if (std.mem.eql(u8, value, "magenta")) return .{ .r = 128, .g = 0, .b = 128 };
    if (std.mem.eql(u8, value, "cyan")) return .{ .r = 0, .g = 128, .b = 128 };
    if (std.mem.eql(u8, value, "white")) return .{ .r = 192, .g = 192, .b = 192 };
    if (std.mem.eql(u8, value, "darkGray")) return .{ .r = 128, .g = 128, .b = 128 };
    if (std.mem.eql(u8, value, "lightRed")) return .{ .r = 255, .g = 0, .b = 0 };
    if (std.mem.eql(u8, value, "lightGreen")) return .{ .r = 0, .g = 255, .b = 0 };
    if (std.mem.eql(u8, value, "lightYellow")) return .{ .r = 255, .g = 255, .b = 0 };
    if (std.mem.eql(u8, value, "lightBlue")) return .{ .r = 0, .g = 0, .b = 255 };
    if (std.mem.eql(u8, value, "lightMagenta")) return .{ .r = 255, .g = 0, .b = 255 };
    if (std.mem.eql(u8, value, "lightCyan")) return .{ .r = 0, .g = 255, .b = 255 };
    if (std.mem.eql(u8, value, "lightWhite")) return .{ .r = 255, .g = 255, .b = 255 };
    if (std.mem.eql(u8, value, "foreground")) return .{ .r = 255, .g = 255, .b = 255 };
    if (std.mem.eql(u8, value, "background")) return .{ .r = 0, .g = 0, .b = 0 };
    if (std.mem.eql(u8, value, "accent")) return .{ .r = 0, .g = 255, .b = 255 };
    return null;
}

fn rgbToOklab(rgb: Rgb) Oklab {
    const r = srgbByteToLinear(rgb.r);
    const g = srgbByteToLinear(rgb.g);
    const b = srgbByteToLinear(rgb.b);
    const l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b;
    const m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b;
    const s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b;
    const l_root = std.math.pow(f64, l, 1.0 / 3.0);
    const m_root = std.math.pow(f64, m, 1.0 / 3.0);
    const s_root = std.math.pow(f64, s, 1.0 / 3.0);
    return .{
        .l = 0.2104542553 * l_root + 0.7936177850 * m_root - 0.0040720468 * s_root,
        .a = 1.9779984951 * l_root - 2.4285922050 * m_root + 0.4505937099 * s_root,
        .b = 0.0259040371 * l_root + 0.7827717662 * m_root - 0.8086757660 * s_root,
    };
}

fn srgbByteToLinear(byte: u8) f64 {
    const value: f64 = @as(f64, @floatFromInt(byte)) / 255.0;
    if (value <= 0.04045) return value / 12.92;
    return std.math.pow(f64, (value + 0.055) / 1.055, 2.4);
}

fn oklabDistanceSquared(a: Oklab, b: Oklab) f64 {
    const dl = a.l - b.l;
    const da = a.a - b.a;
    const db = a.b - b.b;
    return dl * dl + da * da + db * db;
}

fn rgbHexAlloc(allocator: std.mem.Allocator, rgb: Rgb) ![]u8 {
    return std.fmt.allocPrint(allocator, "#{X:0>2}{X:0>2}{X:0>2}", .{ rgb.r, rgb.g, rgb.b });
}

fn appendRgbHexString(allocator: std.mem.Allocator, out: *std.ArrayList(u8), rgb: Rgb) !void {
    const hex = try rgbHexAlloc(allocator, rgb);
    defer allocator.free(hex);
    try appendTomlString(allocator, out, hex);
}

pub const OmpTemplateLayout = struct {
    prefix: []u8,
    suffix: []u8,

    pub fn deinit(self: OmpTemplateLayout, allocator: std.mem.Allocator) void {
        allocator.free(self.prefix);
        allocator.free(self.suffix);
    }
};

pub fn translateOmpTemplateLayoutAlloc(allocator: std.mem.Allocator, template: []const u8) !?OmpTemplateLayout {
    const open = std.mem.indexOf(u8, template, "{{") orelse return null;
    const close_offset = std.mem.indexOf(u8, template[open + 2 ..], "}}") orelse return null;
    const close = open + 2 + close_offset;
    if (std.mem.indexOf(u8, template[close + 2 ..], "{{") != null) return null;
    const expression = std.mem.trim(u8, template[open + 2 .. close], " \t\r\n");
    if (isOmpTemplateControl(expression)) return null;

    const prefix = try stripOmpTemplateMarkupAlloc(allocator, template[0..open]);
    errdefer allocator.free(prefix);
    const suffix = try stripOmpTemplateMarkupAlloc(allocator, template[close + 2 ..]);
    errdefer allocator.free(suffix);
    return .{ .prefix = prefix, .suffix = suffix };
}

fn isOmpTemplateControl(expression: []const u8) bool {
    return std.mem.startsWith(u8, expression, "if ") or
        std.mem.startsWith(u8, expression, "range ") or
        std.mem.startsWith(u8, expression, "with ") or
        std.mem.eql(u8, expression, "else") or
        std.mem.eql(u8, expression, "end");
}

fn stripOmpTemplateMarkupAlloc(allocator: std.mem.Allocator, value: []const u8) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);

    var in_tag = false;
    for (value) |byte| {
        if (in_tag) {
            if (byte == '>') in_tag = false;
        } else if (byte == '<') {
            in_tag = true;
        } else {
            try out.append(allocator, byte);
        }
    }
    return out.toOwnedSlice(allocator);
}
