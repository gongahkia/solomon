const std = @import("std");

pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    const optimize = b.standardOptimizeOption(.{});

    const exe = b.addExecutable(.{
        .name = "shisa",
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/main.zig"),
            .target = target,
            .optimize = optimize,
        }),
    });
    b.installArtifact(exe);

    const debug_exe = b.addExecutable(.{
        .name = "shisa",
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/main.zig"),
            .target = target,
            .optimize = .Debug,
        }),
    });
    const debug_install = b.addInstallArtifact(debug_exe, .{});
    const debug_step = b.step("debug", "Build debug binary");
    debug_step.dependOn(&debug_install.step);

    const release_exe = b.addExecutable(.{
        .name = "shisa",
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/main.zig"),
            .target = target,
            .optimize = .ReleaseFast,
        }),
    });
    const release_install = b.addInstallArtifact(release_exe, .{});
    const release_step = b.step("release", "Build release binary");
    release_step.dependOn(&release_install.step);

    const bench_exe = b.addExecutable(.{
        .name = "shisa-bench",
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/bench.zig"),
            .target = target,
            .optimize = .ReleaseFast,
        }),
    });
    const bench_run = b.addRunArtifact(bench_exe);
    const bench_step = b.step("bench", "Run benchmark skeleton");
    bench_step.dependOn(&bench_run.step);

    const run_cmd = b.addRunArtifact(exe);
    if (b.args) |args| run_cmd.addArgs(args);
    const run_step = b.step("run", "Run shisa");
    run_step.dependOn(&run_cmd.step);

    const tests = b.addTest(.{
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/main.zig"),
            .target = target,
            .optimize = optimize,
        }),
    });
    const test_run = b.addRunArtifact(tests);
    const test_step = b.step("test", "Run unit tests");
    test_step.dependOn(&test_run.step);
}
