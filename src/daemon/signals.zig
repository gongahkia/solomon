const std = @import("std");
const builtin = @import("builtin");

pub var shutdown_requested = std.atomic.Value(bool).init(false);
pub var reload_requested = std.atomic.Value(bool).init(false);
pub var stack_dump_requested = std.atomic.Value(bool).init(false);

pub fn installShutdownHandlers() void {
    shutdown_requested.store(false, .seq_cst);
    reload_requested.store(false, .seq_cst);
    stack_dump_requested.store(false, .seq_cst);

    if (builtin.os.tag == .windows) {
        std.os.windows.SetConsoleCtrlHandler(handleConsoleControl, true) catch {};
        return;
    }

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

fn handleConsoleControl(ctrl_type: std.os.windows.DWORD) callconv(.winapi) std.os.windows.BOOL {
    switch (ctrl_type) {
        std.os.windows.CTRL_C_EVENT,
        std.os.windows.CTRL_BREAK_EVENT,
        std.os.windows.CTRL_CLOSE_EVENT,
        std.os.windows.CTRL_LOGOFF_EVENT,
        std.os.windows.CTRL_SHUTDOWN_EVENT,
        => {
            shutdown_requested.store(true, .seq_cst);
            return std.os.windows.TRUE;
        },
        else => return std.os.windows.FALSE,
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

test "windows console control requests shutdown" {
    if (builtin.os.tag != .windows) return error.SkipZigTest;

    shutdown_requested.store(false, .seq_cst);
    try std.testing.expectEqual(std.os.windows.TRUE, handleConsoleControl(std.os.windows.CTRL_C_EVENT));
    try std.testing.expect(shutdown_requested.load(.seq_cst));
}
