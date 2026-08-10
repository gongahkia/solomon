const std = @import("std");
const plugin_lua = @import("plugin_lua");

pub const capability = plugin_lua.capability;
pub const manifest = plugin_lua.manifest;
pub const Runtime = plugin_lua.Runtime;

const max_plugin_file_bytes = 1024 * 1024;
const plugin_slow_strike_limit: u8 = 3;
const max_host_read_bytes = 64 * 1024;
const max_host_output_bytes = 64 * 1024;

pub const HostPhase = enum {
    lifecycle,
    render,
    update,
    preexec,
};

/// A loaded plugin keeps the sandbox VM that evaluated its manifest. Keeping
/// the VM alive is what makes lifecycle hooks and plugin-local cached state
/// meaningful; manifest-only loading discarded both previously.
pub const Instance = struct {
    allocator: std.mem.Allocator,
    directory: []u8,
    runtime: *Runtime,
    loaded: plugin_lua.OwnedManifest,
    host: *HostState,
    mutex: std.Thread.Mutex = .{},
    update_queued: std.atomic.Value(bool) = std.atomic.Value(bool).init(false),

    pub fn init(allocator: std.mem.Allocator, directory: []const u8) !Instance {
        const manifest_path = try std.fmt.allocPrint(allocator, "{s}/plugin.lua", .{directory});
        defer allocator.free(manifest_path);
        const source = try std.fs.cwd().readFileAlloc(allocator, manifest_path, max_plugin_file_bytes);
        defer allocator.free(source);
        const runtime = try allocator.create(Runtime);
        errdefer allocator.destroy(runtime);
        runtime.* = try Runtime.initSandboxedWithOptions(allocator, .{ .require_root = directory });
        errdefer runtime.deinit();
        const loaded = try runtime.loadManifestStrict(source);
        errdefer {
            var owned = loaded;
            owned.deinit(allocator);
        }
        const host = try HostState.init(allocator, directory, loaded.manifest);
        errdefer host.deinit();
        try runtime.installHostApi(&host.api);
        return .{
            .allocator = allocator,
            .directory = try allocator.dupe(u8, directory),
            .runtime = runtime,
            .loaded = loaded,
            .host = host,
        };
    }

    pub fn deinit(self: *Instance) void {
        self.callLifecycle(self.loaded.manifest.entry_points.on_unload, "{}") catch {};
        self.loaded.deinit(self.allocator);
        self.runtime.deinit();
        self.allocator.destroy(self.runtime);
        self.host.deinit();
        self.allocator.free(self.directory);
        self.* = undefined;
    }

    pub fn activate(self: *Instance) !void {
        try self.callLifecycle(self.loaded.manifest.entry_points.on_load, "{}");
    }

    pub fn renderAlloc(self: *Instance, cwd: []const u8, module_id: []const u8) !?[]u8 {
        const context = try self.host.prepareContextExpressionAlloc(.render, cwd, module_id, "");
        defer self.allocator.free(context);
        self.mutex.lock();
        defer self.mutex.unlock();
        defer self.host.clearContext();
        return self.runtime.callGlobalStringAlloc(self.loaded.manifest.entry_points.render, context);
    }

    pub fn update(self: *Instance, cwd: []const u8, module_id: []const u8) !void {
        const hook = self.loaded.manifest.entry_points.update orelse return;
        const context = try self.host.prepareContextExpressionAlloc(.update, cwd, module_id, "");
        defer self.allocator.free(context);
        self.mutex.lock();
        defer self.mutex.unlock();
        defer self.host.clearContext();
        try self.runtime.callGlobalNoResult(hook, context);
    }

    pub fn setConfigLua(self: *Instance, config_lua: []const u8) !void {
        self.mutex.lock();
        defer self.mutex.unlock();
        try self.host.setConfigLua(config_lua);
    }

    pub fn preexecDecisionAlloc(self: *Instance, cwd: []const u8, command: []const u8) !?Runtime.PreexecDecision {
        const hook = self.loaded.manifest.entry_points.pre_exec orelse return null;
        try checkHostApiCall(self.loaded.manifest.capabilities, .{ .plugin_dir = self.directory }, .pre_exec);
        const context = try self.host.prepareContextExpressionAlloc(.preexec, cwd, "", command);
        defer self.allocator.free(context);
        self.mutex.lock();
        defer self.mutex.unlock();
        defer self.host.clearContext();
        return self.runtime.callGlobalPreexecDecisionAlloc(hook, context);
    }

    pub const WatchRequest = struct {
        module_id: []u8,
        cwd: []u8,
        path: []u8,
    };

    pub fn takeWatchRequestsAlloc(self: *Instance, allocator: std.mem.Allocator) ![]WatchRequest {
        self.mutex.lock();
        defer self.mutex.unlock();
        return self.host.takeWatchesAlloc(allocator);
    }

    pub fn invalidateCache(self: *Instance) void {
        self.mutex.lock();
        defer self.mutex.unlock();
        self.host.clearCache();
    }

    pub fn freeWatchRequests(allocator: std.mem.Allocator, requests: []WatchRequest) void {
        for (requests) |request| {
            allocator.free(request.module_id);
            allocator.free(request.cwd);
            allocator.free(request.path);
        }
        allocator.free(requests);
    }

    fn callLifecycle(self: *Instance, hook: ?[]const u8, context: []const u8) !void {
        const name = hook orelse return;
        self.mutex.lock();
        defer self.mutex.unlock();
        try self.runtime.callGlobalNoResult(name, context);
    }
};

const HostState = struct {
    allocator: std.mem.Allocator,
    plugin_dir: []u8,
    home: ?[]u8,
    capabilities: manifest.Capabilities,
    api: plugin_lua.HostApi,
    phase: HostPhase = .lifecycle,
    cwd: []u8 = &.{},
    module_id: []u8 = &.{},
    command: []u8 = &.{},
    config_lua: []u8,
    cache: std.StringHashMap([]u8),
    watches: std.ArrayList(Instance.WatchRequest) = .empty,

    fn init(allocator: std.mem.Allocator, plugin_dir: []const u8, plugin_manifest: manifest.Manifest) !*HostState {
        const host = try allocator.create(HostState);
        errdefer allocator.destroy(host);
        const owned_plugin_dir = try allocator.dupe(u8, plugin_dir);
        errdefer allocator.free(owned_plugin_dir);
        const home = std.process.getEnvVarOwned(allocator, "HOME") catch |err| switch (err) {
            error.EnvironmentVariableNotFound => null,
            else => return err,
        };
        errdefer if (home) |value| allocator.free(value);
        const config_lua = try allocator.dupe(u8, "{}");
        errdefer allocator.free(config_lua);
        host.* = .{
            .allocator = allocator,
            .plugin_dir = owned_plugin_dir,
            .home = home,
            .capabilities = plugin_manifest.capabilities,
            .api = .{ .callback = hostApiCallback, .user_data = @ptrCast(host) },
            .config_lua = config_lua,
            .cache = std.StringHashMap([]u8).init(allocator),
        };
        return host;
    }

    fn deinit(self: *HostState) void {
        self.clearContext();
        self.clearCache();
        self.cache.deinit();
        for (self.watches.items) |request| {
            self.allocator.free(request.module_id);
            self.allocator.free(request.cwd);
            self.allocator.free(request.path);
        }
        self.watches.deinit(self.allocator);
        self.allocator.free(self.config_lua);
        if (self.home) |home| self.allocator.free(home);
        self.allocator.free(self.plugin_dir);
        self.allocator.destroy(self);
    }

    fn prepareContextExpressionAlloc(self: *HostState, phase: HostPhase, cwd: []const u8, module_id: []const u8, command: []const u8) ![]u8 {
        self.clearContext();
        self.phase = phase;
        self.cwd = try self.allocator.dupe(u8, cwd);
        errdefer self.clearContext();
        self.module_id = try self.allocator.dupe(u8, module_id);
        errdefer self.clearContext();
        self.command = try self.allocator.dupe(u8, command);
        return pluginContextExpressionAlloc(self.allocator, cwd, module_id, command, self.config_lua);
    }

    fn clearContext(self: *HostState) void {
        if (self.cwd.len != 0) self.allocator.free(self.cwd);
        if (self.module_id.len != 0) self.allocator.free(self.module_id);
        if (self.command.len != 0) self.allocator.free(self.command);
        self.cwd = &.{};
        self.module_id = &.{};
        self.command = &.{};
        self.phase = .lifecycle;
    }

    fn gate(self: *const HostState) capability.Gate {
        return .{ .capabilities = self.capabilities, .context = .{ .home = self.home, .plugin_dir = self.plugin_dir } };
    }

    fn registerWatch(self: *HostState, path: []const u8) !void {
        for (self.watches.items) |existing| {
            if (std.mem.eql(u8, existing.module_id, self.module_id) and std.mem.eql(u8, existing.cwd, self.cwd) and std.mem.eql(u8, existing.path, path)) return;
        }
        try self.watches.append(self.allocator, .{
            .module_id = try self.allocator.dupe(u8, self.module_id),
            .cwd = try self.allocator.dupe(u8, self.cwd),
            .path = try self.allocator.dupe(u8, path),
        });
    }

    fn clearCache(self: *HostState) void {
        var it = self.cache.iterator();
        while (it.next()) |entry| {
            self.allocator.free(entry.key_ptr.*);
            self.allocator.free(entry.value_ptr.*);
        }
        self.cache.clearRetainingCapacity();
    }

    fn setConfigLua(self: *HostState, config_lua: []const u8) !void {
        const copied = try self.allocator.dupe(u8, config_lua);
        self.allocator.free(self.config_lua);
        self.config_lua = copied;
    }

    fn takeWatchesAlloc(self: *HostState, allocator: std.mem.Allocator) ![]Instance.WatchRequest {
        const out = try allocator.alloc(Instance.WatchRequest, self.watches.items.len);
        var initialized: usize = 0;
        errdefer {
            for (out[0..initialized]) |request| {
                allocator.free(request.module_id);
                allocator.free(request.cwd);
                allocator.free(request.path);
            }
            allocator.free(out);
        }
        for (self.watches.items) |request| {
            out[initialized] = .{
                .module_id = try allocator.dupe(u8, request.module_id),
                .cwd = try allocator.dupe(u8, request.cwd),
                .path = try allocator.dupe(u8, request.path),
            };
            initialized += 1;
        }
        for (self.watches.items) |request| {
            self.allocator.free(request.module_id);
            self.allocator.free(request.cwd);
            self.allocator.free(request.path);
        }
        self.watches.clearRetainingCapacity();
        return out;
    }
};

fn pluginContextExpressionAlloc(allocator: std.mem.Allocator, cwd: []const u8, module_id: []const u8, command: []const u8, config_lua: []const u8) ![]u8 {
    const cwd_quoted = try luaQuoteAlloc(allocator, cwd);
    defer allocator.free(cwd_quoted);
    const module_quoted = try luaQuoteAlloc(allocator, module_id);
    defer allocator.free(module_quoted);
    const command_quoted = try luaQuoteAlloc(allocator, command);
    defer allocator.free(command_quoted);
    return std.fmt.allocPrint(
        allocator,
        "{{ cwd = {s}, module = {s}, command = {s}, config = {s}, fs = {{ read = _shisa_fs_read, watch = _shisa_fs_watch }}, env = {{ get = _shisa_env_get }}, secrets = {{ get = _shisa_secret_get }}, exec = {{ run = _shisa_exec_run }}, net = {{ get = _shisa_net_get }}, cache = {{ get = _shisa_cache_get, set = _shisa_cache_set }} }}",
        .{ cwd_quoted, module_quoted, command_quoted, config_lua },
    );
}

fn luaQuoteAlloc(allocator: std.mem.Allocator, value: []const u8) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    errdefer out.deinit(allocator);
    try out.append(allocator, '"');
    for (value) |byte| switch (byte) {
        '\\' => try out.appendSlice(allocator, "\\\\"),
        '"' => try out.appendSlice(allocator, "\\\""),
        '\n' => try out.appendSlice(allocator, "\\n"),
        '\r' => try out.appendSlice(allocator, "\\r"),
        else => try out.append(allocator, byte),
    };
    try out.append(allocator, '"');
    return out.toOwnedSlice(allocator);
}

/// Plugin refresh hooks run away from the prompt connection. The queue is
/// deliberately short and has a fixed number of workers: a busy plugin can
/// lose a refresh request, but cannot create an unbounded number of processes
/// or threads on an interactive shell path.
pub const UpdateScheduler = struct {
    allocator: std.mem.Allocator,
    mutex: std.Thread.Mutex = .{},
    tasks: std.ArrayList(Task) = .empty,
    threads: []std.Thread = &.{},
    stopping: bool = false,

    pub const worker_count: usize = 2;
    pub const max_pending_tasks: usize = 64;

    const Task = struct {
        instance: *Instance,
        cwd: []u8,
        module_id: []u8,

        fn deinit(self: *Task, allocator: std.mem.Allocator) void {
            allocator.free(self.cwd);
            allocator.free(self.module_id);
            self.* = undefined;
        }
    };

    pub fn init(allocator: std.mem.Allocator) !*UpdateScheduler {
        const scheduler = try allocator.create(UpdateScheduler);
        errdefer allocator.destroy(scheduler);
        scheduler.* = .{ .allocator = allocator };
        scheduler.threads = try allocator.alloc(std.Thread, worker_count);
        var started: usize = 0;
        errdefer {
            scheduler.mutex.lock();
            scheduler.stopping = true;
            scheduler.mutex.unlock();
            for (scheduler.threads[0..started]) |thread| thread.join();
            allocator.free(scheduler.threads);
        }
        while (started < scheduler.threads.len) : (started += 1) {
            scheduler.threads[started] = try std.Thread.spawn(.{}, updateWorkerMain, .{scheduler});
        }
        return scheduler;
    }

    pub fn deinit(self: *UpdateScheduler) void {
        self.mutex.lock();
        self.stopping = true;
        self.mutex.unlock();
        for (self.threads) |thread| thread.join();
        for (self.tasks.items) |*task| task.deinit(self.allocator);
        self.tasks.deinit(self.allocator);
        self.allocator.free(self.threads);
        const allocator = self.allocator;
        self.* = undefined;
        allocator.destroy(self);
    }

    /// Returns false when the refresh is already scheduled or the bounded
    /// queue is under pressure. In both cases a later prompt may retry.
    pub fn schedule(self: *UpdateScheduler, instance: *Instance, cwd: []const u8, module_id: []const u8) !bool {
        if (instance.loaded.manifest.entry_points.update == null) return false;
        if (instance.update_queued.swap(true, .seq_cst)) return false;
        errdefer instance.update_queued.store(false, .seq_cst);
        self.mutex.lock();
        defer self.mutex.unlock();
        if (self.stopping or self.tasks.items.len >= max_pending_tasks) {
            instance.update_queued.store(false, .seq_cst);
            return false;
        }
        const cwd_copy = try self.allocator.dupe(u8, cwd);
        errdefer self.allocator.free(cwd_copy);
        const module_copy = try self.allocator.dupe(u8, module_id);
        errdefer self.allocator.free(module_copy);
        try self.tasks.append(self.allocator, .{
            .instance = instance,
            .cwd = cwd_copy,
            .module_id = module_copy,
        });
        return true;
    }

    fn takeTask(self: *UpdateScheduler) ?Task {
        self.mutex.lock();
        defer self.mutex.unlock();
        if (self.tasks.items.len == 0) return null;
        return self.tasks.orderedRemove(0);
    }

    fn shouldStop(self: *UpdateScheduler) bool {
        self.mutex.lock();
        defer self.mutex.unlock();
        return self.stopping;
    }

    fn workerLoop(self: *UpdateScheduler) void {
        while (true) {
            if (self.takeTask()) |task_value| {
                var task = task_value;
                defer task.deinit(self.allocator);
                _ = task.instance.update(task.cwd, task.module_id) catch {};
                task.instance.update_queued.store(false, .seq_cst);
                continue;
            }
            if (self.shouldStop()) return;
            std.Thread.sleep(2 * std.time.ns_per_ms);
        }
    }
};

fn updateWorkerMain(scheduler: *UpdateScheduler) void {
    scheduler.workerLoop();
}

fn hostApiCallback(runtime: *Runtime, user_data: ?*anyopaque, method: plugin_lua.HostMethod) callconv(.c) c_int {
    const raw_host = user_data orelse return hostPushError(runtime, "host unavailable");
    const host: *HostState = @ptrCast(@alignCast(raw_host));
    return handleHostApi(host, runtime, method) catch |err| hostPushError(runtime, @errorName(err));
}

fn hostPushError(runtime: *Runtime, message: []const u8) c_int {
    runtime.hostPushNil();
    runtime.hostPushString(message);
    return 2;
}

fn hostPushString(runtime: *Runtime, value: []const u8) c_int {
    runtime.hostPushString(value);
    return 1;
}

fn hostPushTrue(runtime: *Runtime) c_int {
    runtime.hostPushBoolean(true);
    return 1;
}

fn requireUpdatePhase(host: *const HostState) !void {
    if (host.phase != .update) return error.HostApiNotAvailableInPhase;
}

fn requireNonRenderPhase(host: *const HostState) !void {
    if (host.phase == .render) return error.HostApiNotAvailableInRender;
}

fn hostArgument(runtime: *Runtime, index: c_int) ![]const u8 {
    return runtime.hostArgumentString(index) orelse error.InvalidHostArgument;
}

fn runAllowedCommandAlloc(allocator: std.mem.Allocator, cwd: []const u8, command: []const u8, args: []const []const u8) ![]u8 {
    var argv = try allocator.alloc([]const u8, args.len + 1);
    defer allocator.free(argv);
    argv[0] = command;
    for (args, 0..) |arg, index| argv[index + 1] = arg;
    const result = try std.process.Child.run(.{
        .allocator = allocator,
        .argv = argv,
        .cwd = if (cwd.len == 0) null else cwd,
        .max_output_bytes = max_host_output_bytes,
        .expand_arg0 = .expand,
    });
    defer allocator.free(result.stderr);
    if (switch (result.term) {
        .Exited => |code| code == 0,
        else => false,
    }) return result.stdout;
    allocator.free(result.stdout);
    return error.HostCommandFailed;
}

fn netDomain(url: []const u8) ?[]const u8 {
    if (!std.mem.startsWith(u8, url, "https://")) return null;
    const authority = url["https://".len..];
    if (authority.len == 0) return null;
    const end = std.mem.indexOfAny(u8, authority, "/?#") orelse authority.len;
    const host_port = authority[0..end];
    if (host_port.len == 0 or std.mem.indexOfScalar(u8, host_port, '@') != null) return null;
    const host = host_port[0 .. std.mem.indexOfScalar(u8, host_port, ':') orelse host_port.len];
    if (host.len == 0) return null;
    return host;
}

fn dotenvValueAlloc(allocator: std.mem.Allocator, path: []const u8, name: []const u8) !?[]u8 {
    const source = std.fs.cwd().readFileAlloc(allocator, path, max_host_read_bytes) catch |err| switch (err) {
        error.FileNotFound => return null,
        else => return err,
    };
    defer allocator.free(source);
    var lines = std.mem.splitScalar(u8, source, '\n');
    while (lines.next()) |raw_line| {
        const line = std.mem.trim(u8, raw_line, " \t\r");
        if (line.len == 0 or line[0] == '#') continue;
        const equals = std.mem.indexOfScalar(u8, line, '=') orelse continue;
        const key = std.mem.trim(u8, line[0..equals], " \t");
        if (!std.mem.eql(u8, key, name)) continue;
        var value = std.mem.trim(u8, line[equals + 1 ..], " \t\r");
        if (value.len >= 2 and ((value[0] == '"' and value[value.len - 1] == '"') or (value[0] == '\'' and value[value.len - 1] == '\''))) {
            value = value[1 .. value.len - 1];
        }
        return @as(?[]u8, try allocator.dupe(u8, value));
    }
    return null;
}

fn freeStringList(allocator: std.mem.Allocator, values: [][]u8) void {
    for (values) |value| allocator.free(value);
    allocator.free(values);
}

fn handleHostApi(self: *HostState, runtime: *Runtime, method: plugin_lua.HostMethod) !c_int {
    switch (method) {
        .cache_get => {
            const key = try hostArgument(runtime, 1);
            const value = self.cache.get(key) orelse {
                runtime.hostPushNil();
                return 1;
            };
            return hostPushString(runtime, value);
        },
        .cache_set => {
            const key = try hostArgument(runtime, 1);
            const value = try hostArgument(runtime, 2);
            if (self.cache.fetchRemove(key)) |removed| {
                self.allocator.free(removed.key);
                self.allocator.free(removed.value);
            }
            const owned_key = try self.allocator.dupe(u8, key);
            errdefer self.allocator.free(owned_key);
            const owned_value = try self.allocator.dupe(u8, value);
            errdefer self.allocator.free(owned_value);
            try self.cache.put(owned_key, owned_value);
            return hostPushTrue(runtime);
        },
        .fs_read => {
            try requireNonRenderPhase(self);
            const path = try hostArgument(runtime, 1);
            try self.gate().checkFsRead(path);
            const data = try std.fs.cwd().readFileAlloc(self.allocator, path, max_host_read_bytes);
            defer self.allocator.free(data);
            return hostPushString(runtime, data);
        },
        .fs_watch => {
            try requireNonRenderPhase(self);
            const path = try hostArgument(runtime, 1);
            try self.gate().checkFsWatch(path);
            if (self.cwd.len == 0 or self.module_id.len == 0) return error.HostWatchRequiresModuleContext;
            try self.registerWatch(path);
            return hostPushTrue(runtime);
        },
        .env_get => {
            try requireNonRenderPhase(self);
            const name = try hostArgument(runtime, 1);
            try self.gate().checkEnvRead(name);
            const value = std.process.getEnvVarOwned(self.allocator, name) catch |err| switch (err) {
                error.EnvironmentVariableNotFound => {
                    runtime.hostPushNil();
                    return 1;
                },
                else => return err,
            };
            defer self.allocator.free(value);
            return hostPushString(runtime, value);
        },
        .secret_get => {
            try requireNonRenderPhase(self);
            const name = try hostArgument(runtime, 1);
            try self.gate().checkSecrets();
            const plugin_env = try std.fmt.allocPrint(self.allocator, "{s}/.env", .{self.plugin_dir});
            defer self.allocator.free(plugin_env);
            const plugin_value = try dotenvValueAlloc(self.allocator, plugin_env, name);
            if (plugin_value) |value| {
                defer self.allocator.free(value);
                return hostPushString(runtime, value);
            }
            if (self.cwd.len != 0) {
                const project_env = try std.fmt.allocPrint(self.allocator, "{s}/.env", .{self.cwd});
                defer self.allocator.free(project_env);
                const project_value = try dotenvValueAlloc(self.allocator, project_env, name);
                if (project_value) |value| {
                    defer self.allocator.free(value);
                    return hostPushString(runtime, value);
                }
            }
            runtime.hostPushNil();
            return 1;
        },
        .exec_run => {
            try requireUpdatePhase(self);
            const command = try hostArgument(runtime, 1);
            try self.gate().checkExec(command);
            const args = (try runtime.hostArgumentStringArrayAlloc(self.allocator, 2)) orelse &.{};
            defer if (args.len != 0) freeStringList(self.allocator, args);
            const const_args: []const []const u8 = args;
            const output = try runAllowedCommandAlloc(self.allocator, self.cwd, command, const_args);
            defer self.allocator.free(output);
            return hostPushString(runtime, output);
        },
        .net_get => {
            try requireUpdatePhase(self);
            const url = try hostArgument(runtime, 1);
            const domain = netDomain(url) orelse return error.InvalidHttpsUrl;
            try self.gate().checkNet(domain);
            const output = try runAllowedCommandAlloc(self.allocator, self.cwd, "curl", &.{ "--fail", "--silent", "--show-error", "--max-time", "2", "--connect-timeout", "1", url });
            defer self.allocator.free(output);
            return hostPushString(runtime, output);
        },
    }
}

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

pub fn loadInstancesAlloc(allocator: std.mem.Allocator, plugins_dir: []const u8) ![]Instance {
    const names = try loadNamesAlloc(allocator, plugins_dir);
    defer freeNames(allocator, names);
    var instances: std.ArrayList(Instance) = .empty;
    errdefer deinitInstances(allocator, &instances);
    for (names) |name| {
        const directory = try std.fmt.allocPrint(allocator, "{s}/{s}", .{ plugins_dir, name });
        defer allocator.free(directory);
        var instance = Instance.init(allocator, directory) catch |err| switch (err) {
            error.LuaCpuBudgetExceeded => continue,
            else => return err,
        };
        errdefer instance.deinit();
        try instance.activate();
        try instances.append(allocator, instance);
    }
    return instances.toOwnedSlice(allocator);
}

pub fn deinitInstances(allocator: std.mem.Allocator, instances: *std.ArrayList(Instance)) void {
    for (instances.items) |*instance| instance.deinit();
    instances.deinit(allocator);
}

pub fn freeInstances(allocator: std.mem.Allocator, instances: []Instance) void {
    for (instances) |*instance| instance.deinit();
    allocator.free(instances);
}

pub fn findInstance(instances: []Instance, plugin_name: []const u8) ?*Instance {
    for (instances) |*instance| {
        if (std.mem.eql(u8, instance.loaded.manifest.name, plugin_name)) return instance;
    }
    return null;
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

test "plugin network host accepts only HTTPS URLs with an authority" {
    try std.testing.expectEqualStrings("api.example.com", netDomain("https://api.example.com/v1/status").?);
    try std.testing.expectEqualStrings("api.example.com", netDomain("https://api.example.com:8443/v1/status").?);
    try std.testing.expect(netDomain("http://api.example.com/v1/status") == null);
    try std.testing.expect(netDomain("https:///v1/status") == null);
    try std.testing.expect(netDomain("https://:443/v1/status") == null);
    try std.testing.expect(netDomain("https://user@api.example.com/v1/status") == null);
}

test "plugin secrets parse quoted dotenv values without ambient environment access" {
    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();
    try tmp.dir.writeFile(.{ .sub_path = "plugin.env", .data = "# comment\nTOKEN = 'plugin value'\nOTHER=ignored\n" });
    const path = try tmp.dir.realpathAlloc(std.testing.allocator, "plugin.env");
    defer std.testing.allocator.free(path);
    const value = try dotenvValueAlloc(std.testing.allocator, path, "TOKEN");
    defer if (value) |item| std.testing.allocator.free(item);
    try std.testing.expectEqualStrings("plugin value", value.?);
    try std.testing.expect((try dotenvValueAlloc(std.testing.allocator, path, "MISSING")) == null);
}
