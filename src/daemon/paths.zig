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
    return macosSocketPathFromEnv(allocator, home);
}

fn macosLogPath(allocator: std.mem.Allocator) ![]u8 {
    const home = try std.process.getEnvVarOwned(allocator, "HOME");
    defer allocator.free(home);
    return macosLogPathFromEnv(allocator, home);
}

fn linuxSocketPath(allocator: std.mem.Allocator) ![]u8 {
    const xdg = std.process.getEnvVarOwned(allocator, "XDG_RUNTIME_DIR") catch |err| switch (err) {
        error.EnvironmentVariableNotFound => null,
        else => return err,
    };
    if (xdg) |runtime_dir| {
        defer allocator.free(runtime_dir);
        return linuxSocketPathFromEnv(allocator, runtime_dir, std.posix.getuid());
    }

    return linuxSocketPathFromEnv(allocator, null, std.posix.getuid());
}

fn linuxLogPath(allocator: std.mem.Allocator) ![]u8 {
    const state_home = std.process.getEnvVarOwned(allocator, "XDG_STATE_HOME") catch |err| switch (err) {
        error.EnvironmentVariableNotFound => null,
        else => return err,
    };
    if (state_home) |path| {
        defer allocator.free(path);
        return linuxLogPathFromEnv(allocator, path, null);
    }

    const home = try std.process.getEnvVarOwned(allocator, "HOME");
    defer allocator.free(home);
    return linuxLogPathFromEnv(allocator, null, home);
}

fn macosSocketPathFromEnv(allocator: std.mem.Allocator, home: ?[]const u8) ![]u8 {
    const base = home orelse return error.EnvironmentVariableNotFound;
    return std.fmt.allocPrint(allocator, "{s}/Library/Caches/shisa/shisa.sock", .{base});
}

fn macosLogPathFromEnv(allocator: std.mem.Allocator, home: ?[]const u8) ![]u8 {
    const base = home orelse return error.EnvironmentVariableNotFound;
    return std.fmt.allocPrint(allocator, "{s}/Library/Logs/shisa/shisad.log", .{base});
}

fn linuxSocketPathFromEnv(allocator: std.mem.Allocator, xdg_runtime_dir: ?[]const u8, uid: u32) ![]u8 {
    if (xdg_runtime_dir) |runtime_dir| return std.fmt.allocPrint(allocator, "{s}/shisa.sock", .{runtime_dir});
    return std.fmt.allocPrint(allocator, "/run/user/{d}/shisa.sock", .{uid});
}

fn linuxLogPathFromEnv(allocator: std.mem.Allocator, xdg_state_home: ?[]const u8, home: ?[]const u8) ![]u8 {
    if (xdg_state_home) |path| return std.fmt.allocPrint(allocator, "{s}/shisa/shisad.log", .{path});
    const base = home orelse return error.EnvironmentVariableNotFound;
    return std.fmt.allocPrint(allocator, "{s}/.local/state/shisa/shisad.log", .{base});
}

test "macos socket path uses home" {
    const path = try macosSocketPathFromEnv(std.testing.allocator, "/tmp/home");
    defer std.testing.allocator.free(path);
    try std.testing.expectEqualStrings("/tmp/home/Library/Caches/shisa/shisa.sock", path);
}

test "macos log path uses home" {
    const path = try macosLogPathFromEnv(std.testing.allocator, "/tmp/home");
    defer std.testing.allocator.free(path);
    try std.testing.expectEqualStrings("/tmp/home/Library/Logs/shisa/shisad.log", path);
}

test "macos paths require home" {
    try std.testing.expectError(error.EnvironmentVariableNotFound, macosSocketPathFromEnv(std.testing.allocator, null));
    try std.testing.expectError(error.EnvironmentVariableNotFound, macosLogPathFromEnv(std.testing.allocator, null));
}

test "linux socket path prefers runtime dir" {
    const path = try linuxSocketPathFromEnv(std.testing.allocator, "/tmp/runtime", 42);
    defer std.testing.allocator.free(path);
    try std.testing.expectEqualStrings("/tmp/runtime/shisa.sock", path);
}

test "linux socket path falls back to uid" {
    const path = try linuxSocketPathFromEnv(std.testing.allocator, null, 42);
    defer std.testing.allocator.free(path);
    try std.testing.expectEqualStrings("/run/user/42/shisa.sock", path);
}

test "linux log path prefers state home" {
    const path = try linuxLogPathFromEnv(std.testing.allocator, "/tmp/state", "/tmp/home");
    defer std.testing.allocator.free(path);
    try std.testing.expectEqualStrings("/tmp/state/shisa/shisad.log", path);
}

test "linux log path falls back to home" {
    const path = try linuxLogPathFromEnv(std.testing.allocator, null, "/tmp/home");
    defer std.testing.allocator.free(path);
    try std.testing.expectEqualStrings("/tmp/home/.local/state/shisa/shisad.log", path);
}

test "linux log path requires home without state home" {
    try std.testing.expectError(error.EnvironmentVariableNotFound, linuxLogPathFromEnv(std.testing.allocator, null, null));
}
