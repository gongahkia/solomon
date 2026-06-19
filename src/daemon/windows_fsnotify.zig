const std = @import("std");
const builtin = @import("builtin");

pub const Filter = packed struct(u32) {
    file_name: bool = false,
    dir_name: bool = false,
    attributes: bool = false,
    size: bool = false,
    last_write: bool = false,
    last_access: bool = false,
    creation: bool = false,
    security: bool = false,
    _reserved: u24 = 0,

    pub fn bits(self: Filter) u32 {
        return @bitCast(self);
    }
};

pub const default_filter: Filter = .{
    .file_name = true,
    .dir_name = true,
    .last_write = true,
};

pub const WatchRequest = struct {
    path: []const u8,
    recursive: bool,
    filter: Filter = default_filter,
};

pub const Action = enum(u32) {
    added = 0x00000001,
    removed = 0x00000002,
    modified = 0x00000003,
    renamed_old_name = 0x00000004,
    renamed_new_name = 0x00000005,
    unknown = 0xffffffff,

    fn fromInt(value: u32) Action {
        return switch (value) {
            0x00000001 => .added,
            0x00000002 => .removed,
            0x00000003 => .modified,
            0x00000004 => .renamed_old_name,
            0x00000005 => .renamed_new_name,
            else => .unknown,
        };
    }
};

pub const Event = struct {
    action: Action,
    name_utf16: []const u16,
};

pub const EventList = struct {
    events: []Event,

    pub fn deinit(self: *EventList, allocator: std.mem.Allocator) void {
        for (self.events) |event| allocator.free(event.name_utf16);
        allocator.free(self.events);
        self.* = undefined;
    }
};

pub fn planRequest(path: []const u8, recursive: bool) WatchRequest {
    return .{ .path = path, .recursive = recursive };
}

pub fn parseNotificationsAlloc(allocator: std.mem.Allocator, bytes: []const u8) !EventList {
    var events: std.ArrayList(Event) = .empty;
    errdefer {
        for (events.items) |event| allocator.free(event.name_utf16);
        events.deinit(allocator);
    }

    var offset: usize = 0;
    while (offset < bytes.len) {
        if (bytes.len - offset < 12) return error.TruncatedNotification;
        const next = readU32(bytes[offset..][0..4]);
        const action = readU32(bytes[offset + 4 ..][0..4]);
        const name_len = readU32(bytes[offset + 8 ..][0..4]);
        if (name_len % 2 != 0) return error.InvalidNameLength;
        const name_start = offset + 12;
        const name_end = name_start + name_len;
        if (name_end > bytes.len) return error.TruncatedNotification;
        const name_bytes = bytes[name_start..name_end];
        const name_utf16 = try readUtf16NameAlloc(allocator, name_bytes);
        errdefer allocator.free(name_utf16);
        try events.append(allocator, .{
            .action = Action.fromInt(action),
            .name_utf16 = name_utf16,
        });
        if (next == 0) break;
        if (next < 12 or offset + next <= offset or offset + next > bytes.len) return error.InvalidNextEntryOffset;
        offset += next;
    }

    return .{ .events = try events.toOwnedSlice(allocator) };
}

fn readU32(bytes: []const u8) u32 {
    return std.mem.readInt(u32, bytes[0..4], .little);
}

fn readUtf16NameAlloc(allocator: std.mem.Allocator, bytes: []const u8) ![]u16 {
    const out = try allocator.alloc(u16, bytes.len / 2);
    errdefer allocator.free(out);
    for (out, 0..) |*unit, index| {
        const byte_index = index * 2;
        unit.* = std.mem.readInt(u16, bytes[byte_index..][0..2], .little);
    }
    return out;
}

pub const Runtime = if (builtin.os.tag == .windows) struct {
    const windows = std.os.windows;
    const BOOL = windows.BOOL;
    const DWORD = windows.DWORD;
    const HANDLE = windows.HANDLE;
    const LPOVERLAPPED = windows.LPOVERLAPPED;

    extern "kernel32" fn ReadDirectoryChangesW(
        hDirectory: HANDLE,
        lpBuffer: [*]u8,
        nBufferLength: DWORD,
        bWatchSubtree: BOOL,
        dwNotifyFilter: DWORD,
        lpBytesReturned: ?*DWORD,
        lpOverlapped: ?LPOVERLAPPED,
        lpCompletionRoutine: ?*const anyopaque,
    ) callconv(windows.WINAPI) BOOL;

    pub fn readOnce(directory: HANDLE, buffer: []u8, request: WatchRequest) !u32 {
        var bytes_returned: DWORD = 0;
        const ok = ReadDirectoryChangesW(
            directory,
            buffer.ptr,
            @intCast(buffer.len),
            if (request.recursive) 1 else 0,
            request.filter.bits(),
            &bytes_returned,
            null,
            null,
        );
        if (ok == 0) return error.ReadDirectoryChangesWFailed;
        return bytes_returned;
    }
} else struct {};

test "plans default ReadDirectoryChangesW request" {
    const request = planRequest("C:\\repo", true);
    try std.testing.expectEqualStrings("C:\\repo", request.path);
    try std.testing.expect(request.recursive);
    try std.testing.expectEqual(@as(u32, 0x00000013), request.filter.bits());
}

test "parses file notify information records" {
    const bytes =
        "\x10\x00\x00\x00" ++
        "\x01\x00\x00\x00" ++
        "\x04\x00\x00\x00" ++
        "a\x00b\x00" ++
        "\x00\x00\x00\x00" ++
        "\x03\x00\x00\x00" ++
        "\x04\x00\x00\x00" ++
        "c\x00d\x00";
    var parsed = try parseNotificationsAlloc(std.testing.allocator, bytes);
    defer parsed.deinit(std.testing.allocator);
    try std.testing.expectEqual(@as(usize, 2), parsed.events.len);
    try std.testing.expectEqual(Action.added, parsed.events[0].action);
    try std.testing.expectEqualSlices(u16, &.{ 'a', 'b' }, parsed.events[0].name_utf16);
    try std.testing.expectEqual(Action.modified, parsed.events[1].action);
    try std.testing.expectEqualSlices(u16, &.{ 'c', 'd' }, parsed.events[1].name_utf16);
}

test "rejects malformed notification records" {
    try std.testing.expectError(error.TruncatedNotification, parseNotificationsAlloc(std.testing.allocator, "\x00"));
    try std.testing.expectError(error.InvalidNameLength, parseNotificationsAlloc(std.testing.allocator, "\x00\x00\x00\x00\x01\x00\x00\x00\x03\x00\x00\x00abc"));
}
