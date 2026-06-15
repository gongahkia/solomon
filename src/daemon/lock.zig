const std = @import("std");
const builtin = @import("builtin");

pub const InstanceLock = struct {
    allocator: std.mem.Allocator,
    file: std.fs.File,
    path: []u8,

    pub fn acquire(allocator: std.mem.Allocator, socket_path: []const u8) !InstanceLock {
        const lock_path = try std.fmt.allocPrint(allocator, "{s}.lock", .{socket_path});
        errdefer allocator.free(lock_path);

        if (std.fs.path.dirname(lock_path)) |parent| {
            try std.fs.cwd().makePath(parent);
        }

        const file = try std.fs.createFileAbsolute(lock_path, .{
            .read = true,
            .truncate = false,
            .mode = 0o600,
        });
        errdefer file.close();

        std.posix.flock(file.handle, std.posix.LOCK.EX | std.posix.LOCK.NB) catch |err| switch (err) {
            error.WouldBlock => return error.AlreadyRunning,
            else => return err,
        };

        return .{
            .allocator = allocator,
            .file = file,
            .path = lock_path,
        };
    }

    pub fn deinit(self: *InstanceLock) void {
        std.posix.flock(self.file.handle, std.posix.LOCK.UN) catch {};
        self.file.close();
        self.allocator.free(self.path);
        self.* = undefined;
    }
};

test "acquires and releases lock file" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-lock-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};

    const socket_path = try std.fmt.allocPrint(allocator, "{s}/shisa.sock", .{dir_path});
    defer allocator.free(socket_path);

    var first = try InstanceLock.acquire(allocator, socket_path);
    first.deinit();

    var second = try InstanceLock.acquire(allocator, socket_path);
    second.deinit();
}

test "rejects second process while lock is held" {
    switch (builtin.os.tag) {
        .linux, .macos => {},
        else => return,
    }

    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-lock-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};

    const socket_path = try std.fmt.allocPrint(allocator, "{s}/shisa.sock", .{dir_path});
    defer allocator.free(socket_path);

    const pipe_fds = try std.posix.pipe();
    const pid = try std.posix.fork();

    if (pid == 0) {
        std.posix.close(pipe_fds[0]);
        var held = InstanceLock.acquire(std.heap.page_allocator, socket_path) catch std.posix.exit(2);
        _ = std.posix.write(pipe_fds[1], &.{1}) catch std.posix.exit(3);
        std.Thread.sleep(300 * std.time.ns_per_ms);
        held.deinit();
        std.posix.close(pipe_fds[1]);
        std.posix.exit(0);
    }

    std.posix.close(pipe_fds[1]);
    defer std.posix.close(pipe_fds[0]);

    var ready: [1]u8 = undefined;
    const bytes_read = try std.posix.read(pipe_fds[0], &ready);
    try std.testing.expectEqual(@as(usize, 1), bytes_read);

    if (InstanceLock.acquire(allocator, socket_path)) |unexpected| {
        var acquired = unexpected;
        acquired.deinit();
        return error.TestUnexpectedResult;
    } else |err| {
        try std.testing.expectEqual(error.AlreadyRunning, err);
    }

    const result = std.posix.waitpid(pid, 0);
    try std.testing.expectEqual(pid, result.pid);
    try std.testing.expect(std.posix.W.IFEXITED(result.status));
    try std.testing.expectEqual(@as(u8, 0), std.posix.W.EXITSTATUS(result.status));
}
