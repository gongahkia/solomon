const std = @import("std");

pub const module_id = "risk_tier";

pub const Tier = enum {
    unknown,
    dev,
    staging,
    prod,
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
