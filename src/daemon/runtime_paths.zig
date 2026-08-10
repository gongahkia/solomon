const std = @import("std");

pub fn defaultConfigPathAlloc(allocator: std.mem.Allocator) ![]u8 {
    const xdg = std.process.getEnvVarOwned(allocator, "XDG_CONFIG_HOME") catch |err| switch (err) {
        error.EnvironmentVariableNotFound => null,
        else => return err,
    };
    if (xdg) |xdg_config_home| {
        defer allocator.free(xdg_config_home);
        return std.fmt.allocPrint(allocator, "{s}/shisa/shisa.toml", .{xdg_config_home});
    }
    const home = std.process.getEnvVarOwned(allocator, "HOME") catch |err| switch (err) {
        error.EnvironmentVariableNotFound => return error.MissingHome,
        else => return err,
    };
    defer allocator.free(home);
    return std.fmt.allocPrint(allocator, "{s}/.config/shisa/shisa.toml", .{home});
}

pub fn defaultPluginsDirPathAlloc(allocator: std.mem.Allocator) ![]u8 {
    const config_path = try defaultConfigPathAlloc(allocator);
    defer allocator.free(config_path);
    const dir = std.fs.path.dirname(config_path) orelse return error.MissingConfigDir;
    return std.fmt.allocPrint(allocator, "{s}/plugins", .{dir});
}

pub fn defaultPinsPathAlloc(allocator: std.mem.Allocator) ![]u8 {
    const config_path = try defaultConfigPathAlloc(allocator);
    defer allocator.free(config_path);
    const dir = std.fs.path.dirname(config_path) orelse return error.MissingConfigDir;
    return std.fmt.allocPrint(allocator, "{s}/pins", .{dir});
}
