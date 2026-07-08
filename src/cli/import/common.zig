const std = @import("std");
const cli_util = @import("../util.zig");
const shisa_config = @import("../../config.zig");

pub const max_config_bytes = 1024 * 1024;

pub const ImportArgs = struct {
    source_path: ?[]const u8 = null,
    output_path: ?[]const u8 = null,
    dry_run: bool = false,
    diff: bool = false,
    warn_unmapped: bool = true,
};

pub const ImportSidecar = struct {
    name: []const u8,
    data: []u8,
};

pub const ImportPlan = struct {
    target_toml: []u8,
    source_name: []const u8,
    docs_path: []const u8,
    sidecars: std.ArrayList(ImportSidecar) = .empty,
    unmapped_keys: std.ArrayList([]u8) = .empty,

    pub fn deinit(self: *ImportPlan, allocator: std.mem.Allocator) void {
        allocator.free(self.target_toml);
        for (self.sidecars.items) |sidecar| allocator.free(sidecar.data);
        self.sidecars.deinit(allocator);
        for (self.unmapped_keys.items) |key| allocator.free(key);
        self.unmapped_keys.deinit(allocator);
        self.* = undefined;
    }
};

pub fn parseImportArgs(args: []const []const u8, source_required: bool) !ImportArgs {
    var parsed = ImportArgs{};
    var i: usize = 0;
    while (i < args.len) : (i += 1) {
        const arg = args[i];
        if (std.mem.eql(u8, arg, "--dry-run")) {
            parsed.dry_run = true;
        } else if (std.mem.eql(u8, arg, "--diff")) {
            parsed.diff = true;
        } else if (std.mem.eql(u8, arg, "--warn-unmapped")) {
            parsed.warn_unmapped = true;
        } else if (std.mem.eql(u8, arg, "--no-warn-unmapped")) {
            parsed.warn_unmapped = false;
        } else if (std.mem.eql(u8, arg, "--output")) {
            parsed.output_path = try cli_util.nextValue(args, &i);
        } else if (std.mem.startsWith(u8, arg, "--")) {
            return error.UnknownImportArgument;
        } else if (source_required and parsed.source_path == null) {
            parsed.source_path = arg;
        } else {
            return error.UnknownImportArgument;
        }
    }
    if (source_required and parsed.source_path == null) return error.MissingImportSource;
    if (parsed.dry_run and parsed.diff) return error.ConflictingImportModes;
    return parsed;
}

pub fn applyImportPlan(allocator: std.mem.Allocator, plan: *ImportPlan, options: ImportArgs) !void {
    if (options.dry_run) {
        try std.fs.File.stdout().writeAll(plan.target_toml);
        if (options.warn_unmapped) try writeUnmappedWarnings(allocator, plan.*);
        return;
    }

    const target_path = if (options.output_path) |path| try allocator.dupe(u8, path) else try cli_util.defaultConfigPath(allocator);
    defer allocator.free(target_path);

    if (options.diff) {
        const current = try readFileIfPresentAlloc(allocator, target_path);
        defer allocator.free(current);
        try writeUnifiedDiff(allocator, target_path, current, "imported", plan.target_toml);
        if (options.warn_unmapped) try writeUnmappedWarnings(allocator, plan.*);
        return;
    }

    try writeFilePath(target_path, plan.target_toml);
    for (plan.sidecars.items) |sidecar| {
        const sidecar_path = try sidecarPathAlloc(allocator, target_path, sidecar.name);
        defer allocator.free(sidecar_path);
        try writeFilePath(sidecar_path, sidecar.data);
    }
    if (options.warn_unmapped) try writeUnmappedWarnings(allocator, plan.*);
}

pub fn addSidecarOwned(allocator: std.mem.Allocator, plan: *ImportPlan, name: []const u8, data: []u8) !void {
    errdefer allocator.free(data);
    try plan.sidecars.append(allocator, .{ .name = name, .data = data });
}

pub fn collectUnmappedKeys(allocator: std.mem.Allocator, plan: *ImportPlan) !void {
    try collectUnsupportedCommentKeys(allocator, plan, plan.target_toml);
    for (plan.sidecars.items) |sidecar| {
        if (std.mem.eql(u8, sidecar.name, "migration-notes.md")) try collectMigrationNoteKeys(allocator, plan, sidecar.data);
    }
    std.mem.sort([]u8, plan.unmapped_keys.items, {}, stringLessThan);
}

fn collectUnsupportedCommentKeys(allocator: std.mem.Allocator, plan: *ImportPlan, text: []const u8) !void {
    var lines = std.mem.splitScalar(u8, text, '\n');
    while (lines.next()) |line| {
        if (!std.mem.startsWith(u8, line, "# Unsupported ")) continue;
        const colon = std.mem.indexOfScalar(u8, line, ':') orelse continue;
        var names = std.mem.splitScalar(u8, line[colon + 1 ..], ',');
        while (names.next()) |raw_name| {
            const name = std.mem.trim(u8, raw_name, " \t\r");
            if (name.len != 0) try appendUniqueString(allocator, &plan.unmapped_keys, name);
        }
    }
}

fn collectMigrationNoteKeys(allocator: std.mem.Allocator, plan: *ImportPlan, text: []const u8) !void {
    var lines = std.mem.splitScalar(u8, text, '\n');
    while (lines.next()) |line| {
        if (!std.mem.startsWith(u8, line, "- `")) continue;
        const rest = line[3..];
        const end = std.mem.indexOfScalar(u8, rest, '`') orelse continue;
        const key = std.mem.trim(u8, rest[0..end], " \t\r");
        if (key.len != 0) try appendUniqueString(allocator, &plan.unmapped_keys, key);
    }
}

fn appendUniqueString(allocator: std.mem.Allocator, list: *std.ArrayList([]u8), value: []const u8) !void {
    for (list.items) |existing| {
        if (std.mem.eql(u8, existing, value)) return;
    }
    const owned = try allocator.dupe(u8, value);
    errdefer allocator.free(owned);
    try list.append(allocator, owned);
}

fn stringLessThan(_: void, lhs: []u8, rhs: []u8) bool {
    return std.mem.lessThan(u8, lhs, rhs);
}

fn writeUnmappedWarnings(allocator: std.mem.Allocator, plan: ImportPlan) !void {
    if (plan.unmapped_keys.items.len == 0) return;
    try std.fs.File.stdout().writeAll("\n# Migration warnings\n");
    for (plan.unmapped_keys.items) |key| {
        try stdoutFmt(allocator, "# - `{s}` unmapped from {s}; preserve with a custom module or plugin.\n", .{ key, plan.source_name });
    }
    try stdoutFmt(allocator, "# See {s}\n", .{plan.docs_path});
}

fn readFileIfPresentAlloc(allocator: std.mem.Allocator, path: []const u8) ![]u8 {
    var file = if (std.fs.path.isAbsolute(path))
        std.fs.openFileAbsolute(path, .{}) catch |err| switch (err) {
            error.FileNotFound => return allocator.dupe(u8, ""),
            else => return err,
        }
    else
        std.fs.cwd().openFile(path, .{}) catch |err| switch (err) {
            error.FileNotFound => return allocator.dupe(u8, ""),
            else => return err,
        };
    defer file.close();
    return file.readToEndAlloc(allocator, max_config_bytes);
}

fn writeFilePath(path: []const u8, data: []const u8) !void {
    if (std.fs.path.dirname(path)) |parent| try std.fs.cwd().makePath(parent);
    var file = if (std.fs.path.isAbsolute(path))
        try std.fs.createFileAbsolute(path, .{ .truncate = true, .mode = 0o600 })
    else
        try std.fs.cwd().createFile(path, .{ .truncate = true, .mode = 0o600 });
    defer file.close();
    try file.writeAll(data);
}

fn sidecarPathAlloc(allocator: std.mem.Allocator, target_path: []const u8, name: []const u8) ![]u8 {
    if (std.fs.path.dirname(target_path)) |parent| return std.fs.path.join(allocator, &.{ parent, name });
    return allocator.dupe(u8, name);
}

fn writeUnifiedDiff(allocator: std.mem.Allocator, old_label: []const u8, old_text: []const u8, new_label: []const u8, new_text: []const u8) !void {
    if (std.mem.eql(u8, old_text, new_text)) return;
    try stdoutFmt(allocator, "--- {s}\n+++ {s}\n@@ -1,{d} +1,{d} @@\n", .{
        old_label,
        new_label,
        diffLineCount(old_text),
        diffLineCount(new_text),
    });
    try writeDiffLines(allocator, '-', old_text);
    try writeDiffLines(allocator, '+', new_text);
}

fn diffLineCount(text: []const u8) usize {
    if (text.len == 0) return 0;
    var count: usize = 0;
    for (text) |byte| {
        if (byte == '\n') count += 1;
    }
    if (text[text.len - 1] != '\n') count += 1;
    return count;
}

fn writeDiffLines(allocator: std.mem.Allocator, prefix: u8, text: []const u8) !void {
    var offset: usize = 0;
    while (offset < text.len) {
        const rest = text[offset..];
        const line_len = std.mem.indexOfScalar(u8, rest, '\n') orelse rest.len;
        try stdoutFmt(allocator, "{c}{s}\n", .{ prefix, rest[0..line_len] });
        offset += line_len + @intFromBool(line_len < rest.len);
    }
}

fn stdoutFmt(allocator: std.mem.Allocator, comptime format: []const u8, args: anytype) !void {
    const text = try std.fmt.allocPrint(allocator, format, args);
    defer allocator.free(text);
    try std.fs.File.stdout().writeAll(text);
}

pub fn appendTomlString(allocator: std.mem.Allocator, out: *std.ArrayList(u8), value: []const u8) !void {
    try out.append(allocator, '"');
    for (value) |byte| {
        switch (byte) {
            '\\' => try out.appendSlice(allocator, "\\\\"),
            '"' => try out.appendSlice(allocator, "\\\""),
            '\n' => try out.appendSlice(allocator, "\\n"),
            '\r' => try out.appendSlice(allocator, "\\r"),
            '\t' => try out.appendSlice(allocator, "\\t"),
            else => try out.append(allocator, byte),
        }
    }
    try out.append(allocator, '"');
}

pub const StarshipImport = struct {
    modules: std.ArrayList(shisa_config.ModuleId) = .empty,
    right_modules: std.ArrayList(shisa_config.ModuleId) = .empty,
    unsupported: std.ArrayList([]const u8) = .empty,
    python: bool = false,
    node: bool = false,
    rust: bool = false,
    go: bool = false,

    pub fn deinit(self: *StarshipImport, allocator: std.mem.Allocator) void {
        self.modules.deinit(allocator);
        self.right_modules.deinit(allocator);
        for (self.unsupported.items) |name| allocator.free(name);
        self.unsupported.deinit(allocator);
    }
};

pub fn mapStarshipModule(allocator: std.mem.Allocator, name: []const u8, imported: *StarshipImport) !void {
    if (std.mem.eql(u8, name, "directory")) {
        try appendModule(allocator, imported, .cwd);
    } else if (std.mem.eql(u8, name, "git_branch") or std.mem.eql(u8, name, "git_status") or std.mem.eql(u8, name, "git_commit") or std.mem.eql(u8, name, "git_state")) {
        try appendModule(allocator, imported, .git_branch);
    } else if (std.mem.eql(u8, name, "python")) {
        imported.python = true;
        try appendModule(allocator, imported, .language_versions);
    } else if (std.mem.eql(u8, name, "nodejs")) {
        imported.node = true;
        try appendModule(allocator, imported, .language_versions);
    } else if (std.mem.eql(u8, name, "rust")) {
        imported.rust = true;
        try appendModule(allocator, imported, .language_versions);
    } else if (std.mem.eql(u8, name, "golang")) {
        imported.go = true;
        try appendModule(allocator, imported, .language_versions);
    } else if (std.mem.eql(u8, name, "status")) {
        try appendModule(allocator, imported, .exit_status);
    } else if (std.mem.eql(u8, name, "jobs")) {
        try appendModule(allocator, imported, .jobs);
    } else if (std.mem.eql(u8, name, "cmd_duration")) {
        try appendModule(allocator, imported, .cmd_duration);
    } else if (std.mem.eql(u8, name, "username") or std.mem.eql(u8, name, "hostname")) {
        try appendModule(allocator, imported, .user_host);
    } else if (std.mem.eql(u8, name, "time")) {
        try appendModule(allocator, imported, .time);
    } else if (!isIgnoredStarshipModule(name)) {
        try appendUnsupported(allocator, imported, name);
    }
}

pub fn mapP10kElement(allocator: std.mem.Allocator, name: []const u8, imported: *StarshipImport) !void {
    if (std.mem.eql(u8, name, "dir")) {
        try appendModule(allocator, imported, .cwd);
    } else if (std.mem.eql(u8, name, "vcs")) {
        try appendModule(allocator, imported, .git_branch);
    } else if (std.mem.eql(u8, name, "status")) {
        try appendModule(allocator, imported, .exit_status);
    } else if (std.mem.eql(u8, name, "background_jobs")) {
        try appendModule(allocator, imported, .jobs);
    } else if (std.mem.eql(u8, name, "command_execution_time")) {
        try appendModule(allocator, imported, .cmd_duration);
    } else if (std.mem.eql(u8, name, "context")) {
        try appendModule(allocator, imported, .user_host);
    } else if (std.mem.eql(u8, name, "time")) {
        try appendModule(allocator, imported, .time);
    } else if (std.mem.eql(u8, name, "aws") or std.mem.eql(u8, name, "gcloud") or std.mem.eql(u8, name, "azure") or std.mem.eql(u8, name, "kubecontext")) {
        try appendModule(allocator, imported, .cloud_ctx);
    } else if (std.mem.eql(u8, name, "virtualenv") or std.mem.eql(u8, name, "pyenv")) {
        imported.python = true;
        try appendModule(allocator, imported, .language_versions);
    } else if (std.mem.eql(u8, name, "nodeenv") or std.mem.eql(u8, name, "nodenv") or std.mem.eql(u8, name, "nvm")) {
        imported.node = true;
        try appendModule(allocator, imported, .language_versions);
    } else if (std.mem.eql(u8, name, "goenv") or std.mem.eql(u8, name, "go_version")) {
        imported.go = true;
        try appendModule(allocator, imported, .language_versions);
    } else if (std.mem.eql(u8, name, "rust_version")) {
        imported.rust = true;
        try appendModule(allocator, imported, .language_versions);
    } else if (!isIgnoredP10kElement(name)) {
        try appendUnsupported(allocator, imported, name);
    }
}

fn isIgnoredP10kElement(name: []const u8) bool {
    return std.mem.eql(u8, name, "os_icon") or
        std.mem.eql(u8, name, "prompt_char") or
        std.mem.eql(u8, name, "newline");
}

fn isIgnoredStarshipModule(name: []const u8) bool {
    return std.mem.eql(u8, name, "character") or
        std.mem.eql(u8, name, "line_break") or
        std.mem.eql(u8, name, "fill") or
        std.mem.eql(u8, name, "os") or
        std.mem.eql(u8, name, "shell");
}

pub fn appendModule(allocator: std.mem.Allocator, imported: *StarshipImport, module_id: shisa_config.ModuleId) !void {
    try appendModuleTo(allocator, &imported.modules, module_id);
}

pub fn appendRightModule(allocator: std.mem.Allocator, imported: *StarshipImport, module_id: shisa_config.ModuleId) !void {
    try appendModuleTo(allocator, &imported.right_modules, module_id);
}

pub fn appendTideModule(allocator: std.mem.Allocator, imported: *StarshipImport, module_id: shisa_config.ModuleId, right: bool) !void {
    if (right) try appendRightModule(allocator, imported, module_id) else try appendModule(allocator, imported, module_id);
}

pub fn appendModuleTo(allocator: std.mem.Allocator, modules: *std.ArrayList(shisa_config.ModuleId), module_id: shisa_config.ModuleId) !void {
    for (modules.items) |existing| {
        if (existing == module_id) return;
    }
    try modules.append(allocator, module_id);
}

pub fn appendUnsupported(allocator: std.mem.Allocator, imported: *StarshipImport, name: []const u8) !void {
    for (imported.unsupported.items) |existing| {
        if (std.mem.eql(u8, existing, name)) return;
    }
    const owned = try allocator.dupe(u8, name);
    errdefer allocator.free(owned);
    try imported.unsupported.append(allocator, owned);
}

pub fn renderImportedConfigAlloc(allocator: std.mem.Allocator, imported: StarshipImport) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);

    try out.appendSlice(allocator, "version = 1\n");
    try out.appendSlice(allocator, "theme = \"plain\"\n\n");
    try out.appendSlice(allocator, "[prompt]\nmodules = [");
    for (imported.modules.items, 0..) |module_id, index| {
        if (index != 0) try out.appendSlice(allocator, ", ");
        try cli_util.appendFmt(allocator, &out, "\"{s}\"", .{shisa_config.moduleIdName(module_id)});
    }
    try out.appendSlice(allocator, "]\n");

    if (containsModule(imported, .language_versions) and (imported.python or imported.node or imported.rust or imported.go)) {
        try out.appendSlice(allocator, "\n[modules.language_versions]\ndetect = [");
        var count: usize = 0;
        if (imported.python) try appendLanguage(allocator, &out, &count, "python");
        if (imported.node) try appendLanguage(allocator, &out, &count, "node");
        if (imported.rust) try appendLanguage(allocator, &out, &count, "rust");
        if (imported.go) try appendLanguage(allocator, &out, &count, "go");
        try out.appendSlice(allocator, "]\n");
    }

    if (containsModule(imported, .time)) {
        try out.appendSlice(allocator, "\n[modules.time]\nformat = \"24h\"\nutc = true\n");
    }

    if (imported.unsupported.items.len != 0) {
        try out.appendSlice(allocator, "\n# Unsupported Starship modules: ");
        for (imported.unsupported.items, 0..) |name, index| {
            if (index != 0) try out.appendSlice(allocator, ", ");
            try out.appendSlice(allocator, name);
        }
        try out.append(allocator, '\n');
    }

    return out.toOwnedSlice(allocator);
}

pub fn containsModule(imported: StarshipImport, module_id: shisa_config.ModuleId) bool {
    for (imported.modules.items) |existing| {
        if (existing == module_id) return true;
    }
    return false;
}

pub fn containsRightModule(imported: StarshipImport, module_id: shisa_config.ModuleId) bool {
    for (imported.right_modules.items) |existing| {
        if (existing == module_id) return true;
    }
    return false;
}

pub fn containsAnyModule(imported: StarshipImport, module_id: shisa_config.ModuleId) bool {
    return containsModule(imported, module_id) or containsRightModule(imported, module_id);
}

pub fn appendLanguage(allocator: std.mem.Allocator, out: *std.ArrayList(u8), count: *usize, name: []const u8) !void {
    if (count.* != 0) try out.appendSlice(allocator, ", ");
    count.* += 1;
    try cli_util.appendFmt(allocator, out, "\"{s}\"", .{name});
}
