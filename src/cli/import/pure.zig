const std = @import("std");
const common = @import("common.zig");

const ImportPlan = common.ImportPlan;
const parseImportArgs = common.parseImportArgs;
const applyImportPlan = common.applyImportPlan;
const collectUnmappedKeys = common.collectUnmappedKeys;

pub fn importPureCmd(allocator: std.mem.Allocator, args: []const []const u8) !void {
    const options = try parseImportArgs(args, false);
    var plan = try importPurePlanAlloc(allocator);
    defer plan.deinit(allocator);
    try applyImportPlan(allocator, &plan, options);
}

fn importPurePlanAlloc(allocator: std.mem.Allocator) !ImportPlan {
    const output = try pureConfigAlloc(allocator);
    var plan = ImportPlan{
        .target_toml = output,
        .source_name = "Pure",
        .docs_path = "docs/migration-pure.md",
    };
    errdefer plan.deinit(allocator);
    try collectUnmappedKeys(allocator, &plan);
    return plan;
}

fn pureConfigAlloc(allocator: std.mem.Allocator) ![]u8 {
    return try allocator.dupe(u8,
        \\version = 1
        \\theme = "pure"
        \\
        \\[prompt]
        \\modules = ["cwd", "git_branch", "exit_status", "cmd_duration", "jobs", "user_host"]
        \\
        \\[modules.cmd_duration]
        \\threshold_ms = 5000
        \\
        \\[modules.user_host]
        \\mode = "ssh"
        \\
    );
}

test "imports pure preset config" {
    const output = try pureConfigAlloc(std.testing.allocator);
    defer std.testing.allocator.free(output);

    try std.testing.expect(std.mem.indexOf(u8, output, "theme = \"pure\"") != null);
    try std.testing.expect(std.mem.indexOf(u8, output, "modules = [\"cwd\", \"git_branch\", \"exit_status\", \"cmd_duration\", \"jobs\", \"user_host\"]") != null);
    try std.testing.expect(std.mem.indexOf(u8, output, "threshold_ms = 5000") != null);
    try std.testing.expect(std.mem.indexOf(u8, output, "mode = \"ssh\"") != null);
}
