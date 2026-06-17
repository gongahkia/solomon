const std = @import("std");

pub var shutdown_requested = std.atomic.Value(bool).init(false);
pub var reload_requested = std.atomic.Value(bool).init(false);
pub var stack_dump_requested = std.atomic.Value(bool).init(false);

pub fn installShutdownHandlers() void {
    shutdown_requested.store(false, .seq_cst);
    reload_requested.store(false, .seq_cst);
    stack_dump_requested.store(false, .seq_cst);

    const action = std.posix.Sigaction{
        .handler = .{ .handler = handleSignal },
        .mask = std.posix.sigemptyset(),
        .flags = 0,
    };

    std.posix.sigaction(std.posix.SIG.INT, &action, null);
    std.posix.sigaction(std.posix.SIG.TERM, &action, null);
    std.posix.sigaction(std.posix.SIG.USR1, &action, null);
    std.posix.sigaction(std.posix.SIG.USR2, &action, null);
}

fn handleSignal(signal: i32) callconv(.c) void {
    switch (signal) {
        std.posix.SIG.INT, std.posix.SIG.TERM => shutdown_requested.store(true, .seq_cst),
        std.posix.SIG.USR1 => reload_requested.store(true, .seq_cst),
        std.posix.SIG.USR2 => stack_dump_requested.store(true, .seq_cst),
        else => {},
    }
}
