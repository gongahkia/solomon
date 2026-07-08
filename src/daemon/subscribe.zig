const std = @import("std");
const json = @import("json.zig");

const default_subscribe_backpressure_limit = 16;
pub const max_subscribe_backpressure_limit = 1024;
const shutdown_poll_ms: i32 = 100;

const Request = struct {
    v: u32 = 1,
    op: []const u8 = "subscribe",
    request_id: []const u8 = "",
    topics: []const []const u8 = &.{},
    backpressure_limit: u16 = default_subscribe_backpressure_limit,
};

const Command = struct {
    op: []const u8 = "",
    kind: []const u8 = "",
};

const TopicRef = struct {
    topic: []u8,
    count: usize,
};

pub const Queue = struct {
    allocator: std.mem.Allocator,
    max_events: usize,
    events: std.ArrayList([]u8) = .empty,
    dropped: u64 = 0,

    pub fn init(allocator: std.mem.Allocator, max_events: usize) Queue {
        return .{
            .allocator = allocator,
            .max_events = @max(max_events, 1),
        };
    }

    pub fn deinit(self: *Queue) void {
        for (self.events.items) |event| self.allocator.free(event);
        self.events.deinit(self.allocator);
        self.* = undefined;
    }

    pub fn pushOwned(self: *Queue, event: []u8) !bool {
        if (self.events.items.len >= self.max_events) {
            self.allocator.free(event);
            self.dropped += 1;
            return false;
        }
        errdefer self.allocator.free(event);
        try self.events.append(self.allocator, event);
        return true;
    }

    pub fn flush(self: *Queue, fd: std.posix.fd_t) !void {
        for (self.events.items) |event| {
            try writeAll(fd, event);
            self.allocator.free(event);
        }
        self.events.clearRetainingCapacity();
    }
};

pub fn handleConnection(allocator: std.mem.Allocator, fd: std.posix.fd_t, request: []const u8, shutdown_requested: ?*const std.atomic.Value(bool)) !void {
    var parsed = try std.json.parseFromSlice(Request, allocator, request, .{ .ignore_unknown_fields = true });
    defer parsed.deinit();

    const topic_refs = try topicRefsAlloc(allocator, parsed.value.topics);
    defer freeTopicRefs(allocator, topic_refs);
    const snapshot = try snapshotAlloc(allocator, parsed.value.request_id, topic_refs);
    defer allocator.free(snapshot);
    try writeAll(fd, snapshot);

    var queue = Queue.init(allocator, backpressureLimit(parsed.value.backpressure_limit));
    defer queue.deinit();
    var sequence: u64 = 0;
    while (true) {
        const maybe_line = line: {
            if (shutdown_requested) |flag| {
                break :line readNdjsonLineUntilShutdownAlloc(allocator, fd, 64 * 1024, flag) catch |err| switch (err) {
                    error.ConnectionClosed => return,
                    else => return err,
                };
            }
            break :line @as(?[]u8, readNdjsonLineAlloc(allocator, fd, 64 * 1024) catch |err| switch (err) {
                error.ConnectionClosed => return,
                else => return err,
            });
        };
        const line = maybe_line orelse return;
        errdefer allocator.free(line);
        defer allocator.free(line);
        if (std.mem.trim(u8, line, " \t\r\n").len == 0) continue;
        if (!commandAllowed(allocator, line)) {
            const readonly = try readonlyErrorAlloc(allocator, parsed.value.request_id, line);
            defer allocator.free(readonly);
            try writeAll(fd, readonly);
            continue;
        }
        sequence += 1;
        const delta_topic = if (topic_refs.len == 0) "subscription" else topic_refs[0].topic;
        const delta = try deltaAlloc(allocator, parsed.value.request_id, delta_topic, sequence);
        _ = try queue.pushOwned(delta);
        const heartbeat = try heartbeatAlloc(allocator, parsed.value.request_id);
        _ = try queue.pushOwned(heartbeat);
        try queue.flush(fd);
    }
}

pub fn backpressureLimit(value: u16) usize {
    if (value == 0) return default_subscribe_backpressure_limit;
    return @min(@as(usize, value), max_subscribe_backpressure_limit);
}

pub fn readNdjsonLineAlloc(allocator: std.mem.Allocator, fd: std.posix.fd_t, max_line_bytes: usize) ![]u8 {
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

pub fn writeAll(fd: std.posix.fd_t, bytes: []const u8) !void {
    var remaining = bytes;
    while (remaining.len > 0) {
        const written = try std.posix.write(fd, remaining);
        remaining = remaining[written..];
    }
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

fn freeTopicRefs(allocator: std.mem.Allocator, refs: []TopicRef) void {
    for (refs) |ref| allocator.free(ref.topic);
    allocator.free(refs);
}

fn commandAllowed(allocator: std.mem.Allocator, line: []const u8) bool {
    var parsed = std.json.parseFromSlice(Command, allocator, line, .{ .ignore_unknown_fields = true }) catch return false;
    defer parsed.deinit();
    return isReadOnlyOp(parsed.value.op);
}

fn isReadOnlyOp(op: []const u8) bool {
    return std.mem.eql(u8, op, "ping") or
        std.mem.eql(u8, op, "subscribe") or
        std.mem.eql(u8, op, "unsubscribe") or
        std.mem.eql(u8, op, "health") or
        std.mem.eql(u8, op, "metrics") or
        std.mem.eql(u8, op, "version");
}

fn commandName(command: Command) []const u8 {
    if (command.op.len != 0) return command.op;
    if (command.kind.len != 0) return command.kind;
    return "unknown";
}

fn refsJsonAlloc(allocator: std.mem.Allocator, refs: []const TopicRef) ![]u8 {
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

fn snapshotAlloc(allocator: std.mem.Allocator, request_id: []const u8, refs: []const TopicRef) ![]u8 {
    const escaped_request_id = try json.escapeAlloc(allocator, request_id);
    defer allocator.free(escaped_request_id);
    const refs_json = try refsJsonAlloc(allocator, refs);
    defer allocator.free(refs_json);
    return std.fmt.allocPrint(
        allocator,
        "{{\"v\":1,\"request_id\":\"{s}\",\"topic\":\"subscription\",\"kind\":\"snapshot\",\"data\":{{\"topics\":{d},\"refs\":{s}}}}}\n",
        .{ escaped_request_id, refs.len, refs_json },
    );
}

fn heartbeatAlloc(allocator: std.mem.Allocator, request_id: []const u8) ![]u8 {
    const escaped_request_id = try json.escapeAlloc(allocator, request_id);
    defer allocator.free(escaped_request_id);
    return std.fmt.allocPrint(
        allocator,
        "{{\"v\":1,\"request_id\":\"{s}\",\"topic\":\"subscription\",\"kind\":\"heartbeat\",\"data\":{{}}}}\n",
        .{escaped_request_id},
    );
}

fn deltaAlloc(allocator: std.mem.Allocator, request_id: []const u8, topic: []const u8, sequence: u64) ![]u8 {
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

fn readonlyErrorAlloc(allocator: std.mem.Allocator, request_id: []const u8, line: []const u8) ![]u8 {
    const escaped_request_id = try json.escapeAlloc(allocator, request_id);
    defer allocator.free(escaped_request_id);
    var parsed = std.json.parseFromSlice(Command, allocator, line, .{ .ignore_unknown_fields = true }) catch null;
    defer if (parsed) |*value| value.deinit();
    const op = if (parsed) |value| commandName(value.value) else "unknown";
    const escaped_op = try json.escapeAlloc(allocator, op);
    defer allocator.free(escaped_op);
    return std.fmt.allocPrint(
        allocator,
        "{{\"v\":1,\"request_id\":\"{s}\",\"topic\":\"subscription\",\"kind\":\"error\",\"data\":{{\"error\":{{\"code\":\"E_READONLY\",\"message\":\"subscribe connection is read-only\",\"context\":{{\"op\":\"{s}\"}}}}}}}}\n",
        .{ escaped_request_id, escaped_op },
    );
}

test "backpressure queue drops over limit" {
    const allocator = std.testing.allocator;
    var queue = Queue.init(allocator, 1);
    defer queue.deinit();
    try std.testing.expect(try queue.pushOwned(try allocator.dupe(u8, "one\n")));
    try std.testing.expect(!try queue.pushOwned(try allocator.dupe(u8, "two\n")));
    try std.testing.expectEqual(@as(u64, 1), queue.dropped);
    try std.testing.expectEqual(@as(usize, default_subscribe_backpressure_limit), backpressureLimit(0));
    try std.testing.expectEqual(@as(usize, max_subscribe_backpressure_limit), backpressureLimit(max_subscribe_backpressure_limit + 1));
}
