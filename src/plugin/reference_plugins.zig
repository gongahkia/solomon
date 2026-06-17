const std = @import("std");
const lua = @import("lua.zig");

const reference_manifests = [_][]const u8{
    "examples/plugins/git/plugin.lua",
    "examples/plugins/language_versions/plugin.lua",
    "examples/plugins/kubernetes-context/plugin.lua",
    "examples/plugins/aws-profile/plugin.lua",
    "examples/plugins/a11y-live/plugin.lua",
    "examples/plugins/fossil/plugin.lua",
    "examples/plugins/pijul/plugin.lua",
    "examples/plugins/breezy/plugin.lua",
};

test "reference plugin manifests load in strict mode" {
    var runtime = lua.Runtime.initSandboxed(std.testing.allocator) catch |err| switch (err) {
        error.LuaUnavailable => return error.SkipZigTest,
        else => return err,
    };
    defer runtime.deinit();

    for (reference_manifests) |path| {
        const source = try std.fs.cwd().readFileAlloc(std.testing.allocator, path, 1024 * 1024);
        defer std.testing.allocator.free(source);
        var loaded = try runtime.loadManifestStrict(source);
        defer loaded.deinit(std.testing.allocator);
        try loaded.manifest.validate();
    }
}
