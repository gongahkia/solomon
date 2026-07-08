const std = @import("std");
const builtin = @import("builtin");
const cli_theme = @import("theme.zig");
const cli_util = @import("util.zig");
const shisa_config = @import("../config.zig");
const theme_loader = @import("../theme/loader.zig");

/// static help text printed by shisa config set --help.
pub const help_text =
    \\usage: shisa config set locale=<locale|auto>
    \\
    \\commands:
    \\  set locale=<locale|auto> set locale override; auto uses LC_ALL, LC_CTYPE, then LANG
    \\
;

pub const init_help_text =
    \\usage: shisa init [--defaults|--interactive] [--shell NAME] [--theme THEME] [--async on|off] [--write-hook]
    \\
    \\options:
    \\  --defaults      write default shisa.toml without prompting
    \\  --interactive   force first-run wizard
    \\  --shell NAME    target zsh, bash, fish, nu, or pwsh for hook install
    \\  --theme THEME   write a built-in theme id
    \\  --async on|off  enable or disable async fill in generated shell prefs
    \\  --write-hook    append an idempotent shell hook block
    \\  --a11y          write accessibility-first defaults
    \\
;

/// parsed options for shisa init.
/// shell_preferences is null unless a shell preference flag was supplied.
pub const InitConfig = struct {
    /// prints command help and exits.
    help: bool = false,
    /// writes defaults without prompting.
    defaults: bool = false,
    /// forces the first-run wizard.
    interactive: bool = false,
    /// writes the accessibility-first default config when true.
    a11y: bool = false,
    /// appends an idempotent shell hook block to the current shell startup file.
    write_hook: bool = false,
    /// optional shell name override for hook installation.
    shell_name: ?[]const u8 = null,
    /// shell_name is allocator-owned.
    owns_shell_name: bool = false,
    /// optional built-in theme override.
    theme: ?[]const u8 = null,
    /// optional async fill preference.
    async_fill: ?bool = null,
    /// optional shell.env preferences to write next to shisa.toml.
    shell_preferences: ?ShellPreferences = null,

    fn deinit(self: InitConfig, allocator: std.mem.Allocator) void {
        if (self.owns_shell_name) {
            if (self.shell_name) |shell_name| allocator.free(shell_name);
        }
    }
};

/// shell.env preferences emitted by shisa init shell flags.
/// string fields are borrowed from CLI args or static defaults.
pub const ShellPreferences = struct {
    /// enables async fill and shell redraw integration when true; null leaves hook defaults.
    async_fill: ?bool = null,
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
    var config = try parseInitArgs(args);
    defer config.deinit(allocator);
    if (config.help) {
        try std.fs.File.stdout().writeAll(init_help_text);
        return;
    }

    const path = try cli_util.defaultConfigPath(allocator);
    defer allocator.free(path);
    if (std.fs.path.dirname(path)) |parent| {
        try std.fs.cwd().makePath(parent);
    }

    if ((config.interactive or (args.len == 0 and !pathExistsAbsolute(path))) and !config.defaults) {
        config.deinit(allocator);
        config = try runInitWizard(allocator);
    }

    var wrote_config = false;
    if (std.fs.createFileAbsolute(path, .{ .exclusive = true })) |file| {
        var config_file = file;
        defer config_file.close();
        const source = try renderInitConfigAlloc(allocator, config);
        defer allocator.free(source);
        try config_file.writeAll(source);
        wrote_config = true;
    } else |err| switch (err) {
        error.PathAlreadyExists => {
            if (config.shell_preferences == null and !config.write_hook) return err;
            if (config.a11y) return err;
            if (config.theme != null) return err;
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

    var wrote_hook = false;
    var hook_path_for_message: ?[]u8 = null;
    defer if (hook_path_for_message) |hook_path| allocator.free(hook_path);
    if (config.write_hook) {
        hook_path_for_message = if (config.shell_name) |shell_name|
            try writeShellHookForShell(allocator, shell_name, config.async_fill)
        else
            try writeShellHookWithAsync(allocator, config.async_fill);
        wrote_hook = true;
    }

    var message: std.ArrayList(u8) = .empty;
    defer message.deinit(allocator);
    if (wrote_config) try cli_util.appendFmt(allocator, &message, "wrote {s}\n", .{path});
    if (wrote_shell_preferences) try cli_util.appendFmt(allocator, &message, "wrote {s}\n", .{shell_path_for_message.?});
    if (wrote_hook) try cli_util.appendFmt(allocator, &message, "wrote {s}\n", .{hook_path_for_message.?});
    if (message.items.len == 0) try cli_util.appendFmt(allocator, &message, "wrote {s}\n", .{path});
    try std.fs.File.stdout().writeAll(message.items);
}

fn parseInitArgs(args: []const []const u8) !InitConfig {
    var config: InitConfig = .{};
    var prefs: ShellPreferences = .{};
    var seen_prefs = false;
    var i: usize = 0;
    while (i < args.len) : (i += 1) {
        const arg = args[i];
        if (std.mem.eql(u8, arg, "--help") or std.mem.eql(u8, arg, "-h")) {
            config.help = true;
        } else if (std.mem.eql(u8, arg, "--defaults")) {
            config.defaults = true;
        } else if (std.mem.eql(u8, arg, "--interactive")) {
            config.interactive = true;
        } else if (std.mem.eql(u8, arg, "--a11y")) {
            config.a11y = true;
        } else if (std.mem.eql(u8, arg, "--write-hook")) {
            config.write_hook = true;
        } else if (std.mem.eql(u8, arg, "--shell")) {
            i += 1;
            if (i >= args.len) return error.UnknownInitArgument;
            if (!validShellName(args[i])) return error.InvalidShell;
            config.shell_name = args[i];
        } else if (std.mem.eql(u8, arg, "--theme")) {
            i += 1;
            if (i >= args.len) return error.UnknownInitArgument;
            if (!isBuiltInTheme(args[i])) return error.InvalidTheme;
            config.theme = args[i];
        } else if (std.mem.eql(u8, arg, "--async")) {
            i += 1;
            if (i >= args.len) return error.UnknownInitArgument;
            const enabled = parseAsyncMode(args[i]) orelse return error.InvalidAsyncMode;
            config.async_fill = enabled;
            prefs.async_fill = enabled;
            seen_prefs = true;
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
    if (config.defaults and config.interactive) return error.InvalidInitMode;
    if (config.a11y and config.theme != null) return error.InvalidInitMode;
    if (seen_prefs) config.shell_preferences = prefs;
    return config;
}

fn renderInitConfigAlloc(allocator: std.mem.Allocator, config: InitConfig) ![]u8 {
    const base = if (config.a11y) shisa_config.a11y_config_text else shisa_config.default_config_text;
    if (config.theme) |theme_id| return upsertTopLevelStringKeyAlloc(allocator, base, "theme", theme_id);
    return allocator.dupe(u8, base);
}

fn runInitWizard(allocator: std.mem.Allocator) !InitConfig {
    const stdout = std.fs.File.stdout();
    const shell_name = try currentShellNameAlloc(allocator);
    errdefer allocator.free(shell_name);
    const terminal = try detectTerminalAlloc(allocator);
    defer allocator.free(terminal);
    const cwd = try currentCwdForPreviewAlloc(allocator);
    defer allocator.free(cwd);

    try stdout.writeAll("shisa init\n");
    try writeFmt(allocator, stdout, "detected shell: {s}\n", .{shell_name});
    try writeFmt(allocator, stdout, "detected terminal: {s}\n", .{terminal});
    if (nerdFontMayNotRender(terminal)) {
        try stdout.writeAll("warning: Nerd Font glyphs may not render; choose plain if glyphs look wrong.\n");
    }

    const theme_id = try chooseTheme(allocator, stdout, cwd);
    const async_fill = try askYesNo(allocator, stdout, "enable async fill? background segments render cached first, then repaint when ready. [Y/n] ", true);
    const write_hook = try chooseShellHook(allocator, stdout, shell_name, async_fill);

    return .{
        .interactive = true,
        .write_hook = write_hook,
        .shell_name = shell_name,
        .owns_shell_name = true,
        .theme = theme_id,
        .async_fill = async_fill,
        .shell_preferences = .{ .async_fill = async_fill },
    };
}

const wizard_theme_ids = [_][]const u8{ "plain", "minimal-monochrome", "nord-dark", "gruvbox-rainbow", "tokyo-night" };

fn chooseTheme(allocator: std.mem.Allocator, stdout: std.fs.File, cwd: []const u8) ![]const u8 {
    try stdout.writeAll("themes:\n");
    for (wizard_theme_ids, 0..) |theme_id, index| {
        try writeFmt(allocator, stdout, "{d}. {s}\n", .{ index + 1, theme_id });
        const preview = try previewForThemeAlloc(allocator, theme_id, cwd);
        defer allocator.free(preview);
        try stdout.writeAll(preview);
    }
    while (true) {
        try writeFmt(allocator, stdout, "theme [1-{d}] (default 1): ", .{wizard_theme_ids.len});
        const line = try readLineAlloc(allocator);
        defer allocator.free(line);
        const trimmed = std.mem.trim(u8, line, " \t\r\n");
        if (trimmed.len == 0) return wizard_theme_ids[0];
        const choice = std.fmt.parseInt(usize, trimmed, 10) catch {
            try stdout.writeAll("enter a number.\n");
            continue;
        };
        if (choice >= 1 and choice <= wizard_theme_ids.len) return wizard_theme_ids[choice - 1];
        try stdout.writeAll("choice out of range.\n");
    }
}

fn chooseShellHook(allocator: std.mem.Allocator, stdout: std.fs.File, shell_name: []const u8, async_fill: bool) !bool {
    const target_path = try shellHookTargetPathForShellAlloc(allocator, shell_name);
    defer allocator.free(target_path);
    const shisa_bin = try std.fs.selfExePathAlloc(allocator);
    defer allocator.free(shisa_bin);
    const init_dir = try shisaInitDirAlloc(allocator, shisa_bin);
    defer allocator.free(init_dir);
    const block = try shellHookBlockAlloc(allocator, shell_name, shisa_bin, init_dir, async_fill);
    defer allocator.free(block);

    try writeFmt(allocator, stdout, "shell hook target: {s}\n", .{target_path});
    try stdout.writeAll("shell hook block:\n");
    try stdout.writeAll(block);
    return askYesNoAllocPrompt(allocator, stdout, try std.fmt.allocPrint(allocator, "append shell hook to {s}? [y/N] ", .{target_path}), false);
}

fn previewForThemeAlloc(allocator: std.mem.Allocator, theme_id: []const u8, cwd: []const u8) ![]u8 {
    const path = try cli_theme.pathAlloc(allocator, theme_id);
    defer allocator.free(path);
    const source = try std.fs.cwd().readFileAlloc(allocator, path, cli_theme.max_config_bytes);
    defer allocator.free(source);
    var diagnostic: theme_loader.Diagnostic = .{};
    var theme = try theme_loader.parse(allocator, source, &diagnostic);
    defer theme.deinit(allocator);
    return cli_theme.previewAllocWithCwd(allocator, theme, 80, cwd);
}

fn askYesNo(allocator: std.mem.Allocator, stdout: std.fs.File, prompt: []const u8, default_yes: bool) !bool {
    const owned_prompt = try allocator.dupe(u8, prompt);
    return askYesNoAllocPrompt(allocator, stdout, owned_prompt, default_yes);
}

fn askYesNoAllocPrompt(allocator: std.mem.Allocator, stdout: std.fs.File, prompt: []u8, default_yes: bool) !bool {
    defer allocator.free(prompt);
    while (true) {
        try stdout.writeAll(prompt);
        const line = try readLineAlloc(allocator);
        defer allocator.free(line);
        const trimmed = std.mem.trim(u8, line, " \t\r\n");
        if (trimmed.len == 0) return default_yes;
        if (std.ascii.eqlIgnoreCase(trimmed, "y") or std.ascii.eqlIgnoreCase(trimmed, "yes")) return true;
        if (std.ascii.eqlIgnoreCase(trimmed, "n") or std.ascii.eqlIgnoreCase(trimmed, "no")) return false;
        try stdout.writeAll("enter y or n.\n");
    }
}

fn readLineAlloc(allocator: std.mem.Allocator) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    errdefer out.deinit(allocator);
    var byte_buf: [1]u8 = undefined;
    while (out.items.len < 4096) {
        const read = try std.fs.File.stdin().read(&byte_buf);
        if (read == 0) break;
        try out.append(allocator, byte_buf[0]);
        if (byte_buf[0] == '\n') break;
    }
    return out.toOwnedSlice(allocator);
}

fn writeFmt(allocator: std.mem.Allocator, file: std.fs.File, comptime format: []const u8, args: anytype) !void {
    const message = try std.fmt.allocPrint(allocator, format, args);
    defer allocator.free(message);
    try file.writeAll(message);
}

fn detectTerminalAlloc(allocator: std.mem.Allocator) ![]u8 {
    return cli_util.detectTerminalAlloc(allocator);
}

fn nerdFontMayNotRender(terminal: []const u8) bool {
    if (std.process.getEnvVarOwned(std.heap.page_allocator, "SHISA_NERD_FONT")) |value| {
        defer std.heap.page_allocator.free(value);
        if (std.mem.eql(u8, value, "0")) return true;
    } else |_| {}
    return std.mem.eql(u8, terminal, "unknown") or
        std.mem.eql(u8, terminal, "dumb") or
        std.mem.indexOf(u8, terminal, "Apple_Terminal") != null;
}

fn currentCwdForPreviewAlloc(allocator: std.mem.Allocator) ![]u8 {
    if (std.process.getEnvVarOwned(allocator, "PWD")) |value| {
        if (value.len != 0) return value;
        allocator.free(value);
    } else |_| {}
    return std.fs.cwd().realpathAlloc(allocator, ".");
}

fn pathExistsAbsolute(path: []const u8) bool {
    std.fs.accessAbsolute(path, .{}) catch return false;
    return true;
}

fn parseAsyncMode(value: []const u8) ?bool {
    if (std.mem.eql(u8, value, "on") or std.mem.eql(u8, value, "true") or std.mem.eql(u8, value, "1")) return true;
    if (std.mem.eql(u8, value, "off") or std.mem.eql(u8, value, "false") or std.mem.eql(u8, value, "0")) return false;
    return null;
}

fn validShellName(shell_name: []const u8) bool {
    return std.mem.eql(u8, shell_name, "zsh") or
        std.mem.eql(u8, shell_name, "bash") or
        std.mem.eql(u8, shell_name, "fish") or
        std.mem.eql(u8, shell_name, "nu") or
        std.mem.eql(u8, shell_name, "nushell") or
        std.mem.eql(u8, shell_name, "pwsh") or
        std.mem.eql(u8, shell_name, "powershell");
}

fn isBuiltInTheme(theme_id: []const u8) bool {
    for (cli_theme.built_in_theme_ids) |candidate| {
        if (std.mem.eql(u8, theme_id, candidate)) return true;
    }
    return false;
}

pub const shell_hook_marker_start = "# >>> shisa >>>";
pub const shell_hook_marker_end = "# <<< shisa <<<";
const shell_hook_legacy_marker_start = "# >>> shisa hook >>>";

pub fn writeShellHook(allocator: std.mem.Allocator) ![]u8 {
    return writeShellHookWithAsync(allocator, null);
}

fn writeShellHookWithAsync(allocator: std.mem.Allocator, async_fill: ?bool) ![]u8 {
    const shell_name = try currentShellNameAlloc(allocator);
    defer allocator.free(shell_name);
    return writeShellHookForShell(allocator, shell_name, async_fill);
}

pub fn writeShellHookForShell(allocator: std.mem.Allocator, shell_name: []const u8, async_fill: ?bool) ![]u8 {
    const target_path = try shellHookTargetPathForShellAlloc(allocator, shell_name);
    errdefer allocator.free(target_path);
    const shisa_bin = try std.fs.selfExePathAlloc(allocator);
    defer allocator.free(shisa_bin);
    const init_dir = try shisaInitDirAlloc(allocator, shisa_bin);
    defer allocator.free(init_dir);
    const block = try shellHookBlockAlloc(allocator, shell_name, shisa_bin, init_dir, async_fill);
    defer allocator.free(block);

    if (std.fs.path.dirname(target_path)) |parent| try std.fs.cwd().makePath(parent);
    const existing = readFileIfPresentAlloc(allocator, target_path) catch |err| switch (err) {
        error.IsDir => return err,
        else => return err,
    };
    defer allocator.free(existing);
    if (std.mem.indexOf(u8, existing, shell_hook_marker_start) != null or
        std.mem.indexOf(u8, existing, shell_hook_legacy_marker_start) != null) return target_path;

    var file = if (std.fs.path.isAbsolute(target_path))
        try std.fs.createFileAbsolute(target_path, .{ .truncate = false, .read = true })
    else
        try std.fs.cwd().createFile(target_path, .{ .truncate = false, .read = true });
    defer file.close();
    try file.seekFromEnd(0);
    if (existing.len != 0 and existing[existing.len - 1] != '\n') try file.writeAll("\n");
    try file.writeAll(block);
    return target_path;
}

pub fn shellHookTargetPathAlloc(allocator: std.mem.Allocator) ![]u8 {
    const shell_name = try currentShellNameAlloc(allocator);
    defer allocator.free(shell_name);
    return shellHookTargetPathForShellAlloc(allocator, shell_name);
}

pub fn shellHookInstalled(allocator: std.mem.Allocator) bool {
    const active = std.process.getEnvVarOwned(allocator, "SHISA_HOOK_ACTIVE") catch null;
    if (active) |value| {
        defer allocator.free(value);
        if (value.len != 0) return true;
    }
    const target_path = shellHookTargetPathAlloc(allocator) catch return false;
    defer allocator.free(target_path);
    const source = readFileIfPresentAlloc(allocator, target_path) catch return false;
    defer allocator.free(source);
    return std.mem.indexOf(u8, source, shell_hook_marker_start) != null or
        std.mem.indexOf(u8, source, shell_hook_legacy_marker_start) != null;
}

fn currentShellNameAlloc(allocator: std.mem.Allocator) ![]u8 {
    return cli_util.currentShellNameAlloc(allocator);
}

fn passwdShellNameAlloc(allocator: std.mem.Allocator) ![]u8 {
    switch (builtin.os.tag) {
        .windows, .wasi => return error.UnsupportedPasswd,
        else => {
            const pwd = std.c.getpwuid(std.posix.getuid()) orelse return error.MissingPasswd;
            const shell_ptr = pwd.shell orelse return error.MissingPasswdShell;
            const shell_path = std.mem.span(shell_ptr);
            const base = std.fs.path.basename(shell_path);
            if (base.len == 0) return error.MissingPasswdShell;
            return allocator.dupe(u8, base);
        },
    }
}

fn shellHookTargetPathForShellAlloc(allocator: std.mem.Allocator, shell_name: []const u8) ![]u8 {
    const home = try std.process.getEnvVarOwned(allocator, "HOME");
    defer allocator.free(home);
    if (std.mem.eql(u8, shell_name, "zsh")) return std.fmt.allocPrint(allocator, "{s}/.zshrc", .{home});
    if (std.mem.eql(u8, shell_name, "bash")) return std.fmt.allocPrint(allocator, "{s}/.bashrc", .{home});
    if (std.mem.eql(u8, shell_name, "fish")) {
        const config_home = try xdgConfigHomeAlloc(allocator, home);
        defer allocator.free(config_home);
        return std.fmt.allocPrint(allocator, "{s}/fish/config.fish", .{config_home});
    }
    if (std.mem.eql(u8, shell_name, "nu") or std.mem.eql(u8, shell_name, "nushell")) {
        const config_home = try xdgConfigHomeAlloc(allocator, home);
        defer allocator.free(config_home);
        return std.fmt.allocPrint(allocator, "{s}/nushell/config.nu", .{config_home});
    }
    if (std.mem.eql(u8, shell_name, "pwsh") or std.mem.eql(u8, shell_name, "powershell")) {
        const profile = std.process.getEnvVarOwned(allocator, "PROFILE") catch |err| switch (err) {
            error.EnvironmentVariableNotFound => return std.fmt.allocPrint(allocator, "{s}/Documents/PowerShell/Microsoft.PowerShell_profile.ps1", .{home}),
            else => return err,
        };
        return profile;
    }
    return std.fmt.allocPrint(allocator, "{s}/.profile", .{home});
}

fn xdgConfigHomeAlloc(allocator: std.mem.Allocator, home: []const u8) ![]u8 {
    return std.process.getEnvVarOwned(allocator, "XDG_CONFIG_HOME") catch |err| switch (err) {
        error.EnvironmentVariableNotFound => std.fmt.allocPrint(allocator, "{s}/.config", .{home}),
        else => return err,
    };
}

fn shisaInitDirAlloc(allocator: std.mem.Allocator, shisa_bin: []const u8) ![]u8 {
    if (std.process.getEnvVarOwned(allocator, "SHISA_INIT_DIR")) |dir| {
        if (pathExists(dir)) return dir;
        allocator.free(dir);
    } else |_| {}
    if (pathExists("init")) return try std.fs.cwd().realpathAlloc(allocator, "init");
    const bin_dir = std.fs.path.dirname(shisa_bin) orelse return error.MissingInitDir;
    const prefix_dir = std.fs.path.dirname(bin_dir) orelse return error.MissingInitDir;
    const share_candidate = try std.fs.path.join(allocator, &.{ prefix_dir, "share", "shisa", "init" });
    if (pathExists(share_candidate)) return share_candidate;
    allocator.free(share_candidate);
    const zig_out_dir = std.fs.path.dirname(bin_dir) orelse return error.MissingInitDir;
    const repo_dir = std.fs.path.dirname(zig_out_dir) orelse return error.MissingInitDir;
    const candidate = try std.fs.path.join(allocator, &.{ repo_dir, "init" });
    errdefer allocator.free(candidate);
    if (!pathExists(candidate)) return error.MissingInitDir;
    return candidate;
}

fn pathExists(path: []const u8) bool {
    std.fs.cwd().access(path, .{}) catch return false;
    return true;
}

fn shellHookBlockAlloc(allocator: std.mem.Allocator, shell_name: []const u8, shisa_bin: []const u8, init_dir: []const u8, async_fill: ?bool) ![]u8 {
    const quoted_bin = try cli_util.shellSingleQuoteAlloc(allocator, shisa_bin);
    defer allocator.free(quoted_bin);
    const async_value: ?[]const u8 = if (async_fill) |enabled| if (enabled) "1" else "0" else null;
    const hook_name: []const u8 = if (std.mem.eql(u8, shell_name, "fish"))
        "shisa.fish"
    else if (std.mem.eql(u8, shell_name, "nu") or std.mem.eql(u8, shell_name, "nushell"))
        "shisa.nu"
    else if (std.mem.eql(u8, shell_name, "pwsh") or std.mem.eql(u8, shell_name, "powershell"))
        "shisa.ps1"
    else if (std.mem.eql(u8, shell_name, "bash"))
        "shisa.bash"
    else
        "shisa.zsh";
    const hook_path = try std.fs.path.join(allocator, &.{ init_dir, hook_name });
    defer allocator.free(hook_path);
    const quoted_hook = try cli_util.shellSingleQuoteAlloc(allocator, hook_path);
    defer allocator.free(quoted_hook);
    if (std.mem.eql(u8, shell_name, "fish")) {
        return std.fmt.allocPrint(
            allocator,
            "\n{s}\nset -gx SHISA_BIN {s}\nset -gx SHISA_HOOK_ACTIVE 1\n{s}source {s}\n{s}\n",
            .{ shell_hook_marker_start, quoted_bin, asyncEnvLineFish(async_value), quoted_hook, shell_hook_marker_end },
        );
    }
    if (std.mem.eql(u8, shell_name, "nu") or std.mem.eql(u8, shell_name, "nushell")) {
        return std.fmt.allocPrint(
            allocator,
            "\n{s}\n$env.SHISA_BIN = {s}\n$env.SHISA_HOOK_ACTIVE = \"1\"\n{s}source {s}\n{s}\n",
            .{ shell_hook_marker_start, quoted_bin, asyncEnvLineNu(async_value), quoted_hook, shell_hook_marker_end },
        );
    }
    if (std.mem.eql(u8, shell_name, "pwsh") or std.mem.eql(u8, shell_name, "powershell")) {
        return std.fmt.allocPrint(
            allocator,
            "\n{s}\n$env:SHISA_BIN = {s}\n$env:SHISA_HOOK_ACTIVE = \"1\"\n{s}. {s}\n{s}\n",
            .{ shell_hook_marker_start, quoted_bin, asyncEnvLinePwsh(async_value), quoted_hook, shell_hook_marker_end },
        );
    }
    return std.fmt.allocPrint(
        allocator,
        "\n{s}\nexport SHISA_BIN={s}\nexport SHISA_HOOK_ACTIVE=1\n{s}source {s}\n{s}\n",
        .{ shell_hook_marker_start, quoted_bin, asyncEnvLinePosix(async_value), quoted_hook, shell_hook_marker_end },
    );
}

fn asyncEnvLinePosix(value: ?[]const u8) []const u8 {
    return if (value) |enabled| if (std.mem.eql(u8, enabled, "1"))
        "export SHISA_ASYNC_FILL=1\n"
    else
        "export SHISA_ASYNC_FILL=0\n" else "";
}

fn asyncEnvLineFish(value: ?[]const u8) []const u8 {
    return if (value) |enabled| if (std.mem.eql(u8, enabled, "1"))
        "set -gx SHISA_ASYNC_FILL 1\n"
    else
        "set -gx SHISA_ASYNC_FILL 0\n" else "";
}

fn asyncEnvLineNu(value: ?[]const u8) []const u8 {
    return if (value) |enabled| if (std.mem.eql(u8, enabled, "1"))
        "$env.SHISA_ASYNC_FILL = \"1\"\n"
    else
        "$env.SHISA_ASYNC_FILL = \"0\"\n" else "";
}

fn asyncEnvLinePwsh(value: ?[]const u8) []const u8 {
    return if (value) |enabled| if (std.mem.eql(u8, enabled, "1"))
        "$env:SHISA_ASYNC_FILL = \"1\"\n"
    else
        "$env:SHISA_ASYNC_FILL = \"0\"\n" else "";
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
    return file.readToEndAlloc(allocator, cli_util.max_config_bytes);
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
    var out: std.ArrayList(u8) = .empty;
    errdefer out.deinit(allocator);
    if (preferences.async_fill) |enabled| {
        const value: []const u8 = if (enabled) "1" else "0";
        const quoted_async = try cli_util.shellSingleQuoteAlloc(allocator, value);
        defer allocator.free(quoted_async);
        try cli_util.appendFmt(allocator, &out, "SHISA_ASYNC_FILL={s}\n", .{quoted_async});
    }
    const bell_value = try std.fmt.allocPrint(allocator, "{d}", .{@intFromBool(preferences.cmd_complete_bell)});
    defer allocator.free(bell_value);
    const threshold_value = try std.fmt.allocPrint(allocator, "{d}", .{preferences.cmd_complete_bell_threshold_ms});
    defer allocator.free(threshold_value);
    const quoted_bell = try cli_util.shellSingleQuoteAlloc(allocator, bell_value);
    defer allocator.free(quoted_bell);
    const quoted_mode = try cli_util.shellSingleQuoteAlloc(allocator, preferences.cmd_complete_bell_mode);
    defer allocator.free(quoted_mode);
    const quoted_threshold = try cli_util.shellSingleQuoteAlloc(allocator, threshold_value);
    defer allocator.free(quoted_threshold);
    const quoted_message = try cli_util.shellSingleQuoteAlloc(allocator, preferences.cmd_complete_bell_message);
    defer allocator.free(quoted_message);
    try cli_util.appendFmt(
        allocator,
        &out,
        "SHISA_CMD_COMPLETE_BELL={s}\nSHISA_CMD_COMPLETE_BELL_MODE={s}\nSHISA_CMD_COMPLETE_BELL_THRESHOLD_MS={s}\nSHISA_CMD_COMPLETE_BELL_MESSAGE={s}\n",
        .{ quoted_bell, quoted_mode, quoted_threshold, quoted_message },
    );
    return out.toOwnedSlice(allocator);
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
        "SHISA_CMD_COMPLETE_BELL='1'\nSHISA_CMD_COMPLETE_BELL_MODE='osc9'\nSHISA_CMD_COMPLETE_BELL_THRESHOLD_MS='2500'\nSHISA_CMD_COMPLETE_BELL_MESSAGE='done'\n",
        source,
    );
    try std.testing.expectError(error.InvalidCmdCompleteBellMode, parseInitArgs(&.{ "--cmd-complete-bell-mode", "bad" }));
}

test "init args parse write hook" {
    const config = try parseInitArgs(&.{"--write-hook"});
    try std.testing.expect(config.write_hook);
}

test "init args parse first-run flags" {
    const config = try parseInitArgs(&.{ "--defaults", "--shell", "zsh", "--theme", "nord-dark", "--async", "off", "--write-hook" });
    try std.testing.expect(config.defaults);
    try std.testing.expect(config.write_hook);
    try std.testing.expectEqualStrings("zsh", config.shell_name.?);
    try std.testing.expectEqualStrings("nord-dark", config.theme.?);
    try std.testing.expect(config.async_fill.? == false);
    try std.testing.expect(config.shell_preferences.?.async_fill.? == false);
    try std.testing.expectError(error.InvalidAsyncMode, parseInitArgs(&.{ "--async", "maybe" }));
    try std.testing.expectError(error.InvalidShell, parseInitArgs(&.{ "--shell", "csh" }));
    try std.testing.expectError(error.InvalidTheme, parseInitArgs(&.{ "--theme", "missing" }));
    try std.testing.expectError(error.InvalidInitMode, parseInitArgs(&.{ "--defaults", "--interactive" }));
}

test "shell hook block includes marker and active env" {
    const block = try shellHookBlockAlloc(std.testing.allocator, "zsh", "/tmp/shisa", "/tmp/init", true);
    defer std.testing.allocator.free(block);
    try std.testing.expect(std.mem.indexOf(u8, block, shell_hook_marker_start) != null);
    try std.testing.expect(std.mem.indexOf(u8, block, "SHISA_HOOK_ACTIVE=1") != null);
    try std.testing.expect(std.mem.indexOf(u8, block, "SHISA_ASYNC_FILL=1") != null);
    try std.testing.expect(std.mem.indexOf(u8, block, "shisa.zsh") != null);
}

test "init config renderer applies theme override" {
    const source = try renderInitConfigAlloc(std.testing.allocator, .{ .theme = "tokyo-night" });
    defer std.testing.allocator.free(source);
    try std.testing.expect(std.mem.indexOf(u8, source, "theme = \"tokyo-night\"") != null);
}

test "init shell preferences quote metacharacter messages" {
    const prefs: ShellPreferences = .{
        .async_fill = false,
        .cmd_complete_bell = true,
        .cmd_complete_bell_mode = "terminal",
        .cmd_complete_bell_threshold_ms = 1,
        .cmd_complete_bell_message = "it's $(done); ok ✓",
    };
    const source = try renderShellPreferencesAlloc(std.testing.allocator, prefs);
    defer std.testing.allocator.free(source);
    try std.testing.expect(std.mem.indexOf(u8, source, "SHISA_ASYNC_FILL='0'\n") != null);
    try std.testing.expect(std.mem.indexOf(u8, source, "SHISA_CMD_COMPLETE_BELL_MESSAGE='it'\\''s $(done); ok ✓'\n") != null);
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
