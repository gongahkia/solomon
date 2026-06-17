const std = @import("std");

pub const module_id = "cost_glance";
pub const aws_ce_endpoint = "https://ce.us-east-1.amazonaws.com";
pub const aws_ce_target = "AWSInsightsIndexService.GetCostAndUsage";
pub const aws_ce_service = "ce";
pub const aws_ce_region = "us-east-1";
pub const gcp_billing_endpoint = "https://cloudbilling.googleapis.com/v1";
pub const azure_management_endpoint = "https://management.azure.com";
pub const azure_cost_management_api_version = "2025-03-01";

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

pub const CostRecord = struct {
    provider: []const u8,
    amount: []const u8,
    unit: []const u8,
    updated: i64,
};

pub const CachedCostRecord = struct {
    provider: []u8,
    amount: []u8,
    unit: []u8,
    updated: i64,

    pub fn deinit(self: *CachedCostRecord, allocator: std.mem.Allocator) void {
        allocator.free(self.provider);
        allocator.free(self.amount);
        allocator.free(self.unit);
        self.* = undefined;
    }
};

const CostCacheJson = struct {
    v: u32 = 0,
    updated: i64 = 0,
    providers: []CostRecordJson = &.{},
};

const CostRecordJson = struct {
    provider: []const u8 = "",
    amount: []const u8 = "",
    unit: []const u8 = "",
    updated: i64 = 0,
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

pub fn azureCostManagementQueryUrlAlloc(allocator: std.mem.Allocator, scope: []const u8) ![]u8 {
    const trimmed = std.mem.trim(u8, scope, " \t\r\n/");
    if (trimmed.len == 0) return error.InvalidScope;
    return std.fmt.allocPrint(
        allocator,
        "{s}/{s}/providers/Microsoft.CostManagement/query?api-version={s}",
        .{ azure_management_endpoint, trimmed, azure_cost_management_api_version },
    );
}

pub fn azureMonthToDatePayloadAlloc(allocator: std.mem.Allocator) ![]u8 {
    return allocator.dupe(u8, "{\"type\":\"Usage\",\"timeframe\":\"MonthToDate\",\"dataset\":{\"granularity\":\"None\",\"aggregation\":{\"totalCost\":{\"name\":\"PreTaxCost\",\"function\":\"Sum\"}}}}");
}

pub fn azureCostManagementCliArgvAlloc(allocator: std.mem.Allocator, scope: []const u8) ![][]u8 {
    const url = try azureCostManagementQueryUrlAlloc(allocator, scope);
    errdefer allocator.free(url);
    const body = try azureMonthToDatePayloadAlloc(allocator);
    errdefer allocator.free(body);
    var args: std.ArrayList([]u8) = .empty;
    errdefer {
        freePartialArgv(allocator, args.items);
        args.deinit(allocator);
    }
    try appendArg(allocator, &args, "az");
    try appendArg(allocator, &args, "rest");
    try appendArg(allocator, &args, "--method");
    try appendArg(allocator, &args, "post");
    try appendArg(allocator, &args, "--url");
    try args.append(allocator, url);
    try appendArg(allocator, &args, "--body");
    try args.append(allocator, body);
    try appendArg(allocator, &args, "--output");
    try appendArg(allocator, &args, "json");
    return args.toOwnedSlice(allocator);
}

pub fn costCachePathAlloc(allocator: std.mem.Allocator, home: ?[]const u8) !?[]u8 {
    const home_path = home orelse return null;
    return @as(?[]u8, try std.fmt.allocPrint(allocator, "{s}/.local/state/shisa/cost.json", .{home_path}));
}

pub fn writeCostCache(allocator: std.mem.Allocator, path: []const u8, records: []const CostRecord, updated: i64) !void {
    if (std.fs.path.dirname(path)) |parent| try std.fs.cwd().makePath(parent);
    const tmp_path = try std.fmt.allocPrint(allocator, "{s}.tmp", .{path});
    defer allocator.free(tmp_path);
    errdefer std.fs.deleteFileAbsolute(tmp_path) catch {};
    {
        var file = try std.fs.createFileAbsolute(tmp_path, .{ .truncate = true, .mode = 0o600 });
        errdefer file.close();
        try file.writeAll("{\"v\":1,\"updated\":");
        try writeInt(file, updated);
        try file.writeAll(",\"providers\":[");
        for (records, 0..) |record, index| {
            if (index != 0) try file.writeAll(",");
            try file.writeAll("{\"provider\":");
            try writeJsonString(file, record.provider);
            try file.writeAll(",\"amount\":");
            try writeJsonString(file, record.amount);
            try file.writeAll(",\"unit\":");
            try writeJsonString(file, record.unit);
            try file.writeAll(",\"updated\":");
            try writeInt(file, record.updated);
            try file.writeAll("}");
        }
        try file.writeAll("]}\n");
        try file.sync();
        file.close();
    }
    std.fs.renameAbsolute(tmp_path, path) catch |err| switch (err) {
        error.FileNotFound => return err,
        else => return err,
    };
}

pub fn readCostCacheAlloc(allocator: std.mem.Allocator, path: []const u8) ![]CachedCostRecord {
    const source = std.fs.cwd().readFileAlloc(allocator, path, 1024 * 1024) catch |err| switch (err) {
        error.FileNotFound => return allocator.alloc(CachedCostRecord, 0),
        else => return err,
    };
    defer allocator.free(source);
    var parsed = std.json.parseFromSlice(CostCacheJson, allocator, source, .{ .ignore_unknown_fields = true }) catch return allocator.alloc(CachedCostRecord, 0);
    defer parsed.deinit();
    var out: std.ArrayList(CachedCostRecord) = .empty;
    errdefer {
        for (out.items) |*record| record.deinit(allocator);
        out.deinit(allocator);
    }
    for (parsed.value.providers) |record| {
        const provider = std.mem.trim(u8, record.provider, " \t\r\n");
        const amount = std.mem.trim(u8, record.amount, " \t\r\n");
        const unit = std.mem.trim(u8, record.unit, " \t\r\n");
        if (provider.len == 0 or amount.len == 0 or unit.len == 0) continue;
        const owned_provider = try allocator.dupe(u8, provider);
        errdefer allocator.free(owned_provider);
        const owned_amount = try allocator.dupe(u8, amount);
        errdefer allocator.free(owned_amount);
        try out.append(allocator, .{
            .provider = owned_provider,
            .amount = owned_amount,
            .unit = try allocator.dupe(u8, unit),
            .updated = record.updated,
        });
    }
    return out.toOwnedSlice(allocator);
}

pub fn freeCachedRecords(allocator: std.mem.Allocator, records: []CachedCostRecord) void {
    for (records) |*record| record.deinit(allocator);
    allocator.free(records);
}

pub fn refreshCacheFromEnvironment(allocator: std.mem.Allocator, home: ?[]const u8, timestamp: i64) !bool {
    const path = (try costCachePathAlloc(allocator, home)) orelse return false;
    defer allocator.free(path);

    var records: [2]CostRecord = undefined;
    var len: usize = 0;

    var aws_money: ?Money = null;
    defer if (aws_money) |*money| money.deinit(allocator);
    const aws_start = envOwned(allocator, "SHISA_COST_AWS_START") catch null;
    defer if (aws_start) |value| allocator.free(value);
    const aws_end = envOwned(allocator, "SHISA_COST_AWS_END") catch null;
    defer if (aws_end) |value| allocator.free(value);
    if (aws_start != null and aws_end != null) {
        const profile = envOwned(allocator, "AWS_PROFILE") catch null;
        defer if (profile) |value| allocator.free(value);
        aws_money = try readAwsMonthlyCostWithCliAlloc(allocator, profile, aws_start.?, aws_end.?);
        if (aws_money) |money| {
            records[len] = .{ .provider = "aws", .amount = money.amount, .unit = money.unit, .updated = timestamp };
            len += 1;
        }
    }

    var azure_money: ?Money = null;
    defer if (azure_money) |*money| money.deinit(allocator);
    const azure_scope = envOwned(allocator, "SHISA_COST_AZURE_SCOPE") catch null;
    defer if (azure_scope) |value| allocator.free(value);
    if (azure_scope) |scope| {
        azure_money = try readAzureMonthToDateCostWithCliAlloc(allocator, scope);
        if (azure_money) |money| {
            records[len] = .{ .provider = "az", .amount = money.amount, .unit = money.unit, .updated = timestamp };
            len += 1;
        }
    }

    if (len == 0) return false;
    try writeCostCache(allocator, path, records[0..len], timestamp);
    return true;
}

pub fn render(allocator: std.mem.Allocator, home: ?[]const u8) !?[]u8 {
    const path = (try costCachePathAlloc(allocator, home)) orelse return null;
    defer allocator.free(path);
    const records = try readCostCacheAlloc(allocator, path);
    defer freeCachedRecords(allocator, records);
    return renderRecordsAlloc(allocator, records);
}

pub fn renderRecordsAlloc(allocator: std.mem.Allocator, records: []const CachedCostRecord) !?[]u8 {
    if (records.len == 0) return null;
    var out: std.ArrayList(u8) = .empty;
    errdefer out.deinit(allocator);
    try out.appendSlice(allocator, "cost[");
    for (records, 0..) |record, index| {
        if (index != 0) try out.append(allocator, ' ');
        try out.appendSlice(allocator, record.provider);
        try out.append(allocator, ':');
        try appendCompactMoney(allocator, &out, record.amount, record.unit);
    }
    try out.append(allocator, ']');
    return @as(?[]u8, try out.toOwnedSlice(allocator));
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

pub fn readAzureMonthToDateCostWithCliAlloc(allocator: std.mem.Allocator, scope: []const u8) !?Money {
    const argv = try azureCostManagementCliArgvAlloc(allocator, scope);
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
    }) return error.AzureCliFailed;
    return parseAzurePreTaxCostAlloc(allocator, result.stdout);
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

pub fn parseAzurePreTaxCostAlloc(allocator: std.mem.Allocator, source: []const u8) !?Money {
    var parsed = std.json.parseFromSlice(std.json.Value, allocator, source, .{}) catch return null;
    defer parsed.deinit();
    const properties = jsonObjectField(parsed.value, "properties") orelse return null;
    const columns = jsonArrayField(properties, "columns") orelse return null;
    const rows = jsonArrayField(properties, "rows") orelse return null;
    const amount_index = azureColumnIndex(columns, "PreTaxCost") orelse return null;
    const currency_index = azureColumnIndex(columns, "Currency");
    for (rows.items) |row_value| {
        const row = switch (row_value) {
            .array => |array| array,
            else => continue,
        };
        if (amount_index >= row.items.len) continue;
        const amount = (try jsonScalarTextAlloc(allocator, row.items[amount_index])) orelse continue;
        errdefer allocator.free(amount);
        const unit = if (currency_index) |index| unit: {
            if (index < row.items.len) {
                if (try jsonScalarTextAlloc(allocator, row.items[index])) |value| break :unit value;
            }
            break :unit try allocator.dupe(u8, "USD");
        } else try allocator.dupe(u8, "USD");
        return Money{ .amount = amount, .unit = unit };
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

fn azureColumnIndex(columns: std.json.Array, name: []const u8) ?usize {
    for (columns.items, 0..) |column, index| {
        const column_name = jsonObjectStringField(column, "name") orelse continue;
        if (std.mem.eql(u8, column_name, name)) return index;
    }
    return null;
}

fn jsonObjectField(value: std.json.Value, name: []const u8) ?std.json.Value {
    return switch (value) {
        .object => |object| object.get(name),
        else => null,
    };
}

fn jsonArrayField(value: std.json.Value, name: []const u8) ?std.json.Array {
    const field = jsonObjectField(value, name) orelse return null;
    return switch (field) {
        .array => |array| array,
        else => null,
    };
}

fn jsonObjectStringField(value: std.json.Value, name: []const u8) ?[]const u8 {
    const field = jsonObjectField(value, name) orelse return null;
    return switch (field) {
        .string => |text| text,
        else => null,
    };
}

fn jsonScalarTextAlloc(allocator: std.mem.Allocator, value: std.json.Value) !?[]u8 {
    return switch (value) {
        .string => |text| try trimmedDupeAlloc(allocator, text),
        .number_string => |text| try trimmedDupeAlloc(allocator, text),
        .integer => |number| @as(?[]u8, try std.fmt.allocPrint(allocator, "{d}", .{number})),
        .float => |number| @as(?[]u8, try std.fmt.allocPrint(allocator, "{d}", .{number})),
        else => null,
    };
}

fn trimmedDupeAlloc(allocator: std.mem.Allocator, value: []const u8) !?[]u8 {
    const trimmed = std.mem.trim(u8, value, " \t\r\n");
    if (trimmed.len == 0) return null;
    return @as(?[]u8, try allocator.dupe(u8, trimmed));
}

fn envOwned(allocator: std.mem.Allocator, name: []const u8) !?[]u8 {
    const value = std.process.getEnvVarOwned(allocator, name) catch |err| switch (err) {
        error.EnvironmentVariableNotFound => return null,
        else => return err,
    };
    const trimmed = std.mem.trim(u8, value, " \t\r\n");
    if (trimmed.len == 0) {
        allocator.free(value);
        return null;
    }
    return value;
}

fn writeInt(file: std.fs.File, value: i64) !void {
    var buffer: [32]u8 = undefined;
    const text = try std.fmt.bufPrint(&buffer, "{d}", .{value});
    try file.writeAll(text);
}

fn writeJsonString(file: std.fs.File, value: []const u8) !void {
    try file.writeAll("\"");
    for (value) |byte| {
        switch (byte) {
            '"' => try file.writeAll("\\\""),
            '\\' => try file.writeAll("\\\\"),
            '\n' => try file.writeAll("\\n"),
            '\r' => try file.writeAll("\\r"),
            '\t' => try file.writeAll("\\t"),
            else => try file.writeAll(&.{byte}),
        }
    }
    try file.writeAll("\"");
}

fn appendCompactMoney(allocator: std.mem.Allocator, out: *std.ArrayList(u8), amount: []const u8, unit: []const u8) !void {
    const trimmed_amount = std.mem.trim(u8, amount, " \t\r\n");
    const trimmed_unit = std.mem.trim(u8, unit, " \t\r\n");
    const parsed = std.fmt.parseFloat(f64, trimmed_amount) catch null;
    if (std.ascii.eqlIgnoreCase(trimmed_unit, "USD")) {
        try out.append(allocator, '$');
        if (parsed) |value| {
            try appendFmt(allocator, out, "{d:.2}", .{value});
        } else {
            try out.appendSlice(allocator, trimmed_amount);
        }
        return;
    }
    if (parsed) |value| {
        try appendFmt(allocator, out, "{d:.2}{s}", .{ value, trimmed_unit });
    } else {
        try out.appendSlice(allocator, trimmed_amount);
        try out.appendSlice(allocator, trimmed_unit);
    }
}

fn appendFmt(allocator: std.mem.Allocator, out: *std.ArrayList(u8), comptime format: []const u8, args: anytype) !void {
    const text = try std.fmt.allocPrint(allocator, format, args);
    defer allocator.free(text);
    try out.appendSlice(allocator, text);
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

test "builds azure cost management REST URL" {
    const url = try azureCostManagementQueryUrlAlloc(std.testing.allocator, "/subscriptions/00000000-0000-0000-0000-000000000000/");
    defer std.testing.allocator.free(url);
    try std.testing.expectEqualStrings("https://management.azure.com/subscriptions/00000000-0000-0000-0000-000000000000/providers/Microsoft.CostManagement/query?api-version=2025-03-01", url);
}

test "builds azure cost management payload" {
    const payload = try azureMonthToDatePayloadAlloc(std.testing.allocator);
    defer std.testing.allocator.free(payload);
    try std.testing.expectEqualStrings("{\"type\":\"Usage\",\"timeframe\":\"MonthToDate\",\"dataset\":{\"granularity\":\"None\",\"aggregation\":{\"totalCost\":{\"name\":\"PreTaxCost\",\"function\":\"Sum\"}}}}", payload);
}

test "builds azure cost management cli argv" {
    const argv = try azureCostManagementCliArgvAlloc(std.testing.allocator, "subscriptions/sub-1");
    defer freeArgv(std.testing.allocator, argv);
    const expected = [_][]const u8{ "az", "rest", "--method", "post", "--url", "https://management.azure.com/subscriptions/sub-1/providers/Microsoft.CostManagement/query?api-version=2025-03-01", "--body", "{\"type\":\"Usage\",\"timeframe\":\"MonthToDate\",\"dataset\":{\"granularity\":\"None\",\"aggregation\":{\"totalCost\":{\"name\":\"PreTaxCost\",\"function\":\"Sum\"}}}}", "--output", "json" };
    try std.testing.expectEqual(expected.len, argv.len);
    for (expected, 0..) |value, index| try std.testing.expectEqualStrings(value, argv[index]);
}

test "builds cost cache path" {
    const path = (try costCachePathAlloc(std.testing.allocator, "/home/me")).?;
    defer std.testing.allocator.free(path);
    try std.testing.expectEqualStrings("/home/me/.local/state/shisa/cost.json", path);
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

test "writes and reads cost cache" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-cost-cache-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    const path = try std.fmt.allocPrint(allocator, "{s}/.local/state/shisa/cost.json", .{dir_path});
    defer allocator.free(path);

    try writeCostCache(allocator, path, &.{
        .{ .provider = "aws", .amount = "12.34", .unit = "USD", .updated = 10 },
        .{ .provider = "az", .amount = "5.67", .unit = "USD", .updated = 10 },
    }, 10);

    const records = try readCostCacheAlloc(allocator, path);
    defer freeCachedRecords(allocator, records);
    try std.testing.expectEqual(@as(usize, 2), records.len);
    try std.testing.expectEqualStrings("aws", records[0].provider);
    try std.testing.expectEqualStrings("12.34", records[0].amount);
    try std.testing.expectEqualStrings("USD", records[0].unit);
    try std.testing.expectEqualStrings("az", records[1].provider);
}

test "renders cached cost records" {
    var records = [_]CachedCostRecord{
        .{ .provider = try std.testing.allocator.dupe(u8, "aws"), .amount = try std.testing.allocator.dupe(u8, "12.3400000000"), .unit = try std.testing.allocator.dupe(u8, "USD"), .updated = 10 },
        .{ .provider = try std.testing.allocator.dupe(u8, "az"), .amount = try std.testing.allocator.dupe(u8, "5.67"), .unit = try std.testing.allocator.dupe(u8, "USD"), .updated = 10 },
    };
    defer for (&records) |*record| record.deinit(std.testing.allocator);
    const segment = (try renderRecordsAlloc(std.testing.allocator, records[0..])).?;
    defer std.testing.allocator.free(segment);
    try std.testing.expectEqualStrings("cost[aws:$12.34 az:$5.67]", segment);
}

test "renders cost cache from home" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-cost-render-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    const path = (try costCachePathAlloc(allocator, dir_path)).?;
    defer allocator.free(path);
    try writeCostCache(allocator, path, &.{
        .{ .provider = "aws", .amount = "1.2", .unit = "USD", .updated = 10 },
    }, 10);
    const segment = (try render(allocator, dir_path)).?;
    defer allocator.free(segment);
    try std.testing.expectEqualStrings("cost[aws:$1.20]", segment);
}

test "parses azure cost management response" {
    var money = (try parseAzurePreTaxCostAlloc(std.testing.allocator,
        \\{
        \\  "properties": {
        \\    "columns": [
        \\      {"name":"PreTaxCost","type":"Number"},
        \\      {"name":"Currency","type":"String"}
        \\    ],
        \\    "rows": [
        \\      [12.34, "USD"]
        \\    ]
        \\  }
        \\}
    )).?;
    defer money.deinit(std.testing.allocator);
    try std.testing.expectEqualStrings("12.34", money.amount);
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

test "rejects empty azure scope" {
    try std.testing.expectError(error.InvalidScope, azureCostManagementQueryUrlAlloc(std.testing.allocator, " / "));
}
