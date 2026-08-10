const std = @import("std");
const builtin = @import("builtin");

pub const Backend = enum {
    fsevents,
    inotify,
    windows,
    unsupported,
};

pub const default_debounce_ms: u64 = 50;
/// Native registrations are intentionally bounded. A prompt daemon must not
/// consume the user's complete inotify quota merely because it has visited a
/// large number of repositories.
pub const default_native_watch_budget: usize = 8192;
pub const degraded_sweep_interval_ns: u64 = std.time.ns_per_s;

pub const WatchPath = struct {
    path: []const u8,
    recursive: bool = false,
};

pub const Scope = struct {
    module_id: []const u8,
    cwd: []const u8,
    paths: []const WatchPath,
    debounce_ms: u64 = default_debounce_ms,
};

pub const Invalidation = struct {
    module_id: []const u8,
    cwd: []const u8,
};

pub const InotifyLimitStatus = struct {
    watched_paths: usize,
    max_user_watches: ?u64,
    within_limit: ?bool,
    remaining: ?u64,
};

const OwnedPath = struct {
    path: []u8,
    recursive: bool,
};

const Registration = struct {
    module_id: []u8,
    cwd: []u8,
    paths: []OwnedPath,
    debounce_ns: u64,
    pending: bool = false,
    last_event_ns: u64 = 0,

    fn deinit(self: *Registration, allocator: std.mem.Allocator) void {
        allocator.free(self.module_id);
        allocator.free(self.cwd);
        for (self.paths) |owned| allocator.free(owned.path);
        allocator.free(self.paths);
        self.* = undefined;
    }
};

pub const Watcher = struct {
    allocator: std.mem.Allocator,
    backend: Backend,
    registrations: std.ArrayList(Registration),
    native: Native = .{},

    pub fn init(allocator: std.mem.Allocator) Watcher {
        return .{
            .allocator = allocator,
            .backend = selectBackend(builtin.os.tag),
            .registrations = .empty,
        };
    }

    pub fn deinit(self: *Watcher) void {
        self.native.deinit(self.allocator);
        for (self.registrations.items) |*registration| registration.deinit(self.allocator);
        self.registrations.deinit(self.allocator);
        self.* = undefined;
    }

    pub fn watch(self: *Watcher, scope: Scope) !void {
        if (self.scopeIndex(scope.module_id, scope.cwd)) |index| {
            try self.appendScopePaths(&self.registrations.items[index], scope.paths);
            self.installNativeScope(scope) catch |err| switch (err) {
                error.WatchBudgetExceeded, error.WatchUnavailable => self.native.degraded = true,
                else => return err,
            };
            return;
        }

        const module_id = try self.allocator.dupe(u8, scope.module_id);
        errdefer self.allocator.free(module_id);
        const cwd = try self.allocator.dupe(u8, scope.cwd);
        errdefer self.allocator.free(cwd);
        const paths = try self.allocator.alloc(OwnedPath, scope.paths.len);
        errdefer self.allocator.free(paths);

        var initialized: usize = 0;
        errdefer {
            for (paths[0..initialized]) |owned| self.allocator.free(owned.path);
        }

        for (scope.paths, 0..) |path, index| {
            paths[index] = .{
                .path = try self.allocator.dupe(u8, path.path),
                .recursive = path.recursive,
            };
            initialized += 1;
        }

        try self.registrations.append(self.allocator, .{
            .module_id = module_id,
            .cwd = cwd,
            .paths = paths,
            .debounce_ns = scope.debounce_ms * std.time.ns_per_ms,
        });
        self.installNativeScope(scope) catch |err| switch (err) {
            // A native watcher is an invalidation optimization, never a
            // reason to reject rendering. Pressure is reported through the
            // health state and handled by conservative periodic invalidation.
            error.WatchBudgetExceeded, error.WatchUnavailable => self.native.degraded = true,
            else => return err,
        };
    }

    pub fn recordEvent(self: *Watcher, path: []const u8, timestamp_ns: u64) void {
        for (self.registrations.items) |*registration| {
            if (registrationMatches(registration.*, path)) {
                registration.pending = true;
                registration.last_event_ns = timestamp_ns;
            }
        }
    }

    /// Pump the platform event source. This remains separate from
    /// `recordEvent` so unit tests can inject deterministic events without a
    /// host watcher.
    pub fn pump(self: *Watcher, timestamp_ns: u64) void {
        switch (self.backend) {
            .inotify => self.pumpInotify(timestamp_ns),
            .fsevents => self.pumpFsevents(timestamp_ns),
            else => {},
        }
        if (self.native.degraded and timestamp_ns -| self.native.last_degraded_sweep_ns >= degraded_sweep_interval_ns) {
            self.native.last_degraded_sweep_ns = timestamp_ns;
            self.markAllPending(timestamp_ns);
        }
    }

    pub fn nativeFd(self: *const Watcher) ?std.posix.fd_t {
        return if (self.native.inotify_fd) |fd| fd else null;
    }

    pub fn isDegraded(self: Watcher) bool {
        return self.native.degraded;
    }

    pub fn overflowCount(self: Watcher) u64 {
        return self.native.overflows;
    }

    pub fn nativeWatchCount(self: Watcher) usize {
        return self.native.nativePathCount();
    }

    pub fn nextInvalidation(self: *Watcher, timestamp_ns: u64) ?Invalidation {
        for (self.registrations.items) |*registration| {
            if (!registration.pending) continue;
            if (timestamp_ns < registration.last_event_ns) continue;
            if (timestamp_ns - registration.last_event_ns < registration.debounce_ns) continue;
            registration.pending = false;
            return .{
                .module_id = registration.module_id,
                .cwd = registration.cwd,
            };
        }
        return null;
    }

    pub fn count(self: Watcher) usize {
        return self.registrations.items.len;
    }

    pub fn watchedPathCount(self: Watcher) usize {
        var total: usize = 0;
        for (self.registrations.items) |registration| total += registration.paths.len;
        return total;
    }

    pub fn inotifyLimitStatus(self: Watcher, max_user_watches: ?u64) InotifyLimitStatus {
        return inotifyLimitStatusForCount(self.watchedPathCount(), max_user_watches);
    }

    pub fn hasScope(self: Watcher, module_id: []const u8, cwd: []const u8) bool {
        return self.scopeIndex(module_id, cwd) != null;
    }

    fn scopeIndex(self: Watcher, module_id: []const u8, cwd: []const u8) ?usize {
        for (self.registrations.items, 0..) |registration, index| {
            if (std.mem.eql(u8, registration.module_id, module_id) and std.mem.eql(u8, registration.cwd, cwd)) return index;
        }
        return null;
    }

    fn appendScopePaths(self: *Watcher, registration: *Registration, paths: []const WatchPath) !void {
        var additional: usize = 0;
        for (paths) |candidate| {
            var exists = false;
            for (registration.paths) |existing| {
                if (existing.recursive == candidate.recursive and std.mem.eql(u8, existing.path, candidate.path)) {
                    exists = true;
                    break;
                }
            }
            if (!exists) additional += 1;
        }
        if (additional == 0) return;
        const combined = try self.allocator.alloc(OwnedPath, registration.paths.len + additional);
        @memcpy(combined[0..registration.paths.len], registration.paths);
        var initialized = registration.paths.len;
        errdefer {
            for (combined[registration.paths.len..initialized]) |owned| self.allocator.free(owned.path);
            self.allocator.free(combined);
        }
        for (paths) |candidate| {
            var exists = false;
            for (registration.paths) |existing| {
                if (existing.recursive == candidate.recursive and std.mem.eql(u8, existing.path, candidate.path)) {
                    exists = true;
                    break;
                }
            }
            if (exists) continue;
            combined[initialized] = .{
                .path = try self.allocator.dupe(u8, candidate.path),
                .recursive = candidate.recursive,
            };
            initialized += 1;
        }
        self.allocator.free(registration.paths);
        registration.paths = combined;
    }

    fn installNativeScope(self: *Watcher, scope: Scope) !void {
        switch (self.backend) {
            .inotify => {
                try self.ensureInotify();
                for (scope.paths) |path| {
                    if (path.recursive) {
                        try self.addInotifyTree(path.path);
                    } else {
                        // Watch the containing directory rather than the file so an
                        // editor's atomic rename still produces a useful event.
                        const parent = std.fs.path.dirname(path.path) orelse path.path;
                        try self.addInotifyDirectory(parent);
                    }
                }
            },
            .fsevents => try self.addFseventScope(scope),
            else => return,
        }
    }

    fn addFseventScope(self: *Watcher, scope: Scope) !void {
        if (builtin.os.tag != .macos) return error.WatchUnavailable;
        if (scope.paths.len == 0) return;
        var new_paths: std.ArrayList(WatchPath) = .empty;
        defer new_paths.deinit(self.allocator);
        for (scope.paths) |candidate| {
            var exists = false;
            for (self.native.mac_paths.items) |existing| {
                if (std.mem.eql(u8, existing, candidate.path)) {
                    exists = true;
                    break;
                }
            }
            if (!exists) {
                for (new_paths.items) |existing| {
                    if (std.mem.eql(u8, existing.path, candidate.path)) {
                        exists = true;
                        break;
                    }
                }
            }
            if (!exists) try new_paths.append(self.allocator, candidate);
        }
        if (new_paths.items.len == 0) return;
        if (self.native.nativePathCount() + new_paths.items.len > default_native_watch_budget) return error.WatchBudgetExceeded;
        try self.native.mac_paths.ensureTotalCapacity(self.allocator, self.native.mac_paths.items.len + new_paths.items.len);
        const mac_watch = try MacWatch.init(self.allocator, new_paths.items);
        errdefer mac_watch.deinit();
        try self.native.mac_watches.append(self.allocator, mac_watch);
        errdefer _ = self.native.mac_watches.pop();
        const mac_path_start = self.native.mac_paths.items.len;
        errdefer {
            for (self.native.mac_paths.items[mac_path_start..]) |path| self.allocator.free(path);
            self.native.mac_paths.shrinkRetainingCapacity(mac_path_start);
        }
        for (new_paths.items) |path| {
            const owned_path = try self.allocator.dupe(u8, path.path);
            self.native.mac_paths.appendAssumeCapacity(owned_path);
        }
    }

    fn pumpFsevents(self: *Watcher, timestamp_ns: u64) void {
        for (self.native.mac_watches.items) |mac_watch| {
            const batch = mac_watch.takeBatch();
            defer batch.deinit(self.allocator);
            if (batch.overflowed) {
                self.native.overflows += 1;
                self.markAllPending(timestamp_ns);
            }
            for (batch.paths.items) |path| self.recordEvent(path, timestamp_ns);
        }
    }

    fn ensureInotify(self: *Watcher) !void {
        if (builtin.os.tag != .linux) return error.WatchUnavailable;
        if (self.native.inotify_fd != null) return;
        const fd = linuxInotifyInit1(inotify_nonblock | inotify_cloexec);
        if (fd < 0) return error.WatchUnavailable;
        self.native.inotify_fd = fd;
    }

    fn addInotifyTree(self: *Watcher, root: []const u8) !void {
        try self.addInotifyDirectory(root);
        var dir = std.fs.openDirAbsolute(root, .{ .iterate = true }) catch |err| switch (err) {
            error.FileNotFound, error.NotDir, error.AccessDenied => return,
            else => return err,
        };
        defer dir.close();
        var walker = try dir.walk(self.allocator);
        defer walker.deinit();
        while (try walker.next()) |entry| {
            if (entry.kind != .directory) continue;
            const child = try std.fs.path.join(self.allocator, &.{ root, entry.path });
            defer self.allocator.free(child);
            try self.addInotifyDirectory(child);
        }
    }

    fn addInotifyDirectory(self: *Watcher, path: []const u8) !void {
        if (self.native.pathIndex(path) != null) return;
        if (self.native.paths.items.len >= default_native_watch_budget) return error.WatchBudgetExceeded;
        const fd = self.native.inotify_fd orelse return error.WatchUnavailable;
        const wd = linuxInotifyAddWatch(fd, path, inotify_watch_mask);
        if (wd < 0) return error.WatchUnavailable;
        try self.native.paths.append(self.allocator, .{
            .wd = wd,
            .path = try self.allocator.dupe(u8, path),
        });
    }

    fn pumpInotify(self: *Watcher, timestamp_ns: u64) void {
        const fd = self.native.inotify_fd orelse return;
        var bytes: [16 * 1024]u8 = undefined;
        while (true) {
            const read_len = std.posix.read(fd, &bytes) catch |err| switch (err) {
                error.WouldBlock => return,
                else => {
                    self.native.degraded = true;
                    return;
                },
            };
            if (read_len == 0) return;
            self.consumeInotifyBytes(bytes[0..read_len], timestamp_ns);
        }
    }

    fn consumeInotifyBytes(self: *Watcher, bytes: []const u8, timestamp_ns: u64) void {
        var offset: usize = 0;
        while (offset + inotify_event_header_bytes <= bytes.len) {
            const endian = builtin.cpu.arch.endian();
            const wd = std.mem.readInt(i32, bytes[offset..][0..4], endian);
            const mask = std.mem.readInt(u32, bytes[offset + 4 ..][0..4], endian);
            const name_len: usize = std.mem.readInt(u32, bytes[offset + 12 ..][0..4], endian);
            const total = inotify_event_header_bytes + name_len;
            if (offset + total > bytes.len) {
                self.native.degraded = true;
                return;
            }
            if ((mask & inotify_q_overflow) != 0) {
                self.native.overflows += 1;
                self.markAllPending(timestamp_ns);
            } else if (self.native.pathForWd(wd)) |base| {
                const raw_name = bytes[offset + inotify_event_header_bytes .. offset + total];
                const name = std.mem.sliceTo(raw_name, 0);
                const event_path = if (name.len == 0)
                    self.allocator.dupe(u8, base)
                else
                    std.fs.path.join(self.allocator, &.{ base, name });
                if (event_path) |owned_path| {
                    defer self.allocator.free(owned_path);
                    self.recordEvent(owned_path, timestamp_ns);
                    if ((mask & inotify_isdir) != 0 and (mask & (inotify_create | inotify_moved_to)) != 0 and self.isRecursivePath(owned_path)) {
                        self.addInotifyTree(owned_path) catch self.markDegraded();
                    }
                } else |_| self.markDegraded();
            }
            offset += total;
        }
    }

    fn isRecursivePath(self: Watcher, path: []const u8) bool {
        for (self.registrations.items) |registration| {
            for (registration.paths) |watch_path| {
                if (watch_path.recursive and pathMatches(watch_path, path)) return true;
            }
        }
        return false;
    }

    fn markAllPending(self: *Watcher, timestamp_ns: u64) void {
        for (self.registrations.items) |*registration| {
            registration.pending = true;
            registration.last_event_ns = timestamp_ns;
        }
    }

    fn markDegraded(self: *Watcher) void {
        self.native.degraded = true;
    }
};

const NativePath = struct {
    wd: i32,
    path: []u8,
};

const FSEventStreamRef = ?*opaque {};
const CFAllocatorRef = ?*const opaque {};
const CFArrayRef = ?*const opaque {};
const CFMutableArrayRef = ?*opaque {};
const CFStringRef = ?*const opaque {};
const dispatch_queue_t = ?*opaque {};
const FSEventStreamCallback = *const fn (FSEventStreamRef, ?*anyopaque, usize, ?*anyopaque, [*]const u32, [*]const u64) callconv(.c) void;
const FSEventStreamContext = extern struct {
    version: isize = 0,
    info: ?*anyopaque = null,
    retain: ?*const anyopaque = null,
    release: ?*const anyopaque = null,
    copy_description: ?*const anyopaque = null,
};

const MacBatch = struct {
    paths: std.ArrayList([]u8) = .empty,
    overflowed: bool = false,

    fn deinit(self: *const MacBatch, allocator: std.mem.Allocator) void {
        for (self.paths.items) |path| allocator.free(path);
        var paths = self.paths;
        paths.deinit(allocator);
    }
};

const MacWatch = struct {
    allocator: std.mem.Allocator,
    stream: FSEventStreamRef,
    mutex: std.Thread.Mutex = .{},
    paths: std.ArrayList([]u8) = .empty,
    overflowed: bool = false,

    fn init(allocator: std.mem.Allocator, watch_paths: []const WatchPath) !*MacWatch {
        if (builtin.os.tag != .macos) return error.WatchUnavailable;
        const watch = try allocator.create(MacWatch);
        errdefer allocator.destroy(watch);
        watch.* = .{
            .allocator = allocator,
            .stream = null,
        };
        const array = try createFseventPathArray(allocator, watch_paths);
        defer if (array) |value| cfRelease(value);
        var context = FSEventStreamContext{ .info = @ptrCast(watch) };
        const stream = FSEventStreamCreate(null, macFseventCallback, &context, array, fsevent_since_now, 0.05, fsevent_file_events);
        if (stream == null) return error.WatchUnavailable;
        watch.stream = stream;
        const queue = dispatch_get_global_queue(0, 0) orelse return error.WatchUnavailable;
        FSEventStreamSetDispatchQueue(stream, queue);
        if (!FSEventStreamStart(stream)) return error.WatchUnavailable;
        return watch;
    }

    fn deinit(self: *MacWatch) void {
        if (comptime builtin.os.tag == .macos) {
            if (self.stream) |stream| {
                FSEventStreamStop(stream);
                FSEventStreamInvalidate(stream);
                FSEventStreamRelease(stream);
            }
        }
        for (self.paths.items) |path| self.allocator.free(path);
        self.paths.deinit(self.allocator);
        self.allocator.destroy(self);
    }

    fn takeBatch(self: *MacWatch) MacBatch {
        self.mutex.lock();
        defer self.mutex.unlock();
        const paths = self.paths;
        self.paths = .empty;
        const overflowed = self.overflowed;
        self.overflowed = false;
        return .{ .paths = paths, .overflowed = overflowed };
    }

    fn appendEvent(self: *MacWatch, path: []const u8, flags: u32) void {
        self.mutex.lock();
        defer self.mutex.unlock();
        if ((flags & fsevent_must_scan_mask) != 0) self.overflowed = true;
        const owned = self.allocator.dupe(u8, path) catch {
            self.overflowed = true;
            return;
        };
        self.paths.append(self.allocator, owned) catch {
            self.allocator.free(owned);
            self.overflowed = true;
        };
    }
};

const Native = struct {
    inotify_fd: ?std.posix.fd_t = null,
    paths: std.ArrayList(NativePath) = .empty,
    mac_watches: std.ArrayList(*MacWatch) = .empty,
    mac_paths: std.ArrayList([]u8) = .empty,
    degraded: bool = false,
    overflows: u64 = 0,
    last_degraded_sweep_ns: u64 = 0,

    fn deinit(self: *Native, allocator: std.mem.Allocator) void {
        if (self.inotify_fd) |fd| std.posix.close(fd);
        for (self.paths.items) |item| allocator.free(item.path);
        self.paths.deinit(allocator);
        for (self.mac_watches.items) |mac_watch| mac_watch.deinit();
        self.mac_watches.deinit(allocator);
        for (self.mac_paths.items) |path| allocator.free(path);
        self.mac_paths.deinit(allocator);
        self.* = .{};
    }

    fn nativePathCount(self: Native) usize {
        return self.paths.items.len + self.mac_paths.items.len;
    }

    fn pathIndex(self: Native, path: []const u8) ?usize {
        for (self.paths.items, 0..) |item, index| {
            if (std.mem.eql(u8, item.path, path)) return index;
        }
        return null;
    }

    fn pathForWd(self: Native, wd: i32) ?[]const u8 {
        for (self.paths.items) |item| if (item.wd == wd) return item.path;
        return null;
    }
};

const inotify_nonblock: c_int = 0x0000_0800;
const inotify_cloexec: c_int = 0x0008_0000;
const inotify_create: u32 = 0x0000_0100;
const inotify_moved_to: u32 = 0x0000_0080;
const inotify_isdir: u32 = 0x4000_0000;
const inotify_q_overflow: u32 = 0x0000_4000;
const inotify_watch_mask: u32 = 0x0000_0fce; // data, metadata, rename, delete, and self events
const inotify_event_header_bytes: usize = 16;

const kCFStringEncodingUTF8: u32 = 0x0800_0100;
const fsevent_since_now: u64 = 0xffff_ffff_ffff_ffff;
const fsevent_file_events: u32 = 0x0000_0010;
const fsevent_must_scan_subdirs: u32 = 0x0000_0001;
const fsevent_user_dropped: u32 = 0x0000_0002;
const fsevent_kernel_dropped: u32 = 0x0000_0004;
const fsevent_root_changed: u32 = 0x0000_0020;
const fsevent_must_scan_mask = fsevent_must_scan_subdirs | fsevent_user_dropped | fsevent_kernel_dropped | fsevent_root_changed;

extern "c" fn CFStringCreateWithCString(allocator: CFAllocatorRef, c_str: [*:0]const u8, encoding: u32) CFStringRef;
extern "c" fn CFArrayCreateMutable(allocator: CFAllocatorRef, capacity: isize, callbacks: ?*const anyopaque) CFMutableArrayRef;
extern "c" fn CFArrayAppendValue(array: CFMutableArrayRef, value: ?*const anyopaque) void;
extern "c" fn CFRelease(value: ?*const anyopaque) void;
extern "c" var kCFTypeArrayCallBacks: anyopaque;
extern "c" fn FSEventStreamCreate(allocator: CFAllocatorRef, callback: FSEventStreamCallback, context: *FSEventStreamContext, paths_to_watch: CFArrayRef, since_when: u64, latency: f64, flags: u32) FSEventStreamRef;
extern "c" fn FSEventStreamSetDispatchQueue(stream: FSEventStreamRef, queue: dispatch_queue_t) void;
extern "c" fn FSEventStreamStart(stream: FSEventStreamRef) bool;
extern "c" fn FSEventStreamStop(stream: FSEventStreamRef) void;
extern "c" fn FSEventStreamInvalidate(stream: FSEventStreamRef) void;
extern "c" fn FSEventStreamRelease(stream: FSEventStreamRef) void;
extern "c" fn dispatch_get_global_queue(identifier: isize, flags: usize) dispatch_queue_t;

extern "c" fn inotify_init1(flags: c_int) c_int;
extern "c" fn inotify_add_watch(fd: c_int, pathname: [*:0]const u8, mask: u32) c_int;

fn linuxInotifyInit1(flags: c_int) c_int {
    if (builtin.os.tag != .linux) return -1;
    return inotify_init1(flags);
}

fn linuxInotifyAddWatch(fd: std.posix.fd_t, path: []const u8, mask: u32) i32 {
    if (builtin.os.tag != .linux or std.mem.indexOfScalar(u8, path, 0) != null) return -1;
    var terminated: [std.fs.max_path_bytes:0]u8 = undefined;
    if (path.len >= terminated.len) return -1;
    @memcpy(terminated[0..path.len], path);
    terminated[path.len] = 0;
    return inotify_add_watch(fd, &terminated, mask);
}

fn createFseventPathArray(allocator: std.mem.Allocator, paths: []const WatchPath) !CFArrayRef {
    if (builtin.os.tag != .macos) return error.WatchUnavailable;
    const array = CFArrayCreateMutable(null, @intCast(paths.len), @ptrCast(&kCFTypeArrayCallBacks)) orelse return error.WatchUnavailable;
    errdefer cfRelease(array);
    for (paths) |path| {
        const terminated = try allocator.dupeZ(u8, path.path);
        defer allocator.free(terminated);
        const string = CFStringCreateWithCString(null, terminated.ptr, kCFStringEncodingUTF8) orelse return error.WatchUnavailable;
        defer cfRelease(string);
        CFArrayAppendValue(array, @ptrCast(string));
    }
    return @ptrCast(array);
}

fn cfRelease(value: anytype) void {
    const pointer: ?*const anyopaque = @ptrCast(value);
    CFRelease(pointer);
}

fn macFseventCallback(_: FSEventStreamRef, info: ?*anyopaque, event_count: usize, event_paths: ?*anyopaque, event_flags: [*]const u32, _: [*]const u64) callconv(.c) void {
    const raw_watch = info orelse return;
    const raw_paths = event_paths orelse return;
    const watch: *MacWatch = @ptrCast(@alignCast(raw_watch));
    const paths: [*]const ?[*:0]const u8 = @ptrCast(@alignCast(raw_paths));
    for (0..event_count) |index| {
        const path = paths[index] orelse {
            watch.appendEvent("", event_flags[index] | fsevent_must_scan_subdirs);
            continue;
        };
        watch.appendEvent(std.mem.sliceTo(path, 0), event_flags[index]);
    }
}

pub fn selectBackend(os_tag: std.Target.Os.Tag) Backend {
    return switch (os_tag) {
        .macos => .fsevents,
        .linux => .inotify,
        .windows => .windows,
        else => .unsupported,
    };
}

pub fn readLinuxMaxUserWatches(allocator: std.mem.Allocator) !?u64 {
    if (builtin.os.tag != .linux) return null;
    const contents = std.fs.cwd().readFileAlloc(allocator, "/proc/sys/fs/inotify/max_user_watches", 128) catch |err| switch (err) {
        error.FileNotFound, error.AccessDenied => return null,
        else => return err,
    };
    defer allocator.free(contents);
    return try parseUnsigned(contents);
}

pub fn inotifyLimitStatusForCount(watched_paths: usize, max_user_watches: ?u64) InotifyLimitStatus {
    const watched: u64 = @intCast(watched_paths);
    const limit = max_user_watches orelse return .{
        .watched_paths = watched_paths,
        .max_user_watches = null,
        .within_limit = null,
        .remaining = null,
    };
    return .{
        .watched_paths = watched_paths,
        .max_user_watches = limit,
        .within_limit = watched <= limit,
        .remaining = if (watched <= limit) limit - watched else 0,
    };
}

fn parseUnsigned(contents: []const u8) !u64 {
    const trimmed = std.mem.trim(u8, contents, " \t\r\n");
    if (trimmed.len == 0) return error.InvalidUnsigned;
    return std.fmt.parseInt(u64, trimmed, 10);
}

fn registrationMatches(registration: Registration, path: []const u8) bool {
    for (registration.paths) |watch_path| {
        if (pathMatches(watch_path, path)) return true;
    }
    return false;
}

fn pathMatches(watch_path: OwnedPath, path: []const u8) bool {
    if (std.mem.eql(u8, watch_path.path, path)) return true;
    if (!watch_path.recursive) return false;
    if (!std.mem.startsWith(u8, path, watch_path.path)) return false;
    if (path.len == watch_path.path.len) return true;
    return isPathSeparator(path[watch_path.path.len]);
}

fn isPathSeparator(byte: u8) bool {
    return byte == '/' or byte == '\\';
}

test "selects platform backends" {
    try std.testing.expectEqual(Backend.fsevents, selectBackend(.macos));
    try std.testing.expectEqual(Backend.inotify, selectBackend(.linux));
    try std.testing.expectEqual(Backend.windows, selectBackend(.windows));
    try std.testing.expectEqual(Backend.unsupported, selectBackend(.freebsd));
}

test "owns watched scope paths" {
    var watcher = Watcher.init(std.testing.allocator);
    defer watcher.deinit();

    const paths = [_]WatchPath{
        .{ .path = "/repo/.git/HEAD" },
        .{ .path = "/repo/.git/index" },
    };
    try watcher.watch(.{
        .module_id = "git_branch",
        .cwd = "/repo",
        .paths = &paths,
    });

    try std.testing.expectEqual(@as(usize, 1), watcher.count());
    try std.testing.expectEqualStrings("git_branch", watcher.registrations.items[0].module_id);
    try std.testing.expectEqualStrings("/repo/.git/index", watcher.registrations.items[0].paths[1].path);
}

test "deduplicates watched scopes" {
    var watcher = Watcher.init(std.testing.allocator);
    defer watcher.deinit();

    const paths = [_]WatchPath{.{ .path = "/repo/.git/HEAD" }};
    try watcher.watch(.{
        .module_id = "git_branch",
        .cwd = "/repo",
        .paths = &paths,
    });
    try watcher.watch(.{
        .module_id = "git_branch",
        .cwd = "/repo",
        .paths = &paths,
    });

    try std.testing.expect(watcher.hasScope("git_branch", "/repo"));
    try std.testing.expectEqual(@as(usize, 1), watcher.count());
}

test "counts watched paths" {
    var watcher = Watcher.init(std.testing.allocator);
    defer watcher.deinit();

    const paths = [_]WatchPath{
        .{ .path = "/repo/.git/HEAD" },
        .{ .path = "/repo/.git/index" },
    };
    try watcher.watch(.{
        .module_id = "git_branch",
        .cwd = "/repo",
        .paths = &paths,
    });

    try std.testing.expectEqual(@as(usize, 2), watcher.watchedPathCount());
}

test "reports inotify limit status" {
    const ok = inotifyLimitStatusForCount(8, 16);
    try std.testing.expectEqual(@as(usize, 8), ok.watched_paths);
    try std.testing.expectEqual(@as(u64, 16), ok.max_user_watches.?);
    try std.testing.expect(ok.within_limit.?);
    try std.testing.expectEqual(@as(u64, 8), ok.remaining.?);

    const exceeded = inotifyLimitStatusForCount(17, 16);
    try std.testing.expect(!exceeded.within_limit.?);
    try std.testing.expectEqual(@as(u64, 0), exceeded.remaining.?);

    const unknown = inotifyLimitStatusForCount(4, null);
    try std.testing.expect(unknown.within_limit == null);
}

test "linux inotify delivers recursive filesystem changes" {
    if (builtin.os.tag != .linux) return error.SkipZigTest;

    var tmp = std.testing.tmpDir(.{});
    defer tmp.cleanup();
    try tmp.dir.makePath("repo/nested");
    const root = try tmp.dir.realpathAlloc(std.testing.allocator, "repo");
    defer std.testing.allocator.free(root);
    const changed = try std.fs.path.join(std.testing.allocator, &.{ root, "nested", "tracked" });
    defer std.testing.allocator.free(changed);

    var watcher = Watcher.init(std.testing.allocator);
    defer watcher.deinit();
    try watcher.watch(.{
        .module_id = "git_branch",
        .cwd = root,
        .paths = &.{.{ .path = root, .recursive = true }},
        .debounce_ms = 0,
    });
    if (watcher.nativeFd() == null) return error.SkipZigTest;

    try tmp.dir.writeFile(.{ .sub_path = "repo/nested/tracked", .data = "changed" });
    const deadline = monotonicNowNs() + 500 * std.time.ns_per_ms;
    while (monotonicNowNs() < deadline) {
        watcher.pump(monotonicNowNs());
        if (watcher.nextInvalidation(monotonicNowNs())) |invalidation| {
            try std.testing.expectEqualStrings("git_branch", invalidation.module_id);
            try std.testing.expectEqualStrings(root, invalidation.cwd);
            return;
        }
        std.Thread.sleep(std.time.ns_per_ms);
    }
    return error.TestExpectedEqual;
}

fn monotonicNowNs() u64 {
    return @intCast(std.time.nanoTimestamp());
}

test "parses trimmed unsigned sysctl values" {
    try std.testing.expectEqual(@as(u64, 524288), try parseUnsigned("524288\n"));
    try std.testing.expectError(error.InvalidCharacter, parseUnsigned("nope\n"));
}

test "debounces invalidations by scope" {
    var watcher = Watcher.init(std.testing.allocator);
    defer watcher.deinit();

    const paths = [_]WatchPath{
        .{ .path = "/repo/.git/HEAD" },
        .{ .path = "/repo/.git/index" },
    };
    try watcher.watch(.{
        .module_id = "git_branch",
        .cwd = "/repo",
        .paths = &paths,
        .debounce_ms = 50,
    });

    watcher.recordEvent("/repo/.git/index", 1 * std.time.ns_per_ms);
    try std.testing.expect(watcher.nextInvalidation(40 * std.time.ns_per_ms) == null);
    watcher.recordEvent("/repo/.git/HEAD", 45 * std.time.ns_per_ms);
    try std.testing.expect(watcher.nextInvalidation(90 * std.time.ns_per_ms) == null);

    const invalidation = watcher.nextInvalidation(96 * std.time.ns_per_ms).?;
    try std.testing.expectEqualStrings("git_branch", invalidation.module_id);
    try std.testing.expectEqualStrings("/repo", invalidation.cwd);
    try std.testing.expect(watcher.nextInvalidation(150 * std.time.ns_per_ms) == null);
}

test "recursive watches match only descendants" {
    var watcher = Watcher.init(std.testing.allocator);
    defer watcher.deinit();

    const paths = [_]WatchPath{.{ .path = "/repo", .recursive = true }};
    try watcher.watch(.{
        .module_id = "git_branch",
        .cwd = "/repo",
        .paths = &paths,
        .debounce_ms = 0,
    });

    watcher.recordEvent("/repo-other/file", 1);
    try std.testing.expect(watcher.nextInvalidation(1) == null);
    watcher.recordEvent("/repo/src/main.zig", 2);
    try std.testing.expect(watcher.nextInvalidation(2) != null);
}

test "exact watches ignore child paths" {
    var watcher = Watcher.init(std.testing.allocator);
    defer watcher.deinit();

    const paths = [_]WatchPath{.{ .path = "/repo/.git/HEAD" }};
    try watcher.watch(.{
        .module_id = "git_branch",
        .cwd = "/repo",
        .paths = &paths,
        .debounce_ms = 0,
    });

    watcher.recordEvent("/repo/.git/HEAD.lock", 1);
    try std.testing.expect(watcher.nextInvalidation(1) == null);
    watcher.recordEvent("/repo/.git/HEAD", 2);
    try std.testing.expect(watcher.nextInvalidation(2) != null);
}
