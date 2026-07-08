const std = @import("std");
const cli_util = @import("util.zig");
const shisa_config = @import("../config.zig");

/// static help text printed by shisa config set --help.
pub const help_text =
    \\usage: shisa config set locale=<locale|auto>
    \\
    \\commands:
    \\  set locale=<locale|auto> set locale override; auto uses LC_ALL, LC_CTYPE, then LANG
    \\
;

/// parsed options for shisa init.
/// shell_preferences is null unless a shell preference flag was supplied.
pub const InitConfig = struct {
    /// writes the accessibility-first default config when true.
    a11y: bool = false,
    /// optional shell.env preferences to write next to shisa.toml.
    shell_preferences: ?ShellPreferences = null,
};

/// shell.env preferences emitted by shisa init shell flags.
/// string fields are borrowed from CLI args or static defaults.
pub const ShellPreferences = struct {
    /// enables command-completion bell output when true.
    cmd_complete_bell: bool = false,
    /// selects bell, terminal, osc9, notify-send, or macos completion signaling.
    cmd_complete_bell_mode: []const u8 = "bell",
    /// minimum command duration before completion signaling.
    cmd_complete_bell_threshold_ms: u64 = 10000,
    /// message emitted by completion signaling; must not contain newlines.
    cmd_complete_bell_message: []const u8 = "shisa: command complete",
};

/// handles shisa init and writes default config and optional shell preferences.
/// args is borrowed for the duration of the call; stdout receives written paths.
/// ownership: all temporary allocations are freed before return.
/// errors: UnknownInitArgument, InvalidCmdCompleteBellMode, InvalidCmdCompleteBellMessage, PathAlreadyExists, filesystem write errors, parseInt errors, and allocation errors.
pub fn initCmd(allocator: std.mem.Allocator, args: []const []const u8) !void {
    const config = try parseInitArgs(args);

    const path = try cli_util.defaultConfigPath(allocator);
    defer allocator.free(path);
    if (std.fs.path.dirname(path)) |parent| {
        try std.fs.cwd().makePath(parent);
    }

    var wrote_config = false;
    if (std.fs.createFileAbsolute(path, .{ .exclusive = true })) |file| {
        var config_file = file;
        defer config_file.close();
        try config_file.writeAll(if (config.a11y) shisa_config.a11y_config_text else shisa_config.default_config_text);
        wrote_config = true;
    } else |err| switch (err) {
        error.PathAlreadyExists => {
            if (config.shell_preferences == null or config.a11y) return err;
        },
        else => return err,
    }

    var wrote_shell_preferences = false;
    var shell_path_for_message: ?[]u8 = null;
    defer if (shell_path_for_message) |shell_path| allocator.free(shell_path);
    if (config.shell_preferences) |preferences| {
        const shell_path = try shellPreferencesPathAlloc(allocator, path);
        errdefer allocator.free(shell_path);
        const source = try renderShellPreferencesAlloc(allocator, preferences);
        defer allocator.free(source);
        var shell_file = try std.fs.createFileAbsolute(shell_path, .{ .truncate = true });
        defer shell_file.close();
        try shell_file.writeAll(source);
        shell_path_for_message = shell_path;
        wrote_shell_preferences = true;
    }

    const message = if (wrote_config and wrote_shell_preferences)
        try std.fmt.allocPrint(allocator, "wrote {s}\nwrote {s}\n", .{ path, shell_path_for_message.? })
    else if (wrote_shell_preferences)
        try std.fmt.allocPrint(allocator, "wrote {s}\n", .{shell_path_for_message.?})
    else
        try std.fmt.allocPrint(allocator, "wrote {s}\n", .{path});
    defer allocator.free(message);
    try std.fs.File.stdout().writeAll(message);
}

fn parseInitArgs(args: []const []const u8) !InitConfig {
    var config: InitConfig = .{};
    var prefs: ShellPreferences = .{};
    var seen_prefs = false;
    var i: usize = 0;
    while (i < args.len) : (i += 1) {
        const arg = args[i];
        if (std.mem.eql(u8, arg, "--a11y")) {
            config.a11y = true;
        } else if (std.mem.eql(u8, arg, "--cmd-complete-bell")) {
            prefs.cmd_complete_bell = true;
            seen_prefs = true;
        } else if (std.mem.eql(u8, arg, "--cmd-complete-bell-mode")) {
            i += 1;
            if (i >= args.len) return error.UnknownInitArgument;
            if (!validCmdCompleteBellMode(args[i])) return error.InvalidCmdCompleteBellMode;
            prefs.cmd_complete_bell_mode = args[i];
            prefs.cmd_complete_bell = true;
            seen_prefs = true;
        } else if (std.mem.eql(u8, arg, "--cmd-complete-bell-threshold-ms")) {
            i += 1;
            if (i >= args.len) return error.UnknownInitArgument;
            prefs.cmd_complete_bell_threshold_ms = try std.fmt.parseInt(u64, args[i], 10);
            prefs.cmd_complete_bell = true;
            seen_prefs = true;
        } else if (std.mem.eql(u8, arg, "--cmd-complete-bell-message")) {
            i += 1;
            if (i >= args.len) return error.UnknownInitArgument;
            if (std.mem.indexOfAny(u8, args[i], "\r\n") != null) return error.InvalidCmdCompleteBellMessage;
            prefs.cmd_complete_bell_message = args[i];
            prefs.cmd_complete_bell = true;
            seen_prefs = true;
        } else {
            return error.UnknownInitArgument;
        }
    }
    if (seen_prefs) config.shell_preferences = prefs;
    return config;
}

fn validCmdCompleteBellMode(mode: []const u8) bool {
    return std.mem.eql(u8, mode, "bell") or
        std.mem.eql(u8, mode, "terminal") or
        std.mem.eql(u8, mode, "osc9") or
        std.mem.eql(u8, mode, "notify-send") or
        std.mem.eql(u8, mode, "macos");
}

fn shellPreferencesPathAlloc(allocator: std.mem.Allocator, config_path: []const u8) ![]u8 {
    const dir = std.fs.path.dirname(config_path) orelse return error.MissingConfigDir;
    return std.fmt.allocPrint(allocator, "{s}/shell.env", .{dir});
}

fn renderShellPreferencesAlloc(allocator: std.mem.Allocator, preferences: ShellPreferences) ![]u8 {
    return std.fmt.allocPrint(
        allocator,
        "SHISA_CMD_COMPLETE_BELL={d}\nSHISA_CMD_COMPLETE_BELL_MODE={s}\nSHISA_CMD_COMPLETE_BELL_THRESHOLD_MS={d}\nSHISA_CMD_COMPLETE_BELL_MESSAGE={s}\n",
        .{
            @intFromBool(preferences.cmd_complete_bell),
            preferences.cmd_complete_bell_mode,
            preferences.cmd_complete_bell_threshold_ms,
            preferences.cmd_complete_bell_message,
        },
    );
}

/// parsed locale assignment for shisa config set.
/// locale aliases the CLI argument and must not be freed.
pub const Set = struct {
    /// locale override accepted by config validation.
    locale: []const u8,
};

/// handles shisa config subcommands.
/// args is borrowed for the duration of the call; stdout/stderr receive command output.
/// ownership: all temporary allocations are freed before return.
/// errors: UnknownConfigCommand, UnknownConfigSetArgument, InvalidLocale, InvalidConfig, filesystem write errors, and allocation errors.
pub fn setCmd(allocator: std.mem.Allocator, args: []const []const u8) !void {
    if (args.len == 0 or std.mem.eql(u8, args[0], "--help") or std.mem.eql(u8, args[0], "-h")) {
        try std.fs.File.stdout().writeAll(help_text);
        return;
    }
    if (std.mem.eql(u8, args[0], "set")) {
        const set = try parseSetArgs(args[1..]);
        try applySet(allocator, set);
        return;
    }
    return error.UnknownConfigCommand;
}

fn parseSetArgs(args: []const []const u8) !Set {
    if (args.len != 1) return error.UnknownConfigSetArgument;
    const prefix = "locale=";
    const arg = args[0];
    if (!std.mem.startsWith(u8, arg, prefix)) return error.UnknownConfigSetArgument;
    const locale = arg[prefix.len..];
    if (!shisa_config.isValidLocaleOverride(locale)) return error.InvalidLocale;
    return .{ .locale = locale };
}

fn applySet(allocator: std.mem.Allocator, set: Set) !void {
    const path = try cli_util.defaultConfigPath(allocator);
    defer allocator.free(path);
    const source = try cli_util.readConfigOrDefault(allocator, path);
    defer allocator.free(source);

    const updated = try upsertTopLevelStringKeyAlloc(allocator, source, "locale", set.locale);
    defer allocator.free(updated);

    var diagnostic: shisa_config.Diagnostic = .{};
    var parsed = shisa_config.parse(allocator, updated, &diagnostic) catch |err| switch (err) {
        error.InvalidConfig => {
            const message = try std.fmt.allocPrint(allocator, "{s}:{d}:{d}: {s}\n", .{ path, diagnostic.line, diagnostic.column, diagnostic.message });
            defer allocator.free(message);
            try std.fs.File.stderr().writeAll(message);
            return err;
        },
        else => return err,
    };
    parsed.deinit(allocator);

    if (std.fs.path.dirname(path)) |parent| try std.fs.cwd().makePath(parent);
    var file = try std.fs.createFileAbsolute(path, .{ .truncate = true, .mode = 0o600 });
    defer file.close();
    try file.writeAll(updated);

    const message = try std.fmt.allocPrint(allocator, "set locale={s}\n", .{set.locale});
    defer allocator.free(message);
    try std.fs.File.stdout().writeAll(message);
}

fn upsertTopLevelStringKeyAlloc(allocator: std.mem.Allocator, source: []const u8, key: []const u8, value: []const u8) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    errdefer out.deinit(allocator);
    const rendered = try std.fmt.allocPrint(allocator, "{s} = \"{s}\"\n", .{ key, value });
    defer allocator.free(rendered);

    var offset: usize = 0;
    var in_root = true;
    var wrote = false;
    while (offset < source.len) {
        const rest = source[offset..];
        const line_len = std.mem.indexOfScalar(u8, rest, '\n') orelse rest.len;
        const has_newline = line_len < rest.len;
        const raw_line = rest[0..line_len];
        const line = if (raw_line.len > 0 and raw_line[raw_line.len - 1] == '\r') raw_line[0 .. raw_line.len - 1] else raw_line;

        if (in_root) {
            const trimmed = std.mem.trim(u8, stripConfigComment(line), " \t\r\n");
            if (trimmed.len > 0 and trimmed[0] == '[') {
                if (!wrote) {
                    try out.appendSlice(allocator, rendered);
                    wrote = true;
                }
                in_root = false;
            } else if (topLevelKeyMatches(trimmed, key)) {
                try out.appendSlice(allocator, rendered);
                wrote = true;
                offset += line_len + @intFromBool(has_newline);
                continue;
            }
        }

        try out.appendSlice(allocator, raw_line);
        if (has_newline) try out.append(allocator, '\n');
        offset += line_len + @intFromBool(has_newline);
    }

    if (!wrote) {
        if (source.len > 0 and source[source.len - 1] != '\n') try out.append(allocator, '\n');
        try out.appendSlice(allocator, rendered);
    }

    return out.toOwnedSlice(allocator);
}

fn stripConfigComment(line: []const u8) []const u8 {
    var in_string = false;
    var escaped = false;
    for (line, 0..) |byte, index| {
        if (escaped) {
            escaped = false;
            continue;
        }
        if (byte == '\\' and in_string) {
            escaped = true;
            continue;
        }
        if (byte == '"') {
            in_string = !in_string;
            continue;
        }
        if (byte == '#' and !in_string) return line[0..index];
    }
    return line;
}

fn topLevelKeyMatches(trimmed: []const u8, key: []const u8) bool {
    const eq_index = std.mem.indexOfScalar(u8, trimmed, '=') orelse return false;
    const lhs = std.mem.trim(u8, trimmed[0..eq_index], " \t\r\n");
    return std.mem.eql(u8, lhs, key);
}

/// explains the effective config as a stable text summary.
/// args must be empty; stdout receives the rendered explanation.
/// ownership: all temporary allocations are freed before return.
/// errors: UnknownExplainArgument, InvalidConfig, config read errors, and allocation errors.
pub fn explainCmd(allocator: std.mem.Allocator, args: []const []const u8) !void {
    if (args.len != 0) return error.UnknownExplainArgument;

    const path = try cli_util.defaultConfigPath(allocator);
    defer allocator.free(path);
    const source = try cli_util.readConfigOrDefault(allocator, path);
    defer allocator.free(source);

    var diagnostic: shisa_config.Diagnostic = .{};
    var parsed = shisa_config.parse(allocator, source, &diagnostic) catch |err| switch (err) {
        error.InvalidConfig => {
            const message = try std.fmt.allocPrint(allocator, "{s}:{d}:{d}: {s}\n", .{ path, diagnostic.line, diagnostic.column, diagnostic.message });
            defer allocator.free(message);
            try std.fs.File.stderr().writeAll(message);
            return err;
        },
        else => return err,
    };
    defer parsed.deinit(allocator);

    const output = try explainAlloc(allocator, parsed);
    defer allocator.free(output);
    try std.fs.File.stdout().writeAll(output);
}

fn explainAlloc(allocator: std.mem.Allocator, parsed: shisa_config.Config) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);

    try cli_util.appendFmt(allocator, &out, "theme: {s}\n", .{parsed.theme});
    try out.appendSlice(allocator, "pipeline:\n");
    for (parsed.prompt_modules, 0..) |module_id, index| {
        try cli_util.appendFmt(
            allocator,
            &out,
            "  {d}. {s} ({s})\n",
            .{ index + 1, shisa_config.moduleIdName(module_id), shisa_config.moduleExecutionClass(module_id) },
        );
    }

    return try out.toOwnedSlice(allocator);
}

test "config set args accept locale assignment only" {
    const parsed = try parseSetArgs(&.{"locale=ja-JP"});
    try std.testing.expectEqualStrings("ja-JP", parsed.locale);
    try std.testing.expectError(error.InvalidLocale, parseSetArgs(&.{"locale=ja_JP.UTF-8"}));
    try std.testing.expectError(error.UnknownConfigSetArgument, parseSetArgs(&.{"theme=plain"}));
}

test "config set upserts top-level locale" {
    const source =
        \\version = 1
        \\theme = "plain"
        \\
        \\[prompt]
        \\modules = ["cwd"]
        \\
    ;
    const updated = try upsertTopLevelStringKeyAlloc(std.testing.allocator, source, "locale", "ar-EG");
    defer std.testing.allocator.free(updated);

    const locale_index = std.mem.indexOf(u8, updated, "locale = \"ar-EG\"").?;
    const prompt_index = std.mem.indexOf(u8, updated, "[prompt]").?;
    try std.testing.expect(locale_index < prompt_index);
    var diagnostic: shisa_config.Diagnostic = .{};
    var parsed = try shisa_config.parse(std.testing.allocator, updated, &diagnostic);
    defer parsed.deinit(std.testing.allocator);
    try std.testing.expectEqualStrings("ar-EG", parsed.locale);
}

test "config set replaces existing top-level locale" {
    const source =
        \\version = 1
        \\locale = "auto" # keep comment away from replacement
        \\
    ;
    const updated = try upsertTopLevelStringKeyAlloc(std.testing.allocator, source, "locale", "en-US");
    defer std.testing.allocator.free(updated);

    try std.testing.expectEqualStrings("version = 1\nlocale = \"en-US\"\n", updated);
}

test "init args render shell notification preferences" {
    const config = try parseInitArgs(&.{
        "--a11y",
        "--cmd-complete-bell-mode",
        "osc9",
        "--cmd-complete-bell-threshold-ms",
        "2500",
        "--cmd-complete-bell-message",
        "done",
    });
    try std.testing.expect(config.a11y);
    try std.testing.expect(config.shell_preferences != null);
    const prefs = config.shell_preferences.?;
    try std.testing.expect(prefs.cmd_complete_bell);
    try std.testing.expectEqualStrings("osc9", prefs.cmd_complete_bell_mode);
    try std.testing.expectEqual(@as(u64, 2500), prefs.cmd_complete_bell_threshold_ms);
    try std.testing.expectEqualStrings("done", prefs.cmd_complete_bell_message);

    const source = try renderShellPreferencesAlloc(std.testing.allocator, prefs);
    defer std.testing.allocator.free(source);
    try std.testing.expectEqualStrings(
        "SHISA_CMD_COMPLETE_BELL=1\nSHISA_CMD_COMPLETE_BELL_MODE=osc9\nSHISA_CMD_COMPLETE_BELL_THRESHOLD_MS=2500\nSHISA_CMD_COMPLETE_BELL_MESSAGE=done\n",
        source,
    );
    try std.testing.expectError(error.InvalidCmdCompleteBellMode, parseInitArgs(&.{ "--cmd-complete-bell-mode", "bad" }));
}

test "explain output dumps pipeline" {
    var diagnostic: shisa_config.Diagnostic = .{};
    var parsed = try shisa_config.parse(std.testing.allocator, shisa_config.default_config_text, &diagnostic);
    defer parsed.deinit(std.testing.allocator);

    const output = try explainAlloc(std.testing.allocator, parsed);
    defer std.testing.allocator.free(output);

    try std.testing.expect(std.mem.indexOf(u8, output, "theme: plain\n") != null);
    try std.testing.expect(std.mem.indexOf(u8, output, "1. cwd (sync)") != null);
    try std.testing.expect(std.mem.indexOf(u8, output, "2. git_branch (async)") != null);
}
