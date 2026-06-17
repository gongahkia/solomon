const std = @import("std");

pub const version: u32 = 1;
pub const max_frame_bytes: u32 = 1024 * 1024;

pub const Op = enum {
    render,
    render_continue,
    health,
    metrics,
    reload,
    version,
    subscribe,
};

pub const Shell = enum {
    zsh,
    bash,
    fish,
    nu,
    pwsh,
};

pub const ColorCaps = enum {
    truecolor,
    @"256",
    @"16",
    none,
};

pub const GlyphCaps = enum {
    nerdfont,
    unicode,
    ascii,
};

pub const CloudCtxOptions = struct {
    aws: bool = true,
    gcp: bool = true,
    azure: bool = true,
    kubernetes: bool = true,
};

pub const Request = struct {
    v: u32 = version,
    op: Op = .render,
    cwd: []const u8,
    exit: i32,
    jobs: u32,
    duration_ms: u64,
    time: bool = false,
    no_async: bool = false,
    shell: Shell,
    cols: u16,
    rows: u16,
    tty: ?[]const u8 = null,
    color_caps: ColorCaps = .truecolor,
    glyph_caps: GlyphCaps = .unicode,
    user_id: ?u32 = null,
    session: ?[]const u8 = null,
    request_id: []const u8 = "",
    cloud_ctx: CloudCtxOptions = .{},
};

pub const Diagnostic = struct {
    code: []const u8,
    message: []const u8,
};

pub const Response = struct {
    v: u32 = version,
    request_id: []const u8 = "",
    prompt: []const u8,
    redraw_token: ?[]const u8 = null,
    trailer: ?[]const u8 = null,
    diagnostics: []const Diagnostic = &.{},
    elapsed_us: u64 = 0,
};

pub const ErrorCode = enum {
    E_VERSION,
    E_OVERSIZE,
    E_MALFORMED,
    E_NOT_READY,
    E_PLUGIN_TIMEOUT,
    E_CAPABILITY_DENIED,
    E_INTERNAL,
};

pub const Error = struct {
    code: ErrorCode,
    message: []const u8,
    context: ?std.json.Value = null,
};

pub const ErrorEnvelope = struct {
    v: u32 = version,
    request_id: []const u8 = "",
    @"error": Error,
};

test "request type carries v1 render inputs" {
    const request = Request{
        .op = .render,
        .cwd = "/tmp",
        .exit = 1,
        .jobs = 2,
        .duration_ms = 300,
        .time = true,
        .no_async = true,
        .shell = .zsh,
        .cols = 120,
        .rows = 40,
        .tty = "/dev/ttys001",
        .color_caps = .@"256",
        .glyph_caps = .nerdfont,
        .user_id = 501,
        .session = "session-1",
        .request_id = "request-1",
        .cloud_ctx = .{ .azure = false },
    };

    try std.testing.expectEqual(@as(u32, 1), request.v);
    try std.testing.expectEqual(Op.render, request.op);
    try std.testing.expectEqualStrings("/tmp", request.cwd);
    try std.testing.expectEqual(@as(i32, 1), request.exit);
    try std.testing.expectEqual(@as(u32, 2), request.jobs);
    try std.testing.expectEqual(@as(u64, 300), request.duration_ms);
    try std.testing.expect(request.time);
    try std.testing.expect(request.no_async);
    try std.testing.expectEqual(Shell.zsh, request.shell);
    try std.testing.expectEqualStrings("/dev/ttys001", request.tty.?);
    try std.testing.expectEqual(ColorCaps.@"256", request.color_caps);
    try std.testing.expectEqual(GlyphCaps.nerdfont, request.glyph_caps);
    try std.testing.expectEqual(@as(u32, 501), request.user_id.?);
    try std.testing.expectEqualStrings("session-1", request.session.?);
    try std.testing.expectEqualStrings("request-1", request.request_id);
    try std.testing.expect(!request.cloud_ctx.azure);
}

test "response type carries prompt metadata and optional redraw token" {
    const diagnostics = [_]Diagnostic{.{ .code = "slow_module", .message = "git exceeded budget" }};
    const response = Response{
        .request_id = "request-1",
        .prompt = "shisa> ",
        .redraw_token = "abc",
        .trailer = "right prompt",
        .diagnostics = &diagnostics,
        .elapsed_us = 1234,
    };

    try std.testing.expectEqual(@as(u32, 1), response.v);
    try std.testing.expectEqualStrings("request-1", response.request_id);
    try std.testing.expectEqualStrings("shisa> ", response.prompt);
    try std.testing.expectEqualStrings("abc", response.redraw_token.?);
    try std.testing.expectEqualStrings("right prompt", response.trailer.?);
    try std.testing.expectEqualStrings("slow_module", response.diagnostics[0].code);
    try std.testing.expectEqual(@as(u64, 1234), response.elapsed_us);
}

test "error envelope carries explicit code and structured context" {
    const source =
        \\{"v":1,"request_id":"request-1","error":{"code":"E_OVERSIZE","message":"frame too large","context":{"max_frame_bytes":1048576}}}
    ;
    var parsed = try std.json.parseFromSlice(ErrorEnvelope, std.testing.allocator, source, .{ .ignore_unknown_fields = true });
    defer parsed.deinit();

    try std.testing.expectEqual(@as(u32, 1), parsed.value.v);
    try std.testing.expectEqualStrings("request-1", parsed.value.request_id);
    try std.testing.expectEqual(ErrorCode.E_OVERSIZE, parsed.value.@"error".code);
    try std.testing.expectEqualStrings("frame too large", parsed.value.@"error".message);
    const context = parsed.value.@"error".context.?;
    const max_frame_value = switch (context) {
        .object => |object| object.get("max_frame_bytes").?,
        else => return error.ExpectedObject,
    };
    try std.testing.expectEqual(@as(i64, 1048576), max_frame_value.integer);
}
