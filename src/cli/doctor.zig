const std = @import("std");
const builtin = @import("builtin");
const cli_config = @import("config.zig");
const cli_util = @import("util.zig");
const client = @import("../shisa-client.zig");
const daemon_json = @import("../daemon/json.zig");
const fsnotify = @import("../daemon/fsnotify.zig");
const prompt_payload = @import("prompt_payload.zig");
const paths = @import("../daemon/paths.zig");
const socket_security = @import("../daemon/socket_security.zig");
const plugin_lua = @import("../plugin/lua.zig");
const plugin_manifest = @import("../plugin/manifest.zig");
const proto = @import("../proto/types.zig");
const redact = @import("../redact.zig");
const shisa_config = @import("../config.zig");
const vpn_status_module = @import("../daemon/modules/vpn_status.zig");

const DoctorConfig = struct {
    socket_path: ?[]const u8 = null,
    fix: bool = false,
    yes: bool = false,
    lint: bool = false,
    json: bool = false,
    list_checks: bool = false,
    online: bool = false,
    only: ?[]const u8 = null,
    skip: ?[]const u8 = null,
    report_path: ?[]const u8 = null,
    severity_min: Severity = .warning,
};

const DoctorContext = struct {
    socket_path: []const u8,
    socket_status: []const u8,
    daemon_status: []const u8,
    config_dir: []const u8,
    config_dir_permissions: []const u8,
    shell_hook_status: []const u8,
    nerd_font_status: []const u8,
};

const DoctorIssue = struct {
    id: []const u8,
    message: []const u8,
    fix: *const fn (std.mem.Allocator, DoctorContext) anyerror!void,
};

const Severity = enum(u8) {
    info = 0,
    warning = 1,
    @"error" = 2,
};

const DoctorFinding = struct {
    id: []const u8,
    severity: Severity,
    category: []const u8 = "general",
    message: []const u8,
    detail: ?[]const u8 = null,
    evidence: ?[]const u8 = null,
    path: ?[]const u8 = null,
    command: ?[]const u8 = null,
    fix_hint: ?[]const u8 = null,
    fixable: bool = false,
    docs_url: ?[]const u8 = null,
};

const DoctorLintResult = struct {
    output: []u8,
    finding_count: usize,
};

const DoctorSummary = struct {
    info: usize = 0,
    warning: usize = 0,
    @"error": usize = 0,
};

const DoctorCheck = struct {
    id: []const u8,
    category: []const u8,
    online: bool = false,
    docs_url: []const u8,
};

const DeprecationRule = struct {
    kind: []const u8,
    pattern: []const u8,
    replacement: []const u8,
    since: []const u8,
    remove_before: []const u8,
};

const active_deprecation_rules = [_]DeprecationRule{};

const doctor_checks = [_]DoctorCheck{
    .{ .id = "install/zig-version", .category = "install", .docs_url = "docs/doctor.md#install" },
    .{ .id = "install/binary-set", .category = "install", .docs_url = "docs/doctor.md#install" },
    .{ .id = "install/path-shadowing", .category = "install", .docs_url = "docs/doctor.md#install" },
    .{ .id = "config/unreadable", .category = "config", .docs_url = "docs/doctor.md#config" },
    .{ .id = "config/invalid", .category = "config", .docs_url = "docs/doctor.md#config" },
    .{ .id = "config/dir-permissions", .category = "config", .docs_url = "docs/doctor.md#config" },
    .{ .id = "config/deprecations", .category = "config", .docs_url = "docs/doctor.md#config" },
    .{ .id = "daemon/not-running", .category = "daemon", .docs_url = "docs/doctor.md#daemon" },
    .{ .id = "daemon/stale-socket", .category = "daemon", .docs_url = "docs/doctor.md#daemon" },
    .{ .id = "daemon/already-running", .category = "daemon", .docs_url = "docs/doctor.md#daemon" },
    .{ .id = "daemon/socket-permissions", .category = "daemon", .docs_url = "docs/doctor.md#daemon" },
    .{ .id = "daemon/socket-mismatch", .category = "daemon", .docs_url = "docs/doctor.md#daemon" },
    .{ .id = "daemon/non-default-socket", .category = "daemon", .docs_url = "docs/doctor.md#daemon" },
    .{ .id = "daemon/protocol", .category = "daemon", .docs_url = "docs/doctor.md#daemon" },
    .{ .id = "daemon/metrics", .category = "daemon", .docs_url = "docs/doctor.md#daemon" },
    .{ .id = "daemon/log-warnings", .category = "daemon", .docs_url = "docs/doctor.md#daemon" },
    .{ .id = "shell/hook-missing", .category = "shell", .docs_url = "docs/doctor.md#shell" },
    .{ .id = "shell/hook-duplicates", .category = "shell", .docs_url = "docs/doctor.md#shell" },
    .{ .id = "shell/bin-missing", .category = "shell", .docs_url = "docs/doctor.md#shell" },
    .{ .id = "terminal/nerd-font", .category = "terminal", .docs_url = "docs/doctor.md#terminal" },
    .{ .id = "terminal/unknown", .category = "terminal", .docs_url = "docs/doctor.md#terminal" },
    .{ .id = "prompt/async-pending", .category = "prompt", .docs_url = "docs/doctor.md#prompt" },
    .{ .id = "prompt/render-sample", .category = "prompt", .docs_url = "docs/doctor.md#prompt" },
    .{ .id = "modules/vpn-active", .category = "modules", .docs_url = "docs/doctor.md#modules" },
    .{ .id = "modules/git", .category = "modules", .docs_url = "docs/doctor.md#modules" },
    .{ .id = "modules/language-tools", .category = "modules", .docs_url = "docs/doctor.md#modules" },
    .{ .id = "modules/cloud-cache", .category = "modules", .docs_url = "docs/doctor.md#modules" },
    .{ .id = "plugins/runtime", .category = "plugins", .docs_url = "docs/doctor.md#plugins" },
    .{ .id = "plugins/manifests", .category = "plugins", .docs_url = "docs/doctor.md#plugins" },
    .{ .id = "platform/runtime-dir", .category = "platform", .docs_url = "docs/doctor.md#platform" },
    .{ .id = "platform/fsnotify", .category = "platform", .docs_url = "docs/doctor.md#platform" },
    .{ .id = "performance/prompt-budget", .category = "performance", .docs_url = "docs/doctor.md#performance" },
    .{ .id = "security/permissions", .category = "security", .docs_url = "docs/doctor.md#security" },
    .{ .id = "tests/optional-prereqs", .category = "tests", .docs_url = "docs/doctor.md#tests" },
    .{ .id = "release/packaging", .category = "release", .docs_url = "docs/doctor.md#release" },
    .{ .id = "release/online", .category = "release", .online = true, .docs_url = "docs/doctor.md#release" },
};

const doctor_help_text =
    \\usage: shisa doctor [--socket PATH] [--fix [--yes]] [--lint] [--json] [--severity-min LEVEL]
    \\                    [--list-checks] [--only IDS] [--skip IDS] [--online] [--report PATH]
    \\
    \\options:
    \\  --socket <path>        check a non-default daemon socket
    \\  --fix                  apply available fixes interactively
    \\  --yes, -y              apply fixes without prompting
    \\  --lint                 read-only diagnostics with stable finding ids
    \\  --json                 emit lint findings as JSON; implies --lint
    \\  --severity-min LEVEL   info, warning, or error; default warning
    \\  --list-checks          list doctor checks and exit
    \\  --only IDS             comma-separated finding/check ids to run
    \\  --skip IDS             comma-separated finding/check ids to skip
    \\  --online               include explicit network/release checks
    \\  --report PATH          write a redacted doctor report JSON
    \\
;

pub fn command(allocator: std.mem.Allocator, args: []const []const u8) !void {
    commandInner(allocator, args) catch |err| {
        try doctorStderrFmt(allocator, "shisa doctor: {s}\n", .{@errorName(err)});
        std.process.exit(2);
    };
}

fn commandInner(allocator: std.mem.Allocator, args: []const []const u8) !void {
    if (args.len == 1 and (std.mem.eql(u8, args[0], "--help") or std.mem.eql(u8, args[0], "-h"))) {
        try std.fs.File.stdout().writeAll(doctor_help_text);
        return;
    }
    const config = try parseDoctorArgs(args);
    const socket_path = if (config.socket_path) |path| path else try paths.defaultSocketPath(allocator);
    defer if (config.socket_path == null) allocator.free(socket_path);

    if (config.list_checks) {
        const output = try doctorChecksListAlloc(allocator, config);
        defer allocator.free(output);
        try std.fs.File.stdout().writeAll(output);
        return;
    }

    if (config.lint or config.json) {
        const result = try doctorLintOutputAlloc(allocator, socket_path, config);
        defer allocator.free(result.output);
        try std.fs.File.stdout().writeAll(result.output);
        if (config.report_path) |path| try writeDoctorReport(allocator, path, socket_path, config);
        if (result.finding_count != 0) std.process.exit(1);
        return;
    }

    const output = try doctorOutputAlloc(allocator, socket_path, config);
    defer allocator.free(output);
    try std.fs.File.stdout().writeAll(output);
    if (config.report_path) |path| try writeDoctorReport(allocator, path, socket_path, config);
    if (config.fix) try applyDoctorFixes(allocator, socket_path, config.yes);
}

fn parseDoctorArgs(args: []const []const u8) !DoctorConfig {
    var config = DoctorConfig{};
    var i: usize = 0;
    while (i < args.len) : (i += 1) {
        if (std.mem.eql(u8, args[i], "--socket")) {
            config.socket_path = try cli_util.nextValue(args, &i);
        } else if (std.mem.eql(u8, args[i], "--fix")) {
            config.fix = true;
        } else if (std.mem.eql(u8, args[i], "--yes") or std.mem.eql(u8, args[i], "-y")) {
            config.yes = true;
        } else if (std.mem.eql(u8, args[i], "--lint")) {
            config.lint = true;
        } else if (std.mem.eql(u8, args[i], "--json")) {
            config.json = true;
            config.lint = true;
        } else if (std.mem.eql(u8, args[i], "--severity-min")) {
            config.severity_min = parseSeverity(try cli_util.nextValue(args, &i)) orelse return error.InvalidSeverity;
        } else if (std.mem.eql(u8, args[i], "--list-checks")) {
            config.list_checks = true;
        } else if (std.mem.eql(u8, args[i], "--online")) {
            config.online = true;
        } else if (std.mem.eql(u8, args[i], "--only")) {
            config.only = try cli_util.nextValue(args, &i);
        } else if (std.mem.eql(u8, args[i], "--skip")) {
            config.skip = try cli_util.nextValue(args, &i);
        } else if (std.mem.eql(u8, args[i], "--report")) {
            config.report_path = try cli_util.nextValue(args, &i);
        } else {
            return error.UnknownDoctorArgument;
        }
    }
    return config;
}

fn doctorChecksListAlloc(allocator: std.mem.Allocator, config: DoctorConfig) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);
    try out.appendSlice(allocator, "id\tcategory\tmode\tdocs\n");
    for (doctor_checks) |check| {
        if (!checkAllowed(config, check.id)) continue;
        try cli_util.appendFmt(allocator, &out, "{s}\t{s}\t{s}\t{s}\n", .{ check.id, check.category, if (check.online) "online" else "local", check.docs_url });
    }
    return out.toOwnedSlice(allocator);
}

fn checkAllowed(config: DoctorConfig, id: []const u8) bool {
    if (config.only) |ids| {
        if (!csvContains(ids, id)) return false;
    }
    if (config.skip) |ids| {
        if (csvContains(ids, id)) return false;
    }
    return true;
}

fn csvContains(csv: []const u8, needle: []const u8) bool {
    var it = std.mem.splitScalar(u8, csv, ',');
    while (it.next()) |raw| {
        const value = std.mem.trim(u8, raw, " \t\r\n");
        if (std.mem.eql(u8, value, needle)) return true;
    }
    return false;
}

fn doctorOutputAlloc(allocator: std.mem.Allocator, socket_path: []const u8, config: DoctorConfig) ![]u8 {
    const config_path = try cli_util.defaultConfigPath(allocator);
    defer allocator.free(config_path);
    const config_dir = try cli_util.configDirPath(allocator);
    defer allocator.free(config_dir);
    const plugins_dir = try cli_util.pluginsDirPath(allocator);
    defer allocator.free(plugins_dir);

    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);

    const socket_status = pathAccessStatus(socket_path);
    const daemon_status = try daemonHealthStatusAlloc(allocator, socket_path);
    defer allocator.free(daemon_status);
    const config_dir_permissions = try configDirPermissionsStatusAlloc(allocator, config_dir);
    defer allocator.free(config_dir_permissions);
    const shell_hook_status = shellHookStatus(allocator);
    const nerd_font_status = nerdFontStatus();
    const transient_status = try transientStatusAlloc(allocator, config_path, shell_hook_status);
    defer allocator.free(transient_status);
    const shell_name = try cli_util.currentShellNameAlloc(allocator);
    defer allocator.free(shell_name);
    const terminal = try cli_util.detectTerminalAlloc(allocator);
    defer allocator.free(terminal);
    const shell_hook_target = cli_config.shellHookTargetPathAlloc(allocator) catch null;
    defer if (shell_hook_target) |path| allocator.free(path);
    const shisa_bin = try shisaBinPathAlloc(allocator);
    defer allocator.free(shisa_bin);
    const shisa_bin_status = try shisaBinStatusAlloc(allocator, shisa_bin);
    defer allocator.free(shisa_bin_status);
    const default_socket = paths.defaultSocketPath(allocator) catch null;
    defer if (default_socket) |path| allocator.free(path);
    const env_socket = std.process.getEnvVarOwned(allocator, "SHISA_SOCKET") catch null;
    defer if (env_socket) |path| allocator.free(path);
    const socket_owner = try socketOwnerStatusAlloc(allocator, socket_path);
    defer allocator.free(socket_owner);
    const prompt_sample = try samplePromptAlloc(allocator, socket_path, shell_name, daemon_status);
    defer if (prompt_sample) |prompt| allocator.free(prompt);
    const vpn_segment = try activeConfiguredVpnSegmentAlloc(allocator, config_path);
    defer if (vpn_segment) |segment| allocator.free(segment);
    const context = DoctorContext{
        .socket_path = socket_path,
        .socket_status = socket_status,
        .daemon_status = daemon_status,
        .config_dir = config_dir,
        .config_dir_permissions = config_dir_permissions,
        .shell_hook_status = shell_hook_status,
        .nerd_font_status = nerd_font_status,
    };
    const issues = try doctorIssuesAlloc(allocator, context);
    defer allocator.free(issues);

    try cli_util.appendFmt(allocator, &out, "socket: {s} {s}\n", .{ socket_status, socket_path });
    if (default_socket) |path| try cli_util.appendFmt(allocator, &out, "socket_default: {s}\n", .{path});
    if (env_socket) |path| try cli_util.appendFmt(allocator, &out, "socket_env: {s}\n", .{path});
    try cli_util.appendFmt(allocator, &out, "socket_owner: {s}\n", .{socket_owner});
    try cli_util.appendFmt(allocator, &out, "daemon: {s}\n", .{daemon_status});
    try cli_util.appendFmt(allocator, &out, "config_dir: {s} {s}\n", .{ pathAccessStatus(config_dir), config_dir });
    try cli_util.appendFmt(allocator, &out, "config_dir_permissions: {s}\n", .{config_dir_permissions});
    try cli_util.appendFmt(allocator, &out, "detected_shell: {s}\n", .{shell_name});
    try cli_util.appendFmt(allocator, &out, "detected_terminal: {s}\n", .{terminal});
    if (shell_hook_target) |path| try cli_util.appendFmt(allocator, &out, "shell_hook_target: {s}\n", .{path});
    try cli_util.appendFmt(allocator, &out, "shell_hook: {s}\n", .{shell_hook_status});
    try cli_util.appendFmt(allocator, &out, "shisa_bin: {s} {s}\n", .{ shisa_bin_status, shisa_bin });
    try cli_util.appendFmt(allocator, &out, "transient: {s}\n", .{transient_status});
    try cli_util.appendFmt(allocator, &out, "nerd_font: {s}\n", .{nerd_font_status});
    try cli_util.appendFmt(allocator, &out, "plugins_dir: {s} {s}\n", .{ pathAccessStatus(plugins_dir), plugins_dir });
    const plugins_status = try doctorPluginsStatusAlloc(allocator, plugins_dir);
    defer allocator.free(plugins_status);
    try cli_util.appendFmt(allocator, &out, "plugins: {s}\n", .{plugins_status});
    try cli_util.appendFmt(allocator, &out, "lua: {s}\n", .{luaRuntimeStatus(allocator)});
    try cli_util.appendFmt(allocator, &out, "fsnotify: {s}\n", .{fsnotifyBackendName(fsnotify.selectBackend(builtin.os.tag))});
    try appendDoctorDeprecations(allocator, &out, config_path);

    var findings = try doctorFindingsAlloc(allocator, socket_path, config);
    defer findings.deinit(allocator);
    defer deinitDoctorFindings(allocator, findings.items);
    const finding_count = countFindingsAtLeast(findings.items, config.severity_min);
    try cli_util.appendFmt(allocator, &out, "findings: {d} at >= {s}\n", .{ finding_count, severityName(config.severity_min) });
    for (findings.items) |finding| {
        if (!severityAtLeast(finding.severity, config.severity_min)) continue;
        try cli_util.appendFmt(allocator, &out, "finding: {s}: {s}: {s}\n", .{ severityName(finding.severity), finding.id, finding.message });
    }

    if (builtin.os.tag == .linux) {
        const limit = fsnotify.readLinuxMaxUserWatches(allocator) catch null;
        if (limit) |value| {
            try cli_util.appendFmt(allocator, &out, "inotify.max_user_watches: {d}\n", .{value});
        } else {
            try out.appendSlice(allocator, "inotify.max_user_watches: unknown\n");
        }
    }
    for (issues) |issue| {
        try cli_util.appendFmt(allocator, &out, "issue: {s}: {s} [fix available]\n", .{ issue.id, issue.message });
    }
    if (std.mem.eql(u8, daemon_status, "ok")) {
        try out.appendSlice(allocator, "hint: daemon is already running; starting another default daemon prints AlreadyRunning\n");
    }
    if (prompt_sample) |prompt| {
        if (std.mem.indexOf(u8, prompt, "[pending:") != null) {
            try out.appendSlice(allocator, "hint: [pending:<module>] is normal on first async render; rerender after cache fill\n");
        }
    }
    if (vpn_segment) |segment| {
        try cli_util.appendFmt(allocator, &out, "hint: active VPN segment detected ({s}); remove \"vpn_status\" from [prompt].modules to hide it\n", .{segment});
    }

    return out.toOwnedSlice(allocator);
}

fn doctorLintOutputAlloc(allocator: std.mem.Allocator, socket_path: []const u8, config: DoctorConfig) !DoctorLintResult {
    var findings = try doctorFindingsAlloc(allocator, socket_path, config);
    defer findings.deinit(allocator);
    defer deinitDoctorFindings(allocator, findings.items);
    if (config.json) {
        const output = try doctorFindingsJsonAlloc(allocator, findings.items, config);
        return .{ .output = output, .finding_count = countFindingsAtLeast(findings.items, config.severity_min) };
    }
    const output = try doctorFindingsTextAlloc(allocator, findings.items, config);
    return .{ .output = output, .finding_count = countFindingsAtLeast(findings.items, config.severity_min) };
}

fn doctorFindingsAlloc(allocator: std.mem.Allocator, socket_path: []const u8, config: DoctorConfig) !std.ArrayList(DoctorFinding) {
    var findings: std.ArrayList(DoctorFinding) = .empty;
    errdefer findings.deinit(allocator);
    errdefer deinitDoctorFindings(allocator, findings.items);

    const config_path = try cli_util.defaultConfigPath(allocator);
    defer allocator.free(config_path);
    const config_dir = try cli_util.configDirPath(allocator);
    defer allocator.free(config_dir);
    const socket_status = pathAccessStatus(socket_path);
    const daemon_status = try daemonHealthStatusAlloc(allocator, socket_path);
    defer allocator.free(daemon_status);
    const shell_hook_status = shellHookStatus(allocator);
    const config_dir_permissions = try configDirPermissionsStatusAlloc(allocator, config_dir);
    defer allocator.free(config_dir_permissions);
    const nerd_font_status = nerdFontStatus();
    const shell_name = try cli_util.currentShellNameAlloc(allocator);
    defer allocator.free(shell_name);
    const terminal = try cli_util.detectTerminalAlloc(allocator);
    defer allocator.free(terminal);
    const shisa_bin = try shisaBinPathAlloc(allocator);
    defer allocator.free(shisa_bin);
    const shisa_bin_status = try shisaBinStatusAlloc(allocator, shisa_bin);
    defer allocator.free(shisa_bin_status);
    const default_socket = paths.defaultSocketPath(allocator) catch null;
    defer if (default_socket) |path| allocator.free(path);
    const env_socket = std.process.getEnvVarOwned(allocator, "SHISA_SOCKET") catch null;
    defer if (env_socket) |path| allocator.free(path);

    try appendInstallFindings(allocator, &findings, config);
    try appendConfigFindings(allocator, &findings, config_path, config);
    try appendConfigDeprecationFindings(allocator, &findings, config_path, config);
    if (std.mem.eql(u8, socket_status, "present") and !std.mem.eql(u8, daemon_status, "ok")) {
        try appendFindingIfAllowed(allocator, &findings, config, .{ .id = "daemon/stale-socket", .severity = .warning, .category = "daemon", .message = "socket exists but daemon is not reachable", .detail = "A leftover socket file can survive a crash or manual daemon kill.", .evidence = daemon_status, .path = socket_path, .fix_hint = "run `shisa doctor --fix` or remove the stale socket after confirming no owner", .fixable = true, .docs_url = "docs/troubleshooting.md#daemon-and-socket" });
    }
    if (!std.mem.eql(u8, daemon_status, "ok")) {
        try appendFindingIfAllowed(allocator, &findings, config, .{ .id = "daemon/not-running", .severity = .@"error", .category = "daemon", .message = "daemon is not reachable", .evidence = daemon_status, .path = socket_path, .command = "shisad --foreground &", .fix_hint = "start `shisad --foreground &` or run `shisa doctor --fix`", .fixable = true, .docs_url = "docs/troubleshooting.md#daemon-and-socket" });
    } else {
        try appendFindingIfAllowed(allocator, &findings, config, .{ .id = "daemon/already-running", .severity = .info, .category = "daemon", .message = "daemon is already running; starting another daemon for this socket prints AlreadyRunning", .evidence = daemon_status, .path = socket_path, .fix_hint = "reuse the running daemon or choose a different `--socket`", .docs_url = "docs/troubleshooting.md#expected-states" });
        try appendDaemonOnlineFindings(allocator, &findings, socket_path, config);
    }
    try appendSocketPermissionFinding(allocator, &findings, config, socket_path);
    if (env_socket) |path| {
        if (!std.mem.eql(u8, path, socket_path)) {
            try appendFindingIfAllowed(allocator, &findings, config, .{ .id = "daemon/socket-mismatch", .severity = .warning, .category = "daemon", .message = "SHISA_SOCKET differs from the socket being checked", .detail = "The shell hook and manual commands can talk to different daemons if socket paths differ.", .evidence = socket_path, .path = path, .fix_hint = "unset SHISA_SOCKET or pass the same --socket to shisa and shisad", .docs_url = "docs/troubleshooting.md#daemon-and-socket" });
        }
    }
    if (default_socket) |path| {
        if (!std.mem.eql(u8, path, socket_path)) {
            try appendFindingIfAllowed(allocator, &findings, config, .{ .id = "daemon/non-default-socket", .severity = .info, .category = "daemon", .message = "doctor is checking a non-default daemon socket", .evidence = path, .path = socket_path, .fix_hint = "this is expected for isolated tests", .docs_url = "docs/troubleshooting.md#daemon-and-socket" });
        }
    }
    try appendShellHookFindings(allocator, &findings, config);
    if (std.mem.eql(u8, shell_hook_status, "missing")) {
        try appendFindingIfAllowed(allocator, &findings, config, .{ .id = "shell/hook-missing", .severity = .warning, .category = "shell", .message = "shell hook is not installed or not active", .command = "shisa init --defaults --write-hook", .fix_hint = "run `shisa init --defaults --write-hook` then restart the shell", .fixable = true, .docs_url = "docs/troubleshooting.md#shell-hook" });
    }
    if (!std.mem.eql(u8, shisa_bin_status, "ok")) {
        try appendFindingIfAllowed(allocator, &findings, config, .{ .id = "shell/bin-missing", .severity = .@"error", .category = "shell", .message = "SHISA_BIN is not executable", .evidence = shisa_bin_status, .path = shisa_bin, .fix_hint = "set SHISA_BIN to zig-out/bin/shisa or install shisa on PATH", .docs_url = "docs/troubleshooting.md#shell-hook" });
    }
    if (std.mem.startsWith(u8, config_dir_permissions, "wrong")) {
        try appendFindingIfAllowed(allocator, &findings, config, .{ .id = "config/dir-permissions", .severity = .warning, .category = "config", .message = "config directory permissions are too broad", .evidence = config_dir_permissions, .path = config_dir, .command = "chmod 0700 ~/.config/shisa", .fix_hint = "run `shisa doctor --fix`", .fixable = true, .docs_url = "docs/doctor.md#config" });
    }
    if (std.mem.eql(u8, nerd_font_status, "missing")) {
        try appendFindingIfAllowed(allocator, &findings, config, .{ .id = "terminal/nerd-font", .severity = .warning, .category = "terminal", .message = "Nerd Font is not detected", .command = "shisa font check", .fix_hint = "run `shisa font check` and install a Nerd Font if glyphs are broken", .fixable = true, .docs_url = "docs/troubleshooting.md#prompt-output" });
    }
    if (std.mem.eql(u8, terminal, "unknown") or std.mem.eql(u8, terminal, "dumb")) {
        try appendFindingIfAllowed(allocator, &findings, config, .{ .id = "terminal/unknown", .severity = .info, .category = "terminal", .message = "terminal could not be identified", .evidence = terminal, .fix_hint = "set TERM_PROGRAM or use SHISA_GLYPH_CAPS/SHISA_NERD_FONT overrides", .docs_url = "docs/troubleshooting.md#prompt-output" });
    }
    if (try samplePromptAlloc(allocator, socket_path, shell_name, daemon_status)) |prompt| {
        defer allocator.free(prompt);
        if (std.mem.indexOf(u8, prompt, "[pending:") != null) {
            try appendFindingIfAllowed(allocator, &findings, config, .{ .id = "prompt/async-pending", .severity = .info, .category = "prompt", .message = "prompt contains an async placeholder", .detail = "Async modules render a placeholder on the first prompt while the daemon fills cache.", .evidence = prompt, .fix_hint = "rerender after the daemon fills the cache; this is normal on first render", .docs_url = "docs/troubleshooting.md#expected-states" });
        }
        try appendFindingIfAllowed(allocator, &findings, config, .{ .id = "prompt/render-sample", .severity = .info, .category = "prompt", .message = "sample prompt rendered through the daemon", .evidence = prompt, .docs_url = "docs/doctor.md#prompt" });
    }
    if (try activeConfiguredVpnSegmentAlloc(allocator, config_path)) |segment| {
        defer allocator.free(segment);
        try appendFindingIfAllowed(allocator, &findings, config, .{ .id = "modules/vpn-active", .severity = .info, .category = "modules", .message = "vpn_status is enabled and an active VPN was detected", .evidence = segment, .fix_hint = "remove \"vpn_status\" from [prompt].modules to hide this segment", .docs_url = "docs/troubleshooting.md#expected-states" });
    }
    try appendModuleFindings(allocator, &findings, config, config_path);
    try appendPluginFindings(allocator, &findings, config);
    try appendPlatformFindings(allocator, &findings, config, config_dir);
    try appendPerformanceFindings(allocator, &findings, config, socket_path, shell_name, daemon_status);
    try appendSecurityFindings(allocator, &findings, config, config_path, config_dir);
    try appendTestFindings(allocator, &findings, config);
    try appendReleaseFindings(allocator, &findings, config);
    return findings;
}

fn appendSocketPermissionFinding(allocator: std.mem.Allocator, findings: *std.ArrayList(DoctorFinding), config: DoctorConfig, socket_path: []const u8) !void {
    if (!checkAllowed(config, "daemon/socket-permissions") or builtin.os.tag == .windows) return;
    const stat = std.fs.cwd().statFile(socket_path) catch return;
    if (stat.kind != .unix_domain_socket or socket_security.isOwnerOnly(stat.mode)) return;

    const mode = stat.mode & 0o777;
    const evidence = try std.fmt.allocPrint(allocator, "mode={o}", .{mode});
    defer allocator.free(evidence);
    try appendFindingIfAllowed(allocator, findings, config, .{ .id = "daemon/socket-permissions", .severity = .warning, .category = "daemon", .message = "daemon socket mode is not owner-only (expected 0600)", .evidence = evidence, .path = socket_path, .fix_hint = "restart shisad to recreate the socket with mode 0600", .docs_url = "docs/doctor.md#daemon" });
}

fn deinitDoctorFindings(allocator: std.mem.Allocator, findings: []DoctorFinding) void {
    for (findings) |finding| {
        allocator.free(finding.id);
        allocator.free(finding.category);
        allocator.free(finding.message);
        if (finding.detail) |detail| allocator.free(detail);
        if (finding.evidence) |evidence| allocator.free(evidence);
        if (finding.path) |path| allocator.free(path);
        if (finding.command) |cmd| allocator.free(cmd);
        if (finding.fix_hint) |hint| allocator.free(hint);
        if (finding.docs_url) |docs_url| allocator.free(docs_url);
    }
}

fn appendFindingIfAllowed(allocator: std.mem.Allocator, findings: *std.ArrayList(DoctorFinding), config: DoctorConfig, finding: DoctorFinding) !void {
    if (!checkAllowed(config, finding.id)) return;
    try appendFinding(allocator, findings, finding);
}

fn appendFinding(allocator: std.mem.Allocator, findings: *std.ArrayList(DoctorFinding), finding: DoctorFinding) !void {
    const id = try allocator.dupe(u8, finding.id);
    errdefer allocator.free(id);
    const category = try allocator.dupe(u8, finding.category);
    errdefer allocator.free(category);
    const message = try allocator.dupe(u8, finding.message);
    errdefer allocator.free(message);
    const detail = if (finding.detail) |value| try allocator.dupe(u8, value) else null;
    errdefer if (detail) |value| allocator.free(value);
    const evidence = if (finding.evidence) |value| try allocator.dupe(u8, value) else null;
    errdefer if (evidence) |value| allocator.free(value);
    const path = if (finding.path) |value| try allocator.dupe(u8, value) else null;
    errdefer if (path) |value| allocator.free(value);
    const cmd = if (finding.command) |value| try allocator.dupe(u8, value) else null;
    errdefer if (cmd) |value| allocator.free(value);
    const fix_hint = if (finding.fix_hint) |value| try allocator.dupe(u8, value) else null;
    errdefer if (fix_hint) |value| allocator.free(value);
    const docs_url = if (finding.docs_url) |value| try allocator.dupe(u8, value) else null;
    errdefer if (docs_url) |value| allocator.free(value);
    try findings.append(allocator, .{
        .id = id,
        .severity = finding.severity,
        .category = category,
        .message = message,
        .detail = detail,
        .evidence = evidence,
        .path = path,
        .command = cmd,
        .fix_hint = fix_hint,
        .fixable = finding.fixable,
        .docs_url = docs_url,
    });
}

fn appendConfigFindings(allocator: std.mem.Allocator, findings: *std.ArrayList(DoctorFinding), config_path: []const u8, config: DoctorConfig) !void {
    const source = cli_util.readConfigOrDefault(allocator, config_path) catch |err| {
        const message = try std.fmt.allocPrint(allocator, "config is unreadable ({s})", .{@errorName(err)});
        defer allocator.free(message);
        try appendFindingIfAllowed(allocator, findings, config, .{ .id = "config/unreadable", .severity = .@"error", .category = "config", .message = message, .path = config_path, .fix_hint = "fix file permissions or recreate the config with `shisa init --defaults`", .docs_url = "docs/doctor.md#config" });
        return;
    };
    defer allocator.free(source);
    var diagnostic: shisa_config.Diagnostic = .{};
    var parsed = shisa_config.parse(allocator, source, &diagnostic) catch |err| switch (err) {
        error.InvalidConfig => {
            const message = try std.fmt.allocPrint(allocator, "config is invalid at {d}:{d}: {s}", .{ diagnostic.line, diagnostic.column, diagnostic.message });
            defer allocator.free(message);
            try appendFindingIfAllowed(allocator, findings, config, .{ .id = "config/invalid", .severity = .@"error", .category = "config", .message = message, .path = config_path, .fix_hint = "edit shisa.toml or regenerate it with `shisa init --defaults`", .docs_url = "docs/doctor.md#config" });
            return;
        },
        else => return err,
    };
    parsed.deinit(allocator);
}

fn appendInstallFindings(allocator: std.mem.Allocator, findings: *std.ArrayList(DoctorFinding), config: DoctorConfig) !void {
    if (checkAllowed(config, "install/zig-version")) {
        const required = try requiredZigVersionAlloc(allocator);
        defer if (required) |value| allocator.free(value);
        const actual = commandOutputTrimmedAlloc(allocator, &.{ "zig", "version" }) catch |err| switch (err) {
            error.FileNotFound => {
                try appendFindingIfAllowed(allocator, findings, config, .{ .id = "install/zig-version", .severity = .warning, .category = "install", .message = "zig was not found on PATH", .command = "brew install zig@0.15", .fix_hint = "install the Zig version listed in build.zig.zon", .docs_url = "docs/quickstart.md" });
                return;
            },
            else => {
                const evidence = try std.fmt.allocPrint(allocator, "{s}", .{@errorName(err)});
                defer allocator.free(evidence);
                try appendFindingIfAllowed(allocator, findings, config, .{ .id = "install/zig-version", .severity = .warning, .category = "install", .message = "zig version check failed", .evidence = evidence, .fix_hint = "run `zig version` manually and compare with build.zig.zon", .docs_url = "docs/doctor.md#install" });
                return;
            },
        };
        defer allocator.free(actual);
        if (required) |value| {
            if (!std.mem.eql(u8, actual, value)) {
                const evidence = try std.fmt.allocPrint(allocator, "required={s} actual={s}", .{ value, actual });
                defer allocator.free(evidence);
                try appendFindingIfAllowed(allocator, findings, config, .{ .id = "install/zig-version", .severity = .warning, .category = "install", .message = "zig version differs from build.zig.zon", .evidence = evidence, .command = "zig version", .fix_hint = "use the repo-required Zig version before running the full test suite", .docs_url = "docs/quickstart.md" });
            }
        }
    }

    if (checkAllowed(config, "install/binary-set")) {
        inline for (.{ "shisad", "shisa-supervisor" }) |name| {
            const path = try cli_util.siblingExecutablePath(allocator, name);
            defer allocator.free(path);
            if (!pathExecutable(path)) {
                const message = try std.fmt.allocPrint(allocator, "{s} is missing next to shisa", .{name});
                defer allocator.free(message);
                try appendFindingIfAllowed(allocator, findings, config, .{ .id = "install/binary-set", .severity = .warning, .category = "install", .message = message, .path = path, .command = "zig build release", .fix_hint = "run `zig build release` or install all shisa binaries together", .docs_url = "docs/quickstart.md" });
            }
        }
    }

    if (checkAllowed(config, "install/path-shadowing")) {
        const self_path = try std.fs.selfExePathAlloc(allocator);
        defer allocator.free(self_path);
        const which = commandOutputTrimmedAlloc(allocator, &.{ "which", "-a", "shisa" }) catch return;
        defer allocator.free(which);
        if (which.len != 0 and std.mem.indexOf(u8, which, self_path) == null) {
            try appendFindingIfAllowed(allocator, findings, config, .{ .id = "install/path-shadowing", .severity = .info, .category = "install", .message = "PATH resolves a different shisa binary than the running executable", .evidence = which, .path = self_path, .command = "which -a shisa", .fix_hint = "put the intended shisa install dir first in PATH", .docs_url = "docs/doctor.md#install" });
        }
    }
}

fn appendConfigDeprecationFindings(allocator: std.mem.Allocator, findings: *std.ArrayList(DoctorFinding), config_path: []const u8, config: DoctorConfig) !void {
    if (!checkAllowed(config, "config/deprecations")) return;
    const source = cli_util.readConfigOrDefault(allocator, config_path) catch return;
    defer allocator.free(source);
    for (active_deprecation_rules) |rule| {
        if (std.mem.indexOf(u8, source, rule.pattern) == null) continue;
        const message = try std.fmt.allocPrint(allocator, "{s} `{s}` is deprecated", .{ rule.kind, rule.pattern });
        defer allocator.free(message);
        const detail = try std.fmt.allocPrint(allocator, "deprecated since {s}; remove before {s}", .{ rule.since, rule.remove_before });
        defer allocator.free(detail);
        try appendFindingIfAllowed(allocator, findings, config, .{ .id = "config/deprecations", .severity = .warning, .category = "config", .message = message, .detail = detail, .path = config_path, .fix_hint = rule.replacement, .docs_url = "docs/deprecations.md" });
    }
}

fn appendDaemonOnlineFindings(allocator: std.mem.Allocator, findings: *std.ArrayList(DoctorFinding), socket_path: []const u8, config: DoctorConfig) !void {
    if (checkAllowed(config, "daemon/protocol")) {
        const response = client.requestAlloc(allocator, socket_path, "{\"v\":1,\"op\":\"version\",\"request_id\":\"doctor-version\"}") catch |err| {
            const evidence = try std.fmt.allocPrint(allocator, "{s}", .{@errorName(err)});
            defer allocator.free(evidence);
            try appendFindingIfAllowed(allocator, findings, config, .{ .id = "daemon/protocol", .severity = .warning, .category = "daemon", .message = "daemon version request failed", .evidence = evidence, .docs_url = "docs/doctor.md#daemon" });
            return;
        };
        defer allocator.free(response);
        if (std.mem.indexOf(u8, response, "\"protocol\":") == null) {
            try appendFindingIfAllowed(allocator, findings, config, .{ .id = "daemon/protocol", .severity = .warning, .category = "daemon", .message = "daemon version response omitted protocol metadata", .evidence = response, .docs_url = "docs/doctor.md#daemon" });
        } else {
            try appendFindingIfAllowed(allocator, findings, config, .{ .id = "daemon/protocol", .severity = .info, .category = "daemon", .message = "daemon protocol handshake succeeded", .evidence = response, .docs_url = "docs/doctor.md#daemon" });
        }
    }

    if (checkAllowed(config, "daemon/metrics")) {
        const response = client.requestAlloc(allocator, socket_path, "{\"v\":1,\"op\":\"metrics\",\"request_id\":\"doctor-metrics\"}") catch |err| {
            const evidence = try std.fmt.allocPrint(allocator, "{s}", .{@errorName(err)});
            defer allocator.free(evidence);
            try appendFindingIfAllowed(allocator, findings, config, .{ .id = "daemon/metrics", .severity = .warning, .category = "daemon", .message = "daemon metrics request failed", .evidence = evidence, .docs_url = "docs/doctor.md#daemon" });
            return;
        };
        defer allocator.free(response);
        if (std.mem.indexOf(u8, response, "\"render\":") == null) {
            try appendFindingIfAllowed(allocator, findings, config, .{ .id = "daemon/metrics", .severity = .warning, .category = "daemon", .message = "daemon metrics response omitted render metrics", .evidence = response, .docs_url = "docs/doctor.md#daemon" });
        } else {
            try appendFindingIfAllowed(allocator, findings, config, .{ .id = "daemon/metrics", .severity = .info, .category = "daemon", .message = "daemon metrics endpoint responded", .evidence = response, .docs_url = "docs/doctor.md#daemon" });
        }
    }

    if (checkAllowed(config, "daemon/log-warnings")) {
        const log_path = paths.defaultLogPath(allocator) catch return;
        defer allocator.free(log_path);
        const tail = readFileTailAlloc(allocator, log_path, 64 * 1024) catch return;
        defer allocator.free(tail);
        if (std.mem.indexOf(u8, tail, "\"level\":\"warn\"") != null) {
            try appendFindingIfAllowed(allocator, findings, config, .{ .id = "daemon/log-warnings", .severity = .info, .category = "daemon", .message = "daemon log contains warning entries", .path = log_path, .fix_hint = "run `shisa report` if warnings repeat", .docs_url = "docs/report.md" });
        }
    }
}

fn appendShellHookFindings(allocator: std.mem.Allocator, findings: *std.ArrayList(DoctorFinding), config: DoctorConfig) !void {
    if (!checkAllowed(config, "shell/hook-duplicates")) return;
    const target = cli_config.shellHookTargetPathAlloc(allocator) catch return;
    defer allocator.free(target);
    const source = std.fs.cwd().readFileAlloc(allocator, target, 1024 * 1024) catch return;
    defer allocator.free(source);
    const count = countOccurrences(source, cli_config.shell_hook_marker_start);
    if (count > 1) {
        const evidence = try std.fmt.allocPrint(allocator, "marker_count={d}", .{count});
        defer allocator.free(evidence);
        try appendFindingIfAllowed(allocator, findings, config, .{ .id = "shell/hook-duplicates", .severity = .warning, .category = "shell", .message = "shell startup file contains multiple shisa hook blocks", .evidence = evidence, .path = target, .fix_hint = "remove older duplicated shisa blocks and rerun `shisa init --write-hook`", .docs_url = "docs/troubleshooting.md#shell-hook" });
    }
}

fn appendModuleFindings(allocator: std.mem.Allocator, findings: *std.ArrayList(DoctorFinding), config: DoctorConfig, config_path: []const u8) !void {
    const parsed = parsedConfigOrNull(allocator, config_path) orelse return;
    var owned = parsed;
    defer owned.deinit(allocator);
    const cwd = std.fs.cwd().realpathAlloc(allocator, ".") catch return;
    defer allocator.free(cwd);

    if (checkAllowed(config, "modules/git") and (configHasModule(owned.prompt_modules, .git_branch) or configHasModule(owned.right_prompt_modules, .git_branch))) {
        if (hasAncestorMarkerAlloc(allocator, cwd, ".git") catch false) {
            const git_version = commandOutputTrimmedAlloc(allocator, &.{ "git", "--version" }) catch |err| switch (err) {
                error.FileNotFound => {
                    try appendFindingIfAllowed(allocator, findings, config, .{ .id = "modules/git", .severity = .warning, .category = "modules", .message = "git_branch is enabled in a Git worktree but git is not on PATH", .command = "git --version", .fix_hint = "install git or remove git_branch from prompt modules", .docs_url = "docs/troubleshooting.md#tests" });
                    return;
                },
                else => return,
            };
            allocator.free(git_version);
        }
    }

    if (checkAllowed(config, "modules/language-tools") and (configHasModule(owned.prompt_modules, .language_versions) or configHasModule(owned.right_prompt_modules, .language_versions))) {
        try appendMissingLanguageTool(allocator, findings, config, cwd, "package.json", "node", owned.modules.language_versions.node);
        try appendMissingLanguageTool(allocator, findings, config, cwd, "pyproject.toml", "python3", owned.modules.language_versions.python);
        try appendMissingLanguageTool(allocator, findings, config, cwd, "requirements.txt", "python3", owned.modules.language_versions.python);
        try appendMissingLanguageTool(allocator, findings, config, cwd, "Cargo.toml", "rustc", owned.modules.language_versions.rust);
        try appendMissingLanguageTool(allocator, findings, config, cwd, "go.mod", "go", owned.modules.language_versions.go);
    }

    if (checkAllowed(config, "modules/cloud-cache") and (configHasModule(owned.prompt_modules, .cloud_ctx) or configHasModule(owned.right_prompt_modules, .cloud_ctx))) {
        if (!owned.modules.cloud_ctx.aws and !owned.modules.cloud_ctx.gcp and !owned.modules.cloud_ctx.azure and !owned.modules.cloud_ctx.kubernetes) {
            try appendFindingIfAllowed(allocator, findings, config, .{ .id = "modules/cloud-cache", .severity = .info, .category = "modules", .message = "cloud_ctx is enabled but all cloud providers are disabled", .path = config_path, .fix_hint = "enable at least one [modules.cloud_ctx] provider or remove cloud_ctx", .docs_url = "docs/doctor.md#modules" });
        }
    }
}

fn appendMissingLanguageTool(allocator: std.mem.Allocator, findings: *std.ArrayList(DoctorFinding), config: DoctorConfig, cwd: []const u8, marker: []const u8, tool: []const u8, enabled: bool) !void {
    if (!enabled) return;
    if (!(hasAncestorMarkerAlloc(allocator, cwd, marker) catch false)) return;
    const version = commandOutputTrimmedAlloc(allocator, &.{ tool, "--version" }) catch |err| switch (err) {
        error.FileNotFound => {
            const message = try std.fmt.allocPrint(allocator, "{s} marker found but {s} is not on PATH", .{ marker, tool });
            defer allocator.free(message);
            try appendFindingIfAllowed(allocator, findings, config, .{ .id = "modules/language-tools", .severity = .info, .category = "modules", .message = message, .command = tool, .fix_hint = "install the tool or disable that language in [modules.language_versions]", .docs_url = "docs/doctor.md#modules" });
            return;
        },
        else => return,
    };
    allocator.free(version);
}

fn appendPluginFindings(allocator: std.mem.Allocator, findings: *std.ArrayList(DoctorFinding), config: DoctorConfig) !void {
    if (checkAllowed(config, "plugins/runtime") and std.mem.eql(u8, luaRuntimeStatus(allocator), "unavailable")) {
        try appendFindingIfAllowed(allocator, findings, config, .{ .id = "plugins/runtime", .severity = .warning, .category = "plugins", .message = "Lua runtime is unavailable; Lua plugins cannot load", .fix_hint = "build with Lua support or disable Lua plugins", .docs_url = "docs/plugins.md" });
    }
    if (!checkAllowed(config, "plugins/manifests")) return;
    const plugins_dir = cli_util.pluginsDirPath(allocator) catch return;
    defer allocator.free(plugins_dir);
    var dir = std.fs.openDirAbsolute(plugins_dir, .{ .iterate = true }) catch return;
    defer dir.close();
    var it = dir.iterate();
    while (try it.next()) |entry| {
        if (entry.kind != .directory) continue;
        if (plugin_manifest.isValidPluginName(entry.name)) continue;
        const path = try std.fs.path.join(allocator, &.{ plugins_dir, entry.name });
        defer allocator.free(path);
        try appendFindingIfAllowed(allocator, findings, config, .{ .id = "plugins/manifests", .severity = .warning, .category = "plugins", .message = "plugin directory name is invalid and will be ignored", .path = path, .fix_hint = "rename the plugin directory to a lowercase manifest-safe name", .docs_url = "docs/plugins.md" });
    }
}

fn appendPlatformFindings(allocator: std.mem.Allocator, findings: *std.ArrayList(DoctorFinding), config: DoctorConfig, config_dir: []const u8) !void {
    if (checkAllowed(config, "platform/runtime-dir")) {
        if (builtin.os.tag == .linux and !std.process.hasEnvVarConstant("XDG_RUNTIME_DIR")) {
            try appendFindingIfAllowed(allocator, findings, config, .{ .id = "platform/runtime-dir", .severity = .info, .category = "platform", .message = "XDG_RUNTIME_DIR is unset; socket path falls back to /run/user/<uid>", .fix_hint = "set XDG_RUNTIME_DIR in unusual non-login shells if /run/user/<uid> is unavailable", .docs_url = "docs/doctor.md#platform" });
        }
        if (builtin.os.tag == .macos and pathAccessStatus(config_dir).len != 0 and std.mem.eql(u8, pathAccessStatus(config_dir), "denied")) {
            try appendFindingIfAllowed(allocator, findings, config, .{ .id = "platform/runtime-dir", .severity = .warning, .category = "platform", .message = "config directory is not accessible", .path = config_dir, .docs_url = "docs/doctor.md#platform" });
        }
    }
    if (checkAllowed(config, "platform/fsnotify")) {
        if (builtin.os.tag == .linux) {
            const limit = fsnotify.readLinuxMaxUserWatches(allocator) catch null;
            if (limit) |value| {
                if (value < 8192) {
                    const evidence = try std.fmt.allocPrint(allocator, "fs.inotify.max_user_watches={d}", .{value});
                    defer allocator.free(evidence);
                    try appendFindingIfAllowed(allocator, findings, config, .{ .id = "platform/fsnotify", .severity = .warning, .category = "platform", .message = "Linux inotify watch limit is low", .evidence = evidence, .fix_hint = "raise fs.inotify.max_user_watches for large repos", .docs_url = "docs/doctor.md#platform" });
                }
            }
        } else if (std.mem.eql(u8, fsnotifyBackendName(fsnotify.selectBackend(builtin.os.tag)), "unsupported")) {
            try appendFindingIfAllowed(allocator, findings, config, .{ .id = "platform/fsnotify", .severity = .warning, .category = "platform", .message = "filesystem watcher backend is unsupported on this platform", .docs_url = "docs/doctor.md#platform" });
        }
    }
}

fn appendPerformanceFindings(allocator: std.mem.Allocator, findings: *std.ArrayList(DoctorFinding), config: DoctorConfig, socket_path: []const u8, shell_name: []const u8, daemon_status: []const u8) !void {
    if (!checkAllowed(config, "performance/prompt-budget")) return;
    if (!std.mem.eql(u8, daemon_status, "ok")) return;
    const start = std.time.nanoTimestamp();
    const prompt = try samplePromptAlloc(allocator, socket_path, shell_name, daemon_status);
    defer if (prompt) |value| allocator.free(value);
    const elapsed_ns: u64 = @intCast(std.time.nanoTimestamp() - start);
    const evidence = try std.fmt.allocPrint(allocator, "sample_render_ns={d}", .{elapsed_ns});
    defer allocator.free(evidence);
    if (prompt == null) {
        try appendFindingIfAllowed(allocator, findings, config, .{ .id = "performance/prompt-budget", .severity = .warning, .category = "performance", .message = "sample prompt render failed during performance probe", .evidence = evidence, .docs_url = "docs/doctor.md#performance" });
    } else if (elapsed_ns > 10 * std.time.ns_per_ms) {
        try appendFindingIfAllowed(allocator, findings, config, .{ .id = "performance/prompt-budget", .severity = .warning, .category = "performance", .message = "sample prompt render exceeded 10ms budget", .evidence = evidence, .fix_hint = "check daemon metrics, slow module warnings, and active plugins", .docs_url = "docs/doctor.md#performance" });
    } else {
        try appendFindingIfAllowed(allocator, findings, config, .{ .id = "performance/prompt-budget", .severity = .info, .category = "performance", .message = "sample prompt render is within 10ms budget", .evidence = evidence, .docs_url = "docs/doctor.md#performance" });
    }
}

fn appendSecurityFindings(allocator: std.mem.Allocator, findings: *std.ArrayList(DoctorFinding), config: DoctorConfig, config_path: []const u8, config_dir: []const u8) !void {
    if (!checkAllowed(config, "security/permissions")) return;
    if (builtin.os.tag == .windows) return;
    try appendSensitivePathPermissionFinding(allocator, findings, config, config_path, 0o600, "config file permissions are broader than 0600");
    try appendSensitivePathPermissionFinding(allocator, findings, config, config_dir, 0o700, "config directory permissions are broader than 0700");
}

fn appendSensitivePathPermissionFinding(allocator: std.mem.Allocator, findings: *std.ArrayList(DoctorFinding), config: DoctorConfig, path: []const u8, max_mode: u32, message: []const u8) !void {
    const stat = std.fs.cwd().statFile(path) catch return;
    const mode = stat.mode & 0o777;
    if ((mode | max_mode) == max_mode) return;
    const evidence = try std.fmt.allocPrint(allocator, "mode={o}", .{mode});
    defer allocator.free(evidence);
    const hint = try std.fmt.allocPrint(allocator, "chmod {o} {s}", .{ max_mode, path });
    defer allocator.free(hint);
    try appendFindingIfAllowed(allocator, findings, config, .{ .id = "security/permissions", .severity = .warning, .category = "security", .message = message, .evidence = evidence, .path = path, .command = hint, .fix_hint = hint, .docs_url = "docs/doctor.md#security" });
}

fn appendTestFindings(allocator: std.mem.Allocator, findings: *std.ArrayList(DoctorFinding), config: DoctorConfig) !void {
    if (!checkAllowed(config, "tests/optional-prereqs")) return;
    if (!std.process.hasEnvVarConstant("SHISA_PURE_ZSH_DIR") or !std.process.hasEnvVarConstant("SHISA_PURE_FISH_DIR")) {
        try appendFindingIfAllowed(allocator, findings, config, .{ .id = "tests/optional-prereqs", .severity = .info, .category = "tests", .message = "Pure import smoke fixtures are not configured", .fix_hint = "set SHISA_PURE_ZSH_DIR and SHISA_PURE_FISH_DIR only when testing Pure import", .docs_url = "docs/troubleshooting.md#tests" });
    }
    const nix_version = commandOutputTrimmedAlloc(allocator, &.{ "nix-shell", "--version" }) catch |err| switch (err) {
        error.FileNotFound => {
            try appendFindingIfAllowed(allocator, findings, config, .{ .id = "tests/optional-prereqs", .severity = .info, .category = "tests", .message = "nix-shell is not installed; nix-shell language integration smoke will skip", .fix_hint = "install Nix only if you need that integration test", .docs_url = "docs/troubleshooting.md#tests" });
            return;
        },
        else => return,
    };
    allocator.free(nix_version);
}

fn appendReleaseFindings(allocator: std.mem.Allocator, findings: *std.ArrayList(DoctorFinding), config: DoctorConfig) !void {
    if (checkAllowed(config, "release/packaging")) {
        inline for (.{ "shisa", "shisad", "shisa-supervisor" }) |name| {
            const path = try cli_util.siblingExecutablePath(allocator, name);
            defer allocator.free(path);
            if (!pathExecutable(path)) {
                const message = try std.fmt.allocPrint(allocator, "release binary {s} is missing", .{name});
                defer allocator.free(message);
                try appendFindingIfAllowed(allocator, findings, config, .{ .id = "release/packaging", .severity = .warning, .category = "release", .message = message, .path = path, .command = "zig build release", .fix_hint = "run `zig build release` before packaging", .docs_url = "docs/doctor.md#release" });
            }
        }
    }
    if (!config.online) return;
    if (!checkAllowed(config, "release/online")) return;
    const result = std.process.Child.run(.{
        .allocator = allocator,
        .argv = &.{ "git", "ls-remote", "--tags", "https://github.com/gongahkia/shisa" },
        .max_output_bytes = 128 * 1024,
        .expand_arg0 = .expand,
    }) catch |err| {
        const evidence = try std.fmt.allocPrint(allocator, "{s}", .{@errorName(err)});
        defer allocator.free(evidence);
        try appendFindingIfAllowed(allocator, findings, config, .{ .id = "release/online", .severity = .warning, .category = "release", .message = "online release check could not run", .evidence = evidence, .command = "git ls-remote --tags https://github.com/gongahkia/shisa", .docs_url = "docs/doctor.md#release" });
        return;
    };
    defer allocator.free(result.stdout);
    defer allocator.free(result.stderr);
    if (!cli_util.exitedZero(result.term)) {
        try appendFindingIfAllowed(allocator, findings, config, .{ .id = "release/online", .severity = .warning, .category = "release", .message = "online release check failed", .evidence = result.stderr, .command = "git ls-remote --tags https://github.com/gongahkia/shisa", .docs_url = "docs/doctor.md#release" });
    } else {
        try appendFindingIfAllowed(allocator, findings, config, .{ .id = "release/online", .severity = .info, .category = "release", .message = "online release tag query succeeded", .evidence = "git ls-remote exited 0", .docs_url = "docs/doctor.md#release" });
    }
}

fn doctorFindingsTextAlloc(allocator: std.mem.Allocator, findings: []const DoctorFinding, config: DoctorConfig) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);
    const count = countFindingsAtLeast(findings, config.severity_min);
    try cli_util.appendFmt(allocator, &out, "doctor lint: {s} ({d} findings at >= {s})\n", .{ if (count == 0) "ok" else "findings", count, severityName(config.severity_min) });
    for (findings) |finding| {
        if (!severityAtLeast(finding.severity, config.severity_min)) continue;
        try cli_util.appendFmt(allocator, &out, "{s}: {s}: {s}: {s}", .{ severityName(finding.severity), finding.category, finding.id, finding.message });
        if (finding.detail) |detail| try cli_util.appendFmt(allocator, &out, " detail: {s}", .{detail});
        if (finding.evidence) |evidence| try cli_util.appendFmt(allocator, &out, " evidence: {s}", .{evidence});
        if (finding.path) |path| try cli_util.appendFmt(allocator, &out, " [{s}]", .{path});
        if (finding.command) |cmd| try cli_util.appendFmt(allocator, &out, " command: {s}", .{cmd});
        if (finding.fix_hint) |hint| try cli_util.appendFmt(allocator, &out, " fix: {s}", .{hint});
        try out.append(allocator, '\n');
    }
    return out.toOwnedSlice(allocator);
}

fn doctorFindingsJsonAlloc(allocator: std.mem.Allocator, findings: []const DoctorFinding, config: DoctorConfig) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);
    const count = countFindingsAtLeast(findings, config.severity_min);
    const summary = countSummary(findings);
    try cli_util.appendFmt(allocator, &out, "{{\"version\":1,\"status\":\"{s}\",\"severity_min\":\"{s}\",\"online\":{},\"checks_run\":{d},\"summary\":{{\"info\":{d},\"warning\":{d},\"error\":{d}}},\"findings\":[", .{ if (count == 0) "ok" else "findings", severityName(config.severity_min), config.online, countChecksRun(config), summary.info, summary.warning, summary.@"error" });
    var emitted: usize = 0;
    for (findings) |finding| {
        if (!severityAtLeast(finding.severity, config.severity_min)) continue;
        if (emitted != 0) try out.append(allocator, ',');
        emitted += 1;
        try appendJsonFinding(allocator, &out, finding);
    }
    try cli_util.appendFmt(allocator, &out, "],\"count\":{d}}}\n", .{count});
    return out.toOwnedSlice(allocator);
}

fn appendJsonFinding(allocator: std.mem.Allocator, out: *std.ArrayList(u8), finding: DoctorFinding) !void {
    try out.appendSlice(allocator, "{\"id\":");
    try appendJsonString(allocator, out, finding.id);
    try out.appendSlice(allocator, ",\"severity\":");
    try appendJsonString(allocator, out, severityName(finding.severity));
    try out.appendSlice(allocator, ",\"category\":");
    try appendJsonString(allocator, out, finding.category);
    try out.appendSlice(allocator, ",\"message\":");
    try appendJsonString(allocator, out, finding.message);
    try out.appendSlice(allocator, ",\"detail\":");
    if (finding.detail) |detail| try appendJsonString(allocator, out, detail) else try out.appendSlice(allocator, "null");
    try out.appendSlice(allocator, ",\"evidence\":");
    if (finding.evidence) |evidence| try appendJsonString(allocator, out, evidence) else try out.appendSlice(allocator, "null");
    try out.appendSlice(allocator, ",\"path\":");
    if (finding.path) |path| try appendJsonString(allocator, out, path) else try out.appendSlice(allocator, "null");
    try out.appendSlice(allocator, ",\"paths\":");
    if (finding.path) |path| {
        try out.append(allocator, '[');
        try appendJsonString(allocator, out, path);
        try out.append(allocator, ']');
    } else {
        try out.appendSlice(allocator, "[]");
    }
    try out.appendSlice(allocator, ",\"command\":");
    if (finding.command) |cmd| try appendJsonString(allocator, out, cmd) else try out.appendSlice(allocator, "null");
    try out.appendSlice(allocator, ",\"commands\":");
    if (finding.command) |cmd| {
        try out.append(allocator, '[');
        try appendJsonString(allocator, out, cmd);
        try out.append(allocator, ']');
    } else {
        try out.appendSlice(allocator, "[]");
    }
    try out.appendSlice(allocator, ",\"fix_hint\":");
    if (finding.fix_hint) |hint| try appendJsonString(allocator, out, hint) else try out.appendSlice(allocator, "null");
    try cli_util.appendFmt(allocator, out, ",\"fixable\":{}", .{finding.fixable});
    try out.appendSlice(allocator, ",\"docs_url\":");
    if (finding.docs_url) |docs_url| try appendJsonString(allocator, out, docs_url) else try out.appendSlice(allocator, "null");
    try out.append(allocator, '}');
}

fn appendJsonString(allocator: std.mem.Allocator, out: *std.ArrayList(u8), value: []const u8) !void {
    const escaped = try daemon_json.escapeAlloc(allocator, value);
    defer allocator.free(escaped);
    try out.append(allocator, '"');
    try out.appendSlice(allocator, escaped);
    try out.append(allocator, '"');
}

fn writeDoctorReport(allocator: std.mem.Allocator, output_path: []const u8, socket_path: []const u8, config: DoctorConfig) !void {
    var report_config = config;
    report_config.severity_min = .info;
    report_config.json = true;
    report_config.lint = true;

    var findings = try doctorFindingsAlloc(allocator, socket_path, report_config);
    defer findings.deinit(allocator);
    defer deinitDoctorFindings(allocator, findings.items);
    const doctor_json = try doctorFindingsJsonAlloc(allocator, findings.items, report_config);
    defer allocator.free(doctor_json);
    const doctor_json_trimmed = std.mem.trim(u8, doctor_json, " \t\r\n");

    const config_path = try cli_util.defaultConfigPath(allocator);
    defer allocator.free(config_path);
    const log_path = paths.defaultLogPath(allocator) catch null;
    defer if (log_path) |path| allocator.free(path);

    const config_text = try reportConfigRedactedAlloc(allocator, config_path);
    defer allocator.free(config_text);
    const log_text = if (log_path) |path| try reportLogRedactedAlloc(allocator, path) else try allocator.dupe(u8, "status: unsupported log platform\n");
    defer allocator.free(log_text);
    const metrics = client.requestAlloc(allocator, socket_path, "{\"v\":1,\"op\":\"metrics\",\"request_id\":\"doctor-report-metrics\"}") catch try allocator.dupe(u8, "{}");
    defer allocator.free(metrics);

    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);
    try cli_util.appendFmt(allocator, &out, "{{\"version\":1,\"generated_at_unix\":{d},\"socket\":", .{std.time.timestamp()});
    try appendJsonString(allocator, &out, socket_path);
    try out.appendSlice(allocator, ",\"config_path\":");
    try appendJsonString(allocator, &out, config_path);
    try out.appendSlice(allocator, ",\"doctor\":");
    try out.appendSlice(allocator, doctor_json_trimmed);
    try out.appendSlice(allocator, ",\"checks\":");
    try appendDoctorChecksJson(allocator, &out, report_config);
    try out.appendSlice(allocator, ",\"config_redacted\":");
    try appendJsonString(allocator, &out, config_text);
    try out.appendSlice(allocator, ",\"log_tail_redacted\":");
    try appendJsonString(allocator, &out, log_text);
    try out.appendSlice(allocator, ",\"metrics\":");
    try out.appendSlice(allocator, std.mem.trim(u8, metrics, " \t\r\n"));
    try out.appendSlice(allocator, "}\n");

    if (std.fs.path.dirname(output_path)) |parent| try std.fs.cwd().makePath(parent);
    var file = try std.fs.cwd().createFile(output_path, .{ .truncate = true });
    defer file.close();
    try file.writeAll(out.items);
}

fn appendDoctorChecksJson(allocator: std.mem.Allocator, out: *std.ArrayList(u8), config: DoctorConfig) !void {
    try out.append(allocator, '[');
    var emitted: usize = 0;
    for (doctor_checks) |check| {
        if (!checkAllowed(config, check.id)) continue;
        if (emitted != 0) try out.append(allocator, ',');
        emitted += 1;
        try out.appendSlice(allocator, "{\"id\":");
        try appendJsonString(allocator, out, check.id);
        try out.appendSlice(allocator, ",\"category\":");
        try appendJsonString(allocator, out, check.category);
        try cli_util.appendFmt(allocator, out, ",\"online\":{}", .{check.online});
        try out.appendSlice(allocator, ",\"docs_url\":");
        try appendJsonString(allocator, out, check.docs_url);
        try out.append(allocator, '}');
    }
    try out.append(allocator, ']');
}

fn countFindingsAtLeast(findings: []const DoctorFinding, severity_min: Severity) usize {
    var count: usize = 0;
    for (findings) |finding| {
        if (severityAtLeast(finding.severity, severity_min)) count += 1;
    }
    return count;
}

fn countSummary(findings: []const DoctorFinding) DoctorSummary {
    var summary = DoctorSummary{};
    for (findings) |finding| {
        switch (finding.severity) {
            .info => summary.info += 1,
            .warning => summary.warning += 1,
            .@"error" => summary.@"error" += 1,
        }
    }
    return summary;
}

fn countChecksRun(config: DoctorConfig) usize {
    var count: usize = 0;
    for (doctor_checks) |check| {
        if (check.online and !config.online) continue;
        if (!checkAllowed(config, check.id)) continue;
        count += 1;
    }
    return count;
}

fn severityAtLeast(severity: Severity, severity_min: Severity) bool {
    return @intFromEnum(severity) >= @intFromEnum(severity_min);
}

fn severityName(severity: Severity) []const u8 {
    return switch (severity) {
        .info => "info",
        .warning => "warning",
        .@"error" => "error",
    };
}

fn parseSeverity(value: []const u8) ?Severity {
    if (std.mem.eql(u8, value, "info")) return .info;
    if (std.mem.eql(u8, value, "warning")) return .warning;
    if (std.mem.eql(u8, value, "error")) return .@"error";
    return null;
}

fn requiredZigVersionAlloc(allocator: std.mem.Allocator) !?[]u8 {
    const source = std.fs.cwd().readFileAlloc(allocator, "build.zig.zon", 64 * 1024) catch |err| switch (err) {
        error.FileNotFound => return null,
        else => return err,
    };
    defer allocator.free(source);
    const key_index = std.mem.indexOf(u8, source, ".minimum_zig_version") orelse return null;
    const tail = source[key_index..];
    const first_quote = std.mem.indexOfScalar(u8, tail, '"') orelse return null;
    const rest = tail[first_quote + 1 ..];
    const second_quote = std.mem.indexOfScalar(u8, rest, '"') orelse return null;
    return @as(?[]u8, try allocator.dupe(u8, rest[0..second_quote]));
}

fn commandOutputTrimmedAlloc(allocator: std.mem.Allocator, argv: []const []const u8) ![]u8 {
    const result = try std.process.Child.run(.{
        .allocator = allocator,
        .argv = argv,
        .max_output_bytes = 1024 * 1024,
        .expand_arg0 = .expand,
    });
    defer allocator.free(result.stdout);
    defer allocator.free(result.stderr);
    if (!cli_util.exitedZero(result.term)) return error.CommandFailed;
    const raw = if (result.stdout.len != 0) result.stdout else result.stderr;
    const trimmed = std.mem.trim(u8, raw, " \t\r\n");
    return allocator.dupe(u8, trimmed);
}

fn pathExecutable(path: []const u8) bool {
    const stat = std.fs.cwd().statFile(path) catch return false;
    if (stat.kind != .file) return false;
    if (builtin.os.tag == .windows) return true;
    return (stat.mode & 0o111) != 0;
}

fn parsedConfigOrNull(allocator: std.mem.Allocator, config_path: []const u8) ?shisa_config.Config {
    const source = cli_util.readConfigOrDefault(allocator, config_path) catch return null;
    defer allocator.free(source);
    var diagnostic: shisa_config.Diagnostic = .{};
    return shisa_config.parse(allocator, source, &diagnostic) catch null;
}

fn hasAncestorMarkerAlloc(allocator: std.mem.Allocator, cwd: []const u8, marker: []const u8) !bool {
    var current = try allocator.dupe(u8, cwd);
    defer allocator.free(current);
    while (true) {
        const candidate = try std.fs.path.join(allocator, &.{ current, marker });
        const present = std.mem.eql(u8, pathAccessStatus(candidate), "present");
        allocator.free(candidate);
        if (present) return true;
        const parent = std.fs.path.dirname(current) orelse return false;
        if (std.mem.eql(u8, parent, current)) return false;
        const next = try allocator.dupe(u8, parent);
        allocator.free(current);
        current = next;
    }
}

fn countOccurrences(haystack: []const u8, needle: []const u8) usize {
    if (needle.len == 0) return 0;
    var count: usize = 0;
    var offset: usize = 0;
    while (offset <= haystack.len) {
        const found = std.mem.indexOf(u8, haystack[offset..], needle) orelse break;
        count += 1;
        offset += found + needle.len;
    }
    return count;
}

fn shisaBinPathAlloc(allocator: std.mem.Allocator) ![]u8 {
    const env = std.process.getEnvVarOwned(allocator, "SHISA_BIN") catch |err| switch (err) {
        error.EnvironmentVariableNotFound => null,
        else => return err,
    };
    if (env) |path| return path;
    return std.fs.selfExePathAlloc(allocator);
}

fn shisaBinStatusAlloc(allocator: std.mem.Allocator, shisa_bin: []const u8) ![]u8 {
    const result = std.process.Child.run(.{
        .allocator = allocator,
        .argv = &.{ shisa_bin, "--version" },
        .max_output_bytes = 64 * 1024,
        .expand_arg0 = .expand,
    }) catch |err| switch (err) {
        error.FileNotFound => return allocator.dupe(u8, "missing"),
        else => return std.fmt.allocPrint(allocator, "error ({s})", .{@errorName(err)}),
    };
    defer allocator.free(result.stdout);
    defer allocator.free(result.stderr);
    return allocator.dupe(u8, if (cli_util.exitedZero(result.term)) "ok" else "error");
}

fn samplePromptAlloc(allocator: std.mem.Allocator, socket_path: []const u8, shell_name: []const u8, daemon_status: []const u8) !?[]u8 {
    if (!std.mem.eql(u8, daemon_status, "ok")) return null;
    const cwd = std.fs.cwd().realpathAlloc(allocator, ".") catch return null;
    defer allocator.free(cwd);
    const payload = prompt_payload.buildPromptPayload(allocator, .{ .shell = shell_name }, cwd) catch return null;
    defer allocator.free(payload);
    const response = client.requestAlloc(allocator, socket_path, payload) catch return null;
    defer allocator.free(response);
    var parsed = std.json.parseFromSlice(proto.Response, allocator, response, .{ .ignore_unknown_fields = true }) catch return null;
    defer parsed.deinit();
    return @as(?[]u8, try allocator.dupe(u8, parsed.value.prompt));
}

fn activeConfiguredVpnSegmentAlloc(allocator: std.mem.Allocator, config_path: []const u8) !?[]u8 {
    const source = cli_util.readConfigOrDefault(allocator, config_path) catch return null;
    defer allocator.free(source);
    var diagnostic: shisa_config.Diagnostic = .{};
    var parsed = shisa_config.parse(allocator, source, &diagnostic) catch return null;
    defer parsed.deinit(allocator);
    if (!configHasModule(parsed.prompt_modules, .vpn_status) and !configHasModule(parsed.right_prompt_modules, .vpn_status)) return null;
    return vpn_status_module.render(allocator) catch null;
}

fn configHasModule(modules: []const shisa_config.ModuleId, module_id: shisa_config.ModuleId) bool {
    for (modules) |candidate| {
        if (candidate == module_id) return true;
    }
    return false;
}

fn applyDoctorFixes(allocator: std.mem.Allocator, socket_path: []const u8, yes: bool) !void {
    const config_dir = try cli_util.configDirPath(allocator);
    defer allocator.free(config_dir);
    const daemon_status = try daemonHealthStatusAlloc(allocator, socket_path);
    defer allocator.free(daemon_status);
    const config_dir_permissions = try configDirPermissionsStatusAlloc(allocator, config_dir);
    defer allocator.free(config_dir_permissions);
    const context = DoctorContext{
        .socket_path = socket_path,
        .socket_status = pathAccessStatus(socket_path),
        .daemon_status = daemon_status,
        .config_dir = config_dir,
        .config_dir_permissions = config_dir_permissions,
        .shell_hook_status = shellHookStatus(allocator),
        .nerd_font_status = nerdFontStatus(),
    };
    const issues = try doctorIssuesAlloc(allocator, context);
    defer allocator.free(issues);

    var fixed: usize = 0;
    for (issues) |issue| {
        if (!yes and !try promptApplyFix(allocator, issue)) continue;
        issue.fix(allocator, context) catch |err| {
            try doctorStderrFmt(allocator, "fix {s} failed: {s}\n", .{ issue.id, @errorName(err) });
            continue;
        };
        fixed += 1;
    }
    try doctorStdoutFmt(allocator, "fixed {d} of {d} issues\n", .{ fixed, issues.len });
}

fn promptApplyFix(allocator: std.mem.Allocator, issue: DoctorIssue) !bool {
    try doctorStdoutFmt(allocator, "{s}\nApply fix? [y/N] ", .{issue.message});
    var buffer: [8]u8 = undefined;
    const read = try std.fs.File.stdin().read(&buffer);
    if (read == 0) return false;
    return buffer[0] == 'y' or buffer[0] == 'Y';
}

fn doctorStdoutFmt(allocator: std.mem.Allocator, comptime format: []const u8, args: anytype) !void {
    const text = try std.fmt.allocPrint(allocator, format, args);
    defer allocator.free(text);
    try std.fs.File.stdout().writeAll(text);
}

fn doctorStderrFmt(allocator: std.mem.Allocator, comptime format: []const u8, args: anytype) !void {
    const text = try std.fmt.allocPrint(allocator, format, args);
    defer allocator.free(text);
    try std.fs.File.stderr().writeAll(text);
}

fn doctorIssuesAlloc(allocator: std.mem.Allocator, context: DoctorContext) ![]DoctorIssue {
    var issues: std.ArrayList(DoctorIssue) = .empty;
    errdefer issues.deinit(allocator);
    if (std.mem.eql(u8, context.shell_hook_status, "missing")) {
        try issues.append(allocator, .{ .id = "shell_hook", .message = "shell hook is not installed", .fix = fixShellHook });
    }
    if (std.mem.eql(u8, context.socket_status, "present") and !std.mem.eql(u8, context.daemon_status, "ok")) {
        try issues.append(allocator, .{ .id = "stale_socket", .message = "socket exists but daemon is not reachable", .fix = fixStaleSocket });
    }
    if (!std.mem.eql(u8, context.daemon_status, "ok")) {
        try issues.append(allocator, .{ .id = "daemon", .message = "daemon is not running", .fix = fixDaemon });
    }
    if (std.mem.startsWith(u8, context.config_dir_permissions, "wrong")) {
        try issues.append(allocator, .{ .id = "config_dir_permissions", .message = "config directory permissions are too broad", .fix = fixConfigDirPermissions });
    }
    if (std.mem.eql(u8, context.nerd_font_status, "missing")) {
        try issues.append(allocator, .{ .id = "nerd_font", .message = "Nerd Font is not detected", .fix = fixNerdFont });
    }
    return issues.toOwnedSlice(allocator);
}

fn doctorPluginsStatusAlloc(allocator: std.mem.Allocator, plugins_dir: []const u8) ![]u8 {
    var dir = std.fs.openDirAbsolute(plugins_dir, .{ .iterate = true }) catch |err| switch (err) {
        error.FileNotFound => return allocator.dupe(u8, "none"),
        else => return std.fmt.allocPrint(allocator, "unreadable ({s})", .{@errorName(err)}),
    };
    defer dir.close();

    var names: std.ArrayList([]u8) = .empty;
    defer {
        for (names.items) |name| allocator.free(name);
        names.deinit(allocator);
    }

    var it = dir.iterate();
    while (try it.next()) |entry| {
        if (entry.kind != .directory) continue;
        if (!plugin_manifest.isValidPluginName(entry.name)) continue;
        try names.append(allocator, try allocator.dupe(u8, entry.name));
    }
    if (names.items.len == 0) return allocator.dupe(u8, "none");

    std.mem.sort([]u8, names.items, {}, lessThanString);
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);
    for (names.items, 0..) |name, i| {
        if (i != 0) try out.appendSlice(allocator, ",");
        try out.appendSlice(allocator, name);
    }
    return out.toOwnedSlice(allocator);
}

fn transientStatusAlloc(allocator: std.mem.Allocator, config_path: []const u8, shell_hook_status: []const u8) ![]u8 {
    const source = cli_util.readConfigOrDefault(allocator, config_path) catch return allocator.dupe(u8, "unknown");
    defer allocator.free(source);
    var diagnostic: shisa_config.Diagnostic = .{};
    var parsed = shisa_config.parse(allocator, source, &diagnostic) catch return allocator.dupe(u8, "unknown");
    defer parsed.deinit(allocator);
    if (parsed.transient_prompt == null) return allocator.dupe(u8, "off");
    if (std.mem.eql(u8, shell_hook_status, "present")) return allocator.dupe(u8, "on");
    return allocator.dupe(u8, "config-only");
}

fn appendDoctorDeprecations(allocator: std.mem.Allocator, out: *std.ArrayList(u8), config_path: []const u8) !void {
    const source = cli_util.readConfigOrDefault(allocator, config_path) catch |err| {
        try cli_util.appendFmt(allocator, out, "deprecations: unreadable ({s})\n", .{@errorName(err)});
        return;
    };
    defer allocator.free(source);

    const warnings = try deprecationWarningsAlloc(allocator, source, active_deprecation_rules[0..]);
    defer allocator.free(warnings);
    try out.appendSlice(allocator, warnings);
}

fn deprecationWarningsAlloc(allocator: std.mem.Allocator, source: []const u8, rules: []const DeprecationRule) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    var count: usize = 0;
    for (rules) |rule| {
        if (std.mem.indexOf(u8, source, rule.pattern) == null) continue;
        try cli_util.appendFmt(
            allocator,
            &out,
            "deprecation: {s} `{s}` deprecated since {s}; use `{s}`; remove before {s}\n",
            .{ rule.kind, rule.pattern, rule.since, rule.replacement, rule.remove_before },
        );
        count += 1;
    }
    if (count == 0) try out.appendSlice(allocator, "deprecations: none\n");
    return out.toOwnedSlice(allocator);
}

const report_max_log_bytes = 1024 * 1024;
const report_bench_iterations = 8;

const report_help_text =
    \\usage: shisa report [--output path]
    \\
    \\options:
    \\  -o, --output <path> write bundle path; defaults to ./shisa-report-<timestamp>.tar.gz
    \\
;

pub const ReportBench = struct {
    version: []const u8,
    iteration: *const fn (std.mem.Allocator) anyerror![]u8,
};

const ReportConfig = struct {
    output_path: ?[]const u8 = null,
};

pub fn reportCommand(allocator: std.mem.Allocator, args: []const []const u8, bench: ReportBench) !void {
    if (args.len == 1 and (std.mem.eql(u8, args[0], "--help") or std.mem.eql(u8, args[0], "-h"))) {
        try std.fs.File.stdout().writeAll(report_help_text);
        return;
    }

    const config = try parseReportArgs(args);
    const output_path = if (config.output_path) |path| path else try defaultReportPathAlloc(allocator);
    defer if (config.output_path == null) allocator.free(output_path);

    const staging_dir = try reportStagingDirAlloc(allocator);
    defer allocator.free(staging_dir);
    defer std.fs.cwd().deleteTree(staging_dir) catch {};
    try std.fs.cwd().makePath(staging_dir);

    try writeReportBundleFiles(allocator, staging_dir, bench);
    try createReportArchive(allocator, staging_dir, output_path);

    const message = try std.fmt.allocPrint(allocator, "wrote {s}\n", .{output_path});
    defer allocator.free(message);
    try std.fs.File.stdout().writeAll(message);
}

fn parseReportArgs(args: []const []const u8) !ReportConfig {
    var config = ReportConfig{};
    var i: usize = 0;
    while (i < args.len) : (i += 1) {
        if (std.mem.eql(u8, args[i], "--output") or std.mem.eql(u8, args[i], "-o")) {
            config.output_path = try cli_util.nextValue(args, &i);
        } else {
            return error.UnknownReportArgument;
        }
    }
    return config;
}

fn defaultReportPathAlloc(allocator: std.mem.Allocator) ![]u8 {
    return std.fmt.allocPrint(allocator, "shisa-report-{d}.tar.gz", .{std.time.timestamp()});
}

fn reportStagingDirAlloc(allocator: std.mem.Allocator) ![]u8 {
    return std.fmt.allocPrint(allocator, "/tmp/shisa-report-{x}", .{std.crypto.random.int(u64)});
}

fn writeReportBundleFiles(allocator: std.mem.Allocator, staging_dir: []const u8, bench: ReportBench) !void {
    const config_path = try cli_util.defaultConfigPath(allocator);
    defer allocator.free(config_path);
    const log_path = try paths.defaultLogPath(allocator);
    defer allocator.free(log_path);

    const manifest = try reportManifestAlloc(allocator, config_path, log_path);
    defer allocator.free(manifest);
    try writeReportFile(allocator, staging_dir, "README.txt", manifest);

    const config_text = try reportConfigRedactedAlloc(allocator, config_path);
    defer allocator.free(config_text);
    try writeReportFile(allocator, staging_dir, "config.redacted.toml", config_text);

    const log_text = try reportLogRedactedAlloc(allocator, log_path);
    defer allocator.free(log_text);
    try writeReportFile(allocator, staging_dir, "shisad.log.redacted", log_text);

    const bench_text = try reportBenchAlloc(allocator, bench);
    defer allocator.free(bench_text);
    try writeReportFile(allocator, staging_dir, "bench.txt", bench_text);
}

fn reportManifestAlloc(allocator: std.mem.Allocator, config_path: []const u8, log_path: []const u8) ![]u8 {
    return std.fmt.allocPrint(allocator,
        \\Shisa support bundle
        \\
        \\Files:
        \\- config.redacted.toml: active config from {s}, or built-in defaults when missing
        \\- shisad.log.redacted: last 1MiB of {s}, or missing/unreadable status
        \\- bench.txt: local prompt payload microbench metadata
        \\
        \\Redaction:
        \\Values matching documented secret patterns are replaced with [redacted] before archive creation.
        \\
    , .{ config_path, log_path });
}

fn reportConfigRedactedAlloc(allocator: std.mem.Allocator, config_path: []const u8) ![]u8 {
    const raw = try cli_util.readConfigOrDefault(allocator, config_path);
    defer allocator.free(raw);
    return redactReportDataAlloc(allocator, raw);
}

fn reportLogRedactedAlloc(allocator: std.mem.Allocator, log_path: []const u8) ![]u8 {
    const raw = readFileTailAlloc(allocator, log_path, report_max_log_bytes) catch |err| switch (err) {
        error.FileNotFound => return std.fmt.allocPrint(allocator, "log_path: {s}\nstatus: missing\n", .{log_path}),
        else => return std.fmt.allocPrint(allocator, "log_path: {s}\nstatus: unreadable\nerror: {s}\n", .{ log_path, @errorName(err) }),
    };
    defer allocator.free(raw);
    return redactReportDataAlloc(allocator, raw);
}

fn redactReportDataAlloc(allocator: std.mem.Allocator, data: []const u8) ![]u8 {
    return redact.redactAlloc(allocator, data);
}

fn readFileTailAlloc(allocator: std.mem.Allocator, path: []const u8, max_bytes: usize) ![]u8 {
    var file = try std.fs.openFileAbsolute(path, .{});
    defer file.close();
    const end = try file.getEndPos();
    const start = if (end > max_bytes) end - max_bytes else 0;
    try file.seekTo(start);
    return file.readToEndAlloc(allocator, max_bytes);
}

fn reportBenchAlloc(allocator: std.mem.Allocator, bench: ReportBench) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);
    try cli_util.appendFmt(allocator, &out, "version: {s}\n", .{bench.version});
    try cli_util.appendFmt(allocator, &out, "os: {s}\n", .{@tagName(builtin.os.tag)});
    try cli_util.appendFmt(allocator, &out, "iterations: {d}\n", .{report_bench_iterations});

    var total_ns: u64 = 0;
    var min_ns: u64 = std.math.maxInt(u64);
    var max_ns: u64 = 0;
    for (0..report_bench_iterations) |_| {
        const start = std.time.nanoTimestamp();
        const payload = bench.iteration(allocator) catch |err| {
            try cli_util.appendFmt(allocator, &out, "status: failed\nerror: {s}\n", .{@errorName(err)});
            return out.toOwnedSlice(allocator);
        };
        defer allocator.free(payload);
        const elapsed: u64 = @intCast(std.time.nanoTimestamp() - start);
        total_ns += elapsed;
        min_ns = @min(min_ns, elapsed);
        max_ns = @max(max_ns, elapsed);
    }
    try out.appendSlice(allocator, "status: ok\n");
    try cli_util.appendFmt(allocator, &out, "avg_ns: {d}\n", .{total_ns / report_bench_iterations});
    try cli_util.appendFmt(allocator, &out, "min_ns: {d}\n", .{min_ns});
    try cli_util.appendFmt(allocator, &out, "max_ns: {d}\n", .{max_ns});
    return out.toOwnedSlice(allocator);
}

fn writeReportFile(allocator: std.mem.Allocator, staging_dir: []const u8, name: []const u8, data: []const u8) !void {
    const path = try std.fs.path.join(allocator, &.{ staging_dir, name });
    defer allocator.free(path);
    var file = try std.fs.createFileAbsolute(path, .{ .truncate = true });
    defer file.close();
    try file.writeAll(data);
}

fn createReportArchive(allocator: std.mem.Allocator, staging_dir: []const u8, output_path: []const u8) !void {
    const result = std.process.Child.run(.{
        .allocator = allocator,
        .argv = &.{ "tar", "-czf", output_path, "-C", staging_dir, "." },
        .max_output_bytes = 1024 * 1024,
        .expand_arg0 = .expand,
    }) catch |err| switch (err) {
        error.FileNotFound => {
            try std.fs.File.stderr().writeAll("shisa report: tar not found in PATH\n");
            return err;
        },
        else => return err,
    };
    defer allocator.free(result.stdout);
    defer allocator.free(result.stderr);
    try std.fs.File.stderr().writeAll(result.stderr);
    if (!cli_util.exitedZero(result.term)) return error.ReportArchiveFailed;
}

test "report args parse output path" {
    const config = try parseReportArgs(&.{ "--output", "/tmp/shisa-report.tar.gz" });
    try std.testing.expectEqualStrings("/tmp/shisa-report.tar.gz", config.output_path.?);
}

test "report redaction scrubs documented patterns" {
    const input =
        \\password = "hunter2"
        \\Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig
        \\AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE
        \\aws_secret_access_key = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
        \\github=ghp_abcdefghijklmnopqrstuvwxyz1234567890
        \\openai=sk-abcdefghijklmnopqrst
        \\account=123456789012
        \\IdentityFile ~/.ssh/id_rsa
        \\client-key-data: kube-secret
        \\-----BEGIN OPENSSH PRIVATE KEY-----
        \\abc123
        \\-----END OPENSSH PRIVATE KEY-----
        \\
    ;
    const output = try redactReportDataAlloc(std.testing.allocator, input);
    defer std.testing.allocator.free(output);

    inline for (.{
        "hunter2",
        "eyJhbGciOiJIUzI1NiJ9.payload.sig",
        "AKIAIOSFODNN7EXAMPLE",
        "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        "ghp_abcdefghijklmnopqrstuvwxyz1234567890",
        "sk-abcdefghijklmnopqrst",
        "123456789012",
        "~/.ssh/id_rsa",
        "kube-secret",
        "abc123",
    }) |secret| {
        try std.testing.expect(std.mem.indexOf(u8, output, secret) == null);
    }
    try std.testing.expect(std.mem.indexOf(u8, output, redact.marker) != null);
}

fn pathAccessStatus(path: []const u8) []const u8 {
    std.fs.cwd().access(path, .{}) catch |err| switch (err) {
        error.FileNotFound => return "missing",
        error.AccessDenied => return "denied",
        else => return "error",
    };
    return "present";
}

fn configDirPermissionsStatusAlloc(allocator: std.mem.Allocator, config_dir: []const u8) ![]u8 {
    if (builtin.os.tag == .windows) return allocator.dupe(u8, "unsupported");
    const stat = std.fs.cwd().statFile(config_dir) catch |err| switch (err) {
        error.FileNotFound => return allocator.dupe(u8, "missing"),
        else => return std.fmt.allocPrint(allocator, "error ({s})", .{@errorName(err)}),
    };
    const mode = stat.mode & 0o777;
    if (mode == 0o700) return allocator.dupe(u8, "ok");
    return std.fmt.allocPrint(allocator, "wrong ({o})", .{mode});
}

fn shellHookStatus(allocator: std.mem.Allocator) []const u8 {
    return if (cli_config.shellHookInstalled(allocator)) "ok" else "missing";
}

fn nerdFontStatus() []const u8 {
    if (std.process.getEnvVarOwned(std.heap.page_allocator, "SHISA_NERD_FONT")) |value| {
        defer std.heap.page_allocator.free(value);
        if (std.mem.eql(u8, value, "1") or std.mem.eql(u8, value, "true")) return "ok";
        if (std.mem.eql(u8, value, "0") or std.mem.eql(u8, value, "false")) return "missing";
    } else |_| {}
    if (std.process.getEnvVarOwned(std.heap.page_allocator, "SHISA_GLYPH_CAPS")) |value| {
        defer std.heap.page_allocator.free(value);
        if (std.mem.eql(u8, value, "nerdfont")) return "ok";
        if (std.mem.eql(u8, value, "ascii")) return "missing";
    } else |_| {}
    return "unknown";
}

fn fixShellHook(allocator: std.mem.Allocator, _: DoctorContext) !void {
    const path = try cli_config.writeShellHook(allocator);
    defer allocator.free(path);
    try doctorStdoutFmt(allocator, "fixed shell_hook: wrote {s}\n", .{path});
}

fn fixStaleSocket(allocator: std.mem.Allocator, context: DoctorContext) !void {
    if (try socketHasOwner(allocator, context.socket_path)) return error.SocketOwned;
    std.fs.cwd().deleteFile(context.socket_path) catch |err| switch (err) {
        error.FileNotFound => {},
        else => return err,
    };
    try doctorStdoutFmt(allocator, "fixed stale_socket: removed {s}\n", .{context.socket_path});
}

fn fixDaemon(allocator: std.mem.Allocator, context: DoctorContext) !void {
    const shisad = try shisadPathAlloc(allocator);
    defer allocator.free(shisad);
    const result = try std.process.Child.run(.{
        .allocator = allocator,
        .argv = &.{ shisad, "--daemonize", "--socket", context.socket_path },
        .max_output_bytes = 64 * 1024,
        .expand_arg0 = .expand,
    });
    defer allocator.free(result.stdout);
    defer allocator.free(result.stderr);
    try std.fs.File.stderr().writeAll(result.stderr);
    if (!cli_util.exitedZero(result.term)) return error.DaemonStartFailed;
    try doctorStdoutFmt(allocator, "fixed daemon: started {s}\n", .{shisad});
}

fn fixConfigDirPermissions(allocator: std.mem.Allocator, context: DoctorContext) !void {
    const result = try std.process.Child.run(.{
        .allocator = allocator,
        .argv = &.{ "chmod", "0700", context.config_dir },
        .max_output_bytes = 64 * 1024,
        .expand_arg0 = .expand,
    });
    defer allocator.free(result.stdout);
    defer allocator.free(result.stderr);
    try std.fs.File.stderr().writeAll(result.stderr);
    if (!cli_util.exitedZero(result.term)) return error.ChmodFailed;
    try doctorStdoutFmt(allocator, "fixed config_dir_permissions: chmod 0700 {s}\n", .{context.config_dir});
}

fn fixNerdFont(allocator: std.mem.Allocator, _: DoctorContext) !void {
    try doctorStdoutFmt(allocator, "install Nerd Font: {s}\n", .{nerdFontInstallCommand()});
}

fn nerdFontInstallCommand() []const u8 {
    return switch (builtin.os.tag) {
        .macos => "brew install --cask font-hack-nerd-font",
        .linux => "install a Nerd Font package for your distro, then run fc-cache -f",
        .windows => "winget install NerdFonts.Hack",
        else => "download a Nerd Font from https://www.nerdfonts.com/font-downloads",
    };
}

fn socketHasOwner(allocator: std.mem.Allocator, socket_path: []const u8) !bool {
    if (runOwnerProbe(allocator, &.{ "lsof", "-t", socket_path })) |owned| return owned else |err| switch (err) {
        error.FileNotFound => {},
        else => return err,
    }
    if (runOwnerProbe(allocator, &.{ "fuser", socket_path })) |owned| return owned else |err| switch (err) {
        error.FileNotFound => return error.NoSocketOwnerTool,
        else => return err,
    }
}

fn socketOwnerStatusAlloc(allocator: std.mem.Allocator, socket_path: []const u8) ![]u8 {
    if (!std.mem.eql(u8, pathAccessStatus(socket_path), "present")) return allocator.dupe(u8, "none");
    if (runOwnerProbeTextAlloc(allocator, &.{ "lsof", "-t", socket_path })) |owned| return owned else |err| switch (err) {
        error.FileNotFound => {},
        else => return err,
    }
    if (runOwnerProbeTextAlloc(allocator, &.{ "fuser", socket_path })) |owned| return owned else |err| switch (err) {
        error.FileNotFound => return allocator.dupe(u8, "unknown"),
        else => return err,
    }
}

fn runOwnerProbeTextAlloc(allocator: std.mem.Allocator, argv: []const []const u8) ![]u8 {
    const result = try std.process.Child.run(.{
        .allocator = allocator,
        .argv = argv,
        .max_output_bytes = 64 * 1024,
        .expand_arg0 = .expand,
    });
    defer allocator.free(result.stdout);
    defer allocator.free(result.stderr);
    if (!cli_util.exitedZero(result.term)) return allocator.dupe(u8, "none");
    const trimmed = std.mem.trim(u8, if (result.stdout.len != 0) result.stdout else result.stderr, " \t\r\n");
    if (trimmed.len == 0) return allocator.dupe(u8, "none");
    return std.fmt.allocPrint(allocator, "pid:{s}", .{trimmed});
}

fn runOwnerProbe(allocator: std.mem.Allocator, argv: []const []const u8) !bool {
    const result = try std.process.Child.run(.{
        .allocator = allocator,
        .argv = argv,
        .max_output_bytes = 64 * 1024,
        .expand_arg0 = .expand,
    });
    defer allocator.free(result.stdout);
    defer allocator.free(result.stderr);
    return cli_util.exitedZero(result.term) and std.mem.trim(u8, result.stdout, " \t\r\n").len != 0;
}

fn shisadPathAlloc(allocator: std.mem.Allocator) ![]u8 {
    const self_path = try std.fs.selfExePathAlloc(allocator);
    defer allocator.free(self_path);
    const dir = std.fs.path.dirname(self_path) orelse return allocator.dupe(u8, "shisad");
    const candidate = try std.fs.path.join(allocator, &.{ dir, "shisad" });
    errdefer allocator.free(candidate);
    if (std.mem.eql(u8, pathAccessStatus(candidate), "present")) return candidate;
    allocator.free(candidate);
    return allocator.dupe(u8, "shisad");
}

fn daemonHealthStatusAlloc(allocator: std.mem.Allocator, socket_path: []const u8) ![]u8 {
    const stat = std.fs.cwd().statFile(socket_path) catch |err| switch (err) {
        error.FileNotFound => return allocator.dupe(u8, "socket-missing"),
        else => null,
    };
    if (stat) |file_stat| {
        if (file_stat.kind != .unix_domain_socket) return allocator.dupe(u8, "not-reachable (NotSocket)");
    }
    const response = client.requestAlloc(allocator, socket_path, "health\n") catch |err| return daemonHealthErrorStatusAlloc(allocator, err);
    defer allocator.free(response);
    const trimmed = std.mem.trim(u8, response, " \t\r\n");
    if (std.mem.eql(u8, trimmed, "ok")) return allocator.dupe(u8, "ok");
    return allocator.dupe(u8, "bad-response");
}

fn daemonHealthErrorStatusAlloc(allocator: std.mem.Allocator, err: anyerror) ![]u8 {
    return switch (err) {
        error.FileNotFound => allocator.dupe(u8, "socket-missing"),
        error.ConnectionRefused => std.fmt.allocPrint(allocator, "not-reachable ({s})", .{@errorName(err)}),
        error.WouldBlock, error.NetworkUnreachable => std.fmt.allocPrint(allocator, "not-reachable ({s})", .{@errorName(err)}),
        else => std.fmt.allocPrint(allocator, "error ({s})", .{@errorName(err)}),
    };
}

fn luaRuntimeStatus(allocator: std.mem.Allocator) []const u8 {
    var runtime = plugin_lua.Runtime.initSandboxed(allocator) catch |err| switch (err) {
        error.LuaUnavailable => return "unavailable",
        else => return "error",
    };
    runtime.deinit();
    return "available";
}

fn fsnotifyBackendName(backend: fsnotify.Backend) []const u8 {
    return switch (backend) {
        .fsevents => "fsevents",
        .inotify => "inotify",
        .windows => "ReadDirectoryChangesW",
        .unsupported => "unsupported",
    };
}

fn lessThanString(_: void, lhs: []const u8, rhs: []const u8) bool {
    return std.mem.lessThan(u8, lhs, rhs);
}

test "doctor args parse socket override" {
    const config = try parseDoctorArgs(&.{ "--socket", "/tmp/shisa.sock" });
    try std.testing.expectEqualStrings("/tmp/shisa.sock", config.socket_path.?);
}

test "doctor args parse fix mode" {
    const config = try parseDoctorArgs(&.{ "--fix", "--yes" });
    try std.testing.expect(config.fix);
    try std.testing.expect(config.yes);
}

test "doctor args parse lint json severity" {
    const config = try parseDoctorArgs(&.{ "--lint", "--json", "--severity-min", "info", "--list-checks", "--online", "--only", "daemon/not-running", "--skip", "tests/optional-prereqs", "--report", "/tmp/shisa-doctor.json" });
    try std.testing.expect(config.lint);
    try std.testing.expect(config.json);
    try std.testing.expect(config.list_checks);
    try std.testing.expect(config.online);
    try std.testing.expectEqual(Severity.info, config.severity_min);
    try std.testing.expectEqualStrings("daemon/not-running", config.only.?);
    try std.testing.expectEqualStrings("tests/optional-prereqs", config.skip.?);
    try std.testing.expectEqualStrings("/tmp/shisa-doctor.json", config.report_path.?);
}

test "doctor check filters and registry list are stable" {
    try std.testing.expect(checkAllowed(.{ .only = "daemon/not-running,config/invalid" }, "config/invalid"));
    try std.testing.expect(!checkAllowed(.{ .only = "daemon/not-running" }, "config/invalid"));
    try std.testing.expect(!checkAllowed(.{ .skip = "config/invalid" }, "config/invalid"));

    const output = try doctorChecksListAlloc(std.testing.allocator, .{ .only = "daemon/not-running" });
    defer std.testing.allocator.free(output);
    try std.testing.expect(std.mem.indexOf(u8, output, "daemon/not-running\tdaemon\tlocal") != null);
    try std.testing.expect(std.mem.indexOf(u8, output, "config/invalid") == null);
}

test "doctor finding serializers filter severity" {
    const findings = [_]DoctorFinding{
        .{ .id = "prompt/async-pending", .severity = .info, .category = "prompt", .message = "pending" },
        .{ .id = "daemon/not-running", .severity = .@"error", .category = "daemon", .message = "daemon down", .path = "/tmp/shisa.sock", .command = "shisad --foreground &", .fix_hint = "start daemon", .fixable = true, .docs_url = "docs/doctor.md#daemon" },
    };
    const text = try doctorFindingsTextAlloc(std.testing.allocator, findings[0..], .{ .severity_min = .warning });
    defer std.testing.allocator.free(text);
    try std.testing.expect(std.mem.indexOf(u8, text, "daemon/not-running") != null);
    try std.testing.expect(std.mem.indexOf(u8, text, "prompt/async-pending") == null);

    const json = try doctorFindingsJsonAlloc(std.testing.allocator, findings[0..], .{ .severity_min = .info });
    defer std.testing.allocator.free(json);
    try std.testing.expect(std.mem.indexOf(u8, json, "\"count\":2") != null);
    try std.testing.expect(std.mem.indexOf(u8, json, "\"version\":1") != null);
    try std.testing.expect(std.mem.indexOf(u8, json, "\"category\":\"daemon\"") != null);
    try std.testing.expect(std.mem.indexOf(u8, json, "\"commands\":[\"shisad --foreground &\"]") != null);
    try std.testing.expect(std.mem.indexOf(u8, json, "\"fixable\":true") != null);
    try std.testing.expect(std.mem.indexOf(u8, json, "\"fix_hint\":\"start daemon\"") != null);
}

test "doctor issue registry marks fixable failures" {
    const issues = try doctorIssuesAlloc(std.testing.allocator, .{
        .socket_path = "/tmp/stale.sock",
        .socket_status = "present",
        .daemon_status = "not-reachable (ConnectionRefused)",
        .config_dir = "/tmp/shisa",
        .config_dir_permissions = "wrong (755)",
        .shell_hook_status = "missing",
        .nerd_font_status = "missing",
    });
    defer std.testing.allocator.free(issues);
    try std.testing.expectEqual(@as(usize, 5), issues.len);
    try std.testing.expectEqualStrings("shell_hook", issues[0].id);
    try std.testing.expectEqualStrings("stale_socket", issues[1].id);
    try std.testing.expectEqualStrings("daemon", issues[2].id);
    try std.testing.expectEqualStrings("config_dir_permissions", issues[3].id);
    try std.testing.expectEqualStrings("nerd_font", issues[4].id);
}

test "doctor reports path and backend statuses" {
    try std.testing.expectEqualStrings("missing", pathAccessStatus("/tmp/shisa-doctor-missing"));
    try std.testing.expectEqualStrings("fsevents", fsnotifyBackendName(.fsevents));
    try std.testing.expectEqualStrings("inotify", fsnotifyBackendName(.inotify));
    try std.testing.expectEqualStrings("ReadDirectoryChangesW", fsnotifyBackendName(.windows));
}

test "doctor helper counts markers and checks" {
    try std.testing.expectEqual(@as(usize, 2), countOccurrences("a # >>> shisa >>> b # >>> shisa >>>", cli_config.shell_hook_marker_start));
    try std.testing.expect(countChecksRun(.{}) >= 30);
    try std.testing.expectEqual(@as(usize, 1), countChecksRun(.{ .only = "daemon/not-running" }));
}

test "doctor reports installed plugins" {
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();

    const dir_path = try tmp.dir.realpathAlloc(std.testing.allocator, ".");
    defer std.testing.allocator.free(dir_path);
    try tmp.dir.makePath("beta");
    try tmp.dir.makePath("alpha");
    try tmp.dir.makePath("Bad");

    const output = try doctorPluginsStatusAlloc(std.testing.allocator, dir_path);
    defer std.testing.allocator.free(output);
    try std.testing.expectEqualStrings("alpha,beta", output);
}

test "doctor transient status follows config and hook" {
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();
    try tmp.dir.writeFile(.{ .sub_path = "off.toml", .data = shisa_config.default_config_text });
    try tmp.dir.writeFile(.{
        .sub_path = "on.toml",
        .data =
        \\version = 1
        \\transient_prompt = "%~ >"
        \\
        ,
    });
    const off_path = try tmp.dir.realpathAlloc(std.testing.allocator, "off.toml");
    defer std.testing.allocator.free(off_path);
    const on_path = try tmp.dir.realpathAlloc(std.testing.allocator, "on.toml");
    defer std.testing.allocator.free(on_path);

    const off = try transientStatusAlloc(std.testing.allocator, off_path, "present");
    defer std.testing.allocator.free(off);
    const on = try transientStatusAlloc(std.testing.allocator, on_path, "present");
    defer std.testing.allocator.free(on);
    const config_only = try transientStatusAlloc(std.testing.allocator, on_path, "missing");
    defer std.testing.allocator.free(config_only);
    try std.testing.expectEqualStrings("off", off);
    try std.testing.expectEqualStrings("on", on);
    try std.testing.expectEqualStrings("config-only", config_only);
}

test "doctor reports missing daemon socket clearly" {
    const socket_path = try std.fmt.allocPrint(std.testing.allocator, "/tmp/shisa-doctor-missing-{x}.sock", .{std.crypto.random.int(u64)});
    defer std.testing.allocator.free(socket_path);
    std.fs.cwd().deleteFile(socket_path) catch {};

    const status = try daemonHealthStatusAlloc(std.testing.allocator, socket_path);
    defer std.testing.allocator.free(status);
    try std.testing.expectEqualStrings("socket-missing", status);
}

test "doctor deprecation scanner reports matching rules" {
    const rules = [_]DeprecationRule{.{
        .kind = "config",
        .pattern = "old_key",
        .replacement = "new_key",
        .since = "1.4.0",
        .remove_before = "2.0.0",
    }};
    const output = try deprecationWarningsAlloc(std.testing.allocator, "old_key = true\n", rules[0..]);
    defer std.testing.allocator.free(output);
    try std.testing.expect(std.mem.indexOf(u8, output, "deprecation: config `old_key` deprecated since 1.4.0") != null);
}

test "doctor deprecation scanner reports none" {
    const rules = [_]DeprecationRule{.{
        .kind = "config",
        .pattern = "old_key",
        .replacement = "new_key",
        .since = "1.4.0",
        .remove_before = "2.0.0",
    }};
    const output = try deprecationWarningsAlloc(std.testing.allocator, "new_key = true\n", rules[0..]);
    defer std.testing.allocator.free(output);
    try std.testing.expectEqualStrings("deprecations: none\n", output);
}
