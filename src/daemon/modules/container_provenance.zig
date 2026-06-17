const std = @import("std");

pub const module_id = "container_provenance";
pub const docker_marker_path = "/.dockerenv";

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
    const provider = try allocator.dupe(u8, "docker");
    errdefer allocator.free(provider);
    return ContainerStatus{
        .provider = provider,
        .name = try allocator.dupe(u8, "docker"),
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
