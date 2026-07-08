const std = @import("std");
const builtin = @import("builtin");
const shisa_config = @import("../config.zig");

/// maximum config bytes read by helpers that load shisa.toml.
pub const max_config_bytes = 1024 * 1024;

/// builds the default shisa.toml path from the process environment.
/// caller owns the returned slice and must free it with allocator.
/// environment: prefers XDG_CONFIG_HOME; falls back to HOME.
/// errors: EnvironmentVariableNotFound when HOME is required and missing; OutOfMemory on allocation failure.
pub fn defaultConfigPath(allocator: std.mem.Allocator) ![]u8 {
    if (builtin.os.tag == .windows) return windowsDefaultConfigPath(allocator);

    const xdg = std.process.getEnvVarOwned(allocator, "XDG_CONFIG_HOME") catch |err| switch (err) {
        error.EnvironmentVariableNotFound => null,
        else => return err,
    };
    if (xdg) |xdg_config_home| {
        defer allocator.free(xdg_config_home);
        return defaultConfigPathFromEnv(allocator, xdg_config_home, null);
    }

    const home = try std.process.getEnvVarOwned(allocator, "HOME");
    defer allocator.free(home);
    return defaultConfigPathFromEnv(allocator, null, home);
}

/// builds the default shisa.toml path from already-read environment values.
/// xdg_config_home and home are borrowed and are not retained.
/// caller owns the returned slice and must free it with allocator.
/// errors: MissingHome when both inputs are null; OutOfMemory on allocation failure.
pub fn defaultConfigPathFromEnv(allocator: std.mem.Allocator, xdg_config_home: ?[]const u8, home: ?[]const u8) ![]u8 {
    if (xdg_config_home) |base| return std.fmt.allocPrint(allocator, "{s}/shisa/shisa.toml", .{base});
    if (home) |base| return std.fmt.allocPrint(allocator, "{s}/.config/shisa/shisa.toml", .{base});
    return error.MissingHome;
}

fn windowsDefaultConfigPath(allocator: std.mem.Allocator) ![]u8 {
    const app_data = std.process.getEnvVarOwned(allocator, "APPDATA") catch |err| switch (err) {
        error.EnvironmentVariableNotFound => null,
        else => return err,
    };
    if (app_data) |base| {
        defer allocator.free(base);
        return windowsDefaultConfigPathFromEnv(allocator, base, null);
    }

    const user_profile = try std.process.getEnvVarOwned(allocator, "USERPROFILE");
    defer allocator.free(user_profile);
    return windowsDefaultConfigPathFromEnv(allocator, null, user_profile);
}

fn windowsDefaultConfigPathFromEnv(allocator: std.mem.Allocator, app_data: ?[]const u8, user_profile: ?[]const u8) ![]u8 {
    if (app_data) |base| return std.fmt.allocPrint(allocator, "{s}\\shisa\\shisa.toml", .{base});
    const base = user_profile orelse return error.MissingHome;
    return std.fmt.allocPrint(allocator, "{s}\\AppData\\Roaming\\shisa\\shisa.toml", .{base});
}

/// reads a config file or returns the built-in default config when the file is absent.
/// path must be an absolute path; caller owns the returned slice and must free it with allocator.
/// errors: filesystem open/read errors except FileNotFound; FileTooBig when the file exceeds max_config_bytes; OutOfMemory on allocation failure.
pub fn readConfigOrDefault(allocator: std.mem.Allocator, path: []const u8) ![]u8 {
    var file = std.fs.openFileAbsolute(path, .{}) catch |err| switch (err) {
        error.FileNotFound => return allocator.dupe(u8, shisa_config.default_config_text),
        else => return err,
    };
    defer file.close();
    return file.readToEndAlloc(allocator, max_config_bytes);
}

/// builds the directory path that contains the default shisa.toml.
/// caller owns the returned slice and must free it with allocator.
/// environment: follows defaultConfigPath, including XDG_CONFIG_HOME and HOME.
/// errors: MissingConfigDir if the config path has no dirname; plus defaultConfigPath errors.
pub fn configDirPath(allocator: std.mem.Allocator) ![]u8 {
    const config_path = try defaultConfigPath(allocator);
    defer allocator.free(config_path);
    const dir = std.fs.path.dirname(config_path) orelse return error.MissingConfigDir;
    return allocator.dupe(u8, dir);
}

/// builds the configured plugin directory path.
/// caller owns the returned slice and must free it with allocator.
/// environment: follows configDirPath, including XDG_CONFIG_HOME and HOME.
/// errors: MissingConfigDir from configDirPath; EnvironmentVariableNotFound when HOME is required and missing; OutOfMemory on allocation failure.
pub fn pluginsDirPath(allocator: std.mem.Allocator) ![]u8 {
    const dir = try configDirPath(allocator);
    defer allocator.free(dir);
    return std.fmt.allocPrint(allocator, "{s}/plugins", .{dir});
}

/// returns a compact access status for a path relative to the current process.
/// path is borrowed and no allocation occurs.
/// errors: none; FileNotFound maps to "missing", AccessDenied maps to "denied", and other access errors map to "error".
pub fn pathAccessStatus(path: []const u8) []const u8 {
    std.fs.cwd().access(path, .{}) catch |err| switch (err) {
        error.FileNotFound => return "missing",
        error.AccessDenied => return "denied",
        else => return "error",
    };
    return "present";
}

pub fn currentShellNameAlloc(allocator: std.mem.Allocator) ![]u8 {
    if (builtin.os.tag == .windows) return allocator.dupe(u8, "pwsh");
    const shell_path = std.process.getEnvVarOwned(allocator, "SHELL") catch |err| switch (err) {
        error.EnvironmentVariableNotFound => return passwdShellNameAlloc(allocator) catch allocator.dupe(u8, "zsh"),
        else => return err,
    };
    defer allocator.free(shell_path);
    const base = std.fs.path.basename(shell_path);
    return allocator.dupe(u8, base);
}

pub fn detectTerminalAlloc(allocator: std.mem.Allocator) ![]u8 {
    if (std.process.getEnvVarOwned(allocator, "TERM_PROGRAM")) |value| return value else |_| {}
    if (std.process.hasEnvVarConstant("GHOSTTY_RESOURCES_DIR")) return allocator.dupe(u8, "Ghostty");
    if (std.process.hasEnvVarConstant("KITTY_WINDOW_ID")) return allocator.dupe(u8, "kitty");
    if (std.process.hasEnvVarConstant("WT_SESSION")) return allocator.dupe(u8, "Windows Terminal");
    if (std.process.hasEnvVarConstant("WEZTERM_EXECUTABLE")) return allocator.dupe(u8, "WezTerm");
    if (std.process.hasEnvVarConstant("ALACRITTY_LOG")) return allocator.dupe(u8, "Alacritty");
    if (std.process.getEnvVarOwned(allocator, "TERM")) |value| return value else |_| {}
    return allocator.dupe(u8, "unknown");
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

test "default config path prefers xdg" {
    const path = try defaultConfigPathFromEnv(std.testing.allocator, "/tmp/xdg", "/tmp/home");
    defer std.testing.allocator.free(path);
    try std.testing.expectEqualStrings("/tmp/xdg/shisa/shisa.toml", path);
}

test "default config path falls back to home" {
    const path = try defaultConfigPathFromEnv(std.testing.allocator, null, "/tmp/home");
    defer std.testing.allocator.free(path);
    try std.testing.expectEqualStrings("/tmp/home/.config/shisa/shisa.toml", path);
}

test "windows default config path prefers app data" {
    const path = try windowsDefaultConfigPathFromEnv(std.testing.allocator, "C:\\Users\\me\\AppData\\Roaming", "C:\\Users\\me");
    defer std.testing.allocator.free(path);
    try std.testing.expectEqualStrings("C:\\Users\\me\\AppData\\Roaming\\shisa\\shisa.toml", path);
}

test "windows default config path falls back to user profile" {
    const path = try windowsDefaultConfigPathFromEnv(std.testing.allocator, null, "C:\\Users\\me");
    defer std.testing.allocator.free(path);
    try std.testing.expectEqualStrings("C:\\Users\\me\\AppData\\Roaming\\shisa\\shisa.toml", path);
}

/// appends formatted text to an ArrayList.
/// out must remain valid for the call; args follow std.fmt.allocPrint semantics.
/// ownership: temporary formatted storage is freed before return; out retains appended bytes.
/// errors: OutOfMemory from formatting or appending.
pub fn appendFmt(allocator: std.mem.Allocator, out: *std.ArrayList(u8), comptime format: []const u8, args: anytype) !void {
    const line = try std.fmt.allocPrint(allocator, format, args);
    defer allocator.free(line);
    try out.appendSlice(allocator, line);
}

/// consumes and returns the next CLI argument after index.
/// args is borrowed; index is advanced only when a value exists.
/// ownership: returned slice aliases args and must not be freed.
/// errors: MissingValue when there is no following argument.
pub fn nextValue(args: []const []const u8, index: *usize) ![]const u8 {
    if (index.* + 1 >= args.len) return error.MissingValue;
    index.* += 1;
    return args[index.*];
}

/// reports whether a child-process termination value is exit code 0.
/// term is borrowed by value and no allocation occurs.
/// errors: none.
pub fn exitedZero(term: std.process.Child.Term) bool {
    return switch (term) {
        .Exited => |code| code == 0,
        else => false,
    };
}

/// runs a git-style command in cwd_path and returns stdout when it exits 0.
/// argv and cwd_path are borrowed for the call; argv[0] is expanded through PATH.
/// caller owns the returned stdout slice and must free it with allocator.
/// errors: CommandFailed for non-zero exits; process spawn errors such as FileNotFound; OutOfMemory on allocation failure.
pub fn gitOutputAlloc(allocator: std.mem.Allocator, cwd_path: []const u8, argv: []const []const u8) ![]u8 {
    const result = try std.process.Child.run(.{
        .allocator = allocator,
        .argv = argv,
        .cwd = cwd_path,
        .max_output_bytes = 1024 * 1024,
        .expand_arg0 = .expand,
    });
    defer allocator.free(result.stderr);
    if (!exitedZero(result.term)) {
        allocator.free(result.stdout);
        return error.CommandFailed;
    }
    return result.stdout;
}

/// quotes a byte slice as one POSIX shell single-quoted word.
/// value is borrowed; caller owns the returned slice and must free it with allocator.
/// errors: OutOfMemory on allocation failure.
pub fn shellSingleQuoteAlloc(allocator: std.mem.Allocator, value: []const u8) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);
    try out.append(allocator, '\'');
    for (value) |byte| {
        if (byte == '\'') {
            try out.appendSlice(allocator, "'\\''");
        } else {
            try out.append(allocator, byte);
        }
    }
    try out.append(allocator, '\'');
    return out.toOwnedSlice(allocator);
}

pub fn siblingExecutablePath(allocator: std.mem.Allocator, name: []const u8) ![]u8 {
    const self_path = try std.fs.selfExePathAlloc(allocator);
    defer allocator.free(self_path);
    const dir = std.fs.path.dirname(self_path) orelse ".";
    return std.fs.path.join(allocator, &.{ dir, name });
}

pub fn waitForPath(path: []const u8, timeout_ms: i64) !void {
    const start = std.time.milliTimestamp();
    while (std.time.milliTimestamp() - start < timeout_ms) {
        std.fs.cwd().access(path, .{}) catch {
            std.Thread.sleep(10 * std.time.ns_per_ms);
            continue;
        };
        return;
    }
    return error.Timeout;
}

test "shell single quote escapes metacharacters" {
    inline for (.{
        .{ "", "''" },
        .{ "`date`", "'`date`'" },
        .{ "$(touch /tmp/pwned)", "'$(touch /tmp/pwned)'" },
        .{ "a&b|c;d>e<f", "'a&b|c;d>e<f'" },
        .{ "it's done", "'it'\\''s done'" },
        .{ "Done ✓", "'Done ✓'" },
    }) |case| {
        const quoted = try shellSingleQuoteAlloc(std.testing.allocator, case[0]);
        defer std.testing.allocator.free(quoted);
        try std.testing.expectEqualStrings(case[1], quoted);
    }
}
