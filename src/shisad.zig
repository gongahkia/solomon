const std = @import("std");
const builtin = @import("builtin");
const cli = @import("daemon/cli.zig");
const lock = @import("daemon/lock.zig");
const paths = @import("daemon/paths.zig");
const server = @import("daemon/server.zig");
const signals = @import("daemon/signals.zig");

const version = "0.1.0-dev";

pub fn main() !void {
    var gpa_impl = std.heap.GeneralPurposeAllocator(.{}){};
    defer _ = gpa_impl.deinit();
    const allocator = gpa_impl.allocator();

    const args = try std.process.argsAlloc(allocator);
    defer std.process.argsFree(allocator, args);

    const config = cli.parse(args[1..]) catch |err| {
        try std.fs.File.stderr().writeAll("shisad: invalid arguments; run `shisad --help`\n");
        return err;
    };

    if (config.help) {
        try std.fs.File.stdout().writeAll(help_text);
        return;
    }

    if (config.version) {
        try std.fs.File.stdout().writeAll("shisad " ++ version ++ "\n");
        return;
    }

    const socket_path = if (config.socket_path) |path| path else try paths.defaultSocketPath(allocator);
    defer if (config.socket_path == null) allocator.free(socket_path);

    var instance_lock = lock.InstanceLock.acquire(allocator, socket_path) catch |err| switch (err) {
        error.AlreadyRunning => {
            try std.fs.File.stderr().writeAll("shisad: another daemon already owns the socket lock\n");
            return err;
        },
        else => return err,
    };
    defer instance_lock.deinit();

    if (config.daemonize) {
        try daemonize();
    }

    signals.installShutdownHandlers();
    try run(config, socket_path);
}

fn run(config: cli.Config, socket_path: []const u8) !void {
    var daemon_server = try server.Server.init(socket_path);
    defer daemon_server.deinit();

    if (!config.daemonize) {
        try std.fs.File.stdout().writeAll("shisad: listening\n");
    }

    try daemon_server.serve(&signals.shutdown_requested);
}

fn daemonize() !void {
    switch (builtin.os.tag) {
        .linux, .macos => {},
        else => return error.UnsupportedDaemonizePlatform,
    }

    const first_child = try std.posix.fork();
    if (first_child != 0) std.posix.exit(0);

    _ = try std.posix.setsid();

    const second_child = try std.posix.fork();
    if (second_child != 0) std.posix.exit(0);

    try std.posix.chdir("/");

    const null_fd = try std.posix.open("/dev/null", .{ .ACCMODE = .RDWR, .CLOEXEC = true }, 0);
    defer std.posix.close(null_fd);

    try std.posix.dup2(null_fd, std.posix.STDIN_FILENO);
    try std.posix.dup2(null_fd, std.posix.STDOUT_FILENO);
    try std.posix.dup2(null_fd, std.posix.STDERR_FILENO);
}

const help_text =
    \\usage: shisad [options]
    \\
    \\options:
    \\  -h, --help            print help
    \\      --version         print version
    \\      --foreground      do not daemonize
    \\      --daemonize       daemonize with fork+setsid (default)
    \\      --socket <path>   override daemon socket path
    \\      --log <path>      override daemon log path
    \\
;
