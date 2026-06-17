const std = @import("std");

pub const default_host = "127.0.0.1";
pub const default_port: u16 = 11434;
pub const recommended_model = "gemma3:1b";
const max_http_response_bytes = 16 * 1024 * 1024;

pub const Status = struct {
    installed: bool,
    daemon_running: bool,
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

pub fn generateAlloc(allocator: std.mem.Allocator, host: []const u8, port: u16, model: []const u8, prompt: []const u8) ![]u8 {
    const payload = try generatePayloadAlloc(allocator, model, prompt, false);
    defer allocator.free(payload);
    var response = try httpRequestAlloc(allocator, host, port, "POST", "/api/generate", payload);
    defer response.deinit(allocator);
    if (response.status < 200 or response.status >= 300) return error.OllamaHttpError;
    return parseGenerateResponseAlloc(allocator, response.body);
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

pub fn generatePayloadAlloc(allocator: std.mem.Allocator, model: []const u8, prompt: []const u8, stream: bool) ![]u8 {
    const escaped_model = try jsonStringAlloc(allocator, model);
    defer allocator.free(escaped_model);
    const escaped_prompt = try jsonStringAlloc(allocator, prompt);
    defer allocator.free(escaped_prompt);
    return std.fmt.allocPrint(allocator, "{{\"model\":{s},\"prompt\":{s},\"stream\":{}}}", .{ escaped_model, escaped_prompt, stream });
}

const GenerateResponse = struct {
    response: []const u8 = "",
};

pub fn parseGenerateResponseAlloc(allocator: std.mem.Allocator, source: []const u8) ![]u8 {
    var parsed = try std.json.parseFromSlice(GenerateResponse, allocator, source, .{ .ignore_unknown_fields = true });
    defer parsed.deinit();
    return allocator.dupe(u8, parsed.value.response);
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
    try std.testing.expectEqualStrings("{\"model\":\"gemma3:1b\",\"prompt\":\"say \\\"hi\\\"\",\"stream\":false}", payload);
}

test "parses generate response" {
    const text = try parseGenerateResponseAlloc(std.testing.allocator, "{\"response\":\"ok\",\"done\":true}");
    defer std.testing.allocator.free(text);
    try std.testing.expectEqualStrings("ok", text);
}
