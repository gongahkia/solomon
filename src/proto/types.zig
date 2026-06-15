const std = @import("std");

pub const version: u32 = 1;
pub const max_frame_bytes: u32 = 1024 * 1024;

pub const Shell = enum {
    zsh,
    bash,
    fish,
    nu,
    pwsh,
};

pub const Request = struct {
    v: u32 = version,
    cwd: []const u8,
    exit: i32,
    jobs: u32,
    duration_ms: u64,
    shell: Shell,
    cols: u16,
    rows: u16,
};

pub const Response = struct {
    v: u32 = version,
    prompt: []const u8,
    redraw_token: ?[]const u8 = null,
};

test "request type carries v1 render inputs" {
    const request = Request{
        .cwd = "/tmp",
        .exit = 1,
        .jobs = 2,
        .duration_ms = 300,
        .shell = .zsh,
        .cols = 120,
        .rows = 40,
    };

    try std.testing.expectEqual(@as(u32, 1), request.v);
    try std.testing.expectEqualStrings("/tmp", request.cwd);
    try std.testing.expectEqual(@as(i32, 1), request.exit);
    try std.testing.expectEqual(@as(u32, 2), request.jobs);
    try std.testing.expectEqual(@as(u64, 300), request.duration_ms);
    try std.testing.expectEqual(Shell.zsh, request.shell);
}

test "response type carries prompt and optional redraw token" {
    const response = Response{
        .prompt = "shisa> ",
        .redraw_token = "abc",
    };

    try std.testing.expectEqual(@as(u32, 1), response.v);
    try std.testing.expectEqualStrings("shisa> ", response.prompt);
    try std.testing.expectEqualStrings("abc", response.redraw_token.?);
}
