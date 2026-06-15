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

    const daemon = b.addExecutable(.{
        .name = "shisad",
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/shisad.zig"),
            .target = target,
            .optimize = optimize,
        }),
    });
    b.installArtifact(daemon);

    const debug_exe = b.addExecutable(.{
        .name = "shisa",
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/main.zig"),
            .target = target,
            .optimize = .Debug,
        }),
    });
    const debug_install = b.addInstallArtifact(debug_exe, .{});
    const debug_daemon = b.addExecutable(.{
        .name = "shisad",
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/shisad.zig"),
            .target = target,
            .optimize = .Debug,
        }),
    });
    const debug_daemon_install = b.addInstallArtifact(debug_daemon, .{});
    const debug_step = b.step("debug", "Build debug binary");
    debug_step.dependOn(&debug_install.step);
    debug_step.dependOn(&debug_daemon_install.step);

    const release_exe = b.addExecutable(.{
        .name = "shisa",
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/main.zig"),
            .target = target,
            .optimize = .ReleaseFast,
        }),
    });
    const release_install = b.addInstallArtifact(release_exe, .{});
    const release_daemon = b.addExecutable(.{
        .name = "shisad",
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/shisad.zig"),
            .target = target,
            .optimize = .ReleaseFast,
        }),
    });
    const release_daemon_install = b.addInstallArtifact(release_daemon, .{});
    const release_step = b.step("release", "Build release binary");
    release_step.dependOn(&release_install.step);
    release_step.dependOn(&release_daemon_install.step);

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
    const cli_tests = b.addTest(.{
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/daemon/cli.zig"),
            .target = target,
            .optimize = optimize,
        }),
    });
    const cli_test_run = b.addRunArtifact(cli_tests);
    const lock_tests = b.addTest(.{
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/daemon/lock.zig"),
            .target = target,
            .optimize = optimize,
        }),
    });
    const lock_test_run = b.addRunArtifact(lock_tests);
    const log_tests = b.addTest(.{
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/daemon/log.zig"),
            .target = target,
            .optimize = optimize,
        }),
    });
    const log_test_run = b.addRunArtifact(log_tests);
    const cwd_tests = b.addTest(.{
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/daemon/modules/cwd.zig"),
            .target = target,
            .optimize = optimize,
        }),
    });
    const cwd_test_run = b.addRunArtifact(cwd_tests);
    const exit_status_tests = b.addTest(.{
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/daemon/modules/exit_status.zig"),
            .target = target,
            .optimize = optimize,
        }),
    });
    const exit_status_test_run = b.addRunArtifact(exit_status_tests);
    const jobs_tests = b.addTest(.{
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/daemon/modules/jobs.zig"),
            .target = target,
            .optimize = optimize,
        }),
    });
    const jobs_test_run = b.addRunArtifact(jobs_tests);
    const daemon_json_tests = b.addTest(.{
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/daemon/json.zig"),
            .target = target,
            .optimize = optimize,
        }),
    });
    const daemon_json_test_run = b.addRunArtifact(daemon_json_tests);
    const supervisor_tests = b.addTest(.{
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/supervisor.zig"),
            .target = target,
            .optimize = optimize,
        }),
    });
    const supervisor_test_run = b.addRunArtifact(supervisor_tests);
    const proto_types_tests = b.addTest(.{
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/proto/types.zig"),
            .target = target,
            .optimize = optimize,
        }),
    });
    const proto_types_test_run = b.addRunArtifact(proto_types_tests);
    const proto_frame_tests = b.addTest(.{
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/proto/frame.zig"),
            .target = target,
            .optimize = optimize,
        }),
    });
    const proto_frame_test_run = b.addRunArtifact(proto_frame_tests);
    const client_tests = b.addTest(.{
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/shisa-client.zig"),
            .target = target,
            .optimize = optimize,
        }),
    });
    const client_test_run = b.addRunArtifact(client_tests);
    const server_tests = b.addTest(.{
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/daemon/server.zig"),
            .target = target,
            .optimize = optimize,
        }),
    });
    const server_test_run = b.addRunArtifact(server_tests);
    const test_step = b.step("test", "Run unit tests");
    test_step.dependOn(&test_run.step);
    test_step.dependOn(&cli_test_run.step);
    test_step.dependOn(&lock_test_run.step);
    test_step.dependOn(&log_test_run.step);
    test_step.dependOn(&cwd_test_run.step);
    test_step.dependOn(&exit_status_test_run.step);
    test_step.dependOn(&jobs_test_run.step);
    test_step.dependOn(&daemon_json_test_run.step);
    test_step.dependOn(&supervisor_test_run.step);
    test_step.dependOn(&proto_types_test_run.step);
    test_step.dependOn(&proto_frame_test_run.step);
    test_step.dependOn(&client_test_run.step);
    test_step.dependOn(&server_test_run.step);
}
