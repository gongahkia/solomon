const std = @import("std");
const builtin = @import("builtin");
const win = std.os.windows;

const TOKEN_QUERY: win.DWORD = 0x0008;
const TokenUser: win.DWORD = 1;
const SID_AND_ATTRIBUTES = extern struct {
    Sid: *anyopaque,
    Attributes: win.DWORD,
};
const TOKEN_USER = extern struct {
    User: SID_AND_ATTRIBUTES,
};

extern "advapi32" fn OpenProcessToken(ProcessHandle: win.HANDLE, DesiredAccess: win.DWORD, TokenHandle: *win.HANDLE) callconv(.winapi) win.BOOL;
extern "advapi32" fn GetTokenInformation(TokenHandle: win.HANDLE, TokenInformationClass: win.DWORD, TokenInformation: ?*anyopaque, TokenInformationLength: win.DWORD, ReturnLength: *win.DWORD) callconv(.winapi) win.BOOL;
extern "advapi32" fn ConvertSidToStringSidW(Sid: *anyopaque, StringSid: *win.LPWSTR) callconv(.winapi) win.BOOL;
extern "kernel32" fn LocalFree(hMem: ?*anyopaque) callconv(.winapi) ?*anyopaque;

/// builds the daemon Unix-socket path for the current platform.
/// caller owns the returned slice and must free it with allocator.
/// environment: macOS reads HOME; Linux reads XDG_RUNTIME_DIR when set.
/// errors: UnsupportedSocketPlatform for non-macOS/non-Linux targets; EnvironmentVariableNotFound when HOME is required and missing; OutOfMemory on allocation failure.
pub fn defaultSocketPath(allocator: std.mem.Allocator) ![]u8 {
    return switch (builtin.os.tag) {
        .macos => macosSocketPath(allocator),
        .linux => linuxSocketPath(allocator),
        .windows => windowsSocketPath(allocator),
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
        .windows => windowsLogPath(allocator),
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

fn windowsSocketPath(allocator: std.mem.Allocator) ![]u8 {
    const sid = try windowsCurrentSidAlloc(allocator);
    defer allocator.free(sid);
    return windowsPipePathFromSidAlloc(allocator, sid);
}

fn windowsLogPath(allocator: std.mem.Allocator) ![]u8 {
    const local_app_data = std.process.getEnvVarOwned(allocator, "LOCALAPPDATA") catch |err| switch (err) {
        error.EnvironmentVariableNotFound => null,
        else => return err,
    };
    if (local_app_data) |path| {
        defer allocator.free(path);
        return windowsLogPathFromEnv(allocator, path, null);
    }

    const user_profile = try std.process.getEnvVarOwned(allocator, "USERPROFILE");
    defer allocator.free(user_profile);
    return windowsLogPathFromEnv(allocator, null, user_profile);
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

pub fn windowsPipePathFromSidAlloc(allocator: std.mem.Allocator, sid: []const u8) ![]u8 {
    if (!validWindowsSidForPipeName(sid)) return error.InvalidSid;
    return std.fmt.allocPrint(allocator, "\\\\.\\pipe\\shisa-{s}", .{sid});
}

fn windowsLogPathFromEnv(allocator: std.mem.Allocator, local_app_data: ?[]const u8, user_profile: ?[]const u8) ![]u8 {
    if (local_app_data) |path| return std.fmt.allocPrint(allocator, "{s}\\shisa\\shisad.log", .{path});
    const base = user_profile orelse return error.EnvironmentVariableNotFound;
    return std.fmt.allocPrint(allocator, "{s}\\AppData\\Local\\shisa\\shisad.log", .{base});
}

fn validWindowsSidForPipeName(sid: []const u8) bool {
    if (!std.mem.startsWith(u8, sid, "S-")) return false;
    for (sid) |byte| {
        if ((byte >= '0' and byte <= '9') or byte == 'S' or byte == '-') continue;
        return false;
    }
    return true;
}

fn windowsCurrentSidAlloc(allocator: std.mem.Allocator) ![]u8 {
    if (std.process.getEnvVarOwned(allocator, "SHISA_WINDOWS_SID")) |sid| return sid else |err| switch (err) {
        error.EnvironmentVariableNotFound => {},
        else => return err,
    }
    if (builtin.os.tag != .windows) return error.UnsupportedSocketPlatform;
    return windowsCurrentSidFromTokenAlloc(allocator);
}

fn windowsCurrentSidFromTokenAlloc(allocator: std.mem.Allocator) ![]u8 {
    var token: win.HANDLE = undefined;
    if (OpenProcessToken(win.GetCurrentProcess(), TOKEN_QUERY, &token) == 0) return error.OpenProcessTokenFailed;
    defer win.CloseHandle(token);

    var needed: win.DWORD = 0;
    _ = GetTokenInformation(token, TokenUser, null, 0, &needed);
    if (needed == 0) return error.GetTokenInformationFailed;

    const raw = try allocator.alloc(u8, needed);
    defer allocator.free(raw);
    if (GetTokenInformation(token, TokenUser, raw.ptr, needed, &needed) == 0) return error.GetTokenInformationFailed;

    const token_user: *TOKEN_USER = @ptrCast(@alignCast(raw.ptr));
    var sid_w: win.LPWSTR = undefined;
    if (ConvertSidToStringSidW(token_user.User.Sid, &sid_w) == 0) return error.ConvertSidToStringSidFailed;
    defer _ = LocalFree(sid_w);

    var len: usize = 0;
    while (sid_w[len] != 0) : (len += 1) {}
    return std.unicode.utf16LeToUtf8Alloc(allocator, sid_w[0..len]);
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

test "windows pipe path uses SID" {
    const path = try windowsPipePathFromSidAlloc(std.testing.allocator, "S-1-5-21-1-2-3-1001");
    defer std.testing.allocator.free(path);
    try std.testing.expectEqualStrings("\\\\.\\pipe\\shisa-S-1-5-21-1-2-3-1001", path);
}

test "windows pipe path rejects unsafe SID" {
    try std.testing.expectError(error.InvalidSid, windowsPipePathFromSidAlloc(std.testing.allocator, "S-1\\bad"));
}

test "windows log path prefers local app data" {
    const path = try windowsLogPathFromEnv(std.testing.allocator, "C:\\Users\\me\\AppData\\Local", "C:\\Users\\me");
    defer std.testing.allocator.free(path);
    try std.testing.expectEqualStrings("C:\\Users\\me\\AppData\\Local\\shisa\\shisad.log", path);
}

test "windows log path falls back to user profile" {
    const path = try windowsLogPathFromEnv(std.testing.allocator, null, "C:\\Users\\me");
    defer std.testing.allocator.free(path);
    try std.testing.expectEqualStrings("C:\\Users\\me\\AppData\\Local\\shisa\\shisad.log", path);
}
