const std = @import("std");
const builtin = @import("builtin");

/// builds the daemon Unix-socket path for the current platform.
/// caller owns the returned slice and must free it with allocator.
/// environment: macOS reads HOME; Linux reads XDG_RUNTIME_DIR when set.
/// errors: UnsupportedSocketPlatform for non-macOS/non-Linux targets; EnvironmentVariableNotFound when HOME is required and missing; OutOfMemory on allocation failure.
pub fn defaultSocketPath(allocator: std.mem.Allocator) ![]u8 {
    return switch (builtin.os.tag) {
        .macos => macosSocketPath(allocator),
        .linux => linuxSocketPath(allocator),
        else => error.UnsupportedSocketPlatform,
    };
}

/// builds the daemon log-file path for the current platform.
/// caller owns the returned slice and must free it with allocator.
/// environment: macOS reads HOME; Linux reads XDG_STATE_HOME when set, then HOME.
/// errors: UnsupportedLogPlatform for non-macOS/non-Linux targets; EnvironmentVariableNotFound when HOME is required and missing; OutOfMemory on allocation failure.
pub fn defaultLogPath(allocator: std.mem.Allocator) ![]u8 {
    return switch (builtin.os.tag) {
        .macos => macosLogPath(allocator),
        .linux => linuxLogPath(allocator),
        else => error.UnsupportedLogPlatform,
    };
}

fn macosSocketPath(allocator: std.mem.Allocator) ![]u8 {
    const home = try std.process.getEnvVarOwned(allocator, "HOME");
    defer allocator.free(home);
    return std.fmt.allocPrint(allocator, "{s}/Library/Caches/shisa/shisa.sock", .{home});
}

fn macosLogPath(allocator: std.mem.Allocator) ![]u8 {
    const home = try std.process.getEnvVarOwned(allocator, "HOME");
    defer allocator.free(home);
    return std.fmt.allocPrint(allocator, "{s}/Library/Logs/shisa/shisad.log", .{home});
}

fn linuxSocketPath(allocator: std.mem.Allocator) ![]u8 {
    const xdg = std.process.getEnvVarOwned(allocator, "XDG_RUNTIME_DIR") catch |err| switch (err) {
        error.EnvironmentVariableNotFound => null,
        else => return err,
    };
    if (xdg) |runtime_dir| {
        defer allocator.free(runtime_dir);
        return std.fmt.allocPrint(allocator, "{s}/shisa.sock", .{runtime_dir});
    }

    return std.fmt.allocPrint(allocator, "/run/user/{d}/shisa.sock", .{std.posix.getuid()});
}

fn linuxLogPath(allocator: std.mem.Allocator) ![]u8 {
    const state_home = std.process.getEnvVarOwned(allocator, "XDG_STATE_HOME") catch |err| switch (err) {
        error.EnvironmentVariableNotFound => null,
        else => return err,
    };
    if (state_home) |path| {
        defer allocator.free(path);
        return std.fmt.allocPrint(allocator, "{s}/shisa/shisad.log", .{path});
    }

    const home = try std.process.getEnvVarOwned(allocator, "HOME");
    defer allocator.free(home);
    return std.fmt.allocPrint(allocator, "{s}/.local/state/shisa/shisad.log", .{home});
}
