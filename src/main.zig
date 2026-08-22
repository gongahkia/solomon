const std = @import("std");
const cli_target = @import("cli/target.zig");

const version = "0.2.0-dev";

pub fn main() void {
    run() catch |err| {
        if (err != error.TargetContractNotVerified) {
            std.debug.print("shisa: {s}\n", .{@errorName(err)});
        }
        std.process.exit(1);
    };
}

fn run() !void {
    var gpa_impl = std.heap.GeneralPurposeAllocator(.{}){};
    defer _ = gpa_impl.deinit();
    const allocator = gpa_impl.allocator();

    const args = try std.process.argsAlloc(allocator);
    defer std.process.argsFree(allocator, args);

    if (args.len == 1 or std.mem.eql(u8, args[1], "--help") or std.mem.eql(u8, args[1], "-h")) {
        try std.fs.File.stdout().writeAll(help_text);
        return;
    }
    if (std.mem.eql(u8, args[1], "--version")) {
        try std.fs.File.stdout().writeAll("shisa " ++ version ++ "\n");
        return;
    }
    if (std.mem.eql(u8, args[1], "target")) {
        try cli_target.command(allocator, args[2..]);
        return;
    }

    try std.fs.File.stderr().writeAll("shisa: unknown command; run `shisa --help`\n");
    return error.UnknownCommand;
}

const help_text =
    \\usage: shisa <command> [options]
    \\
    \\Shisa verifies the actual local target before a direct infrastructure command starts.
    \\It does not activate contexts, manage credentials, or enforce remote policy.
    \\
    \\commands:
    \\  target       list, inspect, or verify-and-run target contracts
    \\
    \\options:
    \\  -h, --help    print help
    \\      --version  print version
    \\
;

test "smoke" {
    try std.testing.expect(true);
}
