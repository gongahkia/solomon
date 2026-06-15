const std = @import("std");

pub const Server = struct {
    socket_path: []const u8,
    listener: std.net.Server,

    pub fn init(socket_path: []const u8) !Server {
        if (std.fs.path.dirname(socket_path)) |parent| {
            try std.fs.cwd().makePath(parent);
        }

        std.fs.deleteFileAbsolute(socket_path) catch |err| switch (err) {
            error.FileNotFound => {},
            else => return err,
        };

        const address = try std.net.Address.initUnix(socket_path);
        const listener = try address.listen(.{
            .reuse_address = false,
            .force_nonblocking = false,
            .kernel_backlog = 128,
        });

        return .{
            .socket_path = socket_path,
            .listener = listener,
        };
    }

    pub fn deinit(self: *Server) void {
        self.listener.deinit();
        std.fs.deleteFileAbsolute(self.socket_path) catch {};
        self.* = undefined;
    }

    pub fn serve(self: *Server, shutdown_requested: *const std.atomic.Value(bool)) !void {
        while (!shutdown_requested.load(.seq_cst)) {
            var poll_fds = [_]std.posix.pollfd{.{
                .fd = self.listener.stream.handle,
                .events = std.posix.POLL.IN,
                .revents = 0,
            }};

            const ready = try std.posix.poll(&poll_fds, 100);
            if (ready == 0) continue;

            if ((poll_fds[0].revents & std.posix.POLL.IN) != 0) {
                try self.acceptOne();
            }
        }
    }

    pub fn acceptOne(self: *Server) !void {
        const connection = try self.listener.accept();
        try handleConnection(connection);
    }
};

fn handleConnection(connection: std.net.Server.Connection) !void {
    defer connection.stream.close();

    var buffer: [4096]u8 = undefined;
    _ = try std.posix.read(connection.stream.handle, &buffer);
    try writeAll(connection.stream.handle, "ok\n");
}

fn writeAll(fd: std.posix.fd_t, bytes: []const u8) !void {
    var remaining = bytes;
    while (remaining.len > 0) {
        const written = try std.posix.write(fd, remaining);
        remaining = remaining[written..];
    }
}

fn acceptOneThread(server: *Server) !void {
    try server.acceptOne();
}

test "accepts one unix socket connection" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-server-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};

    const socket_path = try std.fmt.allocPrint(allocator, "{s}/shisa.sock", .{dir_path});
    defer allocator.free(socket_path);

    var server = try Server.init(socket_path);
    defer server.deinit();

    const thread = try std.Thread.spawn(.{}, acceptOneThread, .{&server});

    var client = try std.net.connectUnixSocket(socket_path);
    defer client.close();
    _ = try std.posix.write(client.handle, "ping");

    var response: [16]u8 = undefined;
    const n = try std.posix.read(client.handle, &response);
    try std.testing.expectEqualStrings("ok\n", response[0..n]);

    thread.join();
}
