const std = @import("std");

pub var shutdown_requested = std.atomic.Value(bool).init(false);

pub fn installShutdownHandlers() void {
    shutdown_requested.store(false, .seq_cst);

    const action = std.posix.Sigaction{
        .handler = .{ .handler = handleSignal },
        .mask = std.posix.sigemptyset(),
        .flags = 0,
    };

    std.posix.sigaction(std.posix.SIG.INT, &action, null);
    std.posix.sigaction(std.posix.SIG.TERM, &action, null);
}

fn handleSignal(_: i32) callconv(.c) void {
    shutdown_requested.store(true, .seq_cst);
}
