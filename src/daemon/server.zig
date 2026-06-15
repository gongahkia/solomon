const std = @import("std");
const cmd_duration_module = @import("modules/cmd_duration.zig");
const cwd_module = @import("modules/cwd.zig");
const exit_status_module = @import("modules/exit_status.zig");
const jobs_module = @import("modules/jobs.zig");
const json = @import("json.zig");

const header_bytes = 4;
const max_frame_bytes = 1024 * 1024;

const RenderRequest = struct {
    v: u32 = 1,
    cwd: []const u8,
    exit: i32 = 0,
    jobs: u32 = 0,
    duration_ms: u64 = 0,
    shell: []const u8 = "zsh",
    cols: u16 = 80,
    rows: u16 = 24,
};

pub const Server = struct {
    socket_path: []const u8,
    listener: std.net.Server,
    connections: u64 = 0,

    pub fn init(socket_path: []const u8) !Server {
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
        };
    }

    pub fn deinit(self: *Server) void {
        self.listener.deinit();
        std.fs.deleteFileAbsolute(self.socket_path) catch {};
        self.* = undefined;
    }

    pub fn serve(self: *Server, shutdown_requested: *const std.atomic.Value(bool)) !void {
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
        } else {
            const response = try renderResponse(request);
            defer std.heap.page_allocator.free(response);
            try writeFrame(connection.stream.handle, response);
        }
    }
};

fn renderResponse(request_payload: []const u8) ![]u8 {
    var parsed = try std.json.parseFromSlice(RenderRequest, std.heap.page_allocator, request_payload, .{ .ignore_unknown_fields = true });
    defer parsed.deinit();

    const home = std.process.getEnvVarOwned(std.heap.page_allocator, "HOME") catch null;
    defer if (home) |home_path| std.heap.page_allocator.free(home_path);

    const cwd = try cwd_module.render(std.heap.page_allocator, parsed.value.cwd, home, 3);
    defer std.heap.page_allocator.free(cwd);

    const exit_status = try exit_status_module.render(std.heap.page_allocator, parsed.value.exit);
    defer if (exit_status) |segment| std.heap.page_allocator.free(segment);
    const jobs = try jobs_module.render(std.heap.page_allocator, parsed.value.jobs);
    defer if (jobs) |segment| std.heap.page_allocator.free(segment);
    const cmd_duration = try cmd_duration_module.render(std.heap.page_allocator, parsed.value.duration_ms, 1000);
    defer if (cmd_duration) |segment| std.heap.page_allocator.free(segment);

    const prompt = try formatPrompt(std.heap.page_allocator, cwd, exit_status, jobs, cmd_duration);
    defer std.heap.page_allocator.free(prompt);

    const escaped_prompt = try json.escapeAlloc(std.heap.page_allocator, prompt);
    defer std.heap.page_allocator.free(escaped_prompt);

    return std.fmt.allocPrint(std.heap.page_allocator, "{{\"v\":1,\"prompt\":\"{s}\",\"redraw_token\":null}}", .{escaped_prompt});
}

fn formatPrompt(allocator: std.mem.Allocator, cwd: []const u8, exit_status: ?[]const u8, jobs: ?[]const u8, cmd_duration: ?[]const u8) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);

    try out.appendSlice(allocator, cwd);
    if (exit_status) |segment| try appendSegment(allocator, &out, segment);
    if (jobs) |segment| try appendSegment(allocator, &out, segment);
    if (cmd_duration) |segment| try appendSegment(allocator, &out, segment);
    try out.appendSlice(allocator, "> ");

    return out.toOwnedSlice(allocator);
}

fn appendSegment(allocator: std.mem.Allocator, out: *std.ArrayList(u8), segment: []const u8) !void {
    try out.append(allocator, ' ');
    try out.appendSlice(allocator, segment);
}

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

fn acceptOneThread(server: *Server) !void {
    try server.acceptOne();
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
