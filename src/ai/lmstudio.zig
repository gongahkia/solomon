const std = @import("std");
const openai_compat = @import("openai.zig");

pub const provider_id = "lmstudio";
pub const default_model = "openai/gpt-oss-20b";
pub const default_base_url = "http://127.0.0.1:1234/v1";
const max_http_response_bytes = 16 * 1024 * 1024;

pub const GenerateConfig = struct {
    model: []const u8 = default_model,
    base_url: []const u8 = default_base_url,
    input: []const u8,
};

pub fn baseUrlFromEnvAlloc(allocator: std.mem.Allocator) ![]u8 {
    const url = std.process.getEnvVarOwned(allocator, "SHISA_LMSTUDIO_BASE_URL") catch |err| switch (err) {
        error.EnvironmentVariableNotFound => return allocator.dupe(u8, default_base_url),
        else => return err,
    };
    errdefer allocator.free(url);
    if (std.mem.trim(u8, url, " \t\r\n").len == 0) return error.LmStudioBaseUrlMissing;
    if (!isLoopbackBaseUrl(url)) return error.LmStudioRemoteBaseUrl;
    return url;
}

pub fn generateAlloc(allocator: std.mem.Allocator, config: GenerateConfig) ![]u8 {
    if (!isLoopbackBaseUrl(config.base_url)) return error.LmStudioRemoteBaseUrl;
    const payload = try responsesPayloadAlloc(allocator, config.model, config.input);
    defer allocator.free(payload);
    const endpoint = try responsesUrlAlloc(allocator, config.base_url);
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
    if (status < 200 or status >= 300) return error.LmStudioHttpError;
    if (response_body.written().len > max_http_response_bytes) return error.ResponseTooLarge;
    return openai_compat.parseResponsesTextAlloc(allocator, response_body.written());
}

pub fn responsesPayloadAlloc(allocator: std.mem.Allocator, model: []const u8, input: []const u8) ![]u8 {
    const escaped_model = try jsonStringAlloc(allocator, model);
    defer allocator.free(escaped_model);
    const escaped_input = try jsonStringAlloc(allocator, input);
    defer allocator.free(escaped_input);
    return std.fmt.allocPrint(allocator, "{{\"model\":{s},\"input\":{s}}}", .{ escaped_model, escaped_input });
}

pub fn responsesUrlAlloc(allocator: std.mem.Allocator, base_url: []const u8) ![]u8 {
    const trimmed = std.mem.trimRight(u8, base_url, "/");
    if (std.mem.endsWith(u8, trimmed, "/responses")) return allocator.dupe(u8, trimmed);
    return std.fmt.allocPrint(allocator, "{s}/responses", .{trimmed});
}

fn isLoopbackBaseUrl(value: []const u8) bool {
    const trimmed = std.mem.trim(u8, value, " \t\r\n");
    return hasLoopbackPrefix(trimmed, "http://127.0.0.1") or hasLoopbackPrefix(trimmed, "http://localhost") or hasLoopbackPrefix(trimmed, "http://[::1]");
}

fn hasLoopbackPrefix(value: []const u8, prefix: []const u8) bool {
    if (!std.mem.startsWith(u8, value, prefix)) return false;
    if (value.len == prefix.len) return true;
    return value[prefix.len] == ':' or value[prefix.len] == '/';
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
    try std.testing.expectEqualStrings("{\"model\":\"openai/gpt-oss-20b\",\"input\":\"say \\\"ok\\\"\"}", payload);
}

test "builds responses URL from base URL" {
    const url = try responsesUrlAlloc(std.testing.allocator, "http://127.0.0.1:1234/v1/");
    defer std.testing.allocator.free(url);
    try std.testing.expectEqualStrings("http://127.0.0.1:1234/v1/responses", url);
}

test "rejects non-loopback base URL" {
    try std.testing.expectError(error.LmStudioRemoteBaseUrl, generateAlloc(std.testing.allocator, .{
        .model = "x",
        .base_url = "https://example.com/v1",
        .input = "hi",
    }));
}

test "mock responses harness returns deterministic text" {
    var listener = try openai_compat.mockResponsesListener();
    defer listener.deinit();
    const thread = try std.Thread.spawn(.{}, openai_compat.serveOneMockResponses, .{
        std.testing.allocator,
        &listener,
        "{\"output\":[{\"type\":\"message\",\"content\":[{\"type\":\"output_text\",\"text\":\"mock-ok\"}]}]}",
    });
    defer thread.join();

    const base_url = try std.fmt.allocPrint(std.testing.allocator, "http://127.0.0.1:{d}/v1", .{openai_compat.mockResponsesPort(&listener)});
    defer std.testing.allocator.free(base_url);
    const text = try generateAlloc(std.testing.allocator, .{
        .model = "local-test",
        .base_url = base_url,
        .input = "say ok",
    });
    defer std.testing.allocator.free(text);
    try std.testing.expectEqualStrings("mock-ok", text);
}
