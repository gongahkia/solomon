const std = @import("std");

pub const module_id = "iam_whoami";

const AwsStsIdentityJson = struct {
    UserId: []const u8 = "",
    Account: []const u8 = "",
    Arn: []const u8 = "",
};

const GcloudAuthJson = struct {
    account: []const u8 = "",
    status: []const u8 = "",
};

const AzureAccountUserJson = struct {
    name: []const u8 = "",
    type: []const u8 = "",
};

const AzureAccountShowJson = struct {
    name: []const u8 = "",
    id: []const u8 = "",
    user: AzureAccountUserJson = .{},
};

pub fn awsStsCachePathAlloc(allocator: std.mem.Allocator, home: ?[]const u8, profile: ?[]const u8) !?[]u8 {
    const home_path = home orelse return null;
    const profile_name = sanitizeProfile(profile orelse "default");
    return @as(?[]u8, try std.fmt.allocPrint(allocator, "{s}/.cache/shisa/aws-sts-{s}.json", .{ home_path, profile_name }));
}

pub fn readAwsStsIdentityAlloc(allocator: std.mem.Allocator, path: []const u8) !?[]u8 {
    const source = std.fs.cwd().readFileAlloc(allocator, path, 256 * 1024) catch |err| switch (err) {
        error.FileNotFound => return null,
        else => return err,
    };
    defer allocator.free(source);
    return parseAwsStsIdentityAlloc(allocator, source);
}

pub fn parseAwsStsIdentityAlloc(allocator: std.mem.Allocator, source: []const u8) !?[]u8 {
    var parsed = std.json.parseFromSlice(AwsStsIdentityJson, allocator, source, .{ .ignore_unknown_fields = true }) catch return null;
    defer parsed.deinit();
    const arn = std.mem.trim(u8, parsed.value.Arn, " \t\r\n");
    if (arn.len != 0) return @as(?[]u8, try allocator.dupe(u8, arn));
    const account = std.mem.trim(u8, parsed.value.Account, " \t\r\n");
    if (account.len != 0) return @as(?[]u8, try allocator.dupe(u8, account));
    const user_id = std.mem.trim(u8, parsed.value.UserId, " \t\r\n");
    if (user_id.len != 0) return @as(?[]u8, try allocator.dupe(u8, user_id));
    return null;
}

pub fn gcloudAuthCachePathAlloc(allocator: std.mem.Allocator, home: ?[]const u8) !?[]u8 {
    const home_path = home orelse return null;
    return @as(?[]u8, try std.fmt.allocPrint(allocator, "{s}/.cache/shisa/gcloud-auth-list.json", .{home_path}));
}

pub fn readGcloudAuthAccountAlloc(allocator: std.mem.Allocator, path: []const u8) !?[]u8 {
    const source = std.fs.cwd().readFileAlloc(allocator, path, 256 * 1024) catch |err| switch (err) {
        error.FileNotFound => return null,
        else => return err,
    };
    defer allocator.free(source);
    return parseGcloudAuthAccountAlloc(allocator, source);
}

pub fn parseGcloudAuthAccountAlloc(allocator: std.mem.Allocator, source: []const u8) !?[]u8 {
    var parsed = std.json.parseFromSlice([]GcloudAuthJson, allocator, source, .{ .ignore_unknown_fields = true }) catch return null;
    defer parsed.deinit();
    var fallback: ?[]const u8 = null;
    for (parsed.value) |entry| {
        const account = std.mem.trim(u8, entry.account, " \t\r\n");
        if (account.len == 0) continue;
        if (fallback == null) fallback = account;
        if (std.ascii.eqlIgnoreCase(std.mem.trim(u8, entry.status, " \t\r\n"), "ACTIVE")) {
            return @as(?[]u8, try allocator.dupe(u8, account));
        }
    }
    if (fallback) |account| return @as(?[]u8, try allocator.dupe(u8, account));
    return null;
}

pub fn azureAccountCachePathAlloc(allocator: std.mem.Allocator, home: ?[]const u8) !?[]u8 {
    const home_path = home orelse return null;
    return @as(?[]u8, try std.fmt.allocPrint(allocator, "{s}/.cache/shisa/az-account-show.json", .{home_path}));
}

pub fn readAzureAccountAlloc(allocator: std.mem.Allocator, path: []const u8) !?[]u8 {
    const source = std.fs.cwd().readFileAlloc(allocator, path, 256 * 1024) catch |err| switch (err) {
        error.FileNotFound => return null,
        else => return err,
    };
    defer allocator.free(source);
    return parseAzureAccountAlloc(allocator, source);
}

pub fn parseAzureAccountAlloc(allocator: std.mem.Allocator, source: []const u8) !?[]u8 {
    var parsed = std.json.parseFromSlice(AzureAccountShowJson, allocator, source, .{ .ignore_unknown_fields = true }) catch return null;
    defer parsed.deinit();
    const user = std.mem.trim(u8, parsed.value.user.name, " \t\r\n");
    if (user.len != 0) return @as(?[]u8, try allocator.dupe(u8, user));
    const name = std.mem.trim(u8, parsed.value.name, " \t\r\n");
    if (name.len != 0) return @as(?[]u8, try allocator.dupe(u8, name));
    const id = std.mem.trim(u8, parsed.value.id, " \t\r\n");
    if (id.len != 0) return @as(?[]u8, try allocator.dupe(u8, id));
    return null;
}

pub fn kubeConfigPathAlloc(allocator: std.mem.Allocator, kubeconfig_env: ?[]const u8, home: ?[]const u8) !?[]u8 {
    if (kubeconfig_env) |value| {
        var entries = std.mem.splitScalar(u8, value, std.fs.path.delimiter);
        while (entries.next()) |entry| {
            const trimmed = std.mem.trim(u8, entry, " \t\r\n");
            if (trimmed.len != 0) return @as(?[]u8, try allocator.dupe(u8, trimmed));
        }
    }
    const home_path = home orelse return null;
    return @as(?[]u8, try std.fmt.allocPrint(allocator, "{s}/.kube/config", .{home_path}));
}

pub fn readKubeUserAlloc(allocator: std.mem.Allocator, path: []const u8) !?[]u8 {
    const source = std.fs.cwd().readFileAlloc(allocator, path, 1024 * 1024) catch |err| switch (err) {
        error.FileNotFound => return null,
        else => return err,
    };
    defer allocator.free(source);
    return parseKubeUserAlloc(allocator, source);
}

pub fn parseKubeUserAlloc(allocator: std.mem.Allocator, source: []const u8) !?[]u8 {
    const current_context = findTopLevelYamlScalar(source, "current-context") orelse return null;
    const user = findKubeContextUser(source, current_context) orelse return null;
    if (user.len == 0) return null;
    return @as(?[]u8, try allocator.dupe(u8, user));
}

fn sanitizeProfile(profile: []const u8) []const u8 {
    if (safeProfile(profile)) return profile;
    return "default";
}

fn safeProfile(profile: []const u8) bool {
    if (profile.len == 0) return false;
    for (profile) |byte| {
        if (!(std.ascii.isAlphanumeric(byte) or byte == '_' or byte == '-' or byte == '.')) return false;
    }
    return true;
}

const YamlLine = struct {
    indent: usize,
    trimmed: []const u8,
};

fn yamlLine(raw_line: []const u8) ?YamlLine {
    const line = std.mem.trimRight(u8, raw_line, "\r");
    const trimmed = std.mem.trim(u8, line, " \t");
    if (trimmed.len == 0 or trimmed[0] == '#') return null;
    var indent: usize = 0;
    while (indent < line.len and line[indent] == ' ') : (indent += 1) {}
    return .{ .indent = indent, .trimmed = trimmed };
}

fn hasYamlKey(line: []const u8, key: []const u8) bool {
    return line.len > key.len and std.mem.startsWith(u8, line, key) and line[key.len] == ':';
}

fn yamlScalar(line: []const u8, key: []const u8) ?[]const u8 {
    if (!hasYamlKey(line, key)) return null;
    var value = std.mem.trim(u8, line[key.len + 1 ..], " \t\r\n");
    if (value.len >= 2 and ((value[0] == '"' and value[value.len - 1] == '"') or (value[0] == '\'' and value[value.len - 1] == '\''))) {
        value = value[1 .. value.len - 1];
    }
    return value;
}

fn findTopLevelYamlScalar(source: []const u8, key: []const u8) ?[]const u8 {
    var lines = std.mem.splitScalar(u8, source, '\n');
    while (lines.next()) |raw_line| {
        const line = yamlLine(raw_line) orelse continue;
        if (line.indent != 0) continue;
        const value = yamlScalar(line.trimmed, key) orelse continue;
        if (value.len != 0) return value;
    }
    return null;
}

fn findKubeContextUser(source: []const u8, current_context: []const u8) ?[]const u8 {
    var lines = std.mem.splitScalar(u8, source, '\n');
    var in_contexts = false;
    var contexts_indent: usize = 0;
    var entry_active = false;
    var entry_indent: usize = 0;
    var context_indent: ?usize = null;
    var entry_name: ?[]const u8 = null;
    var entry_user: ?[]const u8 = null;

    while (lines.next()) |raw_line| {
        const line = yamlLine(raw_line) orelse continue;
        if (!in_contexts) {
            if (line.indent == 0 and hasYamlKey(line.trimmed, "contexts")) {
                in_contexts = true;
                contexts_indent = line.indent;
            }
            continue;
        }

        if (line.indent <= contexts_indent and !std.mem.startsWith(u8, line.trimmed, "- ")) break;
        if (std.mem.startsWith(u8, line.trimmed, "- ")) {
            if (entry_active and entry_name != null and std.mem.eql(u8, entry_name.?, current_context)) return entry_user;
            entry_active = true;
            entry_indent = line.indent;
            context_indent = null;
            entry_name = null;
            entry_user = null;
            const rest = std.mem.trim(u8, line.trimmed[2..], " \t");
            if (yamlScalar(rest, "name")) |value| entry_name = value;
            if (hasYamlKey(rest, "context")) context_indent = line.indent;
            if (yamlScalar(rest, "user")) |value| entry_user = value;
            continue;
        }

        if (!entry_active or line.indent <= entry_indent) continue;
        if (yamlScalar(line.trimmed, "name")) |value| entry_name = value;
        if (hasYamlKey(line.trimmed, "context")) {
            context_indent = line.indent;
            continue;
        }
        if (context_indent) |indent| {
            if (line.indent > indent) {
                if (yamlScalar(line.trimmed, "user")) |value| entry_user = value;
            } else {
                context_indent = null;
            }
        }
    }

    if (entry_active and entry_name != null and std.mem.eql(u8, entry_name.?, current_context)) return entry_user;
    return null;
}

test "parses aws sts identity arn" {
    const identity = (try parseAwsStsIdentityAlloc(std.testing.allocator,
        \\{
        \\  "UserId": "AIDAEXAMPLE",
        \\  "Account": "123456789012",
        \\  "Arn": "arn:aws:iam::123456789012:user/alice"
        \\}
    )).?;
    defer std.testing.allocator.free(identity);
    try std.testing.expectEqualStrings("arn:aws:iam::123456789012:user/alice", identity);
}

test "parses aws sts identity account fallback" {
    const identity = (try parseAwsStsIdentityAlloc(std.testing.allocator,
        \\{
        \\  "Account": "123456789012"
        \\}
    )).?;
    defer std.testing.allocator.free(identity);
    try std.testing.expectEqualStrings("123456789012", identity);
}

test "builds aws sts cache path" {
    const path = (try awsStsCachePathAlloc(std.testing.allocator, "/home/me", "prod")).?;
    defer std.testing.allocator.free(path);
    try std.testing.expectEqualStrings("/home/me/.cache/shisa/aws-sts-prod.json", path);
}

test "unsafe profile falls back in path" {
    const path = (try awsStsCachePathAlloc(std.testing.allocator, "/home/me", "../prod")).?;
    defer std.testing.allocator.free(path);
    try std.testing.expectEqualStrings("/home/me/.cache/shisa/aws-sts-default.json", path);
}

test "parses gcloud active account" {
    const account = (try parseGcloudAuthAccountAlloc(std.testing.allocator,
        \\[
        \\  {"account": "old@example.com", "status": ""},
        \\  {"account": "active@example.com", "status": "ACTIVE"}
        \\]
    )).?;
    defer std.testing.allocator.free(account);
    try std.testing.expectEqualStrings("active@example.com", account);
}

test "parses gcloud account fallback" {
    const account = (try parseGcloudAuthAccountAlloc(std.testing.allocator,
        \\[
        \\  {"account": "first@example.com"}
        \\]
    )).?;
    defer std.testing.allocator.free(account);
    try std.testing.expectEqualStrings("first@example.com", account);
}

test "builds gcloud auth cache path" {
    const path = (try gcloudAuthCachePathAlloc(std.testing.allocator, "/home/me")).?;
    defer std.testing.allocator.free(path);
    try std.testing.expectEqualStrings("/home/me/.cache/shisa/gcloud-auth-list.json", path);
}

test "parses azure account user" {
    const account = (try parseAzureAccountAlloc(std.testing.allocator,
        \\{
        \\  "id": "00000000-0000-0000-0000-000000000000",
        \\  "name": "prod-sub",
        \\  "user": {"name": "alice@example.com", "type": "user"}
        \\}
    )).?;
    defer std.testing.allocator.free(account);
    try std.testing.expectEqualStrings("alice@example.com", account);
}

test "parses azure account subscription fallback" {
    const account = (try parseAzureAccountAlloc(std.testing.allocator,
        \\{
        \\  "name": "prod-sub"
        \\}
    )).?;
    defer std.testing.allocator.free(account);
    try std.testing.expectEqualStrings("prod-sub", account);
}

test "builds azure account cache path" {
    const path = (try azureAccountCachePathAlloc(std.testing.allocator, "/home/me")).?;
    defer std.testing.allocator.free(path);
    try std.testing.expectEqualStrings("/home/me/.cache/shisa/az-account-show.json", path);
}

test "parses kube current context user" {
    const user = (try parseKubeUserAlloc(std.testing.allocator,
        \\apiVersion: v1
        \\contexts:
        \\- context:
        \\    cluster: prod
        \\    user: prod-user
        \\  name: prod
        \\- context:
        \\    cluster: dev
        \\    user: dev-user
        \\  name: dev
        \\current-context: prod
        \\
    )).?;
    defer std.testing.allocator.free(user);
    try std.testing.expectEqualStrings("prod-user", user);
}

test "builds kubeconfig path" {
    const path = (try kubeConfigPathAlloc(std.testing.allocator, null, "/home/me")).?;
    defer std.testing.allocator.free(path);
    try std.testing.expectEqualStrings("/home/me/.kube/config", path);
}
