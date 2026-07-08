const std = @import("std");
const cli_config = @import("config.zig");
const cli_util = @import("util.zig");
const daemon_paths = @import("../daemon/paths.zig");

pub const help_text =
    \\usage: shisa uninstall [--shell NAME|--all-shells] [--restore-starship] [--purge --yes] [--dry-run]
    \\
    \\options:
    \\  --shell NAME        remove the hook from zsh, bash, fish, nu, or pwsh startup
    \\  --all-shells        remove known shisa hook blocks from all supported startup files
    \\  --restore-starship  add a Starship init line when the target startup file has none
    \\  --purge             remove shisa config, cache, state, logs, socket, and lock files
    \\  --yes               confirm --purge
    \\  --dry-run           print planned removals without writing
    \\
;

const Config = struct {
    shell_name: ?[]const u8 = null,
    all_shells: bool = false,
    restore_starship: bool = false,
    purge: bool = false,
    yes: bool = false,
    dry_run: bool = false,
};

const supported_shells = [_][]const u8{ "zsh", "bash", "fish", "nu", "pwsh" };
const legacy_hook_marker_start = "# >>> shisa hook >>>";
const legacy_hook_marker_end = "# <<< shisa hook <<<";

pub fn command(allocator: std.mem.Allocator, args: []const []const u8) !void {
    const config = try parseArgs(args);
    if (config.purge and !config.yes and !config.dry_run) return error.PurgeRequiresYes;

    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);

    if (config.all_shells) {
        for (supported_shells) |shell_name| {
            try uninstallShellHook(allocator, config, shell_name, &out);
        }
    } else {
        const shell_name = if (config.shell_name) |shell|
            shell
        else
            try cli_util.currentShellNameAlloc(allocator);
        defer if (config.shell_name == null) allocator.free(shell_name);
        try uninstallShellHook(allocator, config, shell_name, &out);
    }

    if (config.purge) try purgeShisaPaths(allocator, config.dry_run, &out);
    if (out.items.len == 0) try cli_util.appendFmt(allocator, &out, "uninstall: no changes\n", .{});
    try std.fs.File.stdout().writeAll(out.items);
}

fn parseArgs(args: []const []const u8) !Config {
    var config = Config{};
    var i: usize = 0;
    while (i < args.len) : (i += 1) {
        const arg = args[i];
        if (std.mem.eql(u8, arg, "--help") or std.mem.eql(u8, arg, "-h")) {
            try std.fs.File.stdout().writeAll(help_text);
            std.process.exit(0);
        } else if (std.mem.eql(u8, arg, "--shell")) {
            i += 1;
            if (i >= args.len) return error.MissingValue;
            if (!validShell(args[i])) return error.InvalidShell;
            config.shell_name = args[i];
        } else if (std.mem.eql(u8, arg, "--all-shells")) {
            config.all_shells = true;
        } else if (std.mem.eql(u8, arg, "--restore-starship")) {
            config.restore_starship = true;
        } else if (std.mem.eql(u8, arg, "--purge")) {
            config.purge = true;
        } else if (std.mem.eql(u8, arg, "--yes")) {
            config.yes = true;
        } else if (std.mem.eql(u8, arg, "--dry-run")) {
            config.dry_run = true;
        } else {
            return error.UnknownUninstallArgument;
        }
    }
    if (config.shell_name != null and config.all_shells) return error.InvalidUninstallMode;
    return config;
}

fn validShell(shell_name: []const u8) bool {
    for (supported_shells) |candidate| {
        if (std.mem.eql(u8, shell_name, candidate)) return true;
    }
    return false;
}

fn uninstallShellHook(allocator: std.mem.Allocator, config: Config, shell_name: []const u8, out: *std.ArrayList(u8)) !void {
    const path = try shellHookTargetPathForShellAlloc(allocator, shell_name);
    defer allocator.free(path);
    const source = try readFileIfPresentAlloc(allocator, path);
    defer allocator.free(source);
    if (source.len == 0) return;

    const without_hook = try removeShisaHookBlocksAlloc(allocator, source);
    defer allocator.free(without_hook);
    const restored = if (config.restore_starship)
        try ensureStarshipInitAlloc(allocator, without_hook, shell_name)
    else
        try allocator.dupe(u8, without_hook);
    defer allocator.free(restored);

    if (std.mem.eql(u8, restored, source)) return;
    if (config.dry_run) {
        try cli_util.appendFmt(allocator, out, "would update {s}\n", .{path});
        return;
    }
    var file = try std.fs.createFileAbsolute(path, .{ .truncate = true });
    defer file.close();
    try file.writeAll(restored);
    try cli_util.appendFmt(allocator, out, "updated {s}\n", .{path});
}

fn removeShisaHookBlocksAlloc(allocator: std.mem.Allocator, source: []const u8) ![]u8 {
    var current = try allocator.dupe(u8, source);
    errdefer allocator.free(current);
    while (try removeBlockOnceAlloc(allocator, current, cli_config.shell_hook_marker_start, cli_config.shell_hook_marker_end)) |next| {
        allocator.free(current);
        current = next;
    }
    while (try removeBlockOnceAlloc(allocator, current, legacy_hook_marker_start, legacy_hook_marker_end)) |next| {
        allocator.free(current);
        current = next;
    }
    return current;
}

fn removeBlockOnceAlloc(allocator: std.mem.Allocator, source: []const u8, start_marker: []const u8, end_marker: []const u8) !?[]u8 {
    const start = std.mem.indexOf(u8, source, start_marker) orelse return null;
    const end_marker_start = std.mem.indexOfPos(u8, source, start + start_marker.len, end_marker) orelse return null;
    var remove_start = start;
    if (remove_start > 0 and source[remove_start - 1] == '\n') remove_start -= 1;
    const end_marker_end = end_marker_start + end_marker.len;
    var remove_end = end_marker_end;
    if (remove_end < source.len and source[remove_end] == '\r') remove_end += 1;
    if (remove_end < source.len and source[remove_end] == '\n') remove_end += 1;
    var out: std.ArrayList(u8) = .empty;
    errdefer out.deinit(allocator);
    try out.appendSlice(allocator, source[0..remove_start]);
    try out.appendSlice(allocator, source[remove_end..]);
    return out.toOwnedSlice(allocator);
}

fn ensureStarshipInitAlloc(allocator: std.mem.Allocator, source: []const u8, shell_name: []const u8) ![]u8 {
    if (std.mem.indexOf(u8, source, "starship init") != null) return allocator.dupe(u8, source);
    const init_line = starshipInitLine(shell_name) orelse return allocator.dupe(u8, source);
    var out: std.ArrayList(u8) = .empty;
    errdefer out.deinit(allocator);
    try out.appendSlice(allocator, source);
    if (source.len != 0 and source[source.len - 1] != '\n') try out.append(allocator, '\n');
    try out.appendSlice(allocator, init_line);
    try out.append(allocator, '\n');
    return out.toOwnedSlice(allocator);
}

fn starshipInitLine(shell_name: []const u8) ?[]const u8 {
    if (std.mem.eql(u8, shell_name, "zsh")) return "eval \"$(starship init zsh)\"";
    if (std.mem.eql(u8, shell_name, "bash")) return "eval \"$(starship init bash)\"";
    if (std.mem.eql(u8, shell_name, "fish")) return "starship init fish | source";
    if (std.mem.eql(u8, shell_name, "pwsh")) return "Invoke-Expression (&starship init powershell)";
    return null;
}

fn purgeShisaPaths(allocator: std.mem.Allocator, dry_run: bool, out: *std.ArrayList(u8)) !void {
    var paths = std.ArrayList([]u8).empty;
    defer {
        for (paths.items) |path| allocator.free(path);
        paths.deinit(allocator);
    }
    try appendPurgePaths(allocator, &paths);
    for (paths.items) |path| {
        if (dry_run) {
            try cli_util.appendFmt(allocator, out, "would remove {s}\n", .{path});
            continue;
        }
        try removePathIfPresent(path);
        try cli_util.appendFmt(allocator, out, "removed {s}\n", .{path});
    }
}

fn appendPurgePaths(allocator: std.mem.Allocator, paths: *std.ArrayList([]u8)) !void {
    const config_path = try cli_util.defaultConfigPath(allocator);
    defer allocator.free(config_path);
    if (std.fs.path.dirname(config_path)) |config_dir| try appendUniquePath(allocator, paths, config_dir);

    if (std.process.getEnvVarOwned(allocator, "HOME")) |home| {
        defer allocator.free(home);
        try appendUniquePathFmt(allocator, paths, "{s}/.cache/shisa", .{home});
        try appendUniquePathFmt(allocator, paths, "{s}/.local/state/shisa", .{home});
        try appendUniquePathFmt(allocator, paths, "{s}/Library/Caches/shisa", .{home});
        try appendUniquePathFmt(allocator, paths, "{s}/Library/Logs/shisa", .{home});
        try appendUniquePathFmt(allocator, paths, "{s}/Library/Application Support/shisa", .{home});
    } else |_| {}

    if (std.process.getEnvVarOwned(allocator, "XDG_STATE_HOME")) |state_home| {
        defer allocator.free(state_home);
        try appendUniquePathFmt(allocator, paths, "{s}/shisa", .{state_home});
    } else |_| {}

    const socket = daemon_paths.defaultSocketPath(allocator) catch null;
    defer if (socket) |path| allocator.free(path);
    if (socket) |path| {
        try appendUniquePath(allocator, paths, path);
        const lock_path = try std.fmt.allocPrint(allocator, "{s}.lock", .{path});
        defer allocator.free(lock_path);
        try appendUniquePath(allocator, paths, lock_path);
    }
}

fn appendUniquePathFmt(allocator: std.mem.Allocator, paths: *std.ArrayList([]u8), comptime fmt: []const u8, args: anytype) !void {
    const path = try std.fmt.allocPrint(allocator, fmt, args);
    defer allocator.free(path);
    try appendUniquePath(allocator, paths, path);
}

fn appendUniquePath(allocator: std.mem.Allocator, paths: *std.ArrayList([]u8), path: []const u8) !void {
    for (paths.items) |existing| {
        if (std.mem.eql(u8, existing, path)) return;
    }
    try paths.append(allocator, try allocator.dupe(u8, path));
}

fn removePathIfPresent(path: []const u8) !void {
    std.fs.deleteTreeAbsolute(path) catch |err| switch (err) {
        error.FileNotFound => return,
        error.NotDir => {
            std.fs.deleteFileAbsolute(path) catch |file_err| switch (file_err) {
                error.FileNotFound => return,
                else => return file_err,
            };
        },
        else => return err,
    };
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
    if (std.mem.eql(u8, shell_name, "nu")) {
        const config_home = try xdgConfigHomeAlloc(allocator, home);
        defer allocator.free(config_home);
        return std.fmt.allocPrint(allocator, "{s}/nushell/config.nu", .{config_home});
    }
    if (std.mem.eql(u8, shell_name, "pwsh")) {
        const profile = std.process.getEnvVarOwned(allocator, "PROFILE") catch |err| switch (err) {
            error.EnvironmentVariableNotFound => return std.fmt.allocPrint(allocator, "{s}/Documents/PowerShell/Microsoft.PowerShell_profile.ps1", .{home}),
            else => return err,
        };
        return profile;
    }
    return error.InvalidShell;
}

fn xdgConfigHomeAlloc(allocator: std.mem.Allocator, home: []const u8) ![]u8 {
    return std.process.getEnvVarOwned(allocator, "XDG_CONFIG_HOME") catch |err| switch (err) {
        error.EnvironmentVariableNotFound => std.fmt.allocPrint(allocator, "{s}/.config", .{home}),
        else => return err,
    };
}

fn readFileIfPresentAlloc(allocator: std.mem.Allocator, path: []const u8) ![]u8 {
    var file = std.fs.openFileAbsolute(path, .{}) catch |err| switch (err) {
        error.FileNotFound => return allocator.dupe(u8, ""),
        else => return err,
    };
    defer file.close();
    return file.readToEndAlloc(allocator, cli_util.max_config_bytes);
}

test "removes shisa hook block" {
    const source =
        "before\n" ++
        cli_config.shell_hook_marker_start ++ "\n" ++
        "source shisa\n" ++
        cli_config.shell_hook_marker_end ++ "\n" ++
        "after\n";
    const actual = try removeShisaHookBlocksAlloc(std.testing.allocator, source);
    defer std.testing.allocator.free(actual);
    try std.testing.expectEqualStrings("before\nafter\n", actual);
}

test "restore starship keeps existing init" {
    const source = "eval \"$(starship init zsh)\"\n";
    const actual = try ensureStarshipInitAlloc(std.testing.allocator, source, "zsh");
    defer std.testing.allocator.free(actual);
    try std.testing.expectEqualStrings(source, actual);
}
