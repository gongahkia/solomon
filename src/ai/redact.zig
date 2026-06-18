const std = @import("std");

pub const marker = "[redacted]";

const KeyValue = struct {
    prefix_end: usize,
    value_end: usize,
};

const key_names = [_][]const u8{
    "aws_secret_access_key",
    "aws_access_key_id",
    "aws_session_token",
    "client-certificate-data",
    "client-key-data",
    "client_secret",
    "refresh_token",
    "access_token",
    "identityfile",
    "private_key",
    "password",
    "passwd",
    "api_key",
    "apikey",
    "secret",
    "token",
};

pub fn redactAlloc(allocator: std.mem.Allocator, input: []const u8) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    errdefer out.deinit(allocator);

    var index: usize = 0;
    while (index < input.len) {
        if (privateKeyBlockEnd(input, index)) |end| {
            try out.appendSlice(allocator, marker);
            index = end;
            continue;
        }
        if (bearerValue(input, index)) |match| {
            try out.appendSlice(allocator, input[index..match.prefix_end]);
            try out.appendSlice(allocator, marker);
            index = match.value_end;
            continue;
        }
        if (keyValue(input, index)) |match| {
            try out.appendSlice(allocator, input[index..match.prefix_end]);
            try out.appendSlice(allocator, marker);
            index = match.value_end;
            continue;
        }
        if (secretTokenEnd(input, index)) |end| {
            try out.appendSlice(allocator, marker);
            index = end;
            continue;
        }
        try out.append(allocator, input[index]);
        index += 1;
    }

    return out.toOwnedSlice(allocator);
}

fn privateKeyBlockEnd(input: []const u8, start: usize) ?usize {
    const tail = input[start..];
    if (!std.mem.startsWith(u8, tail, "-----BEGIN ")) return null;
    const header_end = std.mem.indexOfScalar(u8, tail, '\n') orelse tail.len;
    if (std.mem.indexOf(u8, tail[0..header_end], "PRIVATE KEY-----") == null) return null;
    if (std.mem.indexOf(u8, tail, "-----END ")) |relative_end| {
        const line_end = std.mem.indexOfScalar(u8, tail[relative_end..], '\n') orelse tail[relative_end..].len;
        return start + relative_end + line_end;
    }
    return input.len;
}

fn bearerValue(input: []const u8, start: usize) ?KeyValue {
    if (!boundaryBefore(input, start)) return null;
    if (!startsWithIgnoreCase(input[start..], "bearer")) return null;
    var index = start + "bearer".len;
    if (index >= input.len or !std.ascii.isWhitespace(input[index])) return null;
    while (index < input.len and std.ascii.isWhitespace(input[index]) and input[index] != '\n') : (index += 1) {}
    if (index >= input.len or std.mem.startsWith(u8, input[index..], marker)) return null;
    const end = tokenEnd(input, index);
    if (end == index) return null;
    return .{ .prefix_end = index, .value_end = end };
}

fn keyValue(input: []const u8, start: usize) ?KeyValue {
    if (!boundaryBefore(input, start)) return null;
    var key_start = start;
    const quote = if (input[start] == '"' or input[start] == '\'') input[start] else 0;
    if (quote != 0) key_start += 1;

    for (key_names) |key| {
        if (!startsWithIgnoreCase(input[key_start..], key)) continue;
        var index = key_start + key.len;
        if (quote != 0) {
            if (index >= input.len or input[index] != quote) continue;
            index += 1;
        } else if (!boundaryAfter(input, index)) {
            continue;
        }
        while (index < input.len and input[index] != '\n' and std.ascii.isWhitespace(input[index])) : (index += 1) {}
        if (index < input.len and (input[index] == '=' or input[index] == ':')) {
            index += 1;
            while (index < input.len and input[index] != '\n' and std.ascii.isWhitespace(input[index])) : (index += 1) {}
        } else if (!std.ascii.eqlIgnoreCase(key, "identityfile")) {
            continue;
        }
        if (index >= input.len or input[index] == '\n' or input[index] == '\r') continue;
        return valueRange(input, index);
    }
    return null;
}

fn valueRange(input: []const u8, start: usize) ?KeyValue {
    if (std.mem.startsWith(u8, input[start..], marker)) return null;
    if (input[start] == '"' or input[start] == '\'') {
        const quote = input[start];
        const value_start = start + 1;
        if (value_start >= input.len or std.mem.startsWith(u8, input[value_start..], marker)) return null;
        var end = value_start;
        while (end < input.len and input[end] != quote and input[end] != '\n' and input[end] != '\r') : (end += 1) {}
        if (end == value_start) return null;
        return .{ .prefix_end = value_start, .value_end = end };
    }
    const end = tokenEnd(input, start);
    if (end == start) return null;
    return .{ .prefix_end = start, .value_end = end };
}

fn secretTokenEnd(input: []const u8, start: usize) ?usize {
    if (!boundaryBefore(input, start)) return null;
    if (awsAccessKeyEnd(input, start)) |end| return end;
    if (prefixedTokenEnd(input, start, &.{ "ghp_", "gho_", "ghu_", "ghs_", "ghr_", "sk-" })) |end| return end;
    if (awsAccountIdEnd(input, start)) |end| return end;
    return null;
}

fn awsAccessKeyEnd(input: []const u8, start: usize) ?usize {
    if (!(std.mem.startsWith(u8, input[start..], "AKIA") or std.mem.startsWith(u8, input[start..], "ASIA"))) return null;
    const end = start + 20;
    if (end > input.len or !boundaryAfter(input, end)) return null;
    for (input[start..end]) |byte| {
        if (!(std.ascii.isUpper(byte) or std.ascii.isDigit(byte))) return null;
    }
    return end;
}

fn prefixedTokenEnd(input: []const u8, start: usize, comptime prefixes: []const []const u8) ?usize {
    for (prefixes) |prefix| {
        if (!std.mem.startsWith(u8, input[start..], prefix)) continue;
        const end = tokenEnd(input, start);
        if (end >= start + prefix.len + 8) return end;
    }
    return null;
}

fn awsAccountIdEnd(input: []const u8, start: usize) ?usize {
    const end = start + 12;
    if (end > input.len or !boundaryAfter(input, end)) return null;
    for (input[start..end]) |byte| {
        if (!std.ascii.isDigit(byte)) return null;
    }
    return end;
}

fn tokenEnd(input: []const u8, start: usize) usize {
    var end = start;
    while (end < input.len and isTokenByte(input[end])) : (end += 1) {}
    return end;
}

fn startsWithIgnoreCase(value: []const u8, prefix: []const u8) bool {
    return value.len >= prefix.len and std.ascii.eqlIgnoreCase(value[0..prefix.len], prefix);
}

fn boundaryBefore(input: []const u8, start: usize) bool {
    return start == 0 or !isWordByte(input[start - 1]);
}

fn boundaryAfter(input: []const u8, end: usize) bool {
    return end >= input.len or !isWordByte(input[end]);
}

fn isWordByte(byte: u8) bool {
    return std.ascii.isAlphanumeric(byte) or byte == '_' or byte == '-';
}

fn isTokenByte(byte: u8) bool {
    return std.ascii.isAlphanumeric(byte) or byte == '_' or byte == '-' or byte == '.' or byte == '/' or byte == '+' or byte == '=' or byte == '~' or byte == ':';
}

test "redacts documented credential patterns" {
    const input =
        \\AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE
        \\aws_secret_access_key = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
        \\Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig
        \\github=ghp_abcdefghijklmnopqrstuvwxyz1234567890
        \\openai=sk-abcdefghijklmnopqrst
        \\account=123456789012
        \\IdentityFile ~/.ssh/id_rsa
        \\token: kube-secret
        \\-----BEGIN OPENSSH PRIVATE KEY-----
        \\abc123
        \\-----END OPENSSH PRIVATE KEY-----
        \\
    ;
    const output = try redactAlloc(std.testing.allocator, input);
    defer std.testing.allocator.free(output);

    inline for (.{
        "AKIAIOSFODNN7EXAMPLE",
        "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        "eyJhbGciOiJIUzI1NiJ9.payload.sig",
        "ghp_abcdefghijklmnopqrstuvwxyz1234567890",
        "sk-abcdefghijklmnopqrst",
        "123456789012",
        "~/.ssh/id_rsa",
        "kube-secret",
        "abc123",
    }) |secret| {
        try std.testing.expect(std.mem.indexOf(u8, output, secret) == null);
    }
    try std.testing.expect(std.mem.indexOf(u8, output, marker) != null);
}

test "keeps harmless prompt context unchanged" {
    const input = "shell=zsh\ncwd=/repo\nrequest=list files\n";
    const output = try redactAlloc(std.testing.allocator, input);
    defer std.testing.allocator.free(output);
    try std.testing.expectEqualStrings(input, output);
}

test "fuzz redaction invariants" {
    return std.testing.fuzz({}, fuzzRedaction, .{
        .corpus = &.{
            "",
            "token=secret",
            "Authorization: Bearer abc.def.ghi",
            "-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----\n",
            "AKIAIOSFODNN7EXAMPLE",
        },
    });
}

fn fuzzRedaction(_: void, input: []const u8) !void {
    if (input.len > 8192) return;
    const redacted = try redactAlloc(std.testing.allocator, input);
    defer std.testing.allocator.free(redacted);
    const again = try redactAlloc(std.testing.allocator, redacted);
    defer std.testing.allocator.free(again);
    try std.testing.expectEqualStrings(redacted, again);
}
