const std = @import("std");

pub const Logger = struct {
    allocator: std.mem.Allocator,
    file: std.fs.File,

    pub const Options = struct {
        max_bytes: u64 = 10 * 1024 * 1024,
        backups: u8 = 5,
    };

    pub fn open(allocator: std.mem.Allocator, path: []const u8) !Logger {
        return openWithOptions(allocator, path, .{});
    }

    pub fn openWithOptions(allocator: std.mem.Allocator, path: []const u8, options: Options) !Logger {
        if (std.fs.path.dirname(path)) |parent| {
            try std.fs.cwd().makePath(parent);
        }

        try rotateIfNeeded(allocator, path, options);

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

fn rotateIfNeeded(allocator: std.mem.Allocator, path: []const u8, options: Logger.Options) !void {
    if (options.max_bytes == 0 or options.backups == 0) return;

    var existing = std.fs.openFileAbsolute(path, .{}) catch |err| switch (err) {
        error.FileNotFound => return,
        else => return err,
    };
    defer existing.close();

    const size = try existing.getEndPos();
    if (size < options.max_bytes) return;

    var index = options.backups;
    while (index > 0) : (index -= 1) {
        const dst = try numberedPath(allocator, path, index);
        defer allocator.free(dst);

        if (index == options.backups) {
            std.fs.deleteFileAbsolute(dst) catch |err| switch (err) {
                error.FileNotFound => {},
                else => return err,
            };
        }

        const src = if (index == 1) try allocator.dupe(u8, path) else try numberedPath(allocator, path, index - 1);
        defer allocator.free(src);

        std.fs.renameAbsolute(src, dst) catch |err| switch (err) {
            error.FileNotFound => {},
            else => return err,
        };
    }
}

fn numberedPath(allocator: std.mem.Allocator, path: []const u8, index: u8) ![]u8 {
    return std.fmt.allocPrint(allocator, "{s}.{d}", .{ path, index });
}

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

test "rotates size-limited logs" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-log-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};

    const log_path = try std.fmt.allocPrint(allocator, "{s}/shisad.log", .{dir_path});
    defer allocator.free(log_path);

    try std.fs.cwd().makePath(dir_path);
    {
        var seed = try std.fs.createFileAbsolute(log_path, .{});
        defer seed.close();
        try seed.writeAll("123456789");
    }

    var logger = try Logger.openWithOptions(allocator, log_path, .{ .max_bytes = 8, .backups = 2 });
    try logger.info("rotated", "new file");
    logger.deinit();

    const rotated_path = try numberedPath(allocator, log_path, 1);
    defer allocator.free(rotated_path);
    const rotated = try std.fs.cwd().readFileAlloc(allocator, rotated_path, 4096);
    defer allocator.free(rotated);
    try std.testing.expectEqualStrings("123456789", rotated);

    const current = try std.fs.cwd().readFileAlloc(allocator, log_path, 4096);
    defer allocator.free(current);
    try std.testing.expect(std.mem.indexOf(u8, current, "\"event\":\"rotated\"") != null);
}
