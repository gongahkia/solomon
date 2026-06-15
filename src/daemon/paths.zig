const std = @import("std");
const builtin = @import("builtin");

pub fn defaultSocketPath(allocator: std.mem.Allocator) ![]u8 {
    return switch (builtin.os.tag) {
        .macos => macosSocketPath(allocator),
        .linux => linuxSocketPath(allocator),
        else => error.UnsupportedSocketPlatform,
    };
}

fn macosSocketPath(allocator: std.mem.Allocator) ![]u8 {
    const home = try std.process.getEnvVarOwned(allocator, "HOME");
    defer allocator.free(home);
    return std.fmt.allocPrint(allocator, "{s}/Library/Caches/shisa/shisa.sock", .{home});
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
