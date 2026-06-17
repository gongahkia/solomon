const std = @import("std");
const builtin = @import("builtin");

pub const module_id = "vpn_status";

pub const VpnStatus = struct {
    provider: []u8,
    name: []u8,

    pub fn deinit(self: *VpnStatus, allocator: std.mem.Allocator) void {
        allocator.free(self.provider);
        allocator.free(self.name);
        self.* = undefined;
    }
};

const TailscaleSelfJson = struct {
    HostName: []const u8 = "",
    DNSName: []const u8 = "",
};

const TailscaleStatusJson = struct {
    BackendState: []const u8 = "",
    Self: TailscaleSelfJson = .{},
};

const NetBirdStatusJson = struct {
    status: []const u8 = "",
    netbirdIp: []const u8 = "",
    fqdn: []const u8 = "",
};

pub fn readWireGuardStatusAlloc(allocator: std.mem.Allocator) !?VpnStatus {
    const result = try std.process.Child.run(.{
        .allocator = allocator,
        .argv = &.{ "wg", "show" },
        .max_output_bytes = 256 * 1024,
        .expand_arg0 = .expand,
    });
    defer allocator.free(result.stdout);
    defer allocator.free(result.stderr);
    if (!switch (result.term) {
        .Exited => |code| code == 0,
        else => false,
    }) return null;
    return parseWireGuardShowAlloc(allocator, result.stdout);
}

pub fn readTailscaleStatusAlloc(allocator: std.mem.Allocator) !?VpnStatus {
    const result = try std.process.Child.run(.{
        .allocator = allocator,
        .argv = &.{ "tailscale", "status", "--json" },
        .max_output_bytes = 1024 * 1024,
        .expand_arg0 = .expand,
    });
    defer allocator.free(result.stdout);
    defer allocator.free(result.stderr);
    if (!switch (result.term) {
        .Exited => |code| code == 0,
        else => false,
    }) return null;
    return parseTailscaleStatusAlloc(allocator, result.stdout);
}

pub fn readNetBirdStatusAlloc(allocator: std.mem.Allocator) !?VpnStatus {
    const result = try std.process.Child.run(.{
        .allocator = allocator,
        .argv = &.{ "netbird", "status", "--json" },
        .max_output_bytes = 1024 * 1024,
        .expand_arg0 = .expand,
    });
    defer allocator.free(result.stdout);
    defer allocator.free(result.stderr);
    if (!switch (result.term) {
        .Exited => |code| code == 0,
        else => false,
    }) return null;
    return parseNetBirdStatusAlloc(allocator, result.stdout);
}

pub fn readWarpStatusAlloc(allocator: std.mem.Allocator) !?VpnStatus {
    const result = try std.process.Child.run(.{
        .allocator = allocator,
        .argv = &.{ "warp-cli", "status" },
        .max_output_bytes = 256 * 1024,
        .expand_arg0 = .expand,
    });
    defer allocator.free(result.stdout);
    defer allocator.free(result.stderr);
    if (!switch (result.term) {
        .Exited => |code| code == 0,
        else => false,
    }) return null;
    return parseWarpStatusAlloc(allocator, result.stdout);
}

pub fn readZeroTierStatusAlloc(allocator: std.mem.Allocator) !?VpnStatus {
    const result = try std.process.Child.run(.{
        .allocator = allocator,
        .argv = &.{ "zerotier-cli", "status" },
        .max_output_bytes = 256 * 1024,
        .expand_arg0 = .expand,
    });
    defer allocator.free(result.stdout);
    defer allocator.free(result.stderr);
    if (!switch (result.term) {
        .Exited => |code| code == 0,
        else => false,
    }) return null;
    return parseZeroTierStatusAlloc(allocator, result.stdout);
}

pub fn readScutilNetworkServiceStatusAlloc(allocator: std.mem.Allocator) !?VpnStatus {
    const result = try std.process.Child.run(.{
        .allocator = allocator,
        .argv = &.{ "scutil", "--nc", "list" },
        .max_output_bytes = 256 * 1024,
        .expand_arg0 = .expand,
    });
    defer allocator.free(result.stdout);
    defer allocator.free(result.stderr);
    if (!switch (result.term) {
        .Exited => |code| code == 0,
        else => false,
    }) return null;
    return parseScutilNetworkServicesAlloc(allocator, result.stdout);
}

pub fn readNetworkManagerStatusAlloc(allocator: std.mem.Allocator) !?VpnStatus {
    const active = try busctlGetPropertyAlloc(
        allocator,
        "/org/freedesktop/NetworkManager",
        "org.freedesktop.NetworkManager",
        "ActiveConnections",
    );
    defer allocator.free(active);
    const paths = try parseNetworkManagerActiveConnectionsAlloc(allocator, active);
    defer freeStringList(allocator, paths);
    for (paths) |path| {
        const vpn = try busctlGetPropertyAlloc(
            allocator,
            path,
            "org.freedesktop.NetworkManager.Connection.Active",
            "Vpn",
        );
        defer allocator.free(vpn);
        if (!parseBusctlBool(vpn)) continue;
        const id = try busctlGetPropertyAlloc(
            allocator,
            path,
            "org.freedesktop.NetworkManager.Connection.Active",
            "Id",
        );
        defer allocator.free(id);
        return @as(?VpnStatus, try vpnStatusAlloc(allocator, "nm", parseBusctlString(id) orelse "vpn"));
    }
    return null;
}

pub fn render(allocator: std.mem.Allocator) !?[]u8 {
    if (try firstActiveStatusAlloc(allocator)) |status_value| {
        var status = status_value;
        defer status.deinit(allocator);
        return renderStatusAlloc(allocator, status);
    }
    return null;
}

pub fn firstActiveStatusAlloc(allocator: std.mem.Allocator) !?VpnStatus {
    if (readWireGuardStatusAlloc(allocator) catch null) |status| return status;
    if (readTailscaleStatusAlloc(allocator) catch null) |status| return status;
    if (readNetBirdStatusAlloc(allocator) catch null) |status| return status;
    if (readWarpStatusAlloc(allocator) catch null) |status| return status;
    if (readZeroTierStatusAlloc(allocator) catch null) |status| return status;
    if (builtin.os.tag == .macos) {
        if (readScutilNetworkServiceStatusAlloc(allocator) catch null) |status| return status;
    }
    if (builtin.os.tag == .linux) {
        if (readNetworkManagerStatusAlloc(allocator) catch null) |status| return status;
    }
    return null;
}

pub fn renderStatusAlloc(allocator: std.mem.Allocator, status: VpnStatus) !?[]u8 {
    var out: std.ArrayList(u8) = .empty;
    errdefer out.deinit(allocator);
    try out.appendSlice(allocator, "vpn:");
    const name = std.mem.trim(u8, status.name, " \t\r\n");
    if (name.len == 0) {
        try out.appendSlice(allocator, status.provider);
    } else {
        try appendCompactName(allocator, &out, name);
    }
    return @as(?[]u8, try out.toOwnedSlice(allocator));
}

pub fn parseWireGuardShowAlloc(allocator: std.mem.Allocator, source: []const u8) !?VpnStatus {
    var lines = std.mem.splitScalar(u8, source, '\n');
    while (lines.next()) |raw_line| {
        const line = std.mem.trim(u8, raw_line, " \t\r");
        if (!std.mem.startsWith(u8, line, "interface:")) continue;
        const name = std.mem.trim(u8, line["interface:".len..], " \t\r\n");
        if (name.len == 0) continue;
        const provider = try allocator.dupe(u8, "wg");
        errdefer allocator.free(provider);
        return VpnStatus{
            .provider = provider,
            .name = try allocator.dupe(u8, name),
        };
    }
    return null;
}

pub fn parseTailscaleStatusAlloc(allocator: std.mem.Allocator, source: []const u8) !?VpnStatus {
    var parsed = std.json.parseFromSlice(TailscaleStatusJson, allocator, source, .{ .ignore_unknown_fields = true }) catch return null;
    defer parsed.deinit();
    if (!std.mem.eql(u8, std.mem.trim(u8, parsed.value.BackendState, " \t\r\n"), "Running")) return null;
    const name = tailscaleName(parsed.value.Self) orelse return null;
    const provider = try allocator.dupe(u8, "ts");
    errdefer allocator.free(provider);
    return VpnStatus{
        .provider = provider,
        .name = try allocator.dupe(u8, name),
    };
}

pub fn parseNetBirdStatusAlloc(allocator: std.mem.Allocator, source: []const u8) !?VpnStatus {
    var parsed = std.json.parseFromSlice(NetBirdStatusJson, allocator, source, .{ .ignore_unknown_fields = true }) catch return null;
    defer parsed.deinit();
    if (!statusIsConnected(parsed.value.status)) return null;
    const name = netbirdName(parsed.value);
    return @as(?VpnStatus, try vpnStatusAlloc(allocator, "netbird", name));
}

pub fn parseWarpStatusAlloc(allocator: std.mem.Allocator, source: []const u8) !?VpnStatus {
    var lines = std.mem.splitScalar(u8, source, '\n');
    while (lines.next()) |raw_line| {
        const line = std.mem.trim(u8, raw_line, " \t\r");
        if (!std.mem.startsWith(u8, line, "Status update:")) continue;
        const status = std.mem.trim(u8, line["Status update:".len..], " \t\r\n");
        if (std.ascii.eqlIgnoreCase(status, "Connected")) return @as(?VpnStatus, try vpnStatusAlloc(allocator, "warp", "warp"));
        return null;
    }
    return null;
}

pub fn parseZeroTierStatusAlloc(allocator: std.mem.Allocator, source: []const u8) !?VpnStatus {
    var tokens = std.mem.tokenizeAny(u8, source, " \t\r\n");
    while (tokens.next()) |token| {
        if (std.ascii.eqlIgnoreCase(token, "ONLINE")) return @as(?VpnStatus, try vpnStatusAlloc(allocator, "zt", "zerotier"));
    }
    return null;
}

pub fn parseScutilNetworkServicesAlloc(allocator: std.mem.Allocator, source: []const u8) !?VpnStatus {
    var lines = std.mem.splitScalar(u8, source, '\n');
    while (lines.next()) |raw_line| {
        const line = std.mem.trim(u8, raw_line, " \t\r");
        if (std.mem.indexOf(u8, line, "(Connected)") == null) continue;
        if (std.mem.indexOf(u8, line, "[VPN:") == null) continue;
        return @as(?VpnStatus, try vpnStatusAlloc(allocator, "vpn", scutilServiceName(line)));
    }
    return null;
}

pub fn parseNetworkManagerActiveConnectionsAlloc(allocator: std.mem.Allocator, source: []const u8) ![][]u8 {
    var out: std.ArrayList([]u8) = .empty;
    errdefer {
        for (out.items) |path| allocator.free(path);
        out.deinit(allocator);
    }
    var index: usize = 0;
    while (index < source.len) {
        const start_quote = std.mem.indexOfScalarPos(u8, source, index, '"') orelse break;
        const rest = source[start_quote + 1 ..];
        const end_quote = std.mem.indexOfScalar(u8, rest, '"') orelse break;
        const value = rest[0..end_quote];
        index = start_quote + 1 + end_quote + 1;
        if (!std.mem.startsWith(u8, value, "/org/freedesktop/NetworkManager/ActiveConnection/")) continue;
        try out.append(allocator, try allocator.dupe(u8, value));
    }
    return out.toOwnedSlice(allocator);
}

fn tailscaleName(self: TailscaleSelfJson) ?[]const u8 {
    const host = std.mem.trim(u8, self.HostName, " \t\r\n.");
    if (host.len != 0) return host;
    const dns = std.mem.trim(u8, self.DNSName, " \t\r\n.");
    if (dns.len != 0) return dns;
    return null;
}

fn statusIsConnected(value: []const u8) bool {
    const status = std.mem.trim(u8, value, " \t\r\n");
    return std.ascii.eqlIgnoreCase(status, "connected") or std.ascii.eqlIgnoreCase(status, "up");
}

fn netbirdName(status: NetBirdStatusJson) []const u8 {
    const ip = std.mem.trim(u8, status.netbirdIp, " \t\r\n");
    if (ip.len != 0) return ip;
    const fqdn = std.mem.trim(u8, status.fqdn, " \t\r\n.");
    if (fqdn.len != 0) return fqdn;
    return "netbird";
}

fn vpnStatusAlloc(allocator: std.mem.Allocator, provider: []const u8, name: []const u8) !VpnStatus {
    const owned_provider = try allocator.dupe(u8, provider);
    errdefer allocator.free(owned_provider);
    return .{
        .provider = owned_provider,
        .name = try allocator.dupe(u8, name),
    };
}

fn scutilServiceName(line: []const u8) []const u8 {
    const marker = "(Connected)";
    const marker_index = std.mem.indexOf(u8, line, marker) orelse return "vpn";
    const rest = std.mem.trim(u8, line[marker_index + marker.len ..], " \t\r\n");
    if (quotedName(rest)) |name| return name;
    const bracket_index = std.mem.indexOf(u8, rest, "[") orelse rest.len;
    const name = std.mem.trim(u8, rest[0..bracket_index], " \t\r\n");
    if (name.len == 0) return "vpn";
    return name;
}

fn quotedName(value: []const u8) ?[]const u8 {
    const start = std.mem.indexOfScalar(u8, value, '"') orelse return null;
    const rest = value[start + 1 ..];
    const end = std.mem.indexOfScalar(u8, rest, '"') orelse return null;
    if (end == 0) return null;
    return rest[0..end];
}

fn busctlGetPropertyAlloc(allocator: std.mem.Allocator, path: []const u8, interface: []const u8, property: []const u8) ![]u8 {
    const result = try std.process.Child.run(.{
        .allocator = allocator,
        .argv = &.{ "busctl", "get-property", "org.freedesktop.NetworkManager", path, interface, property },
        .max_output_bytes = 256 * 1024,
        .expand_arg0 = .expand,
    });
    defer allocator.free(result.stderr);
    if (!switch (result.term) {
        .Exited => |code| code == 0,
        else => false,
    }) {
        allocator.free(result.stdout);
        return error.BusctlFailed;
    }
    return result.stdout;
}

fn parseBusctlBool(source: []const u8) bool {
    var tokens = std.mem.tokenizeAny(u8, source, " \t\r\n");
    while (tokens.next()) |token| {
        if (std.ascii.eqlIgnoreCase(token, "true")) return true;
        if (std.ascii.eqlIgnoreCase(token, "false")) return false;
    }
    return false;
}

fn parseBusctlString(source: []const u8) ?[]const u8 {
    return quotedName(source);
}

fn freeStringList(allocator: std.mem.Allocator, values: [][]u8) void {
    for (values) |value| allocator.free(value);
    allocator.free(values);
}

fn appendCompactName(allocator: std.mem.Allocator, out: *std.ArrayList(u8), name: []const u8) !void {
    for (name) |byte| {
        if (byte == ' ' or byte == '\t' or byte == '\r' or byte == '\n') {
            try out.append(allocator, '_');
        } else {
            try out.append(allocator, byte);
        }
    }
}

test "parses wireguard interface from wg show" {
    var status = (try parseWireGuardShowAlloc(std.testing.allocator,
        \\interface: wg0
        \\  public key: abc
        \\  private key: (hidden)
        \\  listening port: 51820
        \\
        \\peer: def
        \\  endpoint: 192.0.2.1:51820
        \\
    )).?;
    defer status.deinit(std.testing.allocator);
    try std.testing.expectEqualStrings("wg", status.provider);
    try std.testing.expectEqualStrings("wg0", status.name);
}

test "wireguard parser ignores empty output" {
    try std.testing.expect(try parseWireGuardShowAlloc(std.testing.allocator, "") == null);
    try std.testing.expect(try parseWireGuardShowAlloc(std.testing.allocator, "interface:   \n") == null);
}

test "parses tailscale running status" {
    var status = (try parseTailscaleStatusAlloc(std.testing.allocator,
        \\{
        \\  "BackendState": "Running",
        \\  "Self": {
        \\    "HostName": "laptop",
        \\    "DNSName": "laptop.tailnet.ts.net."
        \\  }
        \\}
    )).?;
    defer status.deinit(std.testing.allocator);
    try std.testing.expectEqualStrings("ts", status.provider);
    try std.testing.expectEqualStrings("laptop", status.name);
}

test "tailscale parser ignores stopped status" {
    try std.testing.expect(try parseTailscaleStatusAlloc(std.testing.allocator, "{\"BackendState\":\"Stopped\",\"Self\":{\"HostName\":\"laptop\"}}") == null);
}

test "parses netbird connected status" {
    var status = (try parseNetBirdStatusAlloc(std.testing.allocator, "{\"status\":\"Connected\",\"netbirdIp\":\"100.64.0.10\"}")).?;
    defer status.deinit(std.testing.allocator);
    try std.testing.expectEqualStrings("netbird", status.provider);
    try std.testing.expectEqualStrings("100.64.0.10", status.name);
}

test "netbird parser ignores disconnected status" {
    try std.testing.expect(try parseNetBirdStatusAlloc(std.testing.allocator, "{\"status\":\"Disconnected\"}") == null);
}

test "parses warp connected status" {
    var status = (try parseWarpStatusAlloc(std.testing.allocator, "Status update: Connected\n")).?;
    defer status.deinit(std.testing.allocator);
    try std.testing.expectEqualStrings("warp", status.provider);
    try std.testing.expectEqualStrings("warp", status.name);
}

test "warp parser ignores disconnected status" {
    try std.testing.expect(try parseWarpStatusAlloc(std.testing.allocator, "Status update: Disconnected\n") == null);
}

test "parses zerotier online status" {
    var status = (try parseZeroTierStatusAlloc(std.testing.allocator, "200 info abcdef0123 1.14.2 ONLINE\n")).?;
    defer status.deinit(std.testing.allocator);
    try std.testing.expectEqualStrings("zt", status.provider);
    try std.testing.expectEqualStrings("zerotier", status.name);
}

test "zerotier parser ignores offline status" {
    try std.testing.expect(try parseZeroTierStatusAlloc(std.testing.allocator, "200 info abcdef0123 1.14.2 OFFLINE\n") == null);
}

test "parses connected macos network vpn" {
    var status = (try parseScutilNetworkServicesAlloc(std.testing.allocator,
        \\Available network connection services in the current set (*=enabled):
        \\* (Disconnected) Old VPN "Old VPN" [VPN:L2TP]
        \\* (Connected) Work IKE "Work IKE" [VPN:IKEv2]
        \\
    )).?;
    defer status.deinit(std.testing.allocator);
    try std.testing.expectEqualStrings("vpn", status.provider);
    try std.testing.expectEqualStrings("Work IKE", status.name);
}

test "scutil parser ignores disconnected vpn" {
    try std.testing.expect(try parseScutilNetworkServicesAlloc(std.testing.allocator, "* (Disconnected) Work VPN \"Work VPN\" [VPN:IKEv2]\n") == null);
}

test "parses networkmanager active connection paths" {
    const paths = try parseNetworkManagerActiveConnectionsAlloc(std.testing.allocator, "ao 2 \"/org/freedesktop/NetworkManager/ActiveConnection/1\" \"/org/freedesktop/NetworkManager/ActiveConnection/2\"\n");
    defer freeStringList(std.testing.allocator, paths);
    try std.testing.expectEqual(@as(usize, 2), paths.len);
    try std.testing.expectEqualStrings("/org/freedesktop/NetworkManager/ActiveConnection/1", paths[0]);
    try std.testing.expectEqualStrings("/org/freedesktop/NetworkManager/ActiveConnection/2", paths[1]);
}

test "parses busctl property values" {
    try std.testing.expect(parseBusctlBool("b true\n"));
    try std.testing.expect(!parseBusctlBool("b false\n"));
    try std.testing.expectEqualStrings("Work VPN", parseBusctlString("s \"Work VPN\"\n").?);
}

test "renders compact vpn segment" {
    var status = VpnStatus{
        .provider = try std.testing.allocator.dupe(u8, "vpn"),
        .name = try std.testing.allocator.dupe(u8, "Work VPN"),
    };
    defer status.deinit(std.testing.allocator);
    const segment = (try renderStatusAlloc(std.testing.allocator, status)).?;
    defer std.testing.allocator.free(segment);
    try std.testing.expectEqualStrings("vpn:Work_VPN", segment);
}
