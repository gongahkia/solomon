const std = @import("std");
const cost_glance_module = @import("modules/cost_glance.zig");

pub const State = struct {
    shutdown: std.atomic.Value(bool) = std.atomic.Value(bool).init(false),
    thread: ?std.Thread = null,
    home: ?[]u8 = null,
    allocator: std.mem.Allocator = std.heap.page_allocator,

    pub fn start(self: *State, allocator: std.mem.Allocator) !void {
        if (self.thread != null) return;
        const home = std.process.getEnvVarOwned(allocator, "HOME") catch |err| switch (err) {
            error.EnvironmentVariableNotFound => null,
            else => return err,
        };
        self.allocator = allocator;
        self.home = home;
        self.shutdown.store(false, .seq_cst);
        self.thread = try std.Thread.spawn(.{}, costRefreshThreadMain, .{self});
    }

    pub fn stop(self: *State) void {
        self.shutdown.store(true, .seq_cst);
        if (self.thread) |thread| {
            thread.join();
            self.thread = null;
        }
        if (self.home) |home| {
            self.allocator.free(home);
            self.home = null;
        }
    }

    fn loop(self: *State) void {
        var next_refresh_ns: u64 = 0;
        const refresh_interval_ns = intervalNs();
        const sleep_ns = @min(refresh_interval_ns, 250 * std.time.ns_per_ms);
        while (!self.shutdown.load(.seq_cst)) {
            const now_ns = nowNs();
            if (now_ns >= next_refresh_ns) {
                _ = cost_glance_module.refreshCacheFromEnvironment(std.heap.page_allocator, self.home, std.time.timestamp()) catch {};
                next_refresh_ns = now_ns + refresh_interval_ns;
            }
            std.Thread.sleep(sleep_ns);
        }
    }
};

pub fn intervalNs() u64 {
    const raw = std.process.getEnvVarOwned(std.heap.page_allocator, "SHISA_COST_REFRESH_INTERVAL_MS") catch return std.time.ns_per_hour;
    defer std.heap.page_allocator.free(raw);
    const ms = std.fmt.parseUnsigned(u64, raw, 10) catch return std.time.ns_per_hour;
    if (ms == 0) return std.time.ns_per_hour;
    return std.math.mul(u64, ms, std.time.ns_per_ms) catch std.time.ns_per_hour;
}

pub fn costRefreshThreadMain(state: *State) void {
    state.loop();
}

fn nowNs() u64 {
    return @intCast(std.time.nanoTimestamp());
}
