const std = @import("std");

pub const Logger = struct {
    allocator: std.mem.Allocator,
    file: std.fs.File,

    pub fn open(allocator: std.mem.Allocator, path: []const u8) !Logger {
        if (std.fs.path.dirname(path)) |parent| {
            try std.fs.cwd().makePath(parent);
        }

        const file = try std.fs.createFileAbsolute(path, .{
            .read = true,
            .truncate = false,
            .mode = 0o600,
        });
        try file.seekFromEnd(0);

        return .{
            .allocator = allocator,
            .file = file,
        };
    }

    pub fn deinit(self: *Logger) void {
        self.file.close();
        self.* = undefined;
    }

    pub fn info(self: *Logger, event: []const u8, message: []const u8) !void {
        try self.write("info", event, message);
    }

    pub fn warn(self: *Logger, event: []const u8, message: []const u8) !void {
        try self.write("warn", event, message);
    }

    fn write(self: *Logger, level: []const u8, event: []const u8, message: []const u8) !void {
        const line = try std.fmt.allocPrint(
            self.allocator,
            "{{\"ts\":{d},\"level\":\"{s}\",\"event\":\"{s}\",\"message\":\"{s}\"}}\n",
            .{ std.time.timestamp(), level, event, message },
        );
        defer self.allocator.free(line);
        try self.file.writeAll(line);
    }
};

test "writes json log line" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-log-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};

    const log_path = try std.fmt.allocPrint(allocator, "{s}/shisad.log", .{dir_path});
    defer allocator.free(log_path);

    var logger = try Logger.open(allocator, log_path);
    try logger.info("test", "logger ready");
    logger.deinit();

    const contents = try std.fs.cwd().readFileAlloc(allocator, log_path, 4096);
    defer allocator.free(contents);
    try std.testing.expect(std.mem.indexOf(u8, contents, "\"level\":\"info\"") != null);
    try std.testing.expect(std.mem.indexOf(u8, contents, "\"event\":\"test\"") != null);
}
