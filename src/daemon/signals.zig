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

test "term and int request shutdown" {
    shutdown_requested.store(false, .seq_cst);
    handleSignal(std.posix.SIG.TERM);
    try std.testing.expect(shutdown_requested.load(.seq_cst));

    shutdown_requested.store(false, .seq_cst);
    handleSignal(std.posix.SIG.INT);
    try std.testing.expect(shutdown_requested.load(.seq_cst));
}

test "usr1 requests reload" {
    reload_requested.store(false, .seq_cst);
    handleSignal(std.posix.SIG.USR1);
    try std.testing.expect(reload_requested.load(.seq_cst));
}

test "usr2 requests stack dump" {
    stack_dump_requested.store(false, .seq_cst);
    handleSignal(std.posix.SIG.USR2);
    try std.testing.expect(stack_dump_requested.load(.seq_cst));
}
