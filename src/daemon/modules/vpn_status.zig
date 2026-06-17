const std = @import("std");

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
