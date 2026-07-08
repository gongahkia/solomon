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
const mapP10kElement = common.mapP10kElement;
const containsModule = common.containsModule;
const containsAnyModule = common.containsAnyModule;
const appendLanguage = common.appendLanguage;

const P10kSetting = struct {
    name: []u8,
    values: std.ArrayList([]u8) = .empty,

    fn deinit(self: *P10kSetting, allocator: std.mem.Allocator) void {
        allocator.free(self.name);
        for (self.values.items) |value| allocator.free(value);
        self.values.deinit(allocator);
    }
};

const P10kImport = struct {
    settings: std.ArrayList(P10kSetting) = .empty,

    fn deinit(self: *P10kImport, allocator: std.mem.Allocator) void {
        for (self.settings.items) |*setting| setting.deinit(allocator);
        self.settings.deinit(allocator);
    }

    fn find(self: P10kImport, name: []const u8) ?P10kSetting {
        for (self.settings.items) |setting| {
            if (std.mem.eql(u8, setting.name, name)) return setting;
        }
        return null;
    }
};

fn parseP10kConfig(allocator: std.mem.Allocator, source: []const u8) !P10kImport {
    var imported = P10kImport{};
    errdefer imported.deinit(allocator);

    var active_array: ?usize = null;
    var lines = std.mem.splitScalar(u8, source, '\n');
    while (lines.next()) |raw_line| {
        var line = std.mem.trim(u8, raw_line, " \t\r");
        if (line.len == 0 or line[0] == '#') continue;

        if (active_array) |setting_index| {
            if (std.mem.indexOfScalar(u8, line, ')')) |close_index| {
                try appendP10kWords(allocator, &imported.settings.items[setting_index], line[0..close_index]);
                active_array = null;
            } else {
                try appendP10kWords(allocator, &imported.settings.items[setting_index], line);
            }
            continue;
        }

        const start = std.mem.indexOf(u8, line, "POWERLEVEL9K_") orelse continue;
        line = line[start..];
        const eq_index = std.mem.indexOfScalar(u8, line, '=') orelse continue;
        const key = std.mem.trim(u8, line[0..eq_index], " \t");
        if (!validP10kKey(key)) continue;

        const name = key["POWERLEVEL9K_".len..];
        var setting = P10kSetting{ .name = try allocator.dupe(u8, name) };
        errdefer setting.deinit(allocator);

        var value = std.mem.trim(u8, line[eq_index + 1 ..], " \t");
        if (std.mem.startsWith(u8, value, "(")) {
            value = std.mem.trim(u8, value[1..], " \t");
            if (std.mem.indexOfScalar(u8, value, ')')) |close_index| {
                try appendP10kWords(allocator, &setting, value[0..close_index]);
            } else {
                try appendP10kWords(allocator, &setting, value);
                try imported.settings.append(allocator, setting);
                active_array = imported.settings.items.len - 1;
                continue;
            }
        } else {
            try appendP10kWords(allocator, &setting, value);
        }
        try imported.settings.append(allocator, setting);
    }

    if (active_array != null) return error.UnclosedP10kArray;
    return imported;
}

fn validP10kKey(key: []const u8) bool {
    if (!std.mem.startsWith(u8, key, "POWERLEVEL9K_")) return false;
    for (key) |byte| {
        if (!(std.ascii.isUpper(byte) or std.ascii.isDigit(byte) or byte == '_')) return false;
    }
    return true;
}

fn appendP10kWords(allocator: std.mem.Allocator, setting: *P10kSetting, text: []const u8) !void {
    var index: usize = 0;
    while (index < text.len) {
        while (index < text.len and std.ascii.isWhitespace(text[index])) : (index += 1) {}
        if (index >= text.len or text[index] == '#') break;

        const start = index;
        if (text[index] == '\'' or text[index] == '"') {
            const quote = text[index];
            index += 1;
            const value_start = index;
            while (index < text.len and text[index] != quote) : (index += 1) {}
            if (index >= text.len) return error.UnclosedP10kQuote;
            const owned = try allocator.dupe(u8, text[value_start..index]);
            errdefer allocator.free(owned);
            try setting.values.append(allocator, owned);
            index += 1;
            continue;
        }

        while (index < text.len and !std.ascii.isWhitespace(text[index]) and text[index] != '#') : (index += 1) {}
        var value = text[start..index];
        value = std.mem.trimRight(u8, value, ")");
        if (value.len != 0) {
            const owned = try allocator.dupe(u8, value);
            errdefer allocator.free(owned);
            try setting.values.append(allocator, owned);
        }
    }
}

fn expectP10kValues(imported: P10kImport, name: []const u8, expected: []const []const u8) !void {
    const setting = imported.find(name) orelse return error.MissingP10kSetting;
    try std.testing.expectEqual(expected.len, setting.values.items.len);
    for (expected, 0..) |value, index| {
        try std.testing.expectEqualStrings(value, setting.values.items[index]);
    }
}

test "parses p10k POWERLEVEL9K assignments" {
    const source =
        \\typeset -g POWERLEVEL9K_LEFT_PROMPT_ELEMENTS=(
        \\  dir vcs
        \\  # comment
        \\)
        \\typeset -g POWERLEVEL9K_RIGHT_PROMPT_ELEMENTS=(status command_execution_time)
        \\typeset -g POWERLEVEL9K_INSTANT_PROMPT=verbose
        \\typeset -g POWERLEVEL9K_MODE='nerdfont-complete'
        \\ZSH_THEME=powerlevel10k/powerlevel10k
        \\
    ;
    var imported = try parseP10kConfig(std.testing.allocator, source);
    defer imported.deinit(std.testing.allocator);

    try std.testing.expectEqual(@as(usize, 4), imported.settings.items.len);
    try expectP10kValues(imported, "LEFT_PROMPT_ELEMENTS", &.{ "dir", "vcs" });
    try expectP10kValues(imported, "RIGHT_PROMPT_ELEMENTS", &.{ "status", "command_execution_time" });
    try expectP10kValues(imported, "INSTANT_PROMPT", &.{"verbose"});
    try expectP10kValues(imported, "MODE", &.{"nerdfont-complete"});
}

const P10kImportResult = struct {
    config: []u8,
    notes: ?[]u8 = null,

    fn deinit(self: P10kImportResult, allocator: std.mem.Allocator) void {
        allocator.free(self.config);
        if (self.notes) |notes| allocator.free(notes);
    }
};

pub fn importP10kCmd(allocator: std.mem.Allocator, args: []const []const u8) !void {
    const options = try parseImportArgs(args, true);

    const source = try std.fs.cwd().readFileAlloc(allocator, options.source_path.?, max_config_bytes);
    defer allocator.free(source);

    var plan = try importP10kPlanAlloc(allocator, source);
    defer plan.deinit(allocator);
    try applyImportPlan(allocator, &plan, options);
}

fn importP10kAlloc(allocator: std.mem.Allocator, source: []const u8) ![]u8 {
    const result = try importP10kResultAlloc(allocator, source);
    if (result.notes) |notes| allocator.free(notes);
    return result.config;
}

fn importP10kPlanAlloc(allocator: std.mem.Allocator, source: []const u8) !ImportPlan {
    const result = try importP10kResultAlloc(allocator, source);
    var plan = ImportPlan{
        .target_toml = result.config,
        .source_name = "Powerlevel10k",
        .docs_path = "docs/migration-p10k.md",
    };
    errdefer plan.deinit(allocator);
    if (result.notes) |notes| try addSidecarOwned(allocator, &plan, "migration-notes.md", notes);
    try collectUnmappedKeys(allocator, &plan);
    return plan;
}

fn importP10kResultAlloc(allocator: std.mem.Allocator, source: []const u8) !P10kImportResult {
    var p10k = try parseP10kConfig(allocator, source);
    defer p10k.deinit(allocator);

    var imported = StarshipImport{};
    defer imported.deinit(allocator);

    const left = if (p10k.find("LEFT_PROMPT_ELEMENTS")) |setting| setting.values.items else &.{};
    const right = if (p10k.find("RIGHT_PROMPT_ELEMENTS")) |setting| setting.values.items else &.{};
    const instant_prompt = p10kInstantPrompt(p10k);

    for (left) |element| try mapP10kElement(allocator, element, &imported);
    for (right) |element| try mapP10kElement(allocator, element, &imported);

    if (imported.modules.items.len == 0) {
        inline for (.{ .cwd, .git_branch, .exit_status, .jobs, .cmd_duration, .user_host }) |module_id| {
            try appendModule(allocator, &imported, module_id);
        }
    }

    const config = try renderP10kImportedConfigAlloc(allocator, imported, left, right, instant_prompt);
    errdefer allocator.free(config);
    const notes = try renderP10kMigrationNotesAlloc(allocator, imported);
    errdefer if (notes) |owned| allocator.free(owned);
    return .{ .config = config, .notes = notes };
}

fn p10kInstantPrompt(imported: P10kImport) ?[]const u8 {
    const setting = imported.find("INSTANT_PROMPT") orelse return null;
    if (setting.values.items.len == 0) return null;
    return setting.values.items[0];
}

fn p10kInstantEnabled(value: []const u8) bool {
    return !(std.mem.eql(u8, value, "off") or std.mem.eql(u8, value, "false") or std.mem.eql(u8, value, "0") or std.mem.eql(u8, value, "no"));
}

fn renderP10kImportedConfigAlloc(allocator: std.mem.Allocator, imported: StarshipImport, left: []const []u8, right: []const []u8, instant_prompt: ?[]const u8) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);

    try out.appendSlice(allocator, "version = 1\n");
    try out.appendSlice(allocator, "theme = \"plain\"\n\n");
    try appendP10kLayoutComment(allocator, &out, "left", left);
    try appendP10kLayoutComment(allocator, &out, "right", right);
    if (instant_prompt) |value| {
        try cli_util.appendFmt(allocator, &out, "# Powerlevel10k instant_prompt: {s}\n", .{value});
        try cli_util.appendFmt(allocator, &out, "# Shisa instant prompt: SHISA_INSTANT={d}\n", .{@intFromBool(p10kInstantEnabled(value))});
    }
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
        try out.appendSlice(allocator, "\n# Unsupported Powerlevel10k elements: ");
        for (imported.unsupported.items, 0..) |name, index| {
            if (index != 0) try out.appendSlice(allocator, ", ");
            try out.appendSlice(allocator, name);
        }
        try out.append(allocator, '\n');
    }

    return try out.toOwnedSlice(allocator);
}

fn appendP10kLayoutComment(allocator: std.mem.Allocator, out: *std.ArrayList(u8), side: []const u8, elements: []const []u8) !void {
    try cli_util.appendFmt(allocator, out, "# Powerlevel10k {s} elements: ", .{side});
    for (elements, 0..) |element, index| {
        if (index != 0) try out.appendSlice(allocator, ", ");
        try out.appendSlice(allocator, element);
    }
    try out.append(allocator, '\n');
}

fn renderP10kMigrationNotesAlloc(allocator: std.mem.Allocator, imported: StarshipImport) !?[]u8 {
    if (imported.unsupported.items.len == 0) return null;

    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);

    try out.appendSlice(allocator, "# Powerlevel10k Migration Notes\n\n");
    try out.appendSlice(allocator, "## Unsupported Elements\n\n");
    for (imported.unsupported.items) |name| {
        try cli_util.appendFmt(allocator, &out, "- `{s}`: {s}\n", .{ name, p10kUnsupportedReason(name) });
    }
    return try out.toOwnedSlice(allocator);
}

fn p10kUnsupportedReason(name: []const u8) []const u8 {
    if (std.mem.eql(u8, name, "public_ip")) return "No core public-IP module; recreate as a plugin or omit.";
    if (std.mem.eql(u8, name, "ip")) return "No core local-IP module; recreate as a plugin or omit.";
    if (std.mem.eql(u8, name, "battery")) return "No core battery module; recreate as a plugin or omit.";
    if (std.mem.eql(u8, name, "ram")) return "No core RAM module; recreate as a plugin or omit.";
    if (std.mem.eql(u8, name, "load")) return "No core load-average module; recreate as a plugin or omit.";
    if (std.mem.eql(u8, name, "todo")) return "No core todo module; recreate as a plugin or omit.";
    return "No Shisa core mapping; recreate as a plugin or omit.";
}

test "maps p10k elements to shisa modules" {
    var imported = StarshipImport{};
    defer imported.deinit(std.testing.allocator);

    inline for (.{ "os_icon", "dir", "vcs", "virtualenv", "nodeenv", "go_version", "rust_version", "status", "background_jobs", "command_execution_time", "context", "aws", "time", "public_ip" }) |element| {
        try mapP10kElement(std.testing.allocator, element, &imported);
    }

    try std.testing.expect(containsModule(imported, .cwd));
    try std.testing.expect(containsModule(imported, .git_branch));
    try std.testing.expect(containsModule(imported, .language_versions));
    try std.testing.expect(containsModule(imported, .exit_status));
    try std.testing.expect(containsModule(imported, .jobs));
    try std.testing.expect(containsModule(imported, .cmd_duration));
    try std.testing.expect(containsModule(imported, .user_host));
    try std.testing.expect(containsModule(imported, .cloud_ctx));
    try std.testing.expect(containsModule(imported, .time));
    try std.testing.expect(imported.python);
    try std.testing.expect(imported.node);
    try std.testing.expect(imported.go);
    try std.testing.expect(imported.rust);
    try std.testing.expectEqual(@as(usize, 1), imported.unsupported.items.len);
    try std.testing.expectEqualStrings("public_ip", imported.unsupported.items[0]);
}

test "imports p10k left and right layout" {
    const source =
        \\typeset -g POWERLEVEL9K_LEFT_PROMPT_ELEMENTS=(dir vcs)
        \\typeset -g POWERLEVEL9K_RIGHT_PROMPT_ELEMENTS=(status command_execution_time time)
        \\
    ;
    const output = try importP10kAlloc(std.testing.allocator, source);
    defer std.testing.allocator.free(output);

    try std.testing.expect(std.mem.indexOf(u8, output, "# Powerlevel10k left elements: dir, vcs") != null);
    try std.testing.expect(std.mem.indexOf(u8, output, "# Powerlevel10k right elements: status, command_execution_time, time") != null);
    try std.testing.expect(std.mem.indexOf(u8, output, "modules = [\"cwd\", \"git_branch\", \"exit_status\", \"cmd_duration\", \"time\"]") != null);
}

test "imports p10k instant prompt mapping" {
    const source =
        \\typeset -g POWERLEVEL9K_LEFT_PROMPT_ELEMENTS=(dir)
        \\typeset -g POWERLEVEL9K_INSTANT_PROMPT=quiet
        \\
    ;
    const output = try importP10kAlloc(std.testing.allocator, source);
    defer std.testing.allocator.free(output);

    try std.testing.expect(std.mem.indexOf(u8, output, "# Powerlevel10k instant_prompt: quiet") != null);
    try std.testing.expect(std.mem.indexOf(u8, output, "# Shisa instant prompt: SHISA_INSTANT=1") != null);
}

test "imports disabled p10k instant prompt mapping" {
    const source =
        \\typeset -g POWERLEVEL9K_LEFT_PROMPT_ELEMENTS=(dir)
        \\typeset -g POWERLEVEL9K_INSTANT_PROMPT=off
        \\
    ;
    const output = try importP10kAlloc(std.testing.allocator, source);
    defer std.testing.allocator.free(output);

    try std.testing.expect(std.mem.indexOf(u8, output, "# Powerlevel10k instant_prompt: off") != null);
    try std.testing.expect(std.mem.indexOf(u8, output, "# Shisa instant prompt: SHISA_INSTANT=0") != null);
}

test "imports p10k unsupported elements into migration notes" {
    const source =
        \\typeset -g POWERLEVEL9K_LEFT_PROMPT_ELEMENTS=(dir public_ip battery weird_segment)
        \\
    ;
    const result = try importP10kResultAlloc(std.testing.allocator, source);
    defer result.deinit(std.testing.allocator);

    try std.testing.expect(std.mem.indexOf(u8, result.config, "Unsupported Powerlevel10k elements: public_ip, battery, weird_segment") != null);
    const notes = result.notes orelse return error.MissingP10kNotes;
    try std.testing.expect(std.mem.indexOf(u8, notes, "# Powerlevel10k Migration Notes") != null);
    try std.testing.expect(std.mem.indexOf(u8, notes, "- `public_ip`: No core public-IP module") != null);
    try std.testing.expect(std.mem.indexOf(u8, notes, "- `battery`: No core battery module") != null);
    try std.testing.expect(std.mem.indexOf(u8, notes, "- `weird_segment`: No Shisa core mapping") != null);
}

test "omits p10k migration notes when all elements map" {
    const source =
        \\typeset -g POWERLEVEL9K_LEFT_PROMPT_ELEMENTS=(dir vcs)
        \\
    ;
    const result = try importP10kResultAlloc(std.testing.allocator, source);
    defer result.deinit(std.testing.allocator);

    try std.testing.expect(result.notes == null);
}
