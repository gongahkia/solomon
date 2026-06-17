const std = @import("std");
const cloud_ctx_module = @import("modules/cloud_ctx.zig");
const dispatcher = @import("dispatcher.zig");
const cost_glance_module = @import("modules/cost_glance.zig");
const git_branch_module = @import("modules/git_branch.zig");
const iac_workspace_module = @import("modules/iac_workspace.zig");
const language_versions_module = @import("modules/language_versions.zig");
const prod_guard_module = @import("modules/prod_guard.zig");
const risk_tier_module = @import("modules/risk_tier.zig");
const sso_expiry_module = @import("modules/sso_expiry.zig");
const daemon_log = @import("log.zig");
const warmup = @import("warmup.zig");
const json = @import("json.zig");
const fsnotify = @import("fsnotify.zig");

const header_bytes = 4;
const max_frame_bytes = 1024 * 1024;

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
    cloud_ctx: cloud_ctx_module.Options = .{},
    sso_expiry: sso_expiry_module.Options = .{},
};

const PreexecRequest = struct {
    v: u32 = 1,
    kind: []const u8 = "",
    cwd: []const u8 = "",
    shell: []const u8 = "",
    command: []const u8 = "",
    force: bool = false,
};

pub const Server = struct {
    socket_path: []const u8,
    listener: std.net.Server,
    logger: ?*daemon_log.Logger = null,
    connections: u64 = 0,
    git_branch_cache: git_branch_module.Cache = .{},
    language_versions_cache: language_versions_module.Cache = .{},
    cloud_ctx_cache: cloud_ctx_module.Cache = .{},
    fs_watcher: fsnotify.Watcher,
    prod_guard_audit_home: ?[]const u8 = null,
    cost_refresh_shutdown: std.atomic.Value(bool) = std.atomic.Value(bool).init(false),
    cost_refresh_thread: ?std.Thread = null,
    cost_refresh_home: ?[]u8 = null,

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
            .fs_watcher = fsnotify.Watcher.init(std.heap.page_allocator),
        };
    }

    pub fn deinit(self: *Server) void {
        self.stopCostRefresh();
        self.git_branch_cache.deinit(std.heap.page_allocator);
        self.language_versions_cache.deinit(std.heap.page_allocator);
        self.cloud_ctx_cache.deinit(std.heap.page_allocator);
        self.fs_watcher.deinit();
        self.listener.deinit();
        std.fs.deleteFileAbsolute(self.socket_path) catch {};
        self.* = undefined;
    }

    pub fn serve(self: *Server, shutdown_requested: *const std.atomic.Value(bool)) !void {
        try self.warmupCaches(std.heap.page_allocator);
        try self.startCostRefresh(std.heap.page_allocator);
        while (!shutdown_requested.load(.seq_cst)) {
            var poll_fds = [_]std.posix.pollfd{.{
                .fd = self.listener.stream.handle,
                .events = std.posix.POLL.IN,
                .revents = 0,
            }};

            const ready = try std.posix.poll(&poll_fds, 100);
            if (ready == 0) continue;

            if ((poll_fds[0].revents & std.posix.POLL.IN) != 0) {
                try self.acceptOne();
            }
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
        const connection = try self.listener.accept();
        self.connections += 1;
        try self.handleConnection(connection);
    }

    fn handleConnection(self: *Server, connection: std.net.Server.Connection) !void {
        defer connection.stream.close();

        const request = try readFrameAlloc(std.heap.page_allocator, connection.stream.handle);
        defer std.heap.page_allocator.free(request);

        if (std.mem.startsWith(u8, request, "metrics")) {
            var response: [128]u8 = undefined;
            const line = try std.fmt.bufPrint(&response, "{{\"connections\":{d}}}\n", .{self.connections});
            try writeFrame(connection.stream.handle, line);
        } else if (std.mem.startsWith(u8, request, "health")) {
            try writeFrame(connection.stream.handle, "ok\n");
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
        if (!std.mem.eql(u8, parsed.value.op, "render")) {
            const escaped_request_id = try json.escapeAlloc(std.heap.page_allocator, parsed.value.request_id);
            defer std.heap.page_allocator.free(escaped_request_id);
            return std.fmt.allocPrint(
                std.heap.page_allocator,
                "{{\"v\":1,\"request_id\":\"{s}\",\"error\":{{\"code\":\"E_MALFORMED\",\"message\":\"unsupported render path op\",\"context\":{{\"field\":\"op\",\"expected\":\"render\"}}}}}}",
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

        var rendered = try dispatcher.renderDefault(std.heap.page_allocator, .{
            .git_branch = &self.git_branch_cache,
            .language_versions = &self.language_versions_cache,
            .cloud_ctx = &self.cloud_ctx_cache,
        }, .{
            .cwd = parsed.value.cwd,
            .home = home,
            .exit = parsed.value.exit,
            .jobs = parsed.value.jobs,
            .duration_ms = parsed.value.duration_ms,
            .time = parsed.value.time,
            .no_async = parsed.value.no_async,
            .timestamp = std.time.timestamp(),
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
            .kubeconfig = kubeconfig,
            .cloud_ctx = parsed.value.cloud_ctx,
            .sso_expiry = parsed.value.sso_expiry,
        });
        defer rendered.deinit(std.heap.page_allocator);
        try self.logSlowWarning(rendered.slow_warning);

        const escaped_request_id = try json.escapeAlloc(std.heap.page_allocator, parsed.value.request_id);
        defer std.heap.page_allocator.free(escaped_request_id);
        const escaped_prompt = try json.escapeAlloc(std.heap.page_allocator, rendered.prompt);
        defer std.heap.page_allocator.free(escaped_prompt);
        const elapsed_us = (nowNs() - start_ns) / std.time.ns_per_us;

        if (rendered.redraw_token) |token| {
            const escaped_token = try json.escapeAlloc(std.heap.page_allocator, token);
            defer std.heap.page_allocator.free(escaped_token);
            return std.fmt.allocPrint(std.heap.page_allocator, "{{\"v\":1,\"request_id\":\"{s}\",\"prompt\":\"{s}\",\"redraw_token\":\"{s}\",\"trailer\":null,\"diagnostics\":[],\"elapsed_us\":{d}}}", .{ escaped_request_id, escaped_prompt, escaped_token, elapsed_us });
        }
        return std.fmt.allocPrint(std.heap.page_allocator, "{{\"v\":1,\"request_id\":\"{s}\",\"prompt\":\"{s}\",\"redraw_token\":null,\"trailer\":null,\"diagnostics\":[],\"elapsed_us\":{d}}}", .{ escaped_request_id, escaped_prompt, elapsed_us });
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

    pub fn recordFsEvent(self: *Server, path: []const u8, timestamp_ns: u64) void {
        self.fs_watcher.recordEvent(path, timestamp_ns);
    }

    fn drainFsInvalidations(self: *Server, timestamp_ns: u64) void {
        while (self.fs_watcher.nextInvalidation(timestamp_ns)) |invalidation| {
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

fn isPreexecRequest(request: []const u8) bool {
    return std.mem.indexOf(u8, request, "\"kind\":\"preexec\"") != null or
        std.mem.indexOf(u8, request, "\"kind\": \"preexec\"") != null;
}

fn prodGuardAuditPathAlloc(allocator: std.mem.Allocator, home: []const u8) ![]u8 {
    return std.fmt.allocPrint(allocator, "{s}/.local/state/shisa/prod_guard.jsonl", .{home});
}

fn acceptOneThread(server: *Server) !void {
    try server.acceptOne();
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

    const dirty_file = try std.fmt.allocPrint(allocator, "{s}/dirty.txt", .{dir_path});
    defer allocator.free(dirty_file);
    var file = try std.fs.createFileAbsolute(dirty_file, .{});
    try file.writeAll("dirty");
    file.close();

    server.recordFsEvent(dirty_file, 1);
    const dirty = try server.renderResponse(request);
    defer std.heap.page_allocator.free(dirty);
    try std.testing.expect(std.mem.indexOf(u8, dirty, "git:main*> ") != null);
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
