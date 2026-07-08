const std = @import("std");
const plugin_lua = @import("plugin_lua");

pub const capability = plugin_lua.capability;
pub const manifest = plugin_lua.manifest;
pub const Runtime = plugin_lua.Runtime;

const max_plugin_file_bytes = 1024 * 1024;
const plugin_slow_strike_limit: u8 = 3;

pub const ReloadState = struct {
    mutex: std.Thread.Mutex = .{},
    config_generation: u64 = 0,
    plugin_generation: u64 = 0,
    config_source: []u8 = &.{},
    plugin_names: [][]u8 = &.{},

    pub const Snapshot = struct {
        config_generation: u64 = 0,
        plugin_generation: u64 = 0,
        plugin_count: usize = 0,
    };

    pub fn deinit(self: *ReloadState, allocator: std.mem.Allocator) void {
        self.mutex.lock();
        defer self.mutex.unlock();
        allocator.free(self.config_source);
        freeNames(allocator, self.plugin_names);
        self.config_source = &.{};
        self.plugin_names = &.{};
        self.config_generation = 0;
        self.plugin_generation = 0;
    }

    pub fn snapshot(self: *ReloadState) Snapshot {
        self.mutex.lock();
        defer self.mutex.unlock();
        return .{
            .config_generation = self.config_generation,
            .plugin_generation = self.plugin_generation,
            .plugin_count = self.plugin_names.len,
        };
    }

    pub fn replace(self: *ReloadState, allocator: std.mem.Allocator, config_source: []u8, plugin_names: [][]u8) void {
        self.mutex.lock();
        defer self.mutex.unlock();
        allocator.free(self.config_source);
        freeNames(allocator, self.plugin_names);
        self.config_source = config_source;
        self.plugin_names = plugin_names;
        self.config_generation += 1;
        self.plugin_generation += 1;
    }

    pub fn replacePluginNames(self: *ReloadState, allocator: std.mem.Allocator, plugin_names: [][]u8) void {
        self.mutex.lock();
        defer self.mutex.unlock();
        freeNames(allocator, self.plugin_names);
        self.plugin_names = plugin_names;
    }

    pub fn copyConfigSourceAlloc(self: *ReloadState, allocator: std.mem.Allocator) ![]u8 {
        self.mutex.lock();
        defer self.mutex.unlock();
        return allocator.dupe(u8, self.config_source);
    }

    pub fn copyPluginNamesAlloc(self: *ReloadState, allocator: std.mem.Allocator) ![][]u8 {
        self.mutex.lock();
        defer self.mutex.unlock();
        return dupeNames(allocator, self.plugin_names);
    }
};

pub fn loadNamesAlloc(allocator: std.mem.Allocator, plugins_dir: []const u8) ![][]u8 {
    const disabled_path = try statePathForPluginsDirAlloc(allocator, plugins_dir, "plugins.disabled");
    defer allocator.free(disabled_path);
    const strikes_path = try statePathForPluginsDirAlloc(allocator, plugins_dir, "plugins.slow-strikes");
    defer allocator.free(strikes_path);

    var dir = std.fs.openDirAbsolute(plugins_dir, .{ .iterate = true }) catch |err| switch (err) {
        error.FileNotFound => return allocator.alloc([]u8, 0),
        else => return err,
    };
    defer dir.close();

    var names: std.ArrayList([]u8) = .empty;
    errdefer deinitNameList(allocator, &names);
    var it = dir.iterate();
    while (try it.next()) |entry| {
        if (entry.kind != .directory) continue;
        if (!manifest.isValidPluginName(entry.name)) continue;
        if (try nameListed(allocator, disabled_path, entry.name)) continue;
        const plugin_dir = try std.fmt.allocPrint(allocator, "{s}/{s}", .{ plugins_dir, entry.name });
        defer allocator.free(plugin_dir);
        const manifest_path = try std.fmt.allocPrint(allocator, "{s}/plugin.lua", .{plugin_dir});
        defer allocator.free(manifest_path);
        const source = std.fs.cwd().readFileAlloc(allocator, manifest_path, max_plugin_file_bytes) catch |err| switch (err) {
            error.FileNotFound => continue,
            else => return err,
        };
        defer allocator.free(source);

        var runtime = try Runtime.initSandboxedWithOptions(allocator, .{ .require_root = plugin_dir });
        defer runtime.deinit();
        var loaded = runtime.loadManifestStrict(source) catch |err| switch (err) {
            error.LuaCpuBudgetExceeded => {
                try recordSlowStrike(allocator, strikes_path, disabled_path, entry.name);
                continue;
            },
            else => return err,
        };
        defer loaded.deinit(allocator);
        try clearSlowStrike(allocator, strikes_path, loaded.manifest.name);
        if (try nameListed(allocator, disabled_path, loaded.manifest.name)) continue;
        try names.append(allocator, try allocator.dupe(u8, loaded.manifest.name));
    }

    return names.toOwnedSlice(allocator);
}

pub fn checkHostApiCall(capabilities: manifest.Capabilities, context: capability.Context, call: capability.HostApiCall) capability.Error!void {
    try capability.Gate.init(capabilities, context).checkCall(call);
}

pub fn statePathForPluginsDirAlloc(allocator: std.mem.Allocator, plugins_dir: []const u8, basename: []const u8) ![]u8 {
    const dir = std.fs.path.dirname(plugins_dir) orelse return error.MissingConfigDir;
    return std.fmt.allocPrint(allocator, "{s}/{s}", .{ dir, basename });
}

pub fn recordSlowStrike(allocator: std.mem.Allocator, strikes_path: []const u8, disabled_path: []const u8, name: []const u8) !void {
    const count = try incrementSlowStrike(allocator, strikes_path, name);
    if (count >= plugin_slow_strike_limit) try setNameListed(allocator, disabled_path, name, true);
}

pub fn clearSlowStrike(allocator: std.mem.Allocator, strikes_path: []const u8, name: []const u8) !void {
    try setSlowStrikeCount(allocator, strikes_path, name, 0);
}

pub fn nameListed(allocator: std.mem.Allocator, path: []const u8, name: []const u8) !bool {
    var names = try readNames(allocator, path);
    defer deinitNameList(allocator, &names);
    return indexOfString(names.items, name) != null;
}

pub fn dupeNames(allocator: std.mem.Allocator, items: []const []const u8) ![][]u8 {
    const out = try allocator.alloc([]u8, items.len);
    var filled: usize = 0;
    errdefer {
        for (out[0..filled]) |item| allocator.free(item);
        allocator.free(out);
    }
    for (items) |item| {
        out[filled] = try allocator.dupe(u8, item);
        filled += 1;
    }
    return out;
}

pub fn freeNames(allocator: std.mem.Allocator, items: [][]u8) void {
    for (items) |item| allocator.free(item);
    allocator.free(items);
}

fn incrementSlowStrike(allocator: std.mem.Allocator, strikes_path: []const u8, name: []const u8) !u8 {
    var strikes = try readSlowStrikes(allocator, strikes_path);
    defer deinitSlowStrikes(allocator, &strikes);
    const index = indexOfSlowStrike(strikes.items, name);
    const count = if (index) |i| @min(strikes.items[i].count +| 1, plugin_slow_strike_limit) else 1;
    try setSlowStrikeCountLoaded(allocator, strikes_path, &strikes, name, count);
    return count;
}

fn setSlowStrikeCount(allocator: std.mem.Allocator, strikes_path: []const u8, name: []const u8, count: u8) !void {
    var strikes = try readSlowStrikes(allocator, strikes_path);
    defer deinitSlowStrikes(allocator, &strikes);
    try setSlowStrikeCountLoaded(allocator, strikes_path, &strikes, name, count);
}

fn setSlowStrikeCountLoaded(allocator: std.mem.Allocator, strikes_path: []const u8, strikes: *std.ArrayList(SlowStrike), name: []const u8, count: u8) !void {
    if (!manifest.isValidPluginName(name)) return error.InvalidPluginName;
    if (indexOfSlowStrike(strikes.items, name)) |index| {
        if (count == 0) {
            const removed = strikes.orderedRemove(index);
            allocator.free(removed.name);
        } else {
            strikes.items[index].count = count;
        }
    } else if (count != 0) {
        try strikes.append(allocator, .{ .name = try allocator.dupe(u8, name), .count = count });
    }
    std.mem.sort(SlowStrike, strikes.items, {}, lessThanSlowStrike);
    try writeSlowStrikes(allocator, strikes_path, strikes.items);
}

const SlowStrike = struct {
    name: []u8,
    count: u8,
};

fn readSlowStrikes(allocator: std.mem.Allocator, path: []const u8) !std.ArrayList(SlowStrike) {
    var strikes: std.ArrayList(SlowStrike) = .empty;
    const contents = std.fs.cwd().readFileAlloc(allocator, path, 1024 * 1024) catch |err| switch (err) {
        error.FileNotFound => return strikes,
        else => return err,
    };
    defer allocator.free(contents);

    var lines = std.mem.tokenizeScalar(u8, contents, '\n');
    while (lines.next()) |line| {
        var fields = std.mem.tokenizeAny(u8, std.mem.trim(u8, line, " \t\r"), " \t\r");
        const name = fields.next() orelse continue;
        const count_text = fields.next() orelse continue;
        if (fields.next() != null or !manifest.isValidPluginName(name)) continue;
        const count = std.fmt.parseInt(u8, count_text, 10) catch continue;
        if (count == 0 or indexOfSlowStrike(strikes.items, name) != null) continue;
        try strikes.append(allocator, .{ .name = try allocator.dupe(u8, name), .count = @min(count, plugin_slow_strike_limit) });
    }
    return strikes;
}

fn writeSlowStrikes(allocator: std.mem.Allocator, path: []const u8, strikes: []const SlowStrike) !void {
    if (std.fs.path.dirname(path)) |parent| try std.fs.cwd().makePath(parent);
    var file = try std.fs.createFileAbsolute(path, .{ .truncate = true, .mode = 0o600 });
    defer file.close();
    for (strikes) |strike| {
        const line = try std.fmt.allocPrint(allocator, "{s} {d}\n", .{ strike.name, strike.count });
        defer allocator.free(line);
        try file.writeAll(line);
    }
}

fn deinitSlowStrikes(allocator: std.mem.Allocator, strikes: *std.ArrayList(SlowStrike)) void {
    for (strikes.items) |strike| allocator.free(strike.name);
    strikes.deinit(allocator);
}

fn indexOfSlowStrike(strikes: []const SlowStrike, name: []const u8) ?usize {
    for (strikes, 0..) |strike, index| {
        if (std.mem.eql(u8, strike.name, name)) return index;
    }
    return null;
}

fn lessThanSlowStrike(_: void, lhs: SlowStrike, rhs: SlowStrike) bool {
    return std.mem.lessThan(u8, lhs.name, rhs.name);
}

fn setNameListed(allocator: std.mem.Allocator, path: []const u8, name: []const u8, listed: bool) !void {
    if (!manifest.isValidPluginName(name)) return error.InvalidPluginName;
    var names = try readNames(allocator, path);
    defer deinitNameList(allocator, &names);

    const index = indexOfString(names.items, name);
    if (listed and index == null) {
        try names.append(allocator, try allocator.dupe(u8, name));
    } else if (!listed and index != null) {
        const removed = names.orderedRemove(index.?);
        allocator.free(removed);
    }
    std.mem.sort([]u8, names.items, {}, lessThanString);
    try writeNames(path, names.items);
}

fn readNames(allocator: std.mem.Allocator, path: []const u8) !std.ArrayList([]u8) {
    var names: std.ArrayList([]u8) = .empty;
    const contents = std.fs.cwd().readFileAlloc(allocator, path, 1024 * 1024) catch |err| switch (err) {
        error.FileNotFound => return names,
        else => return err,
    };
    defer allocator.free(contents);

    var lines = std.mem.tokenizeScalar(u8, contents, '\n');
    while (lines.next()) |line| {
        const trimmed = std.mem.trim(u8, line, " \t\r");
        if (trimmed.len == 0 or !manifest.isValidPluginName(trimmed)) continue;
        if (indexOfString(names.items, trimmed) == null) try names.append(allocator, try allocator.dupe(u8, trimmed));
    }
    return names;
}

fn writeNames(path: []const u8, names: []const []const u8) !void {
    if (std.fs.path.dirname(path)) |parent| try std.fs.cwd().makePath(parent);
    var file = try std.fs.createFileAbsolute(path, .{ .truncate = true, .mode = 0o600 });
    defer file.close();
    for (names) |name| {
        try file.writeAll(name);
        try file.writeAll("\n");
    }
}

fn deinitNameList(allocator: std.mem.Allocator, items: *std.ArrayList([]u8)) void {
    for (items.items) |item| allocator.free(item);
    items.deinit(allocator);
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

test "slow plugin strikes disable after third strike" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-plugin-strikes-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    const plugins_dir = try std.fmt.allocPrint(allocator, "{s}/plugins", .{dir_path});
    defer allocator.free(plugins_dir);
    const strikes_path = try statePathForPluginsDirAlloc(allocator, plugins_dir, "plugins.slow-strikes");
    defer allocator.free(strikes_path);
    const disabled_path = try statePathForPluginsDirAlloc(allocator, plugins_dir, "plugins.disabled");
    defer allocator.free(disabled_path);

    try recordSlowStrike(allocator, strikes_path, disabled_path, "slow-plugin");
    try std.testing.expect(!(try nameListed(allocator, disabled_path, "slow-plugin")));
    try recordSlowStrike(allocator, strikes_path, disabled_path, "slow-plugin");
    try std.testing.expect(!(try nameListed(allocator, disabled_path, "slow-plugin")));
    try recordSlowStrike(allocator, strikes_path, disabled_path, "slow-plugin");
    try std.testing.expect(try nameListed(allocator, disabled_path, "slow-plugin"));

    const strikes = try std.fs.cwd().readFileAlloc(allocator, strikes_path, 4096);
    defer allocator.free(strikes);
    try std.testing.expectEqualStrings("slow-plugin 3\n", strikes);
}

test "daemon checks plugin host api calls through capability gate" {
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();
    try tmp.dir.makePath("repo/.git");
    try tmp.dir.writeFile(.{ .sub_path = "repo/config.toml", .data = "" });
    try tmp.dir.writeFile(.{ .sub_path = "repo/.git/HEAD", .data = "ref: refs/heads/main\n" });

    const allocator = std.testing.allocator;
    const repo = try tmp.dir.realpathAlloc(allocator, "repo");
    defer allocator.free(repo);
    const repo_git = try tmp.dir.realpathAlloc(allocator, "repo/.git");
    defer allocator.free(repo_git);
    const config_path = try tmp.dir.realpathAlloc(allocator, "repo/config.toml");
    defer allocator.free(config_path);
    const git_head = try tmp.dir.realpathAlloc(allocator, "repo/.git/HEAD");
    defer allocator.free(git_head);
    const read_pattern = try std.fmt.allocPrint(allocator, "{s}/**", .{repo});
    defer allocator.free(read_pattern);
    const watch_pattern = try std.fmt.allocPrint(allocator, "{s}/**", .{repo_git});
    defer allocator.free(watch_pattern);
    const read_patterns = [_][]const u8{read_pattern};
    const watch_patterns = [_][]const u8{watch_pattern};
    const capabilities = manifest.Capabilities{
        .fs_read = read_patterns[0..],
        .fs_watch = watch_patterns[0..],
        .exec = .{ .allow = &.{"git"} },
        .net = .{ .allow = &.{"api.example.com"} },
        .env_read = &.{"AWS_PROFILE"},
        .secrets = true,
        .pre_exec = true,
    };
    const context = capability.Context{};

    try checkHostApiCall(capabilities, context, .{ .fs_read = config_path });
    try checkHostApiCall(capabilities, context, .{ .fs_watch = git_head });
    try checkHostApiCall(capabilities, context, .{ .exec = "git" });
    try checkHostApiCall(capabilities, context, .{ .net = "api.example.com" });
    try checkHostApiCall(capabilities, context, .{ .env_read = "AWS_PROFILE" });
    try checkHostApiCall(capabilities, context, .secrets);
    try checkHostApiCall(capabilities, context, .pre_exec);
    try std.testing.expectError(error.CapabilityDenied, checkHostApiCall(capabilities, context, .{ .exec = "sh" }));
}
