const std = @import("std");
const builtin = @import("builtin");
const win = std.os.windows;

const token_query: win.DWORD = 0x0008;
const token_groups: win.DWORD = 2;
const se_group_logon_id: win.DWORD = 0xc0000000;
const sddl_revision_1: win.DWORD = 1;

const SID_AND_ATTRIBUTES = extern struct {
    Sid: *anyopaque,
    Attributes: win.DWORD,
};

const TOKEN_GROUPS = extern struct {
    GroupCount: win.DWORD,
    Groups: [1]SID_AND_ATTRIBUTES,
};

extern "advapi32" fn OpenProcessToken(ProcessHandle: win.HANDLE, DesiredAccess: win.DWORD, TokenHandle: *win.HANDLE) callconv(.winapi) win.BOOL;
extern "advapi32" fn GetTokenInformation(TokenHandle: win.HANDLE, TokenInformationClass: win.DWORD, TokenInformation: ?*anyopaque, TokenInformationLength: win.DWORD, ReturnLength: *win.DWORD) callconv(.winapi) win.BOOL;
extern "advapi32" fn ConvertSidToStringSidW(Sid: *anyopaque, StringSid: *win.LPWSTR) callconv(.winapi) win.BOOL;
extern "advapi32" fn ConvertStringSecurityDescriptorToSecurityDescriptorW(StringSecurityDescriptor: win.LPCWSTR, StringSDRevision: win.DWORD, SecurityDescriptor: *?*anyopaque, SecurityDescriptorSize: ?*win.DWORD) callconv(.winapi) win.BOOL;
extern "kernel32" fn LocalFree(hMem: ?*anyopaque) callconv(.winapi) ?*anyopaque;

/// A protected DACL that gives only the current logon session the rights
/// needed to exchange pipe data. `FILE_CREATE_PIPE_INSTANCE` is deliberately
/// absent: client processes must not be able to create a server instance.
const client_access: win.DWORD = win.SYNCHRONIZE | win.READ_CONTROL | win.FILE_READ_DATA | win.FILE_WRITE_DATA;

pub const Descriptor = struct {
    raw: *anyopaque,

    pub fn init(allocator: std.mem.Allocator) !Descriptor {
        if (builtin.os.tag != .windows) return error.UnsupportedSocketPlatform;

        const logon_sid = try currentLogonSidAlloc(allocator);
        defer allocator.free(logon_sid);
        const sddl = try descriptorSddlAlloc(allocator, logon_sid);
        defer allocator.free(sddl);
        const sddl_w = try std.unicode.utf8ToUtf16LeAllocZ(allocator, sddl);
        defer allocator.free(sddl_w);

        var raw: ?*anyopaque = null;
        if (ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl_w.ptr, sddl_revision_1, &raw, null) == 0 or raw == null) {
            return error.CreateSecurityDescriptorFailed;
        }
        return .{ .raw = raw.? };
    }

    pub fn deinit(self: *Descriptor) void {
        _ = LocalFree(self.raw);
        self.* = undefined;
    }

    pub fn attributes(self: *const Descriptor) win.SECURITY_ATTRIBUTES {
        return .{
            .nLength = @sizeOf(win.SECURITY_ATTRIBUTES),
            .lpSecurityDescriptor = self.raw,
            .bInheritHandle = 0,
        };
    }
};

/// Access requested by named-pipe clients. Do not replace this with
/// `GENERIC_WRITE`: for named pipes it includes `FILE_CREATE_PIPE_INSTANCE`.
pub const client_access_mask = client_access;

fn currentLogonSidAlloc(allocator: std.mem.Allocator) ![]u8 {
    var token: win.HANDLE = undefined;
    if (OpenProcessToken(win.GetCurrentProcess(), token_query, &token) == 0) return error.OpenProcessTokenFailed;
    defer win.CloseHandle(token);

    var needed: win.DWORD = 0;
    _ = GetTokenInformation(token, token_groups, null, 0, &needed);
    if (needed == 0) return error.GetTokenInformationFailed;

    const raw = try allocator.alloc(u8, needed);
    defer allocator.free(raw);
    if (GetTokenInformation(token, token_groups, raw.ptr, needed, &needed) == 0) return error.GetTokenInformationFailed;

    const groups_header: *const TOKEN_GROUPS = @ptrCast(@alignCast(raw.ptr));
    const groups: [*]const SID_AND_ATTRIBUTES = @ptrCast(&groups_header.Groups);
    for (groups[0..groups_header.GroupCount]) |group| {
        if (group.Attributes & se_group_logon_id != se_group_logon_id) continue;
        return sidToUtf8Alloc(allocator, group.Sid);
    }
    return error.LogonSidNotFound;
}

fn sidToUtf8Alloc(allocator: std.mem.Allocator, sid: *anyopaque) ![]u8 {
    var sid_w: win.LPWSTR = undefined;
    if (ConvertSidToStringSidW(sid, &sid_w) == 0) return error.ConvertSidToStringSidFailed;
    defer _ = LocalFree(sid_w);

    var len: usize = 0;
    while (sid_w[len] != 0) : (len += 1) {}
    return std.unicode.utf16LeToUtf8Alloc(allocator, sid_w[0..len]);
}

fn descriptorSddlAlloc(allocator: std.mem.Allocator, logon_sid: []const u8) ![]u8 {
    if (!isLogonSid(logon_sid)) return error.InvalidLogonSid;
    return std.fmt.allocPrint(allocator, "D:P(A;;0x00120003;;;{s})", .{logon_sid});
}

fn isLogonSid(sid: []const u8) bool {
    if (!std.mem.startsWith(u8, sid, "S-1-5-5-")) return false;
    var parts = std.mem.splitScalar(u8, sid[8..], '-');
    const high = parts.next() orelse return false;
    const low = parts.next() orelse return false;
    if (parts.next() != null or high.len == 0 or low.len == 0) return false;
    for (high) |byte| if (!std.ascii.isDigit(byte)) return false;
    for (low) |byte| if (!std.ascii.isDigit(byte)) return false;
    return true;
}

test "descriptor DACL is restricted to one logon session" {
    const sddl = try descriptorSddlAlloc(std.testing.allocator, "S-1-5-5-42-9001");
    defer std.testing.allocator.free(sddl);

    try std.testing.expectEqualStrings("D:P(A;;0x00120003;;;S-1-5-5-42-9001)", sddl);
    try std.testing.expect(std.mem.indexOf(u8, sddl, "GW") == null);
    try std.testing.expect(std.mem.indexOf(u8, sddl, "WD") == null);
    try std.testing.expect(std.mem.indexOf(u8, sddl, "AN") == null);
}

test "descriptor DACL rejects account and malformed logon SIDs" {
    try std.testing.expectError(error.InvalidLogonSid, descriptorSddlAlloc(std.testing.allocator, "S-1-5-21-1-2-3-1001"));
    try std.testing.expectError(error.InvalidLogonSid, descriptorSddlAlloc(std.testing.allocator, "S-1-5-5-1"));
    try std.testing.expectError(error.InvalidLogonSid, descriptorSddlAlloc(std.testing.allocator, "S-1-5-5-a-2"));
}
