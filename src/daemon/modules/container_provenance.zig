const std = @import("std");

pub const module_id = "container_provenance";
pub const docker_marker_path = "/.dockerenv";
pub const podman_cgroup_path = "/proc/1/cgroup";
pub const devcontainer_env_var = "REMOTE_CONTAINERS";
pub const nix_shell_env_var = "IN_NIX_SHELL";
pub const distrobox_container_id_env_var = "CONTAINER_ID";
pub const toolbx_marker_path = "/run/.toolbxenv";
pub const toolbox_marker_path = "/run/.toolboxenv";

pub const ContainerStatus = struct {
    provider: []u8,
    name: []u8,

    pub fn deinit(self: *ContainerStatus, allocator: std.mem.Allocator) void {
        allocator.free(self.provider);
        allocator.free(self.name);
        self.* = undefined;
    }
};

pub fn detectDockerAlloc(allocator: std.mem.Allocator, marker_path: []const u8) !?ContainerStatus {
    if (!try pathExists(marker_path)) return null;
    return try containerStatusAlloc(allocator, "docker", "docker");
}

pub fn detectPodmanAlloc(allocator: std.mem.Allocator, cgroup_path: []const u8) !?ContainerStatus {
    var file = std.fs.openFileAbsolute(cgroup_path, .{}) catch |err| switch (err) {
        error.FileNotFound => return null,
        else => return err,
    };
    defer file.close();
    const cgroup = try file.readToEndAlloc(allocator, 64 * 1024);
    defer allocator.free(cgroup);
    return detectPodmanFromCgroupAlloc(allocator, cgroup);
}

pub fn detectPodmanFromCgroupAlloc(allocator: std.mem.Allocator, cgroup: []const u8) !?ContainerStatus {
    if (std.mem.indexOf(u8, cgroup, "libpod") == null and std.mem.indexOf(u8, cgroup, "podman") == null) return null;
    return try containerStatusAlloc(allocator, "podman", "podman");
}

pub fn detectDevcontainerEnvAlloc(allocator: std.mem.Allocator) !?ContainerStatus {
    const value = std.process.getEnvVarOwned(allocator, devcontainer_env_var) catch |err| switch (err) {
        error.EnvironmentVariableNotFound => return null,
        else => return err,
    };
    defer allocator.free(value);
    return detectDevcontainerAlloc(allocator, value);
}

pub fn detectDevcontainerAlloc(allocator: std.mem.Allocator, remote_containers: ?[]const u8) !?ContainerStatus {
    const value = remote_containers orelse return null;
    if (std.mem.trim(u8, value, " \t\r\n").len == 0) return null;
    return try containerStatusAlloc(allocator, "devcontainer", "devcontainer");
}

pub fn detectNixShellEnvAlloc(allocator: std.mem.Allocator) !?ContainerStatus {
    const value = std.process.getEnvVarOwned(allocator, nix_shell_env_var) catch |err| switch (err) {
        error.EnvironmentVariableNotFound => return null,
        else => return err,
    };
    defer allocator.free(value);
    return detectNixShellAlloc(allocator, value);
}

pub fn detectNixShellAlloc(allocator: std.mem.Allocator, in_nix_shell: ?[]const u8) !?ContainerStatus {
    const value = in_nix_shell orelse return null;
    if (std.mem.trim(u8, value, " \t\r\n").len == 0) return null;
    return try containerStatusAlloc(allocator, "nix", "shell");
}

pub fn detectDistroboxEnvAlloc(allocator: std.mem.Allocator) !?ContainerStatus {
    const value = std.process.getEnvVarOwned(allocator, distrobox_container_id_env_var) catch |err| switch (err) {
        error.EnvironmentVariableNotFound => return null,
        else => return err,
    };
    defer allocator.free(value);
    return detectDistroboxAlloc(allocator, value);
}

pub fn detectDistroboxAlloc(allocator: std.mem.Allocator, container_id: ?[]const u8) !?ContainerStatus {
    const value = container_id orelse return null;
    const name = std.mem.trim(u8, value, " \t\r\n");
    if (name.len == 0) return null;
    return try containerStatusAlloc(allocator, "distrobox", name);
}

pub fn detectToolbxDefaultAlloc(allocator: std.mem.Allocator) !?ContainerStatus {
    if (try detectToolbxAlloc(allocator, toolbx_marker_path)) |status| return status;
    return detectToolbxAlloc(allocator, toolbox_marker_path);
}

pub fn detectToolbxAlloc(allocator: std.mem.Allocator, marker_path: []const u8) !?ContainerStatus {
    if (!try pathExists(marker_path)) return null;
    return try containerStatusAlloc(allocator, "toolbx", "toolbox");
}

fn containerStatusAlloc(allocator: std.mem.Allocator, provider: []const u8, name: []const u8) !ContainerStatus {
    const provider_copy = try allocator.dupe(u8, provider);
    errdefer allocator.free(provider_copy);
    return ContainerStatus{
        .provider = provider_copy,
        .name = try allocator.dupe(u8, name),
    };
}

fn pathExists(path: []const u8) !bool {
    std.fs.cwd().access(path, .{}) catch |err| switch (err) {
        error.FileNotFound => return false,
        else => return err,
    };
    return true;
}

test "detects docker marker" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-container-docker-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);
    const marker = try std.fmt.allocPrint(allocator, "{s}/.dockerenv", .{dir_path});
    defer allocator.free(marker);
    {
        var file = try std.fs.createFileAbsolute(marker, .{});
        defer file.close();
        try file.writeAll("");
    }
    var status = (try detectDockerAlloc(allocator, marker)).?;
    defer status.deinit(allocator);
    try std.testing.expectEqualStrings("docker", status.provider);
    try std.testing.expectEqualStrings("docker", status.name);
}

test "ignores missing docker marker" {
    try std.testing.expect(try detectDockerAlloc(std.testing.allocator, "/tmp/shisa-missing-dockerenv") == null);
}

test "detects podman cgroup" {
    var status = (try detectPodmanFromCgroupAlloc(std.testing.allocator, "0::/machine.slice/libpod-8fdc.scope\n")).?;
    defer status.deinit(std.testing.allocator);
    try std.testing.expectEqualStrings("podman", status.provider);
    try std.testing.expectEqualStrings("podman", status.name);
}

test "detects podman cgroupfs parent" {
    var status = (try detectPodmanFromCgroupAlloc(std.testing.allocator, "1:name=systemd:/libpod_parent/libpod-8fdc/ctr\n")).?;
    defer status.deinit(std.testing.allocator);
    try std.testing.expectEqualStrings("podman", status.provider);
    try std.testing.expectEqualStrings("podman", status.name);
}

test "ignores unrelated cgroup" {
    try std.testing.expect(try detectPodmanFromCgroupAlloc(std.testing.allocator, "0::/user.slice/user-501.slice/session-1.scope\n") == null);
}

test "detects devcontainer env" {
    var status = (try detectDevcontainerAlloc(std.testing.allocator, "true")).?;
    defer status.deinit(std.testing.allocator);
    try std.testing.expectEqualStrings("devcontainer", status.provider);
    try std.testing.expectEqualStrings("devcontainer", status.name);
}

test "ignores empty devcontainer env" {
    try std.testing.expect(try detectDevcontainerAlloc(std.testing.allocator, " \n") == null);
    try std.testing.expect(try detectDevcontainerAlloc(std.testing.allocator, null) == null);
}

test "detects nix shell env" {
    var status = (try detectNixShellAlloc(std.testing.allocator, "pure")).?;
    defer status.deinit(std.testing.allocator);
    try std.testing.expectEqualStrings("nix", status.provider);
    try std.testing.expectEqualStrings("shell", status.name);
}

test "ignores empty nix shell env" {
    try std.testing.expect(try detectNixShellAlloc(std.testing.allocator, " \n") == null);
    try std.testing.expect(try detectNixShellAlloc(std.testing.allocator, null) == null);
}

test "detects distrobox env" {
    var status = (try detectDistroboxAlloc(std.testing.allocator, "dev-fedora")).?;
    defer status.deinit(std.testing.allocator);
    try std.testing.expectEqualStrings("distrobox", status.provider);
    try std.testing.expectEqualStrings("dev-fedora", status.name);
}

test "ignores empty distrobox env" {
    try std.testing.expect(try detectDistroboxAlloc(std.testing.allocator, " \n") == null);
    try std.testing.expect(try detectDistroboxAlloc(std.testing.allocator, null) == null);
}

test "detects toolbx marker" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-toolbx-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);
    const marker = try std.fmt.allocPrint(allocator, "{s}/.toolbxenv", .{dir_path});
    defer allocator.free(marker);
    {
        var file = try std.fs.createFileAbsolute(marker, .{});
        defer file.close();
        try file.writeAll("");
    }
    var status = (try detectToolbxAlloc(allocator, marker)).?;
    defer status.deinit(allocator);
    try std.testing.expectEqualStrings("toolbx", status.provider);
    try std.testing.expectEqualStrings("toolbox", status.name);
}

test "ignores missing toolbx marker" {
    try std.testing.expect(try detectToolbxAlloc(std.testing.allocator, "/tmp/shisa-missing-toolbxenv") == null);
}
