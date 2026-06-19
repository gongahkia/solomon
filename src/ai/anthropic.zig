const std = @import("std");

pub const provider_id = "anthropic";
pub const default_model = "claude-fable-5";
pub const default_base_url = "https://api.anthropic.com/v1/messages";
pub const api_version = "2023-06-01";
const max_http_response_bytes = 16 * 1024 * 1024;
const default_max_tokens: u32 = 512;

pub const GenerateConfig = struct {
    api_key: []const u8,
    model: []const u8 = default_model,
    base_url: []const u8 = default_base_url,
    input: []const u8,
};

pub fn isConfiguredEnv(allocator: std.mem.Allocator) bool {
    const key = std.process.getEnvVarOwned(allocator, "ANTHROPIC_API_KEY") catch return false;
    defer allocator.free(key);
    return std.mem.trim(u8, key, " \t\r\n").len != 0;
}

pub fn apiKeyFromEnvAlloc(allocator: std.mem.Allocator) ![]u8 {
    const key = std.process.getEnvVarOwned(allocator, "ANTHROPIC_API_KEY") catch |err| switch (err) {
        error.EnvironmentVariableNotFound => return error.AnthropicKeyMissing,
        else => return err,
    };
    errdefer allocator.free(key);
    if (std.mem.trim(u8, key, " \t\r\n").len == 0) return error.AnthropicKeyMissing;
    return key;
}

pub fn baseUrlFromEnvAlloc(allocator: std.mem.Allocator) ![]u8 {
    const url = std.process.getEnvVarOwned(allocator, "SHISA_ANTHROPIC_BASE_URL") catch |err| switch (err) {
        error.EnvironmentVariableNotFound => return allocator.dupe(u8, default_base_url),
        else => return err,
    };
    errdefer allocator.free(url);
    if (std.mem.trim(u8, url, " \t\r\n").len == 0) return error.AnthropicBaseUrlMissing;
    return url;
}

pub fn generateAlloc(allocator: std.mem.Allocator, config: GenerateConfig) ![]u8 {
    const payload = try messagesPayloadAlloc(allocator, config.model, config.input);
    defer allocator.free(payload);

    var client = std.http.Client{ .allocator = allocator };
    defer client.deinit();
    var response_body = std.Io.Writer.Allocating.init(allocator);
    defer response_body.deinit();
    const result = try client.fetch(.{
        .location = .{ .url = config.base_url },
        .method = .POST,
        .payload = payload,
        .headers = .{ .content_type = .{ .override = "application/json" }, .accept_encoding = .omit },
        .privileged_headers = &.{
            .{ .name = "x-api-key", .value = config.api_key },
            .{ .name = "anthropic-version", .value = api_version },
        },
        .response_writer = &response_body.writer,
        .keep_alive = false,
    });
    const status: u16 = @intFromEnum(result.status);
    if (status < 200 or status >= 300) return error.AnthropicHttpError;
    if (response_body.written().len > max_http_response_bytes) return error.ResponseTooLarge;
    return parseMessagesTextAlloc(allocator, response_body.written());
}

pub fn messagesPayloadAlloc(allocator: std.mem.Allocator, model: []const u8, input: []const u8) ![]u8 {
    const escaped_model = try jsonStringAlloc(allocator, model);
    defer allocator.free(escaped_model);
    const escaped_input = try jsonStringAlloc(allocator, input);
    defer allocator.free(escaped_input);
    return std.fmt.allocPrint(
        allocator,
        "{{\"model\":{s},\"max_tokens\":{d},\"messages\":[{{\"role\":\"user\",\"content\":{s}}}]}}",
        .{ escaped_model, default_max_tokens, escaped_input },
    );
}

const MessagesResponse = struct {
    content: []ContentItem = &.{},
};

const ContentItem = struct {
    type: []const u8 = "",
    text: []const u8 = "",
};

pub fn parseMessagesTextAlloc(allocator: std.mem.Allocator, source: []const u8) ![]u8 {
    var parsed = try std.json.parseFromSlice(MessagesResponse, allocator, source, .{ .ignore_unknown_fields = true });
    defer parsed.deinit();

    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);
    for (parsed.value.content) |content| {
        if (!std.mem.eql(u8, content.type, "text")) continue;
        try out.appendSlice(allocator, content.text);
    }
    if (out.items.len == 0) return error.EmptyAnthropicResponse;
    return out.toOwnedSlice(allocator);
}

pub fn mockMessagesListener() !std.net.Server {
    const address = try std.net.Address.parseIp("127.0.0.1", 0);
    return address.listen(.{ .reuse_address = true });
}

pub fn mockMessagesPort(listener: *const std.net.Server) u16 {
    return listener.listen_address.getPort();
}

pub fn serveOneMockMessages(allocator: std.mem.Allocator, listener: *std.net.Server, response_json: []const u8) !void {
    var connection = try listener.accept();
    defer connection.stream.close();
    var request_buffer: [8192]u8 = undefined;
    const request_len = try connection.stream.read(&request_buffer);
    const request = request_buffer[0..request_len];
    const ok_path = std.mem.indexOf(u8, request, "POST /v1/messages ") != null;
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

test "builds messages payload" {
    const payload = try messagesPayloadAlloc(std.testing.allocator, default_model, "say \"ok\"");
    defer std.testing.allocator.free(payload);
    try std.testing.expectEqualStrings("{\"model\":\"claude-fable-5\",\"max_tokens\":512,\"messages\":[{\"role\":\"user\",\"content\":\"say \\\"ok\\\"\"}]}", payload);
}

test "parses messages output text" {
    const text = try parseMessagesTextAlloc(
        std.testing.allocator,
        "{\"content\":[{\"type\":\"text\",\"text\":\"ok\"}]}",
    );
    defer std.testing.allocator.free(text);
    try std.testing.expectEqualStrings("ok", text);
}

test "empty messages output errors" {
    try std.testing.expectError(error.EmptyAnthropicResponse, parseMessagesTextAlloc(std.testing.allocator, "{\"content\":[]}"));
}

test "mock messages harness returns deterministic text" {
    var listener = try mockMessagesListener();
    defer listener.deinit();
    const thread = try std.Thread.spawn(.{}, serveOneMockMessages, .{
        std.testing.allocator,
        &listener,
        "{\"content\":[{\"type\":\"text\",\"text\":\"mock-ok\"}]}",
    });
    defer thread.join();

    const base_url = try std.fmt.allocPrint(std.testing.allocator, "http://127.0.0.1:{d}/v1/messages", .{mockMessagesPort(&listener)});
    defer std.testing.allocator.free(base_url);
    const text = try generateAlloc(std.testing.allocator, .{
        .api_key = "test-key",
        .model = "claude-test",
        .base_url = base_url,
        .input = "say ok",
    });
    defer std.testing.allocator.free(text);
    try std.testing.expectEqualStrings("mock-ok", text);
}
