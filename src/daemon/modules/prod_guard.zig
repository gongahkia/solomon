const std = @import("std");

pub const module_id = "prod_guard";

pub fn destructivePattern(command: []const u8) ?[]const u8 {
    if (containsSqlDropTable(command)) return "DROP TABLE";
    var tokens = TokenList{};
    tokens.init(command);
    if (tokens.len == 0) return null;

    if (tokenEql(tokens.at(0), "kubectl") and tokens.len >= 2) {
        if (tokenEql(tokens.at(1), "delete")) return "kubectl delete";
        if (tokenEql(tokens.at(1), "drain")) return "kubectl drain";
    }
    if (tokenEql(tokens.at(0), "terraform") and tokens.len >= 2 and tokenEql(tokens.at(1), "destroy")) return "terraform destroy";
    if (tokenEql(tokens.at(0), "aws") and tokens.len >= 3) {
        if (tokenEql(tokens.at(1), "ec2") and startsWithIgnoreCase(tokens.at(2), "terminate")) return "aws ec2 terminate";
        if (tokenEql(tokens.at(1), "s3") and tokenEql(tokens.at(2), "rb")) return "aws s3 rb";
    }
    if (tokenEql(tokens.at(0), "gcloud")) {
        var index: usize = 1;
        while (index < tokens.len) : (index += 1) {
            if (tokenEql(tokens.at(index), "delete")) return "gcloud * delete";
        }
    }
    if (tokenEql(tokens.at(0), "rm")) {
        var index: usize = 1;
        while (index < tokens.len) : (index += 1) {
            if (isRecursiveForceFlag(tokens.at(index))) return "rm -rf";
        }
    }
    if (tokenEql(tokens.at(0), "dd")) {
        var index: usize = 1;
        while (index < tokens.len) : (index += 1) {
            if (startsWithIgnoreCase(tokens.at(index), "of=/dev/")) return "dd of=/dev/";
        }
    }
    if (startsWithIgnoreCase(tokens.at(0), "mkfs")) return "mkfs";
    return null;
}

const max_tokens = 64;

const TokenList = struct {
    values: [max_tokens][]const u8 = undefined,
    len: usize = 0,

    fn init(self: *TokenList, command: []const u8) void {
        var parts = std.mem.tokenizeAny(u8, command, " \t\r\n;");
        while (parts.next()) |part| {
            if (self.len == max_tokens) break;
            self.values[self.len] = part;
            self.len += 1;
        }
    }

    fn at(self: TokenList, index: usize) []const u8 {
        return self.values[index];
    }
};

fn tokenEql(left: []const u8, right: []const u8) bool {
    return std.ascii.eqlIgnoreCase(left, right);
}

fn startsWithIgnoreCase(value: []const u8, prefix: []const u8) bool {
    if (value.len < prefix.len) return false;
    return std.ascii.eqlIgnoreCase(value[0..prefix.len], prefix);
}

fn isRecursiveForceFlag(token: []const u8) bool {
    if (token.len < 3 or token[0] != '-') return false;
    return std.mem.indexOfScalar(u8, token, 'r') != null and std.mem.indexOfScalar(u8, token, 'f') != null;
}

fn containsSqlDropTable(command: []const u8) bool {
    var tokens = TokenList{};
    tokens.init(command);
    var previous_drop = false;
    var index: usize = 0;
    while (index < tokens.len) : (index += 1) {
        const token = trimSqlToken(tokens.at(index));
        if (previous_drop and tokenEql(token, "table")) return true;
        previous_drop = tokenEql(token, "drop");
    }
    return false;
}

fn trimSqlToken(token: []const u8) []const u8 {
    return std.mem.trim(u8, token, "'\"`()[]{}.,");
}

test "matches kubectl destructive commands" {
    try std.testing.expectEqualStrings("kubectl delete", destructivePattern("kubectl delete pod x").?);
    try std.testing.expectEqualStrings("kubectl drain", destructivePattern("kubectl drain node-a").?);
}

test "matches terraform and cloud destructive commands" {
    try std.testing.expectEqualStrings("terraform destroy", destructivePattern("terraform destroy -auto-approve").?);
    try std.testing.expectEqualStrings("aws ec2 terminate", destructivePattern("aws ec2 terminate-instances --instance-ids i-123").?);
    try std.testing.expectEqualStrings("aws s3 rb", destructivePattern("aws s3 rb s3://bucket").?);
    try std.testing.expectEqualStrings("gcloud * delete", destructivePattern("gcloud compute instances delete vm-a").?);
}

test "matches local destructive commands" {
    try std.testing.expectEqualStrings("rm -rf", destructivePattern("rm -rf /tmp/x").?);
    try std.testing.expectEqualStrings("rm -rf", destructivePattern("rm -fr /tmp/x").?);
    try std.testing.expectEqualStrings("dd of=/dev/", destructivePattern("dd if=a of=/dev/disk2").?);
    try std.testing.expectEqualStrings("mkfs", destructivePattern("mkfs.ext4 /dev/sdb").?);
}

test "matches sql drop table" {
    try std.testing.expectEqualStrings("DROP TABLE", destructivePattern("psql -c 'DROP TABLE users'").?);
}

test "does not match safe commands" {
    try std.testing.expect(destructivePattern("kubectl get pods") == null);
    try std.testing.expect(destructivePattern("terraform plan") == null);
}

test "safe command corpus does not trigger blocklist" {
    const source = try std.fs.cwd().readFileAlloc(std.testing.allocator, "test/fixtures/prod_guard/safe_commands.txt", 64 * 1024);
    defer std.testing.allocator.free(source);

    var lines = std.mem.splitScalar(u8, source, '\n');
    while (lines.next()) |raw_line| {
        const line = std.mem.trim(u8, raw_line, " \t\r");
        if (line.len == 0 or line[0] == '#') continue;
        try std.testing.expect(destructivePattern(line) == null);
    }
}

test "fuzzes destructive command templates" {
    var prng = std.Random.DefaultPrng.init(0x5eed_f00d);
    const random = prng.random();
    const cases = [_]struct {
        tokens: []const []const u8,
        pattern: []const u8,
    }{
        .{ .tokens = &.{ "kubectl", "delete", "pod", "api" }, .pattern = "kubectl delete" },
        .{ .tokens = &.{ "kubectl", "drain", "node-a" }, .pattern = "kubectl drain" },
        .{ .tokens = &.{ "terraform", "destroy", "-auto-approve" }, .pattern = "terraform destroy" },
        .{ .tokens = &.{ "aws", "ec2", "terminate-instances", "--instance-ids", "i-123" }, .pattern = "aws ec2 terminate" },
        .{ .tokens = &.{ "aws", "s3", "rb", "s3://bucket" }, .pattern = "aws s3 rb" },
        .{ .tokens = &.{ "gcloud", "compute", "instances", "delete", "vm-a" }, .pattern = "gcloud * delete" },
        .{ .tokens = &.{ "rm", "-rf", "/tmp/x" }, .pattern = "rm -rf" },
        .{ .tokens = &.{ "rm", "-fr", "/tmp/x" }, .pattern = "rm -rf" },
        .{ .tokens = &.{ "dd", "if=a", "of=/dev/disk2" }, .pattern = "dd of=/dev/" },
        .{ .tokens = &.{ "mkfs.ext4", "/dev/sdb" }, .pattern = "mkfs" },
        .{ .tokens = &.{ "psql", "-c", "drop", "table", "users" }, .pattern = "DROP TABLE" },
    };
    for (0..32) |_| {
        for (cases) |case| {
            const command = try fuzzCommandAlloc(std.testing.allocator, random, case.tokens);
            defer std.testing.allocator.free(command);
            try std.testing.expectEqualStrings(case.pattern, destructivePattern(command).?);
        }
    }
}

test "fuzzes safe command templates" {
    var prng = std.Random.DefaultPrng.init(0x51afe);
    const random = prng.random();
    const cases = [_][]const []const u8{
        &.{ "kubectl", "get", "pods" },
        &.{ "kubectl", "describe", "pod", "api-prod" },
        &.{ "terraform", "plan" },
        &.{ "terraform", "show" },
        &.{ "aws", "ec2", "describe-instances" },
        &.{ "aws", "s3", "ls", "s3://prod-bucket" },
        &.{ "gcloud", "compute", "instances", "list" },
        &.{ "rm", "-ri", "/tmp/shisa-test" },
        &.{ "dd", "if=/dev/zero", "of=./disk.img" },
        &.{ "psql", "-c", "select", "from", "users" },
    };
    for (0..32) |_| {
        for (cases) |tokens| {
            const command = try fuzzCommandAlloc(std.testing.allocator, random, tokens);
            defer std.testing.allocator.free(command);
            try std.testing.expect(destructivePattern(command) == null);
        }
    }
}

fn fuzzCommandAlloc(allocator: std.mem.Allocator, random: std.Random, tokens: []const []const u8) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    errdefer out.deinit(allocator);
    for (tokens, 0..) |token, index| {
        if (index != 0) {
            const spaces = random.intRangeAtMost(u8, 1, 4);
            for (0..spaces) |_| try out.append(allocator, if (random.boolean()) ' ' else '\t');
        }
        try appendRandomCase(allocator, &out, random, token);
    }
    return out.toOwnedSlice(allocator);
}

fn appendRandomCase(allocator: std.mem.Allocator, out: *std.ArrayList(u8), random: std.Random, token: []const u8) !void {
    if (token.len != 0 and token[0] == '-') {
        try out.appendSlice(allocator, token);
        return;
    }
    for (token) |byte| {
        if (std.ascii.isAlphabetic(byte)) {
            try out.append(allocator, if (random.boolean()) std.ascii.toUpper(byte) else std.ascii.toLower(byte));
        } else {
            try out.append(allocator, byte);
        }
    }
}
