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

        const file = std.fs.createFileAbsolute(lock_path, .{
            .read = true,
            .truncate = false,
            .lock = .exclusive,
            .lock_nonblocking = true,
            .mode = 0o600,
        }) catch |err| switch (err) {
            error.WouldBlock => return error.AlreadyRunning,
            else => return err,
        };
        errdefer file.close();

        return .{
            .allocator = allocator,
            .file = file,
            .path = lock_path,
        };
    }

    pub fn deinit(self: *InstanceLock) void {
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

test "races concurrent lock contenders to one owner" {
    switch (builtin.os.tag) {
        .linux, .macos => {},
        else => return,
    }

    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-lock-race-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};

    const socket_path = try std.fmt.allocPrint(allocator, "{s}/shisa.sock", .{dir_path});
    defer allocator.free(socket_path);

    const child_count = 8;
    var pids: [child_count]std.posix.pid_t = undefined;
    const start_fds = try std.posix.pipe();
    const result_fds = try std.posix.pipe();
    const release_fds = try std.posix.pipe();

    for (0..child_count) |index| {
        const pid = try std.posix.fork();
        if (pid == 0) {
            std.posix.close(start_fds[1]);
            std.posix.close(result_fds[0]);
            std.posix.close(release_fds[1]);
            var token: [1]u8 = undefined;
            if ((std.posix.read(start_fds[0], &token) catch 0) != 1) std.posix.exit(3);
            var held = InstanceLock.acquire(std.heap.page_allocator, socket_path) catch |err| switch (err) {
                error.AlreadyRunning => {
                    _ = std.posix.write(result_fds[1], &.{'0'}) catch 0;
                    std.posix.exit(0);
                },
                else => {
                    _ = std.posix.write(result_fds[1], &.{'2'}) catch 0;
                    std.posix.exit(2);
                },
            };
            _ = std.posix.write(result_fds[1], &.{'1'}) catch 0;
            _ = std.posix.read(release_fds[0], &token) catch 0;
            held.deinit();
            std.posix.exit(0);
        }
        pids[index] = pid;
    }

    std.posix.close(start_fds[0]);
    std.posix.close(result_fds[1]);
    std.posix.close(release_fds[0]);
    defer std.posix.close(result_fds[0]);
    defer std.posix.close(release_fds[1]);

    for (0..child_count) |_| {
        try std.testing.expectEqual(@as(usize, 1), try std.posix.write(start_fds[1], &.{1}));
    }
    std.posix.close(start_fds[1]);

    var owners: usize = 0;
    var blocked: usize = 0;
    while (owners + blocked < child_count) {
        var result_byte: [1]u8 = undefined;
        const bytes_read = try std.posix.read(result_fds[0], &result_byte);
        try std.testing.expectEqual(@as(usize, 1), bytes_read);
        switch (result_byte[0]) {
            '1' => owners += 1,
            '0' => blocked += 1,
            else => return error.TestUnexpectedResult,
        }
    }
    try std.testing.expectEqual(@as(usize, 1), owners);
    try std.testing.expectEqual(@as(usize, child_count - 1), blocked);

    try std.testing.expectEqual(@as(usize, 1), try std.posix.write(release_fds[1], &.{1}));
    for (pids) |pid| {
        const result = std.posix.waitpid(pid, 0);
        try std.testing.expectEqual(pid, result.pid);
        try std.testing.expect(std.posix.W.IFEXITED(result.status));
        try std.testing.expectEqual(@as(u8, 0), std.posix.W.EXITSTATUS(result.status));
    }
}
