const std = @import("std");

pub const module_id = "container_provenance";
pub const docker_marker_path = "/.dockerenv";
pub const podman_cgroup_path = "/proc/1/cgroup";
pub const devcontainer_env_var = "REMOTE_CONTAINERS";

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
