const std = @import("std");
const prod_guard = @import("../daemon/modules/prod_guard.zig");

pub const Risk = enum {
    low,
    medium,
    high,

    pub fn label(self: Risk) []const u8 {
        return switch (self) {
            .low => "low",
            .medium => "medium",
            .high => "high",
        };
    }
};

pub const Explanation = struct {
    risk: Risk,
    source: []const u8,
    pattern: []const u8,
};

pub const default_prompt =
    \\You are shisa risk. Classify one shell command as low, medium, or high risk.
    \\Output only one label: low, medium, or high.
    \\
    \\Rules:
    \\- high means destructive or likely irreversible.
    \\- medium means mutating, privileged, or hard to inspect.
    \\- low means read-only or harmless.
    \\
    \\Command: {{command}}
++ "\n";

pub fn explain(command: []const u8) Explanation {
    if (prod_guard.destructivePattern(command)) |pattern| {
        return .{ .risk = .high, .source = "rules", .pattern = pattern };
    }
    if (isBorderline(command)) return .{ .risk = .medium, .source = "rules", .pattern = "borderline" };
    return .{ .risk = .low, .source = "rules", .pattern = "-" };
}

pub fn outputAlloc(allocator: std.mem.Allocator, command: []const u8) ![]u8 {
    const result = explain(command);
    return outputExplanationAlloc(allocator, command, result);
}

pub fn outputExplanationAlloc(allocator: std.mem.Allocator, command: []const u8, result: Explanation) ![]u8 {
    const annotation = try annotationAlloc(allocator, command, result);
    defer allocator.free(annotation);
    return std.fmt.allocPrint(allocator, "risk: {s}\nsource: {s}\npattern: {s}\nannotation: {s}\n", .{ result.risk.label(), result.source, result.pattern, annotation });
}

pub fn annotationAlloc(allocator: std.mem.Allocator, command: []const u8, result: Explanation) ![]u8 {
    if (std.mem.eql(u8, result.pattern, "rm -rf")) {
        if (rmRecursiveTarget(command)) |target| {
            const count = countFilesUnderTarget(allocator, target) catch 0;
            if (count != 0) return std.fmt.allocPrint(allocator, "this will delete {d} files in {s}", .{ count, target });
            return std.fmt.allocPrint(allocator, "this may delete files in {s}", .{target});
        }
    }
    if (std.mem.startsWith(u8, result.pattern, "kubectl ")) return allocator.dupe(u8, "this may delete Kubernetes resources");
    if (std.mem.eql(u8, result.pattern, "terraform destroy")) return allocator.dupe(u8, "this may destroy Terraform-managed infrastructure");
    if (std.mem.eql(u8, result.pattern, "DROP TABLE")) return allocator.dupe(u8, "this may drop a database table");
    if (std.mem.eql(u8, result.pattern, "borderline")) return allocator.dupe(u8, "this command needs review before running");
    return allocator.dupe(u8, "-");
}

pub fn promptWithCommandAlloc(allocator: std.mem.Allocator, command: []const u8) ![]u8 {
    const marker = "{{command}}";
    if (std.mem.indexOf(u8, default_prompt, marker)) |index| {
        var out: std.ArrayList(u8) = .empty;
        errdefer out.deinit(allocator);
        try out.appendSlice(allocator, default_prompt[0..index]);
        try out.appendSlice(allocator, command);
        try out.appendSlice(allocator, default_prompt[index + marker.len ..]);
        return out.toOwnedSlice(allocator);
    }
    return std.fmt.allocPrint(allocator, "{s}\nCommand: {s}\n", .{ default_prompt, command });
}

pub fn parseSlmRisk(raw: []const u8) ?Risk {
    const trimmed = std.mem.trim(u8, raw, " \t\r\n.:-`\"'");
    if (startsWithIgnoreCase(trimmed, "low")) return .low;
    if (startsWithIgnoreCase(trimmed, "medium")) return .medium;
    if (startsWithIgnoreCase(trimmed, "high")) return .high;
    return null;
}

fn startsWithIgnoreCase(value: []const u8, prefix: []const u8) bool {
    if (value.len < prefix.len) return false;
    return std.ascii.eqlIgnoreCase(value[0..prefix.len], prefix);
}

fn isBorderline(command: []const u8) bool {
    if (std.mem.indexOfAny(u8, command, "|;&><`") != null) return true;
    if (std.mem.indexOf(u8, command, "$(") != null) return true;
    var tokens = std.mem.tokenizeAny(u8, command, " \t\r\n");
    const first = tokens.next() orelse return false;
    inline for (.{ "sudo", "chmod", "chown", "mv", "cp", "rsync", "find", "xargs", "kill", "pkill" }) |name| {
        if (std.mem.eql(u8, first, name)) return true;
    }
    return false;
}

fn rmRecursiveTarget(command: []const u8) ?[]const u8 {
    var tokens = std.mem.tokenizeAny(u8, command, " \t\r\n;");
    const first = tokens.next() orelse return null;
    if (!std.ascii.eqlIgnoreCase(first, "rm")) return null;
    while (tokens.next()) |token| {
        if (std.mem.startsWith(u8, token, "-")) continue;
        const target = std.mem.trim(u8, token, "\"'");
        return if (target.len == 0) null else target;
    }
    return null;
}

fn countFilesUnderTarget(allocator: std.mem.Allocator, target: []const u8) !usize {
    _ = allocator;
    if (target.len == 0) return 0;
    var dir = if (std.fs.path.isAbsolute(target))
        try std.fs.openDirAbsolute(target, .{ .iterate = true })
    else
        try std.fs.cwd().openDir(target, .{ .iterate = true });
    defer dir.close();
    return countFilesInDir(&dir, 10000);
}

fn countFilesInDir(dir: *std.fs.Dir, limit: usize) !usize {
    if (limit == 0) return 0;
    var count: usize = 0;
    var iter = dir.iterate();
    while (try iter.next()) |entry| {
        if (entry.kind == .file or entry.kind == .sym_link) {
            count += 1;
        } else if (entry.kind == .directory) {
            var child = dir.openDir(entry.name, .{ .iterate = true }) catch continue;
            defer child.close();
            count += try countFilesInDir(&child, limit - count);
        }
        if (count >= limit) return count;
    }
    return count;
}

test "explains risk with prod guard blocklist" {
    const destructive = explain("rm -rf /tmp/x");
    try std.testing.expectEqual(Risk.high, destructive.risk);
    try std.testing.expectEqualStrings("rm -rf", destructive.pattern);

    const safe = explain("kubectl get pods");
    try std.testing.expectEqual(Risk.low, safe.risk);
    try std.testing.expectEqualStrings("-", safe.pattern);

    const borderline = explain("sudo systemctl status sshd");
    try std.testing.expectEqual(Risk.medium, borderline.risk);
    try std.testing.expectEqualStrings("borderline", borderline.pattern);
}

test "renders risk output" {
    const output = try outputAlloc(std.testing.allocator, "terraform destroy");
    defer std.testing.allocator.free(output);
    try std.testing.expectEqualStrings("risk: high\nsource: rules\npattern: terraform destroy\nannotation: this may destroy Terraform-managed infrastructure\n", output);
}

test "parses slm risk labels" {
    try std.testing.expectEqual(Risk.low, parseSlmRisk("low\n").?);
    try std.testing.expectEqual(Risk.medium, parseSlmRisk("Medium risk").?);
    try std.testing.expectEqual(Risk.high, parseSlmRisk("HIGH").?);
    try std.testing.expect(parseSlmRisk("unknown") == null);
}

test "annotates rm recursive target with file count" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-risk-annotation-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    try std.fs.cwd().makePath(dir_path);
    defer std.fs.deleteTreeAbsolute(dir_path) catch {};
    const file_path = try std.fmt.allocPrint(allocator, "{s}/a.txt", .{dir_path});
    defer allocator.free(file_path);
    var file = try std.fs.createFileAbsolute(file_path, .{});
    file.close();

    const annotation = try annotationAlloc(allocator, "rm -rf /tmp/shisa-risk-annotation-nope", explain("rm -rf /tmp/shisa-risk-annotation-nope"));
    defer allocator.free(annotation);
    try std.testing.expect(std.mem.indexOf(u8, annotation, "this may delete files in") != null);

    const command = try std.fmt.allocPrint(allocator, "rm -rf {s}", .{dir_path});
    defer allocator.free(command);
    const counted = try annotationAlloc(allocator, command, explain(command));
    defer allocator.free(counted);
    try std.testing.expect(std.mem.indexOf(u8, counted, "this will delete 1 files in") != null);
}
