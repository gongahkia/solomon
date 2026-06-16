const std = @import("std");
const builtin = @import("builtin");
const daemon_cache = @import("daemon/cache.zig");
const fsnotify = @import("daemon/fsnotify.zig");
const client = @import("shisa-client.zig");
const shisa_config = @import("config.zig");
const paths = @import("daemon/paths.zig");
const proto = @import("proto/types.zig");
const plugin_lua = @import("plugin/lua.zig");
const plugin_manifest = @import("plugin/manifest.zig");
const supervisor = @import("supervisor.zig");
const vcs_stack = @import("vcs/stack.zig");
const vcs_worktree = @import("vcs/worktree.zig");

const version = "0.1.0-dev";
const max_config_bytes = 1024 * 1024;

pub fn main() !void {
    var gpa_impl = std.heap.GeneralPurposeAllocator(.{}){};
    defer _ = gpa_impl.deinit();
    const allocator = gpa_impl.allocator();

    const args = try std.process.argsAlloc(allocator);
    defer std.process.argsFree(allocator, args);

    if (args.len == 1 or std.mem.eql(u8, args[1], "--help") or std.mem.eql(u8, args[1], "-h")) {
        try std.fs.File.stdout().writeAll(help_text);
        return;
    }

    if (std.mem.eql(u8, args[1], "--version")) {
        try std.fs.File.stdout().writeAll("shisa " ++ version ++ "\n");
        return;
    }

    if (std.mem.eql(u8, args[1], "supervisor")) {
        try supervisor.run(allocator, args[2..]);
        return;
    }

    if (std.mem.eql(u8, args[1], "init")) {
        try initConfig(allocator, args[2..]);
        return;
    }

    if (std.mem.eql(u8, args[1], "explain")) {
        try explainConfig(allocator, args[2..]);
        return;
    }

    if (std.mem.eql(u8, args[1], "doctor")) {
        try doctorCommand(allocator, args[2..]);
        return;
    }

    if (std.mem.eql(u8, args[1], "import-starship")) {
        try importStarship(allocator, args[2..]);
        return;
    }

    if (std.mem.eql(u8, args[1], "bench")) {
        try bench(allocator, args[2..]);
        return;
    }

    if (std.mem.eql(u8, args[1], "cache")) {
        try cacheCommand(allocator, args[2..]);
        return;
    }

    if (std.mem.eql(u8, args[1], "pin")) {
        try pinCommand(allocator, args[2..]);
        return;
    }

    if (std.mem.eql(u8, args[1], "plugin")) {
        try pluginCommand(allocator, args[2..]);
        return;
    }

    if (std.mem.eql(u8, args[1], "stack")) {
        try stackCommand(allocator, args[2..]);
        return;
    }

    if (std.mem.eql(u8, args[1], "worktrees")) {
        try worktreesCommand(allocator, args[2..]);
        return;
    }

    if (std.mem.eql(u8, args[1], "prompt")) {
        try prompt(allocator, args[2..]);
        return;
    }

    try std.fs.File.stderr().writeAll("shisa: unknown command; run `shisa --help`\n");
    return error.UnknownCommand;
}

test "smoke" {
    try std.testing.expect(true);
}

fn initConfig(allocator: std.mem.Allocator, args: []const []const u8) !void {
    if (args.len != 0) return error.UnknownInitArgument;

    const path = try defaultConfigPath(allocator);
    defer allocator.free(path);
    if (std.fs.path.dirname(path)) |parent| {
        try std.fs.cwd().makePath(parent);
    }

    var file = try std.fs.createFileAbsolute(path, .{ .exclusive = true });
    defer file.close();
    try file.writeAll(shisa_config.default_config_text);

    const message = try std.fmt.allocPrint(allocator, "wrote {s}\n", .{path});
    defer allocator.free(message);
    try std.fs.File.stdout().writeAll(message);
}

fn defaultConfigPath(allocator: std.mem.Allocator) ![]u8 {
    const xdg = std.process.getEnvVarOwned(allocator, "XDG_CONFIG_HOME") catch |err| switch (err) {
        error.EnvironmentVariableNotFound => null,
        else => return err,
    };
    if (xdg) |xdg_config_home| {
        defer allocator.free(xdg_config_home);
        return defaultConfigPathFromEnv(allocator, xdg_config_home, null);
    }

    const home = try std.process.getEnvVarOwned(allocator, "HOME");
    defer allocator.free(home);
    return defaultConfigPathFromEnv(allocator, null, home);
}

fn defaultConfigPathFromEnv(allocator: std.mem.Allocator, xdg_config_home: ?[]const u8, home: ?[]const u8) ![]u8 {
    if (xdg_config_home) |base| return std.fmt.allocPrint(allocator, "{s}/shisa/shisa.toml", .{base});
    if (home) |base| return std.fmt.allocPrint(allocator, "{s}/.config/shisa/shisa.toml", .{base});
    return error.MissingHome;
}

test "default config path prefers xdg" {
    const path = try defaultConfigPathFromEnv(std.testing.allocator, "/tmp/xdg", "/tmp/home");
    defer std.testing.allocator.free(path);
    try std.testing.expectEqualStrings("/tmp/xdg/shisa/shisa.toml", path);
}

test "default config path falls back to home" {
    const path = try defaultConfigPathFromEnv(std.testing.allocator, null, "/tmp/home");
    defer std.testing.allocator.free(path);
    try std.testing.expectEqualStrings("/tmp/home/.config/shisa/shisa.toml", path);
}

fn explainConfig(allocator: std.mem.Allocator, args: []const []const u8) !void {
    if (args.len != 0) return error.UnknownExplainArgument;

    const path = try defaultConfigPath(allocator);
    defer allocator.free(path);
    const source = try readConfigOrDefault(allocator, path);
    defer allocator.free(source);

    var diagnostic: shisa_config.Diagnostic = .{};
    var parsed = shisa_config.parse(allocator, source, &diagnostic) catch |err| switch (err) {
        error.InvalidConfig => {
            const message = try std.fmt.allocPrint(allocator, "{s}:{d}:{d}: {s}\n", .{ path, diagnostic.line, diagnostic.column, diagnostic.message });
            defer allocator.free(message);
            try std.fs.File.stderr().writeAll(message);
            return err;
        },
        else => return err,
    };
    defer parsed.deinit(allocator);

    const output = try explainAlloc(allocator, parsed);
    defer allocator.free(output);
    try std.fs.File.stdout().writeAll(output);
}

fn readConfigOrDefault(allocator: std.mem.Allocator, path: []const u8) ![]u8 {
    var file = std.fs.openFileAbsolute(path, .{}) catch |err| switch (err) {
        error.FileNotFound => return allocator.dupe(u8, shisa_config.default_config_text),
        else => return err,
    };
    defer file.close();
    return file.readToEndAlloc(allocator, max_config_bytes);
}

fn explainAlloc(allocator: std.mem.Allocator, parsed: shisa_config.Config) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);

    try appendFmt(allocator, &out, "theme: {s}\n", .{parsed.theme});
    try out.appendSlice(allocator, "pipeline:\n");
    for (parsed.prompt_modules, 0..) |module_id, index| {
        try appendFmt(
            allocator,
            &out,
            "  {d}. {s} ({s})\n",
            .{ index + 1, shisa_config.moduleIdName(module_id), shisa_config.moduleExecutionClass(module_id) },
        );
    }

    return out.toOwnedSlice(allocator);
}

fn appendFmt(allocator: std.mem.Allocator, out: *std.ArrayList(u8), comptime format: []const u8, args: anytype) !void {
    const line = try std.fmt.allocPrint(allocator, format, args);
    defer allocator.free(line);
    try out.appendSlice(allocator, line);
}

test "explain output dumps pipeline" {
    var diagnostic: shisa_config.Diagnostic = .{};
    var parsed = try shisa_config.parse(std.testing.allocator, shisa_config.default_config_text, &diagnostic);
    defer parsed.deinit(std.testing.allocator);

    const output = try explainAlloc(std.testing.allocator, parsed);
    defer std.testing.allocator.free(output);

    try std.testing.expect(std.mem.indexOf(u8, output, "theme: plain\n") != null);
    try std.testing.expect(std.mem.indexOf(u8, output, "1. cwd (sync)") != null);
    try std.testing.expect(std.mem.indexOf(u8, output, "2. git_branch (async)") != null);
}

const DoctorConfig = struct {
    socket_path: ?[]const u8 = null,
};

fn doctorCommand(allocator: std.mem.Allocator, args: []const []const u8) !void {
    const config = try parseDoctorArgs(args);
    const socket_path = if (config.socket_path) |path| path else try paths.defaultSocketPath(allocator);
    defer if (config.socket_path == null) allocator.free(socket_path);

    const output = try doctorOutputAlloc(allocator, socket_path);
    defer allocator.free(output);
    try std.fs.File.stdout().writeAll(output);
}

fn parseDoctorArgs(args: []const []const u8) !DoctorConfig {
    var config = DoctorConfig{};
    var i: usize = 0;
    while (i < args.len) : (i += 1) {
        if (std.mem.eql(u8, args[i], "--socket")) {
            config.socket_path = try nextValue(args, &i);
        } else {
            return error.UnknownDoctorArgument;
        }
    }
    return config;
}

fn doctorOutputAlloc(allocator: std.mem.Allocator, socket_path: []const u8) ![]u8 {
    const config_dir = try configDirPath(allocator);
    defer allocator.free(config_dir);
    const plugins_dir = try pluginsDirPath(allocator);
    defer allocator.free(plugins_dir);

    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);

    try appendFmt(allocator, &out, "socket: {s} {s}\n", .{ pathAccessStatus(socket_path), socket_path });
    try appendFmt(allocator, &out, "daemon: {s}\n", .{try daemonHealthStatus(allocator, socket_path)});
    try appendFmt(allocator, &out, "config_dir: {s} {s}\n", .{ pathAccessStatus(config_dir), config_dir });
    try appendFmt(allocator, &out, "plugins_dir: {s} {s}\n", .{ pathAccessStatus(plugins_dir), plugins_dir });
    try appendFmt(allocator, &out, "lua: {s}\n", .{luaRuntimeStatus(allocator)});
    try appendFmt(allocator, &out, "fsnotify: {s}\n", .{fsnotifyBackendName(fsnotify.selectBackend(builtin.os.tag))});

    if (builtin.os.tag == .linux) {
        const limit = fsnotify.readLinuxMaxUserWatches(allocator) catch null;
        if (limit) |value| {
            try appendFmt(allocator, &out, "inotify.max_user_watches: {d}\n", .{value});
        } else {
            try out.appendSlice(allocator, "inotify.max_user_watches: unknown\n");
        }
    }

    return out.toOwnedSlice(allocator);
}

fn configDirPath(allocator: std.mem.Allocator) ![]u8 {
    const config_path = try defaultConfigPath(allocator);
    defer allocator.free(config_path);
    const dir = std.fs.path.dirname(config_path) orelse return error.MissingConfigDir;
    return allocator.dupe(u8, dir);
}

fn pathAccessStatus(path: []const u8) []const u8 {
    std.fs.cwd().access(path, .{}) catch |err| switch (err) {
        error.FileNotFound => return "missing",
        error.AccessDenied => return "denied",
        else => return "error",
    };
    return "present";
}

fn daemonHealthStatus(allocator: std.mem.Allocator, socket_path: []const u8) ![]const u8 {
    const response = client.requestAlloc(allocator, socket_path, "health\n") catch return "unreachable";
    defer allocator.free(response);
    const trimmed = std.mem.trim(u8, response, " \t\r\n");
    if (std.mem.eql(u8, trimmed, "ok")) return "ok";
    return "bad-response";
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
        .unsupported => "unsupported",
    };
}

test "doctor args parse socket override" {
    const config = try parseDoctorArgs(&.{ "--socket", "/tmp/shisa.sock" });
    try std.testing.expectEqualStrings("/tmp/shisa.sock", config.socket_path.?);
}

test "doctor reports path and backend statuses" {
    try std.testing.expectEqualStrings("missing", pathAccessStatus("/tmp/shisa-doctor-missing"));
    try std.testing.expectEqualStrings("fsevents", fsnotifyBackendName(.fsevents));
    try std.testing.expectEqualStrings("inotify", fsnotifyBackendName(.inotify));
}

const StackConfig = struct {
    cwd: ?[]const u8 = null,
};

fn stackCommand(allocator: std.mem.Allocator, args: []const []const u8) !void {
    const config = try parseStackArgs(args);
    const cwd = if (config.cwd) |path| path else try std.fs.cwd().realpathAlloc(allocator, ".");
    defer if (config.cwd == null) allocator.free(cwd);

    const output = try stackOutputAlloc(allocator, cwd);
    defer allocator.free(output);
    try std.fs.File.stdout().writeAll(output);
}

fn parseStackArgs(args: []const []const u8) !StackConfig {
    var config = StackConfig{};
    var i: usize = 0;
    while (i < args.len) : (i += 1) {
        if (std.mem.eql(u8, args[i], "--cwd")) {
            config.cwd = try nextValue(args, &i);
        } else {
            return error.UnknownStackArgument;
        }
    }
    return config;
}

fn stackOutputAlloc(allocator: std.mem.Allocator, cwd_path: []const u8) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);

    var detection = (try vcs_stack.detect(allocator, cwd_path)) orelse {
        try out.appendSlice(allocator, "stack: none\n");
        return out.toOwnedSlice(allocator);
    };
    defer detection.deinit(allocator);

    try appendFmt(allocator, &out, "provider: {s}\n", .{detection.provider.label()});
    try appendFmt(allocator, &out, "root: {s}\n", .{detection.root_path});
    try appendFmt(allocator, &out, "marker: {s}\n", .{detection.marker_path});
    if (detection.branch_name) |branch_name| {
        try appendFmt(allocator, &out, "branch: {s}\n", .{branch_name});
    }
    return out.toOwnedSlice(allocator);
}

test "stack args parse cwd override" {
    const config = try parseStackArgs(&.{ "--cwd", "/tmp/repo" });
    try std.testing.expectEqualStrings("/tmp/repo", config.cwd.?);
    try std.testing.expectError(error.UnknownStackArgument, parseStackArgs(&.{"--bad"}));
}

test "stack output reports no stack" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-cli-stack-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    const output = try stackOutputAlloc(allocator, dir_path);
    defer allocator.free(output);
    try std.testing.expectEqualStrings("stack: none\n", output);
}

test "stack output dumps detected stack" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-cli-stack-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    const marker_path = try std.fmt.allocPrint(allocator, "{s}/.graphite_repo_config", .{dir_path});
    defer allocator.free(marker_path);
    var file = try std.fs.createFileAbsolute(marker_path, .{});
    try file.writeAll("{}\n");
    file.close();

    const output = try stackOutputAlloc(allocator, dir_path);
    defer allocator.free(output);
    try std.testing.expect(std.mem.indexOf(u8, output, "provider: graphite\n") != null);
    try std.testing.expect(std.mem.indexOf(u8, output, dir_path) != null);
    try std.testing.expect(std.mem.indexOf(u8, output, marker_path) != null);
}

const WorktreesConfig = struct {
    cwd: ?[]const u8 = null,
};

fn worktreesCommand(allocator: std.mem.Allocator, args: []const []const u8) !void {
    const config = try parseWorktreesArgs(args);
    const cwd = if (config.cwd) |path| path else try std.fs.cwd().realpathAlloc(allocator, ".");
    defer if (config.cwd == null) allocator.free(cwd);

    const output = try worktreesOutputAlloc(allocator, cwd);
    defer allocator.free(output);
    try std.fs.File.stdout().writeAll(output);
}

fn parseWorktreesArgs(args: []const []const u8) !WorktreesConfig {
    var config = WorktreesConfig{};
    var i: usize = 0;
    while (i < args.len) : (i += 1) {
        if (std.mem.eql(u8, args[i], "--cwd")) {
            config.cwd = try nextValue(args, &i);
        } else {
            return error.UnknownWorktreesArgument;
        }
    }
    return config;
}

fn worktreesOutputAlloc(allocator: std.mem.Allocator, cwd_path: []const u8) ![]u8 {
    const active_root_output = gitOutputAlloc(allocator, cwd_path, &.{ "git", "rev-parse", "--show-toplevel" }) catch |err| switch (err) {
        error.CommandFailed, error.FileNotFound => return allocator.dupe(u8, "worktrees: none\n"),
        else => return err,
    };
    defer allocator.free(active_root_output);
    const active_root = std.mem.trim(u8, active_root_output, " \t\r\n");

    const porcelain = gitOutputAlloc(allocator, cwd_path, &.{ "git", "worktree", "list", "--porcelain" }) catch |err| switch (err) {
        error.CommandFailed, error.FileNotFound => return allocator.dupe(u8, "worktrees: none\n"),
        else => return err,
    };
    defer allocator.free(porcelain);

    var list = try vcs_worktree.parseListPorcelain(allocator, porcelain, active_root);
    defer list.deinit(allocator);
    try markDirtyWorktrees(allocator, &list);
    return vcs_worktree.renderListAlloc(allocator, list);
}

fn worktreesRenderAlloc(allocator: std.mem.Allocator, porcelain: []const u8, active_root: []const u8) ![]u8 {
    var list = try vcs_worktree.parseListPorcelain(allocator, porcelain, active_root);
    defer list.deinit(allocator);
    return vcs_worktree.renderListAlloc(allocator, list);
}

fn markDirtyWorktrees(allocator: std.mem.Allocator, list: *vcs_worktree.List) !void {
    for (list.entries) |*entry| {
        entry.dirty = try gitStatusDirty(allocator, entry.path);
    }
}

fn gitStatusDirty(allocator: std.mem.Allocator, cwd_path: []const u8) !bool {
    const output = gitOutputAlloc(allocator, cwd_path, &.{ "git", "status", "--porcelain" }) catch |err| switch (err) {
        error.CommandFailed, error.FileNotFound => return false,
        else => return err,
    };
    defer allocator.free(output);
    return std.mem.trim(u8, output, " \t\r\n").len != 0;
}

fn gitOutputAlloc(allocator: std.mem.Allocator, cwd_path: []const u8, argv: []const []const u8) ![]u8 {
    const result = try std.process.Child.run(.{
        .allocator = allocator,
        .argv = argv,
        .cwd = cwd_path,
        .max_output_bytes = 1024 * 1024,
        .expand_arg0 = .expand,
    });
    defer allocator.free(result.stderr);
    if (!exitedZero(result.term)) {
        allocator.free(result.stdout);
        return error.CommandFailed;
    }
    return result.stdout;
}

test "worktrees args parse cwd override" {
    const config = try parseWorktreesArgs(&.{ "--cwd", "/tmp/repo" });
    try std.testing.expectEqualStrings("/tmp/repo", config.cwd.?);
    try std.testing.expectError(error.UnknownWorktreesArgument, parseWorktreesArgs(&.{"--bad"}));
}

test "worktrees output marks active path" {
    const source =
        \\worktree /repo
        \\HEAD a
        \\branch refs/heads/main
        \\
        \\worktree /repo-linked
        \\HEAD b
        \\branch refs/heads/feature
        \\
    ;
    const output = try worktreesRenderAlloc(std.testing.allocator, source, "/repo-linked");
    defer std.testing.allocator.free(output);
    try std.testing.expectEqualStrings("  /repo main\n* /repo-linked feature\n", output);
}

const StarshipImport = struct {
    modules: std.ArrayList(shisa_config.ModuleId) = .empty,
    unsupported: std.ArrayList([]const u8) = .empty,
    python: bool = false,
    node: bool = false,
    rust: bool = false,
    go: bool = false,

    fn deinit(self: *StarshipImport, allocator: std.mem.Allocator) void {
        self.modules.deinit(allocator);
        for (self.unsupported.items) |name| allocator.free(name);
        self.unsupported.deinit(allocator);
    }
};

fn importStarship(allocator: std.mem.Allocator, args: []const []const u8) !void {
    if (args.len != 1) return error.UnknownImportStarshipArgument;

    const source = try std.fs.cwd().readFileAlloc(allocator, args[0], max_config_bytes);
    defer allocator.free(source);

    const output = try importStarshipAlloc(allocator, source);
    defer allocator.free(output);
    try std.fs.File.stdout().writeAll(output);
}

fn importStarshipAlloc(allocator: std.mem.Allocator, source: []const u8) ![]u8 {
    var imported = StarshipImport{};
    defer imported.deinit(allocator);

    if (try starshipFormatAlloc(allocator, source)) |format| {
        defer allocator.free(format);
        try scanStarshipFormat(allocator, format, &imported);
    } else {
        try scanStarshipTables(allocator, source, &imported);
    }

    if (imported.modules.items.len == 0) {
        inline for (.{ .cwd, .git_branch, .language_versions, .exit_status, .jobs, .cmd_duration, .user_host }) |module_id| {
            try appendModule(allocator, &imported, module_id);
        }
    }

    return renderImportedConfigAlloc(allocator, imported);
}

fn starshipFormatAlloc(allocator: std.mem.Allocator, source: []const u8) !?[]u8 {
    var offset: usize = 0;
    while (offset <= source.len) {
        const rest = source[offset..];
        const line_len = std.mem.indexOfScalar(u8, rest, '\n') orelse rest.len;
        const line = rest[0..line_len];
        const trimmed = std.mem.trim(u8, line, " \t\r");
        if (trimmed.len != 0 and trimmed[0] == '[') return null;
        if (std.mem.startsWith(u8, trimmed, "format")) {
            const eq_index = std.mem.indexOfScalar(u8, trimmed, '=') orelse return null;
            const value = std.mem.trim(u8, trimmed[eq_index + 1 ..], " \t\r");
            return parseTomlStringAlloc(allocator, value);
        }
        offset += line_len + 1;
        if (offset > source.len) break;
    }
    return null;
}

fn parseTomlStringAlloc(allocator: std.mem.Allocator, value: []const u8) !?[]u8 {
    if (value.len >= 6 and std.mem.startsWith(u8, value, "\"\"\"") and std.mem.endsWith(u8, value, "\"\"\"")) {
        return try allocator.dupe(u8, value[3 .. value.len - 3]);
    }
    if (value.len < 2 or value[0] != '"') return null;

    var out: std.ArrayList(u8) = .empty;
    errdefer out.deinit(allocator);

    var index: usize = 1;
    while (index < value.len) : (index += 1) {
        const byte = value[index];
        if (byte == '"') return try out.toOwnedSlice(allocator);
        if (byte == '\\') {
            index += 1;
            if (index >= value.len) return null;
            switch (value[index]) {
                '"' => try out.append(allocator, '"'),
                '\\' => try out.append(allocator, '\\'),
                'n' => try out.append(allocator, '\n'),
                'r' => try out.append(allocator, '\r'),
                't' => try out.append(allocator, '\t'),
                else => try out.append(allocator, value[index]),
            }
        } else {
            try out.append(allocator, byte);
        }
    }
    return null;
}

fn scanStarshipFormat(allocator: std.mem.Allocator, format: []const u8, imported: *StarshipImport) !void {
    var index: usize = 0;
    while (index < format.len) : (index += 1) {
        if (format[index] != '$') continue;
        index += 1;
        const start = index;
        while (index < format.len and isStarshipModuleByte(format[index])) : (index += 1) {}
        if (index == start) continue;
        try mapStarshipModule(allocator, format[start..index], imported);
        index -= 1;
    }
}

fn scanStarshipTables(allocator: std.mem.Allocator, source: []const u8, imported: *StarshipImport) !void {
    var offset: usize = 0;
    while (offset <= source.len) {
        const rest = source[offset..];
        const line_len = std.mem.indexOfScalar(u8, rest, '\n') orelse rest.len;
        const line = rest[0..line_len];
        const trimmed = std.mem.trim(u8, line, " \t\r");
        if (trimmed.len > 2 and trimmed[0] == '[' and trimmed[trimmed.len - 1] == ']') {
            const name = std.mem.trim(u8, trimmed[1 .. trimmed.len - 1], " \t\r");
            if (!std.mem.startsWith(u8, name, "[") and std.mem.indexOfScalar(u8, name, '.') == null) {
                try mapStarshipModule(allocator, name, imported);
            }
        }
        offset += line_len + 1;
        if (offset > source.len) break;
    }
}

fn isStarshipModuleByte(byte: u8) bool {
    return std.ascii.isAlphanumeric(byte) or byte == '_';
}

fn mapStarshipModule(allocator: std.mem.Allocator, name: []const u8, imported: *StarshipImport) !void {
    if (std.mem.eql(u8, name, "directory")) {
        try appendModule(allocator, imported, .cwd);
    } else if (std.mem.eql(u8, name, "git_branch") or std.mem.eql(u8, name, "git_status") or std.mem.eql(u8, name, "git_commit") or std.mem.eql(u8, name, "git_state")) {
        try appendModule(allocator, imported, .git_branch);
    } else if (std.mem.eql(u8, name, "python")) {
        imported.python = true;
        try appendModule(allocator, imported, .language_versions);
    } else if (std.mem.eql(u8, name, "nodejs")) {
        imported.node = true;
        try appendModule(allocator, imported, .language_versions);
    } else if (std.mem.eql(u8, name, "rust")) {
        imported.rust = true;
        try appendModule(allocator, imported, .language_versions);
    } else if (std.mem.eql(u8, name, "golang")) {
        imported.go = true;
        try appendModule(allocator, imported, .language_versions);
    } else if (std.mem.eql(u8, name, "status")) {
        try appendModule(allocator, imported, .exit_status);
    } else if (std.mem.eql(u8, name, "jobs")) {
        try appendModule(allocator, imported, .jobs);
    } else if (std.mem.eql(u8, name, "cmd_duration")) {
        try appendModule(allocator, imported, .cmd_duration);
    } else if (std.mem.eql(u8, name, "username") or std.mem.eql(u8, name, "hostname")) {
        try appendModule(allocator, imported, .user_host);
    } else if (std.mem.eql(u8, name, "time")) {
        try appendModule(allocator, imported, .time);
    } else if (!isIgnoredStarshipModule(name)) {
        try appendUnsupported(allocator, imported, name);
    }
}

fn isIgnoredStarshipModule(name: []const u8) bool {
    return std.mem.eql(u8, name, "character") or
        std.mem.eql(u8, name, "line_break") or
        std.mem.eql(u8, name, "fill") or
        std.mem.eql(u8, name, "os") or
        std.mem.eql(u8, name, "shell");
}

fn appendModule(allocator: std.mem.Allocator, imported: *StarshipImport, module_id: shisa_config.ModuleId) !void {
    for (imported.modules.items) |existing| {
        if (existing == module_id) return;
    }
    try imported.modules.append(allocator, module_id);
}

fn appendUnsupported(allocator: std.mem.Allocator, imported: *StarshipImport, name: []const u8) !void {
    for (imported.unsupported.items) |existing| {
        if (std.mem.eql(u8, existing, name)) return;
    }
    const owned = try allocator.dupe(u8, name);
    errdefer allocator.free(owned);
    try imported.unsupported.append(allocator, owned);
}

fn renderImportedConfigAlloc(allocator: std.mem.Allocator, imported: StarshipImport) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);

    try out.appendSlice(allocator, "version = 1\n");
    try out.appendSlice(allocator, "theme = \"plain\"\n\n");
    try out.appendSlice(allocator, "[prompt]\nmodules = [");
    for (imported.modules.items, 0..) |module_id, index| {
        if (index != 0) try out.appendSlice(allocator, ", ");
        try appendFmt(allocator, &out, "\"{s}\"", .{shisa_config.moduleIdName(module_id)});
    }
    try out.appendSlice(allocator, "]\n");

    if (containsModule(imported, .language_versions) and (imported.python or imported.node or imported.rust or imported.go)) {
        try out.appendSlice(allocator, "\n[modules.language_versions]\ndetect = [");
        var count: usize = 0;
        if (imported.python) try appendLanguage(allocator, &out, &count, "python");
        if (imported.node) try appendLanguage(allocator, &out, &count, "node");
        if (imported.rust) try appendLanguage(allocator, &out, &count, "rust");
        if (imported.go) try appendLanguage(allocator, &out, &count, "go");
        try out.appendSlice(allocator, "]\n");
    }

    if (containsModule(imported, .time)) {
        try out.appendSlice(allocator, "\n[modules.time]\nformat = \"24h\"\nutc = true\n");
    }

    if (imported.unsupported.items.len != 0) {
        try out.appendSlice(allocator, "\n# Unsupported Starship modules: ");
        for (imported.unsupported.items, 0..) |name, index| {
            if (index != 0) try out.appendSlice(allocator, ", ");
            try out.appendSlice(allocator, name);
        }
        try out.append(allocator, '\n');
    }

    return out.toOwnedSlice(allocator);
}

fn containsModule(imported: StarshipImport, module_id: shisa_config.ModuleId) bool {
    for (imported.modules.items) |existing| {
        if (existing == module_id) return true;
    }
    return false;
}

fn appendLanguage(allocator: std.mem.Allocator, out: *std.ArrayList(u8), count: *usize, name: []const u8) !void {
    if (count.* != 0) try out.appendSlice(allocator, ", ");
    count.* += 1;
    try appendFmt(allocator, out, "\"{s}\"", .{name});
}

test "imports starship format into shisa modules" {
    const source =
        \\format = "$directory$git_branch$git_status$python$nodejs$status$jobs$cmd_duration$hostname$time$character"
        \\
    ;
    const output = try importStarshipAlloc(std.testing.allocator, source);
    defer std.testing.allocator.free(output);

    try std.testing.expect(std.mem.indexOf(u8, output, "modules = [\"cwd\", \"git_branch\", \"language_versions\", \"exit_status\", \"jobs\", \"cmd_duration\", \"user_host\", \"time\"]") != null);
    try std.testing.expect(std.mem.indexOf(u8, output, "detect = [\"python\", \"node\"]") != null);
    try std.testing.expect(std.mem.indexOf(u8, output, "[modules.time]") != null);
}

test "imports starship table fallback and records unsupported modules" {
    const source =
        \\[directory]
        \\[aws]
        \\[git_branch]
        \\
    ;
    const output = try importStarshipAlloc(std.testing.allocator, source);
    defer std.testing.allocator.free(output);

    try std.testing.expect(std.mem.indexOf(u8, output, "modules = [\"cwd\", \"git_branch\"]") != null);
    try std.testing.expect(std.mem.indexOf(u8, output, "Unsupported Starship modules: aws") != null);
}

fn bench(allocator: std.mem.Allocator, args: []const []const u8) !void {
    const bench_config = try parseBench(args);
    try ensureHyperfine(allocator);

    const self_path = try std.fs.selfExePathAlloc(allocator);
    defer allocator.free(self_path);
    const daemon_path = try siblingExecutablePath(allocator, "shisad");
    defer allocator.free(daemon_path);
    const cwd = try std.fs.cwd().realpathAlloc(allocator, ".");
    defer allocator.free(cwd);
    const socket_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-bench-{x}.sock", .{std.crypto.random.int(u64)});
    defer allocator.free(socket_path);
    const log_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-bench-{x}.log", .{std.crypto.random.int(u64)});
    defer allocator.free(log_path);
    defer std.fs.deleteFileAbsolute(socket_path) catch {};
    defer std.fs.deleteFileAbsolute(log_path) catch {};

    var daemon = std.process.Child.init(&.{ daemon_path, "--foreground", "--socket", socket_path, "--log", log_path }, allocator);
    daemon.stdin_behavior = .Ignore;
    daemon.stdout_behavior = .Ignore;
    daemon.stderr_behavior = .Ignore;
    try daemon.spawn();
    defer _ = daemon.kill() catch {};

    try waitForPath(socket_path, 1000);
    const workload = try benchWorkloadAlloc(allocator, self_path, socket_path, cwd);
    defer allocator.free(workload);
    try runHyperfine(allocator, workload, bench_config);
}

const BenchConfig = struct {
    export_json: ?[]const u8 = null,
};

fn parseBench(args: []const []const u8) !BenchConfig {
    var config = BenchConfig{};
    var i: usize = 0;
    while (i < args.len) : (i += 1) {
        const arg = args[i];
        if (std.mem.eql(u8, arg, "--export-json")) {
            config.export_json = try nextValue(args, &i);
        } else {
            return error.UnknownBenchArgument;
        }
    }
    return config;
}

fn ensureHyperfine(allocator: std.mem.Allocator) !void {
    const result = std.process.Child.run(.{
        .allocator = allocator,
        .argv = &.{ "hyperfine", "--version" },
        .max_output_bytes = 4096,
        .expand_arg0 = .expand,
    }) catch |err| switch (err) {
        error.FileNotFound => {
            try std.fs.File.stderr().writeAll("shisa bench: hyperfine not found in PATH\n");
            return err;
        },
        else => return err,
    };
    defer allocator.free(result.stdout);
    defer allocator.free(result.stderr);
    if (!exitedZero(result.term)) return error.HyperfineUnavailable;
}

fn runHyperfine(allocator: std.mem.Allocator, workload: []const u8, bench_config: BenchConfig) !void {
    var argv: std.ArrayList([]const u8) = .empty;
    defer argv.deinit(allocator);
    try argv.appendSlice(allocator, &.{ "hyperfine", "--warmup", "5", "--runs", "25" });
    if (bench_config.export_json) |path| {
        try argv.appendSlice(allocator, &.{ "--export-json", path });
    }
    try argv.append(allocator, workload);

    const result = try std.process.Child.run(.{
        .allocator = allocator,
        .argv = argv.items,
        .max_output_bytes = 8 * 1024 * 1024,
        .expand_arg0 = .expand,
    });
    defer allocator.free(result.stdout);
    defer allocator.free(result.stderr);

    try std.fs.File.stdout().writeAll(result.stdout);
    try std.fs.File.stderr().writeAll(result.stderr);
    if (!exitedZero(result.term)) return error.BenchmarkFailed;
}

fn benchWorkloadAlloc(allocator: std.mem.Allocator, self_path: []const u8, socket_path: []const u8, cwd: []const u8) ![]u8 {
    const quoted_self = try shellQuoteAlloc(allocator, self_path);
    defer allocator.free(quoted_self);
    const quoted_socket = try shellQuoteAlloc(allocator, socket_path);
    defer allocator.free(quoted_socket);
    const quoted_cwd = try shellQuoteAlloc(allocator, cwd);
    defer allocator.free(quoted_cwd);
    return std.fmt.allocPrint(
        allocator,
        "{s} prompt --socket {s} --cwd {s} --shell zsh --cols 80 --rows 24",
        .{ quoted_self, quoted_socket, quoted_cwd },
    );
}

fn shellQuoteAlloc(allocator: std.mem.Allocator, value: []const u8) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);
    try out.append(allocator, '\'');
    for (value) |byte| {
        if (byte == '\'') {
            try out.appendSlice(allocator, "'\\''");
        } else {
            try out.append(allocator, byte);
        }
    }
    try out.append(allocator, '\'');
    return out.toOwnedSlice(allocator);
}

fn siblingExecutablePath(allocator: std.mem.Allocator, name: []const u8) ![]u8 {
    const self_path = try std.fs.selfExePathAlloc(allocator);
    defer allocator.free(self_path);
    const dir = std.fs.path.dirname(self_path) orelse ".";
    return std.fs.path.join(allocator, &.{ dir, name });
}

fn waitForPath(path: []const u8, timeout_ms: i64) !void {
    const start = std.time.milliTimestamp();
    while (std.time.milliTimestamp() - start < timeout_ms) {
        std.fs.cwd().access(path, .{}) catch {
            std.Thread.sleep(10 * std.time.ns_per_ms);
            continue;
        };
        return;
    }
    return error.Timeout;
}

fn exitedZero(term: std.process.Child.Term) bool {
    return switch (term) {
        .Exited => |code| code == 0,
        else => false,
    };
}

test "shell quoting handles spaces and quotes" {
    const quoted = try shellQuoteAlloc(std.testing.allocator, "/tmp/a b/c'd");
    defer std.testing.allocator.free(quoted);
    try std.testing.expectEqualStrings("'/tmp/a b/c'\\''d'", quoted);
}

test "bench workload targets prompt command" {
    const workload = try benchWorkloadAlloc(std.testing.allocator, "/tmp/shisa", "/tmp/sock", "/tmp/repo");
    defer std.testing.allocator.free(workload);
    try std.testing.expectEqualStrings("'/tmp/shisa' prompt --socket '/tmp/sock' --cwd '/tmp/repo' --shell zsh --cols 80 --rows 24", workload);
}

fn cacheCommand(allocator: std.mem.Allocator, args: []const []const u8) !void {
    const action = if (args.len == 0) "stats" else args[0];
    if (args.len > 1) return error.UnknownCacheArgument;
    if (!std.mem.eql(u8, action, "stats")) return error.UnknownCacheArgument;

    const output = try cacheStatsAlloc(allocator, .{});
    defer allocator.free(output);
    try std.fs.File.stdout().writeAll(output);
}

fn cacheStatsAlloc(allocator: std.mem.Allocator, options: daemon_cache.Options) ![]u8 {
    return std.fmt.allocPrint(
        allocator,
        "{{\"module_cache\":{{\"entries\":0,\"max_entries\":{d},\"max_age_ns\":{d}}},\"prompt_cache\":{{\"entries\":0}}}}\n",
        .{ options.max_entries, options.max_age_ns },
    );
}

test "cache stats output is json object" {
    const output = try cacheStatsAlloc(std.testing.allocator, .{ .max_entries = 2, .max_age_ns = 3 });
    defer std.testing.allocator.free(output);
    try std.testing.expectEqualStrings("{\"module_cache\":{\"entries\":0,\"max_entries\":2,\"max_age_ns\":3},\"prompt_cache\":{\"entries\":0}}\n", output);
}

fn pinCommand(allocator: std.mem.Allocator, args: []const []const u8) !void {
    if (args.len != 1) return error.UnknownPinArgument;
    const path = try std.fs.cwd().realpathAlloc(allocator, args[0]);
    defer allocator.free(path);
    const pins_path = try pinsPath(allocator);
    defer allocator.free(pins_path);
    try appendPin(allocator, pins_path, path);

    const message = try std.fmt.allocPrint(allocator, "pinned {s}\n", .{path});
    defer allocator.free(message);
    try std.fs.File.stdout().writeAll(message);
}

fn pinsPath(allocator: std.mem.Allocator) ![]u8 {
    const config_path = try defaultConfigPath(allocator);
    defer allocator.free(config_path);
    const dir = std.fs.path.dirname(config_path) orelse return error.MissingConfigDir;
    return std.fmt.allocPrint(allocator, "{s}/pins", .{dir});
}

fn appendPin(allocator: std.mem.Allocator, pins_path: []const u8, path: []const u8) !void {
    if (std.fs.path.dirname(pins_path)) |parent| {
        try std.fs.cwd().makePath(parent);
    }

    if (try pinExists(allocator, pins_path, path)) return;

    var file = try std.fs.createFileAbsolute(pins_path, .{ .truncate = false, .read = true });
    defer file.close();
    try file.seekFromEnd(0);
    try file.writeAll(path);
    try file.writeAll("\n");
}

fn pinExists(allocator: std.mem.Allocator, pins_path: []const u8, path: []const u8) !bool {
    const contents = std.fs.cwd().readFileAlloc(allocator, pins_path, 1024 * 1024) catch |err| switch (err) {
        error.FileNotFound => return false,
        else => return err,
    };
    defer allocator.free(contents);

    var lines = std.mem.tokenizeScalar(u8, contents, '\n');
    while (lines.next()) |line| {
        if (std.mem.eql(u8, line, path)) return true;
    }
    return false;
}

test "appends pin once" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-pin-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    const pins_path = try std.fmt.allocPrint(allocator, "{s}/pins", .{dir_path});
    defer allocator.free(pins_path);
    try appendPin(allocator, pins_path, "/tmp/repo");
    try appendPin(allocator, pins_path, "/tmp/repo");

    const contents = try std.fs.cwd().readFileAlloc(allocator, pins_path, 4096);
    defer allocator.free(contents);
    try std.testing.expectEqualStrings("/tmp/repo\n", contents);
}

fn pluginCommand(allocator: std.mem.Allocator, args: []const []const u8) !void {
    if (args.len == 0) return error.UnknownPluginArgument;

    const plugins_dir = try pluginsDirPath(allocator);
    defer allocator.free(plugins_dir);
    const disabled_path = try disabledPluginsPath(allocator);
    defer allocator.free(disabled_path);
    const trusted_path = try trustedPluginsPath(allocator);
    defer allocator.free(trusted_path);

    if (std.mem.eql(u8, args[0], "list")) {
        if (args.len != 1) return error.UnknownPluginArgument;
        const output = try pluginListAlloc(allocator, plugins_dir, disabled_path);
        defer allocator.free(output);
        try std.fs.File.stdout().writeAll(output);
    } else if (std.mem.eql(u8, args[0], "install")) {
        const config = try parsePluginInstallArgs(args[1..]);
        try pluginInstall(allocator, plugins_dir, config);
    } else if (std.mem.eql(u8, args[0], "disable")) {
        if (args.len != 2) return error.UnknownPluginArgument;
        try setPluginDisabled(allocator, disabled_path, args[1], true);
        const message = try std.fmt.allocPrint(allocator, "disabled {s}\n", .{args[1]});
        defer allocator.free(message);
        try std.fs.File.stdout().writeAll(message);
    } else if (std.mem.eql(u8, args[0], "enable")) {
        if (args.len != 2) return error.UnknownPluginArgument;
        try setPluginDisabled(allocator, disabled_path, args[1], false);
        const message = try std.fmt.allocPrint(allocator, "enabled {s}\n", .{args[1]});
        defer allocator.free(message);
        try std.fs.File.stdout().writeAll(message);
    } else if (std.mem.eql(u8, args[0], "trust")) {
        if (args.len != 2) return error.UnknownPluginArgument;
        try setPluginTrusted(allocator, trusted_path, args[1]);
        const message = try std.fmt.allocPrint(allocator, "trusted {s}\n", .{args[1]});
        defer allocator.free(message);
        try std.fs.File.stdout().writeAll(message);
    } else {
        return error.UnknownPluginArgument;
    }
}

const PluginInstallConfig = struct {
    url: []const u8,
    yes: bool = false,
    strict: bool = false,
};

fn parsePluginInstallArgs(args: []const []const u8) !PluginInstallConfig {
    var config: PluginInstallConfig = undefined;
    var seen_url = false;
    config.yes = false;
    config.strict = false;

    for (args) |arg| {
        if (std.mem.eql(u8, arg, "--yes") or std.mem.eql(u8, arg, "-y")) {
            config.yes = true;
        } else if (std.mem.eql(u8, arg, "--plugin-sandbox-strict")) {
            config.strict = true;
        } else if (!seen_url) {
            config.url = arg;
            seen_url = true;
        } else {
            return error.UnknownPluginArgument;
        }
    }
    if (!seen_url) return error.UnknownPluginArgument;
    return config;
}

fn pluginInstall(allocator: std.mem.Allocator, plugins_dir: []const u8, config: PluginInstallConfig) !void {
    try std.fs.cwd().makePath(plugins_dir);

    const temp_path = try std.fmt.allocPrint(allocator, "{s}/.install-{x}", .{ plugins_dir, std.crypto.random.int(u64) });
    defer allocator.free(temp_path);
    defer std.fs.cwd().deleteTree(temp_path) catch {};

    try runGitClone(allocator, config.url, temp_path);

    const manifest_path = try std.fmt.allocPrint(allocator, "{s}/plugin.lua", .{temp_path});
    defer allocator.free(manifest_path);
    const manifest_source = try std.fs.cwd().readFileAlloc(allocator, manifest_path, 1024 * 1024);
    defer allocator.free(manifest_source);

    var runtime = try plugin_lua.Runtime.initSandboxed(allocator);
    defer runtime.deinit();
    var loaded = if (config.strict)
        try runtime.loadManifestStrict(manifest_source)
    else
        try runtime.loadManifest(manifest_source);
    defer loaded.deinit(allocator);

    if (!config.yes and !(try confirmPluginInstall(allocator, loaded.manifest))) return error.PluginInstallDeclined;

    const target_path = try std.fmt.allocPrint(allocator, "{s}/{s}", .{ plugins_dir, loaded.manifest.name });
    defer allocator.free(target_path);
    if (std.fs.cwd().access(target_path, .{})) |_| return error.PluginAlreadyInstalled else |err| switch (err) {
        error.FileNotFound => {},
        else => return err,
    }

    try std.fs.renameAbsolute(temp_path, target_path);
    const message = try std.fmt.allocPrint(allocator, "installed {s} {s}\n", .{ loaded.manifest.name, loaded.manifest.version });
    defer allocator.free(message);
    try std.fs.File.stdout().writeAll(message);
}

fn runGitClone(allocator: std.mem.Allocator, url: []const u8, target_path: []const u8) !void {
    const result = try std.process.Child.run(.{
        .allocator = allocator,
        .argv = &.{ "git", "clone", "--depth", "1", url, target_path },
        .max_output_bytes = 1024 * 1024,
        .expand_arg0 = .expand,
    });
    defer allocator.free(result.stdout);
    defer allocator.free(result.stderr);
    if (!exitedZero(result.term)) return error.PluginCloneFailed;
}

fn confirmPluginInstall(allocator: std.mem.Allocator, manifest: plugin_manifest.Manifest) !bool {
    const prompt_text = try std.fmt.allocPrint(allocator, "Install plugin {s} {s}? [y/N] ", .{ manifest.name, manifest.version });
    defer allocator.free(prompt_text);
    try std.fs.File.stdout().writeAll(prompt_text);
    const answer = try std.fs.File.stdin().readToEndAlloc(allocator, 16);
    defer allocator.free(answer);
    const trimmed = std.mem.trim(u8, answer, " \t\r\n");
    return trimmed.len > 0 and (trimmed[0] == 'y' or trimmed[0] == 'Y');
}

fn pluginsDirPath(allocator: std.mem.Allocator) ![]u8 {
    const config_path = try defaultConfigPath(allocator);
    defer allocator.free(config_path);
    const dir = std.fs.path.dirname(config_path) orelse return error.MissingConfigDir;
    return std.fmt.allocPrint(allocator, "{s}/plugins", .{dir});
}

fn disabledPluginsPath(allocator: std.mem.Allocator) ![]u8 {
    const config_path = try defaultConfigPath(allocator);
    defer allocator.free(config_path);
    const dir = std.fs.path.dirname(config_path) orelse return error.MissingConfigDir;
    return std.fmt.allocPrint(allocator, "{s}/plugins.disabled", .{dir});
}

fn trustedPluginsPath(allocator: std.mem.Allocator) ![]u8 {
    const config_path = try defaultConfigPath(allocator);
    defer allocator.free(config_path);
    const dir = std.fs.path.dirname(config_path) orelse return error.MissingConfigDir;
    return std.fmt.allocPrint(allocator, "{s}/plugins.trusted", .{dir});
}

fn pluginListAlloc(allocator: std.mem.Allocator, plugins_dir: []const u8, disabled_path: []const u8) ![]u8 {
    var names: std.ArrayList([]u8) = .empty;
    defer {
        for (names.items) |name| allocator.free(name);
        names.deinit(allocator);
    }

    var dir = std.fs.openDirAbsolute(plugins_dir, .{ .iterate = true }) catch |err| switch (err) {
        error.FileNotFound => return allocator.dupe(u8, ""),
        else => return err,
    };
    defer dir.close();

    var it = dir.iterate();
    while (try it.next()) |entry| {
        if (entry.kind != .directory) continue;
        if (!plugin_manifest.isValidPluginName(entry.name)) continue;
        try names.append(allocator, try allocator.dupe(u8, entry.name));
    }
    std.mem.sort([]u8, names.items, {}, lessThanString);

    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);
    for (names.items) |name| {
        const state = if (try pluginDisabled(allocator, disabled_path, name)) "disabled" else "enabled";
        try appendFmt(allocator, &out, "{s} {s}\n", .{ name, state });
    }
    return out.toOwnedSlice(allocator);
}

fn setPluginDisabled(allocator: std.mem.Allocator, disabled_path: []const u8, name: []const u8, disabled: bool) !void {
    if (!plugin_manifest.isValidPluginName(name)) return error.InvalidPluginName;

    var names = try readPluginNames(allocator, disabled_path);
    defer {
        for (names.items) |item| allocator.free(item);
        names.deinit(allocator);
    }

    const index = indexOfString(names.items, name);
    if (disabled and index == null) {
        try names.append(allocator, try allocator.dupe(u8, name));
    } else if (!disabled and index != null) {
        const removed = names.orderedRemove(index.?);
        allocator.free(removed);
    }
    std.mem.sort([]u8, names.items, {}, lessThanString);
    try writePluginNames(disabled_path, names.items);
}

fn pluginDisabled(allocator: std.mem.Allocator, disabled_path: []const u8, name: []const u8) !bool {
    var names = try readPluginNames(allocator, disabled_path);
    defer {
        for (names.items) |item| allocator.free(item);
        names.deinit(allocator);
    }
    return indexOfString(names.items, name) != null;
}

fn setPluginTrusted(allocator: std.mem.Allocator, trusted_path: []const u8, name: []const u8) !void {
    if (!plugin_manifest.isValidPluginName(name)) return error.InvalidPluginName;

    var names = try readPluginNames(allocator, trusted_path);
    defer {
        for (names.items) |item| allocator.free(item);
        names.deinit(allocator);
    }

    if (indexOfString(names.items, name) == null) {
        try names.append(allocator, try allocator.dupe(u8, name));
    }
    std.mem.sort([]u8, names.items, {}, lessThanString);
    try writePluginNames(trusted_path, names.items);
}

fn pluginTrusted(allocator: std.mem.Allocator, trusted_path: []const u8, name: []const u8) !bool {
    var names = try readPluginNames(allocator, trusted_path);
    defer {
        for (names.items) |item| allocator.free(item);
        names.deinit(allocator);
    }
    return indexOfString(names.items, name) != null;
}

fn readPluginNames(allocator: std.mem.Allocator, path: []const u8) !std.ArrayList([]u8) {
    var names: std.ArrayList([]u8) = .empty;
    const contents = std.fs.cwd().readFileAlloc(allocator, path, 1024 * 1024) catch |err| switch (err) {
        error.FileNotFound => return names,
        else => return err,
    };
    defer allocator.free(contents);

    var lines = std.mem.tokenizeScalar(u8, contents, '\n');
    while (lines.next()) |line| {
        const trimmed = std.mem.trim(u8, line, " \t\r");
        if (trimmed.len == 0 or !plugin_manifest.isValidPluginName(trimmed)) continue;
        if (indexOfString(names.items, trimmed) == null) {
            try names.append(allocator, try allocator.dupe(u8, trimmed));
        }
    }
    return names;
}

fn writePluginNames(path: []const u8, names: []const []const u8) !void {
    if (std.fs.path.dirname(path)) |parent| {
        try std.fs.cwd().makePath(parent);
    }

    var file = try std.fs.createFileAbsolute(path, .{ .truncate = true, .mode = 0o600 });
    defer file.close();
    for (names) |name| {
        try file.writeAll(name);
        try file.writeAll("\n");
    }
}

fn indexOfString(items: []const []const u8, name: []const u8) ?usize {
    for (items, 0..) |item, index| {
        if (std.mem.eql(u8, item, name)) return index;
    }
    return null;
}

fn lessThanString(_: void, lhs: []const u8, rhs: []const u8) bool {
    return std.mem.lessThan(u8, lhs, rhs);
}

test "plugin list reports enabled and disabled plugins" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-plugin-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};

    const plugins_dir = try std.fmt.allocPrint(allocator, "{s}/plugins", .{dir_path});
    defer allocator.free(plugins_dir);
    try std.fs.cwd().makePath(plugins_dir);
    const beta_path = try std.fmt.allocPrint(allocator, "{s}/beta", .{plugins_dir});
    defer allocator.free(beta_path);
    const alpha_path = try std.fmt.allocPrint(allocator, "{s}/alpha", .{plugins_dir});
    defer allocator.free(alpha_path);
    const bad_path = try std.fmt.allocPrint(allocator, "{s}/Bad", .{plugins_dir});
    defer allocator.free(bad_path);
    try std.fs.cwd().makePath(beta_path);
    try std.fs.cwd().makePath(alpha_path);
    try std.fs.cwd().makePath(bad_path);

    const disabled_path = try std.fmt.allocPrint(allocator, "{s}/plugins.disabled", .{dir_path});
    defer allocator.free(disabled_path);
    try setPluginDisabled(allocator, disabled_path, "beta", true);

    const output = try pluginListAlloc(allocator, plugins_dir, disabled_path);
    defer allocator.free(output);
    try std.testing.expectEqualStrings("alpha enabled\nbeta disabled\n", output);
}

test "parses plugin install args" {
    const config = try parsePluginInstallArgs(&.{ "https://example.com/plugin.git", "--yes", "--plugin-sandbox-strict" });
    try std.testing.expectEqualStrings("https://example.com/plugin.git", config.url);
    try std.testing.expect(config.yes);
    try std.testing.expect(config.strict);
    try std.testing.expectError(error.UnknownPluginArgument, parsePluginInstallArgs(&.{"--yes"}));
}

test "plugin enable disable is duplicate safe" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-plugin-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    const disabled_path = try std.fmt.allocPrint(allocator, "{s}/plugins.disabled", .{dir_path});
    defer allocator.free(disabled_path);
    try setPluginDisabled(allocator, disabled_path, "alpha", true);
    try setPluginDisabled(allocator, disabled_path, "alpha", true);
    try std.testing.expect(try pluginDisabled(allocator, disabled_path, "alpha"));
    try setPluginDisabled(allocator, disabled_path, "alpha", false);
    try std.testing.expect(!(try pluginDisabled(allocator, disabled_path, "alpha")));

    const contents = try std.fs.cwd().readFileAlloc(allocator, disabled_path, 4096);
    defer allocator.free(contents);
    try std.testing.expectEqualStrings("", contents);
}

test "plugin trust is duplicate safe" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-plugin-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    const trusted_path = try std.fmt.allocPrint(allocator, "{s}/plugins.trusted", .{dir_path});
    defer allocator.free(trusted_path);
    try setPluginTrusted(allocator, trusted_path, "alpha");
    try setPluginTrusted(allocator, trusted_path, "alpha");
    try std.testing.expect(try pluginTrusted(allocator, trusted_path, "alpha"));

    const contents = try std.fs.cwd().readFileAlloc(allocator, trusted_path, 4096);
    defer allocator.free(contents);
    try std.testing.expectEqualStrings("alpha\n", contents);
}

test "plugin state rejects invalid names" {
    try std.testing.expectError(error.InvalidPluginName, setPluginDisabled(std.testing.allocator, "/tmp/shisa-plugin-invalid", "Bad", true));
    try std.testing.expectError(error.InvalidPluginName, setPluginTrusted(std.testing.allocator, "/tmp/shisa-plugin-invalid", "Bad"));
}

test "parses bench export json flag" {
    const args = [_][]const u8{ "--export-json", "/tmp/out.json" };
    const config = try parseBench(args[0..]);
    try std.testing.expectEqualStrings("/tmp/out.json", config.export_json.?);
}

const PromptConfig = struct {
    socket_path: ?[]const u8 = null,
    cwd: ?[]const u8 = null,
    exit: i32 = 0,
    jobs: u32 = 0,
    duration_ms: u64 = 0,
    time: bool = false,
    no_async: bool = false,
    instant: bool = false,
    shell: []const u8 = "zsh",
    cols: u16 = 80,
    rows: u16 = 24,
};

fn prompt(allocator: std.mem.Allocator, args: []const []const u8) !void {
    const config = try parsePrompt(args);
    const socket_path = if (config.socket_path) |path| path else try paths.defaultSocketPath(allocator);
    defer if (config.socket_path == null) allocator.free(socket_path);
    const cwd = if (config.cwd) |path| path else try std.fs.cwd().realpathAlloc(allocator, ".");
    defer if (config.cwd == null) allocator.free(cwd);

    const payload = try buildPromptPayload(allocator, config, cwd);
    defer allocator.free(payload);

    if (config.instant) {
        if (try readInstantPrompt(allocator)) |cached| {
            defer allocator.free(cached);
            try std.fs.File.stdout().writeAll(cached);
            return;
        }
    }

    const response_payload = try client.requestAlloc(allocator, socket_path, payload);
    defer allocator.free(response_payload);

    var parsed = try std.json.parseFromSlice(proto.Response, allocator, response_payload, .{ .ignore_unknown_fields = true });
    defer parsed.deinit();
    if (config.instant) {
        try writeInstantPrompt(allocator, parsed.value.prompt);
    }
    try std.fs.File.stdout().writeAll(parsed.value.prompt);
}

fn parsePrompt(args: []const []const u8) !PromptConfig {
    var config = PromptConfig{};
    var i: usize = 0;

    while (i < args.len) : (i += 1) {
        const arg = args[i];
        if (std.mem.eql(u8, arg, "--socket")) {
            config.socket_path = try nextValue(args, &i);
        } else if (std.mem.eql(u8, arg, "--cwd")) {
            config.cwd = try nextValue(args, &i);
        } else if (std.mem.eql(u8, arg, "--exit")) {
            config.exit = try std.fmt.parseInt(i32, try nextValue(args, &i), 10);
        } else if (std.mem.eql(u8, arg, "--jobs")) {
            config.jobs = try std.fmt.parseInt(u32, try nextValue(args, &i), 10);
        } else if (std.mem.eql(u8, arg, "--duration-ms")) {
            config.duration_ms = try std.fmt.parseInt(u64, try nextValue(args, &i), 10);
        } else if (std.mem.eql(u8, arg, "--time")) {
            config.time = true;
        } else if (std.mem.eql(u8, arg, "--no-async")) {
            config.no_async = true;
        } else if (std.mem.eql(u8, arg, "--instant")) {
            config.instant = true;
        } else if (std.mem.eql(u8, arg, "--shell")) {
            config.shell = try nextValue(args, &i);
        } else if (std.mem.eql(u8, arg, "--cols")) {
            config.cols = try std.fmt.parseInt(u16, try nextValue(args, &i), 10);
        } else if (std.mem.eql(u8, arg, "--rows")) {
            config.rows = try std.fmt.parseInt(u16, try nextValue(args, &i), 10);
        } else {
            return error.UnknownPromptArgument;
        }
    }

    return config;
}

fn instantPromptPath(allocator: std.mem.Allocator) ![]u8 {
    const config_path = try defaultConfigPath(allocator);
    defer allocator.free(config_path);
    const dir = std.fs.path.dirname(config_path) orelse return error.MissingConfigDir;
    return std.fmt.allocPrint(allocator, "{s}/last-prompt", .{dir});
}

fn readInstantPrompt(allocator: std.mem.Allocator) !?[]u8 {
    const path = try instantPromptPath(allocator);
    defer allocator.free(path);
    return std.fs.cwd().readFileAlloc(allocator, path, 16 * 1024) catch |err| switch (err) {
        error.FileNotFound => null,
        else => return err,
    };
}

fn writeInstantPrompt(allocator: std.mem.Allocator, prompt_text: []const u8) !void {
    const path = try instantPromptPath(allocator);
    defer allocator.free(path);
    if (std.fs.path.dirname(path)) |parent| {
        try std.fs.cwd().makePath(parent);
    }
    var file = try std.fs.createFileAbsolute(path, .{ .truncate = true, .mode = 0o600 });
    defer file.close();
    try file.writeAll(prompt_text);
}

test "instant prompt read write roundtrip" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-instant-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    const path = try std.fmt.allocPrint(allocator, "{s}/last-prompt", .{dir_path});
    defer allocator.free(path);
    var file = try std.fs.createFileAbsolute(path, .{});
    try file.writeAll("cached> ");
    file.close();

    const cached = try std.fs.cwd().readFileAlloc(allocator, path, 16 * 1024);
    defer allocator.free(cached);
    try std.testing.expectEqualStrings("cached> ", cached);
}

fn nextValue(args: []const []const u8, index: *usize) ![]const u8 {
    if (index.* + 1 >= args.len) return error.MissingValue;
    index.* += 1;
    return args[index.*];
}

fn buildPromptPayload(allocator: std.mem.Allocator, config: PromptConfig, cwd: []const u8) ![]u8 {
    const escaped_cwd = try jsonEscapeAlloc(allocator, cwd);
    defer allocator.free(escaped_cwd);
    const escaped_shell = try jsonEscapeAlloc(allocator, config.shell);
    defer allocator.free(escaped_shell);
    const cloud_ctx = try promptCloudCtxOptions(allocator);

    return std.fmt.allocPrint(
        allocator,
        "{{\"v\":1,\"cwd\":\"{s}\",\"exit\":{d},\"jobs\":{d},\"duration_ms\":{d},\"time\":{},\"no_async\":{},\"shell\":\"{s}\",\"cols\":{d},\"rows\":{d},\"cloud_ctx\":{{\"aws\":{},\"gcp\":{},\"azure\":{},\"kubernetes\":{}}}}}",
        .{ escaped_cwd, config.exit, config.jobs, config.duration_ms, config.time, config.no_async, escaped_shell, config.cols, config.rows, cloud_ctx.aws, cloud_ctx.gcp, cloud_ctx.azure, cloud_ctx.kubernetes },
    );
}

fn promptCloudCtxOptions(allocator: std.mem.Allocator) !shisa_config.CloudCtxOptions {
    const path = try defaultConfigPath(allocator);
    defer allocator.free(path);
    const source = try readConfigOrDefault(allocator, path);
    defer allocator.free(source);
    var diagnostic: shisa_config.Diagnostic = .{};
    var parsed = shisa_config.parse(allocator, source, &diagnostic) catch |err| switch (err) {
        error.InvalidConfig => {
            const message = try std.fmt.allocPrint(allocator, "{s}:{d}:{d}: {s}\n", .{ path, diagnostic.line, diagnostic.column, diagnostic.message });
            defer allocator.free(message);
            try std.fs.File.stderr().writeAll(message);
            return err;
        },
        else => return err,
    };
    defer parsed.deinit(allocator);
    return parsed.modules.cloud_ctx;
}

fn jsonEscapeAlloc(allocator: std.mem.Allocator, value: []const u8) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);

    for (value) |byte| {
        switch (byte) {
            '"' => try out.appendSlice(allocator, "\\\""),
            '\\' => try out.appendSlice(allocator, "\\\\"),
            '\n' => try out.appendSlice(allocator, "\\n"),
            '\r' => try out.appendSlice(allocator, "\\r"),
            '\t' => try out.appendSlice(allocator, "\\t"),
            else => try out.append(allocator, byte),
        }
    }

    return out.toOwnedSlice(allocator);
}

const help_text =
    \\usage: shisa <command> [options]
    \\
    \\commands:
    \\  bench         benchmark prompt render via hyperfine
    \\  cache         dump cache stats
    \\  doctor        diagnose socket, config, plugins, lua, fsnotify
    \\  explain       print resolved module pipeline
    \\  import-starship <path>
    \\                translate starship.toml to shisa.toml
    \\  init          write default shisa.toml
    \\  pin           mark a path as never-evicted
    \\  plugin        install, list, enable, disable, or trust plugins
    \\  prompt        render prompt through shisad
    \\  stack         dump detected stacked-diff metadata
    \\  supervisor    run shisad under a crash-restart supervisor
    \\  worktrees     list Git worktrees and mark active
    \\
    \\options:
    \\  -h, --help    print help
    \\      --version print version
    \\
;
