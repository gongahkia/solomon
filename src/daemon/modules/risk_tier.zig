const std = @import("std");

pub const module_id = "risk_tier";

pub const Tier = enum {
    unknown,
    dev,
    staging,
    prod,
};

pub const Rules = struct {
    dev: [][]u8 = &.{},
    staging: [][]u8 = &.{},
    prod: [][]u8 = &.{},

    pub fn deinit(self: *Rules, allocator: std.mem.Allocator) void {
        freePatterns(allocator, self.dev);
        freePatterns(allocator, self.staging);
        freePatterns(allocator, self.prod);
        self.* = .{};
    }
};

pub fn classify(value: []const u8) Tier {
    var tier = Tier.unknown;
    var token_start: ?usize = null;

    for (value, 0..) |byte, index| {
        if (isSeparator(byte)) {
            if (token_start) |start| {
                tier = maxTier(tier, classifyToken(value[start..index]));
                token_start = null;
            }
        } else if (token_start == null) {
            token_start = index;
        }
    }

    if (token_start) |start| tier = maxTier(tier, classifyToken(value[start..]));
    return tier;
}

pub fn classifyWithRules(value: []const u8, rules: Rules) Tier {
    var tier = classify(value);
    if (matchesAny(value, rules.dev)) tier = maxTier(tier, .dev);
    if (matchesAny(value, rules.staging)) tier = maxTier(tier, .staging);
    if (matchesAny(value, rules.prod)) tier = maxTier(tier, .prod);
    return tier;
}

pub fn rulesPathAlloc(allocator: std.mem.Allocator, home: ?[]const u8) !?[]u8 {
    const home_path = home orelse return null;
    return @as(?[]u8, try std.fmt.allocPrint(allocator, "{s}/.config/shisa/risk_tiers.toml", .{home_path}));
}

pub fn loadUserRulesAlloc(allocator: std.mem.Allocator, home: ?[]const u8) !?Rules {
    const path = (try rulesPathAlloc(allocator, home)) orelse return null;
    defer allocator.free(path);
    const source = std.fs.cwd().readFileAlloc(allocator, path, 256 * 1024) catch |err| switch (err) {
        error.FileNotFound => return null,
        else => return err,
    };
    defer allocator.free(source);
    return try parseRulesAlloc(allocator, source);
}

pub fn parseRulesAlloc(allocator: std.mem.Allocator, source: []const u8) !Rules {
    var parser = RuleParser{ .allocator = allocator, .source = source };
    return parser.parse();
}

pub fn tierName(tier: Tier) []const u8 {
    return switch (tier) {
        .unknown => "unknown",
        .dev => "dev",
        .staging => "staging",
        .prod => "prod",
    };
}

fn classifyToken(token: []const u8) Tier {
    if (asciiEql(token, "prod") or asciiEql(token, "production") or asciiEql(token, "live") or asciiEql(token, "prd")) return .prod;
    if (asciiEql(token, "stg") or asciiEql(token, "staging")) return .staging;
    if (asciiEql(token, "dev") or asciiEql(token, "sandbox")) return .dev;
    return .unknown;
}

fn matchesAny(value: []const u8, patterns: []const []const u8) bool {
    for (patterns) |pattern| {
        if (std.mem.indexOfScalar(u8, pattern, '*') != null) {
            if (globMatchIgnoreCase(value, pattern)) return true;
        } else if (containsToken(value, pattern)) {
            return true;
        }
    }
    return false;
}

fn containsToken(value: []const u8, pattern: []const u8) bool {
    var token_start: ?usize = null;
    for (value, 0..) |byte, index| {
        if (isSeparator(byte)) {
            if (token_start) |start| {
                if (asciiEql(value[start..index], pattern)) return true;
                token_start = null;
            }
        } else if (token_start == null) {
            token_start = index;
        }
    }
    if (token_start) |start| return asciiEql(value[start..], pattern);
    return false;
}

fn globMatchIgnoreCase(value: []const u8, pattern: []const u8) bool {
    return globMatchAt(value, 0, pattern, 0);
}

fn globMatchAt(value: []const u8, value_index: usize, pattern: []const u8, pattern_index: usize) bool {
    if (pattern_index == pattern.len) return value_index == value.len;
    if (pattern[pattern_index] == '*') {
        var next_value = value_index;
        while (next_value <= value.len) : (next_value += 1) {
            if (globMatchAt(value, next_value, pattern, pattern_index + 1)) return true;
        }
        return false;
    }
    if (value_index == value.len) return false;
    if (std.ascii.toLower(value[value_index]) != std.ascii.toLower(pattern[pattern_index])) return false;
    return globMatchAt(value, value_index + 1, pattern, pattern_index + 1);
}

const RuleParser = struct {
    allocator: std.mem.Allocator,
    source: []const u8,
    rules: Rules = .{},
    seen_dev: bool = false,
    seen_staging: bool = false,
    seen_prod: bool = false,

    fn parse(self: *RuleParser) !Rules {
        errdefer self.rules.deinit(self.allocator);
        var offset: usize = 0;
        while (offset <= self.source.len) {
            const rest = self.source[offset..];
            const line_len = std.mem.indexOfScalar(u8, rest, '\n') orelse rest.len;
            var line = rest[0..line_len];
            if (line.len > 0 and line[line.len - 1] == '\r') line = line[0 .. line.len - 1];
            try self.parseLine(line);
            offset += line_len + 1;
            if (offset > self.source.len) break;
        }
        const rules = self.rules;
        self.rules = .{};
        return rules;
    }

    fn parseLine(self: *RuleParser, raw_line: []const u8) !void {
        const line = std.mem.trim(u8, stripComment(raw_line), " \t\r\n");
        if (line.len == 0) return;
        const eq_index = std.mem.indexOfScalar(u8, line, '=') orelse return error.InvalidRules;
        const key = std.mem.trim(u8, line[0..eq_index], " \t");
        const value = std.mem.trim(u8, line[eq_index + 1 ..], " \t");
        if (std.mem.eql(u8, key, "dev")) {
            try markUnseen(&self.seen_dev);
            self.rules.dev = try parseStringArrayAlloc(self.allocator, value);
        } else if (std.mem.eql(u8, key, "staging")) {
            try markUnseen(&self.seen_staging);
            self.rules.staging = try parseStringArrayAlloc(self.allocator, value);
        } else if (std.mem.eql(u8, key, "prod")) {
            try markUnseen(&self.seen_prod);
            self.rules.prod = try parseStringArrayAlloc(self.allocator, value);
        } else {
            return error.InvalidRules;
        }
    }
};

fn parseStringArrayAlloc(allocator: std.mem.Allocator, value: []const u8) ![][]u8 {
    if (value.len < 2 or value[0] != '[' or value[value.len - 1] != ']') return error.InvalidRules;
    var out: std.ArrayList([]u8) = .empty;
    errdefer {
        for (out.items) |pattern| allocator.free(pattern);
        out.deinit(allocator);
    }

    var index: usize = 1;
    while (index < value.len - 1) {
        skipSpaces(value, &index);
        if (index >= value.len - 1) break;
        const parsed = try parseTomlStringAlloc(allocator, value, &index);
        out.append(allocator, parsed) catch |err| {
            allocator.free(parsed);
            return err;
        };
        skipSpaces(value, &index);
        if (index >= value.len - 1) break;
        if (value[index] != ',') return error.InvalidRules;
        index += 1;
    }

    return out.toOwnedSlice(allocator);
}

fn parseTomlStringAlloc(allocator: std.mem.Allocator, value: []const u8, index: *usize) ![]u8 {
    if (value[index.*] != '"') return error.InvalidRules;
    index.* += 1;
    var out: std.ArrayList(u8) = .empty;
    errdefer out.deinit(allocator);
    while (index.* < value.len) : (index.* += 1) {
        const byte = value[index.*];
        if (byte == '"') {
            index.* += 1;
            return out.toOwnedSlice(allocator);
        }
        if (byte == '\\') {
            index.* += 1;
            if (index.* >= value.len) return error.InvalidRules;
            switch (value[index.*]) {
                '"' => try out.append(allocator, '"'),
                '\\' => try out.append(allocator, '\\'),
                'n' => try out.append(allocator, '\n'),
                'r' => try out.append(allocator, '\r'),
                't' => try out.append(allocator, '\t'),
                else => return error.InvalidRules,
            }
        } else {
            try out.append(allocator, byte);
        }
    }
    return error.InvalidRules;
}

fn stripComment(line: []const u8) []const u8 {
    var in_string = false;
    var escaped = false;
    for (line, 0..) |byte, index| {
        if (escaped) {
            escaped = false;
            continue;
        }
        if (byte == '\\' and in_string) {
            escaped = true;
            continue;
        }
        if (byte == '"') {
            in_string = !in_string;
            continue;
        }
        if (byte == '#' and !in_string) return line[0..index];
    }
    return line;
}

fn skipSpaces(value: []const u8, index: *usize) void {
    while (index.* < value.len and std.ascii.isWhitespace(value[index.*])) : (index.* += 1) {}
}

fn markUnseen(seen: *bool) !void {
    if (seen.*) return error.InvalidRules;
    seen.* = true;
}

fn freePatterns(allocator: std.mem.Allocator, patterns: [][]u8) void {
    for (patterns) |pattern| allocator.free(pattern);
    allocator.free(patterns);
}

fn maxTier(left: Tier, right: Tier) Tier {
    return if (rank(right) > rank(left)) right else left;
}

fn rank(tier: Tier) u8 {
    return switch (tier) {
        .unknown => 0,
        .dev => 1,
        .staging => 2,
        .prod => 3,
    };
}

fn asciiEql(left: []const u8, right: []const u8) bool {
    return std.ascii.eqlIgnoreCase(left, right);
}

fn isSeparator(byte: u8) bool {
    return byte == '-' or byte == '_' or byte == '.' or byte == '/' or byte == ':' or byte == '@' or std.ascii.isWhitespace(byte);
}

test "classifies prod defaults" {
    try std.testing.expectEqual(Tier.prod, classify("prod"));
    try std.testing.expectEqual(Tier.prod, classify("production"));
    try std.testing.expectEqual(Tier.prod, classify("live"));
    try std.testing.expectEqual(Tier.prod, classify("team-prd-use1"));
}

test "classifies staging defaults" {
    try std.testing.expectEqual(Tier.staging, classify("api-stg"));
    try std.testing.expectEqual(Tier.staging, classify("staging/eu"));
}

test "classifies dev defaults" {
    try std.testing.expectEqual(Tier.dev, classify("dev"));
    try std.testing.expectEqual(Tier.dev, classify("sandbox-account"));
}

test "prod wins over lower tiers" {
    try std.testing.expectEqual(Tier.prod, classify("dev-prod"));
    try std.testing.expectEqual(Tier.prod, classify("staging-live"));
}

test "unknown when no default matches" {
    try std.testing.expectEqual(Tier.unknown, classify("personal"));
}

test "parses user rules" {
    var rules = try parseRulesAlloc(std.testing.allocator,
        \\prod = ["critical", "*-payments-*"]
        \\staging = ["preprod"]
        \\dev = ["local"]
        \\
    );
    defer rules.deinit(std.testing.allocator);

    try std.testing.expectEqual(Tier.prod, classifyWithRules("team-critical", rules));
    try std.testing.expectEqual(Tier.prod, classifyWithRules("eu-payments-main", rules));
    try std.testing.expectEqual(Tier.staging, classifyWithRules("preprod", rules));
    try std.testing.expectEqual(Tier.dev, classifyWithRules("local", rules));
}

test "user rules keep prod precedence" {
    var rules = try parseRulesAlloc(std.testing.allocator,
        \\dev = ["prod"]
        \\
    );
    defer rules.deinit(std.testing.allocator);

    try std.testing.expectEqual(Tier.prod, classifyWithRules("prod", rules));
}

test "resolves user rule path" {
    const path = (try rulesPathAlloc(std.testing.allocator, "/home/me")).?;
    defer std.testing.allocator.free(path);
    try std.testing.expectEqualStrings("/home/me/.config/shisa/risk_tiers.toml", path);
}

test "rejects invalid user rules" {
    try std.testing.expectError(error.InvalidRules, parseRulesAlloc(std.testing.allocator, "prod = [bad]\n"));
}
