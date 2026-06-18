const std = @import("std");
const cdhint_module = @import("modules/cdhint.zig");
const cloud_ctx_module = @import("modules/cloud_ctx.zig");
const dispatcher = @import("dispatcher.zig");
const cost_glance_module = @import("modules/cost_glance.zig");
const cwd_module = @import("modules/cwd.zig");
const git_branch_module = @import("modules/git_branch.zig");
const iac_workspace_module = @import("modules/iac_workspace.zig");
const language_versions_module = @import("modules/language_versions.zig");
const prod_guard_module = @import("modules/prod_guard.zig");
const risk_tier_module = @import("modules/risk_tier.zig");
const sso_expiry_module = @import("modules/sso_expiry.zig");
const tmux_pane_module = @import("modules/tmux_pane.zig");
const daemon_log = @import("log.zig");
const warmup = @import("warmup.zig");
const json = @import("json.zig");
const fsnotify = @import("fsnotify.zig");
const daemon_cache = @import("cache.zig");
const plugin_lua = @import("plugin_lua");
const plugin_capability = plugin_lua.capability;
const plugin_manifest = plugin_lua.manifest;

const header_bytes = 4;
const max_frame_bytes = 1024 * 1024;
const max_config_bytes = 1024 * 1024;
const default_subscribe_backpressure_limit = 16;
const max_subscribe_backpressure_limit = 1024;
pub const graceful_shutdown_timeout_ms: i64 = 5000;
const shutdown_poll_ms: i32 = 100;
const render_histogram_buckets = 5;
const prompt_cache_module = "render_prompt";
const plugin_slow_strike_limit: u8 = 3;
pub const daemon_version = "0.1.0-dev";
pub const protocol_version: u32 = 1;
const default_config_text =
    \\version = 1
    \\theme = "plain"
    \\
    \\[prompt]
    \\modules = ["cwd", "git_branch", "language_versions", "exit_status", "jobs", "cmd_duration", "user_host"]
    \\
;

const RenderRequest = struct {
    v: u32 = 1,
    op: []const u8 = "render",
    cwd: []const u8,
    exit: i32 = 0,
    jobs: u32 = 0,
    duration_ms: u64 = 0,
    time: bool = false,
    no_async: bool = false,
    shell: []const u8 = "zsh",
    cols: u16 = 80,
    rows: u16 = 24,
    request_id: []const u8 = "",
    modules: []const []const u8 = &.{},
    tmux_pane: ?[]const u8 = null,
    cloud_ctx: cloud_ctx_module.Options = .{},
    cwd_options: cwd_module.Options = .{},
    cdhint: cdhint_module.Options = .{},
    tmux_pane_options: tmux_pane_module.Options = .{},
    risk_tier: risk_tier_module.BarColors = .{},
    sso_expiry: sso_expiry_module.Options = .{},
    rtl: bool = false,
    rtl_reverse: bool = false,
};

const PreexecRequest = struct {
    v: u32 = 1,
    kind: []const u8 = "",
    cwd: []const u8 = "",
    shell: []const u8 = "",
    command: []const u8 = "",
    force: bool = false,
};

const MetricsRequest = struct {
    v: u32 = 1,
    op: []const u8 = "metrics",
    request_id: []const u8 = "",
    format: []const u8 = "json",
};

const SubscribeRequest = struct {
    v: u32 = 1,
    op: []const u8 = "subscribe",
    request_id: []const u8 = "",
    topics: []const []const u8 = &.{},
    backpressure_limit: u16 = default_subscribe_backpressure_limit,
};

const SubscribeCommand = struct {
    op: []const u8 = "",
    kind: []const u8 = "",
};

const RenderCacheSnapshot = struct {
    git_valid: bool = false,
    git_in_flight: bool = false,
    git_generation: u64 = 0,
    git_cwd: ?[]const u8 = null,
    language_valid: bool = false,
    language_in_flight: bool = false,
    language_generation: u64 = 0,
    language_cwd: ?[]const u8 = null,
    gcp_valid: bool = false,
    azure_valid: bool = false,
    kube_valid: bool = false,
};

const RenderCacheContext = struct {
    timestamp_minute: i64 = 0,
    home: ?[]const u8 = null,
    kubeconfig: ?[]const u8 = null,
    ssh: ?[]const u8 = null,
    user: []const u8 = "",
    host: []const u8 = "",
    aws_profile: ?[]const u8 = null,
    aws_region: ?[]const u8 = null,
    aws_default_region: ?[]const u8 = null,
    cloudsdk_compute_region: ?[]const u8 = null,
    azure_location: ?[]const u8 = null,
    arm_location: ?[]const u8 = null,
    azure_default_location: ?[]const u8 = null,
    config_generation: u64 = 0,
    plugin_generation: u64 = 0,
    cache_rev: u64 = 0,
    snapshot: RenderCacheSnapshot = .{},
};

const TopicRef = struct {
    topic: []u8,
    count: usize,
};

const SubscriptionQueue = struct {
    allocator: std.mem.Allocator,
    max_events: usize,
    events: std.ArrayList([]u8) = .empty,
    dropped: u64 = 0,

    fn init(allocator: std.mem.Allocator, max_events: usize) SubscriptionQueue {
        return .{
            .allocator = allocator,
            .max_events = @max(max_events, 1),
        };
    }

    fn deinit(self: *SubscriptionQueue) void {
        for (self.events.items) |event| self.allocator.free(event);
        self.events.deinit(self.allocator);
        self.* = undefined;
    }

    fn pushOwned(self: *SubscriptionQueue, event: []u8) !bool {
        if (self.events.items.len >= self.max_events) {
            self.allocator.free(event);
            self.dropped += 1;
            return false;
        }
        errdefer self.allocator.free(event);
        try self.events.append(self.allocator, event);
        return true;
    }

    fn flush(self: *SubscriptionQueue, fd: std.posix.fd_t) !void {
        for (self.events.items) |event| {
            try writeAll(fd, event);
            self.allocator.free(event);
        }
        self.events.clearRetainingCapacity();
    }
};

const ReloadState = struct {
    config_generation: u64 = 0,
    plugin_generation: u64 = 0,
    config_source: []u8 = &.{},
    plugin_names: [][]u8 = &.{},

    fn deinit(self: *ReloadState, allocator: std.mem.Allocator) void {
        allocator.free(self.config_source);
        freeStringList(allocator, self.plugin_names);
        self.* = .{};
    }
};

pub const Server = struct {
    socket_path: []const u8,
    listener: std.net.Server,
    logger: ?*daemon_log.Logger = null,
    connections: u64 = 0,
    render_count: u64 = 0,
    render_total_us: u64 = 0,
    render_max_us: u64 = 0,
    render_histogram: [render_histogram_buckets]u64 = [_]u64{0} ** render_histogram_buckets,
    prompt_cache: daemon_cache.Store,
    prompt_cache_hits: u64 = 0,
    prompt_cache_misses: u64 = 0,
    cache_rev: u64 = 0,
    git_branch_cache: git_branch_module.Cache = .{},
    language_versions_cache: language_versions_module.Cache = .{},
    cloud_ctx_cache: cloud_ctx_module.Cache = .{},
    fs_watcher: fsnotify.Watcher,
    prod_guard_audit_home: ?[]const u8 = null,
    cost_refresh_shutdown: std.atomic.Value(bool) = std.atomic.Value(bool).init(false),
    cost_refresh_thread: ?std.Thread = null,
    cost_refresh_home: ?[]u8 = null,
    reload_state: ReloadState = .{},
    config_path_override: ?[]const u8 = null,
    plugins_dir_override: ?[]const u8 = null,

    pub fn init(socket_path: []const u8) !Server {
        return initWithLogger(socket_path, null);
    }

    pub fn initWithLogger(socket_path: []const u8, logger: ?*daemon_log.Logger) !Server {
        if (std.fs.path.dirname(socket_path)) |parent| {
            try std.fs.cwd().makePath(parent);
        }

        std.fs.deleteFileAbsolute(socket_path) catch |err| switch (err) {
            error.FileNotFound => {},
            else => return err,
        };

        const address = try std.net.Address.initUnix(socket_path);
        const listener = try address.listen(.{
            .reuse_address = false,
            .force_nonblocking = false,
            .kernel_backlog = 128,
        });

        return .{
            .socket_path = socket_path,
            .listener = listener,
            .logger = logger,
            .prompt_cache = daemon_cache.Store.initWithOptions(std.heap.page_allocator, .{ .max_entries = 1024, .max_age_ns = 5 * std.time.ns_per_min }),
            .fs_watcher = fsnotify.Watcher.init(std.heap.page_allocator),
        };
    }

    pub fn deinit(self: *Server) void {
        self.stopCostRefresh();
        self.prompt_cache.deinit();
        self.git_branch_cache.deinit(std.heap.page_allocator);
        self.language_versions_cache.deinit(std.heap.page_allocator);
        self.cloud_ctx_cache.deinit(std.heap.page_allocator);
        self.fs_watcher.deinit();
        self.reload_state.deinit(std.heap.page_allocator);
        self.listener.deinit();
        std.fs.deleteFileAbsolute(self.socket_path) catch {};
        self.* = undefined;
    }

    pub fn serve(self: *Server, shutdown_requested: *const std.atomic.Value(bool), reload_requested: *std.atomic.Value(bool), stack_dump_requested: *std.atomic.Value(bool)) !void {
        try self.warmupCaches(std.heap.page_allocator);
        try self.startCostRefresh(std.heap.page_allocator);
        while (!shutdown_requested.load(.seq_cst)) {
            try self.consumeReloadSignal(reload_requested);
            try self.consumeStackDumpSignal(stack_dump_requested);
            var poll_fds = [_]std.posix.pollfd{.{
                .fd = self.listener.stream.handle,
                .events = std.posix.POLL.IN,
                .revents = 0,
            }};

            const ready = try std.posix.poll(&poll_fds, shutdown_poll_ms);
            if (ready == 0) continue;

            if ((poll_fds[0].revents & std.posix.POLL.IN) != 0) {
                try self.acceptOneWithShutdown(shutdown_requested);
            }
        }
    }

    fn consumeStackDumpSignal(self: *Server, stack_dump_requested: *std.atomic.Value(bool)) !void {
        if (!stack_dump_requested.swap(false, .seq_cst)) return;
        const message = try stackDumpMessageAlloc(std.heap.page_allocator);
        defer std.heap.page_allocator.free(message);
        if (self.logger) |logger| {
            try logger.warn("stack_dump", message);
        } else {
            try std.fs.File.stderr().writeAll(message);
            try std.fs.File.stderr().writeAll("\n");
        }
    }

    fn consumeReloadSignal(self: *Server, reload_requested: *std.atomic.Value(bool)) !void {
        if (!reload_requested.swap(false, .seq_cst)) return;
        self.reloadConfigAndPlugins(std.heap.page_allocator) catch |err| {
            if (self.logger) |logger| {
                try logger.warn("reload_failed", @errorName(err));
            }
            return;
        };
        if (self.logger) |logger| {
            try logger.info("reloaded", "config and plugins reloaded");
        }
    }

    fn startCostRefresh(self: *Server, allocator: std.mem.Allocator) !void {
        if (self.cost_refresh_thread != null) return;
        const home = std.process.getEnvVarOwned(allocator, "HOME") catch |err| switch (err) {
            error.EnvironmentVariableNotFound => null,
            else => return err,
        };
        self.cost_refresh_home = home;
        self.cost_refresh_shutdown.store(false, .seq_cst);
        self.cost_refresh_thread = try std.Thread.spawn(.{}, costRefreshThreadMain, .{self});
    }

    fn stopCostRefresh(self: *Server) void {
        self.cost_refresh_shutdown.store(true, .seq_cst);
        if (self.cost_refresh_thread) |thread| {
            thread.join();
            self.cost_refresh_thread = null;
        }
        if (self.cost_refresh_home) |home| {
            std.heap.page_allocator.free(home);
            self.cost_refresh_home = null;
        }
    }

    fn costRefreshLoop(self: *Server) void {
        var next_refresh_ns: u64 = 0;
        while (!self.cost_refresh_shutdown.load(.seq_cst)) {
            const now_ns = nowNs();
            if (now_ns >= next_refresh_ns) {
                _ = cost_glance_module.refreshCacheFromEnvironment(std.heap.page_allocator, self.cost_refresh_home, std.time.timestamp()) catch {};
                next_refresh_ns = now_ns + std.time.ns_per_hour;
            }
            std.Thread.sleep(250 * std.time.ns_per_ms);
        }
    }

    fn warmupCaches(self: *Server, allocator: std.mem.Allocator) !void {
        const history_path = warmup.historyPath(allocator) catch return;
        defer allocator.free(history_path);
        const contents = std.fs.cwd().readFileAlloc(allocator, history_path, 1024 * 1024) catch return;
        defer allocator.free(contents);
        const dirs = try warmup.topDirsFromZshHistory(allocator, contents, 10);
        defer {
            for (dirs) |dir| allocator.free(dir);
            allocator.free(dirs);
        }
        for (dirs) |dir| {
            var git = self.git_branch_cache.renderAsync(allocator, dir) catch continue;
            git.deinit(allocator);
            var lang = self.language_versions_cache.renderAsync(allocator, dir) catch continue;
            lang.deinit(allocator);
        }
    }

    pub fn acceptOne(self: *Server) !void {
        try self.acceptOneWithShutdown(null);
    }

    fn acceptOneWithShutdown(self: *Server, shutdown_requested: ?*const std.atomic.Value(bool)) !void {
        const connection = try self.listener.accept();
        self.connections += 1;
        try self.handleConnection(connection, shutdown_requested);
    }

    fn handleConnection(self: *Server, connection: std.net.Server.Connection, shutdown_requested: ?*const std.atomic.Value(bool)) !void {
        defer connection.stream.close();

        const request = try readFrameAlloc(std.heap.page_allocator, connection.stream.handle);
        defer std.heap.page_allocator.free(request);

        if (std.mem.startsWith(u8, request, "metrics")) {
            var response: [128]u8 = undefined;
            const line = try std.fmt.bufPrint(&response, "{{\"connections\":{d}}}\n", .{self.connections});
            try writeFrame(connection.stream.handle, line);
        } else if (isOpRequest(request, "metrics")) {
            const response = try self.metricsResponseAlloc(std.heap.page_allocator, request);
            defer std.heap.page_allocator.free(response);
            try writeFrame(connection.stream.handle, response);
        } else if (std.mem.startsWith(u8, request, "health")) {
            try writeFrame(connection.stream.handle, "ok\n");
        } else if (isOpRequest(request, "health")) {
            const response = try healthResponseAlloc(std.heap.page_allocator, request, true);
            defer std.heap.page_allocator.free(response);
            try writeFrame(connection.stream.handle, response);
        } else if (isOpRequest(request, "version")) {
            const response = try versionResponseAlloc(std.heap.page_allocator, request);
            defer std.heap.page_allocator.free(response);
            try writeFrame(connection.stream.handle, response);
        } else if (isOpRequest(request, "reload")) {
            const response = try self.reloadResponseAlloc(std.heap.page_allocator, request);
            defer std.heap.page_allocator.free(response);
            try writeFrame(connection.stream.handle, response);
        } else if (isOpRequest(request, "subscribe")) {
            try self.handleSubscribeConnection(connection.stream.handle, request, shutdown_requested);
        } else if (isPreexecRequest(request)) {
            const response = try self.preexecResponse(request);
            defer std.heap.page_allocator.free(response);
            try writeFrame(connection.stream.handle, response);
        } else {
            const response = try self.renderResponse(request);
            defer std.heap.page_allocator.free(response);
            try writeFrame(connection.stream.handle, response);
        }
    }

    fn renderResponse(self: *Server, request_payload: []const u8) ![]u8 {
        const start_ns = nowNs();
        var parsed = try std.json.parseFromSlice(RenderRequest, std.heap.page_allocator, request_payload, .{ .ignore_unknown_fields = true });
        defer parsed.deinit();
        if (!std.mem.eql(u8, parsed.value.op, "render") and !std.mem.eql(u8, parsed.value.op, "render_continue")) {
            const escaped_request_id = try json.escapeAlloc(std.heap.page_allocator, parsed.value.request_id);
            defer std.heap.page_allocator.free(escaped_request_id);
            return std.fmt.allocPrint(
                std.heap.page_allocator,
                "{{\"v\":1,\"request_id\":\"{s}\",\"error\":{{\"code\":\"E_MALFORMED\",\"message\":\"unsupported render path op\",\"context\":{{\"field\":\"op\",\"expected\":\"render|render_continue\"}}}}}}",
                .{escaped_request_id},
            );
        }

        self.drainFsInvalidations(nowNs());
        try self.registerGitInvalidation(parsed.value.cwd);

        const home = std.process.getEnvVarOwned(std.heap.page_allocator, "HOME") catch null;
        defer if (home) |home_path| std.heap.page_allocator.free(home_path);
        const kubeconfig = std.process.getEnvVarOwned(std.heap.page_allocator, "KUBECONFIG") catch null;
        defer if (kubeconfig) |value| std.heap.page_allocator.free(value);
        try self.registerCloudInvalidation(home, kubeconfig);

        const ssh = std.process.getEnvVarOwned(std.heap.page_allocator, "SSH_CONNECTION") catch null;
        defer if (ssh) |value| std.heap.page_allocator.free(value);
        const aws_profile = std.process.getEnvVarOwned(std.heap.page_allocator, "AWS_PROFILE") catch null;
        defer if (aws_profile) |value| std.heap.page_allocator.free(value);
        const aws_region = std.process.getEnvVarOwned(std.heap.page_allocator, "AWS_REGION") catch null;
        defer if (aws_region) |value| std.heap.page_allocator.free(value);
        const aws_default_region = std.process.getEnvVarOwned(std.heap.page_allocator, "AWS_DEFAULT_REGION") catch null;
        defer if (aws_default_region) |value| std.heap.page_allocator.free(value);
        const cloudsdk_compute_region = std.process.getEnvVarOwned(std.heap.page_allocator, "CLOUDSDK_COMPUTE_REGION") catch null;
        defer if (cloudsdk_compute_region) |value| std.heap.page_allocator.free(value);
        const azure_location = std.process.getEnvVarOwned(std.heap.page_allocator, "AZURE_LOCATION") catch null;
        defer if (azure_location) |value| std.heap.page_allocator.free(value);
        const arm_location = std.process.getEnvVarOwned(std.heap.page_allocator, "ARM_LOCATION") catch null;
        defer if (arm_location) |value| std.heap.page_allocator.free(value);
        const azure_default_location = std.process.getEnvVarOwned(std.heap.page_allocator, "AZURE_DEFAULT_LOCATION") catch null;
        defer if (azure_default_location) |value| std.heap.page_allocator.free(value);
        const user = std.process.getEnvVarOwned(std.heap.page_allocator, "USER") catch try std.heap.page_allocator.dupe(u8, "unknown");
        defer std.heap.page_allocator.free(user);
        var host_buffer: [std.posix.HOST_NAME_MAX]u8 = undefined;
        const host = std.posix.gethostname(&host_buffer) catch "unknown";
        const timestamp = std.time.timestamp();
        const cache_context = RenderCacheContext{
            .timestamp_minute = if (parsed.value.time and timestamp >= 0) @divTrunc(timestamp, 60) else 0,
            .home = home,
            .kubeconfig = kubeconfig,
            .ssh = ssh,
            .user = user,
            .host = host,
            .aws_profile = aws_profile,
            .aws_region = aws_region,
            .aws_default_region = aws_default_region,
            .cloudsdk_compute_region = cloudsdk_compute_region,
            .azure_location = azure_location,
            .arm_location = arm_location,
            .azure_default_location = azure_default_location,
            .config_generation = self.reload_state.config_generation,
            .plugin_generation = self.reload_state.plugin_generation,
            .cache_rev = self.cache_rev,
            .snapshot = self.renderCacheSnapshot(),
        };
        const cache_key = try renderPromptCacheKeyAlloc(std.heap.page_allocator, parsed.value, cache_context);
        defer std.heap.page_allocator.free(cache_key);

        if (try self.prompt_cache.get(prompt_cache_module, cache_key)) |cached| {
            self.prompt_cache_hits += 1;
            const escaped_request_id = try json.escapeAlloc(std.heap.page_allocator, parsed.value.request_id);
            defer std.heap.page_allocator.free(escaped_request_id);
            const escaped_prompt = try json.escapeAlloc(std.heap.page_allocator, cached.output);
            defer std.heap.page_allocator.free(escaped_prompt);
            const elapsed_us = (nowNs() - start_ns) / std.time.ns_per_us;
            self.recordRender(elapsed_us);
            return std.fmt.allocPrint(std.heap.page_allocator, "{{\"v\":1,\"request_id\":\"{s}\",\"prompt\":\"{s}\",\"redraw_token\":null,\"trailer\":null,\"diagnostics\":[],\"elapsed_us\":{d}}}", .{ escaped_request_id, escaped_prompt, elapsed_us });
        }
        self.prompt_cache_misses += 1;

        const cache_set = dispatcher.CacheSet{
            .git_branch = &self.git_branch_cache,
            .language_versions = &self.language_versions_cache,
            .cloud_ctx = &self.cloud_ctx_cache,
        };
        const render_input = dispatcher.RenderInput{
            .cwd = parsed.value.cwd,
            .home = home,
            .exit = parsed.value.exit,
            .jobs = parsed.value.jobs,
            .duration_ms = parsed.value.duration_ms,
            .time = parsed.value.time,
            .no_async = parsed.value.no_async,
            .timestamp = timestamp,
            .ssh = ssh,
            .user = user,
            .host = host,
            .cwd_options = parsed.value.cwd_options,
            .aws_profile = aws_profile,
            .aws_region = aws_region,
            .aws_default_region = aws_default_region,
            .cloudsdk_compute_region = cloudsdk_compute_region,
            .azure_location = azure_location,
            .arm_location = arm_location,
            .azure_default_location = azure_default_location,
            .kubeconfig = kubeconfig,
            .cloud_ctx = parsed.value.cloud_ctx,
            .cdhint = parsed.value.cdhint,
            .tmux_pane = parsed.value.tmux_pane,
            .tmux_pane_options = parsed.value.tmux_pane_options,
            .risk_tier = parsed.value.risk_tier,
            .sso_expiry = parsed.value.sso_expiry,
            .rtl = parsed.value.rtl,
            .rtl_reverse = parsed.value.rtl_reverse,
        };
        const request_pipeline = try renderPipelineFromModuleNamesAlloc(std.heap.page_allocator, parsed.value.modules);
        defer if (request_pipeline) |pipeline| std.heap.page_allocator.free(pipeline);
        var rendered = if (request_pipeline) |pipeline|
            try dispatcher.renderPipeline(std.heap.page_allocator, cache_set, render_input, pipeline)
        else
            try dispatcher.renderDefault(std.heap.page_allocator, cache_set, render_input);
        defer rendered.deinit(std.heap.page_allocator);
        try self.logSlowWarning(rendered.slow_warning);

        const escaped_request_id = try json.escapeAlloc(std.heap.page_allocator, parsed.value.request_id);
        defer std.heap.page_allocator.free(escaped_request_id);
        const escaped_prompt = try json.escapeAlloc(std.heap.page_allocator, rendered.prompt);
        defer std.heap.page_allocator.free(escaped_prompt);
        const elapsed_us = (nowNs() - start_ns) / std.time.ns_per_us;
        self.recordRender(elapsed_us);
        if (rendered.redraw_token == null) {
            var store_context = cache_context;
            store_context.snapshot = self.renderCacheSnapshot();
            const store_key = try renderPromptCacheKeyAlloc(std.heap.page_allocator, parsed.value, store_context);
            defer std.heap.page_allocator.free(store_key);
            try self.prompt_cache.put(prompt_cache_module, store_key, rendered.prompt, 0);
        }

        if (rendered.redraw_token) |token| {
            const escaped_token = try json.escapeAlloc(std.heap.page_allocator, token);
            defer std.heap.page_allocator.free(escaped_token);
            return std.fmt.allocPrint(std.heap.page_allocator, "{{\"v\":1,\"request_id\":\"{s}\",\"prompt\":\"{s}\",\"redraw_token\":\"{s}\",\"trailer\":null,\"diagnostics\":[],\"elapsed_us\":{d}}}", .{ escaped_request_id, escaped_prompt, escaped_token, elapsed_us });
        }
        return std.fmt.allocPrint(std.heap.page_allocator, "{{\"v\":1,\"request_id\":\"{s}\",\"prompt\":\"{s}\",\"redraw_token\":null,\"trailer\":null,\"diagnostics\":[],\"elapsed_us\":{d}}}", .{ escaped_request_id, escaped_prompt, elapsed_us });
    }

    fn renderCacheSnapshot(self: *Server) RenderCacheSnapshot {
        var snapshot = RenderCacheSnapshot{};

        self.git_branch_cache.mutex.lock();
        snapshot.git_valid = self.git_branch_cache.valid;
        snapshot.git_in_flight = self.git_branch_cache.in_flight;
        snapshot.git_generation = self.git_branch_cache.generation;
        snapshot.git_cwd = self.git_branch_cache.cwd;
        self.git_branch_cache.mutex.unlock();

        self.language_versions_cache.mutex.lock();
        snapshot.language_valid = self.language_versions_cache.valid;
        snapshot.language_in_flight = self.language_versions_cache.in_flight;
        snapshot.language_generation = self.language_versions_cache.generation;
        snapshot.language_cwd = self.language_versions_cache.cwd;
        self.language_versions_cache.mutex.unlock();

        self.cloud_ctx_cache.mutex.lock();
        snapshot.gcp_valid = self.cloud_ctx_cache.gcp_valid;
        snapshot.azure_valid = self.cloud_ctx_cache.azure_valid;
        snapshot.kube_valid = self.cloud_ctx_cache.kube_valid;
        self.cloud_ctx_cache.mutex.unlock();

        return snapshot;
    }

    fn preexecResponse(self: *Server, request_payload: []const u8) ![]u8 {
        var parsed = try std.json.parseFromSlice(PreexecRequest, std.heap.page_allocator, request_payload, .{ .ignore_unknown_fields = true });
        defer parsed.deinit();
        const reason = risk_tier_module.explain(parsed.value.command, null);
        const escaped_pattern = try json.escapeAlloc(std.heap.page_allocator, if (reason.pattern.len == 0) "-" else reason.pattern);
        defer std.heap.page_allocator.free(escaped_pattern);
        const destructive = prod_guard_module.destructivePattern(parsed.value.command);
        const escaped_destructive = try json.escapeAlloc(std.heap.page_allocator, destructive orelse "-");
        defer std.heap.page_allocator.free(escaped_destructive);
        const iac_warning = if (parsed.value.cwd.len == 0) null else try iac_workspace_module.preexecWarningAlloc(std.heap.page_allocator, parsed.value.cwd, parsed.value.command);
        defer if (iac_warning) |value| std.heap.page_allocator.free(value);
        const escaped_iac_warning = try json.escapeAlloc(std.heap.page_allocator, iac_warning orelse "");
        defer std.heap.page_allocator.free(escaped_iac_warning);
        const allow = parsed.value.force or destructive == null or reason.tier != .prod;
        if (destructive) |pattern| {
            try self.appendProdGuardAudit(reason.tier, allow, parsed.value.force, pattern, parsed.value.command);
            if (parsed.value.force) try self.logProdGuardForce(reason.tier, pattern);
        }
        return std.fmt.allocPrint(
            std.heap.page_allocator,
            "{{\"v\":1,\"allow\":{},\"forced\":{},\"confirm\":\"{s}\",\"tier\":\"{s}\",\"source\":\"{s}\",\"pattern\":\"{s}\",\"destructive\":{},\"destructive_pattern\":\"{s}\",\"warning\":\"{s}\"}}",
            .{ allow, parsed.value.force, if (allow) "" else risk_tier_module.tierName(reason.tier), risk_tier_module.tierName(reason.tier), risk_tier_module.sourceName(reason.source), escaped_pattern, destructive != null, escaped_destructive, escaped_iac_warning },
        );
    }

    fn logProdGuardForce(self: *Server, tier: risk_tier_module.Tier, pattern: []const u8) !void {
        const logger = self.logger orelse return;
        const message = try std.fmt.allocPrint(
            std.heap.page_allocator,
            "tier={s} pattern={s}",
            .{ risk_tier_module.tierName(tier), pattern },
        );
        defer std.heap.page_allocator.free(message);
        try logger.warn("prod_guard_force", message);
    }

    fn appendProdGuardAudit(self: *Server, tier: risk_tier_module.Tier, allow: bool, forced: bool, pattern: []const u8, command: []const u8) !void {
        const home_owned = if (self.prod_guard_audit_home == null)
            std.process.getEnvVarOwned(std.heap.page_allocator, "HOME") catch return
        else
            null;
        defer if (home_owned) |value| std.heap.page_allocator.free(value);
        const home = self.prod_guard_audit_home orelse home_owned.?;
        const path = try prodGuardAuditPathAlloc(std.heap.page_allocator, home);
        defer std.heap.page_allocator.free(path);
        if (std.fs.path.dirname(path)) |parent| try std.fs.cwd().makePath(parent);
        var file = try std.fs.createFileAbsolute(path, .{
            .read = true,
            .truncate = false,
            .mode = 0o600,
        });
        defer file.close();
        try file.seekFromEnd(0);

        const escaped_pattern = try json.escapeAlloc(std.heap.page_allocator, pattern);
        defer std.heap.page_allocator.free(escaped_pattern);
        const escaped_command = try json.escapeAlloc(std.heap.page_allocator, command);
        defer std.heap.page_allocator.free(escaped_command);
        const line = try std.fmt.allocPrint(
            std.heap.page_allocator,
            "{{\"ts\":{d},\"tier\":\"{s}\",\"allow\":{},\"forced\":{},\"pattern\":\"{s}\",\"command\":\"{s}\"}}\n",
            .{ std.time.timestamp(), risk_tier_module.tierName(tier), allow, forced, escaped_pattern, escaped_command },
        );
        defer std.heap.page_allocator.free(line);
        try file.writeAll(line);
    }

    fn logSlowWarning(self: *Server, slow_warning: ?dispatcher.SlowWarning) !void {
        const warning = slow_warning orelse return;
        if (self.logger) |logger| {
            const message = try std.fmt.allocPrint(
                std.heap.page_allocator,
                "module={s} elapsed_ns={d}",
                .{ dispatcher.moduleIdName(warning.module_id), warning.elapsed_ns },
            );
            defer std.heap.page_allocator.free(message);
            try logger.warn("slow_module", message);
        }
    }

    fn recordRender(self: *Server, elapsed_us: u64) void {
        self.render_count += 1;
        self.render_total_us += elapsed_us;
        self.render_max_us = @max(self.render_max_us, elapsed_us);
        self.render_histogram[renderHistogramIndex(elapsed_us)] += 1;
    }

    fn metricsResponseAlloc(self: *Server, allocator: std.mem.Allocator, request: []const u8) ![]u8 {
        var parsed = std.json.parseFromSlice(MetricsRequest, allocator, request, .{ .ignore_unknown_fields = true }) catch null;
        defer if (parsed) |*value| value.deinit();
        const request_id = try requestIdAlloc(allocator, request);
        defer allocator.free(request_id);
        const escaped_request_id = try json.escapeAlloc(allocator, request_id);
        defer allocator.free(escaped_request_id);

        self.git_branch_cache.mutex.lock();
        const git_valid = self.git_branch_cache.valid;
        const git_in_flight = self.git_branch_cache.in_flight;
        const git_generation = self.git_branch_cache.generation;
        self.git_branch_cache.mutex.unlock();

        self.language_versions_cache.mutex.lock();
        const language_valid = self.language_versions_cache.valid;
        const language_in_flight = self.language_versions_cache.in_flight;
        const language_generation = self.language_versions_cache.generation;
        self.language_versions_cache.mutex.unlock();

        self.cloud_ctx_cache.mutex.lock();
        const gcp_valid = self.cloud_ctx_cache.gcp_valid;
        const azure_valid = self.cloud_ctx_cache.azure_valid;
        const kube_valid = self.cloud_ctx_cache.kube_valid;
        self.cloud_ctx_cache.mutex.unlock();
        const prompt_cache_entries = self.prompt_cache.count();
        const prompt_cache_hit_rate_ppm = promptCacheHitRatePpm(self.prompt_cache_hits, self.prompt_cache_misses);

        if (parsed) |value| {
            if (std.mem.eql(u8, value.value.format, "prometheus")) {
                return self.metricsPrometheusAlloc(allocator, git_valid, git_in_flight, git_generation, language_valid, language_in_flight, language_generation, gcp_valid, azure_valid, kube_valid);
            }
        }

        return std.fmt.allocPrint(
            allocator,
            "{{\"v\":1,\"request_id\":\"{s}\",\"connections\":{d},\"cache\":{{\"git_branch\":{{\"valid\":{},\"in_flight\":{},\"generation\":{d}}},\"language_versions\":{{\"valid\":{},\"in_flight\":{},\"generation\":{d}}},\"cloud_ctx\":{{\"gcp_valid\":{},\"azure_valid\":{},\"kube_valid\":{}}},\"prompt_l1\":{{\"entries\":{d},\"hits\":{d},\"misses\":{d},\"hit_rate_ppm\":{d}}}}},\"render\":{{\"count\":{d},\"total_us\":{d},\"max_us\":{d},\"histogram\":{{\"le_100us\":{d},\"le_500us\":{d},\"le_1000us\":{d},\"le_5000us\":{d},\"gt_5000us\":{d}}}}},\"plugins\":{d},\"fsnotify\":{{\"backend\":\"{s}\",\"registrations\":{d}}}}}",
            .{ escaped_request_id, self.connections, git_valid, git_in_flight, git_generation, language_valid, language_in_flight, language_generation, gcp_valid, azure_valid, kube_valid, prompt_cache_entries, self.prompt_cache_hits, self.prompt_cache_misses, prompt_cache_hit_rate_ppm, self.render_count, self.render_total_us, self.render_max_us, self.render_histogram[0], self.render_histogram[1], self.render_histogram[2], self.render_histogram[3], self.render_histogram[4], self.reload_state.plugin_names.len, @tagName(self.fs_watcher.backend), self.fs_watcher.registrations.items.len },
        );
    }

    fn metricsPrometheusAlloc(self: *Server, allocator: std.mem.Allocator, git_valid: bool, git_in_flight: bool, git_generation: u64, language_valid: bool, language_in_flight: bool, language_generation: u64, gcp_valid: bool, azure_valid: bool, kube_valid: bool) ![]u8 {
        return std.fmt.allocPrint(
            allocator,
            "# HELP shisa_connections Active accepted connections.\n# TYPE shisa_connections gauge\nshisa_connections {d}\n# HELP shisa_render_count Render requests served.\n# TYPE shisa_render_count counter\nshisa_render_count {d}\n# HELP shisa_render_total_us Total render latency in microseconds.\n# TYPE shisa_render_total_us counter\nshisa_render_total_us {d}\n# HELP shisa_render_max_us Max observed render latency in microseconds.\n# TYPE shisa_render_max_us gauge\nshisa_render_max_us {d}\n# HELP shisa_render_latency_bucket Render latency buckets.\n# TYPE shisa_render_latency_bucket counter\nshisa_render_latency_bucket{{le=\"100\"}} {d}\nshisa_render_latency_bucket{{le=\"500\"}} {d}\nshisa_render_latency_bucket{{le=\"1000\"}} {d}\nshisa_render_latency_bucket{{le=\"5000\"}} {d}\nshisa_render_latency_bucket{{le=\"+Inf\"}} {d}\n# HELP shisa_prompt_cache_entries L1 rendered-prompt cache entries.\n# TYPE shisa_prompt_cache_entries gauge\nshisa_prompt_cache_entries {d}\n# HELP shisa_prompt_cache_hits L1 rendered-prompt cache hits.\n# TYPE shisa_prompt_cache_hits counter\nshisa_prompt_cache_hits {d}\n# HELP shisa_prompt_cache_misses L1 rendered-prompt cache misses.\n# TYPE shisa_prompt_cache_misses counter\nshisa_prompt_cache_misses {d}\n# HELP shisa_prompt_cache_hit_rate_ppm L1 rendered-prompt cache hit rate in parts per million.\n# TYPE shisa_prompt_cache_hit_rate_ppm gauge\nshisa_prompt_cache_hit_rate_ppm {d}\n# HELP shisa_plugins Loaded plugins.\n# TYPE shisa_plugins gauge\nshisa_plugins {d}\n# HELP shisa_cache_valid Cache validity by module.\n# TYPE shisa_cache_valid gauge\nshisa_cache_valid{{module=\"git_branch\"}} {d}\nshisa_cache_valid{{module=\"language_versions\"}} {d}\nshisa_cache_valid{{module=\"cloud_ctx_gcp\"}} {d}\nshisa_cache_valid{{module=\"cloud_ctx_azure\"}} {d}\nshisa_cache_valid{{module=\"cloud_ctx_kube\"}} {d}\n# HELP shisa_cache_in_flight Cache worker in-flight by module.\n# TYPE shisa_cache_in_flight gauge\nshisa_cache_in_flight{{module=\"git_branch\"}} {d}\nshisa_cache_in_flight{{module=\"language_versions\"}} {d}\n# HELP shisa_cache_generation Cache generation by module.\n# TYPE shisa_cache_generation counter\nshisa_cache_generation{{module=\"git_branch\"}} {d}\nshisa_cache_generation{{module=\"language_versions\"}} {d}\n",
            .{ self.connections, self.render_count, self.render_total_us, self.render_max_us, self.render_histogram[0], self.render_histogram[1], self.render_histogram[2], self.render_histogram[3], self.render_histogram[4], self.prompt_cache.count(), self.prompt_cache_hits, self.prompt_cache_misses, promptCacheHitRatePpm(self.prompt_cache_hits, self.prompt_cache_misses), self.reload_state.plugin_names.len, @intFromBool(git_valid), @intFromBool(language_valid), @intFromBool(gcp_valid), @intFromBool(azure_valid), @intFromBool(kube_valid), @intFromBool(git_in_flight), @intFromBool(language_in_flight), git_generation, language_generation },
        );
    }

    fn reloadResponseAlloc(self: *Server, allocator: std.mem.Allocator, request: []const u8) ![]u8 {
        const request_id = try requestIdAlloc(allocator, request);
        defer allocator.free(request_id);
        const escaped_request_id = try json.escapeAlloc(allocator, request_id);
        defer allocator.free(escaped_request_id);

        self.reloadConfigAndPlugins(std.heap.page_allocator) catch |err| {
            const escaped_detail = try json.escapeAlloc(allocator, @errorName(err));
            defer allocator.free(escaped_detail);
            return std.fmt.allocPrint(
                allocator,
                "{{\"v\":1,\"request_id\":\"{s}\",\"error\":{{\"code\":\"E_INTERNAL\",\"message\":\"reload failed\",\"context\":{{\"op\":\"reload\",\"detail\":\"{s}\"}}}}}}",
                .{ escaped_request_id, escaped_detail },
            );
        };

        return std.fmt.allocPrint(
            allocator,
            "{{\"v\":1,\"request_id\":\"{s}\",\"reloaded\":true,\"config_generation\":{d},\"plugin_generation\":{d},\"plugins\":{d}}}",
            .{ escaped_request_id, self.reload_state.config_generation, self.reload_state.plugin_generation, self.reload_state.plugin_names.len },
        );
    }

    fn handleSubscribeConnection(self: *Server, fd: std.posix.fd_t, request: []const u8, shutdown_requested: ?*const std.atomic.Value(bool)) !void {
        _ = self;
        var parsed = try std.json.parseFromSlice(SubscribeRequest, std.heap.page_allocator, request, .{ .ignore_unknown_fields = true });
        defer parsed.deinit();

        const topic_refs = try topicRefsAlloc(std.heap.page_allocator, parsed.value.topics);
        defer freeTopicRefs(std.heap.page_allocator, topic_refs);
        const snapshot = try subscribeSnapshotAlloc(std.heap.page_allocator, parsed.value.request_id, topic_refs);
        defer std.heap.page_allocator.free(snapshot);
        try writeAll(fd, snapshot);

        var queue = SubscriptionQueue.init(std.heap.page_allocator, subscribeBackpressureLimit(parsed.value.backpressure_limit));
        defer queue.deinit();
        var sequence: u64 = 0;
        while (true) {
            const maybe_line = line: {
                if (shutdown_requested) |flag| {
                    break :line readNdjsonLineUntilShutdownAlloc(std.heap.page_allocator, fd, 64 * 1024, flag) catch |err| switch (err) {
                        error.ConnectionClosed => return,
                        else => return err,
                    };
                }
                break :line @as(?[]u8, readNdjsonLineAlloc(std.heap.page_allocator, fd, 64 * 1024) catch |err| switch (err) {
                    error.ConnectionClosed => return,
                    else => return err,
                });
            };
            const line = maybe_line orelse return;
            errdefer std.heap.page_allocator.free(line);
            defer std.heap.page_allocator.free(line);
            if (std.mem.trim(u8, line, " \t\r\n").len == 0) continue;
            if (!subscribeCommandAllowed(line)) {
                const readonly = try subscribeReadonlyErrorAlloc(std.heap.page_allocator, parsed.value.request_id, line);
                defer std.heap.page_allocator.free(readonly);
                try writeAll(fd, readonly);
                continue;
            }
            sequence += 1;
            const delta_topic = if (topic_refs.len == 0) "subscription" else topic_refs[0].topic;
            const delta = try subscribeDeltaAlloc(std.heap.page_allocator, parsed.value.request_id, delta_topic, sequence);
            _ = try queue.pushOwned(delta);
            const heartbeat = try subscribeHeartbeatAlloc(std.heap.page_allocator, parsed.value.request_id);
            _ = try queue.pushOwned(heartbeat);
            try queue.flush(fd);
        }
    }

    fn reloadConfigAndPlugins(self: *Server, allocator: std.mem.Allocator) !void {
        const config_source = try self.loadConfigSourceAlloc(allocator);
        errdefer allocator.free(config_source);
        const plugin_names = try self.loadPluginNamesAlloc(allocator);
        errdefer freeStringList(allocator, plugin_names);

        allocator.free(self.reload_state.config_source);
        freeStringList(allocator, self.reload_state.plugin_names);
        self.reload_state.config_source = config_source;
        self.reload_state.plugin_names = plugin_names;
        self.reload_state.config_generation += 1;
        self.reload_state.plugin_generation += 1;
    }

    fn loadConfigSourceAlloc(self: *Server, allocator: std.mem.Allocator) ![]u8 {
        const path = if (self.config_path_override) |override| try allocator.dupe(u8, override) else try defaultConfigPathAlloc(allocator);
        defer allocator.free(path);
        return readConfigOrDefaultAlloc(allocator, path);
    }

    fn loadPluginNamesAlloc(self: *Server, allocator: std.mem.Allocator) ![][]u8 {
        const plugins_dir = if (self.plugins_dir_override) |override| try allocator.dupe(u8, override) else try defaultPluginsDirPathAlloc(allocator);
        defer allocator.free(plugins_dir);
        const disabled_path = try pluginStatePathForPluginsDirAlloc(allocator, plugins_dir, "plugins.disabled");
        defer allocator.free(disabled_path);
        const strikes_path = try pluginStatePathForPluginsDirAlloc(allocator, plugins_dir, "plugins.slow-strikes");
        defer allocator.free(strikes_path);

        var dir = std.fs.openDirAbsolute(plugins_dir, .{ .iterate = true }) catch |err| switch (err) {
            error.FileNotFound => return allocator.alloc([]u8, 0),
            else => return err,
        };
        defer dir.close();

        var names: std.ArrayList([]u8) = .empty;
        errdefer deinitStringArrayList(allocator, &names);
        var it = dir.iterate();
        while (try it.next()) |entry| {
            if (entry.kind != .directory) continue;
            if (!plugin_manifest.isValidPluginName(entry.name)) continue;
            if (try pluginNameListed(allocator, disabled_path, entry.name)) continue;
            const plugin_dir = try std.fmt.allocPrint(allocator, "{s}/{s}", .{ plugins_dir, entry.name });
            defer allocator.free(plugin_dir);
            const manifest_path = try std.fmt.allocPrint(allocator, "{s}/plugin.lua", .{plugin_dir});
            defer allocator.free(manifest_path);
            const source = std.fs.cwd().readFileAlloc(allocator, manifest_path, max_config_bytes) catch |err| switch (err) {
                error.FileNotFound => continue,
                else => return err,
            };
            defer allocator.free(source);

            var runtime = try plugin_lua.Runtime.initSandboxedWithOptions(allocator, .{ .require_root = plugin_dir });
            defer runtime.deinit();
            var loaded = runtime.loadManifestStrict(source) catch |err| switch (err) {
                error.LuaCpuBudgetExceeded => {
                    try recordPluginSlowStrike(allocator, strikes_path, disabled_path, entry.name);
                    continue;
                },
                else => return err,
            };
            defer loaded.deinit(allocator);
            try clearPluginSlowStrike(allocator, strikes_path, loaded.manifest.name);
            if (try pluginNameListed(allocator, disabled_path, loaded.manifest.name)) continue;
            try names.append(allocator, try allocator.dupe(u8, loaded.manifest.name));
        }

        return names.toOwnedSlice(allocator);
    }

    fn checkPluginHostApiCall(capabilities: plugin_manifest.Capabilities, context: plugin_capability.Context, call: plugin_capability.HostApiCall) plugin_capability.Error!void {
        try plugin_capability.Gate.init(capabilities, context).checkCall(call);
    }

    pub fn recordFsEvent(self: *Server, path: []const u8, timestamp_ns: u64) void {
        self.fs_watcher.recordEvent(path, timestamp_ns);
    }

    fn drainFsInvalidations(self: *Server, timestamp_ns: u64) void {
        while (self.fs_watcher.nextInvalidation(timestamp_ns)) |invalidation| {
            self.cache_rev +%= 1;
            if (std.mem.eql(u8, invalidation.module_id, git_branch_module.module_id)) {
                self.git_branch_cache.invalidate(std.heap.page_allocator, invalidation.cwd);
            } else if (std.mem.eql(u8, invalidation.module_id, cloud_ctx_module.module_id)) {
                self.cloud_ctx_cache.invalidateGcp(std.heap.page_allocator);
                self.cloud_ctx_cache.invalidateAzure(std.heap.page_allocator);
                self.cloud_ctx_cache.invalidateKube(std.heap.page_allocator);
            }
        }
    }

    fn registerGitInvalidation(self: *Server, cwd_path: []const u8) !void {
        if (self.fs_watcher.hasScope(git_branch_module.module_id, cwd_path)) return;
        var watched = (try git_branch_module.watchScope(std.heap.page_allocator, cwd_path)) orelse return;
        defer watched.deinit(std.heap.page_allocator);
        const git_scope = watched.scope();
        var paths: [3]fsnotify.WatchPath = undefined;
        for (git_scope.paths, 0..) |path, index| {
            paths[index] = .{ .path = path.path, .recursive = path.recursive };
        }
        try self.fs_watcher.watch(.{
            .module_id = git_scope.module_id,
            .cwd = git_scope.cwd,
            .paths = paths[0..],
            .debounce_ms = git_scope.debounce_ms,
        });
        try self.logInotifyLimitWarning();
    }

    fn registerCloudInvalidation(self: *Server, home: ?[]const u8, kubeconfig: ?[]const u8) !void {
        if (home) |home_path| {
            var gcp_scope = try cloud_ctx_module.gcpWatchScope(std.heap.page_allocator, home_path);
            defer gcp_scope.deinit(std.heap.page_allocator);
            try self.registerCloudScope(gcp_scope.scope());

            var azure_scope = try cloud_ctx_module.azureWatchScope(std.heap.page_allocator, home_path);
            defer azure_scope.deinit(std.heap.page_allocator);
            try self.registerCloudScope(azure_scope.scope());
        }

        var kube_scope = (try cloud_ctx_module.kubeWatchScope(std.heap.page_allocator, kubeconfig, home)) orelse return;
        defer kube_scope.deinit(std.heap.page_allocator);
        try self.registerCloudScope(kube_scope.scope());
    }

    fn registerCloudScope(self: *Server, cloud_scope: cloud_ctx_module.Scope) !void {
        if (self.fs_watcher.hasScope(cloud_scope.module_id, cloud_scope.cwd)) return;
        var paths: [1]fsnotify.WatchPath = undefined;
        for (cloud_scope.paths, 0..) |path, index| {
            paths[index] = .{ .path = path.path, .recursive = path.recursive };
        }
        try self.fs_watcher.watch(.{
            .module_id = cloud_scope.module_id,
            .cwd = cloud_scope.cwd,
            .paths = paths[0..],
            .debounce_ms = cloud_scope.debounce_ms,
        });
        try self.logInotifyLimitWarning();
    }

    fn logInotifyLimitWarning(self: *Server) !void {
        const logger = self.logger orelse return;
        const max_user_watches = fsnotify.readLinuxMaxUserWatches(std.heap.page_allocator) catch return;
        const status = self.fs_watcher.inotifyLimitStatus(max_user_watches);
        if (status.within_limit == false) {
            const message = try std.fmt.allocPrint(
                std.heap.page_allocator,
                "watched_paths={d} max_user_watches={d}",
                .{ status.watched_paths, status.max_user_watches.? },
            );
            defer std.heap.page_allocator.free(message);
            try logger.warn("inotify_limit_exceeded", message);
        } else if (status.remaining) |remaining| {
            if (remaining < 128) {
                const message = try std.fmt.allocPrint(
                    std.heap.page_allocator,
                    "watched_paths={d} max_user_watches={d} remaining={d}",
                    .{ status.watched_paths, status.max_user_watches.?, remaining },
                );
                defer std.heap.page_allocator.free(message);
                try logger.warn("inotify_limit_low", message);
            }
        }
    }
};

fn writeFrame(fd: std.posix.fd_t, payload: []const u8) !void {
    const encoded = try encodeFrameAlloc(std.heap.page_allocator, payload);
    defer std.heap.page_allocator.free(encoded);
    try writeAll(fd, encoded);
}

fn encodeFrameAlloc(allocator: std.mem.Allocator, payload: []const u8) ![]u8 {
    if (payload.len > max_frame_bytes) return error.Oversize;
    const encoded = try allocator.alloc(u8, header_bytes + payload.len);
    std.mem.writeInt(u32, encoded[0..header_bytes], @as(u32, @intCast(payload.len)), .big);
    @memcpy(encoded[header_bytes..], payload);
    return encoded;
}

fn readFrameAlloc(allocator: std.mem.Allocator, fd: std.posix.fd_t) ![]u8 {
    var header: [header_bytes]u8 = undefined;
    try readExact(fd, &header);
    const payload_len = std.mem.readInt(u32, &header, .big);
    if (payload_len > max_frame_bytes) return error.Oversize;
    const payload = try allocator.alloc(u8, payload_len);
    errdefer allocator.free(payload);
    try readExact(fd, payload);
    return payload;
}

fn readNdjsonLineAlloc(allocator: std.mem.Allocator, fd: std.posix.fd_t, max_line_bytes: usize) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    errdefer out.deinit(allocator);
    while (out.items.len < max_line_bytes) {
        var byte: [1]u8 = undefined;
        const n = try std.posix.read(fd, &byte);
        if (n == 0) {
            if (out.items.len == 0) return error.ConnectionClosed;
            break;
        }
        try out.append(allocator, byte[0]);
        if (byte[0] == '\n') break;
    } else {
        return error.Oversize;
    }
    return out.toOwnedSlice(allocator);
}

fn readNdjsonLineUntilShutdownAlloc(allocator: std.mem.Allocator, fd: std.posix.fd_t, max_line_bytes: usize, shutdown_requested: *const std.atomic.Value(bool)) !?[]u8 {
    var out: std.ArrayList(u8) = .empty;
    errdefer out.deinit(allocator);
    while (out.items.len < max_line_bytes) {
        if (shutdown_requested.load(.seq_cst)) {
            if (out.items.len == 0) return null;
            break;
        }
        var poll_fds = [_]std.posix.pollfd{.{
            .fd = fd,
            .events = std.posix.POLL.IN,
            .revents = 0,
        }};
        const ready = try std.posix.poll(&poll_fds, shutdown_poll_ms);
        if (ready == 0) continue;
        if ((poll_fds[0].revents & std.posix.POLL.IN) == 0) {
            if ((poll_fds[0].revents & (std.posix.POLL.HUP | std.posix.POLL.ERR | std.posix.POLL.NVAL)) != 0) {
                if (out.items.len == 0) return error.ConnectionClosed;
                break;
            }
            continue;
        }
        var byte: [1]u8 = undefined;
        const n = try std.posix.read(fd, &byte);
        if (n == 0) {
            if (out.items.len == 0) return error.ConnectionClosed;
            break;
        }
        try out.append(allocator, byte[0]);
        if (byte[0] == '\n') break;
    } else {
        return error.Oversize;
    }
    return try out.toOwnedSlice(allocator);
}

fn readExact(fd: std.posix.fd_t, buffer: []u8) !void {
    var offset: usize = 0;
    while (offset < buffer.len) {
        const n = try std.posix.read(fd, buffer[offset..]);
        if (n == 0) return error.ConnectionClosed;
        offset += n;
    }
}

fn writeAll(fd: std.posix.fd_t, bytes: []const u8) !void {
    var remaining = bytes;
    while (remaining.len > 0) {
        const written = try std.posix.write(fd, remaining);
        remaining = remaining[written..];
    }
}

fn nowNs() u64 {
    return @intCast(std.time.nanoTimestamp());
}

fn renderHistogramIndex(elapsed_us: u64) usize {
    if (elapsed_us <= 100) return 0;
    if (elapsed_us <= 500) return 1;
    if (elapsed_us <= 1000) return 2;
    if (elapsed_us <= 5000) return 3;
    return 4;
}

fn promptCacheHitRatePpm(hits: u64, misses: u64) u64 {
    const total = @as(u128, hits) + @as(u128, misses);
    if (total == 0) return 0;
    return @intCast((@as(u128, hits) * 1_000_000) / total);
}

fn renderPipelineFromModuleNamesAlloc(allocator: std.mem.Allocator, modules: []const []const u8) !?[]dispatcher.ModuleSpec {
    if (modules.len == 0) return null;
    const pipeline = try allocator.alloc(dispatcher.ModuleSpec, modules.len);
    errdefer allocator.free(pipeline);
    for (modules, 0..) |module_name, index| {
        const module_id = dispatcher.moduleIdFromName(module_name) orelse return error.UnknownModule;
        pipeline[index] = .{
            .id = module_id,
            .execution_class = dispatcher.executionClass(module_id),
        };
    }
    return pipeline;
}

fn renderPromptCacheKeyAlloc(allocator: std.mem.Allocator, request: RenderRequest, context: RenderCacheContext) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    errdefer out.deinit(allocator);

    try appendKeyInt(allocator, &out, "v", request.v);
    try appendKeyString(allocator, &out, "cwd", request.cwd);
    try appendKeyInt(allocator, &out, "exit", request.exit);
    try appendKeyInt(allocator, &out, "jobs", request.jobs);
    try appendKeyInt(allocator, &out, "duration_ms", request.duration_ms);
    try appendKeyBool(allocator, &out, "time", request.time);
    try appendKeyInt(allocator, &out, "time_min", context.timestamp_minute);
    try appendKeyBool(allocator, &out, "no_async", request.no_async);
    try appendKeyString(allocator, &out, "shell", request.shell);
    try appendKeyInt(allocator, &out, "cols", request.cols);
    try appendKeyInt(allocator, &out, "rows", request.rows);
    try appendKeyOptional(allocator, &out, "tmux_pane", request.tmux_pane);
    try appendKeyInt(allocator, &out, "modules_len", request.modules.len);
    for (request.modules, 0..) |module_name, index| {
        const key = try std.fmt.allocPrint(allocator, "module_{d}", .{index});
        defer allocator.free(key);
        try appendKeyString(allocator, &out, key, module_name);
    }
    try appendKeyBool(allocator, &out, "cloud_aws", request.cloud_ctx.aws);
    try appendKeyBool(allocator, &out, "cloud_gcp", request.cloud_ctx.gcp);
    try appendKeyBool(allocator, &out, "cloud_azure", request.cloud_ctx.azure);
    try appendKeyBool(allocator, &out, "cloud_kube", request.cloud_ctx.kubernetes);
    try appendKeyInt(allocator, &out, "cwd_truncate_to", request.cwd_options.truncate_to);
    try appendKeyBool(allocator, &out, "cwd_home_tilde", request.cwd_options.home_tilde);
    try appendKeyInt(allocator, &out, "cwd_max_width", request.cwd_options.max_width);
    try appendKeyBool(allocator, &out, "cdhint_enabled", request.cdhint.enabled);
    try appendKeyBool(allocator, &out, "tmux_pane_enabled", request.tmux_pane_options.enabled);
    try appendKeyString(allocator, &out, "risk_unknown_bg", risk_tier_module.colorSlotName(request.risk_tier.unknown_bg));
    try appendKeyString(allocator, &out, "risk_dev_bg", risk_tier_module.colorSlotName(request.risk_tier.dev_bg));
    try appendKeyString(allocator, &out, "risk_staging_bg", risk_tier_module.colorSlotName(request.risk_tier.staging_bg));
    try appendKeyString(allocator, &out, "risk_prod_bg", risk_tier_module.colorSlotName(request.risk_tier.prod_bg));
    try appendKeyInt(allocator, &out, "sso_warning", request.sso_expiry.warning_minutes);
    try appendKeyBool(allocator, &out, "rtl", request.rtl);
    try appendKeyBool(allocator, &out, "rtl_reverse", request.rtl_reverse);
    try appendKeyOptional(allocator, &out, "home", context.home);
    try appendKeyOptional(allocator, &out, "kubeconfig", context.kubeconfig);
    try appendKeyOptional(allocator, &out, "ssh", context.ssh);
    try appendKeyString(allocator, &out, "user", context.user);
    try appendKeyString(allocator, &out, "host", context.host);
    try appendKeyOptional(allocator, &out, "aws_profile", context.aws_profile);
    try appendKeyOptional(allocator, &out, "aws_region", context.aws_region);
    try appendKeyOptional(allocator, &out, "aws_default_region", context.aws_default_region);
    try appendKeyOptional(allocator, &out, "cloudsdk_compute_region", context.cloudsdk_compute_region);
    try appendKeyOptional(allocator, &out, "azure_location", context.azure_location);
    try appendKeyOptional(allocator, &out, "arm_location", context.arm_location);
    try appendKeyOptional(allocator, &out, "azure_default_location", context.azure_default_location);
    try appendKeyInt(allocator, &out, "config_generation", context.config_generation);
    try appendKeyInt(allocator, &out, "plugin_generation", context.plugin_generation);
    try appendKeyInt(allocator, &out, "cache_rev", context.cache_rev);
    try appendKeyBool(allocator, &out, "git_valid", context.snapshot.git_valid);
    try appendKeyBool(allocator, &out, "git_in_flight", context.snapshot.git_in_flight);
    try appendKeyInt(allocator, &out, "git_generation", context.snapshot.git_generation);
    try appendKeyOptional(allocator, &out, "git_cwd", context.snapshot.git_cwd);
    try appendKeyBool(allocator, &out, "language_valid", context.snapshot.language_valid);
    try appendKeyBool(allocator, &out, "language_in_flight", context.snapshot.language_in_flight);
    try appendKeyInt(allocator, &out, "language_generation", context.snapshot.language_generation);
    try appendKeyOptional(allocator, &out, "language_cwd", context.snapshot.language_cwd);
    try appendKeyBool(allocator, &out, "gcp_valid", context.snapshot.gcp_valid);
    try appendKeyBool(allocator, &out, "azure_valid", context.snapshot.azure_valid);
    try appendKeyBool(allocator, &out, "kube_valid", context.snapshot.kube_valid);

    return out.toOwnedSlice(allocator);
}

fn appendKeyString(allocator: std.mem.Allocator, out: *std.ArrayList(u8), name: []const u8, value: []const u8) !void {
    try out.appendSlice(allocator, name);
    try out.append(allocator, '=');
    try std.fmt.format(out.writer(allocator), "{d}:", .{value.len});
    try out.appendSlice(allocator, value);
    try out.append(allocator, '|');
}

fn appendKeyOptional(allocator: std.mem.Allocator, out: *std.ArrayList(u8), name: []const u8, value: ?[]const u8) !void {
    if (value) |present| {
        try appendKeyString(allocator, out, name, present);
        return;
    }
    try out.appendSlice(allocator, name);
    try out.appendSlice(allocator, "=-|");
}

fn appendKeyBool(allocator: std.mem.Allocator, out: *std.ArrayList(u8), name: []const u8, value: bool) !void {
    try out.appendSlice(allocator, name);
    try out.append(allocator, '=');
    try out.append(allocator, if (value) '1' else '0');
    try out.append(allocator, '|');
}

fn appendKeyInt(allocator: std.mem.Allocator, out: *std.ArrayList(u8), name: []const u8, value: anytype) !void {
    try out.appendSlice(allocator, name);
    try out.append(allocator, '=');
    try std.fmt.format(out.writer(allocator), "{d}", .{value});
    try out.append(allocator, '|');
}

fn stackDumpMessageAlloc(allocator: std.mem.Allocator) ![]u8 {
    var addresses: [32]usize = undefined;
    var stack_trace = std.builtin.StackTrace{
        .index = 0,
        .instruction_addresses = addresses[0..],
    };
    std.debug.captureStackTrace(@returnAddress(), &stack_trace);

    var out: std.ArrayList(u8) = .empty;
    errdefer out.deinit(allocator);
    try out.appendSlice(allocator, "frames=");
    const count = @min(stack_trace.index, stack_trace.instruction_addresses.len);
    for (stack_trace.instruction_addresses[0..count], 0..) |address, index| {
        if (index != 0) try out.append(allocator, ',');
        const frame = try std.fmt.allocPrint(allocator, "0x{x}", .{address});
        defer allocator.free(frame);
        try out.appendSlice(allocator, frame);
    }
    return out.toOwnedSlice(allocator);
}

fn isPreexecRequest(request: []const u8) bool {
    return std.mem.indexOf(u8, request, "\"kind\":\"preexec\"") != null or
        std.mem.indexOf(u8, request, "\"kind\": \"preexec\"") != null;
}

const OpRequest = struct {
    op: []const u8 = "",
    request_id: []const u8 = "",
};

fn isOpRequest(request: []const u8, op: []const u8) bool {
    var parsed = std.json.parseFromSlice(OpRequest, std.heap.page_allocator, request, .{ .ignore_unknown_fields = true }) catch return false;
    defer parsed.deinit();
    return std.mem.eql(u8, parsed.value.op, op);
}

fn healthResponseAlloc(allocator: std.mem.Allocator, request: []const u8, ok: bool) ![]u8 {
    const request_id = try requestIdAlloc(allocator, request);
    defer allocator.free(request_id);
    const escaped_request_id = try json.escapeAlloc(allocator, request_id);
    defer allocator.free(escaped_request_id);
    return std.fmt.allocPrint(allocator, "{{\"v\":1,\"request_id\":\"{s}\",\"ok\":{}}}", .{ escaped_request_id, ok });
}

fn versionResponseAlloc(allocator: std.mem.Allocator, request: []const u8) ![]u8 {
    const request_id = try requestIdAlloc(allocator, request);
    defer allocator.free(request_id);
    const escaped_request_id = try json.escapeAlloc(allocator, request_id);
    defer allocator.free(escaped_request_id);
    return std.fmt.allocPrint(allocator, "{{\"v\":1,\"request_id\":\"{s}\",\"daemon\":\"{s}\",\"protocol\":{d}}}", .{ escaped_request_id, daemon_version, protocol_version });
}

fn topicRefsAlloc(allocator: std.mem.Allocator, topics: []const []const u8) ![]TopicRef {
    var refs: std.ArrayList(TopicRef) = .empty;
    errdefer {
        for (refs.items) |*ref| allocator.free(ref.topic);
        refs.deinit(allocator);
    }

    for (topics) |topic| {
        var found = false;
        for (refs.items) |*ref| {
            if (std.mem.eql(u8, ref.topic, topic)) {
                ref.count += 1;
                found = true;
                break;
            }
        }
        if (!found) {
            try refs.append(allocator, .{
                .topic = try allocator.dupe(u8, topic),
                .count = 1,
            });
        }
    }

    return refs.toOwnedSlice(allocator);
}

fn subscribeBackpressureLimit(value: u16) usize {
    if (value == 0) return default_subscribe_backpressure_limit;
    return @min(@as(usize, value), max_subscribe_backpressure_limit);
}

fn subscribeCommandAllowed(line: []const u8) bool {
    var parsed = std.json.parseFromSlice(SubscribeCommand, std.heap.page_allocator, line, .{ .ignore_unknown_fields = true }) catch return false;
    defer parsed.deinit();
    return isSubscribeReadOnlyOp(parsed.value.op);
}

fn isSubscribeReadOnlyOp(op: []const u8) bool {
    return std.mem.eql(u8, op, "ping") or
        std.mem.eql(u8, op, "subscribe") or
        std.mem.eql(u8, op, "unsubscribe") or
        std.mem.eql(u8, op, "health") or
        std.mem.eql(u8, op, "metrics") or
        std.mem.eql(u8, op, "version");
}

fn subscribeCommandName(command: SubscribeCommand) []const u8 {
    if (command.op.len != 0) return command.op;
    if (command.kind.len != 0) return command.kind;
    return "unknown";
}

fn freeTopicRefs(allocator: std.mem.Allocator, refs: []TopicRef) void {
    for (refs) |ref| allocator.free(ref.topic);
    allocator.free(refs);
}

fn topicRefsJsonAlloc(allocator: std.mem.Allocator, refs: []const TopicRef) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    errdefer out.deinit(allocator);
    try out.append(allocator, '{');
    for (refs, 0..) |ref, index| {
        if (index != 0) try out.append(allocator, ',');
        const escaped_topic = try json.escapeAlloc(allocator, ref.topic);
        defer allocator.free(escaped_topic);
        try std.fmt.format(out.writer(allocator), "\"{s}\":{d}", .{ escaped_topic, ref.count });
    }
    try out.append(allocator, '}');
    return out.toOwnedSlice(allocator);
}

fn subscribeSnapshotAlloc(allocator: std.mem.Allocator, request_id: []const u8, refs: []const TopicRef) ![]u8 {
    const escaped_request_id = try json.escapeAlloc(allocator, request_id);
    defer allocator.free(escaped_request_id);
    const refs_json = try topicRefsJsonAlloc(allocator, refs);
    defer allocator.free(refs_json);
    return std.fmt.allocPrint(
        allocator,
        "{{\"v\":1,\"request_id\":\"{s}\",\"topic\":\"subscription\",\"kind\":\"snapshot\",\"data\":{{\"topics\":{d},\"refs\":{s}}}}}\n",
        .{ escaped_request_id, refs.len, refs_json },
    );
}

fn subscribeHeartbeatAlloc(allocator: std.mem.Allocator, request_id: []const u8) ![]u8 {
    const escaped_request_id = try json.escapeAlloc(allocator, request_id);
    defer allocator.free(escaped_request_id);
    return std.fmt.allocPrint(
        allocator,
        "{{\"v\":1,\"request_id\":\"{s}\",\"topic\":\"subscription\",\"kind\":\"heartbeat\",\"data\":{{}}}}\n",
        .{escaped_request_id},
    );
}

fn subscribeDeltaAlloc(allocator: std.mem.Allocator, request_id: []const u8, topic: []const u8, sequence: u64) ![]u8 {
    const escaped_request_id = try json.escapeAlloc(allocator, request_id);
    defer allocator.free(escaped_request_id);
    const escaped_topic = try json.escapeAlloc(allocator, topic);
    defer allocator.free(escaped_topic);
    return std.fmt.allocPrint(
        allocator,
        "{{\"v\":1,\"request_id\":\"{s}\",\"topic\":\"{s}\",\"kind\":\"delta\",\"data\":{{\"sequence\":{d}}}}}\n",
        .{ escaped_request_id, escaped_topic, sequence },
    );
}

fn subscribeReadonlyErrorAlloc(allocator: std.mem.Allocator, request_id: []const u8, line: []const u8) ![]u8 {
    const escaped_request_id = try json.escapeAlloc(allocator, request_id);
    defer allocator.free(escaped_request_id);
    var parsed = std.json.parseFromSlice(SubscribeCommand, allocator, line, .{ .ignore_unknown_fields = true }) catch null;
    defer if (parsed) |*value| value.deinit();
    const op = if (parsed) |value| subscribeCommandName(value.value) else "unknown";
    const escaped_op = try json.escapeAlloc(allocator, op);
    defer allocator.free(escaped_op);
    return std.fmt.allocPrint(
        allocator,
        "{{\"v\":1,\"request_id\":\"{s}\",\"topic\":\"subscription\",\"kind\":\"error\",\"data\":{{\"error\":{{\"code\":\"E_READONLY\",\"message\":\"subscribe connection is read-only\",\"context\":{{\"op\":\"{s}\"}}}}}}}}\n",
        .{ escaped_request_id, escaped_op },
    );
}

fn defaultConfigPathAlloc(allocator: std.mem.Allocator) ![]u8 {
    const xdg = std.process.getEnvVarOwned(allocator, "XDG_CONFIG_HOME") catch |err| switch (err) {
        error.EnvironmentVariableNotFound => null,
        else => return err,
    };
    if (xdg) |xdg_config_home| {
        defer allocator.free(xdg_config_home);
        return std.fmt.allocPrint(allocator, "{s}/shisa/shisa.toml", .{xdg_config_home});
    }

    const home = std.process.getEnvVarOwned(allocator, "HOME") catch |err| switch (err) {
        error.EnvironmentVariableNotFound => return error.MissingHome,
        else => return err,
    };
    defer allocator.free(home);
    return std.fmt.allocPrint(allocator, "{s}/.config/shisa/shisa.toml", .{home});
}

fn defaultPluginsDirPathAlloc(allocator: std.mem.Allocator) ![]u8 {
    const config_path = try defaultConfigPathAlloc(allocator);
    defer allocator.free(config_path);
    const dir = std.fs.path.dirname(config_path) orelse return error.MissingConfigDir;
    return std.fmt.allocPrint(allocator, "{s}/plugins", .{dir});
}

fn pluginStatePathForPluginsDirAlloc(allocator: std.mem.Allocator, plugins_dir: []const u8, basename: []const u8) ![]u8 {
    const dir = std.fs.path.dirname(plugins_dir) orelse return error.MissingConfigDir;
    return std.fmt.allocPrint(allocator, "{s}/{s}", .{ dir, basename });
}

fn recordPluginSlowStrike(allocator: std.mem.Allocator, strikes_path: []const u8, disabled_path: []const u8, name: []const u8) !void {
    const count = try incrementPluginSlowStrike(allocator, strikes_path, name);
    if (count >= plugin_slow_strike_limit) try setPluginNameListed(allocator, disabled_path, name, true);
}

fn clearPluginSlowStrike(allocator: std.mem.Allocator, strikes_path: []const u8, name: []const u8) !void {
    try setPluginSlowStrikeCount(allocator, strikes_path, name, 0);
}

fn incrementPluginSlowStrike(allocator: std.mem.Allocator, strikes_path: []const u8, name: []const u8) !u8 {
    var strikes = try readPluginSlowStrikes(allocator, strikes_path);
    defer deinitPluginSlowStrikes(allocator, &strikes);
    const index = indexOfPluginSlowStrike(strikes.items, name);
    const count = if (index) |i| @min(strikes.items[i].count +| 1, plugin_slow_strike_limit) else 1;
    try setPluginSlowStrikeCountLoaded(allocator, strikes_path, &strikes, name, count);
    return count;
}

fn setPluginSlowStrikeCount(allocator: std.mem.Allocator, strikes_path: []const u8, name: []const u8, count: u8) !void {
    var strikes = try readPluginSlowStrikes(allocator, strikes_path);
    defer deinitPluginSlowStrikes(allocator, &strikes);
    try setPluginSlowStrikeCountLoaded(allocator, strikes_path, &strikes, name, count);
}

fn setPluginSlowStrikeCountLoaded(allocator: std.mem.Allocator, strikes_path: []const u8, strikes: *std.ArrayList(PluginSlowStrike), name: []const u8, count: u8) !void {
    if (!plugin_manifest.isValidPluginName(name)) return error.InvalidPluginName;
    if (indexOfPluginSlowStrike(strikes.items, name)) |index| {
        if (count == 0) {
            const removed = strikes.orderedRemove(index);
            allocator.free(removed.name);
        } else {
            strikes.items[index].count = count;
        }
    } else if (count != 0) {
        try strikes.append(allocator, .{ .name = try allocator.dupe(u8, name), .count = count });
    }
    std.mem.sort(PluginSlowStrike, strikes.items, {}, lessThanPluginSlowStrike);
    try writePluginSlowStrikes(allocator, strikes_path, strikes.items);
}

const PluginSlowStrike = struct {
    name: []u8,
    count: u8,
};

fn readPluginSlowStrikes(allocator: std.mem.Allocator, path: []const u8) !std.ArrayList(PluginSlowStrike) {
    var strikes: std.ArrayList(PluginSlowStrike) = .empty;
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
        if (fields.next() != null or !plugin_manifest.isValidPluginName(name)) continue;
        const count = std.fmt.parseInt(u8, count_text, 10) catch continue;
        if (count == 0 or indexOfPluginSlowStrike(strikes.items, name) != null) continue;
        try strikes.append(allocator, .{ .name = try allocator.dupe(u8, name), .count = @min(count, plugin_slow_strike_limit) });
    }
    return strikes;
}

fn writePluginSlowStrikes(allocator: std.mem.Allocator, path: []const u8, strikes: []const PluginSlowStrike) !void {
    if (std.fs.path.dirname(path)) |parent| try std.fs.cwd().makePath(parent);
    var file = try std.fs.createFileAbsolute(path, .{ .truncate = true, .mode = 0o600 });
    defer file.close();
    for (strikes) |strike| {
        const line = try std.fmt.allocPrint(allocator, "{s} {d}\n", .{ strike.name, strike.count });
        defer allocator.free(line);
        try file.writeAll(line);
    }
}

fn deinitPluginSlowStrikes(allocator: std.mem.Allocator, strikes: *std.ArrayList(PluginSlowStrike)) void {
    for (strikes.items) |strike| allocator.free(strike.name);
    strikes.deinit(allocator);
}

fn indexOfPluginSlowStrike(strikes: []const PluginSlowStrike, name: []const u8) ?usize {
    for (strikes, 0..) |strike, index| {
        if (std.mem.eql(u8, strike.name, name)) return index;
    }
    return null;
}

fn lessThanPluginSlowStrike(_: void, lhs: PluginSlowStrike, rhs: PluginSlowStrike) bool {
    return std.mem.lessThan(u8, lhs.name, rhs.name);
}

fn pluginNameListed(allocator: std.mem.Allocator, path: []const u8, name: []const u8) !bool {
    var names = try readPluginNames(allocator, path);
    defer deinitStringArrayList(allocator, &names);
    return indexOfString(names.items, name) != null;
}

fn setPluginNameListed(allocator: std.mem.Allocator, path: []const u8, name: []const u8, listed: bool) !void {
    if (!plugin_manifest.isValidPluginName(name)) return error.InvalidPluginName;
    var names = try readPluginNames(allocator, path);
    defer deinitStringArrayList(allocator, &names);

    const index = indexOfString(names.items, name);
    if (listed and index == null) {
        try names.append(allocator, try allocator.dupe(u8, name));
    } else if (!listed and index != null) {
        const removed = names.orderedRemove(index.?);
        allocator.free(removed);
    }
    std.mem.sort([]u8, names.items, {}, lessThanString);
    try writePluginNames(path, names.items);
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
        if (indexOfString(names.items, trimmed) == null) try names.append(allocator, try allocator.dupe(u8, trimmed));
    }
    return names;
}

fn writePluginNames(path: []const u8, names: []const []const u8) !void {
    if (std.fs.path.dirname(path)) |parent| try std.fs.cwd().makePath(parent);
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

fn readConfigOrDefaultAlloc(allocator: std.mem.Allocator, path: []const u8) ![]u8 {
    var file = std.fs.openFileAbsolute(path, .{}) catch |err| switch (err) {
        error.FileNotFound => return allocator.dupe(u8, default_config_text),
        else => return err,
    };
    defer file.close();
    return file.readToEndAlloc(allocator, max_config_bytes);
}

fn freeStringList(allocator: std.mem.Allocator, items: [][]u8) void {
    for (items) |item| allocator.free(item);
    allocator.free(items);
}

fn deinitStringArrayList(allocator: std.mem.Allocator, items: *std.ArrayList([]u8)) void {
    for (items.items) |item| allocator.free(item);
    items.deinit(allocator);
}

fn requestIdAlloc(allocator: std.mem.Allocator, request: []const u8) ![]u8 {
    var parsed = std.json.parseFromSlice(OpRequest, allocator, request, .{ .ignore_unknown_fields = true }) catch return allocator.dupe(u8, "");
    defer parsed.deinit();
    return allocator.dupe(u8, parsed.value.request_id);
}

fn prodGuardAuditPathAlloc(allocator: std.mem.Allocator, home: []const u8) ![]u8 {
    return std.fmt.allocPrint(allocator, "{s}/.local/state/shisa/prod_guard.jsonl", .{home});
}

fn acceptOneThread(server: *Server) !void {
    try server.acceptOne();
}

fn serveThread(server: *Server, shutdown_requested: *const std.atomic.Value(bool), reload_requested: *std.atomic.Value(bool), stack_dump_requested: *std.atomic.Value(bool)) !void {
    try server.serve(shutdown_requested, reload_requested, stack_dump_requested);
}

fn costRefreshThreadMain(server: *Server) void {
    server.costRefreshLoop();
}

test "accepts one unix socket connection" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-server-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};

    const socket_path = try std.fmt.allocPrint(allocator, "{s}/shisa.sock", .{dir_path});
    defer allocator.free(socket_path);

    var server = try Server.init(socket_path);
    defer server.deinit();

    const thread = try std.Thread.spawn(.{}, acceptOneThread, .{&server});

    var client_stream = try std.net.connectUnixSocket(socket_path);
    defer client_stream.close();
    try writeFrame(client_stream.handle, "health");
    const response = try readFrameAlloc(allocator, client_stream.handle);
    defer allocator.free(response);
    try std.testing.expectEqualStrings("ok\n", response);

    thread.join();
}

test "returns metrics response" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-server-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};

    const socket_path = try std.fmt.allocPrint(allocator, "{s}/shisa.sock", .{dir_path});
    defer allocator.free(socket_path);

    var server = try Server.init(socket_path);
    defer server.deinit();

    const thread = try std.Thread.spawn(.{}, acceptOneThread, .{&server});

    var client_stream = try std.net.connectUnixSocket(socket_path);
    defer client_stream.close();
    try writeFrame(client_stream.handle, "metrics");
    const response = try readFrameAlloc(allocator, client_stream.handle);
    defer allocator.free(response);
    try std.testing.expectEqualStrings("{\"connections\":1}\n", response);

    thread.join();
}

test "renders cwd prompt response" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-server-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};

    const socket_path = try std.fmt.allocPrint(allocator, "{s}/shisa.sock", .{dir_path});
    defer allocator.free(socket_path);

    var server = try Server.init(socket_path);
    defer server.deinit();

    const thread = try std.Thread.spawn(.{}, acceptOneThread, .{&server});

    var client_stream = try std.net.connectUnixSocket(socket_path);
    defer client_stream.close();
    try writeFrame(client_stream.handle, "{\"v\":1,\"cwd\":\"/tmp/project\",\"exit\":0,\"jobs\":0,\"duration_ms\":0,\"shell\":\"zsh\",\"cols\":80,\"rows\":24}");
    const response = try readFrameAlloc(allocator, client_stream.handle);
    defer allocator.free(response);
    try std.testing.expect(std.mem.indexOf(u8, response, "\"prompt\":\"/tmp/project> \"") != null);

    thread.join();
}

test "renders optional time segment" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-server-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};

    const socket_path = try std.fmt.allocPrint(allocator, "{s}/shisa.sock", .{dir_path});
    defer allocator.free(socket_path);

    var server = try Server.init(socket_path);
    defer server.deinit();

    const thread = try std.Thread.spawn(.{}, acceptOneThread, .{&server});

    var client_stream = try std.net.connectUnixSocket(socket_path);
    defer client_stream.close();
    try writeFrame(client_stream.handle, "{\"v\":1,\"cwd\":\"/tmp/project\",\"exit\":0,\"jobs\":0,\"duration_ms\":0,\"time\":true,\"shell\":\"zsh\",\"cols\":80,\"rows\":24}");
    const response = try readFrameAlloc(allocator, client_stream.handle);
    defer allocator.free(response);
    try std.testing.expect(std.mem.indexOf(u8, response, "\"prompt\":\"/tmp/project time:") != null);

    thread.join();
}

test "preexec response classifies command tier" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-server-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};

    const socket_path = try std.fmt.allocPrint(allocator, "{s}/shisa.sock", .{dir_path});
    defer allocator.free(socket_path);

    var server = try Server.init(socket_path);
    defer server.deinit();

    const response = try server.preexecResponse("{\"v\":1,\"kind\":\"preexec\",\"shell\":\"zsh\",\"command\":\"kubectl get pods --context api-prd-use1\"}");
    defer std.heap.page_allocator.free(response);
    try std.testing.expect(std.mem.indexOf(u8, response, "\"tier\":\"prod\"") != null);
    try std.testing.expect(std.mem.indexOf(u8, response, "\"allow\":true") != null);
    try std.testing.expect(std.mem.indexOf(u8, response, "\"destructive\":false") != null);
}

test "preexec response warns on locked iac workspace" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-server-iac-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    const lock_path = try std.fmt.allocPrint(allocator, "{s}/.terraform.tfstate.lock.info", .{dir_path});
    defer allocator.free(lock_path);
    {
        var file = try std.fs.createFileAbsolute(lock_path, .{});
        defer file.close();
        try file.writeAll("{}");
    }

    const socket_path = try std.fmt.allocPrint(allocator, "{s}/shisa.sock", .{dir_path});
    defer allocator.free(socket_path);
    var server = try Server.init(socket_path);
    defer server.deinit();

    const request = try std.fmt.allocPrint(allocator, "{{\"v\":1,\"kind\":\"preexec\",\"cwd\":\"{s}\",\"shell\":\"zsh\",\"command\":\"terraform apply\"}}", .{dir_path});
    defer allocator.free(request);
    const response = try server.preexecResponse(request);
    defer std.heap.page_allocator.free(response);
    try std.testing.expect(std.mem.indexOf(u8, response, "\"warning\":\"iac_workspace_locked:terraform apply\"") != null);
}

test "preexec response denies destructive prod command" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-server-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};

    const socket_path = try std.fmt.allocPrint(allocator, "{s}/shisa.sock", .{dir_path});
    defer allocator.free(socket_path);

    var server = try Server.init(socket_path);
    defer server.deinit();
    server.prod_guard_audit_home = dir_path;

    const response = try server.preexecResponse("{\"v\":1,\"kind\":\"preexec\",\"shell\":\"zsh\",\"command\":\"kubectl delete pod x --context api-prd-use1\"}");
    defer std.heap.page_allocator.free(response);
    try std.testing.expect(std.mem.indexOf(u8, response, "\"tier\":\"prod\"") != null);
    try std.testing.expect(std.mem.indexOf(u8, response, "\"allow\":false") != null);
    try std.testing.expect(std.mem.indexOf(u8, response, "\"confirm\":\"prod\"") != null);
    try std.testing.expect(std.mem.indexOf(u8, response, "\"destructive_pattern\":\"kubectl delete\"") != null);

    const audit_path = try prodGuardAuditPathAlloc(allocator, dir_path);
    defer allocator.free(audit_path);
    const audit = try std.fs.cwd().readFileAlloc(allocator, audit_path, 4096);
    defer allocator.free(audit);
    try std.testing.expect(std.mem.indexOf(u8, audit, "\"allow\":false") != null);
    try std.testing.expect(std.mem.indexOf(u8, audit, "\"pattern\":\"kubectl delete\"") != null);
}

test "preexec force allows and logs destructive command" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-server-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};

    const socket_path = try std.fmt.allocPrint(allocator, "{s}/shisa.sock", .{dir_path});
    defer allocator.free(socket_path);
    const log_path = try std.fmt.allocPrint(allocator, "{s}/shisad.log", .{dir_path});
    defer allocator.free(log_path);

    var logger = try daemon_log.Logger.open(allocator, log_path);
    defer logger.deinit();
    var server = try Server.initWithLogger(socket_path, &logger);
    defer server.deinit();
    server.prod_guard_audit_home = dir_path;

    const response = try server.preexecResponse("{\"v\":1,\"kind\":\"preexec\",\"force\":true,\"shell\":\"zsh\",\"command\":\"kubectl delete pod x --context api-prd-use1\"}");
    defer std.heap.page_allocator.free(response);
    try std.testing.expect(std.mem.indexOf(u8, response, "\"allow\":true") != null);
    try std.testing.expect(std.mem.indexOf(u8, response, "\"forced\":true") != null);

    const contents = try std.fs.cwd().readFileAlloc(allocator, log_path, 4096);
    defer allocator.free(contents);
    try std.testing.expect(std.mem.indexOf(u8, contents, "\"event\":\"prod_guard_force\"") != null);

    const audit_path = try prodGuardAuditPathAlloc(allocator, dir_path);
    defer allocator.free(audit_path);
    const audit = try std.fs.cwd().readFileAlloc(allocator, audit_path, 4096);
    defer allocator.free(audit);
    try std.testing.expect(std.mem.indexOf(u8, audit, "\"forced\":true") != null);
}

test "fs event invalidates git branch cache" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-server-git-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);
    try runGit(allocator, dir_path, &.{ "git", "init", "-b", "main" });

    const socket_path = try std.fmt.allocPrint(allocator, "{s}/shisa.sock", .{dir_path});
    defer allocator.free(socket_path);
    var server = try Server.init(socket_path);
    defer server.deinit();

    const request = try std.fmt.allocPrint(allocator, "{{\"v\":1,\"cwd\":\"{s}\",\"exit\":0,\"jobs\":0,\"duration_ms\":0,\"no_async\":true,\"shell\":\"zsh\",\"cols\":80,\"rows\":24}}", .{dir_path});
    defer allocator.free(request);
    const clean = try server.renderResponse(request);
    defer std.heap.page_allocator.free(clean);
    try std.testing.expect(std.mem.indexOf(u8, clean, "git:main> ") != null);
    try std.testing.expect(server.fs_watcher.hasScope(git_branch_module.module_id, dir_path));
    try std.testing.expectEqual(@as(u64, 0), server.cache_rev);

    const dirty_file = try std.fmt.allocPrint(allocator, "{s}/dirty.txt", .{dir_path});
    defer allocator.free(dirty_file);
    var file = try std.fs.createFileAbsolute(dirty_file, .{});
    try file.writeAll("dirty");
    file.close();

    server.recordFsEvent(dirty_file, 1);
    const dirty = try server.renderResponse(request);
    defer std.heap.page_allocator.free(dirty);
    try std.testing.expect(std.mem.indexOf(u8, dirty, "git:main*> ") != null);
    try std.testing.expectEqual(@as(u64, 1), server.cache_rev);
}

test "render response carries request id and v1 shape" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-server-render-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    const socket_path = try std.fmt.allocPrint(allocator, "{s}/shisa.sock", .{dir_path});
    defer allocator.free(socket_path);
    var server = try Server.init(socket_path);
    defer server.deinit();

    const request = try std.fmt.allocPrint(allocator, "{{\"v\":1,\"op\":\"render\",\"cwd\":\"{s}\",\"exit\":0,\"jobs\":0,\"duration_ms\":0,\"no_async\":true,\"shell\":\"zsh\",\"cols\":80,\"rows\":24,\"request_id\":\"render-test\"}}", .{dir_path});
    defer allocator.free(request);
    const response = try server.renderResponse(request);
    defer std.heap.page_allocator.free(response);

    const RenderResponseShape = struct {
        v: u32 = 1,
        request_id: []const u8 = "",
        prompt: []const u8,
        elapsed_us: u64 = 0,
    };
    var parsed = try std.json.parseFromSlice(RenderResponseShape, allocator, response, .{ .ignore_unknown_fields = true });
    defer parsed.deinit();
    try std.testing.expectEqualStrings("render-test", parsed.value.request_id);
    try std.testing.expect(parsed.value.prompt.len > 0);
}

test "render request modules select cdhint" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-server-cdhint-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);
    const marker_path = try std.fmt.allocPrint(allocator, "{s}/package.json", .{dir_path});
    defer allocator.free(marker_path);
    {
        var file = try std.fs.createFileAbsolute(marker_path, .{});
        defer file.close();
        try file.writeAll("{}");
    }

    const socket_path = try std.fmt.allocPrint(allocator, "{s}/shisa.sock", .{dir_path});
    defer allocator.free(socket_path);
    var server = try Server.init(socket_path);
    defer server.deinit();

    const request = try std.fmt.allocPrint(allocator, "{{\"v\":1,\"op\":\"render\",\"cwd\":\"{s}\",\"exit\":0,\"jobs\":0,\"duration_ms\":0,\"no_async\":true,\"shell\":\"zsh\",\"cols\":80,\"rows\":24,\"request_id\":\"cdhint-test\",\"modules\":[\"cdhint\"]}}", .{dir_path});
    defer allocator.free(request);
    const response = try server.renderResponse(request);
    defer std.heap.page_allocator.free(response);
    try std.testing.expect(std.mem.indexOf(u8, response, "\"prompt\":\"cd:node> \"") != null);
}

test "render request modules select tmux pane" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-server-tmux-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    const socket_path = try std.fmt.allocPrint(allocator, "{s}/shisa.sock", .{dir_path});
    defer allocator.free(socket_path);
    var server = try Server.init(socket_path);
    defer server.deinit();

    const request = try std.fmt.allocPrint(allocator, "{{\"v\":1,\"op\":\"render\",\"cwd\":\"{s}\",\"exit\":0,\"jobs\":0,\"duration_ms\":0,\"no_async\":true,\"shell\":\"zsh\",\"cols\":80,\"rows\":24,\"request_id\":\"tmux-test\",\"modules\":[\"tmux_pane\"],\"tmux_pane\":\"%4\"}}", .{dir_path});
    defer allocator.free(request);
    const response = try server.renderResponse(request);
    defer std.heap.page_allocator.free(response);
    try std.testing.expect(std.mem.indexOf(u8, response, "\"prompt\":\"tmux:%4> \"") != null);
}

test "render prompt cache key ignores request id and includes tuple fields" {
    const allocator = std.testing.allocator;
    const first = try renderPromptCacheKeyAlloc(allocator, .{
        .cwd = "/tmp/project",
        .exit = 0,
        .jobs = 1,
        .duration_ms = 10,
        .shell = "zsh",
        .cols = 80,
        .rows = 24,
        .request_id = "first",
    }, .{
        .timestamp_minute = 123,
        .user = "me",
        .host = "host",
    });
    defer allocator.free(first);
    const second = try renderPromptCacheKeyAlloc(allocator, .{
        .cwd = "/tmp/project",
        .exit = 0,
        .jobs = 1,
        .duration_ms = 10,
        .shell = "zsh",
        .cols = 80,
        .rows = 24,
        .request_id = "second",
    }, .{
        .timestamp_minute = 123,
        .user = "me",
        .host = "host",
    });
    defer allocator.free(second);
    const different_exit = try renderPromptCacheKeyAlloc(allocator, .{
        .cwd = "/tmp/project",
        .exit = 2,
        .jobs = 1,
        .duration_ms = 10,
        .shell = "zsh",
        .cols = 80,
        .rows = 24,
        .request_id = "first",
    }, .{
        .timestamp_minute = 123,
        .user = "me",
        .host = "host",
    });
    defer allocator.free(different_exit);
    const different_rev = try renderPromptCacheKeyAlloc(allocator, .{
        .cwd = "/tmp/project",
        .exit = 0,
        .jobs = 1,
        .duration_ms = 10,
        .shell = "zsh",
        .cols = 80,
        .rows = 24,
        .request_id = "first",
    }, .{
        .timestamp_minute = 123,
        .user = "me",
        .host = "host",
        .cache_rev = 1,
    });
    defer allocator.free(different_rev);
    const different_modules = try renderPromptCacheKeyAlloc(allocator, .{
        .cwd = "/tmp/project",
        .exit = 0,
        .jobs = 1,
        .duration_ms = 10,
        .shell = "zsh",
        .cols = 80,
        .rows = 24,
        .request_id = "first",
        .modules = &.{"cdhint"},
    }, .{
        .timestamp_minute = 123,
        .user = "me",
        .host = "host",
    });
    defer allocator.free(different_modules);
    const different_cdhint = try renderPromptCacheKeyAlloc(allocator, .{
        .cwd = "/tmp/project",
        .exit = 0,
        .jobs = 1,
        .duration_ms = 10,
        .shell = "zsh",
        .cols = 80,
        .rows = 24,
        .request_id = "first",
        .cdhint = .{ .enabled = false },
    }, .{
        .timestamp_minute = 123,
        .user = "me",
        .host = "host",
    });
    defer allocator.free(different_cdhint);
    const different_tmux = try renderPromptCacheKeyAlloc(allocator, .{
        .cwd = "/tmp/project",
        .exit = 0,
        .jobs = 1,
        .duration_ms = 10,
        .shell = "zsh",
        .cols = 80,
        .rows = 24,
        .request_id = "first",
        .tmux_pane = "%1",
    }, .{
        .timestamp_minute = 123,
        .user = "me",
        .host = "host",
    });
    defer allocator.free(different_tmux);

    try std.testing.expectEqualStrings(first, second);
    try std.testing.expect(!std.mem.eql(u8, first, different_exit));
    try std.testing.expect(!std.mem.eql(u8, first, different_rev));
    try std.testing.expect(!std.mem.eql(u8, first, different_modules));
    try std.testing.expect(!std.mem.eql(u8, first, different_cdhint));
    try std.testing.expect(!std.mem.eql(u8, first, different_tmux));
}

test "prompt cache hit rate uses ppm" {
    try std.testing.expectEqual(@as(u64, 0), promptCacheHitRatePpm(0, 0));
    try std.testing.expectEqual(@as(u64, 750000), promptCacheHitRatePpm(3, 1));
    try std.testing.expectEqual(@as(u64, 333333), promptCacheHitRatePpm(1, 2));
}

test "render response stores completed prompts in bounded l1 cache" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-server-l1-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    const socket_path = try std.fmt.allocPrint(allocator, "{s}/shisa.sock", .{dir_path});
    defer allocator.free(socket_path);
    var server = try Server.init(socket_path);
    defer server.deinit();
    server.prompt_cache.options.max_entries = 1;

    const first_request = try std.fmt.allocPrint(allocator, "{{\"v\":1,\"op\":\"render\",\"cwd\":\"{s}\",\"exit\":0,\"jobs\":0,\"duration_ms\":0,\"shell\":\"zsh\",\"cols\":80,\"rows\":24,\"request_id\":\"first\"}}", .{dir_path});
    defer allocator.free(first_request);
    const first = try server.renderResponse(first_request);
    defer std.heap.page_allocator.free(first);
    try std.testing.expect(std.mem.indexOf(u8, first, "\"request_id\":\"first\"") != null);
    try std.testing.expectEqual(@as(usize, 1), server.prompt_cache.count());
    try std.testing.expectEqual(@as(u64, 0), server.prompt_cache_hits);
    try std.testing.expectEqual(@as(u64, 1), server.prompt_cache_misses);

    const second_request = try std.fmt.allocPrint(allocator, "{{\"v\":1,\"op\":\"render_continue\",\"cwd\":\"{s}\",\"exit\":0,\"jobs\":0,\"duration_ms\":0,\"shell\":\"zsh\",\"cols\":80,\"rows\":24,\"request_id\":\"second\"}}", .{dir_path});
    defer allocator.free(second_request);
    const second = try server.renderResponse(second_request);
    defer std.heap.page_allocator.free(second);
    try std.testing.expect(std.mem.indexOf(u8, second, "\"request_id\":\"second\"") != null);
    try std.testing.expectEqual(@as(usize, 1), server.prompt_cache.count());
    try std.testing.expectEqual(@as(u64, 1), server.prompt_cache_hits);
    try std.testing.expectEqual(@as(u64, 1), server.prompt_cache_misses);

    const different_request = try std.fmt.allocPrint(allocator, "{{\"v\":1,\"op\":\"render\",\"cwd\":\"{s}\",\"exit\":2,\"jobs\":0,\"duration_ms\":0,\"shell\":\"zsh\",\"cols\":80,\"rows\":24,\"request_id\":\"different\"}}", .{dir_path});
    defer allocator.free(different_request);
    const different = try server.renderResponse(different_request);
    defer std.heap.page_allocator.free(different);
    try std.testing.expect(std.mem.indexOf(u8, different, "exit:2") != null);
    try std.testing.expectEqual(@as(usize, 1), server.prompt_cache.count());
    try std.testing.expectEqual(@as(u64, 1), server.prompt_cache_hits);
    try std.testing.expectEqual(@as(u64, 2), server.prompt_cache_misses);
}

test "stress 10k cd loop records prompt cache hit rate" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-server-cd-loop-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    const socket_path = try std.fmt.allocPrint(allocator, "{s}/shisa.sock", .{dir_path});
    defer allocator.free(socket_path);
    var server = try Server.init(socket_path);
    defer server.deinit();
    const context = RenderCacheContext{ .user = "me", .host = "host" };

    for (0..10) |index| {
        var cwd_buffer: [64]u8 = undefined;
        const cwd = try std.fmt.bufPrint(&cwd_buffer, "/repo/{d}", .{index});
        const key = try renderPromptCacheKeyAlloc(allocator, .{ .cwd = cwd, .shell = "zsh", .cols = 80, .rows = 24 }, context);
        defer allocator.free(key);
        try server.prompt_cache.put(prompt_cache_module, key, "cached> ", 0);
    }

    for (0..10_000) |index| {
        var cwd_buffer: [64]u8 = undefined;
        const cwd = try std.fmt.bufPrint(&cwd_buffer, "/repo/{d}", .{index % 10});
        const key = try renderPromptCacheKeyAlloc(allocator, .{ .cwd = cwd, .shell = "zsh", .cols = 80, .rows = 24 }, context);
        defer allocator.free(key);
        if ((try server.prompt_cache.get(prompt_cache_module, key)) != null) {
            server.prompt_cache_hits += 1;
        } else {
            server.prompt_cache_misses += 1;
        }
    }

    try std.testing.expectEqual(@as(u64, 10_000), server.prompt_cache_hits);
    try std.testing.expectEqual(@as(u64, 0), server.prompt_cache_misses);
    try std.testing.expectEqual(@as(u64, 1_000_000), promptCacheHitRatePpm(server.prompt_cache_hits, server.prompt_cache_misses));
}

test "render_continue fills async git segment from cache within 1000 ms" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-server-continue-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);
    try runGit(allocator, dir_path, &.{ "git", "init", "-b", "main" });

    const socket_path = try std.fmt.allocPrint(allocator, "{s}/shisa.sock", .{dir_path});
    defer allocator.free(socket_path);
    var server = try Server.init(socket_path);
    defer server.deinit();

    const initial_request = try std.fmt.allocPrint(allocator, "{{\"v\":1,\"op\":\"render\",\"cwd\":\"{s}\",\"exit\":0,\"jobs\":0,\"duration_ms\":0,\"shell\":\"zsh\",\"cols\":80,\"rows\":24,\"request_id\":\"render-start\"}}", .{dir_path});
    defer allocator.free(initial_request);
    const initial_response = try server.renderResponse(initial_request);
    defer std.heap.page_allocator.free(initial_response);
    try std.testing.expect(std.mem.indexOf(u8, initial_response, "[pending:git_branch]") != null);
    try std.testing.expect(std.mem.indexOf(u8, initial_response, "\"redraw_token\":\"pending\"") != null);

    const continue_request = try std.fmt.allocPrint(allocator, "{{\"v\":1,\"op\":\"render_continue\",\"cwd\":\"{s}\",\"exit\":0,\"jobs\":0,\"duration_ms\":0,\"shell\":\"zsh\",\"cols\":80,\"rows\":24,\"request_id\":\"render-continue\"}}", .{dir_path});
    defer allocator.free(continue_request);
    const deadline_ms: i64 = 1000;
    const poll_ms: u64 = 20;
    const start_ms = std.time.milliTimestamp();
    while (std.time.milliTimestamp() - start_ms < deadline_ms) {
        std.Thread.sleep(poll_ms * std.time.ns_per_ms);
        const response = try server.renderResponse(continue_request);
        defer std.heap.page_allocator.free(response);
        if (std.mem.indexOf(u8, response, "git:main") != null) {
            const elapsed_ms = std.time.milliTimestamp() - start_ms;
            try std.testing.expect(std.mem.indexOf(u8, response, "\"request_id\":\"render-continue\"") != null);
            try std.testing.expect(std.mem.indexOf(u8, response, "\"redraw_token\":null") != null);
            try std.testing.expect(elapsed_ms <= deadline_ms);
            return;
        }
    }
    return error.AsyncFillDeadlineExceeded;
}

test "health op returns minimal ok response" {
    const allocator = std.testing.allocator;
    const response = try healthResponseAlloc(allocator, "{\"v\":1,\"op\":\"health\",\"request_id\":\"health-1\"}", true);
    defer allocator.free(response);

    const HealthResponse = struct {
        v: u32 = 1,
        request_id: []const u8 = "",
        ok: bool,
    };
    var parsed = try std.json.parseFromSlice(HealthResponse, allocator, response, .{ .ignore_unknown_fields = true });
    defer parsed.deinit();
    try std.testing.expectEqual(@as(u32, 1), parsed.value.v);
    try std.testing.expectEqualStrings("health-1", parsed.value.request_id);
    try std.testing.expect(parsed.value.ok);
}

test "version op returns daemon and protocol version" {
    const allocator = std.testing.allocator;
    const response = try versionResponseAlloc(allocator, "{\"v\":1,\"op\":\"version\",\"request_id\":\"version-1\"}");
    defer allocator.free(response);

    const VersionResponse = struct {
        v: u32 = 1,
        request_id: []const u8 = "",
        daemon: []const u8,
        protocol: u32,
    };
    var parsed = try std.json.parseFromSlice(VersionResponse, allocator, response, .{ .ignore_unknown_fields = true });
    defer parsed.deinit();
    try std.testing.expectEqual(@as(u32, 1), parsed.value.v);
    try std.testing.expectEqualStrings("version-1", parsed.value.request_id);
    try std.testing.expectEqualStrings(daemon_version, parsed.value.daemon);
    try std.testing.expectEqual(protocol_version, parsed.value.protocol);
}

test "reload op rereads config and bumps generations" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-server-reload-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    const socket_path = try std.fmt.allocPrint(allocator, "{s}/shisa.sock", .{dir_path});
    defer allocator.free(socket_path);
    const config_path = try std.fmt.allocPrint(allocator, "{s}/shisa.toml", .{dir_path});
    defer allocator.free(config_path);
    const plugins_dir = try std.fmt.allocPrint(allocator, "{s}/plugins", .{dir_path});
    defer allocator.free(plugins_dir);

    try std.fs.cwd().writeFile(.{
        .sub_path = config_path,
        .data =
        \\version = 1
        \\theme = "plain"
        \\
        \\[prompt]
        \\modules = ["cwd"]
        \\
        ,
    });

    var server = try Server.init(socket_path);
    defer server.deinit();
    server.config_path_override = config_path;
    server.plugins_dir_override = plugins_dir;

    const first = try server.reloadResponseAlloc(allocator, "{\"v\":1,\"op\":\"reload\",\"request_id\":\"reload-1\"}");
    defer allocator.free(first);
    try std.testing.expect(std.mem.indexOf(u8, first, "\"reloaded\":true") != null);
    try std.testing.expectEqual(@as(u64, 1), server.reload_state.config_generation);
    try std.testing.expectEqual(@as(u64, 1), server.reload_state.plugin_generation);
    try std.testing.expectEqual(@as(usize, 0), server.reload_state.plugin_names.len);
    try std.testing.expect(std.mem.indexOf(u8, server.reload_state.config_source, "theme = \"plain\"") != null);

    try std.fs.cwd().writeFile(.{
        .sub_path = config_path,
        .data =
        \\version = 1
        \\theme = "minimal"
        \\
        \\[prompt]
        \\modules = ["cwd", "time"]
        \\
        ,
    });

    const second = try server.reloadResponseAlloc(allocator, "{\"v\":1,\"op\":\"reload\",\"request_id\":\"reload-2\"}");
    defer allocator.free(second);
    try std.testing.expect(std.mem.indexOf(u8, second, "\"config_generation\":2") != null);
    try std.testing.expect(std.mem.indexOf(u8, server.reload_state.config_source, "theme = \"minimal\"") != null);
    try std.testing.expect(std.mem.indexOf(u8, server.reload_state.config_source, "modules = [\"cwd\", \"time\"]") != null);
}

test "reload signal rereads config and clears flag" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-server-sigusr1-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    const socket_path = try std.fmt.allocPrint(allocator, "{s}/shisa.sock", .{dir_path});
    defer allocator.free(socket_path);
    const config_path = try std.fmt.allocPrint(allocator, "{s}/shisa.toml", .{dir_path});
    defer allocator.free(config_path);
    const plugins_dir = try std.fmt.allocPrint(allocator, "{s}/plugins", .{dir_path});
    defer allocator.free(plugins_dir);

    try std.fs.cwd().writeFile(.{
        .sub_path = config_path,
        .data =
        \\version = 1
        \\theme = "signal"
        \\
        \\[prompt]
        \\modules = ["cwd"]
        \\
        ,
    });

    var server = try Server.init(socket_path);
    defer server.deinit();
    server.config_path_override = config_path;
    server.plugins_dir_override = plugins_dir;

    var reload_requested = std.atomic.Value(bool).init(true);
    try server.consumeReloadSignal(&reload_requested);
    try std.testing.expect(!reload_requested.load(.seq_cst));
    try std.testing.expectEqual(@as(u64, 1), server.reload_state.config_generation);
    try std.testing.expect(std.mem.indexOf(u8, server.reload_state.config_source, "theme = \"signal\"") != null);
}

test "stack dump signal logs frames and clears flag" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-server-sigusr2-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    const socket_path = try std.fmt.allocPrint(allocator, "{s}/shisa.sock", .{dir_path});
    defer allocator.free(socket_path);
    const log_path = try std.fmt.allocPrint(allocator, "{s}/shisad.log", .{dir_path});
    defer allocator.free(log_path);

    var logger = try daemon_log.Logger.open(allocator, log_path);
    defer logger.deinit();
    var server = try Server.initWithLogger(socket_path, &logger);
    defer server.deinit();

    var stack_dump_requested = std.atomic.Value(bool).init(true);
    try server.consumeStackDumpSignal(&stack_dump_requested);
    try std.testing.expect(!stack_dump_requested.load(.seq_cst));

    const contents = try std.fs.cwd().readFileAlloc(allocator, log_path, 4096);
    defer allocator.free(contents);
    try std.testing.expect(std.mem.indexOf(u8, contents, "\"event\":\"stack_dump\"") != null);
    try std.testing.expect(std.mem.indexOf(u8, contents, "frames=0x") != null);
}

test "reload op rereads plugin manifests" {
    const allocator = std.testing.allocator;
    var runtime = plugin_lua.Runtime.initSandboxed(allocator) catch |err| switch (err) {
        error.LuaUnavailable => return error.SkipZigTest,
        else => return err,
    };
    runtime.deinit();

    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-server-reload-plugin-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    const plugin_path = try std.fmt.allocPrint(allocator, "{s}/plugins/demo-plugin", .{dir_path});
    defer allocator.free(plugin_path);
    try std.fs.cwd().makePath(plugin_path);

    const socket_path = try std.fmt.allocPrint(allocator, "{s}/shisa.sock", .{dir_path});
    defer allocator.free(socket_path);
    const config_path = try std.fmt.allocPrint(allocator, "{s}/shisa.toml", .{dir_path});
    defer allocator.free(config_path);
    const plugins_dir = try std.fmt.allocPrint(allocator, "{s}/plugins", .{dir_path});
    defer allocator.free(plugins_dir);
    const manifest_path = try std.fmt.allocPrint(allocator, "{s}/plugin.lua", .{plugin_path});
    defer allocator.free(manifest_path);

    try std.fs.cwd().writeFile(.{
        .sub_path = config_path,
        .data =
        \\version = 1
        \\theme = "plain"
        \\
        \\[prompt]
        \\modules = ["cwd"]
        \\
        ,
    });
    try std.fs.cwd().writeFile(.{
        .sub_path = manifest_path,
        .data =
        \\return {
        \\  name = "demo-plugin",
        \\  version = "0.1.0",
        \\  api_version = 1,
        \\  license = "MIT",
        \\  modules = { "demo" },
        \\}
        ,
    });

    var server = try Server.init(socket_path);
    defer server.deinit();
    server.config_path_override = config_path;
    server.plugins_dir_override = plugins_dir;

    const response = try server.reloadResponseAlloc(allocator, "{\"v\":1,\"op\":\"reload\",\"request_id\":\"reload-plugin\"}");
    defer allocator.free(response);
    try std.testing.expect(std.mem.indexOf(u8, response, "\"plugins\":1") != null);
    try std.testing.expectEqual(@as(usize, 1), server.reload_state.plugin_names.len);
    try std.testing.expectEqualStrings("demo-plugin", server.reload_state.plugin_names[0]);
}

test "slow plugin strikes disable after third strike" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-plugin-strikes-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    const plugins_dir = try std.fmt.allocPrint(allocator, "{s}/plugins", .{dir_path});
    defer allocator.free(plugins_dir);
    const strikes_path = try pluginStatePathForPluginsDirAlloc(allocator, plugins_dir, "plugins.slow-strikes");
    defer allocator.free(strikes_path);
    const disabled_path = try pluginStatePathForPluginsDirAlloc(allocator, plugins_dir, "plugins.disabled");
    defer allocator.free(disabled_path);

    try recordPluginSlowStrike(allocator, strikes_path, disabled_path, "slow-plugin");
    try std.testing.expect(!(try pluginNameListed(allocator, disabled_path, "slow-plugin")));
    try recordPluginSlowStrike(allocator, strikes_path, disabled_path, "slow-plugin");
    try std.testing.expect(!(try pluginNameListed(allocator, disabled_path, "slow-plugin")));
    try recordPluginSlowStrike(allocator, strikes_path, disabled_path, "slow-plugin");
    try std.testing.expect(try pluginNameListed(allocator, disabled_path, "slow-plugin"));

    const strikes = try std.fs.cwd().readFileAlloc(allocator, strikes_path, 4096);
    defer allocator.free(strikes);
    try std.testing.expectEqualStrings("slow-plugin 3\n", strikes);
}

test "reload disables slow plugin after three cpu strikes" {
    const allocator = std.testing.allocator;
    var runtime = plugin_lua.Runtime.initSandboxed(allocator) catch |err| switch (err) {
        error.LuaUnavailable => return error.SkipZigTest,
        else => return err,
    };
    runtime.deinit();

    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-server-slow-plugin-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    const plugin_path = try std.fmt.allocPrint(allocator, "{s}/plugins/slow-plugin", .{dir_path});
    defer allocator.free(plugin_path);
    try std.fs.cwd().makePath(plugin_path);

    const socket_path = try std.fmt.allocPrint(allocator, "{s}/shisa.sock", .{dir_path});
    defer allocator.free(socket_path);
    const config_path = try std.fmt.allocPrint(allocator, "{s}/shisa.toml", .{dir_path});
    defer allocator.free(config_path);
    const plugins_dir = try std.fmt.allocPrint(allocator, "{s}/plugins", .{dir_path});
    defer allocator.free(plugins_dir);
    const manifest_path = try std.fmt.allocPrint(allocator, "{s}/plugin.lua", .{plugin_path});
    defer allocator.free(manifest_path);
    const disabled_path = try pluginStatePathForPluginsDirAlloc(allocator, plugins_dir, "plugins.disabled");
    defer allocator.free(disabled_path);

    try std.fs.cwd().writeFile(.{
        .sub_path = config_path,
        .data =
        \\version = 1
        \\theme = "plain"
        \\
        \\[prompt]
        \\modules = ["cwd"]
        \\
        ,
    });
    try std.fs.cwd().writeFile(.{
        .sub_path = manifest_path,
        .data = "while true do end\n",
    });

    var server = try Server.init(socket_path);
    defer server.deinit();
    server.config_path_override = config_path;
    server.plugins_dir_override = plugins_dir;

    for (0..3) |index| {
        const request = try std.fmt.allocPrint(allocator, "{{\"v\":1,\"op\":\"reload\",\"request_id\":\"reload-slow-{d}\"}}", .{index});
        defer allocator.free(request);
        const response = try server.reloadResponseAlloc(allocator, request);
        defer allocator.free(response);
        try std.testing.expect(std.mem.indexOf(u8, response, "\"plugins\":0") != null);
    }
    try std.testing.expect(try pluginNameListed(allocator, disabled_path, "slow-plugin"));
}

test "daemon checks plugin host api calls through capability gate" {
    const capabilities = plugin_manifest.Capabilities{
        .fs_read = &.{"/repo/**"},
        .fs_watch = &.{"/repo/.git/**"},
        .exec = .{ .allow = &.{"git"} },
        .net = .{ .allow = &.{"api.example.com"} },
        .env_read = &.{"AWS_PROFILE"},
        .secrets = true,
        .pre_exec = true,
    };
    const context = plugin_capability.Context{};

    try Server.checkPluginHostApiCall(capabilities, context, .{ .fs_read = "/repo/config.toml" });
    try Server.checkPluginHostApiCall(capabilities, context, .{ .fs_watch = "/repo/.git/HEAD" });
    try Server.checkPluginHostApiCall(capabilities, context, .{ .exec = "git" });
    try Server.checkPluginHostApiCall(capabilities, context, .{ .net = "api.example.com" });
    try Server.checkPluginHostApiCall(capabilities, context, .{ .env_read = "AWS_PROFILE" });
    try Server.checkPluginHostApiCall(capabilities, context, .secrets);
    try Server.checkPluginHostApiCall(capabilities, context, .pre_exec);
    try std.testing.expectError(error.CapabilityDenied, Server.checkPluginHostApiCall(capabilities, context, .{ .exec = "sh" }));
}

test "subscribe op switches connection to bidirectional ndjson" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-server-subscribe-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};

    const socket_path = try std.fmt.allocPrint(allocator, "{s}/shisa.sock", .{dir_path});
    defer allocator.free(socket_path);

    var server = try Server.init(socket_path);
    defer server.deinit();

    const thread = try std.Thread.spawn(.{}, acceptOneThread, .{&server});

    var client_stream = try std.net.connectUnixSocket(socket_path);
    try writeFrame(client_stream.handle, "{\"v\":1,\"op\":\"subscribe\",\"request_id\":\"subscribe-1\",\"topics\":[\"vcs.summary\",\"vcs.summary\"]}");

    const snapshot = try readNdjsonLineAlloc(allocator, client_stream.handle, 4096);
    defer allocator.free(snapshot);
    try std.testing.expect(std.mem.endsWith(u8, snapshot, "\n"));
    try std.testing.expect(std.mem.indexOf(u8, snapshot, "\"kind\":\"snapshot\"") != null);
    try std.testing.expect(std.mem.indexOf(u8, snapshot, "\"topics\":1") != null);
    try std.testing.expect(std.mem.indexOf(u8, snapshot, "\"refs\":{\"vcs.summary\":2}") != null);

    try writeAll(client_stream.handle, "{\"op\":\"ping\"}\n");
    const delta = try readNdjsonLineAlloc(allocator, client_stream.handle, 4096);
    defer allocator.free(delta);
    try std.testing.expect(std.mem.endsWith(u8, delta, "\n"));
    try std.testing.expect(std.mem.indexOf(u8, delta, "\"kind\":\"delta\"") != null);
    try std.testing.expect(std.mem.indexOf(u8, delta, "\"topic\":\"vcs.summary\"") != null);
    try std.testing.expect(std.mem.indexOf(u8, delta, "\"sequence\":1") != null);

    const heartbeat = try readNdjsonLineAlloc(allocator, client_stream.handle, 4096);
    defer allocator.free(heartbeat);
    try std.testing.expect(std.mem.endsWith(u8, heartbeat, "\n"));
    try std.testing.expect(std.mem.indexOf(u8, heartbeat, "\"kind\":\"heartbeat\"") != null);

    client_stream.close();
    thread.join();
}

test "subscribe backpressure queue drops over limit" {
    const allocator = std.testing.allocator;
    var queue = SubscriptionQueue.init(allocator, 1);
    defer queue.deinit();

    try std.testing.expect(try queue.pushOwned(try allocator.dupe(u8, "first\n")));
    try std.testing.expect(!(try queue.pushOwned(try allocator.dupe(u8, "second\n"))));
    try std.testing.expectEqual(@as(u64, 1), queue.dropped);
    try std.testing.expectEqual(@as(usize, 1), queue.events.items.len);
    try std.testing.expectEqual(@as(usize, default_subscribe_backpressure_limit), subscribeBackpressureLimit(0));
    try std.testing.expectEqual(@as(usize, max_subscribe_backpressure_limit), subscribeBackpressureLimit(max_subscribe_backpressure_limit + 1));
}

test "subscribe op exits cleanly on client disconnect" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-server-subscribe-close-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};

    const socket_path = try std.fmt.allocPrint(allocator, "{s}/shisa.sock", .{dir_path});
    defer allocator.free(socket_path);

    var server = try Server.init(socket_path);
    defer server.deinit();

    const thread = try std.Thread.spawn(.{}, acceptOneThread, .{&server});

    var client_stream = try std.net.connectUnixSocket(socket_path);
    try writeFrame(client_stream.handle, "{\"v\":1,\"op\":\"subscribe\",\"request_id\":\"subscribe-close\",\"topics\":[\"vcs.summary\"]}");
    const snapshot = try readNdjsonLineAlloc(allocator, client_stream.handle, 4096);
    defer allocator.free(snapshot);
    try std.testing.expect(std.mem.indexOf(u8, snapshot, "\"kind\":\"snapshot\"") != null);

    client_stream.close();
    thread.join();
}

test "serve drains subscribe shutdown and unlinks socket" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-server-shutdown-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};

    const socket_path = try std.fmt.allocPrint(allocator, "{s}/shisa.sock", .{dir_path});
    defer allocator.free(socket_path);

    var server = try Server.init(socket_path);
    var shutdown_requested = std.atomic.Value(bool).init(false);
    var reload_requested = std.atomic.Value(bool).init(false);
    var stack_dump_requested = std.atomic.Value(bool).init(false);
    const thread = try std.Thread.spawn(.{}, serveThread, .{ &server, &shutdown_requested, &reload_requested, &stack_dump_requested });

    var client_stream = try std.net.connectUnixSocket(socket_path);
    defer client_stream.close();
    try writeFrame(client_stream.handle, "{\"v\":1,\"op\":\"subscribe\",\"request_id\":\"shutdown\",\"topics\":[\"vcs.summary\"]}");
    const snapshot = try readNdjsonLineAlloc(allocator, client_stream.handle, 4096);
    defer allocator.free(snapshot);
    try std.testing.expect(std.mem.indexOf(u8, snapshot, "\"kind\":\"snapshot\"") != null);

    const start_ms = std.time.milliTimestamp();
    shutdown_requested.store(true, .seq_cst);
    thread.join();
    const elapsed_ms = std.time.milliTimestamp() - start_ms;
    try std.testing.expect(elapsed_ms < graceful_shutdown_timeout_ms);

    server.deinit();
    try std.testing.expectError(error.FileNotFound, std.fs.cwd().access(socket_path, .{}));
}

test "subscribe rejects mutating commands as readonly" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-server-subscribe-readonly-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};

    const socket_path = try std.fmt.allocPrint(allocator, "{s}/shisa.sock", .{dir_path});
    defer allocator.free(socket_path);

    var server = try Server.init(socket_path);
    defer server.deinit();

    const thread = try std.Thread.spawn(.{}, acceptOneThread, .{&server});

    var client_stream = try std.net.connectUnixSocket(socket_path);
    try writeFrame(client_stream.handle, "{\"v\":1,\"op\":\"subscribe\",\"request_id\":\"subscribe-readonly\",\"topics\":[\"vcs.summary\"]}");
    const snapshot = try readNdjsonLineAlloc(allocator, client_stream.handle, 4096);
    defer allocator.free(snapshot);
    try std.testing.expect(std.mem.indexOf(u8, snapshot, "\"kind\":\"snapshot\"") != null);

    try writeAll(client_stream.handle, "{\"op\":\"reload\"}\n");
    const readonly = try readNdjsonLineAlloc(allocator, client_stream.handle, 4096);
    defer allocator.free(readonly);
    try std.testing.expect(std.mem.indexOf(u8, readonly, "\"kind\":\"error\"") != null);
    try std.testing.expect(std.mem.indexOf(u8, readonly, "\"code\":\"E_READONLY\"") != null);
    try std.testing.expect(std.mem.indexOf(u8, readonly, "\"op\":\"reload\"") != null);

    client_stream.close();
    thread.join();
}

test "subscribe cannot bypass prod guard preexec" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-server-subscribe-prodguard-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};

    const socket_path = try std.fmt.allocPrint(allocator, "{s}/shisa.sock", .{dir_path});
    defer allocator.free(socket_path);

    var server = try Server.init(socket_path);
    defer server.deinit();
    server.prod_guard_audit_home = dir_path;

    const thread = try std.Thread.spawn(.{}, acceptOneThread, .{&server});

    var client_stream = try std.net.connectUnixSocket(socket_path);
    try writeFrame(client_stream.handle, "{\"v\":1,\"op\":\"subscribe\",\"request_id\":\"subscribe-prodguard\",\"topics\":[\"risk_tier\"]}");
    const snapshot = try readNdjsonLineAlloc(allocator, client_stream.handle, 4096);
    defer allocator.free(snapshot);
    try std.testing.expect(std.mem.indexOf(u8, snapshot, "\"kind\":\"snapshot\"") != null);

    try writeAll(client_stream.handle, "{\"v\":1,\"kind\":\"preexec\",\"shell\":\"zsh\",\"command\":\"kubectl delete pod x --context api-prd-use1\"}\n");
    const readonly = try readNdjsonLineAlloc(allocator, client_stream.handle, 4096);
    defer allocator.free(readonly);
    try std.testing.expect(std.mem.indexOf(u8, readonly, "\"code\":\"E_READONLY\"") != null);
    try std.testing.expect(std.mem.indexOf(u8, readonly, "\"op\":\"preexec\"") != null);

    const audit_path = try prodGuardAuditPathAlloc(allocator, dir_path);
    defer allocator.free(audit_path);
    try std.testing.expectError(error.FileNotFound, std.fs.cwd().access(audit_path, .{}));

    client_stream.close();
    thread.join();
}

test "metrics op returns JSON metrics dump" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-server-metrics-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    const socket_path = try std.fmt.allocPrint(allocator, "{s}/shisa.sock", .{dir_path});
    defer allocator.free(socket_path);
    var server = try Server.init(socket_path);
    defer server.deinit();
    server.connections = 3;
    server.recordRender(50);
    server.recordRender(6000);
    server.prompt_cache_hits = 3;
    server.prompt_cache_misses = 1;
    try server.prompt_cache.put(prompt_cache_module, "metrics-key", "cached> ", 0);
    server.reload_state.plugin_names = try std.heap.page_allocator.alloc([]u8, 1);
    server.reload_state.plugin_names[0] = try std.heap.page_allocator.dupe(u8, "demo-plugin");

    const response = try server.metricsResponseAlloc(allocator, "{\"v\":1,\"op\":\"metrics\",\"request_id\":\"metrics-1\"}");
    defer allocator.free(response);
    try std.testing.expect(std.mem.indexOf(u8, response, "\"request_id\":\"metrics-1\"") != null);
    try std.testing.expect(std.mem.indexOf(u8, response, "\"connections\":3") != null);
    try std.testing.expect(std.mem.indexOf(u8, response, "\"git_branch\"") != null);
    try std.testing.expect(std.mem.indexOf(u8, response, "\"prompt_l1\":{\"entries\":1,\"hits\":3,\"misses\":1,\"hit_rate_ppm\":750000}") != null);
    try std.testing.expect(std.mem.indexOf(u8, response, "\"render\":{\"count\":2,\"total_us\":6050,\"max_us\":6000") != null);
    try std.testing.expect(std.mem.indexOf(u8, response, "\"le_100us\":1") != null);
    try std.testing.expect(std.mem.indexOf(u8, response, "\"gt_5000us\":1") != null);
    try std.testing.expect(std.mem.indexOf(u8, response, "\"plugins\":1") != null);
    try std.testing.expect(std.mem.indexOf(u8, response, "\"fsnotify\"") != null);

    const prometheus = try server.metricsResponseAlloc(allocator, "{\"v\":1,\"op\":\"metrics\",\"request_id\":\"metrics-prom\",\"format\":\"prometheus\"}");
    defer allocator.free(prometheus);
    try std.testing.expect(std.mem.indexOf(u8, prometheus, "# TYPE shisa_connections gauge") != null);
    try std.testing.expect(std.mem.indexOf(u8, prometheus, "shisa_render_count 2") != null);
    try std.testing.expect(std.mem.indexOf(u8, prometheus, "shisa_render_latency_bucket{le=\"+Inf\"} 1") != null);
    try std.testing.expect(std.mem.indexOf(u8, prometheus, "shisa_prompt_cache_entries 1") != null);
    try std.testing.expect(std.mem.indexOf(u8, prometheus, "shisa_prompt_cache_hit_rate_ppm 750000") != null);
    try std.testing.expect(std.mem.indexOf(u8, prometheus, "shisa_plugins 1") != null);
}

test "logs slow module warning" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-server-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};

    const socket_path = try std.fmt.allocPrint(allocator, "{s}/shisa.sock", .{dir_path});
    defer allocator.free(socket_path);
    const log_path = try std.fmt.allocPrint(allocator, "{s}/shisad.log", .{dir_path});
    defer allocator.free(log_path);

    var logger = try daemon_log.Logger.open(allocator, log_path);
    defer logger.deinit();
    var server = try Server.initWithLogger(socket_path, &logger);
    defer server.deinit();

    try server.logSlowWarning(.{ .module_id = .language_versions, .elapsed_ns = 12_000_000 });

    const contents = try std.fs.cwd().readFileAlloc(allocator, log_path, 4096);
    defer allocator.free(contents);
    try std.testing.expect(std.mem.indexOf(u8, contents, "\"event\":\"slow_module\"") != null);
    try std.testing.expect(std.mem.indexOf(u8, contents, "module=language_versions") != null);
}

fn runGit(allocator: std.mem.Allocator, cwd_path: []const u8, argv: []const []const u8) !void {
    const result = try std.process.Child.run(.{
        .allocator = allocator,
        .argv = argv,
        .cwd = cwd_path,
        .max_output_bytes = 4096,
        .expand_arg0 = .expand,
    });
    defer allocator.free(result.stdout);
    defer allocator.free(result.stderr);
    try std.testing.expect(switch (result.term) {
        .Exited => |code| code == 0,
        else => false,
    });
}
