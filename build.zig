const std = @import("std");

pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    const optimize = b.standardOptimizeOption(.{});
    const vcs_worktree_module = b.createModule(.{
        .root_source_file = b.path("src/vcs/worktree.zig"),
        .target = target,
        .optimize = optimize,
    });
    const vcs_worktree_debug_module = b.createModule(.{
        .root_source_file = b.path("src/vcs/worktree.zig"),
        .target = target,
        .optimize = .Debug,
    });
    const vcs_worktree_release_module = b.createModule(.{
        .root_source_file = b.path("src/vcs/worktree.zig"),
        .target = target,
        .optimize = .ReleaseFast,
    });

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
    daemon.root_module.addImport("vcs_worktree", vcs_worktree_module);
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
    debug_daemon.root_module.addImport("vcs_worktree", vcs_worktree_debug_module);
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
    release_daemon.root_module.addImport("vcs_worktree", vcs_worktree_release_module);
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
    const config_tests = b.addTest(.{
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/config.zig"),
            .target = target,
            .optimize = optimize,
        }),
    });
    const config_test_run = b.addRunArtifact(config_tests);
    const plugin_manifest_tests = b.addTest(.{
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/plugin/manifest.zig"),
            .target = target,
            .optimize = optimize,
        }),
    });
    const plugin_manifest_test_run = b.addRunArtifact(plugin_manifest_tests);
    const plugin_capability_tests = b.addTest(.{
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/plugin/capability.zig"),
            .target = target,
            .optimize = optimize,
        }),
    });
    const plugin_capability_test_run = b.addRunArtifact(plugin_capability_tests);
    const plugin_lua_tests = b.addTest(.{
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/plugin/lua.zig"),
            .target = target,
            .optimize = optimize,
        }),
    });
    const plugin_lua_test_run = b.addRunArtifact(plugin_lua_tests);
    const plugin_reference_tests = b.addTest(.{
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/plugin/reference_plugins.zig"),
            .target = target,
            .optimize = optimize,
        }),
    });
    const plugin_reference_test_run = b.addRunArtifact(plugin_reference_tests);
    const theme_builtin_tests = b.addTest(.{
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/theme/builtin.zig"),
            .target = target,
            .optimize = optimize,
        }),
    });
    const theme_builtin_test_run = b.addRunArtifact(theme_builtin_tests);
    const vcs_jj_tests = b.addTest(.{
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/vcs/jj.zig"),
            .target = target,
            .optimize = optimize,
        }),
    });
    const vcs_jj_test_run = b.addRunArtifact(vcs_jj_tests);
    const vcs_sl_tests = b.addTest(.{
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/vcs/sl.zig"),
            .target = target,
            .optimize = optimize,
        }),
    });
    const vcs_sl_test_run = b.addRunArtifact(vcs_sl_tests);
    const vcs_hg_tests = b.addTest(.{
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/vcs/hg.zig"),
            .target = target,
            .optimize = optimize,
        }),
    });
    const vcs_hg_test_run = b.addRunArtifact(vcs_hg_tests);
    const vcs_stack_tests = b.addTest(.{
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/vcs/stack.zig"),
            .target = target,
            .optimize = optimize,
        }),
    });
    const vcs_stack_test_run = b.addRunArtifact(vcs_stack_tests);
    const vcs_worktree_tests = b.addTest(.{
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/vcs/worktree.zig"),
            .target = target,
            .optimize = optimize,
        }),
    });
    const vcs_worktree_test_run = b.addRunArtifact(vcs_worktree_tests);
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
    const cache_tests = b.addTest(.{
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/daemon/cache.zig"),
            .target = target,
            .optimize = optimize,
        }),
    });
    const cache_test_run = b.addRunArtifact(cache_tests);
    const warmup_tests = b.addTest(.{
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/daemon/warmup.zig"),
            .target = target,
            .optimize = optimize,
        }),
    });
    const warmup_test_run = b.addRunArtifact(warmup_tests);
    const fsnotify_tests = b.addTest(.{
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/daemon/fsnotify.zig"),
            .target = target,
            .optimize = optimize,
        }),
    });
    const fsnotify_test_run = b.addRunArtifact(fsnotify_tests);
    const prompt_cache_tests = b.addTest(.{
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/daemon/prompt_cache.zig"),
            .target = target,
            .optimize = optimize,
        }),
    });
    const prompt_cache_test_run = b.addRunArtifact(prompt_cache_tests);
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
    const user_host_tests = b.addTest(.{
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/daemon/modules/user_host.zig"),
            .target = target,
            .optimize = optimize,
        }),
    });
    const user_host_test_run = b.addRunArtifact(user_host_tests);
    const cloud_ctx_tests = b.addTest(.{
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/daemon/modules/cloud_ctx.zig"),
            .target = target,
            .optimize = optimize,
        }),
    });
    const cloud_ctx_test_run = b.addRunArtifact(cloud_ctx_tests);
    const risk_tier_tests = b.addTest(.{
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/daemon/modules/risk_tier.zig"),
            .target = target,
            .optimize = optimize,
        }),
    });
    const risk_tier_test_run = b.addRunArtifact(risk_tier_tests);
    const region_drift_tests = b.addTest(.{
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/daemon/modules/region_drift.zig"),
            .target = target,
            .optimize = optimize,
        }),
    });
    const region_drift_test_run = b.addRunArtifact(region_drift_tests);
    const cost_glance_tests = b.addTest(.{
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/daemon/modules/cost_glance.zig"),
            .target = target,
            .optimize = optimize,
        }),
    });
    const cost_glance_test_run = b.addRunArtifact(cost_glance_tests);
    const prod_guard_tests = b.addTest(.{
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/daemon/modules/prod_guard.zig"),
            .target = target,
            .optimize = optimize,
        }),
    });
    const prod_guard_test_run = b.addRunArtifact(prod_guard_tests);
    const iam_whoami_tests = b.addTest(.{
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/daemon/modules/iam_whoami.zig"),
            .target = target,
            .optimize = optimize,
        }),
    });
    const iam_whoami_test_run = b.addRunArtifact(iam_whoami_tests);
    const iac_workspace_tests = b.addTest(.{
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/daemon/modules/iac_workspace.zig"),
            .target = target,
            .optimize = optimize,
        }),
    });
    const iac_workspace_test_run = b.addRunArtifact(iac_workspace_tests);
    const sso_expiry_tests = b.addTest(.{
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/daemon/modules/sso_expiry.zig"),
            .target = target,
            .optimize = optimize,
        }),
    });
    const sso_expiry_test_run = b.addRunArtifact(sso_expiry_tests);
    const time_tests = b.addTest(.{
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/daemon/modules/time.zig"),
            .target = target,
            .optimize = optimize,
        }),
    });
    const time_test_run = b.addRunArtifact(time_tests);
    const git_branch_tests = b.addTest(.{
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/daemon/modules/git_branch.zig"),
            .target = target,
            .optimize = optimize,
        }),
    });
    git_branch_tests.root_module.addImport("vcs_worktree", vcs_worktree_module);
    const git_branch_test_run = b.addRunArtifact(git_branch_tests);
    const language_versions_tests = b.addTest(.{
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/daemon/modules/language_versions.zig"),
            .target = target,
            .optimize = optimize,
        }),
    });
    const language_versions_test_run = b.addRunArtifact(language_versions_tests);
    const cmd_duration_tests = b.addTest(.{
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/daemon/modules/cmd_duration.zig"),
            .target = target,
            .optimize = optimize,
        }),
    });
    const cmd_duration_test_run = b.addRunArtifact(cmd_duration_tests);
    const daemon_json_tests = b.addTest(.{
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/daemon/json.zig"),
            .target = target,
            .optimize = optimize,
        }),
    });
    const daemon_json_test_run = b.addRunArtifact(daemon_json_tests);
    const dispatcher_tests = b.addTest(.{
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/daemon/dispatcher.zig"),
            .target = target,
            .optimize = optimize,
        }),
    });
    dispatcher_tests.root_module.addImport("vcs_worktree", vcs_worktree_module);
    const dispatcher_test_run = b.addRunArtifact(dispatcher_tests);
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
    server_tests.root_module.addImport("vcs_worktree", vcs_worktree_module);
    const server_test_run = b.addRunArtifact(server_tests);
    const zsh_integration = b.addSystemCommand(&.{ "bash", "test/integration/zsh_fake_socket.sh" });
    zsh_integration.step.dependOn(&debug_install.step);
    const bash_integration = b.addSystemCommand(&.{ "bash", "test/integration/bash_fake_socket.sh" });
    bash_integration.step.dependOn(&debug_install.step);
    const fish_integration = b.addSystemCommand(&.{ "bash", "test/integration/fish_fake_socket.sh" });
    fish_integration.step.dependOn(&debug_install.step);
    const nu_integration = b.addSystemCommand(&.{ "bash", "test/integration/nu_fake_socket.sh" });
    nu_integration.step.dependOn(&debug_install.step);
    const pwsh_integration = b.addSystemCommand(&.{ "bash", "test/integration/pwsh_fake_socket.sh" });
    pwsh_integration.step.dependOn(&debug_install.step);
    const starship_presets_import = b.addSystemCommand(&.{ "bash", "test/integration/starship_presets_import.sh" });
    starship_presets_import.step.dependOn(&debug_install.step);
    const prompt_snapshot = b.addSystemCommand(&.{ "bash", "test/integration/prompt_snapshot.sh" });
    prompt_snapshot.step.dependOn(&debug_install.step);
    prompt_snapshot.step.dependOn(&debug_daemon_install.step);
    const test_step = b.step("test", "Run unit tests");
    test_step.dependOn(&test_run.step);
    test_step.dependOn(&cli_test_run.step);
    test_step.dependOn(&config_test_run.step);
    test_step.dependOn(&plugin_manifest_test_run.step);
    test_step.dependOn(&plugin_capability_test_run.step);
    test_step.dependOn(&plugin_lua_test_run.step);
    test_step.dependOn(&plugin_reference_test_run.step);
    test_step.dependOn(&theme_builtin_test_run.step);
    test_step.dependOn(&vcs_jj_test_run.step);
    test_step.dependOn(&vcs_sl_test_run.step);
    test_step.dependOn(&vcs_hg_test_run.step);
    test_step.dependOn(&vcs_stack_test_run.step);
    test_step.dependOn(&vcs_worktree_test_run.step);
    test_step.dependOn(&lock_test_run.step);
    test_step.dependOn(&log_test_run.step);
    test_step.dependOn(&cache_test_run.step);
    test_step.dependOn(&warmup_test_run.step);
    test_step.dependOn(&fsnotify_test_run.step);
    test_step.dependOn(&prompt_cache_test_run.step);
    test_step.dependOn(&cwd_test_run.step);
    test_step.dependOn(&exit_status_test_run.step);
    test_step.dependOn(&jobs_test_run.step);
    test_step.dependOn(&user_host_test_run.step);
    test_step.dependOn(&cloud_ctx_test_run.step);
    test_step.dependOn(&risk_tier_test_run.step);
    test_step.dependOn(&region_drift_test_run.step);
    test_step.dependOn(&cost_glance_test_run.step);
    test_step.dependOn(&prod_guard_test_run.step);
    test_step.dependOn(&iam_whoami_test_run.step);
    test_step.dependOn(&iac_workspace_test_run.step);
    test_step.dependOn(&sso_expiry_test_run.step);
    test_step.dependOn(&time_test_run.step);
    test_step.dependOn(&git_branch_test_run.step);
    test_step.dependOn(&language_versions_test_run.step);
    test_step.dependOn(&cmd_duration_test_run.step);
    test_step.dependOn(&daemon_json_test_run.step);
    test_step.dependOn(&dispatcher_test_run.step);
    test_step.dependOn(&supervisor_test_run.step);
    test_step.dependOn(&proto_types_test_run.step);
    test_step.dependOn(&proto_frame_test_run.step);
    test_step.dependOn(&client_test_run.step);
    test_step.dependOn(&server_test_run.step);
    test_step.dependOn(&zsh_integration.step);
    test_step.dependOn(&bash_integration.step);
    test_step.dependOn(&fish_integration.step);
    test_step.dependOn(&nu_integration.step);
    test_step.dependOn(&pwsh_integration.step);
    test_step.dependOn(&starship_presets_import.step);
    test_step.dependOn(&prompt_snapshot.step);
}
