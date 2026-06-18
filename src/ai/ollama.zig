const std = @import("std");

pub const default_host = "127.0.0.1";
pub const default_port: u16 = 11434;
pub const recommended_model = "gemma3:1b";
pub const supported_models = [_][]const u8{recommended_model};
const max_http_response_bytes = 16 * 1024 * 1024;

pub const Status = struct {
    installed: bool,
    daemon_running: bool,
};

pub const StreamSink = struct {
    context: *anyopaque,
    onToken: *const fn (context: *anyopaque, token: []const u8) anyerror!void,
    onDone: ?*const fn (context: *anyopaque, event: StreamEvent) anyerror!void = null,
};

pub const StreamEvent = struct {
    token: ?[]u8 = null,
    done: bool = false,
    total_duration: u64 = 0,
    load_duration: u64 = 0,
    eval_count: u64 = 0,
    eval_duration: u64 = 0,

    pub fn deinit(self: *StreamEvent, allocator: std.mem.Allocator) void {
        if (self.token) |value| allocator.free(value);
        self.* = undefined;
    }
};

pub const BenchmarkResult = struct {
    first_token_ns: u64,
    tokens_per_second_x100: u64,
    peak_ram_bytes: u64,
    total_duration_ns: u64,
    load_duration_ns: u64,
    eval_count: u64,
    eval_duration_ns: u64,
};

pub fn detect(allocator: std.mem.Allocator) !Status {
    return .{
        .installed = isInstalled(allocator),
        .daemon_running = isDaemonRunning(allocator, default_host, default_port),
    };
}

pub fn isInstalled(allocator: std.mem.Allocator) bool {
    const result = std.process.Child.run(.{
        .allocator = allocator,
        .argv = &.{ "ollama", "--version" },
        .max_output_bytes = 4096,
        .expand_arg0 = .expand,
    }) catch return false;
    defer allocator.free(result.stdout);
    defer allocator.free(result.stderr);
    return switch (result.term) {
        .Exited => |code| code == 0,
        else => false,
    };
}

pub fn isDaemonRunning(allocator: std.mem.Allocator, host: []const u8, port: u16) bool {
    return httpGetOk(allocator, host, port, "/api/tags") catch false;
}

pub fn pullModel(allocator: std.mem.Allocator, host: []const u8, port: u16, model: []const u8) !void {
    const payload = try pullPayloadAlloc(allocator, model);
    defer allocator.free(payload);
    var response = try httpRequestAlloc(allocator, host, port, "POST", "/api/pull", payload);
    defer response.deinit(allocator);
    if (response.status < 200 or response.status >= 300) return error.OllamaHttpError;
}

pub fn loadModel(allocator: std.mem.Allocator, host: []const u8, port: u16, model: []const u8) !void {
    const payload = try loadPayloadAlloc(allocator, model);
    defer allocator.free(payload);
    var response = try httpRequestAlloc(allocator, host, port, "POST", "/api/generate", payload);
    defer response.deinit(allocator);
    if (response.status < 200 or response.status >= 300) return error.OllamaHttpError;
}

pub fn unloadModel(allocator: std.mem.Allocator, host: []const u8, port: u16, model: []const u8) !void {
    const payload = try unloadPayloadAlloc(allocator, model);
    defer allocator.free(payload);
    var response = try httpRequestAlloc(allocator, host, port, "POST", "/api/generate", payload);
    defer response.deinit(allocator);
    if (response.status < 200 or response.status >= 300) return error.OllamaHttpError;
}

pub fn generateAlloc(allocator: std.mem.Allocator, host: []const u8, port: u16, model: []const u8, prompt: []const u8) ![]u8 {
    const payload = try generatePayloadAlloc(allocator, model, prompt, false);
    defer allocator.free(payload);
    var response = try httpRequestAlloc(allocator, host, port, "POST", "/api/generate", payload);
    defer response.deinit(allocator);
    if (response.status < 200 or response.status >= 300) return error.OllamaHttpError;
    return parseGenerateResponseAlloc(allocator, response.body);
}

pub fn generateStream(allocator: std.mem.Allocator, host: []const u8, port: u16, model: []const u8, prompt: []const u8, cancel: ?*const std.atomic.Value(bool), sink: StreamSink) !void {
    const payload = try generatePayloadAlloc(allocator, model, prompt, true);
    defer allocator.free(payload);
    const url = try std.fmt.allocPrint(allocator, "http://{s}:{d}/api/generate", .{ host, port });
    defer allocator.free(url);
    const uri = try std.Uri.parse(url);

    var client = std.http.Client{ .allocator = allocator };
    defer client.deinit();
    var request = try client.request(.POST, uri, .{
        .keep_alive = false,
        .headers = .{ .content_type = .{ .override = "application/json" }, .accept_encoding = .omit },
    });
    defer request.deinit();
    request.transfer_encoding = .{ .content_length = payload.len };
    var body = try request.sendBodyUnflushed(&.{});
    try body.writer.writeAll(payload);
    try body.end();
    try request.connection.?.flush();

    var response = try request.receiveHead(&.{});
    const status: u16 = @intFromEnum(response.head.status);
    if (status < 200 or status >= 300) return error.OllamaHttpError;
    var transfer_buffer: [4096]u8 = undefined;
    const reader = response.reader(&transfer_buffer);
    while (true) {
        if (cancel) |value| if (value.load(.seq_cst)) return error.Cancelled;
        const line = reader.takeDelimiter('\n') catch |err| switch (err) {
            error.ReadFailed => return response.bodyErr() orelse err,
            else => return err,
        } orelse break;
        try emitStreamLine(allocator, line, sink);
    }
}

pub fn benchmarkGenerate(allocator: std.mem.Allocator, host: []const u8, port: u16, model: []const u8, prompt: []const u8) !BenchmarkResult {
    const Context = struct {
        start_ns: i128,
        first_token_ns: u64 = 0,
        total_duration_ns: u64 = 0,
        load_duration_ns: u64 = 0,
        eval_count: u64 = 0,
        eval_duration_ns: u64 = 0,

        fn onToken(context: *anyopaque, token: []const u8) !void {
            _ = token;
            const self: *@This() = @ptrCast(@alignCast(context));
            if (self.first_token_ns == 0) self.first_token_ns = @intCast(std.time.nanoTimestamp() - self.start_ns);
        }

        fn onDone(context: *anyopaque, event: StreamEvent) !void {
            const self: *@This() = @ptrCast(@alignCast(context));
            self.total_duration_ns = event.total_duration;
            self.load_duration_ns = event.load_duration;
            self.eval_count = event.eval_count;
            self.eval_duration_ns = event.eval_duration;
        }
    };
    var context = Context{ .start_ns = std.time.nanoTimestamp() };
    try generateStream(allocator, host, port, model, prompt, null, .{
        .context = &context,
        .onToken = Context.onToken,
        .onDone = Context.onDone,
    });
    if (context.eval_count == 0 or context.eval_duration_ns == 0) return error.MissingOllamaMetrics;
    const peak_ram_bytes = runningModelSize(allocator, host, port, model) catch 0;
    return .{
        .first_token_ns = context.first_token_ns,
        .tokens_per_second_x100 = tokensPerSecondX100(context.eval_count, context.eval_duration_ns),
        .peak_ram_bytes = peak_ram_bytes,
        .total_duration_ns = context.total_duration_ns,
        .load_duration_ns = context.load_duration_ns,
        .eval_count = context.eval_count,
        .eval_duration_ns = context.eval_duration_ns,
    };
}

pub fn consumeGenerateStreamLines(allocator: std.mem.Allocator, source: []const u8, cancel: ?*const std.atomic.Value(bool), sink: StreamSink) !void {
    var lines = std.mem.splitScalar(u8, source, '\n');
    while (lines.next()) |line| {
        if (cancel) |value| if (value.load(.seq_cst)) return error.Cancelled;
        try emitStreamLine(allocator, line, sink);
    }
}

pub fn mockModelListener() !std.net.Server {
    const address = try std.net.Address.parseIp(default_host, 0);
    return address.listen(.{ .reuse_address = true });
}

pub fn mockModelPort(listener: *const std.net.Server) u16 {
    return listener.listen_address.getPort();
}

pub fn serveOneMockGenerate(allocator: std.mem.Allocator, listener: *std.net.Server, response_json: []const u8) !void {
    var connection = try listener.accept();
    defer connection.stream.close();
    var request_buffer: [8192]u8 = undefined;
    const request_len = try connection.stream.read(&request_buffer);
    const request = request_buffer[0..request_len];
    const status: []const u8 = if (std.mem.indexOf(u8, request, "POST /api/generate ") != null) "200 OK" else "404 Not Found";
    const body = if (std.mem.startsWith(u8, status, "200")) response_json else "{\"error\":\"not found\"}";
    const response = try std.fmt.allocPrint(
        allocator,
        "HTTP/1.1 {s}\r\nContent-Type: application/json\r\nContent-Length: {d}\r\nConnection: close\r\n\r\n{s}",
        .{ status, body.len, body },
    );
    defer allocator.free(response);
    try connection.stream.writeAll(response);
}

fn httpGetOk(allocator: std.mem.Allocator, host: []const u8, port: u16, path: []const u8) !bool {
    var response = try httpRequestAlloc(allocator, host, port, "GET", path, "");
    defer response.deinit(allocator);
    const status = response.status;
    return status >= 200 and status < 300;
}

const HttpResponse = struct {
    status: u16,
    body: []u8,

    fn deinit(self: *HttpResponse, allocator: std.mem.Allocator) void {
        allocator.free(self.body);
        self.* = undefined;
    }
};

fn httpRequestAlloc(allocator: std.mem.Allocator, host: []const u8, port: u16, method: []const u8, path: []const u8, body: []const u8) !HttpResponse {
    var stream = try std.net.tcpConnectToHost(allocator, host, port);
    defer stream.close();
    const request = try std.fmt.allocPrint(
        allocator,
        "{s} {s} HTTP/1.1\r\nHost: {s}:{d}\r\nContent-Type: application/json\r\nContent-Length: {d}\r\nConnection: close\r\n\r\n{s}",
        .{ method, path, host, port, body.len, body },
    );
    defer allocator.free(request);
    try stream.writeAll(request);

    var raw: std.ArrayList(u8) = .empty;
    defer raw.deinit(allocator);
    while (true) {
        var buffer: [4096]u8 = undefined;
        const read_len = try stream.read(&buffer);
        if (read_len == 0) break;
        if (raw.items.len + read_len > max_http_response_bytes) return error.ResponseTooLarge;
        try raw.appendSlice(allocator, buffer[0..read_len]);
    }
    return parseHttpResponseAlloc(allocator, raw.items);
}

fn parseHttpResponseAlloc(allocator: std.mem.Allocator, response: []const u8) !HttpResponse {
    const status = parseHttpStatus(response) orelse return error.InvalidHttpResponse;
    const body_start = if (std.mem.indexOf(u8, response, "\r\n\r\n")) |index| index + 4 else return error.InvalidHttpResponse;
    return .{
        .status = status,
        .body = try allocator.dupe(u8, response[body_start..]),
    };
}

pub fn parseHttpStatus(response: []const u8) ?u16 {
    const line_end = std.mem.indexOf(u8, response, "\r\n") orelse response.len;
    const line = response[0..line_end];
    if (!std.mem.startsWith(u8, line, "HTTP/")) return null;
    var parts = std.mem.splitScalar(u8, line, ' ');
    _ = parts.next() orelse return null;
    const code_text = parts.next() orelse return null;
    return std.fmt.parseInt(u16, code_text, 10) catch null;
}

pub fn pullPayloadAlloc(allocator: std.mem.Allocator, model: []const u8) ![]u8 {
    const escaped_model = try jsonStringAlloc(allocator, model);
    defer allocator.free(escaped_model);
    return std.fmt.allocPrint(allocator, "{{\"model\":{s},\"stream\":false}}", .{escaped_model});
}

pub fn loadPayloadAlloc(allocator: std.mem.Allocator, model: []const u8) ![]u8 {
    const escaped_model = try jsonStringAlloc(allocator, model);
    defer allocator.free(escaped_model);
    return std.fmt.allocPrint(allocator, "{{\"model\":{s},\"prompt\":\"\",\"stream\":false,\"keep_alive\":-1}}", .{escaped_model});
}

pub fn unloadPayloadAlloc(allocator: std.mem.Allocator, model: []const u8) ![]u8 {
    const escaped_model = try jsonStringAlloc(allocator, model);
    defer allocator.free(escaped_model);
    return std.fmt.allocPrint(allocator, "{{\"model\":{s},\"prompt\":\"\",\"stream\":false,\"keep_alive\":0}}", .{escaped_model});
}

pub fn generatePayloadAlloc(allocator: std.mem.Allocator, model: []const u8, prompt: []const u8, stream: bool) ![]u8 {
    const escaped_model = try jsonStringAlloc(allocator, model);
    defer allocator.free(escaped_model);
    const escaped_prompt = try jsonStringAlloc(allocator, prompt);
    defer allocator.free(escaped_prompt);
    return std.fmt.allocPrint(allocator, "{{\"model\":{s},\"prompt\":{s},\"stream\":{},\"options\":{{\"temperature\":0,\"num_predict\":128}}}}", .{ escaped_model, escaped_prompt, stream });
}

const GenerateResponse = struct {
    response: []const u8 = "",
};

pub fn parseGenerateResponseAlloc(allocator: std.mem.Allocator, source: []const u8) ![]u8 {
    var parsed = try std.json.parseFromSlice(GenerateResponse, allocator, source, .{ .ignore_unknown_fields = true });
    defer parsed.deinit();
    return allocator.dupe(u8, parsed.value.response);
}

const GenerateStreamResponse = struct {
    response: []const u8 = "",
    done: bool = false,
    total_duration: u64 = 0,
    load_duration: u64 = 0,
    eval_count: u64 = 0,
    eval_duration: u64 = 0,
};

pub fn parseGenerateStreamLineAlloc(allocator: std.mem.Allocator, source: []const u8) !StreamEvent {
    const trimmed = std.mem.trim(u8, source, " \t\r\n");
    if (trimmed.len == 0) return .{};
    var parsed = try std.json.parseFromSlice(GenerateStreamResponse, allocator, trimmed, .{ .ignore_unknown_fields = true });
    defer parsed.deinit();
    return .{
        .token = if (parsed.value.response.len == 0) null else try allocator.dupe(u8, parsed.value.response),
        .done = parsed.value.done,
        .total_duration = parsed.value.total_duration,
        .load_duration = parsed.value.load_duration,
        .eval_count = parsed.value.eval_count,
        .eval_duration = parsed.value.eval_duration,
    };
}

fn emitStreamLine(allocator: std.mem.Allocator, line: []const u8, sink: StreamSink) !void {
    var event = try parseGenerateStreamLineAlloc(allocator, line);
    defer event.deinit(allocator);
    if (event.token) |token| try sink.onToken(sink.context, token);
    if (event.done) if (sink.onDone) |onDone| try onDone(sink.context, event);
}

const RunningModelsResponse = struct {
    models: []RunningModel = &.{},
};

const RunningModel = struct {
    name: []const u8 = "",
    model: []const u8 = "",
    size: u64 = 0,
};

pub fn runningModelSize(allocator: std.mem.Allocator, host: []const u8, port: u16, model: []const u8) !u64 {
    var response = try httpRequestAlloc(allocator, host, port, "GET", "/api/ps", "");
    defer response.deinit(allocator);
    if (response.status < 200 or response.status >= 300) return error.OllamaHttpError;
    return parseRunningModelSize(allocator, response.body, model);
}

pub fn parseRunningModelSize(allocator: std.mem.Allocator, source: []const u8, selected_model: []const u8) !u64 {
    var parsed = try std.json.parseFromSlice(RunningModelsResponse, allocator, source, .{ .ignore_unknown_fields = true });
    defer parsed.deinit();
    for (parsed.value.models) |model| {
        if (std.mem.eql(u8, model.model, selected_model) or std.mem.eql(u8, model.name, selected_model)) return model.size;
    }
    return 0;
}

pub fn tokensPerSecondX100(eval_count: u64, eval_duration_ns: u64) u64 {
    if (eval_count == 0 or eval_duration_ns == 0) return 0;
    return @divFloor(eval_count * 100 * std.time.ns_per_s, eval_duration_ns);
}

fn jsonStringAlloc(allocator: std.mem.Allocator, value: []const u8) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    errdefer out.deinit(allocator);
    try out.append(allocator, '"');
    for (value) |byte| {
        switch (byte) {
            '"' => try out.appendSlice(allocator, "\\\""),
            '\\' => try out.appendSlice(allocator, "\\\\"),
            '\n' => try out.appendSlice(allocator, "\\n"),
            '\r' => try out.appendSlice(allocator, "\\r"),
            '\t' => try out.appendSlice(allocator, "\\t"),
            else => try out.append(allocator, byte),
        }
    }
    try out.append(allocator, '"');
    return out.toOwnedSlice(allocator);
}

test "parses http status" {
    try std.testing.expectEqual(@as(?u16, 200), parseHttpStatus("HTTP/1.1 200 OK\r\n"));
    try std.testing.expectEqual(@as(?u16, 404), parseHttpStatus("HTTP/1.1 404 Not Found\r\n"));
    try std.testing.expect(parseHttpStatus("bad") == null);
}

test "parses http response body" {
    var response = try parseHttpResponseAlloc(std.testing.allocator, "HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{}");
    defer response.deinit(std.testing.allocator);
    try std.testing.expectEqual(@as(u16, 200), response.status);
    try std.testing.expectEqualStrings("{}", response.body);
}

test "builds pull payload" {
    const payload = try pullPayloadAlloc(std.testing.allocator, recommended_model);
    defer std.testing.allocator.free(payload);
    try std.testing.expectEqualStrings("{\"model\":\"gemma3:1b\",\"stream\":false}", payload);
}

test "builds generate payload" {
    const payload = try generatePayloadAlloc(std.testing.allocator, "gemma3:1b", "say \"hi\"", false);
    defer std.testing.allocator.free(payload);
    try std.testing.expectEqualStrings("{\"model\":\"gemma3:1b\",\"prompt\":\"say \\\"hi\\\"\",\"stream\":false,\"options\":{\"temperature\":0,\"num_predict\":128}}", payload);
}

test "builds load and unload payloads" {
    const load = try loadPayloadAlloc(std.testing.allocator, recommended_model);
    defer std.testing.allocator.free(load);
    try std.testing.expectEqualStrings("{\"model\":\"gemma3:1b\",\"prompt\":\"\",\"stream\":false,\"keep_alive\":-1}", load);
    const unload = try unloadPayloadAlloc(std.testing.allocator, recommended_model);
    defer std.testing.allocator.free(unload);
    try std.testing.expectEqualStrings("{\"model\":\"gemma3:1b\",\"prompt\":\"\",\"stream\":false,\"keep_alive\":0}", unload);
}

test "parses generate response" {
    const text = try parseGenerateResponseAlloc(std.testing.allocator, "{\"response\":\"ok\",\"done\":true}");
    defer std.testing.allocator.free(text);
    try std.testing.expectEqualStrings("ok", text);
}

test "mock model harness returns deterministic generate response" {
    var listener = try mockModelListener();
    defer listener.deinit();
    const thread = try std.Thread.spawn(.{}, serveOneMockGenerate, .{
        std.testing.allocator,
        &listener,
        "{\"response\":\"mock-ok\",\"done\":true}",
    });
    defer thread.join();

    const text = try generateAlloc(std.testing.allocator, default_host, mockModelPort(&listener), "mock-model", "say ok");
    defer std.testing.allocator.free(text);
    try std.testing.expectEqualStrings("mock-ok", text);
}

test "parses generate stream line" {
    var event = try parseGenerateStreamLineAlloc(std.testing.allocator, "{\"response\":\"hel\",\"done\":false,\"eval_count\":2,\"eval_duration\":1000000000}");
    defer event.deinit(std.testing.allocator);
    try std.testing.expectEqualStrings("hel", event.token.?);
    try std.testing.expect(!event.done);
    try std.testing.expectEqual(@as(u64, 2), event.eval_count);
}

test "consumes stream tokens with cancellation" {
    const Context = struct {
        text: std.ArrayList(u8) = .empty,
        cancel: std.atomic.Value(bool) = std.atomic.Value(bool).init(false),

        fn onToken(context: *anyopaque, token: []const u8) !void {
            const self: *@This() = @ptrCast(@alignCast(context));
            try self.text.appendSlice(std.testing.allocator, token);
            self.cancel.store(true, .seq_cst);
        }
    };
    var context = Context{};
    defer context.text.deinit(std.testing.allocator);
    try std.testing.expectError(error.Cancelled, consumeGenerateStreamLines(
        std.testing.allocator,
        "{\"response\":\"a\",\"done\":false}\n{\"response\":\"b\",\"done\":false}\n",
        &context.cancel,
        .{ .context = &context, .onToken = Context.onToken },
    ));
    try std.testing.expectEqualStrings("a", context.text.items);
}

test "computes benchmark metrics" {
    try std.testing.expectEqual(@as(u64, 250), tokensPerSecondX100(5, 2 * std.time.ns_per_s));
    try std.testing.expectEqual(@as(u64, 0), tokensPerSecondX100(0, 2 * std.time.ns_per_s));
}

test "parses running model size" {
    const size = try parseRunningModelSize(std.testing.allocator, "{\"models\":[{\"name\":\"gemma3:1b\",\"model\":\"gemma3:1b\",\"size\":815000000}]}", "gemma3:1b");
    try std.testing.expectEqual(@as(u64, 815000000), size);
}
