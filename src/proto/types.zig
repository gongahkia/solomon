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

pub const CwdOptions = struct {
    truncate_to: u8 = 3,
    home_tilde: bool = true,
    max_width: u16 = 0,
};

pub const CloudCtxOptions = struct {
    aws: bool = true,
    gcp: bool = true,
    azure: bool = true,
    kubernetes: bool = true,
};

pub const RiskTierColor = enum {
    fg,
    muted,
    accent,
    success,
    warning,
    danger,
};

pub const RiskTierOptions = struct {
    unknown_bg: RiskTierColor = .muted,
    dev_bg: RiskTierColor = .success,
    staging_bg: RiskTierColor = .warning,
    prod_bg: RiskTierColor = .danger,
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
    rtl: bool = false,
    rtl_reverse: bool = false,
    cwd_options: CwdOptions = .{},
    cloud_ctx: CloudCtxOptions = .{},
    risk_tier: RiskTierOptions = .{},
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
    E_READONLY,
    E_INTERNAL,
};

pub const ErrorContext = struct {
    field: ?[]const u8 = null,
    expected: ?[]const u8 = null,
    highest_supported_version: ?u32 = null,
    max_frame_bytes: ?u32 = null,
    op: ?[]const u8 = null,
    retry_after_ms: ?u32 = null,
    plugin: ?[]const u8 = null,
    timeout_ms: ?u32 = null,
    capability: ?[]const u8 = null,
    detail: ?[]const u8 = null,
};

pub const Error = struct {
    code: ErrorCode,
    message: []const u8,
    context: ErrorContext = .{},
};

pub const ErrorEnvelope = struct {
    v: u32 = version,
    request_id: []const u8 = "",
    @"error": Error,
};

pub fn encodeAlloc(allocator: std.mem.Allocator, value: anytype) ![]u8 {
    var out: std.Io.Writer.Allocating = .init(allocator);
    errdefer out.deinit();
    try std.json.Stringify.value(value, .{ .emit_null_optional_fields = false }, &out.writer);
    return out.toOwnedSlice();
}

pub fn decodeAlloc(comptime T: type, allocator: std.mem.Allocator, source: []const u8) !std.json.Parsed(T) {
    return std.json.parseFromSlice(T, allocator, source, .{ .ignore_unknown_fields = true });
}

pub fn validateRequestPayload(allocator: std.mem.Allocator, source: []const u8) !?ErrorEnvelope {
    var parsed = std.json.parseFromSlice(std.json.Value, allocator, source, .{}) catch {
        return malformedRequest("request", "valid JSON");
    };
    defer parsed.deinit();

    const object = switch (parsed.value) {
        .object => |object| object,
        else => return malformedRequest("request", "JSON object"),
    };

    for (required_request_fields) |field| {
        if (object.get(field) == null) return malformedRequest(field, "required field");
    }

    const raw_version = object.get("v").?;
    const request_version = switch (raw_version) {
        .integer => |value| value,
        else => return malformedRequest("v", "integer"),
    };
    if (request_version != @as(i64, version)) {
        return .{
            .@"error" = .{
                .code = .E_VERSION,
                .message = "unsupported protocol version",
                .context = .{ .field = "v", .highest_supported_version = version },
            },
        };
    }

    return null;
}

const required_request_fields = [_][]const u8{
    "v",
    "op",
    "shell",
    "cwd",
    "exit",
    "jobs",
    "duration_ms",
    "cols",
    "rows",
    "tty",
    "color_caps",
    "glyph_caps",
    "user_id",
    "session",
    "request_id",
};

fn malformedRequest(field: []const u8, expected: []const u8) ErrorEnvelope {
    return .{
        .@"error" = .{
            .code = .E_MALFORMED,
            .message = "malformed request",
            .context = .{ .field = field, .expected = expected },
        },
    };
}

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
        .risk_tier = .{ .prod_bg = .accent },
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
    try std.testing.expectEqual(RiskTierColor.accent, request.risk_tier.prod_bg);
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
    try std.testing.expectEqual(@as(u32, 1048576), parsed.value.@"error".context.max_frame_bytes.?);
}

test "error code enum exposes canonical protocol codes" {
    const codes = [_]ErrorCode{
        .E_VERSION,
        .E_OVERSIZE,
        .E_MALFORMED,
        .E_NOT_READY,
        .E_PLUGIN_TIMEOUT,
        .E_CAPABILITY_DENIED,
        .E_READONLY,
        .E_INTERNAL,
    };
    const names = [_][]const u8{
        "E_VERSION",
        "E_OVERSIZE",
        "E_MALFORMED",
        "E_NOT_READY",
        "E_PLUGIN_TIMEOUT",
        "E_CAPABILITY_DENIED",
        "E_READONLY",
        "E_INTERNAL",
    };
    for (codes, names) |code, name| {
        try std.testing.expectEqualStrings(name, @tagName(code));
    }
}

test "error context carries machine fields for each code" {
    const allocator = std.testing.allocator;
    const envelopes = [_]ErrorEnvelope{
        .{ .@"error" = .{ .code = .E_VERSION, .message = "bad version", .context = .{ .field = "v", .highest_supported_version = 1 } } },
        .{ .@"error" = .{ .code = .E_OVERSIZE, .message = "too large", .context = .{ .max_frame_bytes = max_frame_bytes } } },
        .{ .@"error" = .{ .code = .E_MALFORMED, .message = "bad request", .context = .{ .field = "op", .expected = "render" } } },
        .{ .@"error" = .{ .code = .E_NOT_READY, .message = "pending", .context = .{ .op = "render_continue", .retry_after_ms = 25 } } },
        .{ .@"error" = .{ .code = .E_PLUGIN_TIMEOUT, .message = "timeout", .context = .{ .plugin = "git", .timeout_ms = 2 } } },
        .{ .@"error" = .{ .code = .E_CAPABILITY_DENIED, .message = "denied", .context = .{ .capability = "exec", .op = "render" } } },
        .{ .@"error" = .{ .code = .E_READONLY, .message = "readonly", .context = .{ .op = "reload" } } },
        .{ .@"error" = .{ .code = .E_INTERNAL, .message = "internal", .context = .{ .detail = "cache_state" } } },
    };

    for (envelopes) |envelope| {
        const encoded = try encodeAlloc(allocator, envelope);
        defer allocator.free(encoded);
        var parsed = try decodeAlloc(ErrorEnvelope, allocator, encoded);
        defer parsed.deinit();
        try std.testing.expectEqual(envelope.@"error".code, parsed.value.@"error".code);
        switch (envelope.@"error".code) {
            .E_VERSION => try std.testing.expectEqual(@as(u32, 1), parsed.value.@"error".context.highest_supported_version.?),
            .E_OVERSIZE => try std.testing.expectEqual(max_frame_bytes, parsed.value.@"error".context.max_frame_bytes.?),
            .E_MALFORMED => try std.testing.expectEqualStrings("render", parsed.value.@"error".context.expected.?),
            .E_NOT_READY => try std.testing.expectEqual(@as(u32, 25), parsed.value.@"error".context.retry_after_ms.?),
            .E_PLUGIN_TIMEOUT => try std.testing.expectEqualStrings("git", parsed.value.@"error".context.plugin.?),
            .E_CAPABILITY_DENIED => try std.testing.expectEqualStrings("exec", parsed.value.@"error".context.capability.?),
            .E_READONLY => try std.testing.expectEqualStrings("reload", parsed.value.@"error".context.op.?),
            .E_INTERNAL => try std.testing.expectEqualStrings("cache_state", parsed.value.@"error".context.detail.?),
        }
    }
}

test "json helpers roundtrip request and response" {
    const allocator = std.testing.allocator;
    const request = Request{
        .cwd = "/tmp/project",
        .exit = 0,
        .jobs = 1,
        .duration_ms = 42,
        .shell = .fish,
        .cols = 100,
        .rows = 30,
        .tty = "/dev/ttys002",
        .color_caps = .truecolor,
        .glyph_caps = .ascii,
        .user_id = 501,
        .session = "session-2",
        .request_id = "request-2",
    };

    const request_json = try encodeAlloc(allocator, request);
    defer allocator.free(request_json);
    var parsed_request = try decodeAlloc(Request, allocator, request_json);
    defer parsed_request.deinit();

    try std.testing.expectEqual(Op.render, parsed_request.value.op);
    try std.testing.expectEqual(Shell.fish, parsed_request.value.shell);
    try std.testing.expectEqual(ColorCaps.truecolor, parsed_request.value.color_caps);
    try std.testing.expectEqual(GlyphCaps.ascii, parsed_request.value.glyph_caps);
    try std.testing.expectEqualStrings("request-2", parsed_request.value.request_id);

    const diagnostics = [_]Diagnostic{.{ .code = "async_pending", .message = "git still running" }};
    const response = Response{
        .request_id = "request-2",
        .prompt = "shisa> ",
        .redraw_token = "token-1",
        .diagnostics = &diagnostics,
        .elapsed_us = 321,
    };
    const response_json = try encodeAlloc(allocator, response);
    defer allocator.free(response_json);
    var parsed_response = try decodeAlloc(Response, allocator, response_json);
    defer parsed_response.deinit();

    try std.testing.expectEqualStrings("request-2", parsed_response.value.request_id);
    try std.testing.expectEqualStrings("shisa> ", parsed_response.value.prompt);
    try std.testing.expectEqualStrings("token-1", parsed_response.value.redraw_token.?);
    try std.testing.expectEqualStrings("async_pending", parsed_response.value.diagnostics[0].code);
    try std.testing.expectEqual(@as(u64, 321), parsed_response.value.elapsed_us);
}

test "decode ignores unknown fields for forward compatibility" {
    const allocator = std.testing.allocator;
    var request = try decodeAlloc(Request, allocator,
        \\{"v":1,"op":"render","shell":"zsh","cwd":"/tmp","exit":0,"jobs":0,"duration_ms":1,"cols":80,"rows":24,"future_request_field":true}
    );
    defer request.deinit();
    try std.testing.expectEqual(Shell.zsh, request.value.shell);
    try std.testing.expectEqualStrings("/tmp", request.value.cwd);

    var response = try decodeAlloc(Response, allocator,
        \\{"v":1,"request_id":"r1","prompt":"shisa> ","future_response_field":{"nested":1}}
    );
    defer response.deinit();
    try std.testing.expectEqualStrings("r1", response.value.request_id);
    try std.testing.expectEqualStrings("shisa> ", response.value.prompt);

    var envelope = try decodeAlloc(ErrorEnvelope, allocator,
        \\{"v":1,"request_id":"r1","error":{"code":"E_VERSION","message":"bad version","context":{},"future_error_field":"ignored"},"future_envelope_field":1}
    );
    defer envelope.deinit();
    try std.testing.expectEqual(ErrorCode.E_VERSION, envelope.value.@"error".code);
    try std.testing.expectEqualStrings("bad version", envelope.value.@"error".message);
}

test "validates required request fields with structured errors" {
    const allocator = std.testing.allocator;
    const missing = (try validateRequestPayload(allocator,
        \\{"v":1,"op":"render","shell":"zsh","exit":0,"jobs":0,"duration_ms":1,"cols":80,"rows":24,"tty":"/dev/ttys001","color_caps":"truecolor","glyph_caps":"unicode","user_id":501,"session":"s1","request_id":"r1"}
    )).?;
    try std.testing.expectEqual(ErrorCode.E_MALFORMED, missing.@"error".code);
    try std.testing.expectEqualStrings("cwd", missing.@"error".context.field.?);
    try std.testing.expectEqualStrings("required field", missing.@"error".context.expected.?);

    const bad_version = (try validateRequestPayload(allocator,
        \\{"v":2,"op":"render","shell":"zsh","cwd":"/tmp","exit":0,"jobs":0,"duration_ms":1,"cols":80,"rows":24,"tty":"/dev/ttys001","color_caps":"truecolor","glyph_caps":"unicode","user_id":501,"session":"s1","request_id":"r1"}
    )).?;
    try std.testing.expectEqual(ErrorCode.E_VERSION, bad_version.@"error".code);
    try std.testing.expectEqual(@as(u32, version), bad_version.@"error".context.highest_supported_version.?);

    const valid = try validateRequestPayload(allocator,
        \\{"v":1,"op":"render","shell":"zsh","cwd":"/tmp","exit":0,"jobs":0,"duration_ms":1,"cols":80,"rows":24,"tty":"/dev/ttys001","color_caps":"truecolor","glyph_caps":"unicode","user_id":501,"session":"s1","request_id":"r1"}
    );
    try std.testing.expect(valid == null);
}

test "fuzz request decoder invariants" {
    return std.testing.fuzz({}, fuzzRequestDecode, .{
        .corpus = &.{
            "",
            "{}",
            "{\"v\":\"1\"}",
            "{\"v\":2}",
            \\{"v":1,"op":"render","shell":"zsh","cwd":"/tmp","exit":0,"jobs":0,"duration_ms":1,"cols":80,"rows":24,"tty":"/dev/tty","color_caps":"truecolor","glyph_caps":"unicode","user_id":501,"session":"s1","request_id":"r1"}
        },
    });
}

fn fuzzRequestDecode(_: void, input: []const u8) !void {
    if (input.len > 8192) return;
    const validation = validateRequestPayload(std.testing.allocator, input) catch return;
    if (validation) |envelope| {
        try std.testing.expect(envelope.@"error".code == .E_MALFORMED or envelope.@"error".code == .E_VERSION);
        return;
    }
    var parsed = decodeAlloc(Request, std.testing.allocator, input) catch return;
    defer parsed.deinit();
    try std.testing.expectEqual(version, parsed.value.v);
}

test "snapshots every op and protocol shape" {
    const allocator = std.testing.allocator;
    const ops = [_]Op{ .render, .render_continue, .health, .metrics, .reload, .version, .subscribe };

    for (ops) |op| {
        const op_name = @tagName(op);
        const request_id = try std.fmt.allocPrint(allocator, "{s}-request", .{op_name});
        defer allocator.free(request_id);

        const request = Request{
            .op = op,
            .cwd = "/tmp",
            .exit = 0,
            .jobs = 0,
            .duration_ms = 1,
            .shell = .zsh,
            .cols = 80,
            .rows = 24,
            .tty = "/dev/ttys001",
            .color_caps = .truecolor,
            .glyph_caps = .unicode,
            .user_id = 501,
            .session = "session-1",
            .request_id = request_id,
        };
        const request_json = try encodeAlloc(allocator, request);
        defer allocator.free(request_json);
        const expected_request = try std.fmt.allocPrint(allocator, "{{\"v\":1,\"op\":\"{s}\",\"cwd\":\"/tmp\",\"exit\":0,\"jobs\":0,\"duration_ms\":1,\"time\":false,\"no_async\":false,\"shell\":\"zsh\",\"cols\":80,\"rows\":24,\"tty\":\"/dev/ttys001\",\"color_caps\":\"truecolor\",\"glyph_caps\":\"unicode\",\"user_id\":501,\"session\":\"session-1\",\"request_id\":\"{s}\",\"rtl\":false,\"rtl_reverse\":false,\"cwd_options\":{{\"truncate_to\":3,\"home_tilde\":true,\"max_width\":0}},\"cloud_ctx\":{{\"aws\":true,\"gcp\":true,\"azure\":true,\"kubernetes\":true}},\"risk_tier\":{{\"unknown_bg\":\"muted\",\"dev_bg\":\"success\",\"staging_bg\":\"warning\",\"prod_bg\":\"danger\"}}}}", .{ op_name, request_id });
        defer allocator.free(expected_request);
        try std.testing.expectEqualStrings(expected_request, request_json);

        const diagnostics = [_]Diagnostic{.{ .code = "snapshot", .message = "ok" }};
        const response = Response{
            .request_id = request_id,
            .prompt = "shisa> ",
            .redraw_token = "token",
            .trailer = "right",
            .diagnostics = &diagnostics,
            .elapsed_us = 7,
        };
        const response_json = try encodeAlloc(allocator, response);
        defer allocator.free(response_json);
        const expected_response = try std.fmt.allocPrint(allocator, "{{\"v\":1,\"request_id\":\"{s}\",\"prompt\":\"shisa> \",\"redraw_token\":\"token\",\"trailer\":\"right\",\"diagnostics\":[{{\"code\":\"snapshot\",\"message\":\"ok\"}}],\"elapsed_us\":7}}", .{request_id});
        defer allocator.free(expected_response);
        try std.testing.expectEqualStrings(expected_response, response_json);

        const envelope = ErrorEnvelope{
            .request_id = request_id,
            .@"error" = .{
                .code = .E_INTERNAL,
                .message = "snapshot error",
                .context = .{ .field = "op" },
            },
        };
        const error_json = try encodeAlloc(allocator, envelope);
        defer allocator.free(error_json);
        const expected_error = try std.fmt.allocPrint(allocator, "{{\"v\":1,\"request_id\":\"{s}\",\"error\":{{\"code\":\"E_INTERNAL\",\"message\":\"snapshot error\",\"context\":{{\"field\":\"op\"}}}}}}", .{request_id});
        defer allocator.free(expected_error);
        try std.testing.expectEqualStrings(expected_error, error_json);
    }
}
