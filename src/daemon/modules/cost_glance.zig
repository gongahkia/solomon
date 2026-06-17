const std = @import("std");

pub const module_id = "cost_glance";
pub const aws_ce_endpoint = "https://ce.us-east-1.amazonaws.com";
pub const aws_ce_target = "AWSInsightsIndexService.GetCostAndUsage";
pub const aws_ce_service = "ce";
pub const aws_ce_region = "us-east-1";
pub const gcp_billing_endpoint = "https://cloudbilling.googleapis.com/v1";

pub const Money = struct {
    amount: []u8,
    unit: []u8,

    pub fn deinit(self: *Money, allocator: std.mem.Allocator) void {
        allocator.free(self.amount);
        allocator.free(self.unit);
        self.* = undefined;
    }
};

const AwsMetric = struct {
    Amount: []const u8 = "",
    Unit: []const u8 = "",
};

const AwsTotal = struct {
    UnblendedCost: AwsMetric = .{},
};

const AwsResultByTime = struct {
    Total: AwsTotal = .{},
};

const AwsCostResponse = struct {
    ResultsByTime: []AwsResultByTime = &.{},
};

pub const GcpBillingAccount = struct {
    name: []u8,
    display_name: []u8,
    open: bool,

    pub fn deinit(self: *GcpBillingAccount, allocator: std.mem.Allocator) void {
        allocator.free(self.name);
        allocator.free(self.display_name);
        self.* = undefined;
    }
};

const GcpBillingAccountJson = struct {
    name: []const u8 = "",
    displayName: []const u8 = "",
    display_name: []const u8 = "",
    open: bool = false,
};

const GcpBillingAccountsResponse = struct {
    billingAccounts: []GcpBillingAccountJson = &.{},
};

pub fn awsGetCostAndUsagePayloadAlloc(allocator: std.mem.Allocator, start_date: []const u8, end_date: []const u8) ![]u8 {
    if (!validIsoDate(start_date) or !validIsoDate(end_date)) return error.InvalidDate;
    return std.fmt.allocPrint(
        allocator,
        "{{\"TimePeriod\":{{\"Start\":\"{s}\",\"End\":\"{s}\"}},\"Granularity\":\"MONTHLY\",\"Metrics\":[\"UnblendedCost\"]}}",
        .{ start_date, end_date },
    );
}

pub fn awsCostExplorerCliArgvAlloc(allocator: std.mem.Allocator, profile: ?[]const u8, start_date: []const u8, end_date: []const u8) ![][]u8 {
    if (!validIsoDate(start_date) or !validIsoDate(end_date)) return error.InvalidDate;
    var args: std.ArrayList([]u8) = .empty;
    errdefer {
        freePartialArgv(allocator, args.items);
        args.deinit(allocator);
    }

    try appendArg(allocator, &args, "aws");
    if (trimEnv(profile)) |profile_name| {
        try appendArg(allocator, &args, "--profile");
        try appendArg(allocator, &args, profile_name);
    }
    try appendArg(allocator, &args, "ce");
    try appendArg(allocator, &args, "get-cost-and-usage");
    try appendArg(allocator, &args, "--time-period");
    const period = try std.fmt.allocPrint(allocator, "Start={s},End={s}", .{ start_date, end_date });
    errdefer allocator.free(period);
    try args.append(allocator, period);
    try appendArg(allocator, &args, "--granularity");
    try appendArg(allocator, &args, "MONTHLY");
    try appendArg(allocator, &args, "--metrics");
    try appendArg(allocator, &args, "UnblendedCost");
    try appendArg(allocator, &args, "--output");
    try appendArg(allocator, &args, "json");
    return args.toOwnedSlice(allocator);
}

pub fn gcpBillingAccountsListUrlAlloc(allocator: std.mem.Allocator) ![]u8 {
    return std.fmt.allocPrint(allocator, "{s}/billingAccounts", .{gcp_billing_endpoint});
}

pub fn gcpBillingAccountsCliArgvAlloc(allocator: std.mem.Allocator) ![][]u8 {
    var args: std.ArrayList([]u8) = .empty;
    errdefer {
        freePartialArgv(allocator, args.items);
        args.deinit(allocator);
    }
    try appendArg(allocator, &args, "gcloud");
    try appendArg(allocator, &args, "billing");
    try appendArg(allocator, &args, "accounts");
    try appendArg(allocator, &args, "list");
    try appendArg(allocator, &args, "--filter=open=true");
    try appendArg(allocator, &args, "--format=json");
    return args.toOwnedSlice(allocator);
}

pub fn freeArgv(allocator: std.mem.Allocator, argv: [][]u8) void {
    freePartialArgv(allocator, argv);
    allocator.free(argv);
}

pub fn readAwsMonthlyCostWithCliAlloc(allocator: std.mem.Allocator, profile: ?[]const u8, start_date: []const u8, end_date: []const u8) !?Money {
    const argv = try awsCostExplorerCliArgvAlloc(allocator, profile, start_date, end_date);
    defer freeArgv(allocator, argv);
    const result = try std.process.Child.run(.{
        .allocator = allocator,
        .argv = argv,
        .max_output_bytes = 1024 * 1024,
        .expand_arg0 = .expand,
    });
    defer allocator.free(result.stdout);
    defer allocator.free(result.stderr);
    if (!switch (result.term) {
        .Exited => |code| code == 0,
        else => false,
    }) return error.AwsCliFailed;
    return parseAwsUnblendedCostAlloc(allocator, result.stdout);
}

pub fn readGcpPrimaryBillingAccountWithCliAlloc(allocator: std.mem.Allocator) !?GcpBillingAccount {
    const argv = try gcpBillingAccountsCliArgvAlloc(allocator);
    defer freeArgv(allocator, argv);
    const result = try std.process.Child.run(.{
        .allocator = allocator,
        .argv = argv,
        .max_output_bytes = 1024 * 1024,
        .expand_arg0 = .expand,
    });
    defer allocator.free(result.stdout);
    defer allocator.free(result.stderr);
    if (!switch (result.term) {
        .Exited => |code| code == 0,
        else => false,
    }) return error.GcloudCliFailed;
    return parseGcpPrimaryBillingAccountAlloc(allocator, result.stdout);
}

pub fn parseAwsUnblendedCostAlloc(allocator: std.mem.Allocator, source: []const u8) !?Money {
    var parsed = std.json.parseFromSlice(AwsCostResponse, allocator, source, .{ .ignore_unknown_fields = true }) catch return null;
    defer parsed.deinit();
    for (parsed.value.ResultsByTime) |result| {
        const amount = std.mem.trim(u8, result.Total.UnblendedCost.Amount, " \t\r\n");
        if (amount.len == 0) continue;
        const unit = std.mem.trim(u8, result.Total.UnblendedCost.Unit, " \t\r\n");
        const owned_amount = try allocator.dupe(u8, amount);
        errdefer allocator.free(owned_amount);
        return Money{
            .amount = owned_amount,
            .unit = try allocator.dupe(u8, if (unit.len == 0) "USD" else unit),
        };
    }
    return null;
}

pub fn parseGcpPrimaryBillingAccountAlloc(allocator: std.mem.Allocator, source: []const u8) !?GcpBillingAccount {
    if (try parseGcpPrimaryBillingAccountArrayAlloc(allocator, source)) |account| return account;
    var parsed = std.json.parseFromSlice(GcpBillingAccountsResponse, allocator, source, .{ .ignore_unknown_fields = true }) catch return null;
    defer parsed.deinit();
    return gcpPrimaryBillingAccountFromListAlloc(allocator, parsed.value.billingAccounts);
}

fn parseGcpPrimaryBillingAccountArrayAlloc(allocator: std.mem.Allocator, source: []const u8) !?GcpBillingAccount {
    var parsed = std.json.parseFromSlice([]GcpBillingAccountJson, allocator, source, .{ .ignore_unknown_fields = true }) catch return null;
    defer parsed.deinit();
    return gcpPrimaryBillingAccountFromListAlloc(allocator, parsed.value);
}

fn gcpPrimaryBillingAccountFromListAlloc(allocator: std.mem.Allocator, accounts: []const GcpBillingAccountJson) !?GcpBillingAccount {
    for (accounts) |account| {
        const name = std.mem.trim(u8, account.name, " \t\r\n");
        if (!account.open or name.len == 0) continue;
        const display_name = gcpDisplayName(account);
        const owned_name = try allocator.dupe(u8, name);
        errdefer allocator.free(owned_name);
        return GcpBillingAccount{
            .name = owned_name,
            .display_name = try allocator.dupe(u8, display_name),
            .open = account.open,
        };
    }
    return null;
}

fn gcpDisplayName(account: GcpBillingAccountJson) []const u8 {
    const display_name = std.mem.trim(u8, account.displayName, " \t\r\n");
    if (display_name.len != 0) return display_name;
    return std.mem.trim(u8, account.display_name, " \t\r\n");
}

pub fn validIsoDate(value: []const u8) bool {
    if (value.len != 10) return false;
    for (value, 0..) |byte, index| {
        if (index == 4 or index == 7) {
            if (byte != '-') return false;
        } else if (!std.ascii.isDigit(byte)) return false;
    }
    return true;
}

fn appendArg(allocator: std.mem.Allocator, args: *std.ArrayList([]u8), value: []const u8) !void {
    const owned = try allocator.dupe(u8, value);
    errdefer allocator.free(owned);
    try args.append(allocator, owned);
}

fn freePartialArgv(allocator: std.mem.Allocator, argv: [][]u8) void {
    for (argv) |arg| allocator.free(arg);
}

fn trimEnv(value: ?[]const u8) ?[]const u8 {
    if (value) |raw| {
        const trimmed = std.mem.trim(u8, raw, " \t\r\n");
        if (trimmed.len != 0) return trimmed;
    }
    return null;
}

test "builds aws cost explorer payload" {
    const payload = try awsGetCostAndUsagePayloadAlloc(std.testing.allocator, "2026-06-01", "2026-07-01");
    defer std.testing.allocator.free(payload);
    try std.testing.expectEqualStrings("{\"TimePeriod\":{\"Start\":\"2026-06-01\",\"End\":\"2026-07-01\"},\"Granularity\":\"MONTHLY\",\"Metrics\":[\"UnblendedCost\"]}", payload);
}

test "builds aws cost explorer cli argv" {
    const argv = try awsCostExplorerCliArgvAlloc(std.testing.allocator, " prod ", "2026-06-01", "2026-07-01");
    defer freeArgv(std.testing.allocator, argv);
    const expected = [_][]const u8{ "aws", "--profile", "prod", "ce", "get-cost-and-usage", "--time-period", "Start=2026-06-01,End=2026-07-01", "--granularity", "MONTHLY", "--metrics", "UnblendedCost", "--output", "json" };
    try std.testing.expectEqual(expected.len, argv.len);
    for (expected, 0..) |value, index| try std.testing.expectEqualStrings(value, argv[index]);
}

test "builds gcp billing accounts cli argv" {
    const argv = try gcpBillingAccountsCliArgvAlloc(std.testing.allocator);
    defer freeArgv(std.testing.allocator, argv);
    const expected = [_][]const u8{ "gcloud", "billing", "accounts", "list", "--filter=open=true", "--format=json" };
    try std.testing.expectEqual(expected.len, argv.len);
    for (expected, 0..) |value, index| try std.testing.expectEqualStrings(value, argv[index]);
}

test "builds gcp billing accounts REST URL" {
    const url = try gcpBillingAccountsListUrlAlloc(std.testing.allocator);
    defer std.testing.allocator.free(url);
    try std.testing.expectEqualStrings("https://cloudbilling.googleapis.com/v1/billingAccounts", url);
}

test "parses aws cost explorer response" {
    var money = (try parseAwsUnblendedCostAlloc(std.testing.allocator,
        \\{
        \\  "ResultsByTime": [
        \\    {
        \\      "Total": {
        \\        "UnblendedCost": {
        \\          "Amount": "12.3400000000",
        \\          "Unit": "USD"
        \\        }
        \\      }
        \\    }
        \\  ]
        \\}
    )).?;
    defer money.deinit(std.testing.allocator);
    try std.testing.expectEqualStrings("12.3400000000", money.amount);
    try std.testing.expectEqualStrings("USD", money.unit);
}

test "parses gcp billing accounts array response" {
    var account = (try parseGcpPrimaryBillingAccountAlloc(std.testing.allocator,
        \\[
        \\  {"name":"billingAccounts/000000-111111-222222","displayName":"Prod Billing","open":true}
        \\]
    )).?;
    defer account.deinit(std.testing.allocator);
    try std.testing.expectEqualStrings("billingAccounts/000000-111111-222222", account.name);
    try std.testing.expectEqualStrings("Prod Billing", account.display_name);
    try std.testing.expect(account.open);
}

test "parses gcp billing accounts REST response" {
    var account = (try parseGcpPrimaryBillingAccountAlloc(std.testing.allocator,
        \\{
        \\  "billingAccounts": [
        \\    {"name":"billingAccounts/closed","displayName":"Closed","open":false},
        \\    {"name":"billingAccounts/open","displayName":"Open","open":true}
        \\  ]
        \\}
    )).?;
    defer account.deinit(std.testing.allocator);
    try std.testing.expectEqualStrings("billingAccounts/open", account.name);
    try std.testing.expectEqualStrings("Open", account.display_name);
}

test "rejects malformed aws date" {
    try std.testing.expectError(error.InvalidDate, awsGetCostAndUsagePayloadAlloc(std.testing.allocator, "20260601", "2026-07-01"));
}
