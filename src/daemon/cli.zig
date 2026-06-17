const std = @import("std");

pub const Config = struct {
    daemonize: bool = true,
    help: bool = false,
    health: bool = false,
    metrics: bool = false,
    prometheus: bool = false,
    version: bool = false,
    socket_path: ?[]const u8 = null,
    log_path: ?[]const u8 = null,
};

pub const ParseError = error{
    MissingValue,
    UnknownArgument,
};

pub fn parse(args: []const []const u8) ParseError!Config {
    var config = Config{};
    var i: usize = 0;

    while (i < args.len) : (i += 1) {
        const arg = args[i];

        if (std.mem.eql(u8, arg, "--help") or std.mem.eql(u8, arg, "-h")) {
            config.help = true;
        } else if (std.mem.eql(u8, arg, "--health")) {
            config.health = true;
        } else if (std.mem.eql(u8, arg, "--metrics")) {
            config.metrics = true;
        } else if (std.mem.eql(u8, arg, "--prometheus")) {
            config.prometheus = true;
        } else if (std.mem.eql(u8, arg, "--version")) {
            config.version = true;
        } else if (std.mem.eql(u8, arg, "--foreground")) {
            config.daemonize = false;
        } else if (std.mem.eql(u8, arg, "--daemonize")) {
            config.daemonize = true;
        } else if (std.mem.eql(u8, arg, "--socket")) {
            config.socket_path = try nextValue(args, &i);
        } else if (std.mem.startsWith(u8, arg, "--socket=")) {
            config.socket_path = arg["--socket=".len..];
        } else if (std.mem.eql(u8, arg, "--log")) {
            config.log_path = try nextValue(args, &i);
        } else if (std.mem.startsWith(u8, arg, "--log=")) {
            config.log_path = arg["--log=".len..];
        } else {
            return error.UnknownArgument;
        }
    }

    return config;
}

fn nextValue(args: []const []const u8, index: *usize) ParseError![]const u8 {
    if (index.* + 1 >= args.len) return error.MissingValue;
    index.* += 1;
    return args[index.*];
}

test "defaults to daemonizing" {
    const config = try parse(&.{});
    try std.testing.expect(config.daemonize);
    try std.testing.expect(!config.help);
    try std.testing.expect(!config.health);
    try std.testing.expect(!config.metrics);
    try std.testing.expect(!config.prometheus);
    try std.testing.expect(!config.version);
}

test "parses admin flags" {
    const args = [_][]const u8{ "--health", "--metrics", "--prometheus" };
    const config = try parse(args[0..]);
    try std.testing.expect(config.health);
    try std.testing.expect(config.metrics);
    try std.testing.expect(config.prometheus);
}

test "parses foreground and paths" {
    const args = [_][]const u8{ "--foreground", "--socket", "/tmp/shisa.sock", "--log=/tmp/shisad.log" };
    const config = try parse(args[0..]);
    try std.testing.expect(!config.daemonize);
    try std.testing.expectEqualStrings("/tmp/shisa.sock", config.socket_path.?);
    try std.testing.expectEqualStrings("/tmp/shisad.log", config.log_path.?);
}

test "rejects missing values" {
    const args = [_][]const u8{"--socket"};
    try std.testing.expectError(error.MissingValue, parse(args[0..]));
}

test "rejects unknown arguments" {
    const args = [_][]const u8{"--wat"};
    try std.testing.expectError(error.UnknownArgument, parse(args[0..]));
}
