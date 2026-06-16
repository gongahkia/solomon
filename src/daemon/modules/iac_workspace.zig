const std = @import("std");

pub const module_id = "iac_workspace";

const TerraformStateJson = struct {
    workspace: []const u8 = "",
    current_workspace: []const u8 = "",
};

const PulumiWorkspaceJson = struct {
    stack: []const u8 = "",
    currentStack: []const u8 = "",
    current_stack: []const u8 = "",
    workDir: []const u8 = "",
    workdir: []const u8 = "",
    work_dir: []const u8 = "",
};

pub fn terraformEnvironmentPathAlloc(allocator: std.mem.Allocator, cwd: []const u8) ![]u8 {
    return std.fmt.allocPrint(allocator, "{s}/.terraform/environment", .{cwd});
}

pub fn terraformBackendStatePathAlloc(allocator: std.mem.Allocator, cwd: []const u8) ![]u8 {
    return std.fmt.allocPrint(allocator, "{s}/.terraform/terraform.tfstate", .{cwd});
}

pub fn terraformRootStatePathAlloc(allocator: std.mem.Allocator, cwd: []const u8) ![]u8 {
    return std.fmt.allocPrint(allocator, "{s}/terraform.tfstate", .{cwd});
}

pub fn readTerraformWorkspaceAlloc(allocator: std.mem.Allocator, cwd: []const u8) !?[]u8 {
    const env_path = try terraformEnvironmentPathAlloc(allocator, cwd);
    defer allocator.free(env_path);
    if (try readTerraformEnvironmentAlloc(allocator, env_path)) |workspace| return workspace;

    const backend_state_path = try terraformBackendStatePathAlloc(allocator, cwd);
    defer allocator.free(backend_state_path);
    if (try readTerraformStateWorkspaceAlloc(allocator, backend_state_path)) |workspace| return workspace;

    const root_state_path = try terraformRootStatePathAlloc(allocator, cwd);
    defer allocator.free(root_state_path);
    return readTerraformStateWorkspaceAlloc(allocator, root_state_path);
}

pub fn readTerraformEnvironmentAlloc(allocator: std.mem.Allocator, path: []const u8) !?[]u8 {
    const source = std.fs.cwd().readFileAlloc(allocator, path, 4 * 1024) catch |err| switch (err) {
        error.FileNotFound => return null,
        else => return err,
    };
    defer allocator.free(source);
    return parseTerraformEnvironmentAlloc(allocator, source);
}

pub fn parseTerraformEnvironmentAlloc(allocator: std.mem.Allocator, source: []const u8) !?[]u8 {
    const workspace = std.mem.trim(u8, source, " \t\r\n");
    if (workspace.len == 0) return null;
    return @as(?[]u8, try allocator.dupe(u8, workspace));
}

pub fn readTerraformStateWorkspaceAlloc(allocator: std.mem.Allocator, path: []const u8) !?[]u8 {
    const source = std.fs.cwd().readFileAlloc(allocator, path, 1024 * 1024) catch |err| switch (err) {
        error.FileNotFound => return null,
        else => return err,
    };
    defer allocator.free(source);
    return parseTerraformStateWorkspaceAlloc(allocator, source);
}

pub fn parseTerraformStateWorkspaceAlloc(allocator: std.mem.Allocator, source: []const u8) !?[]u8 {
    var parsed = std.json.parseFromSlice(TerraformStateJson, allocator, source, .{ .ignore_unknown_fields = true }) catch return null;
    defer parsed.deinit();
    const current_workspace = std.mem.trim(u8, parsed.value.current_workspace, " \t\r\n");
    if (current_workspace.len != 0) return @as(?[]u8, try allocator.dupe(u8, current_workspace));
    const workspace = std.mem.trim(u8, parsed.value.workspace, " \t\r\n");
    if (workspace.len != 0) return @as(?[]u8, try allocator.dupe(u8, workspace));
    return null;
}

pub fn pulumiWorkspacesDirAlloc(allocator: std.mem.Allocator, home: ?[]const u8) !?[]u8 {
    const home_path = home orelse return null;
    return @as(?[]u8, try std.fmt.allocPrint(allocator, "{s}/.pulumi/workspaces", .{home_path}));
}

pub fn pulumiStackConfigPathAlloc(allocator: std.mem.Allocator, cwd: []const u8, stack: []const u8) !?[]u8 {
    const name = pulumiStackFileName(stack) orelse return null;
    return @as(?[]u8, try std.fmt.allocPrint(allocator, "{s}/Pulumi.{s}.yaml", .{ cwd, name }));
}

pub fn readPulumiStackAlloc(allocator: std.mem.Allocator, cwd: []const u8, home: ?[]const u8) !?[]u8 {
    const active_stack = (try readPulumiActiveStackAlloc(allocator, cwd, home)) orelse return null;
    defer allocator.free(active_stack);
    const stack_path = (try pulumiStackConfigPathAlloc(allocator, cwd, active_stack)) orelse return null;
    defer allocator.free(stack_path);
    if (!try fileExists(stack_path)) return null;
    const name = pulumiStackFileName(active_stack) orelse return null;
    return @as(?[]u8, try allocator.dupe(u8, name));
}

pub fn readPulumiActiveStackAlloc(allocator: std.mem.Allocator, cwd: []const u8, home: ?[]const u8) !?[]u8 {
    const dir_path = (try pulumiWorkspacesDirAlloc(allocator, home)) orelse return null;
    defer allocator.free(dir_path);
    var dir = std.fs.openDirAbsolute(dir_path, .{ .iterate = true }) catch |err| switch (err) {
        error.FileNotFound => return null,
        else => return err,
    };
    defer dir.close();

    var it = dir.iterate();
    while (try it.next()) |entry| {
        if (entry.kind != .file or !std.mem.endsWith(u8, entry.name, ".json")) continue;
        const source = dir.readFileAlloc(allocator, entry.name, 64 * 1024) catch continue;
        defer allocator.free(source);
        const stack = try parsePulumiActiveStackAlloc(allocator, source, cwd) orelse continue;
        return stack;
    }
    return null;
}

pub fn parsePulumiActiveStackAlloc(allocator: std.mem.Allocator, source: []const u8, cwd: []const u8) !?[]u8 {
    var parsed = std.json.parseFromSlice(PulumiWorkspaceJson, allocator, source, .{ .ignore_unknown_fields = true }) catch return null;
    defer parsed.deinit();
    const work_dir = pulumiWorkspaceDir(parsed.value) orelse return null;
    if (!std.mem.eql(u8, std.mem.trim(u8, work_dir, " \t\r\n"), cwd)) return null;
    const stack = pulumiWorkspaceStack(parsed.value) orelse return null;
    return @as(?[]u8, try allocator.dupe(u8, stack));
}

fn pulumiWorkspaceDir(value: PulumiWorkspaceJson) ?[]const u8 {
    const work_dir = std.mem.trim(u8, value.workDir, " \t\r\n");
    if (work_dir.len != 0) return work_dir;
    const workdir = std.mem.trim(u8, value.workdir, " \t\r\n");
    if (workdir.len != 0) return workdir;
    const work_dir_alt = std.mem.trim(u8, value.work_dir, " \t\r\n");
    if (work_dir_alt.len != 0) return work_dir_alt;
    return null;
}

fn pulumiWorkspaceStack(value: PulumiWorkspaceJson) ?[]const u8 {
    const stack = std.mem.trim(u8, value.stack, " \t\r\n");
    if (stack.len != 0) return stack;
    const current_stack = std.mem.trim(u8, value.currentStack, " \t\r\n");
    if (current_stack.len != 0) return current_stack;
    const current_stack_alt = std.mem.trim(u8, value.current_stack, " \t\r\n");
    if (current_stack_alt.len != 0) return current_stack_alt;
    return null;
}

fn pulumiStackFileName(stack: []const u8) ?[]const u8 {
    const trimmed = std.mem.trim(u8, stack, " \t\r\n");
    if (trimmed.len == 0) return null;
    if (std.mem.lastIndexOfScalar(u8, trimmed, '/')) |index| {
        if (index + 1 >= trimmed.len) return null;
        return trimmed[index + 1 ..];
    }
    return trimmed;
}

fn fileExists(path: []const u8) !bool {
    var file = std.fs.cwd().openFile(path, .{}) catch |err| switch (err) {
        error.FileNotFound => return false,
        else => return err,
    };
    file.close();
    return true;
}

test "parses terraform environment workspace" {
    const workspace = (try parseTerraformEnvironmentAlloc(std.testing.allocator, "prod\n")).?;
    defer std.testing.allocator.free(workspace);
    try std.testing.expectEqualStrings("prod", workspace);
}

test "parses terraform state workspace" {
    const workspace = (try parseTerraformStateWorkspaceAlloc(std.testing.allocator,
        \\{
        \\  "version": 4,
        \\  "current_workspace": "staging"
        \\}
    )).?;
    defer std.testing.allocator.free(workspace);
    try std.testing.expectEqualStrings("staging", workspace);
}

test "parses terraform state workspace fallback" {
    const workspace = (try parseTerraformStateWorkspaceAlloc(std.testing.allocator,
        \\{
        \\  "version": 4,
        \\  "workspace": "dev"
        \\}
    )).?;
    defer std.testing.allocator.free(workspace);
    try std.testing.expectEqualStrings("dev", workspace);
}

test "reads terraform environment before state" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-iac-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    const terraform_dir = try std.fmt.allocPrint(allocator, "{s}/.terraform", .{dir_path});
    defer allocator.free(terraform_dir);
    try std.fs.cwd().makePath(terraform_dir);

    const env_path = try terraformEnvironmentPathAlloc(allocator, dir_path);
    defer allocator.free(env_path);
    {
        var file = try std.fs.createFileAbsolute(env_path, .{});
        defer file.close();
        try file.writeAll("prod\n");
    }

    const state_path = try terraformBackendStatePathAlloc(allocator, dir_path);
    defer allocator.free(state_path);
    {
        var file = try std.fs.createFileAbsolute(state_path, .{});
        defer file.close();
        try file.writeAll("{\"current_workspace\":\"dev\"}");
    }

    const workspace = (try readTerraformWorkspaceAlloc(allocator, dir_path)).?;
    defer allocator.free(workspace);
    try std.testing.expectEqualStrings("prod", workspace);
}

test "reads terraform state fallback" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-iac-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    const terraform_dir = try std.fmt.allocPrint(allocator, "{s}/.terraform", .{dir_path});
    defer allocator.free(terraform_dir);
    try std.fs.cwd().makePath(terraform_dir);

    const state_path = try terraformBackendStatePathAlloc(allocator, dir_path);
    defer allocator.free(state_path);
    {
        var file = try std.fs.createFileAbsolute(state_path, .{});
        defer file.close();
        try file.writeAll("{\"current_workspace\":\"stage\"}");
    }

    const workspace = (try readTerraformWorkspaceAlloc(allocator, dir_path)).?;
    defer allocator.free(workspace);
    try std.testing.expectEqualStrings("stage", workspace);
}

test "parses pulumi active stack for cwd" {
    const stack = (try parsePulumiActiveStackAlloc(std.testing.allocator,
        \\{
        \\  "workDir": "/repo/infra",
        \\  "stack": "org/project/prod"
        \\}
    , "/repo/infra")).?;
    defer std.testing.allocator.free(stack);
    try std.testing.expectEqualStrings("org/project/prod", stack);
}

test "builds pulumi stack config path from qualified stack" {
    const path = (try pulumiStackConfigPathAlloc(std.testing.allocator, "/repo/infra", "org/project/prod")).?;
    defer std.testing.allocator.free(path);
    try std.testing.expectEqualStrings("/repo/infra/Pulumi.prod.yaml", path);
}

test "reads pulumi active stack with stack config" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-pulumi-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    const workspaces_dir = try std.fmt.allocPrint(allocator, "{s}/.pulumi/workspaces", .{dir_path});
    defer allocator.free(workspaces_dir);
    try std.fs.cwd().makePath(workspaces_dir);

    const stack_file = try std.fmt.allocPrint(allocator, "{s}/Pulumi.prod.yaml", .{dir_path});
    defer allocator.free(stack_file);
    {
        var file = try std.fs.createFileAbsolute(stack_file, .{});
        defer file.close();
        try file.writeAll("config: {}\n");
    }

    const workspace_file = try std.fmt.allocPrint(allocator, "{s}/project-workspace.json", .{workspaces_dir});
    defer allocator.free(workspace_file);
    const workspace_json = try std.fmt.allocPrint(allocator, "{{\"workDir\":\"{s}\",\"stack\":\"org/project/prod\"}}", .{dir_path});
    defer allocator.free(workspace_json);
    {
        var file = try std.fs.createFileAbsolute(workspace_file, .{});
        defer file.close();
        try file.writeAll(workspace_json);
    }

    const stack = (try readPulumiStackAlloc(allocator, dir_path, dir_path)).?;
    defer allocator.free(stack);
    try std.testing.expectEqualStrings("prod", stack);
}
