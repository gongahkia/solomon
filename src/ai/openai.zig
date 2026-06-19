const std = @import("std");

pub const provider_id = "openai";
pub const default_model = "gpt-5.5";
pub const default_base_url = "https://api.openai.com/v1/responses";
const max_http_response_bytes = 16 * 1024 * 1024;

pub const GenerateConfig = struct {
    api_key: []const u8,
    model: []const u8 = default_model,
    base_url: []const u8 = default_base_url,
    input: []const u8,
};

pub fn isConfiguredEnv(allocator: std.mem.Allocator) bool {
    const key = std.process.getEnvVarOwned(allocator, "OPENAI_API_KEY") catch return false;
    defer allocator.free(key);
    return std.mem.trim(u8, key, " \t\r\n").len != 0;
}

pub fn apiKeyFromEnvAlloc(allocator: std.mem.Allocator) ![]u8 {
    const key = std.process.getEnvVarOwned(allocator, "OPENAI_API_KEY") catch |err| switch (err) {
        error.EnvironmentVariableNotFound => return error.OpenAIKeyMissing,
        else => return err,
    };
    errdefer allocator.free(key);
    if (std.mem.trim(u8, key, " \t\r\n").len == 0) return error.OpenAIKeyMissing;
    return key;
}

pub fn baseUrlFromEnvAlloc(allocator: std.mem.Allocator) ![]u8 {
    const url = std.process.getEnvVarOwned(allocator, "SHISA_OPENAI_BASE_URL") catch |err| switch (err) {
        error.EnvironmentVariableNotFound => return allocator.dupe(u8, default_base_url),
        else => return err,
    };
    errdefer allocator.free(url);
    if (std.mem.trim(u8, url, " \t\r\n").len == 0) return error.OpenAIBaseUrlMissing;
    return url;
}

pub fn generateAlloc(allocator: std.mem.Allocator, config: GenerateConfig) ![]u8 {
    const payload = try responsesPayloadAlloc(allocator, config.model, config.input);
    defer allocator.free(payload);
    const auth = try std.fmt.allocPrint(allocator, "Bearer {s}", .{config.api_key});
    defer allocator.free(auth);

    var client = std.http.Client{ .allocator = allocator };
    defer client.deinit();
    var response_body = std.Io.Writer.Allocating.init(allocator);
    defer response_body.deinit();
    const result = try client.fetch(.{
        .location = .{ .url = config.base_url },
        .method = .POST,
        .payload = payload,
        .headers = .{ .content_type = .{ .override = "application/json" }, .accept_encoding = .omit },
        .privileged_headers = &.{.{ .name = "Authorization", .value = auth }},
        .response_writer = &response_body.writer,
        .keep_alive = false,
    });
    const status: u16 = @intFromEnum(result.status);
    if (status < 200 or status >= 300) return error.OpenAIHttpError;
    if (response_body.written().len > max_http_response_bytes) return error.ResponseTooLarge;
    return parseResponsesTextAlloc(allocator, response_body.written());
}

pub fn responsesPayloadAlloc(allocator: std.mem.Allocator, model: []const u8, input: []const u8) ![]u8 {
    const escaped_model = try jsonStringAlloc(allocator, model);
    defer allocator.free(escaped_model);
    const escaped_input = try jsonStringAlloc(allocator, input);
    defer allocator.free(escaped_input);
    return std.fmt.allocPrint(allocator, "{{\"model\":{s},\"input\":{s},\"store\":false}}", .{ escaped_model, escaped_input });
}

const ResponsesResponse = struct {
    output: []OutputItem = &.{},
};

const OutputItem = struct {
    type: []const u8 = "",
    content: []ContentItem = &.{},
};

const ContentItem = struct {
    type: []const u8 = "",
    text: []const u8 = "",
};

pub fn parseResponsesTextAlloc(allocator: std.mem.Allocator, source: []const u8) ![]u8 {
    var parsed = try std.json.parseFromSlice(ResponsesResponse, allocator, source, .{ .ignore_unknown_fields = true });
    defer parsed.deinit();

    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);
    for (parsed.value.output) |item| {
        if (!std.mem.eql(u8, item.type, "message")) continue;
        for (item.content) |content| {
            if (!std.mem.eql(u8, content.type, "output_text")) continue;
            try out.appendSlice(allocator, content.text);
        }
    }
    if (out.items.len == 0) return error.EmptyOpenAIResponse;
    return out.toOwnedSlice(allocator);
}

pub fn mockResponsesListener() !std.net.Server {
    const address = try std.net.Address.parseIp("127.0.0.1", 0);
    return address.listen(.{ .reuse_address = true });
}

pub fn mockResponsesPort(listener: *const std.net.Server) u16 {
    return listener.listen_address.getPort();
}

pub fn serveOneMockResponses(allocator: std.mem.Allocator, listener: *std.net.Server, response_json: []const u8) !void {
    var connection = try listener.accept();
    defer connection.stream.close();
    var request_buffer: [8192]u8 = undefined;
    const request_len = try connection.stream.read(&request_buffer);
    const request = request_buffer[0..request_len];
    const ok_path = std.mem.indexOf(u8, request, "POST /v1/responses ") != null;
    const body = if (ok_path) response_json else "{\"error\":\"not found\"}";
    const status: []const u8 = if (ok_path) "200 OK" else "404 Not Found";
    const response = try std.fmt.allocPrint(
        allocator,
        "HTTP/1.1 {s}\r\nContent-Type: application/json\r\nContent-Length: {d}\r\nConnection: close\r\n\r\n{s}",
        .{ status, body.len, body },
    );
    defer allocator.free(response);
    try connection.stream.writeAll(response);
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

test "builds responses payload" {
    const payload = try responsesPayloadAlloc(std.testing.allocator, default_model, "say \"ok\"");
    defer std.testing.allocator.free(payload);
    try std.testing.expectEqualStrings("{\"model\":\"gpt-5.5\",\"input\":\"say \\\"ok\\\"\",\"store\":false}", payload);
}

test "parses responses output text" {
    const text = try parseResponsesTextAlloc(
        std.testing.allocator,
        "{\"output\":[{\"type\":\"message\",\"content\":[{\"type\":\"output_text\",\"text\":\"ok\"}]}]}",
    );
    defer std.testing.allocator.free(text);
    try std.testing.expectEqualStrings("ok", text);
}

test "empty responses output errors" {
    try std.testing.expectError(error.EmptyOpenAIResponse, parseResponsesTextAlloc(std.testing.allocator, "{\"output\":[]}"));
}

test "mock responses harness returns deterministic text" {
    var listener = try mockResponsesListener();
    defer listener.deinit();
    const thread = try std.Thread.spawn(.{}, serveOneMockResponses, .{
        std.testing.allocator,
        &listener,
        "{\"output\":[{\"type\":\"message\",\"content\":[{\"type\":\"output_text\",\"text\":\"mock-ok\"}]}]}",
    });
    defer thread.join();

    const base_url = try std.fmt.allocPrint(std.testing.allocator, "http://127.0.0.1:{d}/v1/responses", .{mockResponsesPort(&listener)});
    defer std.testing.allocator.free(base_url);
    const text = try generateAlloc(std.testing.allocator, .{
        .api_key = "test-key",
        .model = "gpt-test",
        .base_url = base_url,
        .input = "say ok",
    });
    defer std.testing.allocator.free(text);
    try std.testing.expectEqualStrings("mock-ok", text);
}
