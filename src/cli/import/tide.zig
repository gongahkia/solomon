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
const appendTideModule = common.appendTideModule;
const appendUnsupported = common.appendUnsupported;
const containsModule = common.containsModule;
const containsRightModule = common.containsRightModule;
const containsAnyModule = common.containsAnyModule;
const appendLanguage = common.appendLanguage;

const TideSetting = struct {
    name: []u8,
    values: std.ArrayList([]u8) = .empty,

    fn deinit(self: *TideSetting, allocator: std.mem.Allocator) void {
        allocator.free(self.name);
        for (self.values.items) |value| allocator.free(value);
        self.values.deinit(allocator);
    }
};

const TideConfig = struct {
    settings: std.ArrayList(TideSetting) = .empty,

    fn deinit(self: *TideConfig, allocator: std.mem.Allocator) void {
        for (self.settings.items) |*setting| setting.deinit(allocator);
        self.settings.deinit(allocator);
    }

    fn find(self: TideConfig, name: []const u8) ?TideSetting {
        for (self.settings.items) |setting| {
            if (std.mem.eql(u8, setting.name, name)) return setting;
        }
        return null;
    }
};

fn parseTideConfig(allocator: std.mem.Allocator, source: []const u8) !TideConfig {
    var config = TideConfig{};
    errdefer config.deinit(allocator);

    var lines = std.mem.splitScalar(u8, source, '\n');
    while (lines.next()) |raw_line| {
        const line = std.mem.trim(u8, raw_line, " \t\r");
        if (line.len == 0 or line[0] == '#') continue;

        var words: std.ArrayList([]u8) = .empty;
        defer freeStringList(allocator, &words);
        try appendFishWords(allocator, &words, line);
        if (words.items.len == 0) continue;

        const name_index = tideNameIndex(words.items) orelse continue;
        const name = words.items[name_index];
        if (!validTideKey(name)) continue;

        var setting = TideSetting{ .name = try allocator.dupe(u8, name) };
        errdefer setting.deinit(allocator);
        for (words.items[name_index + 1 ..]) |value| {
            const owned = try allocator.dupe(u8, value);
            errdefer allocator.free(owned);
            try setting.values.append(allocator, owned);
        }
        try config.settings.append(allocator, setting);
    }

    return config;
}

fn tideNameIndex(words: []const []u8) ?usize {
    if (words.len == 0) return null;
    if (std.mem.eql(u8, words[0], "set")) {
        for (words[1..], 1..) |word, index| {
            if (std.mem.startsWith(u8, word, "tide_")) return index;
        }
        return null;
    }
    return if (std.mem.startsWith(u8, words[0], "tide_")) 0 else null;
}

fn validTideKey(key: []const u8) bool {
    if (!std.mem.startsWith(u8, key, "tide_")) return false;
    for (key) |byte| {
        if (!(std.ascii.isLower(byte) or std.ascii.isDigit(byte) or byte == '_')) return false;
    }
    return true;
}

fn appendFishWords(allocator: std.mem.Allocator, words: *std.ArrayList([]u8), text: []const u8) !void {
    var index: usize = 0;
    while (index < text.len) {
        while (index < text.len and std.ascii.isWhitespace(text[index])) : (index += 1) {}
        if (index >= text.len or text[index] == '#') break;

        if (text[index] == '\'' or text[index] == '"') {
            const quote = text[index];
            index += 1;
            const start = index;
            while (index < text.len and text[index] != quote) : (index += 1) {}
            if (index >= text.len) return error.UnclosedFishQuote;
            const owned = try allocator.dupe(u8, text[start..index]);
            errdefer allocator.free(owned);
            try words.append(allocator, owned);
            index += 1;
            continue;
        }

        const start = index;
        while (index < text.len and !std.ascii.isWhitespace(text[index]) and text[index] != '#') : (index += 1) {}
        const value = text[start..index];
        if (value.len != 0) {
            const owned = try allocator.dupe(u8, value);
            errdefer allocator.free(owned);
            try words.append(allocator, owned);
        }
    }
}

fn freeStringList(allocator: std.mem.Allocator, words: *std.ArrayList([]u8)) void {
    for (words.items) |word| allocator.free(word);
    words.deinit(allocator);
}

fn scanTideConfig(allocator: std.mem.Allocator, config: TideConfig, imported: *StarshipImport) !void {
    if (config.find("tide_left_prompt_items")) |setting| {
        for (setting.values.items) |item| try mapTideItem(allocator, item, imported, false);
    }
    if (config.find("tide_right_prompt_items")) |setting| {
        for (setting.values.items) |item| try mapTideItem(allocator, item, imported, true);
    }
}

fn mapTideItem(allocator: std.mem.Allocator, name: []const u8, imported: *StarshipImport, right: bool) !void {
    if (std.mem.eql(u8, name, "pwd")) {
        try appendTideModule(allocator, imported, .cwd, right);
    } else if (std.mem.eql(u8, name, "git")) {
        try appendTideModule(allocator, imported, .git_branch, right);
    } else if (std.mem.eql(u8, name, "status")) {
        try appendTideModule(allocator, imported, .exit_status, right);
    } else if (std.mem.eql(u8, name, "cmd_duration")) {
        try appendTideModule(allocator, imported, .cmd_duration, right);
    } else if (std.mem.eql(u8, name, "context")) {
        try appendTideModule(allocator, imported, .user_host, right);
    } else if (std.mem.eql(u8, name, "jobs")) {
        try appendTideModule(allocator, imported, .jobs, right);
    } else if (std.mem.eql(u8, name, "python")) {
        imported.python = true;
        try appendTideModule(allocator, imported, .language_versions, right);
    } else if (std.mem.eql(u8, name, "node")) {
        imported.node = true;
        try appendTideModule(allocator, imported, .language_versions, right);
    } else if (std.mem.eql(u8, name, "rustc")) {
        imported.rust = true;
        try appendTideModule(allocator, imported, .language_versions, right);
    } else if (std.mem.eql(u8, name, "go")) {
        imported.go = true;
        try appendTideModule(allocator, imported, .language_versions, right);
    } else if (std.mem.eql(u8, name, "aws") or
        std.mem.eql(u8, name, "gcloud") or
        std.mem.eql(u8, name, "kubectl"))
    {
        try appendTideModule(allocator, imported, .cloud_ctx, right);
    } else if (std.mem.eql(u8, name, "terraform") or std.mem.eql(u8, name, "pulumi")) {
        try appendTideModule(allocator, imported, .iac_workspace, right);
    } else if (std.mem.eql(u8, name, "time")) {
        try appendTideModule(allocator, imported, .time, right);
    } else if (!isIgnoredTideItem(name)) {
        try appendUnsupported(allocator, imported, name);
    }
}

fn isIgnoredTideItem(name: []const u8) bool {
    return std.mem.eql(u8, name, "newline") or
        std.mem.eql(u8, name, "character");
}

const TideImportResult = struct {
    config: []u8,
    notes: ?[]u8 = null,

    fn deinit(self: TideImportResult, allocator: std.mem.Allocator) void {
        allocator.free(self.config);
        if (self.notes) |notes| allocator.free(notes);
    }
};

pub fn importTideCmd(allocator: std.mem.Allocator, args: []const []const u8) !void {
    const options = try parseImportArgs(args, true);

    const source = try std.fs.cwd().readFileAlloc(allocator, options.source_path.?, max_config_bytes);
    defer allocator.free(source);

    var plan = try importTidePlanAlloc(allocator, source);
    defer plan.deinit(allocator);
    try applyImportPlan(allocator, &plan, options);
}

fn importTidePlanAlloc(allocator: std.mem.Allocator, source: []const u8) !ImportPlan {
    const result = try importTideResultAlloc(allocator, source);
    var plan = ImportPlan{
        .target_toml = result.config,
        .source_name = "Tide",
        .docs_path = "docs/migration-tide.md",
    };
    errdefer plan.deinit(allocator);
    if (result.notes) |notes| try addSidecarOwned(allocator, &plan, "migration-notes.md", notes);
    try collectUnmappedKeys(allocator, &plan);
    return plan;
}

fn importTideResultAlloc(allocator: std.mem.Allocator, source: []const u8) !TideImportResult {
    var tide = try parseTideConfig(allocator, source);
    defer tide.deinit(allocator);

    var imported = StarshipImport{};
    defer imported.deinit(allocator);
    try scanTideConfig(allocator, tide, &imported);

    if (imported.modules.items.len == 0) {
        inline for (.{ .cwd, .git_branch, .exit_status, .cmd_duration, .user_host }) |module_id| {
            try appendModule(allocator, &imported, module_id);
        }
    }

    const config = try renderTideImportedConfigAlloc(allocator, imported, tide);
    errdefer allocator.free(config);
    const notes = try renderTideMigrationNotesAlloc(allocator, imported, tide);
    errdefer if (notes) |owned| allocator.free(owned);
    return .{ .config = config, .notes = notes };
}

fn renderTideImportedConfigAlloc(allocator: std.mem.Allocator, imported: StarshipImport, tide: TideConfig) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);

    try out.appendSlice(allocator, "version = 1\ntheme = \"plain\"\n\n");
    try appendTideItemsComment(allocator, &out, tide, "left", "tide_left_prompt_items");
    try appendTideItemsComment(allocator, &out, tide, "right", "tide_right_prompt_items");
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
        try out.appendSlice(allocator, "\n# Unsupported Tide items: ");
        for (imported.unsupported.items, 0..) |name, index| {
            if (index != 0) try out.appendSlice(allocator, ", ");
            try out.appendSlice(allocator, name);
        }
        try out.append(allocator, '\n');
    }

    return out.toOwnedSlice(allocator);
}

fn appendTideItemsComment(allocator: std.mem.Allocator, out: *std.ArrayList(u8), tide: TideConfig, label: []const u8, key: []const u8) !void {
    try cli_util.appendFmt(allocator, out, "# Tide {s} items: ", .{label});
    if (tide.find(key)) |setting| {
        for (setting.values.items, 0..) |item, index| {
            if (index != 0) try out.appendSlice(allocator, ", ");
            try out.appendSlice(allocator, item);
        }
    }
    try out.append(allocator, '\n');
}

fn renderTideMigrationNotesAlloc(allocator: std.mem.Allocator, imported: StarshipImport, tide: TideConfig) !?[]u8 {
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);

    var count: usize = 0;
    try out.appendSlice(allocator, "# Tide Migration Notes\n\n");

    if (imported.unsupported.items.len != 0) {
        count += imported.unsupported.items.len;
        try out.appendSlice(allocator, "## Unsupported Items\n\n");
        for (imported.unsupported.items) |name| {
            try cli_util.appendFmt(allocator, &out, "- `{s}`: {s}\n", .{ name, tideUnsupportedReason(name) });
        }
        try out.append(allocator, '\n');
    }

    var quirk_count: usize = 0;
    if (settingFirstEquals(tide, "tide_prompt_transient_enabled", "true")) {
        if (quirk_count == 0) try out.appendSlice(allocator, "## Fish/Tide Quirks\n\n");
        quirk_count += 1;
        count += 1;
        try out.appendSlice(allocator, "- `tide_prompt_transient_enabled=true` is not imported for Fish.\n");
    }
    if (hasTideLayoutSetting(tide)) {
        if (quirk_count == 0) try out.appendSlice(allocator, "## Fish/Tide Quirks\n\n");
        quirk_count += 1;
        count += 1;
        try out.appendSlice(allocator, "- Tide frame/separator/prefix/suffix settings require manual theme/layout work.\n");
    }
    if (hasFishVariableColor(tide)) {
        if (quirk_count == 0) try out.appendSlice(allocator, "## Fish/Tide Quirks\n\n");
        quirk_count += 1;
        count += 1;
        try out.appendSlice(allocator, "- Fish variable color refs such as `$_tide_color_*` were not resolved.\n");
    }

    if (count == 0) return null;
    return try out.toOwnedSlice(allocator);
}

fn settingHasValues(tide: TideConfig, name: []const u8) bool {
    const setting = tide.find(name) orelse return false;
    return setting.values.items.len != 0;
}

fn settingFirstEquals(tide: TideConfig, name: []const u8, expected: []const u8) bool {
    const setting = tide.find(name) orelse return false;
    return setting.values.items.len != 0 and std.mem.eql(u8, setting.values.items[0], expected);
}

fn hasTideLayoutSetting(tide: TideConfig) bool {
    for (tide.settings.items) |setting| {
        if (std.mem.indexOf(u8, setting.name, "_frame_enabled") != null or
            std.mem.indexOf(u8, setting.name, "_separator_") != null or
            std.mem.endsWith(u8, setting.name, "_prompt_prefix") or
            std.mem.endsWith(u8, setting.name, "_prompt_suffix"))
        {
            return true;
        }
    }
    return false;
}

fn hasFishVariableColor(tide: TideConfig) bool {
    for (tide.settings.items) |setting| {
        if (std.mem.indexOf(u8, setting.name, "_color") == null) continue;
        for (setting.values.items) |value| {
            if (std.mem.startsWith(u8, value, "$")) return true;
        }
    }
    return false;
}

fn tideUnsupportedReason(name: []const u8) []const u8 {
    if (std.mem.eql(u8, name, "bun")) return "No core Bun detector.";
    if (std.mem.eql(u8, name, "java")) return "No core Java detector.";
    if (std.mem.eql(u8, name, "php")) return "No core PHP detector.";
    if (std.mem.eql(u8, name, "ruby")) return "No core Ruby detector.";
    if (std.mem.eql(u8, name, "crystal")) return "No core Crystal detector.";
    if (std.mem.eql(u8, name, "elixir")) return "No core Elixir detector.";
    if (std.mem.eql(u8, name, "zig")) return "No core Zig detector.";
    if (std.mem.eql(u8, name, "direnv")) return "Environment state belongs in a plugin.";
    if (std.mem.eql(u8, name, "distrobox")) return "Container environment state is not imported yet.";
    if (std.mem.eql(u8, name, "toolbox")) return "Container environment state is not imported yet.";
    if (std.mem.eql(u8, name, "nix_shell")) return "Nix shell state is not imported yet.";
    return "No Shisa core mapping; recreate as a plugin or omit.";
}

fn expectTideValues(config: TideConfig, name: []const u8, expected: []const []const u8) !void {
    const setting = config.find(name) orelse return error.MissingTideSetting;
    try std.testing.expectEqual(expected.len, setting.values.items.len);
    for (expected, 0..) |value, index| {
        try std.testing.expectEqualStrings(value, setting.values.items[index]);
    }
}

test "parses tide configure output" {
    const source =
        \\tide_left_prompt_items pwd git newline character
        \\tide_right_prompt_items status cmd_duration time
        \\tide_left_prompt_prefix ''
        \\tide_prompt_transient_enabled false
        \\tide_git_color_branch $_tide_color_green
        \\
    ;
    var config = try parseTideConfig(std.testing.allocator, source);
    defer config.deinit(std.testing.allocator);

    try expectTideValues(config, "tide_left_prompt_items", &.{ "pwd", "git", "newline", "character" });
    try expectTideValues(config, "tide_right_prompt_items", &.{ "status", "cmd_duration", "time" });
    try expectTideValues(config, "tide_left_prompt_prefix", &.{""});
    try expectTideValues(config, "tide_prompt_transient_enabled", &.{"false"});
    try expectTideValues(config, "tide_git_color_branch", &.{"$_tide_color_green"});
}

test "parses tide fish set syntax" {
    const source =
        \\set -g tide_left_prompt_items pwd git
        \\set --global tide_right_prompt_items status cmd_duration
        \\set -gx tide_prompt_transient_enabled true
        \\set -g not_tide ignored
        \\
    ;
    var config = try parseTideConfig(std.testing.allocator, source);
    defer config.deinit(std.testing.allocator);

    try expectTideValues(config, "tide_left_prompt_items", &.{ "pwd", "git" });
    try expectTideValues(config, "tide_right_prompt_items", &.{ "status", "cmd_duration" });
    try expectTideValues(config, "tide_prompt_transient_enabled", &.{"true"});
    try std.testing.expect(config.find("not_tide") == null);
}

test "maps tide items to shisa modules" {
    const source =
        \\tide_left_prompt_items pwd git newline character
        \\tide_right_prompt_items status cmd_duration context jobs node python rustc go aws gcloud kubectl terraform pulumi time bun
        \\
    ;
    var config = try parseTideConfig(std.testing.allocator, source);
    defer config.deinit(std.testing.allocator);
    var imported = StarshipImport{};
    defer imported.deinit(std.testing.allocator);

    try scanTideConfig(std.testing.allocator, config, &imported);

    try std.testing.expect(containsModule(imported, .cwd));
    try std.testing.expect(containsModule(imported, .git_branch));
    try std.testing.expect(containsRightModule(imported, .exit_status));
    try std.testing.expect(containsRightModule(imported, .cmd_duration));
    try std.testing.expect(containsRightModule(imported, .user_host));
    try std.testing.expect(containsRightModule(imported, .jobs));
    try std.testing.expect(containsRightModule(imported, .language_versions));
    try std.testing.expect(containsRightModule(imported, .cloud_ctx));
    try std.testing.expect(containsRightModule(imported, .iac_workspace));
    try std.testing.expect(containsRightModule(imported, .time));
    try std.testing.expect(imported.node);
    try std.testing.expect(imported.python);
    try std.testing.expect(imported.rust);
    try std.testing.expect(imported.go);
    try std.testing.expectEqual(@as(usize, 1), imported.unsupported.items.len);
    try std.testing.expectEqualStrings("bun", imported.unsupported.items[0]);
}

test "imports tide config and migration notes" {
    const source =
        \\tide_left_prompt_items pwd git newline character
        \\tide_right_prompt_items status cmd_duration context jobs bun
        \\tide_prompt_transient_enabled true
        \\tide_left_prompt_frame_enabled true
        \\tide_left_prompt_separator_same_color '>'
        \\tide_git_color_branch $_tide_color_green
        \\
    ;
    const result = try importTideResultAlloc(std.testing.allocator, source);
    defer result.deinit(std.testing.allocator);

    try std.testing.expect(std.mem.indexOf(u8, result.config, "# Tide left items: pwd, git, newline, character") != null);
    try std.testing.expect(std.mem.indexOf(u8, result.config, "# Tide right items: status, cmd_duration, context, jobs, bun") != null);
    try std.testing.expect(std.mem.indexOf(u8, result.config, "modules = [\"cwd\", \"git_branch\"]") != null);
    try std.testing.expect(std.mem.indexOf(u8, result.config, "right_modules = [\"exit_status\", \"cmd_duration\", \"user_host\", \"jobs\"]") != null);
    const notes = result.notes orelse return error.MissingTideNotes;
    try std.testing.expect(std.mem.indexOf(u8, notes, "# Tide Migration Notes") != null);
    try std.testing.expect(std.mem.indexOf(u8, notes, "- `bun`: No core Bun detector.") != null);
    try std.testing.expect(std.mem.indexOf(u8, notes, "`tide_prompt_transient_enabled=true` is not imported") != null);
    try std.testing.expect(std.mem.indexOf(u8, notes, "frame/separator/prefix/suffix") != null);
    try std.testing.expect(std.mem.indexOf(u8, notes, "$_tide_color_*") != null);
}

test "omits tide migration notes for plain left prompt" {
    const source =
        \\tide_left_prompt_items pwd git
        \\
    ;
    const result = try importTideResultAlloc(std.testing.allocator, source);
    defer result.deinit(std.testing.allocator);

    try std.testing.expect(result.notes == null);
}
