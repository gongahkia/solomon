const std = @import("std");

pub const provider_id = "gemini";
pub const default_model = "gemini-3.5-flash";
pub const default_base_url = "https://generativelanguage.googleapis.com/v1beta";
const max_http_response_bytes = 16 * 1024 * 1024;

pub const GenerateConfig = struct {
    api_key: []const u8,
    model: []const u8 = default_model,
    base_url: []const u8 = default_base_url,
    input: []const u8,
};

pub fn isConfiguredEnv(allocator: std.mem.Allocator) bool {
    const key = std.process.getEnvVarOwned(allocator, "GEMINI_API_KEY") catch return false;
    defer allocator.free(key);
    return std.mem.trim(u8, key, " \t\r\n").len != 0;
}

pub fn apiKeyFromEnvAlloc(allocator: std.mem.Allocator) ![]u8 {
    const key = std.process.getEnvVarOwned(allocator, "GEMINI_API_KEY") catch |err| switch (err) {
        error.EnvironmentVariableNotFound => return error.GeminiKeyMissing,
        else => return err,
    };
    errdefer allocator.free(key);
    if (std.mem.trim(u8, key, " \t\r\n").len == 0) return error.GeminiKeyMissing;
    return key;
}

pub fn baseUrlFromEnvAlloc(allocator: std.mem.Allocator) ![]u8 {
    const url = std.process.getEnvVarOwned(allocator, "SHISA_GEMINI_BASE_URL") catch |err| switch (err) {
        error.EnvironmentVariableNotFound => return allocator.dupe(u8, default_base_url),
        else => return err,
    };
    errdefer allocator.free(url);
    if (std.mem.trim(u8, url, " \t\r\n").len == 0) return error.GeminiBaseUrlMissing;
    return url;
}

pub fn generateAlloc(allocator: std.mem.Allocator, config: GenerateConfig) ![]u8 {
    const payload = try generateContentPayloadAlloc(allocator, config.input);
    defer allocator.free(payload);
    const endpoint = try generateContentUrlAlloc(allocator, config.base_url, config.model, config.api_key);
    defer allocator.free(endpoint);

    var client = std.http.Client{ .allocator = allocator };
    defer client.deinit();
    var response_body = std.Io.Writer.Allocating.init(allocator);
    defer response_body.deinit();
    const result = try client.fetch(.{
        .location = .{ .url = endpoint },
        .method = .POST,
        .payload = payload,
        .headers = .{ .content_type = .{ .override = "application/json" }, .accept_encoding = .omit },
        .response_writer = &response_body.writer,
        .keep_alive = false,
    });
    const status: u16 = @intFromEnum(result.status);
    if (status < 200 or status >= 300) return error.GeminiHttpError;
    if (response_body.written().len > max_http_response_bytes) return error.ResponseTooLarge;
    return parseGenerateContentTextAlloc(allocator, response_body.written());
}

pub fn generateContentPayloadAlloc(allocator: std.mem.Allocator, input: []const u8) ![]u8 {
    const escaped_input = try jsonStringAlloc(allocator, input);
    defer allocator.free(escaped_input);
    return std.fmt.allocPrint(
        allocator,
        "{{\"contents\":[{{\"role\":\"user\",\"parts\":[{{\"text\":{s}}}]}}],\"store\":false}}",
        .{escaped_input},
    );
}

pub fn generateContentUrlAlloc(allocator: std.mem.Allocator, base_url: []const u8, model: []const u8, api_key: []const u8) ![]u8 {
    const trimmed_base = std.mem.trimRight(u8, base_url, "/");
    const model_path = try modelPathAlloc(allocator, model);
    defer allocator.free(model_path);
    const escaped_key = try urlQueryStringAlloc(allocator, api_key);
    defer allocator.free(escaped_key);
    return std.fmt.allocPrint(allocator, "{s}/{s}:generateContent?key={s}", .{ trimmed_base, model_path, escaped_key });
}

fn modelPathAlloc(allocator: std.mem.Allocator, model: []const u8) ![]u8 {
    if (std.mem.startsWith(u8, model, "models/") or std.mem.startsWith(u8, model, "tunedModels/")) return allocator.dupe(u8, model);
    return std.fmt.allocPrint(allocator, "models/{s}", .{model});
}

const GenerateContentResponse = struct {
    candidates: []Candidate = &.{},
};

const Candidate = struct {
    content: Content = .{},
};

const Content = struct {
    parts: []Part = &.{},
};

const Part = struct {
    text: []const u8 = "",
};

pub fn parseGenerateContentTextAlloc(allocator: std.mem.Allocator, source: []const u8) ![]u8 {
    var parsed = try std.json.parseFromSlice(GenerateContentResponse, allocator, source, .{ .ignore_unknown_fields = true });
    defer parsed.deinit();

    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);
    for (parsed.value.candidates) |candidate| {
        for (candidate.content.parts) |part| {
            if (part.text.len == 0) continue;
            try out.appendSlice(allocator, part.text);
        }
    }
    if (out.items.len == 0) return error.EmptyGeminiResponse;
    return out.toOwnedSlice(allocator);
}

pub fn mockGenerateContentListener() !std.net.Server {
    const address = try std.net.Address.parseIp("127.0.0.1", 0);
    return address.listen(.{ .reuse_address = true });
}

pub fn mockGenerateContentPort(listener: *const std.net.Server) u16 {
    return listener.listen_address.getPort();
}

pub fn serveOneMockGenerateContent(allocator: std.mem.Allocator, listener: *std.net.Server, response_json: []const u8) !void {
    var connection = try listener.accept();
    defer connection.stream.close();
    var request_buffer: [8192]u8 = undefined;
    const request_len = try connection.stream.read(&request_buffer);
    const request = request_buffer[0..request_len];
    const ok_path = std.mem.indexOf(u8, request, "POST /v1beta/models/gemini-test:generateContent?key=test-key ") != null;
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

fn urlQueryStringAlloc(allocator: std.mem.Allocator, value: []const u8) ![]u8 {
    const hex = "0123456789ABCDEF";
    var out: std.ArrayList(u8) = .empty;
    errdefer out.deinit(allocator);
    for (value) |byte| {
        const safe = (byte >= 'a' and byte <= 'z') or (byte >= 'A' and byte <= 'Z') or (byte >= '0' and byte <= '9') or byte == '-' or byte == '_' or byte == '.' or byte == '~';
        if (safe) {
            try out.append(allocator, byte);
        } else {
            try out.append(allocator, '%');
            try out.append(allocator, hex[byte >> 4]);
            try out.append(allocator, hex[byte & 0x0f]);
        }
    }
    return out.toOwnedSlice(allocator);
}

test "builds generateContent payload" {
    const payload = try generateContentPayloadAlloc(std.testing.allocator, "say \"ok\"");
    defer std.testing.allocator.free(payload);
    try std.testing.expectEqualStrings("{\"contents\":[{\"role\":\"user\",\"parts\":[{\"text\":\"say \\\"ok\\\"\"}]}],\"store\":false}", payload);
}

test "builds generateContent URL" {
    const url = try generateContentUrlAlloc(std.testing.allocator, default_base_url, default_model, "key with space");
    defer std.testing.allocator.free(url);
    try std.testing.expectEqualStrings("https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent?key=key%20with%20space", url);
}

test "parses generateContent output text" {
    const text = try parseGenerateContentTextAlloc(
        std.testing.allocator,
        "{\"candidates\":[{\"content\":{\"parts\":[{\"text\":\"ok\"}]}}]}",
    );
    defer std.testing.allocator.free(text);
    try std.testing.expectEqualStrings("ok", text);
}

test "empty generateContent output errors" {
    try std.testing.expectError(error.EmptyGeminiResponse, parseGenerateContentTextAlloc(std.testing.allocator, "{\"candidates\":[]}"));
}

test "mock generateContent harness returns deterministic text" {
    var listener = try mockGenerateContentListener();
    defer listener.deinit();
    const thread = try std.Thread.spawn(.{}, serveOneMockGenerateContent, .{
        std.testing.allocator,
        &listener,
        "{\"candidates\":[{\"content\":{\"parts\":[{\"text\":\"mock-ok\"}]}}]}",
    });
    defer thread.join();

    const base_url = try std.fmt.allocPrint(std.testing.allocator, "http://127.0.0.1:{d}/v1beta", .{mockGenerateContentPort(&listener)});
    defer std.testing.allocator.free(base_url);
    const text = try generateAlloc(std.testing.allocator, .{
        .api_key = "test-key",
        .model = "gemini-test",
        .base_url = base_url,
        .input = "say ok",
    });
    defer std.testing.allocator.free(text);
    try std.testing.expectEqualStrings("mock-ok", text);
}
