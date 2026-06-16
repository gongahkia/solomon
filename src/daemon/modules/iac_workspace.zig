const std = @import("std");

pub const module_id = "iac_workspace";

const TerraformStateJson = struct {
    workspace: []const u8 = "",
    current_workspace: []const u8 = "",
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
