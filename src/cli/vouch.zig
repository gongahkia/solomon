const std = @import("std");

const max_vouches_bytes = 256 * 1024;

const VouchEntry = struct {
    ordinal: usize,
    id: ?[]const u8 = null,
    name: ?[]const u8 = null,
    github: ?[]const u8 = null,
    role: ?[]const u8 = null,
    date: ?[]const u8 = null,
    by: ?[]const u8 = null,
};

const VouchKey = struct {
    ordinal: usize,
    field: []const u8,
};

pub fn vouchCmd(allocator: std.mem.Allocator, args: []const []const u8) !void {
    if (args.len == 1 and (std.mem.eql(u8, args[0], "--help") or std.mem.eql(u8, args[0], "-h"))) {
        try std.fs.File.stdout().writeAll(help_text);
        return;
    }
    if (args.len == 0 or !std.mem.eql(u8, args[0], "verify")) {
        try std.fs.File.stderr().writeAll("shisa vouch: unknown command; run `shisa vouch --help`\n");
        return error.UnknownVouchCommand;
    }
    if (args.len > 2) return error.UnknownVouchArgument;
    if (args.len == 2 and (std.mem.eql(u8, args[1], "--help") or std.mem.eql(u8, args[1], "-h"))) {
        try std.fs.File.stdout().writeAll(help_text);
        return;
    }

    const path = if (args.len == 2) args[1] else "VOUCHES";
    const source = try std.fs.cwd().readFileAlloc(allocator, path, max_vouches_bytes);
    defer allocator.free(source);

    const count = verifyVouches(allocator, source) catch |err| {
        const message = try std.fmt.allocPrint(allocator, "shisa vouch verify: invalid {s}: {s}\n", .{ path, @errorName(err) });
        defer allocator.free(message);
        try std.fs.File.stderr().writeAll(message);
        return err;
    };
    const output = try std.fmt.allocPrint(allocator, "{s} ok ({d} entries)\n", .{ path, count });
    defer allocator.free(output);
    try std.fs.File.stdout().writeAll(output);
}

fn verifyVouches(allocator: std.mem.Allocator, source: []const u8) !usize {
    var entries: std.ArrayList(VouchEntry) = .empty;
    defer entries.deinit(allocator);

    var saw_header = false;
    var lines = std.mem.splitScalar(u8, source, '\n');
    while (lines.next()) |raw_line| {
        const line = std.mem.trim(u8, raw_line, " \t\r");
        if (line.len == 0 or line[0] == '#') continue;

        const eq = std.mem.indexOfScalar(u8, line, '=') orelse return error.InvalidAssignment;
        const key = std.mem.trim(u8, line[0..eq], " \t");
        const value = try parseVouchValue(std.mem.trim(u8, line[eq + 1 ..], " \t"));
        if (!validVouchVariable(key)) return error.InvalidVariable;

        if (std.mem.eql(u8, key, "VOUCHES_FORMAT")) {
            if (saw_header) return error.DuplicateHeader;
            if (!std.mem.eql(u8, value, "1")) return error.UnsupportedVouchesFormat;
            saw_header = true;
            continue;
        }

        const parsed_key = try parseVouchKey(key);
        const entry = try ensureVouchEntry(allocator, &entries, parsed_key.ordinal);
        try assignVouchField(entry, parsed_key.field, value);
    }

    if (!saw_header) return error.MissingHeader;
    if (entries.items.len == 0) return error.MissingVouchEntry;
    for (entries.items) |entry| try validateVouchEntry(entry, entries.items);
    try rejectDuplicateVouches(entries.items);
    return entries.items.len;
}

fn parseVouchValue(value: []const u8) ![]const u8 {
    if (value.len == 0) return error.EmptyValue;
    if (value[0] == '\'') {
        if (value.len < 2 or value[value.len - 1] != '\'') return error.InvalidQuotedValue;
        const inner = value[1 .. value.len - 1];
        if (std.mem.indexOfScalar(u8, inner, '\'') != null) return error.InvalidQuotedValue;
        return inner;
    }
    if (std.mem.indexOfAny(u8, value, " \t\r\n'\"") != null) return error.InvalidBareValue;
    return value;
}

fn validVouchVariable(key: []const u8) bool {
    if (key.len == 0) return false;
    for (key) |byte| {
        if (!(std.ascii.isUpper(byte) or std.ascii.isDigit(byte) or byte == '_')) return false;
    }
    return true;
}

fn parseVouchKey(key: []const u8) !VouchKey {
    if (!std.mem.startsWith(u8, key, "VOUCH_")) return error.UnknownVouchVariable;
    const rest = key["VOUCH_".len..];
    const sep = std.mem.indexOfScalar(u8, rest, '_') orelse return error.InvalidVouchVariable;
    const ordinal_text = rest[0..sep];
    if (ordinal_text.len != 4) return error.InvalidOrdinal;
    for (ordinal_text) |byte| {
        if (!std.ascii.isDigit(byte)) return error.InvalidOrdinal;
    }
    const ordinal = try std.fmt.parseInt(usize, ordinal_text, 10);
    if (ordinal == 0) return error.InvalidOrdinal;
    return .{ .ordinal = ordinal, .field = rest[sep + 1 ..] };
}

fn ensureVouchEntry(allocator: std.mem.Allocator, entries: *std.ArrayList(VouchEntry), ordinal: usize) !*VouchEntry {
    while (entries.items.len < ordinal) {
        try entries.append(allocator, .{ .ordinal = entries.items.len + 1 });
    }
    return &entries.items[ordinal - 1];
}

fn assignVouchField(entry: *VouchEntry, field: []const u8, value: []const u8) !void {
    if (std.mem.eql(u8, field, "ID")) {
        if (entry.id != null) return error.DuplicateField;
        entry.id = value;
    } else if (std.mem.eql(u8, field, "NAME")) {
        if (entry.name != null) return error.DuplicateField;
        entry.name = value;
    } else if (std.mem.eql(u8, field, "GITHUB")) {
        if (entry.github != null) return error.DuplicateField;
        entry.github = value;
    } else if (std.mem.eql(u8, field, "ROLE")) {
        if (entry.role != null) return error.DuplicateField;
        entry.role = value;
    } else if (std.mem.eql(u8, field, "DATE")) {
        if (entry.date != null) return error.DuplicateField;
        entry.date = value;
    } else if (std.mem.eql(u8, field, "BY")) {
        if (entry.by != null) return error.DuplicateField;
        entry.by = value;
    } else {
        return error.UnknownVouchField;
    }
}

fn validateVouchEntry(entry: VouchEntry, entries: []const VouchEntry) !void {
    const id = entry.id orelse return error.MissingVouchField;
    const name = entry.name orelse return error.MissingVouchField;
    const github = entry.github orelse return error.MissingVouchField;
    const role = entry.role orelse return error.MissingVouchField;
    const date = entry.date orelse return error.MissingVouchField;
    const by = entry.by orelse return error.MissingVouchField;

    if (!validVouchId(id)) return error.InvalidVouchId;
    if (name.len == 0) return error.InvalidVouchName;
    if (!validGitHubHandle(github)) return error.InvalidGitHubHandle;
    if (!validVouchRole(role)) return error.InvalidVouchRole;
    if (!validDate(date)) return error.InvalidVouchDate;
    if (std.mem.eql(u8, by, "self")) {
        if (entry.ordinal != 1 or !std.mem.eql(u8, id, "founder")) return error.InvalidVouchGrantor;
    } else if (!vouchIdExists(entries, by)) {
        return error.InvalidVouchGrantor;
    }
}

fn validVouchId(value: []const u8) bool {
    if (value.len == 0) return false;
    for (value) |byte| {
        if (!(std.ascii.isLower(byte) or std.ascii.isDigit(byte) or byte == '-')) return false;
    }
    return true;
}

fn validGitHubHandle(value: []const u8) bool {
    if (value.len == 0 or value.len > 39) return false;
    if (value[0] == '-' or value[value.len - 1] == '-') return false;
    for (value) |byte| {
        if (!(std.ascii.isAlphanumeric(byte) or byte == '-')) return false;
    }
    return true;
}

fn validVouchRole(value: []const u8) bool {
    return std.mem.eql(u8, value, "founder") or
        std.mem.eql(u8, value, "maintainer") or
        std.mem.eql(u8, value, "contributor");
}

fn validDate(value: []const u8) bool {
    if (value.len != "YYYY-MM-DD".len) return false;
    if (value[4] != '-' or value[7] != '-') return false;
    for (value, 0..) |byte, index| {
        if (index == 4 or index == 7) continue;
        if (!std.ascii.isDigit(byte)) return false;
    }
    const month = std.fmt.parseInt(u8, value[5..7], 10) catch return false;
    const day = std.fmt.parseInt(u8, value[8..10], 10) catch return false;
    return month >= 1 and month <= 12 and day >= 1 and day <= 31;
}

fn vouchIdExists(entries: []const VouchEntry, id: []const u8) bool {
    for (entries) |entry| {
        if (entry.id) |candidate| {
            if (std.mem.eql(u8, candidate, id)) return true;
        }
    }
    return false;
}

fn rejectDuplicateVouches(entries: []const VouchEntry) !void {
    for (entries, 0..) |left, i| {
        for (entries[i + 1 ..]) |right| {
            if (std.mem.eql(u8, left.id.?, right.id.?)) return error.DuplicateVouchId;
            if (std.mem.eql(u8, left.github.?, right.github.?)) return error.DuplicateGitHubHandle;
        }
    }
}

const valid_vouches_fixture =
    \\VOUCHES_FORMAT=1
    \\VOUCH_0001_ID=founder
    \\VOUCH_0001_NAME='Gabriel Ong Zhe Mian'
    \\VOUCH_0001_GITHUB=gongahkia
    \\VOUCH_0001_ROLE=founder
    \\VOUCH_0001_DATE=2026-06-17
    \\VOUCH_0001_BY=self
;

test "vouch verifier accepts bootstrap entry" {
    try std.testing.expectEqual(@as(usize, 1), try verifyVouches(std.testing.allocator, valid_vouches_fixture));
}

test "vouch verifier rejects missing header" {
    try std.testing.expectError(error.MissingHeader, verifyVouches(std.testing.allocator, "VOUCH_0001_ID=founder\n"));
}

test "vouch verifier rejects duplicate github handles" {
    const source =
        \\VOUCHES_FORMAT=1
        \\VOUCH_0001_ID=founder
        \\VOUCH_0001_NAME='Gabriel Ong Zhe Mian'
        \\VOUCH_0001_GITHUB=gongahkia
        \\VOUCH_0001_ROLE=founder
        \\VOUCH_0001_DATE=2026-06-17
        \\VOUCH_0001_BY=self
        \\VOUCH_0002_ID=maintainer
        \\VOUCH_0002_NAME=Maintainer
        \\VOUCH_0002_GITHUB=gongahkia
        \\VOUCH_0002_ROLE=maintainer
        \\VOUCH_0002_DATE=2026-06-17
        \\VOUCH_0002_BY=founder
    ;
    try std.testing.expectError(error.DuplicateGitHubHandle, verifyVouches(std.testing.allocator, source));
}

test "vouch verifier rejects invalid dates" {
    const source =
        \\VOUCHES_FORMAT=1
        \\VOUCH_0001_ID=founder
        \\VOUCH_0001_NAME='Gabriel Ong Zhe Mian'
        \\VOUCH_0001_GITHUB=gongahkia
        \\VOUCH_0001_ROLE=founder
        \\VOUCH_0001_DATE=2026-99-17
        \\VOUCH_0001_BY=self
    ;
    try std.testing.expectError(error.InvalidVouchDate, verifyVouches(std.testing.allocator, source));
}

const help_text =
    \\usage: shisa vouch verify [path]
    \\
    \\commands:
    \\  verify [path] validate VOUCHES format; defaults to ./VOUCHES
    \\
;
