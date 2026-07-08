const std = @import("std");
const builtin = @import("builtin");
const build_options = @import("build_options");
const cli_config = @import("cli/config.zig");
const cli_doctor = @import("cli/doctor.zig");
const cli_plugin = @import("cli/plugin.zig");
const cli_stack = @import("cli/stack.zig");
const cli_theme = @import("cli/theme.zig");
const cli_util = @import("cli/util.zig");
const cli_worktree = @import("cli/worktree.zig");
const daemon_cache = @import("daemon/cache.zig");
const daemon_json = @import("daemon/json.zig");
const dispatcher = @import("daemon/dispatcher.zig");
const client = @import("shisa-client.zig");
const cloud_ctx_module = @import("daemon/modules/cloud_ctx.zig");
const git_branch_module = @import("daemon/modules/git_branch.zig");
const language_versions_module = @import("daemon/modules/language_versions.zig");
const shisa_config = @import("config.zig");
const paths = @import("daemon/paths.zig");
const proto = @import("proto/types.zig");
const prod_guard_module = @import("daemon/modules/prod_guard.zig");
const risk_tier_module = @import("daemon/modules/risk_tier.zig");
const supervisor = @import("supervisor.zig");
const theme_loader = @import("theme/loader.zig");

const version = "0.1.0-dev";
const max_config_bytes = 1024 * 1024;
const max_vouches_bytes = 256 * 1024;

pub fn main() !void {
    var gpa_impl = std.heap.GeneralPurposeAllocator(.{}){};
    defer _ = gpa_impl.deinit();
    const allocator = gpa_impl.allocator();

    const args = try std.process.argsAlloc(allocator);
    defer std.process.argsFree(allocator, args);

    if (args.len == 1 or std.mem.eql(u8, args[1], "--help") or std.mem.eql(u8, args[1], "-h")) {
        try std.fs.File.stdout().writeAll(help_text);
        return;
    }

    if (std.mem.eql(u8, args[1], "--version")) {
        try std.fs.File.stdout().writeAll("shisa " ++ version ++ "\n");
        return;
    }

    if (std.mem.eql(u8, args[1], "supervisor")) {
        try supervisor.run(allocator, args[2..]);
        return;
    }

    if (std.mem.eql(u8, args[1], "init")) {
        try cli_config.initCmd(allocator, args[2..]);
        return;
    }

    if (std.mem.eql(u8, args[1], "config")) {
        try cli_config.setCmd(allocator, args[2..]);
        return;
    }

    if (std.mem.eql(u8, args[1], "explain")) {
        try cli_config.explainCmd(allocator, args[2..]);
        return;
    }

    if (std.mem.eql(u8, args[1], "doctor")) {
        try cli_doctor.command(allocator, args[2..]);
        return;
    }

    if (std.mem.eql(u8, args[1], "report")) {
        try cli_doctor.reportCommand(allocator, args[2..], .{ .version = version, .iteration = reportPromptPayloadBenchIterationAlloc });
        return;
    }

    if (std.mem.eql(u8, args[1], "font")) {
        try fontCommand(allocator, args[2..]);
        return;
    }

    if (std.mem.eql(u8, args[1], "vouch")) {
        try vouchCommand(allocator, args[2..]);
        return;
    }

    if (std.mem.eql(u8, args[1], "cloud")) {
        try cloudCommand(allocator, args[2..]);
        return;
    }

    if (std.mem.eql(u8, args[1], "import-starship")) {
        try importStarship(allocator, args[2..]);
        return;
    }

    if (std.mem.eql(u8, args[1], "import-p10k")) {
        try importP10k(allocator, args[2..]);
        return;
    }

    if (std.mem.eql(u8, args[1], "import-oh-my-posh")) {
        try importOhMyPosh(allocator, args[2..]);
        return;
    }

    if (std.mem.eql(u8, args[1], "import-tide")) {
        try importTide(allocator, args[2..]);
        return;
    }

    if (std.mem.eql(u8, args[1], "import-pure")) {
        try importPure(allocator, args[2..]);
        return;
    }

    if (std.mem.eql(u8, args[1], "bench")) {
        try bench(allocator, args[2..]);
        return;
    }

    if (std.mem.eql(u8, args[1], "cache")) {
        try cacheCommand(allocator, args[2..]);
        return;
    }

    if (std.mem.eql(u8, args[1], "pin")) {
        try pinCommand(allocator, args[2..]);
        return;
    }

    if (std.mem.eql(u8, args[1], "plugin")) {
        try cli_plugin.command(allocator, args[2..]);
        return;
    }

    if (std.mem.eql(u8, args[1], "theme")) {
        try cli_theme.command(allocator, args[2..]);
        return;
    }

    if (build_options.vcs_extra and std.mem.eql(u8, args[1], "stack")) {
        try cli_stack.command(allocator, args[2..]);
        return;
    }

    if (build_options.vcs_extra and std.mem.eql(u8, args[1], "worktrees")) {
        try cli_worktree.command(allocator, args[2..]);
        return;
    }

    if (std.mem.eql(u8, args[1], "prompt") or std.mem.eql(u8, args[1], "render")) {
        try prompt(allocator, args[2..]);
        return;
    }

    try std.fs.File.stderr().writeAll("shisa: unknown command; run `shisa --help`\n");
    return error.UnknownCommand;
}

test "smoke" {
    try std.testing.expect(true);
}

fn fontCommand(allocator: std.mem.Allocator, args: []const []const u8) !void {
    if (args.len == 0 or std.mem.eql(u8, args[0], "--help") or std.mem.eql(u8, args[0], "-h")) {
        try std.fs.File.stdout().writeAll(font_help_text);
        return;
    }
    if (!std.mem.eql(u8, args[0], "check")) return error.UnknownFontCommand;
    if (args.len != 1) return error.UnknownFontArgument;

    const report = try fontCheckReportAlloc(allocator);
    defer allocator.free(report);
    try std.fs.File.stdout().writeAll(report);
}

fn fontCheckReportAlloc(allocator: std.mem.Allocator) ![]u8 {
    return std.fmt.allocPrint(
        allocator,
        "font check: render probe\nnerd-font: {s}  private-use branch glyph\nunicode:   {s}  unicode arrow fallback\nascii:     {s} ascii fallback\nfont check: inspect output for missing-glyph boxes\n",
        .{ "\xee\x82\xa0", "\xe2\x86\x92", "->" },
    );
}

test "font check report includes fallback tiers" {
    const report = try fontCheckReportAlloc(std.testing.allocator);
    defer std.testing.allocator.free(report);

    try std.testing.expect(std.mem.indexOf(u8, report, "nerd-font: \xee\x82\xa0") != null);
    try std.testing.expect(std.mem.indexOf(u8, report, "unicode:   \xe2\x86\x92") != null);
    try std.testing.expect(std.mem.indexOf(u8, report, "ascii:     ->") != null);
}

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

fn vouchCommand(allocator: std.mem.Allocator, args: []const []const u8) !void {
    if (args.len == 1 and (std.mem.eql(u8, args[0], "--help") or std.mem.eql(u8, args[0], "-h"))) {
        try std.fs.File.stdout().writeAll(vouch_help_text);
        return;
    }
    if (args.len == 0 or !std.mem.eql(u8, args[0], "verify")) {
        try std.fs.File.stderr().writeAll("shisa vouch: unknown command; run `shisa vouch --help`\n");
        return error.UnknownVouchCommand;
    }
    if (args.len > 2) return error.UnknownVouchArgument;
    if (args.len == 2 and (std.mem.eql(u8, args[1], "--help") or std.mem.eql(u8, args[1], "-h"))) {
        try std.fs.File.stdout().writeAll(vouch_help_text);
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

fn cloudCommand(allocator: std.mem.Allocator, args: []const []const u8) !void {
    if (args.len >= 1 and std.mem.eql(u8, args[0], "preexec")) {
        const config = try parseCloudPreexecArgs(args[1..]);
        try cloudPreexec(allocator, config);
        return;
    }
    if (args.len == 1 and std.mem.eql(u8, args[0], "audit")) {
        try cloudAudit(allocator);
        return;
    }
    if (args.len == 1 and std.mem.eql(u8, args[0], "doctor")) {
        try cloudDoctor(allocator);
        return;
    }
    if (args.len != 2 or !std.mem.eql(u8, args[0], "explain")) return error.UnknownCloudArgument;
    const home = std.process.getEnvVarOwned(allocator, "HOME") catch |err| switch (err) {
        error.EnvironmentVariableNotFound => null,
        else => return err,
    };
    defer if (home) |value| allocator.free(value);
    const output = try cloudExplainAlloc(allocator, args[1], home);
    defer allocator.free(output);
    try std.fs.File.stdout().writeAll(output);
}

fn cloudDoctor(allocator: std.mem.Allocator) !void {
    const home = std.process.getEnvVarOwned(allocator, "HOME") catch |err| switch (err) {
        error.EnvironmentVariableNotFound => null,
        else => return err,
    };
    defer if (home) |value| allocator.free(value);
    const aws_profile = std.process.getEnvVarOwned(allocator, "AWS_PROFILE") catch |err| switch (err) {
        error.EnvironmentVariableNotFound => null,
        else => return err,
    };
    defer if (aws_profile) |value| allocator.free(value);
    const kubeconfig = std.process.getEnvVarOwned(allocator, "KUBECONFIG") catch |err| switch (err) {
        error.EnvironmentVariableNotFound => null,
        else => return err,
    };
    defer if (kubeconfig) |value| allocator.free(value);

    const output = try cloudDoctorAlloc(allocator, home, aws_profile, kubeconfig);
    defer allocator.free(output);
    try std.fs.File.stdout().writeAll(output);
}

fn cloudDoctorAlloc(allocator: std.mem.Allocator, home: ?[]const u8, aws_profile_env: ?[]const u8, kubeconfig_env: ?[]const u8) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);

    var cache = cloud_ctx_module.Cache{};
    defer cache.deinit(allocator);

    const aws_profile = try cloud_ctx_module.awsProfileAlloc(allocator, aws_profile_env, home);
    defer if (aws_profile) |value| allocator.free(value);
    try cli_util.appendFmt(allocator, &out, "aws_profile: {s}\n", .{aws_profile orelse "-"});

    const gcp_path = try cloud_ctx_module.gcpConfigPathAlloc(allocator, home);
    defer if (gcp_path) |value| allocator.free(value);
    try appendCloudPathLine(allocator, &out, "gcp_config", gcp_path);
    const gcp_project = try cache.gcpProjectAlloc(allocator, home);
    defer if (gcp_project) |value| allocator.free(value);
    try cli_util.appendFmt(allocator, &out, "gcp_project: {s}\n", .{gcp_project orelse "-"});

    const azure_path = try cloud_ctx_module.azureProfilePathAlloc(allocator, home);
    defer if (azure_path) |value| allocator.free(value);
    try appendCloudPathLine(allocator, &out, "azure_profile", azure_path);
    const azure_subscription = try cache.azureSubscriptionAlloc(allocator, home);
    defer if (azure_subscription) |value| allocator.free(value);
    try cli_util.appendFmt(allocator, &out, "azure_subscription: {s}\n", .{azure_subscription orelse "-"});

    const kube_path = try cloud_ctx_module.kubeConfigPathAlloc(allocator, kubeconfig_env, home);
    defer if (kube_path) |value| allocator.free(value);
    try appendCloudPathLine(allocator, &out, "kubeconfig", kube_path);
    const kube_context = try cache.kubeContextAlloc(allocator, kubeconfig_env, home);
    defer if (kube_context) |value| allocator.free(value);
    try cli_util.appendFmt(allocator, &out, "kube_context: {s}\n", .{kube_context orelse "-"});

    return out.toOwnedSlice(allocator);
}

fn appendCloudPathLine(allocator: std.mem.Allocator, out: *std.ArrayList(u8), label: []const u8, path: ?[]const u8) !void {
    if (path) |value| {
        try cli_util.appendFmt(allocator, out, "{s}: {s} {s}\n", .{ label, cli_util.pathAccessStatus(value), value });
    } else {
        try cli_util.appendFmt(allocator, out, "{s}: missing\n", .{label});
    }
}

fn cloudAudit(allocator: std.mem.Allocator) !void {
    const home = try std.process.getEnvVarOwned(allocator, "HOME");
    defer allocator.free(home);
    const output = try cloudAuditAlloc(allocator, home);
    defer allocator.free(output);
    try std.fs.File.stdout().writeAll(output);
}

fn cloudAuditAlloc(allocator: std.mem.Allocator, home: []const u8) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);
    const cloud_path = try cloudRequestAuditPathAlloc(allocator, home);
    defer allocator.free(cloud_path);
    try appendAuditFileIfExists(allocator, &out, cloud_path);
    const prod_path = try prodGuardAuditPathAlloc(allocator, home);
    defer allocator.free(prod_path);
    try appendAuditFileIfExists(allocator, &out, prod_path);
    return out.toOwnedSlice(allocator);
}

fn appendAuditFileIfExists(allocator: std.mem.Allocator, out: *std.ArrayList(u8), path: []const u8) !void {
    const contents = std.fs.cwd().readFileAlloc(allocator, path, max_config_bytes) catch |err| switch (err) {
        error.FileNotFound => return,
        else => return err,
    };
    defer allocator.free(contents);
    try out.appendSlice(allocator, contents);
}

fn cloudRequestAuditPathAlloc(allocator: std.mem.Allocator, home: []const u8) ![]u8 {
    return std.fmt.allocPrint(allocator, "{s}/.local/state/shisa/cloud_requests.jsonl", .{home});
}

fn prodGuardAuditPathAlloc(allocator: std.mem.Allocator, home: []const u8) ![]u8 {
    return std.fmt.allocPrint(allocator, "{s}/.local/state/shisa/prod_guard.jsonl", .{home});
}

const CloudPreexec = struct {
    socket_path: ?[]const u8 = null,
    shell: []const u8 = "",
    command: []const u8,
    force: bool = false,
};

const CloudPreexecResponse = struct {
    v: u32 = 1,
    allow: bool = true,
    confirm: []const u8 = "",
    tier: []const u8 = "unknown",
    destructive_pattern: []const u8 = "-",
    warning: []const u8 = "",
};

fn parseCloudPreexecArgs(args: []const []const u8) !CloudPreexec {
    var parsed = CloudPreexec{ .command = "" };
    var i: usize = 0;
    while (i < args.len) : (i += 1) {
        const arg = args[i];
        if (std.mem.eql(u8, arg, "--socket")) {
            parsed.socket_path = try cli_util.nextValue(args, &i);
        } else if (std.mem.eql(u8, arg, "--shell")) {
            parsed.shell = try cli_util.nextValue(args, &i);
        } else if (std.mem.eql(u8, arg, "--force")) {
            parsed.force = true;
        } else if (std.mem.eql(u8, arg, "--")) {
            parsed.command = try cli_util.nextValue(args, &i);
            if (i + 1 != args.len) return error.UnknownCloudArgument;
        } else if (parsed.command.len == 0) {
            parsed.command = arg;
        } else {
            return error.UnknownCloudArgument;
        }
    }
    if (parsed.command.len == 0) return error.MissingValue;
    return parsed;
}

fn cloudPreexec(allocator: std.mem.Allocator, config: CloudPreexec) !void {
    const socket_path = if (config.socket_path) |path| path else try paths.defaultSocketPath(allocator);
    defer if (config.socket_path == null) allocator.free(socket_path);
    const payload = try buildCloudPreexecPayload(allocator, config);
    defer allocator.free(payload);
    const response = client.requestAlloc(allocator, socket_path, payload) catch return;
    defer allocator.free(response);
    try enforceCloudPreexecResponse(allocator, response);
}

fn buildCloudPreexecPayload(allocator: std.mem.Allocator, config: CloudPreexec) ![]u8 {
    const cwd = try std.fs.cwd().realpathAlloc(allocator, ".");
    defer allocator.free(cwd);
    const escaped_cwd = try daemon_json.escapeAlloc(allocator, cwd);
    defer allocator.free(escaped_cwd);
    const escaped_shell = try daemon_json.escapeAlloc(allocator, config.shell);
    defer allocator.free(escaped_shell);
    const escaped_command = try daemon_json.escapeAlloc(allocator, config.command);
    defer allocator.free(escaped_command);
    return std.fmt.allocPrint(
        allocator,
        "{{\"v\":1,\"kind\":\"preexec\",\"cwd\":\"{s}\",\"shell\":\"{s}\",\"command\":\"{s}\",\"force\":{}}}",
        .{ escaped_cwd, escaped_shell, escaped_command, config.force },
    );
}

fn cloudExplainAlloc(allocator: std.mem.Allocator, value: []const u8, home: ?[]const u8) ![]u8 {
    var rules = try risk_tier_module.loadUserRulesAlloc(allocator, home);
    defer if (rules) |*loaded| loaded.deinit(allocator);
    const reason = risk_tier_module.explain(value, rules);
    const pattern = if (reason.pattern.len == 0) "-" else reason.pattern;
    return std.fmt.allocPrint(
        allocator,
        "value: {s}\ntier: {s}\nsource: {s}\npattern: {s}\n",
        .{ value, risk_tier_module.tierName(reason.tier), risk_tier_module.sourceName(reason.source), pattern },
    );
}

fn enforceCloudPreexecResponse(allocator: std.mem.Allocator, response: []const u8) !void {
    var parsed = try std.json.parseFromSlice(CloudPreexecResponse, allocator, response, .{ .ignore_unknown_fields = true });
    defer parsed.deinit();
    if (parsed.value.warning.len != 0) try printCloudPreexecWarning(parsed.value.warning);
    if (parsed.value.allow) return;
    if (parsed.value.confirm.len == 0) return error.PreexecDenied;
    try promptTierConfirmation(parsed.value);
}

fn printCloudPreexecWarning(warning: []const u8) !void {
    const stderr = std.fs.File.stderr();
    try stderr.writeAll("shisa warning: ");
    try stderr.writeAll(warning);
    try stderr.writeAll("\n");
}

fn promptTierConfirmation(decision: CloudPreexecResponse) !void {
    const stderr = std.fs.File.stderr();
    try stderr.writeAll("shisa prod_guard: ");
    try stderr.writeAll(decision.destructive_pattern);
    try stderr.writeAll(" in ");
    try stderr.writeAll(decision.tier);
    try stderr.writeAll("; type ");
    try stderr.writeAll(decision.confirm);
    try stderr.writeAll(" to proceed: ");

    var buffer: [128]u8 = undefined;
    const n = try std.fs.File.stdin().read(&buffer);
    const answer = std.mem.trim(u8, buffer[0..n], " \t\r\n");
    if (!std.mem.eql(u8, answer, decision.confirm)) return error.PreexecDenied;
}

test "cloud preexec args parse" {
    const parsed = try parseCloudPreexecArgs(&.{ "--socket", "/tmp/shisa.sock", "--shell", "zsh", "--force", "--", "kubectl delete pod x" });
    try std.testing.expectEqualStrings("/tmp/shisa.sock", parsed.socket_path.?);
    try std.testing.expectEqualStrings("zsh", parsed.shell);
    try std.testing.expect(parsed.force);
    try std.testing.expectEqualStrings("kubectl delete pod x", parsed.command);
}

test "cloud preexec response allows safe command" {
    try enforceCloudPreexecResponse(std.testing.allocator, "{\"v\":1,\"allow\":true}");
}

test "cloud preexec response denies without confirm token" {
    try std.testing.expectError(error.PreexecDenied, enforceCloudPreexecResponse(std.testing.allocator, "{\"v\":1,\"allow\":false}"));
}

test "cloud preexec payload escapes command" {
    const payload = try buildCloudPreexecPayload(std.testing.allocator, .{ .shell = "zsh", .command = "echo \"prod\"" });
    defer std.testing.allocator.free(payload);
    try std.testing.expect(std.mem.indexOf(u8, payload, "\"command\":\"echo \\\"prod\\\"\"") != null);
}

test "cloud audit reads prod guard jsonl" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-audit-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};

    const cloud_path = try cloudRequestAuditPathAlloc(allocator, dir_path);
    defer allocator.free(cloud_path);
    if (std.fs.path.dirname(cloud_path)) |parent| try std.fs.cwd().makePath(parent);
    {
        var file = try std.fs.createFileAbsolute(cloud_path, .{});
        defer file.close();
        try file.writeAll("{\"kind\":\"preexec\"}\n");
    }

    const prod_path = try prodGuardAuditPathAlloc(allocator, dir_path);
    defer allocator.free(prod_path);
    {
        var file = try std.fs.createFileAbsolute(prod_path, .{});
        defer file.close();
        try file.writeAll("{\"tier\":\"prod\"}\n");
    }

    const output = try cloudAuditAlloc(allocator, dir_path);
    defer allocator.free(output);
    try std.testing.expectEqualStrings("{\"kind\":\"preexec\"}\n{\"tier\":\"prod\"}\n", output);
}

test "cloud doctor reports config status" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-cloud-doctor-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};

    try copyFixtureToPath(allocator, "test/fixtures/cloud/aws-config-default", try std.fmt.allocPrint(allocator, "{s}/.aws/config", .{dir_path}));
    try copyFixtureToPath(allocator, "test/fixtures/cloud/gcloud-config", try std.fmt.allocPrint(allocator, "{s}/.config/gcloud/configurations/config_default", .{dir_path}));
    try copyFixtureToPath(allocator, "test/fixtures/cloud/azureProfile.json", try std.fmt.allocPrint(allocator, "{s}/.azure/azureProfile.json", .{dir_path}));
    try copyFixtureToPath(allocator, "test/fixtures/cloud/kubeconfig-with-namespace.yaml", try std.fmt.allocPrint(allocator, "{s}/.kube/config", .{dir_path}));

    const output = try cloudDoctorAlloc(allocator, dir_path, null, null);
    defer allocator.free(output);
    try std.testing.expect(std.mem.indexOf(u8, output, "aws_profile: default\n") != null);
    try std.testing.expect(std.mem.indexOf(u8, output, "gcp_project: test-project\n") != null);
    try std.testing.expect(std.mem.indexOf(u8, output, "azure_subscription: prod-sub\n") != null);
    try std.testing.expect(std.mem.indexOf(u8, output, "kube_context: prod/default\n") != null);
}

test "cloud explain output shows reason" {
    const output = try cloudExplainAlloc(std.testing.allocator, "api-prd-use1", null);
    defer std.testing.allocator.free(output);

    try std.testing.expect(std.mem.indexOf(u8, output, "tier: prod\n") != null);
    try std.testing.expect(std.mem.indexOf(u8, output, "source: default\n") != null);
    try std.testing.expect(std.mem.indexOf(u8, output, "pattern: *-prd-*\n") != null);
}

fn copyFixtureToPath(allocator: std.mem.Allocator, source_path: []const u8, dest_path: []u8) !void {
    defer allocator.free(dest_path);
    const source = try std.fs.cwd().readFileAlloc(allocator, source_path, max_config_bytes);
    defer allocator.free(source);
    if (std.fs.path.dirname(dest_path)) |parent| try std.fs.cwd().makePath(parent);
    var file = try std.fs.createFileAbsolute(dest_path, .{ .truncate = true });
    defer file.close();
    try file.writeAll(source);
}

const P10kSetting = struct {
    name: []u8,
    values: std.ArrayList([]u8) = .empty,

    fn deinit(self: *P10kSetting, allocator: std.mem.Allocator) void {
        allocator.free(self.name);
        for (self.values.items) |value| allocator.free(value);
        self.values.deinit(allocator);
    }
};

const P10kImport = struct {
    settings: std.ArrayList(P10kSetting) = .empty,

    fn deinit(self: *P10kImport, allocator: std.mem.Allocator) void {
        for (self.settings.items) |*setting| setting.deinit(allocator);
        self.settings.deinit(allocator);
    }

    fn find(self: P10kImport, name: []const u8) ?P10kSetting {
        for (self.settings.items) |setting| {
            if (std.mem.eql(u8, setting.name, name)) return setting;
        }
        return null;
    }
};

fn parseP10kConfig(allocator: std.mem.Allocator, source: []const u8) !P10kImport {
    var imported = P10kImport{};
    errdefer imported.deinit(allocator);

    var active_array: ?usize = null;
    var lines = std.mem.splitScalar(u8, source, '\n');
    while (lines.next()) |raw_line| {
        var line = std.mem.trim(u8, raw_line, " \t\r");
        if (line.len == 0 or line[0] == '#') continue;

        if (active_array) |setting_index| {
            if (std.mem.indexOfScalar(u8, line, ')')) |close_index| {
                try appendP10kWords(allocator, &imported.settings.items[setting_index], line[0..close_index]);
                active_array = null;
            } else {
                try appendP10kWords(allocator, &imported.settings.items[setting_index], line);
            }
            continue;
        }

        const start = std.mem.indexOf(u8, line, "POWERLEVEL9K_") orelse continue;
        line = line[start..];
        const eq_index = std.mem.indexOfScalar(u8, line, '=') orelse continue;
        const key = std.mem.trim(u8, line[0..eq_index], " \t");
        if (!validP10kKey(key)) continue;

        const name = key["POWERLEVEL9K_".len..];
        var setting = P10kSetting{ .name = try allocator.dupe(u8, name) };
        errdefer setting.deinit(allocator);

        var value = std.mem.trim(u8, line[eq_index + 1 ..], " \t");
        if (std.mem.startsWith(u8, value, "(")) {
            value = std.mem.trim(u8, value[1..], " \t");
            if (std.mem.indexOfScalar(u8, value, ')')) |close_index| {
                try appendP10kWords(allocator, &setting, value[0..close_index]);
            } else {
                try appendP10kWords(allocator, &setting, value);
                try imported.settings.append(allocator, setting);
                active_array = imported.settings.items.len - 1;
                continue;
            }
        } else {
            try appendP10kWords(allocator, &setting, value);
        }
        try imported.settings.append(allocator, setting);
    }

    if (active_array != null) return error.UnclosedP10kArray;
    return imported;
}

fn validP10kKey(key: []const u8) bool {
    if (!std.mem.startsWith(u8, key, "POWERLEVEL9K_")) return false;
    for (key) |byte| {
        if (!(std.ascii.isUpper(byte) or std.ascii.isDigit(byte) or byte == '_')) return false;
    }
    return true;
}

fn appendP10kWords(allocator: std.mem.Allocator, setting: *P10kSetting, text: []const u8) !void {
    var index: usize = 0;
    while (index < text.len) {
        while (index < text.len and std.ascii.isWhitespace(text[index])) : (index += 1) {}
        if (index >= text.len or text[index] == '#') break;

        const start = index;
        if (text[index] == '\'' or text[index] == '"') {
            const quote = text[index];
            index += 1;
            const value_start = index;
            while (index < text.len and text[index] != quote) : (index += 1) {}
            if (index >= text.len) return error.UnclosedP10kQuote;
            const owned = try allocator.dupe(u8, text[value_start..index]);
            errdefer allocator.free(owned);
            try setting.values.append(allocator, owned);
            index += 1;
            continue;
        }

        while (index < text.len and !std.ascii.isWhitespace(text[index]) and text[index] != '#') : (index += 1) {}
        var value = text[start..index];
        value = std.mem.trimRight(u8, value, ")");
        if (value.len != 0) {
            const owned = try allocator.dupe(u8, value);
            errdefer allocator.free(owned);
            try setting.values.append(allocator, owned);
        }
    }
}

fn expectP10kValues(imported: P10kImport, name: []const u8, expected: []const []const u8) !void {
    const setting = imported.find(name) orelse return error.MissingP10kSetting;
    try std.testing.expectEqual(expected.len, setting.values.items.len);
    for (expected, 0..) |value, index| {
        try std.testing.expectEqualStrings(value, setting.values.items[index]);
    }
}

test "parses p10k POWERLEVEL9K assignments" {
    const source =
        \\typeset -g POWERLEVEL9K_LEFT_PROMPT_ELEMENTS=(
        \\  dir vcs
        \\  # comment
        \\)
        \\typeset -g POWERLEVEL9K_RIGHT_PROMPT_ELEMENTS=(status command_execution_time)
        \\typeset -g POWERLEVEL9K_INSTANT_PROMPT=verbose
        \\typeset -g POWERLEVEL9K_MODE='nerdfont-complete'
        \\ZSH_THEME=powerlevel10k/powerlevel10k
        \\
    ;
    var imported = try parseP10kConfig(std.testing.allocator, source);
    defer imported.deinit(std.testing.allocator);

    try std.testing.expectEqual(@as(usize, 4), imported.settings.items.len);
    try expectP10kValues(imported, "LEFT_PROMPT_ELEMENTS", &.{ "dir", "vcs" });
    try expectP10kValues(imported, "RIGHT_PROMPT_ELEMENTS", &.{ "status", "command_execution_time" });
    try expectP10kValues(imported, "INSTANT_PROMPT", &.{"verbose"});
    try expectP10kValues(imported, "MODE", &.{"nerdfont-complete"});
}

const P10kImportResult = struct {
    config: []u8,
    notes: ?[]u8 = null,

    fn deinit(self: P10kImportResult, allocator: std.mem.Allocator) void {
        allocator.free(self.config);
        if (self.notes) |notes| allocator.free(notes);
    }
};

fn importP10k(allocator: std.mem.Allocator, args: []const []const u8) !void {
    if (args.len != 1) return error.UnknownImportP10kArgument;

    const source = try std.fs.cwd().readFileAlloc(allocator, args[0], max_config_bytes);
    defer allocator.free(source);

    const result = try importP10kResultAlloc(allocator, source);
    defer result.deinit(allocator);
    try std.fs.File.stdout().writeAll(result.config);
    if (result.notes) |notes| {
        try std.fs.cwd().writeFile(.{ .sub_path = "migration-notes.md", .data = notes });
    }
}

fn importP10kAlloc(allocator: std.mem.Allocator, source: []const u8) ![]u8 {
    const result = try importP10kResultAlloc(allocator, source);
    if (result.notes) |notes| allocator.free(notes);
    return result.config;
}

fn importP10kResultAlloc(allocator: std.mem.Allocator, source: []const u8) !P10kImportResult {
    var p10k = try parseP10kConfig(allocator, source);
    defer p10k.deinit(allocator);

    var imported = StarshipImport{};
    defer imported.deinit(allocator);

    const left = if (p10k.find("LEFT_PROMPT_ELEMENTS")) |setting| setting.values.items else &.{};
    const right = if (p10k.find("RIGHT_PROMPT_ELEMENTS")) |setting| setting.values.items else &.{};
    const instant_prompt = p10kInstantPrompt(p10k);

    for (left) |element| try mapP10kElement(allocator, element, &imported);
    for (right) |element| try mapP10kElement(allocator, element, &imported);

    if (imported.modules.items.len == 0) {
        inline for (.{ .cwd, .git_branch, .exit_status, .jobs, .cmd_duration, .user_host }) |module_id| {
            try appendModule(allocator, &imported, module_id);
        }
    }

    const config = try renderP10kImportedConfigAlloc(allocator, imported, left, right, instant_prompt);
    errdefer allocator.free(config);
    const notes = try renderP10kMigrationNotesAlloc(allocator, imported);
    errdefer if (notes) |owned| allocator.free(owned);
    return .{ .config = config, .notes = notes };
}

fn p10kInstantPrompt(imported: P10kImport) ?[]const u8 {
    const setting = imported.find("INSTANT_PROMPT") orelse return null;
    if (setting.values.items.len == 0) return null;
    return setting.values.items[0];
}

fn p10kInstantEnabled(value: []const u8) bool {
    return !(std.mem.eql(u8, value, "off") or std.mem.eql(u8, value, "false") or std.mem.eql(u8, value, "0") or std.mem.eql(u8, value, "no"));
}

fn renderP10kImportedConfigAlloc(allocator: std.mem.Allocator, imported: StarshipImport, left: []const []u8, right: []const []u8, instant_prompt: ?[]const u8) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);

    try out.appendSlice(allocator, "version = 1\n");
    try out.appendSlice(allocator, "theme = \"plain\"\n\n");
    try appendP10kLayoutComment(allocator, &out, "left", left);
    try appendP10kLayoutComment(allocator, &out, "right", right);
    if (instant_prompt) |value| {
        try cli_util.appendFmt(allocator, &out, "# Powerlevel10k instant_prompt: {s}\n", .{value});
        try cli_util.appendFmt(allocator, &out, "# Shisa instant prompt: SHISA_INSTANT={d}\n", .{@intFromBool(p10kInstantEnabled(value))});
    }
    try out.appendSlice(allocator, "[prompt]\nmodules = [");
    for (imported.modules.items, 0..) |module_id, index| {
        if (index != 0) try out.appendSlice(allocator, ", ");
        try cli_util.appendFmt(allocator, &out, "\"{s}\"", .{shisa_config.moduleIdName(module_id)});
    }
    try out.appendSlice(allocator, "]\n");
    if (imported.right_modules.items.len != 0) {
        try out.appendSlice(allocator, "right_modules = [");
        for (imported.right_modules.items, 0..) |module_id, index| {
            if (index != 0) try out.appendSlice(allocator, ", ");
            try cli_util.appendFmt(allocator, &out, "\"{s}\"", .{shisa_config.moduleIdName(module_id)});
        }
        try out.appendSlice(allocator, "]\n");
    }

    if (containsAnyModule(imported, .language_versions) and (imported.python or imported.node or imported.rust or imported.go)) {
        try out.appendSlice(allocator, "\n[modules.language_versions]\ndetect = [");
        var count: usize = 0;
        if (imported.python) try appendLanguage(allocator, &out, &count, "python");
        if (imported.node) try appendLanguage(allocator, &out, &count, "node");
        if (imported.rust) try appendLanguage(allocator, &out, &count, "rust");
        if (imported.go) try appendLanguage(allocator, &out, &count, "go");
        try out.appendSlice(allocator, "]\n");
    }

    if (containsAnyModule(imported, .time)) {
        try out.appendSlice(allocator, "\n[modules.time]\nformat = \"24h\"\nutc = true\n");
    }

    if (imported.unsupported.items.len != 0) {
        try out.appendSlice(allocator, "\n# Unsupported Powerlevel10k elements: ");
        for (imported.unsupported.items, 0..) |name, index| {
            if (index != 0) try out.appendSlice(allocator, ", ");
            try out.appendSlice(allocator, name);
        }
        try out.append(allocator, '\n');
    }

    return try out.toOwnedSlice(allocator);
}

fn appendP10kLayoutComment(allocator: std.mem.Allocator, out: *std.ArrayList(u8), side: []const u8, elements: []const []u8) !void {
    try cli_util.appendFmt(allocator, out, "# Powerlevel10k {s} elements: ", .{side});
    for (elements, 0..) |element, index| {
        if (index != 0) try out.appendSlice(allocator, ", ");
        try out.appendSlice(allocator, element);
    }
    try out.append(allocator, '\n');
}

fn renderP10kMigrationNotesAlloc(allocator: std.mem.Allocator, imported: StarshipImport) !?[]u8 {
    if (imported.unsupported.items.len == 0) return null;

    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);

    try out.appendSlice(allocator, "# Powerlevel10k Migration Notes\n\n");
    try out.appendSlice(allocator, "## Unsupported Elements\n\n");
    for (imported.unsupported.items) |name| {
        try cli_util.appendFmt(allocator, &out, "- `{s}`: {s}\n", .{ name, p10kUnsupportedReason(name) });
    }
    return try out.toOwnedSlice(allocator);
}

fn p10kUnsupportedReason(name: []const u8) []const u8 {
    if (std.mem.eql(u8, name, "public_ip")) return "No core public-IP module; recreate as a plugin or omit.";
    if (std.mem.eql(u8, name, "ip")) return "No core local-IP module; recreate as a plugin or omit.";
    if (std.mem.eql(u8, name, "battery")) return "No core battery module; recreate as a plugin or omit.";
    if (std.mem.eql(u8, name, "ram")) return "No core RAM module; recreate as a plugin or omit.";
    if (std.mem.eql(u8, name, "load")) return "No core load-average module; recreate as a plugin or omit.";
    if (std.mem.eql(u8, name, "todo")) return "No core todo module; recreate as a plugin or omit.";
    return "No Shisa core mapping; recreate as a plugin or omit.";
}

const OmpSegment = struct {
    kind: ?[]u8 = null,
    template: ?[]u8 = null,
    foreground: ?[]u8 = null,
    background: ?[]u8 = null,

    fn deinit(self: OmpSegment, allocator: std.mem.Allocator) void {
        if (self.kind) |kind| allocator.free(kind);
        if (self.template) |template| allocator.free(template);
        if (self.foreground) |foreground| allocator.free(foreground);
        if (self.background) |background| allocator.free(background);
    }
};

const OmpBlock = struct {
    block_type: ?[]u8 = null,
    alignment: ?[]u8 = null,
    segments: std.ArrayList(OmpSegment) = .empty,

    fn deinit(self: *OmpBlock, allocator: std.mem.Allocator) void {
        if (self.block_type) |block_type| allocator.free(block_type);
        if (self.alignment) |alignment| allocator.free(alignment);
        for (self.segments.items) |segment| segment.deinit(allocator);
        self.segments.deinit(allocator);
    }
};

const OmpTheme = struct {
    blocks: std.ArrayList(OmpBlock) = .empty,
    palette: std.ArrayList(OmpPaletteEntry) = .empty,

    fn deinit(self: *OmpTheme, allocator: std.mem.Allocator) void {
        for (self.blocks.items) |*block| block.deinit(allocator);
        self.blocks.deinit(allocator);
        for (self.palette.items) |entry| entry.deinit(allocator);
        self.palette.deinit(allocator);
    }
};

const OmpPaletteEntry = struct {
    name: []u8,
    value: []u8,

    fn deinit(self: OmpPaletteEntry, allocator: std.mem.Allocator) void {
        allocator.free(self.name);
        allocator.free(self.value);
    }
};

fn parseOmpTheme(allocator: std.mem.Allocator, source: []const u8) !OmpTheme {
    const trimmed = std.mem.trim(u8, source, " \t\r\n");
    if (trimmed.len == 0) return error.InvalidOmpTheme;
    if (trimmed[0] == '{') return parseOmpJsonTheme(allocator, source);
    return parseOmpYamlTheme(allocator, source);
}

fn parseOmpJsonTheme(allocator: std.mem.Allocator, source: []const u8) !OmpTheme {
    var parsed = try std.json.parseFromSlice(std.json.Value, allocator, source, .{ .ignore_unknown_fields = true });
    defer parsed.deinit();

    const root = switch (parsed.value) {
        .object => |object| object,
        else => return error.InvalidOmpTheme,
    };
    const blocks_value = root.get("blocks") orelse return error.InvalidOmpTheme;
    const blocks = switch (blocks_value) {
        .array => |array| array,
        else => return error.InvalidOmpTheme,
    };

    var theme = OmpTheme{};
    errdefer theme.deinit(allocator);
    if (root.get("palette")) |palette_value| {
        const palette = switch (palette_value) {
            .object => |object| object,
            else => return error.InvalidOmpTheme,
        };
        var iterator = palette.iterator();
        while (iterator.next()) |entry| {
            switch (entry.value_ptr.*) {
                .string => |value| try appendOmpPaletteEntry(allocator, &theme, entry.key_ptr.*, value),
                else => {},
            }
        }
    }
    for (blocks.items) |block_value| {
        const block_object = switch (block_value) {
            .object => |object| object,
            else => continue,
        };
        var block = OmpBlock{};
        errdefer block.deinit(allocator);
        if (jsonStringField(block_object, "type")) |value| try setOwned(allocator, &block.block_type, value);
        if (jsonStringField(block_object, "alignment")) |value| try setOwned(allocator, &block.alignment, value);
        if (block_object.get("segments")) |segments_value| {
            const segments = switch (segments_value) {
                .array => |array| array,
                else => return error.InvalidOmpTheme,
            };
            for (segments.items) |segment_value| {
                const segment_object = switch (segment_value) {
                    .object => |object| object,
                    else => continue,
                };
                var segment = OmpSegment{};
                errdefer segment.deinit(allocator);
                if (jsonStringField(segment_object, "type")) |value| try setOwned(allocator, &segment.kind, value);
                if (jsonStringField(segment_object, "template")) |value| try setOwned(allocator, &segment.template, value);
                if (jsonStringField(segment_object, "foreground")) |value| try setOwned(allocator, &segment.foreground, value);
                if (jsonStringField(segment_object, "background")) |value| try setOwned(allocator, &segment.background, value);
                try block.segments.append(allocator, segment);
            }
        }
        try theme.blocks.append(allocator, block);
    }
    return theme;
}

fn jsonStringField(object: std.json.ObjectMap, key: []const u8) ?[]const u8 {
    const value = object.get(key) orelse return null;
    return switch (value) {
        .string => |string| string,
        else => null,
    };
}

fn parseOmpYamlTheme(allocator: std.mem.Allocator, source: []const u8) !OmpTheme {
    var theme = OmpTheme{};
    errdefer theme.deinit(allocator);

    var in_blocks = false;
    var in_palette = false;
    var in_segments = false;
    var current_block_index: ?usize = null;
    var current_segment_index: ?usize = null;
    var block_item_indent: usize = 0;

    var lines = std.mem.splitScalar(u8, source, '\n');
    while (lines.next()) |raw_line| {
        const without_comment = stripYamlComment(std.mem.trimRight(u8, raw_line, "\r"));
        if (std.mem.trim(u8, without_comment, " \t").len == 0) continue;
        const indent = leadingSpaces(without_comment);
        const trimmed = std.mem.trim(u8, without_comment[indent..], " \t");

        if (indent == 0 and std.mem.eql(u8, trimmed, "palette:")) {
            in_palette = true;
            in_blocks = false;
            in_segments = false;
            continue;
        }
        if (in_palette) {
            if (indent == 0) {
                in_palette = false;
            } else {
                if (yamlKeyValue(trimmed)) |kv| try appendOmpPaletteEntry(allocator, &theme, kv.key, yamlScalar(kv.value));
                continue;
            }
        }

        if (indent == 0 and std.mem.eql(u8, trimmed, "blocks:")) {
            in_blocks = true;
            in_palette = false;
            in_segments = false;
            continue;
        }
        if (!in_blocks) continue;

        if (std.mem.startsWith(u8, trimmed, "-")) {
            const item = std.mem.trim(u8, trimmed[1..], " \t");
            if (in_segments and indent > block_item_indent) {
                const block_index = current_block_index orelse return error.InvalidOmpTheme;
                try theme.blocks.items[block_index].segments.append(allocator, .{});
                current_segment_index = theme.blocks.items[block_index].segments.items.len - 1;
                if (yamlKeyValue(item)) |kv| {
                    try applyOmpYamlSegmentField(allocator, &theme.blocks.items[block_index].segments.items[current_segment_index.?], kv.key, kv.value);
                }
            } else {
                try theme.blocks.append(allocator, .{});
                current_block_index = theme.blocks.items.len - 1;
                current_segment_index = null;
                block_item_indent = indent;
                in_segments = false;
                if (yamlKeyValue(item)) |kv| try applyOmpYamlBlockField(allocator, &theme.blocks.items[current_block_index.?], kv.key, kv.value);
            }
            continue;
        }

        const block_index = current_block_index orelse continue;
        if (yamlKeyValue(trimmed)) |kv| {
            if (std.mem.eql(u8, kv.key, "segments")) {
                in_segments = true;
                current_segment_index = null;
            } else if (in_segments) {
                if (current_segment_index) |segment_index| {
                    try applyOmpYamlSegmentField(allocator, &theme.blocks.items[block_index].segments.items[segment_index], kv.key, kv.value);
                }
            } else {
                try applyOmpYamlBlockField(allocator, &theme.blocks.items[block_index], kv.key, kv.value);
            }
        }
    }
    return theme;
}

const YamlKeyValue = struct {
    key: []const u8,
    value: []const u8,
};

fn yamlKeyValue(line: []const u8) ?YamlKeyValue {
    const colon = std.mem.indexOfScalar(u8, line, ':') orelse return null;
    const key = std.mem.trim(u8, line[0..colon], " \t");
    if (key.len == 0) return null;
    return .{ .key = key, .value = std.mem.trim(u8, line[colon + 1 ..], " \t") };
}

fn yamlScalar(value: []const u8) []const u8 {
    if (value.len >= 2 and ((value[0] == '"' and value[value.len - 1] == '"') or (value[0] == '\'' and value[value.len - 1] == '\''))) {
        return value[1 .. value.len - 1];
    }
    return value;
}

fn applyOmpYamlBlockField(allocator: std.mem.Allocator, block: *OmpBlock, key: []const u8, value: []const u8) !void {
    if (std.mem.eql(u8, key, "type")) {
        try setOwned(allocator, &block.block_type, yamlScalar(value));
    } else if (std.mem.eql(u8, key, "alignment")) {
        try setOwned(allocator, &block.alignment, yamlScalar(value));
    }
}

fn applyOmpYamlSegmentField(allocator: std.mem.Allocator, segment: *OmpSegment, key: []const u8, value: []const u8) !void {
    if (std.mem.eql(u8, key, "type")) {
        try setOwned(allocator, &segment.kind, yamlScalar(value));
    } else if (std.mem.eql(u8, key, "template")) {
        try setOwned(allocator, &segment.template, yamlScalar(value));
    } else if (std.mem.eql(u8, key, "foreground")) {
        try setOwned(allocator, &segment.foreground, yamlScalar(value));
    } else if (std.mem.eql(u8, key, "background")) {
        try setOwned(allocator, &segment.background, yamlScalar(value));
    }
}

fn appendOmpPaletteEntry(allocator: std.mem.Allocator, theme: *OmpTheme, name: []const u8, value: []const u8) !void {
    const owned_name = try allocator.dupe(u8, name);
    errdefer allocator.free(owned_name);
    const owned_value = try allocator.dupe(u8, value);
    errdefer allocator.free(owned_value);
    try theme.palette.append(allocator, .{ .name = owned_name, .value = owned_value });
}

fn setOwned(allocator: std.mem.Allocator, target: *?[]u8, value: []const u8) !void {
    if (target.*) |owned| allocator.free(owned);
    target.* = try allocator.dupe(u8, value);
}

fn stripYamlComment(line: []const u8) []const u8 {
    var quote: ?u8 = null;
    for (line, 0..) |byte, index| {
        if (quote) |active| {
            if (byte == active) quote = null;
        } else if (byte == '"' or byte == '\'') {
            quote = byte;
        } else if (byte == '#') {
            return line[0..index];
        }
    }
    return line;
}

fn leadingSpaces(line: []const u8) usize {
    var index: usize = 0;
    while (index < line.len and line[index] == ' ') : (index += 1) {}
    return index;
}

fn scanOmpTheme(allocator: std.mem.Allocator, theme: OmpTheme, imported: *StarshipImport) !void {
    for (theme.blocks.items) |block| {
        for (block.segments.items) |segment| {
            if (segment.kind) |kind| try mapOmpSegment(allocator, kind, imported);
        }
    }
}

fn mapOmpSegment(allocator: std.mem.Allocator, name: []const u8, imported: *StarshipImport) !void {
    if (std.mem.eql(u8, name, "path")) {
        try appendModule(allocator, imported, .cwd);
    } else if (std.mem.eql(u8, name, "git") or
        std.mem.eql(u8, name, "jujutsu") or
        std.mem.eql(u8, name, "mercurial") or
        std.mem.eql(u8, name, "sapling") or
        std.mem.eql(u8, name, "svn") or
        std.mem.eql(u8, name, "fossil") or
        std.mem.eql(u8, name, "plastic"))
    {
        try appendModule(allocator, imported, .git_branch);
    } else if (std.mem.eql(u8, name, "python")) {
        imported.python = true;
        try appendModule(allocator, imported, .language_versions);
    } else if (std.mem.eql(u8, name, "node")) {
        imported.node = true;
        try appendModule(allocator, imported, .language_versions);
    } else if (std.mem.eql(u8, name, "go")) {
        imported.go = true;
        try appendModule(allocator, imported, .language_versions);
    } else if (std.mem.eql(u8, name, "rust")) {
        imported.rust = true;
        try appendModule(allocator, imported, .language_versions);
    } else if (std.mem.eql(u8, name, "status")) {
        try appendModule(allocator, imported, .exit_status);
    } else if (std.mem.eql(u8, name, "executiontime")) {
        try appendModule(allocator, imported, .cmd_duration);
    } else if (std.mem.eql(u8, name, "session")) {
        try appendModule(allocator, imported, .user_host);
    } else if (std.mem.eql(u8, name, "aws") or
        std.mem.eql(u8, name, "gcp") or
        std.mem.eql(u8, name, "az") or
        std.mem.eql(u8, name, "kubectl"))
    {
        try appendModule(allocator, imported, .cloud_ctx);
    } else if (std.mem.eql(u8, name, "terraform") or std.mem.eql(u8, name, "pulumi")) {
        try appendModule(allocator, imported, .iac_workspace);
    } else if (std.mem.eql(u8, name, "time")) {
        try appendModule(allocator, imported, .time);
    } else if (!isIgnoredOmpSegment(name)) {
        try appendUnsupported(allocator, imported, name);
    }
}

fn isIgnoredOmpSegment(name: []const u8) bool {
    return std.mem.eql(u8, name, "text") or
        std.mem.eql(u8, name, "shell") or
        std.mem.eql(u8, name, "os") or
        std.mem.eql(u8, name, "upgrade");
}

const OmpImportResult = struct {
    config: []u8,
    theme: ?[]u8 = null,
    notes: ?[]u8 = null,

    fn deinit(self: OmpImportResult, allocator: std.mem.Allocator) void {
        allocator.free(self.config);
        if (self.theme) |theme| allocator.free(theme);
        if (self.notes) |notes| allocator.free(notes);
    }
};

fn importOhMyPosh(allocator: std.mem.Allocator, args: []const []const u8) !void {
    if (args.len != 1) return error.UnknownImportOhMyPoshArgument;

    const source = try std.fs.cwd().readFileAlloc(allocator, args[0], max_config_bytes);
    defer allocator.free(source);

    const result = try importOhMyPoshResultAlloc(allocator, source);
    defer result.deinit(allocator);
    try std.fs.File.stdout().writeAll(result.config);
    if (result.theme) |theme| {
        try std.fs.cwd().writeFile(.{ .sub_path = "oh-my-posh-theme.toml", .data = theme });
    }
    if (result.notes) |notes| {
        try std.fs.cwd().writeFile(.{ .sub_path = "migration-notes.md", .data = notes });
    }
}

fn importOhMyPoshResultAlloc(allocator: std.mem.Allocator, source: []const u8) !OmpImportResult {
    var theme = try parseOmpTheme(allocator, source);
    defer theme.deinit(allocator);

    var imported = StarshipImport{};
    defer imported.deinit(allocator);
    try scanOmpTheme(allocator, theme, &imported);

    if (imported.modules.items.len == 0) {
        inline for (.{ .cwd, .git_branch, .language_versions, .exit_status, .cmd_duration, .user_host }) |module_id| {
            try appendModule(allocator, &imported, module_id);
        }
    }

    const imported_theme = try renderOmpImportedThemeAlloc(allocator, theme);
    errdefer if (imported_theme) |owned| allocator.free(owned);
    const config = try renderOmpImportedConfigAlloc(allocator, imported, theme, if (imported_theme != null) "./oh-my-posh-theme.toml" else null);
    errdefer allocator.free(config);
    const notes = try renderOmpMigrationNotesAlloc(allocator, theme, imported);
    errdefer if (notes) |owned| allocator.free(owned);
    return .{ .config = config, .theme = imported_theme, .notes = notes };
}

fn renderOmpImportedConfigAlloc(allocator: std.mem.Allocator, imported: StarshipImport, theme: OmpTheme, theme_path: ?[]const u8) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);

    try out.appendSlice(allocator, "version = 1\ntheme = ");
    try appendTomlString(allocator, &out, theme_path orelse "plain");
    try out.appendSlice(allocator, "\n\n");
    try appendOmpLayoutComments(allocator, &out, theme);
    try out.appendSlice(allocator, "[prompt]\nmodules = [");
    for (imported.modules.items, 0..) |module_id, index| {
        if (index != 0) try out.appendSlice(allocator, ", ");
        try cli_util.appendFmt(allocator, &out, "\"{s}\"", .{shisa_config.moduleIdName(module_id)});
    }
    try out.appendSlice(allocator, "]\n");
    if (imported.right_modules.items.len != 0) {
        try out.appendSlice(allocator, "right_modules = [");
        for (imported.right_modules.items, 0..) |module_id, index| {
            if (index != 0) try out.appendSlice(allocator, ", ");
            try cli_util.appendFmt(allocator, &out, "\"{s}\"", .{shisa_config.moduleIdName(module_id)});
        }
        try out.appendSlice(allocator, "]\n");
    }

    if (containsAnyModule(imported, .language_versions) and (imported.python or imported.node or imported.rust or imported.go)) {
        try out.appendSlice(allocator, "\n[modules.language_versions]\ndetect = [");
        var count: usize = 0;
        if (imported.python) try appendLanguage(allocator, &out, &count, "python");
        if (imported.node) try appendLanguage(allocator, &out, &count, "node");
        if (imported.rust) try appendLanguage(allocator, &out, &count, "rust");
        if (imported.go) try appendLanguage(allocator, &out, &count, "go");
        try out.appendSlice(allocator, "]\n");
    }

    if (containsAnyModule(imported, .time)) {
        try out.appendSlice(allocator, "\n[modules.time]\nformat = \"24h\"\nutc = true\n");
    }

    if (imported.unsupported.items.len != 0) {
        try out.appendSlice(allocator, "\n# Unsupported Oh My Posh segments: ");
        for (imported.unsupported.items, 0..) |name, index| {
            if (index != 0) try out.appendSlice(allocator, ", ");
            try out.appendSlice(allocator, name);
        }
        try out.append(allocator, '\n');
    }

    return out.toOwnedSlice(allocator);
}

fn renderOmpMigrationNotesAlloc(allocator: std.mem.Allocator, theme: OmpTheme, imported: StarshipImport) !?[]u8 {
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);

    var count: usize = 0;
    try out.appendSlice(allocator, "# Oh My Posh Migration Notes\n\n");

    if (imported.unsupported.items.len != 0) {
        count += imported.unsupported.items.len;
        try out.appendSlice(allocator, "## Unsupported Segments\n\n");
        for (imported.unsupported.items) |name| {
            try cli_util.appendFmt(allocator, &out, "- `{s}`: {s}\n", .{ name, ompUnsupportedReason(name) });
        }
        try out.append(allocator, '\n');
    }

    var template_count: usize = 0;
    for (theme.blocks.items) |block| {
        for (block.segments.items) |segment| {
            const kind = segment.kind orelse continue;
            if (ompModuleForSegment(kind) == null) continue;
            const template = segment.template orelse continue;
            const layout = try translateOmpTemplateLayoutAlloc(allocator, template);
            defer if (layout) |owned| owned.deinit(allocator);
            if (layout == null) {
                if (template_count == 0) try out.appendSlice(allocator, "## Untranslated Templates\n\n");
                template_count += 1;
                count += 1;
                try cli_util.appendFmt(allocator, &out, "- `{s}`: template requires manual port.\n", .{kind});
            }
        }
    }
    if (template_count != 0) try out.append(allocator, '\n');

    var color_count: usize = 0;
    for (theme.blocks.items) |block| {
        for (block.segments.items) |segment| {
            const kind = segment.kind orelse continue;
            if (segment.foreground) |foreground| {
                if (resolveOmpColorRgb(theme, foreground, 0) == null) {
                    if (color_count == 0) try out.appendSlice(allocator, "## Unresolved Colors\n\n");
                    color_count += 1;
                    count += 1;
                    try cli_util.appendFmt(allocator, &out, "- `{s}` foreground `{s}` could not be resolved.\n", .{ kind, foreground });
                }
            }
            if (segment.background) |background| {
                if (resolveOmpColorRgb(theme, background, 0) == null) {
                    if (color_count == 0) try out.appendSlice(allocator, "## Unresolved Colors\n\n");
                    color_count += 1;
                    count += 1;
                    try cli_util.appendFmt(allocator, &out, "- `{s}` background `{s}` could not be resolved.\n", .{ kind, background });
                }
            }
        }
    }

    if (count == 0) return null;
    return try out.toOwnedSlice(allocator);
}

fn ompUnsupportedReason(name: []const u8) []const u8 {
    if (std.mem.eql(u8, name, "battery")) return "No core battery module.";
    if (std.mem.eql(u8, name, "docker")) return "Docker context differs from Shisa container provenance.";
    if (std.mem.eql(u8, name, "ipify")) return "No core public-IP module.";
    if (std.mem.eql(u8, name, "sysinfo")) return "No core CPU/RAM module.";
    if (std.mem.eql(u8, name, "project")) return "No package/project metadata core module yet.";
    if (std.mem.eql(u8, name, "http")) return "Network calls are not imported into prompt hot path.";
    if (std.mem.eql(u8, name, "spotify")) return "Media status belongs in a plugin.";
    if (std.mem.eql(u8, name, "wakatime")) return "External service calls belong in a plugin.";
    if (std.mem.eql(u8, name, "taskwarrior")) return "Task manager integrations belong in a plugin.";
    return "No Shisa core mapping; recreate as a plugin or omit.";
}

fn appendOmpLayoutComments(allocator: std.mem.Allocator, out: *std.ArrayList(u8), theme: OmpTheme) !void {
    try appendOmpLayoutComment(allocator, out, theme, false);
    try appendOmpLayoutComment(allocator, out, theme, true);
}

fn appendOmpLayoutComment(allocator: std.mem.Allocator, out: *std.ArrayList(u8), theme: OmpTheme, right: bool) !void {
    try cli_util.appendFmt(allocator, out, "# Oh My Posh {s} layout: ", .{if (right) "right" else "left"});
    var count: usize = 0;
    for (theme.blocks.items) |block| {
        if (ompBlockIsRight(block) != right) continue;
        for (block.segments.items) |segment| {
            const kind = segment.kind orelse continue;
            if (count != 0) try out.appendSlice(allocator, ", ");
            count += 1;
            try out.appendSlice(allocator, kind);
        }
    }
    try out.append(allocator, '\n');
}

fn ompBlockIsRight(block: OmpBlock) bool {
    if (block.alignment) |alignment| {
        if (std.mem.eql(u8, alignment, "right")) return true;
    }
    if (block.block_type) |block_type| {
        if (std.mem.eql(u8, block_type, "rprompt")) return true;
    }
    return false;
}

fn renderOmpImportedThemeAlloc(allocator: std.mem.Allocator, theme: OmpTheme) !?[]u8 {
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);

    var emitted = StarshipImport{};
    defer emitted.deinit(allocator);

    const mapped_palette = mapOmpPalette(theme);
    try out.appendSlice(allocator, "version = 1\nname = \"oh-my-posh-imported\"\nextends = \"plain\"\n");
    if (mapped_palette.has_source) try appendMappedOmpPalette(allocator, &out, mapped_palette);
    var count: usize = 0;
    for (theme.blocks.items) |block| {
        for (block.segments.items) |segment| {
            const kind = segment.kind orelse continue;
            const module_id = ompModuleForSegment(kind) orelse continue;
            if (containsModule(emitted, module_id)) continue;
            const layout = if (segment.template) |template| try translateOmpTemplateLayoutAlloc(allocator, template) else null;
            defer if (layout) |owned| owned.deinit(allocator);
            const fg_ref = try translateOmpColorRefAlloc(allocator, theme, mapped_palette, segment.foreground);
            defer if (fg_ref) |owned| allocator.free(owned);
            const bg_ref = try translateOmpColorRefAlloc(allocator, theme, mapped_palette, segment.background);
            defer if (bg_ref) |owned| allocator.free(owned);
            const has_layout = if (layout) |owned| owned.prefix.len != 0 or owned.suffix.len != 0 else false;
            if (!has_layout and fg_ref == null and bg_ref == null) continue;
            try appendModule(allocator, &emitted, module_id);
            try cli_util.appendFmt(allocator, &out, "\n[segments.{s}]\n", .{shisa_config.moduleIdName(module_id)});
            if (fg_ref) |value| {
                try out.appendSlice(allocator, "fg = ");
                try appendTomlString(allocator, &out, value);
                try out.append(allocator, '\n');
            }
            if (bg_ref) |value| {
                try out.appendSlice(allocator, "bg = ");
                try appendTomlString(allocator, &out, value);
                try out.append(allocator, '\n');
            }
            if (layout) |owned| if (owned.prefix.len != 0) {
                try out.appendSlice(allocator, "prefix = ");
                try appendTomlString(allocator, &out, owned.prefix);
                try out.append(allocator, '\n');
            };
            if (layout) |owned| if (owned.suffix.len != 0) {
                try out.appendSlice(allocator, "suffix = ");
                try appendTomlString(allocator, &out, owned.suffix);
                try out.append(allocator, '\n');
            };
            count += 1;
        }
    }
    if (count == 0) return null;
    return try out.toOwnedSlice(allocator);
}

fn ompModuleForSegment(name: []const u8) ?shisa_config.ModuleId {
    if (std.mem.eql(u8, name, "path")) return .cwd;
    if (std.mem.eql(u8, name, "git") or
        std.mem.eql(u8, name, "jujutsu") or
        std.mem.eql(u8, name, "mercurial") or
        std.mem.eql(u8, name, "sapling") or
        std.mem.eql(u8, name, "svn") or
        std.mem.eql(u8, name, "fossil") or
        std.mem.eql(u8, name, "plastic")) return .git_branch;
    if (std.mem.eql(u8, name, "python") or
        std.mem.eql(u8, name, "node") or
        std.mem.eql(u8, name, "go") or
        std.mem.eql(u8, name, "rust")) return .language_versions;
    if (std.mem.eql(u8, name, "status")) return .exit_status;
    if (std.mem.eql(u8, name, "executiontime")) return .cmd_duration;
    if (std.mem.eql(u8, name, "session")) return .user_host;
    if (std.mem.eql(u8, name, "aws") or
        std.mem.eql(u8, name, "gcp") or
        std.mem.eql(u8, name, "az") or
        std.mem.eql(u8, name, "kubectl")) return .cloud_ctx;
    if (std.mem.eql(u8, name, "terraform") or std.mem.eql(u8, name, "pulumi")) return .iac_workspace;
    if (std.mem.eql(u8, name, "time")) return .time;
    return null;
}

const Rgb = struct {
    r: u8,
    g: u8,
    b: u8,
};

const Oklab = struct {
    l: f64,
    a: f64,
    b: f64,
};

const ShisaPaletteSlot = struct {
    name: []const u8,
    target: Rgb,
    fallback: Rgb,
};

const shisa_palette_slots = [_]ShisaPaletteSlot{
    .{ .name = "fg", .target = .{ .r = 255, .g = 255, .b = 255 }, .fallback = .{ .r = 255, .g = 255, .b = 255 } },
    .{ .name = "muted", .target = .{ .r = 128, .g = 128, .b = 128 }, .fallback = .{ .r = 128, .g = 128, .b = 128 } },
    .{ .name = "accent", .target = .{ .r = 0, .g = 255, .b = 255 }, .fallback = .{ .r = 0, .g = 255, .b = 255 } },
    .{ .name = "success", .target = .{ .r = 0, .g = 170, .b = 0 }, .fallback = .{ .r = 0, .g = 170, .b = 0 } },
    .{ .name = "warning", .target = .{ .r = 255, .g = 170, .b = 0 }, .fallback = .{ .r = 255, .g = 170, .b = 0 } },
    .{ .name = "danger", .target = .{ .r = 255, .g = 0, .b = 0 }, .fallback = .{ .r = 255, .g = 0, .b = 0 } },
};

const MappedOmpPalette = struct {
    has_source: bool = false,
    colors: [shisa_palette_slots.len]Rgb = defaultShisaPaletteColors(),
};

fn defaultShisaPaletteColors() [shisa_palette_slots.len]Rgb {
    var colors: [shisa_palette_slots.len]Rgb = undefined;
    for (shisa_palette_slots, 0..) |slot, index| colors[index] = slot.fallback;
    return colors;
}

fn mapOmpPalette(theme: OmpTheme) MappedOmpPalette {
    var mapped = MappedOmpPalette{};
    if (theme.palette.items.len == 0) return mapped;
    mapped.has_source = true;
    var filled = [_]bool{false} ** shisa_palette_slots.len;
    for (shisa_palette_slots, 0..) |slot, index| {
        if (findOmpPaletteRgb(theme, slot.name)) |rgb| {
            mapped.colors[index] = rgb;
            filled[index] = true;
        }
    }
    for (shisa_palette_slots, 0..) |slot, index| {
        if (filled[index]) continue;
        if (nearestOmpPaletteRgbAvoiding(theme, slot.target, mapped.colors, filled)) |rgb| {
            mapped.colors[index] = rgb;
            filled[index] = true;
        }
    }
    return mapped;
}

fn appendMappedOmpPalette(allocator: std.mem.Allocator, out: *std.ArrayList(u8), mapped: MappedOmpPalette) !void {
    try out.appendSlice(allocator, "\n[palette]\n");
    for (shisa_palette_slots, 0..) |slot, index| {
        try cli_util.appendFmt(allocator, out, "{s} = ", .{slot.name});
        try appendRgbHexString(allocator, out, mapped.colors[index]);
        try out.append(allocator, '\n');
    }
}

fn translateOmpColorRefAlloc(allocator: std.mem.Allocator, theme: OmpTheme, mapped: MappedOmpPalette, value: ?[]const u8) !?[]u8 {
    const raw = value orelse return null;
    const rgb = resolveOmpColorRgb(theme, raw, 0) orelse return null;
    if (mapped.has_source) {
        const slot = nearestMappedPaletteSlot(mapped, rgb);
        return try std.fmt.allocPrint(allocator, "@{s}", .{slot});
    }
    return try rgbHexAlloc(allocator, rgb);
}

fn nearestMappedPaletteSlot(mapped: MappedOmpPalette, rgb: Rgb) []const u8 {
    const target = rgbToOklab(rgb);
    var best_index: usize = 0;
    var best_distance = oklabDistanceSquared(target, rgbToOklab(mapped.colors[0]));
    for (mapped.colors[1..], 1..) |candidate, offset| {
        const distance = oklabDistanceSquared(target, rgbToOklab(candidate));
        if (distance < best_distance) {
            best_distance = distance;
            best_index = offset;
        }
    }
    return shisa_palette_slots[best_index].name;
}

fn nearestOmpPaletteRgb(theme: OmpTheme, target: Rgb) ?Rgb {
    return nearestOmpPaletteRgbAvoiding(theme, target, defaultShisaPaletteColors(), [_]bool{false} ** shisa_palette_slots.len);
}

fn nearestOmpPaletteRgbAvoiding(theme: OmpTheme, target: Rgb, used_colors: [shisa_palette_slots.len]Rgb, used: [shisa_palette_slots.len]bool) ?Rgb {
    const target_lab = rgbToOklab(target);
    var best: ?Rgb = null;
    var best_distance: f64 = 0;
    for (theme.palette.items) |entry| {
        const rgb = resolveOmpColorRgb(theme, entry.value, 0) orelse continue;
        if (rgbIsUsed(rgb, used_colors, used)) continue;
        const distance = oklabDistanceSquared(target_lab, rgbToOklab(rgb));
        if (best == null or distance < best_distance) {
            best = rgb;
            best_distance = distance;
        }
    }
    return best;
}

fn rgbIsUsed(rgb: Rgb, used_colors: [shisa_palette_slots.len]Rgb, used: [shisa_palette_slots.len]bool) bool {
    for (used, 0..) |is_used, index| {
        if (is_used and std.meta.eql(rgb, used_colors[index])) return true;
    }
    return false;
}

fn findOmpPaletteRgb(theme: OmpTheme, name: []const u8) ?Rgb {
    for (theme.palette.items) |entry| {
        if (std.mem.eql(u8, entry.name, name)) return resolveOmpColorRgb(theme, entry.value, 0);
    }
    return null;
}

fn resolveOmpColorRgb(theme: OmpTheme, value: []const u8, depth: u8) ?Rgb {
    if (depth > 8) return null;
    const trimmed = std.mem.trim(u8, value, " \t\r\n");
    if (std.mem.startsWith(u8, trimmed, "p:")) {
        const name = trimmed[2..];
        for (theme.palette.items) |entry| {
            if (std.mem.eql(u8, entry.name, name)) return resolveOmpColorRgb(theme, entry.value, depth + 1);
        }
        return null;
    }
    if (parseHexColor(trimmed)) |rgb| return rgb;
    if (parseAnsiColor(trimmed)) |rgb| return rgb;
    return namedOmpColor(trimmed);
}

fn parseHexColor(value: []const u8) ?Rgb {
    if (value.len == 7 and value[0] == '#') {
        return .{
            .r = parseHexByte(value[1], value[2]) orelse return null,
            .g = parseHexByte(value[3], value[4]) orelse return null,
            .b = parseHexByte(value[5], value[6]) orelse return null,
        };
    }
    if (value.len == 4 and value[0] == '#') {
        const r = parseHexDigit(value[1]) orelse return null;
        const g = parseHexDigit(value[2]) orelse return null;
        const b = parseHexDigit(value[3]) orelse return null;
        return .{ .r = r * 17, .g = g * 17, .b = b * 17 };
    }
    return null;
}

fn parseHexByte(high: u8, low: u8) ?u8 {
    const high_value = parseHexDigit(high) orelse return null;
    const low_value = parseHexDigit(low) orelse return null;
    return high_value * 16 + low_value;
}

fn parseHexDigit(byte: u8) ?u8 {
    if (byte >= '0' and byte <= '9') return byte - '0';
    if (byte >= 'a' and byte <= 'f') return byte - 'a' + 10;
    if (byte >= 'A' and byte <= 'F') return byte - 'A' + 10;
    return null;
}

fn parseAnsiColor(value: []const u8) ?Rgb {
    const index = std.fmt.parseInt(u8, value, 10) catch return null;
    const base = [_]Rgb{
        .{ .r = 0, .g = 0, .b = 0 },
        .{ .r = 128, .g = 0, .b = 0 },
        .{ .r = 0, .g = 128, .b = 0 },
        .{ .r = 128, .g = 128, .b = 0 },
        .{ .r = 0, .g = 0, .b = 128 },
        .{ .r = 128, .g = 0, .b = 128 },
        .{ .r = 0, .g = 128, .b = 128 },
        .{ .r = 192, .g = 192, .b = 192 },
        .{ .r = 128, .g = 128, .b = 128 },
        .{ .r = 255, .g = 0, .b = 0 },
        .{ .r = 0, .g = 255, .b = 0 },
        .{ .r = 255, .g = 255, .b = 0 },
        .{ .r = 0, .g = 0, .b = 255 },
        .{ .r = 255, .g = 0, .b = 255 },
        .{ .r = 0, .g = 255, .b = 255 },
        .{ .r = 255, .g = 255, .b = 255 },
    };
    if (index < 16) return base[index];
    if (index <= 231) {
        const cube = index - 16;
        const steps = [_]u8{ 0, 95, 135, 175, 215, 255 };
        return .{
            .r = steps[cube / 36],
            .g = steps[(cube / 6) % 6],
            .b = steps[cube % 6],
        };
    }
    const gray: u8 = 8 + (index - 232) * 10;
    return .{ .r = gray, .g = gray, .b = gray };
}

fn namedOmpColor(value: []const u8) ?Rgb {
    if (std.mem.eql(u8, value, "black")) return .{ .r = 0, .g = 0, .b = 0 };
    if (std.mem.eql(u8, value, "red")) return .{ .r = 128, .g = 0, .b = 0 };
    if (std.mem.eql(u8, value, "green")) return .{ .r = 0, .g = 128, .b = 0 };
    if (std.mem.eql(u8, value, "yellow")) return .{ .r = 128, .g = 128, .b = 0 };
    if (std.mem.eql(u8, value, "blue")) return .{ .r = 0, .g = 0, .b = 128 };
    if (std.mem.eql(u8, value, "magenta")) return .{ .r = 128, .g = 0, .b = 128 };
    if (std.mem.eql(u8, value, "cyan")) return .{ .r = 0, .g = 128, .b = 128 };
    if (std.mem.eql(u8, value, "white")) return .{ .r = 192, .g = 192, .b = 192 };
    if (std.mem.eql(u8, value, "darkGray")) return .{ .r = 128, .g = 128, .b = 128 };
    if (std.mem.eql(u8, value, "lightRed")) return .{ .r = 255, .g = 0, .b = 0 };
    if (std.mem.eql(u8, value, "lightGreen")) return .{ .r = 0, .g = 255, .b = 0 };
    if (std.mem.eql(u8, value, "lightYellow")) return .{ .r = 255, .g = 255, .b = 0 };
    if (std.mem.eql(u8, value, "lightBlue")) return .{ .r = 0, .g = 0, .b = 255 };
    if (std.mem.eql(u8, value, "lightMagenta")) return .{ .r = 255, .g = 0, .b = 255 };
    if (std.mem.eql(u8, value, "lightCyan")) return .{ .r = 0, .g = 255, .b = 255 };
    if (std.mem.eql(u8, value, "lightWhite")) return .{ .r = 255, .g = 255, .b = 255 };
    if (std.mem.eql(u8, value, "foreground")) return .{ .r = 255, .g = 255, .b = 255 };
    if (std.mem.eql(u8, value, "background")) return .{ .r = 0, .g = 0, .b = 0 };
    if (std.mem.eql(u8, value, "accent")) return .{ .r = 0, .g = 255, .b = 255 };
    return null;
}

fn rgbToOklab(rgb: Rgb) Oklab {
    const r = srgbByteToLinear(rgb.r);
    const g = srgbByteToLinear(rgb.g);
    const b = srgbByteToLinear(rgb.b);
    const l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b;
    const m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b;
    const s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b;
    const l_root = std.math.pow(f64, l, 1.0 / 3.0);
    const m_root = std.math.pow(f64, m, 1.0 / 3.0);
    const s_root = std.math.pow(f64, s, 1.0 / 3.0);
    return .{
        .l = 0.2104542553 * l_root + 0.7936177850 * m_root - 0.0040720468 * s_root,
        .a = 1.9779984951 * l_root - 2.4285922050 * m_root + 0.4505937099 * s_root,
        .b = 0.0259040371 * l_root + 0.7827717662 * m_root - 0.8086757660 * s_root,
    };
}

fn srgbByteToLinear(byte: u8) f64 {
    const value: f64 = @as(f64, @floatFromInt(byte)) / 255.0;
    if (value <= 0.04045) return value / 12.92;
    return std.math.pow(f64, (value + 0.055) / 1.055, 2.4);
}

fn oklabDistanceSquared(a: Oklab, b: Oklab) f64 {
    const dl = a.l - b.l;
    const da = a.a - b.a;
    const db = a.b - b.b;
    return dl * dl + da * da + db * db;
}

fn rgbHexAlloc(allocator: std.mem.Allocator, rgb: Rgb) ![]u8 {
    return std.fmt.allocPrint(allocator, "#{X:0>2}{X:0>2}{X:0>2}", .{ rgb.r, rgb.g, rgb.b });
}

fn appendRgbHexString(allocator: std.mem.Allocator, out: *std.ArrayList(u8), rgb: Rgb) !void {
    const hex = try rgbHexAlloc(allocator, rgb);
    defer allocator.free(hex);
    try appendTomlString(allocator, out, hex);
}

const OmpTemplateLayout = struct {
    prefix: []u8,
    suffix: []u8,

    fn deinit(self: OmpTemplateLayout, allocator: std.mem.Allocator) void {
        allocator.free(self.prefix);
        allocator.free(self.suffix);
    }
};

fn translateOmpTemplateLayoutAlloc(allocator: std.mem.Allocator, template: []const u8) !?OmpTemplateLayout {
    const open = std.mem.indexOf(u8, template, "{{") orelse return null;
    const close_offset = std.mem.indexOf(u8, template[open + 2 ..], "}}") orelse return null;
    const close = open + 2 + close_offset;
    if (std.mem.indexOf(u8, template[close + 2 ..], "{{") != null) return null;
    const expression = std.mem.trim(u8, template[open + 2 .. close], " \t\r\n");
    if (isOmpTemplateControl(expression)) return null;

    const prefix = try stripOmpTemplateMarkupAlloc(allocator, template[0..open]);
    errdefer allocator.free(prefix);
    const suffix = try stripOmpTemplateMarkupAlloc(allocator, template[close + 2 ..]);
    errdefer allocator.free(suffix);
    return .{ .prefix = prefix, .suffix = suffix };
}

fn isOmpTemplateControl(expression: []const u8) bool {
    return std.mem.startsWith(u8, expression, "if ") or
        std.mem.startsWith(u8, expression, "range ") or
        std.mem.startsWith(u8, expression, "with ") or
        std.mem.eql(u8, expression, "else") or
        std.mem.eql(u8, expression, "end");
}

fn stripOmpTemplateMarkupAlloc(allocator: std.mem.Allocator, value: []const u8) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);

    var in_tag = false;
    for (value) |byte| {
        if (in_tag) {
            if (byte == '>') in_tag = false;
        } else if (byte == '<') {
            in_tag = true;
        } else {
            try out.append(allocator, byte);
        }
    }
    return out.toOwnedSlice(allocator);
}

fn appendTomlString(allocator: std.mem.Allocator, out: *std.ArrayList(u8), value: []const u8) !void {
    try out.append(allocator, '"');
    for (value) |byte| {
        switch (byte) {
            '\\' => try out.appendSlice(allocator, "\\\\"),
            '"' => try out.appendSlice(allocator, "\\\""),
            '\n' => try out.appendSlice(allocator, "\\n"),
            '\r' => try out.appendSlice(allocator, "\\r"),
            '\t' => try out.appendSlice(allocator, "\\t"),
            else => try out.append(allocator, byte),
        }
    }
    try out.append(allocator, '"');
}

const TideSetting = struct {
    name: []u8,
    values: std.ArrayList([]u8) = .empty,

    fn deinit(self: *TideSetting, allocator: std.mem.Allocator) void {
        allocator.free(self.name);
        for (self.values.items) |value| allocator.free(value);
        self.values.deinit(allocator);
    }
};

const TideConfig = struct {
    settings: std.ArrayList(TideSetting) = .empty,

    fn deinit(self: *TideConfig, allocator: std.mem.Allocator) void {
        for (self.settings.items) |*setting| setting.deinit(allocator);
        self.settings.deinit(allocator);
    }

    fn find(self: TideConfig, name: []const u8) ?TideSetting {
        for (self.settings.items) |setting| {
            if (std.mem.eql(u8, setting.name, name)) return setting;
        }
        return null;
    }
};

fn parseTideConfig(allocator: std.mem.Allocator, source: []const u8) !TideConfig {
    var config = TideConfig{};
    errdefer config.deinit(allocator);

    var lines = std.mem.splitScalar(u8, source, '\n');
    while (lines.next()) |raw_line| {
        const line = std.mem.trim(u8, raw_line, " \t\r");
        if (line.len == 0 or line[0] == '#') continue;

        var words: std.ArrayList([]u8) = .empty;
        defer freeStringList(allocator, &words);
        try appendFishWords(allocator, &words, line);
        if (words.items.len == 0) continue;

        const name_index = tideNameIndex(words.items) orelse continue;
        const name = words.items[name_index];
        if (!validTideKey(name)) continue;

        var setting = TideSetting{ .name = try allocator.dupe(u8, name) };
        errdefer setting.deinit(allocator);
        for (words.items[name_index + 1 ..]) |value| {
            const owned = try allocator.dupe(u8, value);
            errdefer allocator.free(owned);
            try setting.values.append(allocator, owned);
        }
        try config.settings.append(allocator, setting);
    }

    return config;
}

fn tideNameIndex(words: []const []u8) ?usize {
    if (words.len == 0) return null;
    if (std.mem.eql(u8, words[0], "set")) {
        for (words[1..], 1..) |word, index| {
            if (std.mem.startsWith(u8, word, "tide_")) return index;
        }
        return null;
    }
    return if (std.mem.startsWith(u8, words[0], "tide_")) 0 else null;
}

fn validTideKey(key: []const u8) bool {
    if (!std.mem.startsWith(u8, key, "tide_")) return false;
    for (key) |byte| {
        if (!(std.ascii.isLower(byte) or std.ascii.isDigit(byte) or byte == '_')) return false;
    }
    return true;
}

fn appendFishWords(allocator: std.mem.Allocator, words: *std.ArrayList([]u8), text: []const u8) !void {
    var index: usize = 0;
    while (index < text.len) {
        while (index < text.len and std.ascii.isWhitespace(text[index])) : (index += 1) {}
        if (index >= text.len or text[index] == '#') break;

        if (text[index] == '\'' or text[index] == '"') {
            const quote = text[index];
            index += 1;
            const start = index;
            while (index < text.len and text[index] != quote) : (index += 1) {}
            if (index >= text.len) return error.UnclosedFishQuote;
            const owned = try allocator.dupe(u8, text[start..index]);
            errdefer allocator.free(owned);
            try words.append(allocator, owned);
            index += 1;
            continue;
        }

        const start = index;
        while (index < text.len and !std.ascii.isWhitespace(text[index]) and text[index] != '#') : (index += 1) {}
        const value = text[start..index];
        if (value.len != 0) {
            const owned = try allocator.dupe(u8, value);
            errdefer allocator.free(owned);
            try words.append(allocator, owned);
        }
    }
}

fn freeStringList(allocator: std.mem.Allocator, words: *std.ArrayList([]u8)) void {
    for (words.items) |word| allocator.free(word);
    words.deinit(allocator);
}

fn scanTideConfig(allocator: std.mem.Allocator, config: TideConfig, imported: *StarshipImport) !void {
    if (config.find("tide_left_prompt_items")) |setting| {
        for (setting.values.items) |item| try mapTideItem(allocator, item, imported, false);
    }
    if (config.find("tide_right_prompt_items")) |setting| {
        for (setting.values.items) |item| try mapTideItem(allocator, item, imported, true);
    }
}

fn mapTideItem(allocator: std.mem.Allocator, name: []const u8, imported: *StarshipImport, right: bool) !void {
    if (std.mem.eql(u8, name, "pwd")) {
        try appendTideModule(allocator, imported, .cwd, right);
    } else if (std.mem.eql(u8, name, "git")) {
        try appendTideModule(allocator, imported, .git_branch, right);
    } else if (std.mem.eql(u8, name, "status")) {
        try appendTideModule(allocator, imported, .exit_status, right);
    } else if (std.mem.eql(u8, name, "cmd_duration")) {
        try appendTideModule(allocator, imported, .cmd_duration, right);
    } else if (std.mem.eql(u8, name, "context")) {
        try appendTideModule(allocator, imported, .user_host, right);
    } else if (std.mem.eql(u8, name, "jobs")) {
        try appendTideModule(allocator, imported, .jobs, right);
    } else if (std.mem.eql(u8, name, "python")) {
        imported.python = true;
        try appendTideModule(allocator, imported, .language_versions, right);
    } else if (std.mem.eql(u8, name, "node")) {
        imported.node = true;
        try appendTideModule(allocator, imported, .language_versions, right);
    } else if (std.mem.eql(u8, name, "rustc")) {
        imported.rust = true;
        try appendTideModule(allocator, imported, .language_versions, right);
    } else if (std.mem.eql(u8, name, "go")) {
        imported.go = true;
        try appendTideModule(allocator, imported, .language_versions, right);
    } else if (std.mem.eql(u8, name, "aws") or
        std.mem.eql(u8, name, "gcloud") or
        std.mem.eql(u8, name, "kubectl"))
    {
        try appendTideModule(allocator, imported, .cloud_ctx, right);
    } else if (std.mem.eql(u8, name, "terraform") or std.mem.eql(u8, name, "pulumi")) {
        try appendTideModule(allocator, imported, .iac_workspace, right);
    } else if (std.mem.eql(u8, name, "time")) {
        try appendTideModule(allocator, imported, .time, right);
    } else if (!isIgnoredTideItem(name)) {
        try appendUnsupported(allocator, imported, name);
    }
}

fn isIgnoredTideItem(name: []const u8) bool {
    return std.mem.eql(u8, name, "newline") or
        std.mem.eql(u8, name, "character");
}

const TideImportResult = struct {
    config: []u8,
    notes: ?[]u8 = null,

    fn deinit(self: TideImportResult, allocator: std.mem.Allocator) void {
        allocator.free(self.config);
        if (self.notes) |notes| allocator.free(notes);
    }
};

fn importTide(allocator: std.mem.Allocator, args: []const []const u8) !void {
    if (args.len != 1) return error.UnknownImportTideArgument;

    const source = try std.fs.cwd().readFileAlloc(allocator, args[0], max_config_bytes);
    defer allocator.free(source);

    const result = try importTideResultAlloc(allocator, source);
    defer result.deinit(allocator);
    try std.fs.File.stdout().writeAll(result.config);
    if (result.notes) |notes| {
        try std.fs.cwd().writeFile(.{ .sub_path = "migration-notes.md", .data = notes });
    }
}

fn importTideResultAlloc(allocator: std.mem.Allocator, source: []const u8) !TideImportResult {
    var tide = try parseTideConfig(allocator, source);
    defer tide.deinit(allocator);

    var imported = StarshipImport{};
    defer imported.deinit(allocator);
    try scanTideConfig(allocator, tide, &imported);

    if (imported.modules.items.len == 0) {
        inline for (.{ .cwd, .git_branch, .exit_status, .cmd_duration, .user_host }) |module_id| {
            try appendModule(allocator, &imported, module_id);
        }
    }

    const config = try renderTideImportedConfigAlloc(allocator, imported, tide);
    errdefer allocator.free(config);
    const notes = try renderTideMigrationNotesAlloc(allocator, imported, tide);
    errdefer if (notes) |owned| allocator.free(owned);
    return .{ .config = config, .notes = notes };
}

fn renderTideImportedConfigAlloc(allocator: std.mem.Allocator, imported: StarshipImport, tide: TideConfig) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);

    try out.appendSlice(allocator, "version = 1\ntheme = \"plain\"\n\n");
    try appendTideItemsComment(allocator, &out, tide, "left", "tide_left_prompt_items");
    try appendTideItemsComment(allocator, &out, tide, "right", "tide_right_prompt_items");
    try out.appendSlice(allocator, "[prompt]\nmodules = [");
    for (imported.modules.items, 0..) |module_id, index| {
        if (index != 0) try out.appendSlice(allocator, ", ");
        try cli_util.appendFmt(allocator, &out, "\"{s}\"", .{shisa_config.moduleIdName(module_id)});
    }
    try out.appendSlice(allocator, "]\n");
    if (imported.right_modules.items.len != 0) {
        try out.appendSlice(allocator, "right_modules = [");
        for (imported.right_modules.items, 0..) |module_id, index| {
            if (index != 0) try out.appendSlice(allocator, ", ");
            try cli_util.appendFmt(allocator, &out, "\"{s}\"", .{shisa_config.moduleIdName(module_id)});
        }
        try out.appendSlice(allocator, "]\n");
    }

    if (containsAnyModule(imported, .language_versions) and (imported.python or imported.node or imported.rust or imported.go)) {
        try out.appendSlice(allocator, "\n[modules.language_versions]\ndetect = [");
        var count: usize = 0;
        if (imported.python) try appendLanguage(allocator, &out, &count, "python");
        if (imported.node) try appendLanguage(allocator, &out, &count, "node");
        if (imported.rust) try appendLanguage(allocator, &out, &count, "rust");
        if (imported.go) try appendLanguage(allocator, &out, &count, "go");
        try out.appendSlice(allocator, "]\n");
    }

    if (containsAnyModule(imported, .time)) {
        try out.appendSlice(allocator, "\n[modules.time]\nformat = \"24h\"\nutc = true\n");
    }

    if (imported.unsupported.items.len != 0) {
        try out.appendSlice(allocator, "\n# Unsupported Tide items: ");
        for (imported.unsupported.items, 0..) |name, index| {
            if (index != 0) try out.appendSlice(allocator, ", ");
            try out.appendSlice(allocator, name);
        }
        try out.append(allocator, '\n');
    }

    return out.toOwnedSlice(allocator);
}

fn appendTideItemsComment(allocator: std.mem.Allocator, out: *std.ArrayList(u8), tide: TideConfig, label: []const u8, key: []const u8) !void {
    try cli_util.appendFmt(allocator, out, "# Tide {s} items: ", .{label});
    if (tide.find(key)) |setting| {
        for (setting.values.items, 0..) |item, index| {
            if (index != 0) try out.appendSlice(allocator, ", ");
            try out.appendSlice(allocator, item);
        }
    }
    try out.append(allocator, '\n');
}

fn renderTideMigrationNotesAlloc(allocator: std.mem.Allocator, imported: StarshipImport, tide: TideConfig) !?[]u8 {
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);

    var count: usize = 0;
    try out.appendSlice(allocator, "# Tide Migration Notes\n\n");

    if (imported.unsupported.items.len != 0) {
        count += imported.unsupported.items.len;
        try out.appendSlice(allocator, "## Unsupported Items\n\n");
        for (imported.unsupported.items) |name| {
            try cli_util.appendFmt(allocator, &out, "- `{s}`: {s}\n", .{ name, tideUnsupportedReason(name) });
        }
        try out.append(allocator, '\n');
    }

    var quirk_count: usize = 0;
    if (settingFirstEquals(tide, "tide_prompt_transient_enabled", "true")) {
        if (quirk_count == 0) try out.appendSlice(allocator, "## Fish/Tide Quirks\n\n");
        quirk_count += 1;
        count += 1;
        try out.appendSlice(allocator, "- `tide_prompt_transient_enabled=true` is not imported for Fish.\n");
    }
    if (hasTideLayoutSetting(tide)) {
        if (quirk_count == 0) try out.appendSlice(allocator, "## Fish/Tide Quirks\n\n");
        quirk_count += 1;
        count += 1;
        try out.appendSlice(allocator, "- Tide frame/separator/prefix/suffix settings require manual theme/layout work.\n");
    }
    if (hasFishVariableColor(tide)) {
        if (quirk_count == 0) try out.appendSlice(allocator, "## Fish/Tide Quirks\n\n");
        quirk_count += 1;
        count += 1;
        try out.appendSlice(allocator, "- Fish variable color refs such as `$_tide_color_*` were not resolved.\n");
    }

    if (count == 0) return null;
    return try out.toOwnedSlice(allocator);
}

fn settingHasValues(tide: TideConfig, name: []const u8) bool {
    const setting = tide.find(name) orelse return false;
    return setting.values.items.len != 0;
}

fn settingFirstEquals(tide: TideConfig, name: []const u8, expected: []const u8) bool {
    const setting = tide.find(name) orelse return false;
    return setting.values.items.len != 0 and std.mem.eql(u8, setting.values.items[0], expected);
}

fn hasTideLayoutSetting(tide: TideConfig) bool {
    for (tide.settings.items) |setting| {
        if (std.mem.indexOf(u8, setting.name, "_frame_enabled") != null or
            std.mem.indexOf(u8, setting.name, "_separator_") != null or
            std.mem.endsWith(u8, setting.name, "_prompt_prefix") or
            std.mem.endsWith(u8, setting.name, "_prompt_suffix"))
        {
            return true;
        }
    }
    return false;
}

fn hasFishVariableColor(tide: TideConfig) bool {
    for (tide.settings.items) |setting| {
        if (std.mem.indexOf(u8, setting.name, "_color") == null) continue;
        for (setting.values.items) |value| {
            if (std.mem.startsWith(u8, value, "$")) return true;
        }
    }
    return false;
}

fn tideUnsupportedReason(name: []const u8) []const u8 {
    if (std.mem.eql(u8, name, "bun")) return "No core Bun detector.";
    if (std.mem.eql(u8, name, "java")) return "No core Java detector.";
    if (std.mem.eql(u8, name, "php")) return "No core PHP detector.";
    if (std.mem.eql(u8, name, "ruby")) return "No core Ruby detector.";
    if (std.mem.eql(u8, name, "crystal")) return "No core Crystal detector.";
    if (std.mem.eql(u8, name, "elixir")) return "No core Elixir detector.";
    if (std.mem.eql(u8, name, "zig")) return "No core Zig detector.";
    if (std.mem.eql(u8, name, "direnv")) return "Environment state belongs in a plugin.";
    if (std.mem.eql(u8, name, "distrobox")) return "Container environment state is not imported yet.";
    if (std.mem.eql(u8, name, "toolbox")) return "Container environment state is not imported yet.";
    if (std.mem.eql(u8, name, "nix_shell")) return "Nix shell state is not imported yet.";
    return "No Shisa core mapping; recreate as a plugin or omit.";
}

fn importPure(allocator: std.mem.Allocator, args: []const []const u8) !void {
    if (args.len != 0) return error.UnknownImportPureArgument;
    const output = try pureConfigAlloc(allocator);
    defer allocator.free(output);
    try std.fs.File.stdout().writeAll(output);
}

fn pureConfigAlloc(allocator: std.mem.Allocator) ![]u8 {
    return try allocator.dupe(u8,
        \\version = 1
        \\theme = "pure"
        \\
        \\[prompt]
        \\modules = ["cwd", "git_branch", "exit_status", "cmd_duration", "jobs", "user_host"]
        \\
        \\[modules.cmd_duration]
        \\threshold_ms = 5000
        \\
        \\[modules.user_host]
        \\mode = "ssh"
        \\
    );
}

const StarshipImport = struct {
    modules: std.ArrayList(shisa_config.ModuleId) = .empty,
    right_modules: std.ArrayList(shisa_config.ModuleId) = .empty,
    unsupported: std.ArrayList([]const u8) = .empty,
    python: bool = false,
    node: bool = false,
    rust: bool = false,
    go: bool = false,

    fn deinit(self: *StarshipImport, allocator: std.mem.Allocator) void {
        self.modules.deinit(allocator);
        self.right_modules.deinit(allocator);
        for (self.unsupported.items) |name| allocator.free(name);
        self.unsupported.deinit(allocator);
    }
};

fn importStarship(allocator: std.mem.Allocator, args: []const []const u8) !void {
    if (args.len != 1) return error.UnknownImportStarshipArgument;

    const source = try std.fs.cwd().readFileAlloc(allocator, args[0], max_config_bytes);
    defer allocator.free(source);

    const output = try importStarshipAlloc(allocator, source);
    defer allocator.free(output);
    try std.fs.File.stdout().writeAll(output);
}

fn importStarshipAlloc(allocator: std.mem.Allocator, source: []const u8) ![]u8 {
    var imported = StarshipImport{};
    defer imported.deinit(allocator);

    if (try starshipFormatAlloc(allocator, source)) |format| {
        defer allocator.free(format);
        try scanStarshipFormat(allocator, format, &imported);
    } else {
        try scanStarshipTables(allocator, source, &imported);
    }

    if (imported.modules.items.len == 0) {
        inline for (.{ .cwd, .git_branch, .language_versions, .exit_status, .jobs, .cmd_duration, .user_host }) |module_id| {
            try appendModule(allocator, &imported, module_id);
        }
    }

    return renderImportedConfigAlloc(allocator, imported);
}

fn starshipFormatAlloc(allocator: std.mem.Allocator, source: []const u8) !?[]u8 {
    var offset: usize = 0;
    while (offset <= source.len) {
        const rest = source[offset..];
        const line_len = std.mem.indexOfScalar(u8, rest, '\n') orelse rest.len;
        const line = rest[0..line_len];
        const trimmed = std.mem.trim(u8, line, " \t\r");
        if (trimmed.len != 0 and trimmed[0] == '[') return null;
        if (std.mem.startsWith(u8, trimmed, "format")) {
            const eq_index = std.mem.indexOfScalar(u8, trimmed, '=') orelse return null;
            const value = std.mem.trim(u8, trimmed[eq_index + 1 ..], " \t\r");
            return parseTomlStringAlloc(allocator, value);
        }
        offset += line_len + 1;
        if (offset > source.len) break;
    }
    return null;
}

fn parseTomlStringAlloc(allocator: std.mem.Allocator, value: []const u8) !?[]u8 {
    if (value.len >= 6 and std.mem.startsWith(u8, value, "\"\"\"") and std.mem.endsWith(u8, value, "\"\"\"")) {
        return try allocator.dupe(u8, value[3 .. value.len - 3]);
    }
    if (value.len < 2 or value[0] != '"') return null;

    var out: std.ArrayList(u8) = .empty;
    errdefer out.deinit(allocator);

    var index: usize = 1;
    while (index < value.len) : (index += 1) {
        const byte = value[index];
        if (byte == '"') return try out.toOwnedSlice(allocator);
        if (byte == '\\') {
            index += 1;
            if (index >= value.len) return null;
            switch (value[index]) {
                '"' => try out.append(allocator, '"'),
                '\\' => try out.append(allocator, '\\'),
                'n' => try out.append(allocator, '\n'),
                'r' => try out.append(allocator, '\r'),
                't' => try out.append(allocator, '\t'),
                else => try out.append(allocator, value[index]),
            }
        } else {
            try out.append(allocator, byte);
        }
    }
    return null;
}

fn scanStarshipFormat(allocator: std.mem.Allocator, format: []const u8, imported: *StarshipImport) !void {
    var index: usize = 0;
    while (index < format.len) : (index += 1) {
        if (format[index] != '$') continue;
        index += 1;
        const start = index;
        while (index < format.len and isStarshipModuleByte(format[index])) : (index += 1) {}
        if (index == start) continue;
        try mapStarshipModule(allocator, format[start..index], imported);
        index -= 1;
    }
}

fn scanStarshipTables(allocator: std.mem.Allocator, source: []const u8, imported: *StarshipImport) !void {
    var offset: usize = 0;
    while (offset <= source.len) {
        const rest = source[offset..];
        const line_len = std.mem.indexOfScalar(u8, rest, '\n') orelse rest.len;
        const line = rest[0..line_len];
        const trimmed = std.mem.trim(u8, line, " \t\r");
        if (trimmed.len > 2 and trimmed[0] == '[' and trimmed[trimmed.len - 1] == ']') {
            const name = std.mem.trim(u8, trimmed[1 .. trimmed.len - 1], " \t\r");
            if (!std.mem.startsWith(u8, name, "[") and std.mem.indexOfScalar(u8, name, '.') == null) {
                try mapStarshipModule(allocator, name, imported);
            }
        }
        offset += line_len + 1;
        if (offset > source.len) break;
    }
}

fn isStarshipModuleByte(byte: u8) bool {
    return std.ascii.isAlphanumeric(byte) or byte == '_';
}

fn mapStarshipModule(allocator: std.mem.Allocator, name: []const u8, imported: *StarshipImport) !void {
    if (std.mem.eql(u8, name, "directory")) {
        try appendModule(allocator, imported, .cwd);
    } else if (std.mem.eql(u8, name, "git_branch") or std.mem.eql(u8, name, "git_status") or std.mem.eql(u8, name, "git_commit") or std.mem.eql(u8, name, "git_state")) {
        try appendModule(allocator, imported, .git_branch);
    } else if (std.mem.eql(u8, name, "python")) {
        imported.python = true;
        try appendModule(allocator, imported, .language_versions);
    } else if (std.mem.eql(u8, name, "nodejs")) {
        imported.node = true;
        try appendModule(allocator, imported, .language_versions);
    } else if (std.mem.eql(u8, name, "rust")) {
        imported.rust = true;
        try appendModule(allocator, imported, .language_versions);
    } else if (std.mem.eql(u8, name, "golang")) {
        imported.go = true;
        try appendModule(allocator, imported, .language_versions);
    } else if (std.mem.eql(u8, name, "status")) {
        try appendModule(allocator, imported, .exit_status);
    } else if (std.mem.eql(u8, name, "jobs")) {
        try appendModule(allocator, imported, .jobs);
    } else if (std.mem.eql(u8, name, "cmd_duration")) {
        try appendModule(allocator, imported, .cmd_duration);
    } else if (std.mem.eql(u8, name, "username") or std.mem.eql(u8, name, "hostname")) {
        try appendModule(allocator, imported, .user_host);
    } else if (std.mem.eql(u8, name, "time")) {
        try appendModule(allocator, imported, .time);
    } else if (!isIgnoredStarshipModule(name)) {
        try appendUnsupported(allocator, imported, name);
    }
}

fn mapP10kElement(allocator: std.mem.Allocator, name: []const u8, imported: *StarshipImport) !void {
    if (std.mem.eql(u8, name, "dir")) {
        try appendModule(allocator, imported, .cwd);
    } else if (std.mem.eql(u8, name, "vcs")) {
        try appendModule(allocator, imported, .git_branch);
    } else if (std.mem.eql(u8, name, "status")) {
        try appendModule(allocator, imported, .exit_status);
    } else if (std.mem.eql(u8, name, "background_jobs")) {
        try appendModule(allocator, imported, .jobs);
    } else if (std.mem.eql(u8, name, "command_execution_time")) {
        try appendModule(allocator, imported, .cmd_duration);
    } else if (std.mem.eql(u8, name, "context")) {
        try appendModule(allocator, imported, .user_host);
    } else if (std.mem.eql(u8, name, "time")) {
        try appendModule(allocator, imported, .time);
    } else if (std.mem.eql(u8, name, "aws") or std.mem.eql(u8, name, "gcloud") or std.mem.eql(u8, name, "azure") or std.mem.eql(u8, name, "kubecontext")) {
        try appendModule(allocator, imported, .cloud_ctx);
    } else if (std.mem.eql(u8, name, "virtualenv") or std.mem.eql(u8, name, "pyenv")) {
        imported.python = true;
        try appendModule(allocator, imported, .language_versions);
    } else if (std.mem.eql(u8, name, "nodeenv") or std.mem.eql(u8, name, "nodenv") or std.mem.eql(u8, name, "nvm")) {
        imported.node = true;
        try appendModule(allocator, imported, .language_versions);
    } else if (std.mem.eql(u8, name, "goenv") or std.mem.eql(u8, name, "go_version")) {
        imported.go = true;
        try appendModule(allocator, imported, .language_versions);
    } else if (std.mem.eql(u8, name, "rust_version")) {
        imported.rust = true;
        try appendModule(allocator, imported, .language_versions);
    } else if (!isIgnoredP10kElement(name)) {
        try appendUnsupported(allocator, imported, name);
    }
}

fn isIgnoredP10kElement(name: []const u8) bool {
    return std.mem.eql(u8, name, "os_icon") or
        std.mem.eql(u8, name, "prompt_char") or
        std.mem.eql(u8, name, "newline");
}

fn isIgnoredStarshipModule(name: []const u8) bool {
    return std.mem.eql(u8, name, "character") or
        std.mem.eql(u8, name, "line_break") or
        std.mem.eql(u8, name, "fill") or
        std.mem.eql(u8, name, "os") or
        std.mem.eql(u8, name, "shell");
}

fn appendModule(allocator: std.mem.Allocator, imported: *StarshipImport, module_id: shisa_config.ModuleId) !void {
    try appendModuleTo(allocator, &imported.modules, module_id);
}

fn appendRightModule(allocator: std.mem.Allocator, imported: *StarshipImport, module_id: shisa_config.ModuleId) !void {
    try appendModuleTo(allocator, &imported.right_modules, module_id);
}

fn appendTideModule(allocator: std.mem.Allocator, imported: *StarshipImport, module_id: shisa_config.ModuleId, right: bool) !void {
    if (right) try appendRightModule(allocator, imported, module_id) else try appendModule(allocator, imported, module_id);
}

fn appendModuleTo(allocator: std.mem.Allocator, modules: *std.ArrayList(shisa_config.ModuleId), module_id: shisa_config.ModuleId) !void {
    for (modules.items) |existing| {
        if (existing == module_id) return;
    }
    try modules.append(allocator, module_id);
}

fn appendUnsupported(allocator: std.mem.Allocator, imported: *StarshipImport, name: []const u8) !void {
    for (imported.unsupported.items) |existing| {
        if (std.mem.eql(u8, existing, name)) return;
    }
    const owned = try allocator.dupe(u8, name);
    errdefer allocator.free(owned);
    try imported.unsupported.append(allocator, owned);
}

fn renderImportedConfigAlloc(allocator: std.mem.Allocator, imported: StarshipImport) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);

    try out.appendSlice(allocator, "version = 1\n");
    try out.appendSlice(allocator, "theme = \"plain\"\n\n");
    try out.appendSlice(allocator, "[prompt]\nmodules = [");
    for (imported.modules.items, 0..) |module_id, index| {
        if (index != 0) try out.appendSlice(allocator, ", ");
        try cli_util.appendFmt(allocator, &out, "\"{s}\"", .{shisa_config.moduleIdName(module_id)});
    }
    try out.appendSlice(allocator, "]\n");

    if (containsModule(imported, .language_versions) and (imported.python or imported.node or imported.rust or imported.go)) {
        try out.appendSlice(allocator, "\n[modules.language_versions]\ndetect = [");
        var count: usize = 0;
        if (imported.python) try appendLanguage(allocator, &out, &count, "python");
        if (imported.node) try appendLanguage(allocator, &out, &count, "node");
        if (imported.rust) try appendLanguage(allocator, &out, &count, "rust");
        if (imported.go) try appendLanguage(allocator, &out, &count, "go");
        try out.appendSlice(allocator, "]\n");
    }

    if (containsModule(imported, .time)) {
        try out.appendSlice(allocator, "\n[modules.time]\nformat = \"24h\"\nutc = true\n");
    }

    if (imported.unsupported.items.len != 0) {
        try out.appendSlice(allocator, "\n# Unsupported Starship modules: ");
        for (imported.unsupported.items, 0..) |name, index| {
            if (index != 0) try out.appendSlice(allocator, ", ");
            try out.appendSlice(allocator, name);
        }
        try out.append(allocator, '\n');
    }

    return out.toOwnedSlice(allocator);
}

fn containsModule(imported: StarshipImport, module_id: shisa_config.ModuleId) bool {
    for (imported.modules.items) |existing| {
        if (existing == module_id) return true;
    }
    return false;
}

fn containsRightModule(imported: StarshipImport, module_id: shisa_config.ModuleId) bool {
    for (imported.right_modules.items) |existing| {
        if (existing == module_id) return true;
    }
    return false;
}

fn containsAnyModule(imported: StarshipImport, module_id: shisa_config.ModuleId) bool {
    return containsModule(imported, module_id) or containsRightModule(imported, module_id);
}

fn appendLanguage(allocator: std.mem.Allocator, out: *std.ArrayList(u8), count: *usize, name: []const u8) !void {
    if (count.* != 0) try out.appendSlice(allocator, ", ");
    count.* += 1;
    try cli_util.appendFmt(allocator, out, "\"{s}\"", .{name});
}

test "imports starship format into shisa modules" {
    const source =
        \\format = "$directory$git_branch$git_status$python$nodejs$status$jobs$cmd_duration$hostname$time$character"
        \\
    ;
    const output = try importStarshipAlloc(std.testing.allocator, source);
    defer std.testing.allocator.free(output);

    try std.testing.expect(std.mem.indexOf(u8, output, "modules = [\"cwd\", \"git_branch\", \"language_versions\", \"exit_status\", \"jobs\", \"cmd_duration\", \"user_host\", \"time\"]") != null);
    try std.testing.expect(std.mem.indexOf(u8, output, "detect = [\"python\", \"node\"]") != null);
    try std.testing.expect(std.mem.indexOf(u8, output, "[modules.time]") != null);
}

test "imports starship table fallback and records unsupported modules" {
    const source =
        \\[directory]
        \\[aws]
        \\[git_branch]
        \\
    ;
    const output = try importStarshipAlloc(std.testing.allocator, source);
    defer std.testing.allocator.free(output);

    try std.testing.expect(std.mem.indexOf(u8, output, "modules = [\"cwd\", \"git_branch\"]") != null);
    try std.testing.expect(std.mem.indexOf(u8, output, "Unsupported Starship modules: aws") != null);
}

test "maps p10k elements to shisa modules" {
    var imported = StarshipImport{};
    defer imported.deinit(std.testing.allocator);

    inline for (.{ "os_icon", "dir", "vcs", "virtualenv", "nodeenv", "go_version", "rust_version", "status", "background_jobs", "command_execution_time", "context", "aws", "time", "public_ip" }) |element| {
        try mapP10kElement(std.testing.allocator, element, &imported);
    }

    try std.testing.expect(containsModule(imported, .cwd));
    try std.testing.expect(containsModule(imported, .git_branch));
    try std.testing.expect(containsModule(imported, .language_versions));
    try std.testing.expect(containsModule(imported, .exit_status));
    try std.testing.expect(containsModule(imported, .jobs));
    try std.testing.expect(containsModule(imported, .cmd_duration));
    try std.testing.expect(containsModule(imported, .user_host));
    try std.testing.expect(containsModule(imported, .cloud_ctx));
    try std.testing.expect(containsModule(imported, .time));
    try std.testing.expect(imported.python);
    try std.testing.expect(imported.node);
    try std.testing.expect(imported.go);
    try std.testing.expect(imported.rust);
    try std.testing.expectEqual(@as(usize, 1), imported.unsupported.items.len);
    try std.testing.expectEqualStrings("public_ip", imported.unsupported.items[0]);
}

test "imports p10k left and right layout" {
    const source =
        \\typeset -g POWERLEVEL9K_LEFT_PROMPT_ELEMENTS=(dir vcs)
        \\typeset -g POWERLEVEL9K_RIGHT_PROMPT_ELEMENTS=(status command_execution_time time)
        \\
    ;
    const output = try importP10kAlloc(std.testing.allocator, source);
    defer std.testing.allocator.free(output);

    try std.testing.expect(std.mem.indexOf(u8, output, "# Powerlevel10k left elements: dir, vcs") != null);
    try std.testing.expect(std.mem.indexOf(u8, output, "# Powerlevel10k right elements: status, command_execution_time, time") != null);
    try std.testing.expect(std.mem.indexOf(u8, output, "modules = [\"cwd\", \"git_branch\", \"exit_status\", \"cmd_duration\", \"time\"]") != null);
}

test "imports p10k instant prompt mapping" {
    const source =
        \\typeset -g POWERLEVEL9K_LEFT_PROMPT_ELEMENTS=(dir)
        \\typeset -g POWERLEVEL9K_INSTANT_PROMPT=quiet
        \\
    ;
    const output = try importP10kAlloc(std.testing.allocator, source);
    defer std.testing.allocator.free(output);

    try std.testing.expect(std.mem.indexOf(u8, output, "# Powerlevel10k instant_prompt: quiet") != null);
    try std.testing.expect(std.mem.indexOf(u8, output, "# Shisa instant prompt: SHISA_INSTANT=1") != null);
}

test "imports disabled p10k instant prompt mapping" {
    const source =
        \\typeset -g POWERLEVEL9K_LEFT_PROMPT_ELEMENTS=(dir)
        \\typeset -g POWERLEVEL9K_INSTANT_PROMPT=off
        \\
    ;
    const output = try importP10kAlloc(std.testing.allocator, source);
    defer std.testing.allocator.free(output);

    try std.testing.expect(std.mem.indexOf(u8, output, "# Powerlevel10k instant_prompt: off") != null);
    try std.testing.expect(std.mem.indexOf(u8, output, "# Shisa instant prompt: SHISA_INSTANT=0") != null);
}

test "imports p10k unsupported elements into migration notes" {
    const source =
        \\typeset -g POWERLEVEL9K_LEFT_PROMPT_ELEMENTS=(dir public_ip battery weird_segment)
        \\
    ;
    const result = try importP10kResultAlloc(std.testing.allocator, source);
    defer result.deinit(std.testing.allocator);

    try std.testing.expect(std.mem.indexOf(u8, result.config, "Unsupported Powerlevel10k elements: public_ip, battery, weird_segment") != null);
    const notes = result.notes orelse return error.MissingP10kNotes;
    try std.testing.expect(std.mem.indexOf(u8, notes, "# Powerlevel10k Migration Notes") != null);
    try std.testing.expect(std.mem.indexOf(u8, notes, "- `public_ip`: No core public-IP module") != null);
    try std.testing.expect(std.mem.indexOf(u8, notes, "- `battery`: No core battery module") != null);
    try std.testing.expect(std.mem.indexOf(u8, notes, "- `weird_segment`: No Shisa core mapping") != null);
}

test "omits p10k migration notes when all elements map" {
    const source =
        \\typeset -g POWERLEVEL9K_LEFT_PROMPT_ELEMENTS=(dir vcs)
        \\
    ;
    const result = try importP10kResultAlloc(std.testing.allocator, source);
    defer result.deinit(std.testing.allocator);

    try std.testing.expect(result.notes == null);
}

test "parses oh-my-posh json theme blocks" {
    const source =
        \\{
        \\  "version": 3,
        \\  "palette": {"accent": "#3366ff"},
        \\  "blocks": [
        \\    {"type": "prompt", "alignment": "left", "segments": [{"type": "path", "template": "cwd:{{ .Path }}!", "foreground": "p:accent"}, {"type": "git"}]},
        \\    {"type": "rprompt", "alignment": "right", "segments": [{"type": "time"}]}
        \\  ]
        \\}
        \\
    ;
    var theme = try parseOmpTheme(std.testing.allocator, source);
    defer theme.deinit(std.testing.allocator);

    try std.testing.expectEqual(@as(usize, 2), theme.blocks.items.len);
    try std.testing.expectEqual(@as(usize, 1), theme.palette.items.len);
    try std.testing.expectEqualStrings("accent", theme.palette.items[0].name);
    try std.testing.expectEqualStrings("#3366ff", theme.palette.items[0].value);
    try std.testing.expectEqualStrings("prompt", theme.blocks.items[0].block_type.?);
    try std.testing.expectEqualStrings("left", theme.blocks.items[0].alignment.?);
    try std.testing.expectEqualStrings("path", theme.blocks.items[0].segments.items[0].kind.?);
    try std.testing.expectEqualStrings("cwd:{{ .Path }}!", theme.blocks.items[0].segments.items[0].template.?);
    try std.testing.expectEqualStrings("p:accent", theme.blocks.items[0].segments.items[0].foreground.?);
    try std.testing.expectEqualStrings("git", theme.blocks.items[0].segments.items[1].kind.?);
    try std.testing.expectEqualStrings("rprompt", theme.blocks.items[1].block_type.?);
    try std.testing.expectEqualStrings("time", theme.blocks.items[1].segments.items[0].kind.?);
}

test "parses oh-my-posh yaml theme blocks" {
    const source =
        \\version: 3
        \\palette:
        \\  accent: "#3366ff"
        \\blocks:
        \\  - type: prompt
        \\    alignment: left
        \\    segments:
        \\      - type: path
        \\        template: "cwd:{{ .Path }}!"
        \\        foreground: p:accent
        \\      - foreground: "#fff"
        \\        type: git
        \\  - type: rprompt
        \\    alignment: right
        \\    segments:
        \\      - type: time
        \\
    ;
    var theme = try parseOmpTheme(std.testing.allocator, source);
    defer theme.deinit(std.testing.allocator);

    try std.testing.expectEqual(@as(usize, 2), theme.blocks.items.len);
    try std.testing.expectEqual(@as(usize, 1), theme.palette.items.len);
    try std.testing.expectEqualStrings("prompt", theme.blocks.items[0].block_type.?);
    try std.testing.expectEqualStrings("left", theme.blocks.items[0].alignment.?);
    try std.testing.expectEqualStrings("path", theme.blocks.items[0].segments.items[0].kind.?);
    try std.testing.expectEqualStrings("cwd:{{ .Path }}!", theme.blocks.items[0].segments.items[0].template.?);
    try std.testing.expectEqualStrings("p:accent", theme.blocks.items[0].segments.items[0].foreground.?);
    try std.testing.expectEqualStrings("git", theme.blocks.items[0].segments.items[1].kind.?);
    try std.testing.expectEqualStrings("rprompt", theme.blocks.items[1].block_type.?);
    try std.testing.expectEqualStrings("right", theme.blocks.items[1].alignment.?);
    try std.testing.expectEqualStrings("time", theme.blocks.items[1].segments.items[0].kind.?);
}

test "maps oh-my-posh segments to shisa modules" {
    const source =
        \\{
        \\  "blocks": [
        \\    {
        \\      "type": "prompt",
        \\      "segments": [
        \\        {"type": "path"},
        \\        {"type": "git"},
        \\        {"type": "jujutsu"},
        \\        {"type": "python"},
        \\        {"type": "node"},
        \\        {"type": "go"},
        \\        {"type": "rust"},
        \\        {"type": "status"},
        \\        {"type": "executiontime"},
        \\        {"type": "session"},
        \\        {"type": "aws"},
        \\        {"type": "gcp"},
        \\        {"type": "az"},
        \\        {"type": "kubectl"},
        \\        {"type": "terraform"},
        \\        {"type": "pulumi"},
        \\        {"type": "time"},
        \\        {"type": "text"},
        \\        {"type": "battery"}
        \\      ]
        \\    }
        \\  ]
        \\}
        \\
    ;
    var theme = try parseOmpTheme(std.testing.allocator, source);
    defer theme.deinit(std.testing.allocator);
    var imported = StarshipImport{};
    defer imported.deinit(std.testing.allocator);

    try scanOmpTheme(std.testing.allocator, theme, &imported);

    try std.testing.expect(containsModule(imported, .cwd));
    try std.testing.expect(containsModule(imported, .git_branch));
    try std.testing.expect(containsModule(imported, .language_versions));
    try std.testing.expect(containsModule(imported, .exit_status));
    try std.testing.expect(containsModule(imported, .cmd_duration));
    try std.testing.expect(containsModule(imported, .user_host));
    try std.testing.expect(containsModule(imported, .cloud_ctx));
    try std.testing.expect(containsModule(imported, .iac_workspace));
    try std.testing.expect(containsModule(imported, .time));
    try std.testing.expect(imported.python);
    try std.testing.expect(imported.node);
    try std.testing.expect(imported.go);
    try std.testing.expect(imported.rust);
    try std.testing.expectEqual(@as(usize, 1), imported.unsupported.items.len);
    try std.testing.expectEqualStrings("battery", imported.unsupported.items[0]);
}

test "translates oh-my-posh simple template wrappers" {
    const layout = (try translateOmpTemplateLayoutAlloc(std.testing.allocator, "cwd:<blue>{{ .Path }}</>!")).?;
    defer layout.deinit(std.testing.allocator);

    try std.testing.expectEqualStrings("cwd:", layout.prefix);
    try std.testing.expectEqualStrings("!", layout.suffix);
    try std.testing.expect(try translateOmpTemplateLayoutAlloc(std.testing.allocator, "{{ .A }}{{ .B }}") == null);
    try std.testing.expect(try translateOmpTemplateLayoutAlloc(std.testing.allocator, "{{ if .A }}x{{ end }}") == null);
}

test "imports oh-my-posh layout and template sidecar" {
    const source =
        \\{
        \\  "blocks": [
        \\    {
        \\      "type": "prompt",
        \\      "alignment": "left",
        \\      "segments": [
        \\        {"type": "path", "template": "cwd:<blue>{{ .Path }}</>!"},
        \\        {"type": "git", "template": " on {{ .HEAD }}"}
        \\      ]
        \\    },
        \\    {
        \\      "type": "rprompt",
        \\      "alignment": "right",
        \\      "segments": [
        \\        {"type": "time", "template": "{{ .CurrentDate }}"}
        \\      ]
        \\    }
        \\  ]
        \\}
        \\
    ;
    const result = try importOhMyPoshResultAlloc(std.testing.allocator, source);
    defer result.deinit(std.testing.allocator);

    try std.testing.expect(std.mem.indexOf(u8, result.config, "theme = \"./oh-my-posh-theme.toml\"") != null);
    try std.testing.expect(std.mem.indexOf(u8, result.config, "# Oh My Posh left layout: path, git") != null);
    try std.testing.expect(std.mem.indexOf(u8, result.config, "# Oh My Posh right layout: time") != null);
    try std.testing.expect(std.mem.indexOf(u8, result.config, "modules = [\"cwd\", \"git_branch\", \"time\"]") != null);
    const theme = result.theme orelse return error.MissingOmpTheme;
    try std.testing.expect(std.mem.indexOf(u8, theme, "[segments.cwd]") != null);
    try std.testing.expect(std.mem.indexOf(u8, theme, "prefix = \"cwd:\"") != null);
    try std.testing.expect(std.mem.indexOf(u8, theme, "suffix = \"!\"") != null);
    try std.testing.expect(std.mem.indexOf(u8, theme, "[segments.git_branch]") != null);
    try std.testing.expect(std.mem.indexOf(u8, theme, "prefix = \" on \"") != null);
}

test "maps oh-my-posh palette through oklab slots" {
    var theme = OmpTheme{};
    defer theme.deinit(std.testing.allocator);
    try appendOmpPaletteEntry(std.testing.allocator, &theme, "accent", "#3366ff");
    try appendOmpPaletteEntry(std.testing.allocator, &theme, "success", "#00ff66");
    try appendOmpPaletteEntry(std.testing.allocator, &theme, "danger", "#ff0033");

    const mapped = mapOmpPalette(theme);
    try std.testing.expect(mapped.has_source);
    try std.testing.expectEqualStrings("success", nearestMappedPaletteSlot(mapped, .{ .r = 0, .g = 238, .b = 80 }));
    try std.testing.expectEqualStrings("danger", nearestMappedPaletteSlot(mapped, .{ .r = 238, .g = 0, .b = 40 }));
}

test "imports oh-my-posh palette and segment colors" {
    const source =
        \\{
        \\  "palette": {
        \\    "fg": "#f8f8f2",
        \\    "muted": "#777777",
        \\    "accent": "#3366ff",
        \\    "success": "#00ff66",
        \\    "warning": "#ffaa00",
        \\    "danger": "#ff0033"
        \\  },
        \\  "blocks": [
        \\    {
        \\      "type": "prompt",
        \\      "segments": [
        \\        {"type": "path", "foreground": "p:accent", "template": "{{ .Path }}"},
        \\        {"type": "status", "background": "#ff0033", "template": "exit:{{ .Code }}"}
        \\      ]
        \\    }
        \\  ]
        \\}
        \\
    ;
    const result = try importOhMyPoshResultAlloc(std.testing.allocator, source);
    defer result.deinit(std.testing.allocator);
    const theme = result.theme orelse return error.MissingOmpTheme;

    try std.testing.expect(std.mem.indexOf(u8, theme, "[palette]") != null);
    try std.testing.expect(std.mem.indexOf(u8, theme, "accent = \"#3366FF\"") != null);
    try std.testing.expect(std.mem.indexOf(u8, theme, "danger = \"#FF0033\"") != null);
    try std.testing.expect(std.mem.indexOf(u8, theme, "[segments.cwd]") != null);
    try std.testing.expect(std.mem.indexOf(u8, theme, "fg = \"@accent\"") != null);
    try std.testing.expect(std.mem.indexOf(u8, theme, "[segments.exit_status]") != null);
    try std.testing.expect(std.mem.indexOf(u8, theme, "bg = \"@danger\"") != null);
}

test "imports oh-my-posh migration notes" {
    const source =
        \\{
        \\  "blocks": [
        \\    {
        \\      "type": "prompt",
        \\      "segments": [
        \\        {"type": "battery"},
        \\        {"type": "path", "template": "{{ if .Writable }}{{ .Path }}{{ end }}"},
        \\        {"type": "git", "foreground": "p:missing"}
        \\      ]
        \\    }
        \\  ]
        \\}
        \\
    ;
    const result = try importOhMyPoshResultAlloc(std.testing.allocator, source);
    defer result.deinit(std.testing.allocator);
    const notes = result.notes orelse return error.MissingOmpNotes;

    try std.testing.expect(std.mem.indexOf(u8, notes, "# Oh My Posh Migration Notes") != null);
    try std.testing.expect(std.mem.indexOf(u8, notes, "## Unsupported Segments") != null);
    try std.testing.expect(std.mem.indexOf(u8, notes, "- `battery`: No core battery module.") != null);
    try std.testing.expect(std.mem.indexOf(u8, notes, "## Untranslated Templates") != null);
    try std.testing.expect(std.mem.indexOf(u8, notes, "- `path`: template requires manual port.") != null);
    try std.testing.expect(std.mem.indexOf(u8, notes, "## Unresolved Colors") != null);
    try std.testing.expect(std.mem.indexOf(u8, notes, "- `git` foreground `p:missing` could not be resolved.") != null);
}

test "omits oh-my-posh migration notes when import is complete" {
    const source =
        \\{
        \\  "blocks": [
        \\    {"type": "prompt", "segments": [{"type": "path", "template": "cwd:{{ .Path }}"}]}
        \\  ]
        \\}
        \\
    ;
    const result = try importOhMyPoshResultAlloc(std.testing.allocator, source);
    defer result.deinit(std.testing.allocator);

    try std.testing.expect(result.notes == null);
}

fn expectTideValues(config: TideConfig, name: []const u8, expected: []const []const u8) !void {
    const setting = config.find(name) orelse return error.MissingTideSetting;
    try std.testing.expectEqual(expected.len, setting.values.items.len);
    for (expected, 0..) |value, index| {
        try std.testing.expectEqualStrings(value, setting.values.items[index]);
    }
}

test "parses tide configure output" {
    const source =
        \\tide_left_prompt_items pwd git newline character
        \\tide_right_prompt_items status cmd_duration time
        \\tide_left_prompt_prefix ''
        \\tide_prompt_transient_enabled false
        \\tide_git_color_branch $_tide_color_green
        \\
    ;
    var config = try parseTideConfig(std.testing.allocator, source);
    defer config.deinit(std.testing.allocator);

    try expectTideValues(config, "tide_left_prompt_items", &.{ "pwd", "git", "newline", "character" });
    try expectTideValues(config, "tide_right_prompt_items", &.{ "status", "cmd_duration", "time" });
    try expectTideValues(config, "tide_left_prompt_prefix", &.{""});
    try expectTideValues(config, "tide_prompt_transient_enabled", &.{"false"});
    try expectTideValues(config, "tide_git_color_branch", &.{"$_tide_color_green"});
}

test "parses tide fish set syntax" {
    const source =
        \\set -g tide_left_prompt_items pwd git
        \\set --global tide_right_prompt_items status cmd_duration
        \\set -gx tide_prompt_transient_enabled true
        \\set -g not_tide ignored
        \\
    ;
    var config = try parseTideConfig(std.testing.allocator, source);
    defer config.deinit(std.testing.allocator);

    try expectTideValues(config, "tide_left_prompt_items", &.{ "pwd", "git" });
    try expectTideValues(config, "tide_right_prompt_items", &.{ "status", "cmd_duration" });
    try expectTideValues(config, "tide_prompt_transient_enabled", &.{"true"});
    try std.testing.expect(config.find("not_tide") == null);
}

test "maps tide items to shisa modules" {
    const source =
        \\tide_left_prompt_items pwd git newline character
        \\tide_right_prompt_items status cmd_duration context jobs node python rustc go aws gcloud kubectl terraform pulumi time bun
        \\
    ;
    var config = try parseTideConfig(std.testing.allocator, source);
    defer config.deinit(std.testing.allocator);
    var imported = StarshipImport{};
    defer imported.deinit(std.testing.allocator);

    try scanTideConfig(std.testing.allocator, config, &imported);

    try std.testing.expect(containsModule(imported, .cwd));
    try std.testing.expect(containsModule(imported, .git_branch));
    try std.testing.expect(containsRightModule(imported, .exit_status));
    try std.testing.expect(containsRightModule(imported, .cmd_duration));
    try std.testing.expect(containsRightModule(imported, .user_host));
    try std.testing.expect(containsRightModule(imported, .jobs));
    try std.testing.expect(containsRightModule(imported, .language_versions));
    try std.testing.expect(containsRightModule(imported, .cloud_ctx));
    try std.testing.expect(containsRightModule(imported, .iac_workspace));
    try std.testing.expect(containsRightModule(imported, .time));
    try std.testing.expect(imported.node);
    try std.testing.expect(imported.python);
    try std.testing.expect(imported.rust);
    try std.testing.expect(imported.go);
    try std.testing.expectEqual(@as(usize, 1), imported.unsupported.items.len);
    try std.testing.expectEqualStrings("bun", imported.unsupported.items[0]);
}

test "imports tide config and migration notes" {
    const source =
        \\tide_left_prompt_items pwd git newline character
        \\tide_right_prompt_items status cmd_duration context jobs bun
        \\tide_prompt_transient_enabled true
        \\tide_left_prompt_frame_enabled true
        \\tide_left_prompt_separator_same_color '>'
        \\tide_git_color_branch $_tide_color_green
        \\
    ;
    const result = try importTideResultAlloc(std.testing.allocator, source);
    defer result.deinit(std.testing.allocator);

    try std.testing.expect(std.mem.indexOf(u8, result.config, "# Tide left items: pwd, git, newline, character") != null);
    try std.testing.expect(std.mem.indexOf(u8, result.config, "# Tide right items: status, cmd_duration, context, jobs, bun") != null);
    try std.testing.expect(std.mem.indexOf(u8, result.config, "modules = [\"cwd\", \"git_branch\"]") != null);
    try std.testing.expect(std.mem.indexOf(u8, result.config, "right_modules = [\"exit_status\", \"cmd_duration\", \"user_host\", \"jobs\"]") != null);
    const notes = result.notes orelse return error.MissingTideNotes;
    try std.testing.expect(std.mem.indexOf(u8, notes, "# Tide Migration Notes") != null);
    try std.testing.expect(std.mem.indexOf(u8, notes, "- `bun`: No core Bun detector.") != null);
    try std.testing.expect(std.mem.indexOf(u8, notes, "`tide_prompt_transient_enabled=true` is not imported") != null);
    try std.testing.expect(std.mem.indexOf(u8, notes, "frame/separator/prefix/suffix") != null);
    try std.testing.expect(std.mem.indexOf(u8, notes, "$_tide_color_*") != null);
}

test "omits tide migration notes for plain left prompt" {
    const source =
        \\tide_left_prompt_items pwd git
        \\
    ;
    const result = try importTideResultAlloc(std.testing.allocator, source);
    defer result.deinit(std.testing.allocator);

    try std.testing.expect(result.notes == null);
}

test "imports pure preset config" {
    const output = try pureConfigAlloc(std.testing.allocator);
    defer std.testing.allocator.free(output);

    try std.testing.expect(std.mem.indexOf(u8, output, "theme = \"pure\"") != null);
    try std.testing.expect(std.mem.indexOf(u8, output, "modules = [\"cwd\", \"git_branch\", \"exit_status\", \"cmd_duration\", \"jobs\", \"user_host\"]") != null);
    try std.testing.expect(std.mem.indexOf(u8, output, "threshold_ms = 5000") != null);
    try std.testing.expect(std.mem.indexOf(u8, output, "mode = \"ssh\"") != null);
}

fn bench(allocator: std.mem.Allocator, args: []const []const u8) !void {
    const bench_config = try parseBench(args);
    try ensureHyperfine(allocator);

    const self_path = try std.fs.selfExePathAlloc(allocator);
    defer allocator.free(self_path);
    const daemon_path = try siblingExecutablePath(allocator, "shisad");
    defer allocator.free(daemon_path);
    const cwd = try std.fs.cwd().realpathAlloc(allocator, ".");
    defer allocator.free(cwd);
    const socket_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-bench-{x}.sock", .{std.crypto.random.int(u64)});
    defer allocator.free(socket_path);
    const log_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-bench-{x}.log", .{std.crypto.random.int(u64)});
    defer allocator.free(log_path);
    defer std.fs.deleteFileAbsolute(socket_path) catch {};
    defer std.fs.deleteFileAbsolute(log_path) catch {};

    var daemon = std.process.Child.init(&.{ daemon_path, "--foreground", "--socket", socket_path, "--log", log_path }, allocator);
    daemon.stdin_behavior = .Ignore;
    daemon.stdout_behavior = .Ignore;
    daemon.stderr_behavior = .Ignore;
    try daemon.spawn();
    defer _ = daemon.kill() catch {};

    try waitForPath(socket_path, 1000);
    const workload = try benchWorkloadAlloc(allocator, self_path, socket_path, cwd);
    defer allocator.free(workload);
    try runHyperfine(allocator, workload, bench_config);
}

const BenchConfig = struct {
    export_json: ?[]const u8 = null,
};

fn parseBench(args: []const []const u8) !BenchConfig {
    var config = BenchConfig{};
    var i: usize = 0;
    while (i < args.len) : (i += 1) {
        const arg = args[i];
        if (std.mem.eql(u8, arg, "--export-json")) {
            config.export_json = try cli_util.nextValue(args, &i);
        } else {
            return error.UnknownBenchArgument;
        }
    }
    return config;
}

fn ensureHyperfine(allocator: std.mem.Allocator) !void {
    const result = std.process.Child.run(.{
        .allocator = allocator,
        .argv = &.{ "hyperfine", "--version" },
        .max_output_bytes = 4096,
        .expand_arg0 = .expand,
    }) catch |err| switch (err) {
        error.FileNotFound => {
            try std.fs.File.stderr().writeAll("shisa bench: hyperfine not found in PATH\n");
            return err;
        },
        else => return err,
    };
    defer allocator.free(result.stdout);
    defer allocator.free(result.stderr);
    if (!cli_util.exitedZero(result.term)) return error.HyperfineUnavailable;
}

fn runHyperfine(allocator: std.mem.Allocator, workload: []const u8, bench_config: BenchConfig) !void {
    var argv: std.ArrayList([]const u8) = .empty;
    defer argv.deinit(allocator);
    try argv.appendSlice(allocator, &.{ "hyperfine", "--warmup", "5", "--runs", "25" });
    if (bench_config.export_json) |path| {
        try argv.appendSlice(allocator, &.{ "--export-json", path });
    }
    try argv.append(allocator, workload);

    const result = try std.process.Child.run(.{
        .allocator = allocator,
        .argv = argv.items,
        .max_output_bytes = 8 * 1024 * 1024,
        .expand_arg0 = .expand,
    });
    defer allocator.free(result.stdout);
    defer allocator.free(result.stderr);

    try std.fs.File.stdout().writeAll(result.stdout);
    try std.fs.File.stderr().writeAll(result.stderr);
    if (!cli_util.exitedZero(result.term)) return error.BenchmarkFailed;
}

fn benchWorkloadAlloc(allocator: std.mem.Allocator, self_path: []const u8, socket_path: []const u8, cwd: []const u8) ![]u8 {
    const quoted_self = try shellQuoteAlloc(allocator, self_path);
    defer allocator.free(quoted_self);
    const quoted_socket = try shellQuoteAlloc(allocator, socket_path);
    defer allocator.free(quoted_socket);
    const quoted_cwd = try shellQuoteAlloc(allocator, cwd);
    defer allocator.free(quoted_cwd);
    return std.fmt.allocPrint(
        allocator,
        "{s} prompt --socket {s} --cwd {s} --shell zsh --cols 80 --rows 24",
        .{ quoted_self, quoted_socket, quoted_cwd },
    );
}

fn shellQuoteAlloc(allocator: std.mem.Allocator, value: []const u8) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);
    try out.append(allocator, '\'');
    for (value) |byte| {
        if (byte == '\'') {
            try out.appendSlice(allocator, "'\\''");
        } else {
            try out.append(allocator, byte);
        }
    }
    try out.append(allocator, '\'');
    return out.toOwnedSlice(allocator);
}

fn siblingExecutablePath(allocator: std.mem.Allocator, name: []const u8) ![]u8 {
    const self_path = try std.fs.selfExePathAlloc(allocator);
    defer allocator.free(self_path);
    const dir = std.fs.path.dirname(self_path) orelse ".";
    return std.fs.path.join(allocator, &.{ dir, name });
}

fn waitForPath(path: []const u8, timeout_ms: i64) !void {
    const start = std.time.milliTimestamp();
    while (std.time.milliTimestamp() - start < timeout_ms) {
        std.fs.cwd().access(path, .{}) catch {
            std.Thread.sleep(10 * std.time.ns_per_ms);
            continue;
        };
        return;
    }
    return error.Timeout;
}

test "shell quoting handles spaces and quotes" {
    const quoted = try shellQuoteAlloc(std.testing.allocator, "/tmp/a b/c'd");
    defer std.testing.allocator.free(quoted);
    try std.testing.expectEqualStrings("'/tmp/a b/c'\\''d'", quoted);
}

test "bench workload targets prompt command" {
    const workload = try benchWorkloadAlloc(std.testing.allocator, "/tmp/shisa", "/tmp/sock", "/tmp/repo");
    defer std.testing.allocator.free(workload);
    try std.testing.expectEqualStrings("'/tmp/shisa' prompt --socket '/tmp/sock' --cwd '/tmp/repo' --shell zsh --cols 80 --rows 24", workload);
}

fn cacheCommand(allocator: std.mem.Allocator, args: []const []const u8) !void {
    const action = if (args.len == 0) "stats" else args[0];
    const output = if (std.mem.eql(u8, action, "stats")) stats: {
        if (args.len > 1) return error.UnknownCacheArgument;
        break :stats try cacheStatsAlloc(allocator, .{});
    } else if (std.mem.eql(u8, action, "clear")) clear: {
        const module = try parseCacheClearModule(args[1..]);
        const path = (try cacheClearPathAlloc(allocator)) orelse {
            break :clear try std.fmt.allocPrint(allocator, "{{\"cleared\":false,\"reason\":\"missing_home\"}}\n", .{});
        };
        defer allocator.free(path);
        break :clear try cacheClearOutputAlloc(allocator, path, module);
    } else return error.UnknownCacheArgument;
    defer allocator.free(output);
    try std.fs.File.stdout().writeAll(output);
}

fn cacheStatsAlloc(allocator: std.mem.Allocator, options: daemon_cache.Options) ![]u8 {
    return std.fmt.allocPrint(
        allocator,
        "{{\"module_cache\":{{\"entries\":0,\"max_entries\":{d},\"max_age_ns\":{d}}},\"prompt_cache\":{{\"entries\":0}}}}\n",
        .{ options.max_entries, options.max_age_ns },
    );
}

test "cache stats output is json object" {
    const output = try cacheStatsAlloc(std.testing.allocator, .{ .max_entries = 2, .max_age_ns = 3 });
    defer std.testing.allocator.free(output);
    try std.testing.expectEqualStrings("{\"module_cache\":{\"entries\":0,\"max_entries\":2,\"max_age_ns\":3},\"prompt_cache\":{\"entries\":0}}\n", output);
}

fn parseCacheClearModule(args: []const []const u8) !?[]const u8 {
    var module: ?[]const u8 = null;
    var i: usize = 0;
    while (i < args.len) : (i += 1) {
        const arg = args[i];
        if (std.mem.eql(u8, arg, "--module")) {
            module = try cli_util.nextValue(args, &i);
        } else if (std.mem.startsWith(u8, arg, "--module=")) {
            module = arg["--module=".len..];
        } else {
            return error.UnknownCacheArgument;
        }
    }
    if (module) |value| if (value.len == 0) return error.UnknownCacheArgument;
    return module;
}

fn cacheClearPathAlloc(allocator: std.mem.Allocator) !?[]u8 {
    const home = std.process.getEnvVarOwned(allocator, "HOME") catch |err| switch (err) {
        error.EnvironmentVariableNotFound => return null,
        else => return err,
    };
    defer allocator.free(home);
    return daemon_cache.defaultPersistPathAlloc(allocator, home);
}

fn cacheClearOutputAlloc(allocator: std.mem.Allocator, path: []const u8, module: ?[]const u8) ![]u8 {
    var store = daemon_cache.Store.initWithOptions(allocator, .{ .max_age_ns = 0 });
    defer store.deinit();
    try store.loadFromFile(path);
    const before = store.count();
    if (module) |module_id| {
        try store.invalidateModule(module_id);
        if (store.count() == 0) {
            std.fs.deleteFileAbsolute(path) catch |err| switch (err) {
                error.FileNotFound => {},
                else => return err,
            };
        } else {
            try store.saveToFile(path);
        }
        const escaped_module = try daemon_json.escapeAlloc(allocator, module_id);
        defer allocator.free(escaped_module);
        return std.fmt.allocPrint(allocator, "{{\"cleared\":true,\"module\":\"{s}\",\"entries_before\":{d},\"entries_after\":{d}}}\n", .{ escaped_module, before, store.count() });
    }

    store.clear();
    std.fs.deleteFileAbsolute(path) catch |err| switch (err) {
        error.FileNotFound => {},
        else => return err,
    };
    return std.fmt.allocPrint(allocator, "{{\"cleared\":true,\"module\":null,\"entries_before\":{d},\"entries_after\":0}}\n", .{before});
}

test "cache clear parses module arg" {
    try std.testing.expectEqualStrings("git_branch", (try parseCacheClearModule(&.{"--module=git_branch"})).?);
    try std.testing.expectEqualStrings("language_versions", (try parseCacheClearModule(&.{ "--module", "language_versions" })).?);
    try std.testing.expect((try parseCacheClearModule(&.{})) == null);
}

test "cache clear removes all persisted entries" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-cache-clear-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);
    const path = try std.fmt.allocPrint(allocator, "{s}/cache.bin", .{dir_path});
    defer allocator.free(path);

    var store = daemon_cache.Store.initWithOptions(allocator, .{ .max_age_ns = 0 });
    defer store.deinit();
    try store.putAt("git_branch", "/repo", "git:main", 1, 1);
    try store.putAt("language_versions", "/repo", "py:3.14", 2, 1);
    try store.saveToFile(path);

    const output = try cacheClearOutputAlloc(allocator, path, null);
    defer allocator.free(output);
    try std.testing.expectEqualStrings("{\"cleared\":true,\"module\":null,\"entries_before\":2,\"entries_after\":0}\n", output);
    try std.testing.expectError(error.FileNotFound, std.fs.cwd().access(path, .{}));
}

test "cache clear removes one module from persisted entries" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-cache-clear-module-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);
    const path = try std.fmt.allocPrint(allocator, "{s}/cache.bin", .{dir_path});
    defer allocator.free(path);

    var store = daemon_cache.Store.initWithOptions(allocator, .{ .max_age_ns = 0 });
    defer store.deinit();
    try store.putAt("git_branch", "/repo", "git:main", 1, 1);
    try store.putAt("language_versions", "/repo", "py:3.14", 2, 1);
    try store.saveToFile(path);

    const output = try cacheClearOutputAlloc(allocator, path, "git_branch");
    defer allocator.free(output);
    try std.testing.expectEqualStrings("{\"cleared\":true,\"module\":\"git_branch\",\"entries_before\":2,\"entries_after\":1}\n", output);

    var loaded = daemon_cache.Store.initWithOptions(allocator, .{ .max_age_ns = 0 });
    defer loaded.deinit();
    try loaded.loadFromFile(path);
    try std.testing.expect(try loaded.getAt("git_branch", "/repo", 2) == null);
    try std.testing.expect((try loaded.getAt("language_versions", "/repo", 2)) != null);
}

fn pinCommand(allocator: std.mem.Allocator, args: []const []const u8) !void {
    if (args.len != 1) return error.UnknownPinArgument;
    const path = try std.fs.cwd().realpathAlloc(allocator, args[0]);
    defer allocator.free(path);
    const pins_path = try pinsPath(allocator);
    defer allocator.free(pins_path);
    try appendPin(allocator, pins_path, path);

    const message = try std.fmt.allocPrint(allocator, "pinned {s}\n", .{path});
    defer allocator.free(message);
    try std.fs.File.stdout().writeAll(message);
}

fn pinsPath(allocator: std.mem.Allocator) ![]u8 {
    const config_path = try cli_util.defaultConfigPath(allocator);
    defer allocator.free(config_path);
    const dir = std.fs.path.dirname(config_path) orelse return error.MissingConfigDir;
    return std.fmt.allocPrint(allocator, "{s}/pins", .{dir});
}

fn appendPin(allocator: std.mem.Allocator, pins_path: []const u8, path: []const u8) !void {
    if (std.fs.path.dirname(pins_path)) |parent| {
        try std.fs.cwd().makePath(parent);
    }

    if (try pinExists(allocator, pins_path, path)) return;

    var file = try std.fs.createFileAbsolute(pins_path, .{ .truncate = false, .read = true });
    defer file.close();
    try file.seekFromEnd(0);
    try file.writeAll(path);
    try file.writeAll("\n");
}

fn pinExists(allocator: std.mem.Allocator, pins_path: []const u8, path: []const u8) !bool {
    const contents = std.fs.cwd().readFileAlloc(allocator, pins_path, 1024 * 1024) catch |err| switch (err) {
        error.FileNotFound => return false,
        else => return err,
    };
    defer allocator.free(contents);

    var lines = std.mem.tokenizeScalar(u8, contents, '\n');
    while (lines.next()) |line| {
        if (std.mem.eql(u8, line, path)) return true;
    }
    return false;
}

test "appends pin once" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-pin-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    const pins_path = try std.fmt.allocPrint(allocator, "{s}/pins", .{dir_path});
    defer allocator.free(pins_path);
    try appendPin(allocator, pins_path, "/tmp/repo");
    try appendPin(allocator, pins_path, "/tmp/repo");

    const contents = try std.fs.cwd().readFileAlloc(allocator, pins_path, 4096);
    defer allocator.free(contents);
    try std.testing.expectEqualStrings("/tmp/repo\n", contents);
}

test "parses bench export json flag" {
    const args = [_][]const u8{ "--export-json", "/tmp/out.json" };
    const config = try parseBench(args[0..]);
    try std.testing.expectEqualStrings("/tmp/out.json", config.export_json.?);
}

fn reportPromptPayloadBenchIterationAlloc(allocator: std.mem.Allocator) ![]u8 {
    const cwd = std.fs.cwd().realpathAlloc(allocator, ".");
    const resolved_cwd = cwd catch |err| return err;
    defer allocator.free(resolved_cwd);
    const config = PromptConfig{ .no_async = true, .cols = 80, .rows = 24 };
    const module_options = defaultPromptModuleOptions();
    return buildPromptPayloadWithModuleOptions(allocator, config, resolved_cwd, module_options);
}

const PromptConfig = struct {
    socket_path: ?[]const u8 = null,
    cwd: ?[]const u8 = null,
    exit: i32 = 0,
    jobs: u32 = 0,
    duration_ms: u64 = 0,
    time: bool = false,
    no_async: bool = false,
    instant: bool = false,
    auto_spawn: bool = false,
    a11y: bool = false,
    explain_a11y: bool = false,
    rtl: bool = false,
    rtl_reverse: bool = false,
    right: bool = false,
    shell: []const u8 = "zsh",
    cols: u16 = 80,
    rows: u16 = 24,
};

const prompt_auto_spawn_grace_ms: i64 = 100;

fn prompt(allocator: std.mem.Allocator, args: []const []const u8) !void {
    const config = try parsePrompt(args);
    if (config.explain_a11y) {
        const output = try promptA11yExplanationAlloc(allocator);
        defer allocator.free(output);
        try std.fs.File.stdout().writeAll(output);
        return;
    }
    const socket_path = if (config.socket_path) |path| path else try paths.defaultSocketPath(allocator);
    defer if (config.socket_path == null) allocator.free(socket_path);
    const cwd = if (config.cwd) |path| path else try std.fs.cwd().realpathAlloc(allocator, ".");
    defer if (config.cwd == null) allocator.free(cwd);

    const payload = try buildPromptPayload(allocator, config, cwd);
    defer allocator.free(payload);

    if (config.instant) {
        if (try readInstantPrompt(allocator)) |cached| {
            defer allocator.free(cached);
            try writePromptText(allocator, cached, config.a11y, cwd);
            return;
        }
    }

    const response_payload = client.requestAlloc(allocator, socket_path, payload) catch |err| response: {
        if (!config.auto_spawn) return err;
        if (try autoSpawnPromptRequestAlloc(allocator, socket_path, payload)) |retried| break :response retried;
        if (config.right) return;
        const prompt_text = try renderSyncPromptAlloc(allocator, config, cwd);
        defer allocator.free(prompt_text);
        if (config.instant) {
            try writeInstantPrompt(allocator, prompt_text);
        }
        try writePromptText(allocator, prompt_text, config.a11y, cwd);
        return;
    };
    defer allocator.free(response_payload);

    var parsed = try std.json.parseFromSlice(proto.Response, allocator, response_payload, .{ .ignore_unknown_fields = true });
    defer parsed.deinit();
    if (config.instant) {
        try writeInstantPrompt(allocator, parsed.value.prompt);
    }
    if (config.right) {
        if (parsed.value.right_prompt) |right_prompt| try std.fs.File.stdout().writeAll(right_prompt);
        return;
    }
    try writePromptText(allocator, parsed.value.prompt, config.a11y, cwd);
}

fn parsePrompt(args: []const []const u8) !PromptConfig {
    var config = PromptConfig{};
    var i: usize = 0;

    while (i < args.len) : (i += 1) {
        const arg = args[i];
        if (std.mem.eql(u8, arg, "--socket")) {
            config.socket_path = try cli_util.nextValue(args, &i);
        } else if (std.mem.eql(u8, arg, "--cwd")) {
            config.cwd = try cli_util.nextValue(args, &i);
        } else if (std.mem.eql(u8, arg, "--exit")) {
            config.exit = try std.fmt.parseInt(i32, try cli_util.nextValue(args, &i), 10);
        } else if (std.mem.eql(u8, arg, "--jobs")) {
            config.jobs = try std.fmt.parseInt(u32, try cli_util.nextValue(args, &i), 10);
        } else if (std.mem.eql(u8, arg, "--duration-ms")) {
            config.duration_ms = try std.fmt.parseInt(u64, try cli_util.nextValue(args, &i), 10);
        } else if (std.mem.eql(u8, arg, "--time")) {
            config.time = true;
        } else if (std.mem.eql(u8, arg, "--no-async")) {
            config.no_async = true;
        } else if (std.mem.eql(u8, arg, "--instant")) {
            config.instant = true;
        } else if (std.mem.eql(u8, arg, "--auto-spawn")) {
            config.auto_spawn = true;
        } else if (std.mem.eql(u8, arg, "--a11y")) {
            config.a11y = true;
        } else if (std.mem.eql(u8, arg, "--explain-a11y")) {
            config.explain_a11y = true;
        } else if (std.mem.eql(u8, arg, "--rtl")) {
            config.rtl = true;
        } else if (std.mem.eql(u8, arg, "--rtl-reverse")) {
            config.rtl_reverse = true;
        } else if (std.mem.eql(u8, arg, "--right")) {
            config.right = true;
        } else if (std.mem.eql(u8, arg, "--shell")) {
            config.shell = try cli_util.nextValue(args, &i);
        } else if (std.mem.eql(u8, arg, "--cols")) {
            config.cols = try std.fmt.parseInt(u16, try cli_util.nextValue(args, &i), 10);
        } else if (std.mem.eql(u8, arg, "--rows")) {
            config.rows = try std.fmt.parseInt(u16, try cli_util.nextValue(args, &i), 10);
        } else {
            return error.UnknownPromptArgument;
        }
    }

    return config;
}

fn promptA11yExplanationAlloc(allocator: std.mem.Allocator) ![]u8 {
    const path = try cli_util.defaultConfigPath(allocator);
    defer allocator.free(path);
    const source = try cli_util.readConfigOrDefault(allocator, path);
    defer allocator.free(source);
    var config_diagnostic: shisa_config.Diagnostic = .{};
    var parsed = shisa_config.parse(allocator, source, &config_diagnostic) catch |err| switch (err) {
        error.InvalidConfig => {
            const message = try std.fmt.allocPrint(allocator, "{s}:{d}:{d}: {s}\n", .{ path, config_diagnostic.line, config_diagnostic.column, config_diagnostic.message });
            defer allocator.free(message);
            try std.fs.File.stderr().writeAll(message);
            return err;
        },
        else => return err,
    };
    defer parsed.deinit(allocator);

    const theme_path = try cli_theme.pathAlloc(allocator, parsed.theme);
    defer allocator.free(theme_path);
    const theme_source = try std.fs.cwd().readFileAlloc(allocator, theme_path, max_config_bytes);
    defer allocator.free(theme_source);
    var theme_diagnostic: theme_loader.Diagnostic = .{};
    var theme = theme_loader.parse(allocator, theme_source, &theme_diagnostic) catch |err| switch (err) {
        error.InvalidTheme => {
            const message = try std.fmt.allocPrint(allocator, "{s}:{d}:{d}: {s}\n", .{ theme_path, theme_diagnostic.line, theme_diagnostic.column, theme_diagnostic.message });
            defer allocator.free(message);
            try std.fs.File.stderr().writeAll(message);
            return err;
        },
        else => return err,
    };
    defer theme.deinit(allocator);

    return a11yExplanationAlloc(allocator, parsed, theme);
}

fn a11yExplanationAlloc(allocator: std.mem.Allocator, parsed: shisa_config.Config, theme: theme_loader.Theme) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);
    try out.appendSlice(allocator, "a11y:\n");
    for (parsed.prompt_modules) |module_id| {
        const id = shisa_config.moduleIdName(module_id);
        const label = if (cli_theme.findSegment(theme, id)) |segment|
            if (segment.a11y.len > 0) segment.a11y else coreA11yLabel(module_id)
        else
            coreA11yLabel(module_id);
        try cli_util.appendFmt(allocator, &out, "  {s}: {s}\n", .{ id, label });
    }
    return out.toOwnedSlice(allocator);
}

fn coreA11yLabel(module_id: shisa_config.ModuleId) []const u8 {
    return switch (module_id) {
        .cwd => "current directory",
        .git_branch => "git branch",
        .language_versions => "language versions",
        .exit_status => "exit status",
        .jobs => "background jobs",
        .cmd_duration => "command duration",
        .user_host => "user and host",
        .cloud_ctx => "cloud context",
        .cdhint => "cd hint",
        .tmux_pane => "tmux pane",
        .risk_tier => "risk tier",
        .sso_expiry => "SSO expiry",
        .iac_workspace => "infrastructure workspace",
        .region_drift => "region drift",
        .cost_glance => "cost glance",
        .vpn_status => "VPN status",
        .ssh_target => "SSH target",
        .container_provenance => "container provenance",
        .time => "time",
    };
}

fn spawnPromptDaemon(allocator: std.mem.Allocator, socket_path: []const u8) !void {
    const daemon_path = try siblingExecutablePath(allocator, "shisad");
    defer allocator.free(daemon_path);
    var daemon = std.process.Child.init(&.{ daemon_path, "--foreground", "--socket", socket_path }, allocator);
    daemon.stdin_behavior = .Ignore;
    daemon.stdout_behavior = .Ignore;
    daemon.stderr_behavior = .Ignore;
    try daemon.spawn();
}

fn autoSpawnPromptRequestAlloc(allocator: std.mem.Allocator, socket_path: []const u8, payload: []const u8) !?[]u8 {
    spawnPromptDaemon(allocator, socket_path) catch return null;
    waitForPath(socket_path, prompt_auto_spawn_grace_ms) catch return null;
    return client.requestAlloc(allocator, socket_path, payload) catch null;
}

fn renderSyncPromptAlloc(allocator: std.mem.Allocator, config: PromptConfig, cwd: []const u8) ![]u8 {
    var git_cache = git_branch_module.Cache{};
    defer git_cache.deinit(allocator);
    var language_cache = language_versions_module.Cache{};
    defer language_cache.deinit(allocator);
    var cloud_cache = cloud_ctx_module.Cache{};
    defer cloud_cache.deinit(allocator);

    var module_options = try promptModuleOptions(allocator);
    defer module_options.deinit(allocator);
    const pipeline = try promptPipelineAlloc(allocator, module_options.modules);
    defer allocator.free(pipeline);
    const home = std.process.getEnvVarOwned(allocator, "HOME") catch null;
    defer if (home) |value| allocator.free(value);
    const kubeconfig = std.process.getEnvVarOwned(allocator, "KUBECONFIG") catch null;
    defer if (kubeconfig) |value| allocator.free(value);
    const ssh = std.process.getEnvVarOwned(allocator, "SSH_CONNECTION") catch null;
    defer if (ssh) |value| allocator.free(value);
    const aws_profile = std.process.getEnvVarOwned(allocator, "AWS_PROFILE") catch null;
    defer if (aws_profile) |value| allocator.free(value);
    const aws_region = std.process.getEnvVarOwned(allocator, "AWS_REGION") catch null;
    defer if (aws_region) |value| allocator.free(value);
    const aws_default_region = std.process.getEnvVarOwned(allocator, "AWS_DEFAULT_REGION") catch null;
    defer if (aws_default_region) |value| allocator.free(value);
    const cloudsdk_compute_region = std.process.getEnvVarOwned(allocator, "CLOUDSDK_COMPUTE_REGION") catch null;
    defer if (cloudsdk_compute_region) |value| allocator.free(value);
    const azure_location = std.process.getEnvVarOwned(allocator, "AZURE_LOCATION") catch null;
    defer if (azure_location) |value| allocator.free(value);
    const arm_location = std.process.getEnvVarOwned(allocator, "ARM_LOCATION") catch null;
    defer if (arm_location) |value| allocator.free(value);
    const azure_default_location = std.process.getEnvVarOwned(allocator, "AZURE_DEFAULT_LOCATION") catch null;
    defer if (azure_default_location) |value| allocator.free(value);
    const tmux_pane = std.process.getEnvVarOwned(allocator, "TMUX_PANE") catch null;
    defer if (tmux_pane) |value| allocator.free(value);
    const user = std.process.getEnvVarOwned(allocator, "USER") catch try allocator.dupe(u8, "unknown");
    defer allocator.free(user);
    var host_buffer: [std.posix.HOST_NAME_MAX]u8 = undefined;
    const host = std.posix.gethostname(&host_buffer) catch "unknown";

    var rendered = try dispatcher.renderPipeline(allocator, .{
        .git_branch = &git_cache,
        .language_versions = &language_cache,
        .cloud_ctx = &cloud_cache,
    }, .{
        .cwd = cwd,
        .home = home,
        .exit = config.exit,
        .jobs = config.jobs,
        .duration_ms = config.duration_ms,
        .time = config.time,
        .no_async = true,
        .timestamp = std.time.timestamp(),
        .ssh = ssh,
        .user = user,
        .host = host,
        .aws_profile = aws_profile,
        .aws_region = aws_region,
        .aws_default_region = aws_default_region,
        .cloudsdk_compute_region = cloudsdk_compute_region,
        .azure_location = azure_location,
        .arm_location = arm_location,
        .azure_default_location = azure_default_location,
        .kubeconfig = kubeconfig,
        .cloud_ctx = .{
            .aws = module_options.cloud_ctx.aws,
            .gcp = module_options.cloud_ctx.gcp,
            .azure = module_options.cloud_ctx.azure,
            .kubernetes = module_options.cloud_ctx.kubernetes,
        },
        .cdhint = module_options.cdhint,
        .tmux_pane = tmux_pane,
        .tmux_pane_options = module_options.tmux_pane,
        .rtl = promptRtl(config, module_options),
        .rtl_reverse = promptRtlReverse(config, module_options),
        .risk_tier = module_options.risk_tier,
        .sso_expiry = module_options.sso_expiry,
    }, pipeline);
    defer rendered.deinit(allocator);
    return allocator.dupe(u8, rendered.prompt);
}

fn promptPipelineAlloc(allocator: std.mem.Allocator, modules: []const shisa_config.ModuleId) ![]dispatcher.ModuleSpec {
    const pipeline = try allocator.alloc(dispatcher.ModuleSpec, modules.len);
    errdefer allocator.free(pipeline);
    for (modules, 0..) |module_id, index| {
        const id = dispatcherModuleId(module_id);
        pipeline[index] = .{
            .id = id,
            .execution_class = dispatcher.executionClass(id),
        };
    }
    return pipeline;
}

fn dispatcherModuleId(module_id: shisa_config.ModuleId) dispatcher.ModuleId {
    return switch (module_id) {
        .cwd => .cwd,
        .git_branch => .git_branch,
        .language_versions => .language_versions,
        .time => .time,
        .exit_status => .exit_status,
        .jobs => .jobs,
        .cmd_duration => .cmd_duration,
        .user_host => .user_host,
        .cloud_ctx => .cloud_ctx,
        .cdhint => .cdhint,
        .tmux_pane => .tmux_pane,
        .risk_tier => .risk_tier,
        .sso_expiry => .sso_expiry,
        .iac_workspace => .iac_workspace,
        .region_drift => .region_drift,
        .cost_glance => .cost_glance,
        .vpn_status => .vpn_status,
        .ssh_target => .ssh_target,
        .container_provenance => .container_provenance,
    };
}

fn writePromptText(allocator: std.mem.Allocator, prompt_text: []const u8, a11y: bool, cwd: []const u8) !void {
    const osc7 = try osc7SequenceAlloc(allocator, cwd);
    defer allocator.free(osc7);
    try std.fs.File.stdout().writeAll(osc7);
    if (!a11y) {
        try std.fs.File.stdout().writeAll(prompt_text);
        return;
    }
    const accessible = try a11yPromptAlloc(allocator, prompt_text);
    defer allocator.free(accessible);
    try std.fs.File.stdout().writeAll(accessible);
}

fn osc7SequenceAlloc(allocator: std.mem.Allocator, cwd: []const u8) ![]u8 {
    const host = std.process.getEnvVarOwned(allocator, "HOSTNAME") catch |err| switch (err) {
        error.EnvironmentVariableNotFound => try allocator.dupe(u8, "localhost"),
        else => return err,
    };
    defer allocator.free(host);
    return osc7SequenceForHostAlloc(allocator, host, cwd);
}

fn osc7SequenceForHostAlloc(allocator: std.mem.Allocator, host: []const u8, cwd: []const u8) ![]u8 {
    const encoded_host = try percentEncodeUriComponentAlloc(allocator, host, false);
    defer allocator.free(encoded_host);
    const encoded_path = try percentEncodeUriComponentAlloc(allocator, cwd, true);
    defer allocator.free(encoded_path);
    return std.fmt.allocPrint(allocator, "\x1b]7;file://{s}{s}\x07", .{ encoded_host, encoded_path });
}

fn percentEncodeUriComponentAlloc(allocator: std.mem.Allocator, value: []const u8, keep_slash: bool) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    for (value) |byte| {
        if (isUriUnreserved(byte) or (keep_slash and byte == '/')) {
            try out.append(allocator, byte);
        } else {
            try out.append(allocator, '%');
            try out.append(allocator, hexDigit(byte >> 4));
            try out.append(allocator, hexDigit(byte & 0x0f));
        }
    }
    return out.toOwnedSlice(allocator);
}

fn isUriUnreserved(byte: u8) bool {
    return (byte >= 'A' and byte <= 'Z') or
        (byte >= 'a' and byte <= 'z') or
        (byte >= '0' and byte <= '9') or
        byte == '-' or byte == '.' or byte == '_' or byte == '~';
}

fn hexDigit(value: u8) u8 {
    return "0123456789ABCDEF"[value & 0x0f];
}

fn instantPromptPath(allocator: std.mem.Allocator) ![]u8 {
    const config_path = try cli_util.defaultConfigPath(allocator);
    defer allocator.free(config_path);
    const dir = std.fs.path.dirname(config_path) orelse return error.MissingConfigDir;
    return std.fmt.allocPrint(allocator, "{s}/last-prompt", .{dir});
}

fn readInstantPrompt(allocator: std.mem.Allocator) !?[]u8 {
    const path = try instantPromptPath(allocator);
    defer allocator.free(path);
    return std.fs.cwd().readFileAlloc(allocator, path, 16 * 1024) catch |err| switch (err) {
        error.FileNotFound => null,
        else => return err,
    };
}

fn writeInstantPrompt(allocator: std.mem.Allocator, prompt_text: []const u8) !void {
    const path = try instantPromptPath(allocator);
    defer allocator.free(path);
    if (std.fs.path.dirname(path)) |parent| {
        try std.fs.cwd().makePath(parent);
    }
    var file = try std.fs.createFileAbsolute(path, .{ .truncate = true, .mode = 0o600 });
    defer file.close();
    try file.writeAll(prompt_text);
}

test "instant prompt read write roundtrip" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-instant-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    const path = try std.fmt.allocPrint(allocator, "{s}/last-prompt", .{dir_path});
    defer allocator.free(path);
    var file = try std.fs.createFileAbsolute(path, .{});
    try file.writeAll("cached> ");
    file.close();

    const cached = try std.fs.cwd().readFileAlloc(allocator, path, 16 * 1024);
    defer allocator.free(cached);
    try std.testing.expectEqualStrings("cached> ", cached);
}

test "osc7 sequence percent-encodes cwd" {
    const sequence = try osc7SequenceForHostAlloc(std.testing.allocator, "local host", "/tmp/a b/%");
    defer std.testing.allocator.free(sequence);
    try std.testing.expectEqualStrings("\x1b]7;file://local%20host/tmp/a%20b/%25\x07", sequence);
}

const PromptModuleOptions = struct {
    locale: []const u8 = "auto",
    rtl_reverse: bool = false,
    modules: []const shisa_config.ModuleId,
    right_modules: []const shisa_config.ModuleId,
    owns_modules: bool = false,
    owns_locale: bool = false,
    cwd: shisa_config.CwdOptions,
    cloud_ctx: shisa_config.CloudCtxOptions,
    cdhint: shisa_config.CdhintOptions,
    tmux_pane: shisa_config.TmuxPaneOptions,
    language_versions: shisa_config.LanguageVersionsOptions,
    risk_tier: shisa_config.RiskTierOptions,
    sso_expiry: shisa_config.SsoExpiryOptions,

    fn deinit(self: *PromptModuleOptions, allocator: std.mem.Allocator) void {
        if (self.owns_modules) {
            allocator.free(self.modules);
            allocator.free(self.right_modules);
        }
        if (self.owns_locale) allocator.free(self.locale);
        self.* = undefined;
    }
};

const default_prompt_modules = [_]shisa_config.ModuleId{
    .cwd,
    .git_branch,
    .language_versions,
    .exit_status,
    .jobs,
    .cmd_duration,
    .user_host,
    .risk_tier,
    .sso_expiry,
    .iac_workspace,
    .region_drift,
    .cost_glance,
    .vpn_status,
    .ssh_target,
    .container_provenance,
};

fn buildPromptPayload(allocator: std.mem.Allocator, config: PromptConfig, cwd: []const u8) ![]u8 {
    var module_options = try promptModuleOptions(allocator);
    defer module_options.deinit(allocator);
    return buildPromptPayloadWithModuleOptions(allocator, config, cwd, module_options);
}

fn buildPromptPayloadWithModuleOptions(allocator: std.mem.Allocator, config: PromptConfig, cwd: []const u8, module_options: PromptModuleOptions) ![]u8 {
    const escaped_cwd = try daemon_json.escapeAlloc(allocator, cwd);
    defer allocator.free(escaped_cwd);
    const escaped_shell = try daemon_json.escapeAlloc(allocator, config.shell);
    defer allocator.free(escaped_shell);
    const modules_json = try promptModulesJsonAlloc(allocator, module_options.modules);
    defer allocator.free(modules_json);
    const right_modules_json = try promptModulesJsonAlloc(allocator, module_options.right_modules);
    defer allocator.free(right_modules_json);
    const tmux_pane = std.process.getEnvVarOwned(allocator, "TMUX_PANE") catch null;
    defer if (tmux_pane) |value| allocator.free(value);
    const escaped_tmux_pane = try daemon_json.escapeAlloc(allocator, tmux_pane orelse "");
    defer allocator.free(escaped_tmux_pane);
    const request_id = try std.fmt.allocPrint(allocator, "cli-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(request_id);
    const rtl = promptRtl(config, module_options);
    const rtl_reverse = promptRtlReverse(config, module_options);
    const env_json = if (module_options.language_versions.path_hash_invalidate)
        try pathEnvJsonAlloc(allocator)
    else
        try allocator.dupe(u8, "");
    defer allocator.free(env_json);

    const head = try std.fmt.allocPrint(
        allocator,
        "{{\"v\":1,\"op\":\"render\",\"cwd\":\"{s}\",\"exit\":{d},\"jobs\":{d},\"duration_ms\":{d},\"time\":{},\"no_async\":{},\"shell\":\"{s}\",\"cols\":{d},\"rows\":{d},\"tty\":\"/dev/tty\",\"color_caps\":\"{s}\",\"glyph_caps\":\"{s}\",\"user_id\":{d},\"session\":\"cli\",\"request_id\":\"{s}\"{s},",
        .{ escaped_cwd, config.exit, config.jobs, config.duration_ms, config.time, config.no_async, escaped_shell, config.cols, config.rows, promptColorCaps(config), promptGlyphCaps(config), std.posix.getuid(), request_id, env_json },
    );
    defer allocator.free(head);
    const tail = try std.fmt.allocPrint(
        allocator,
        "\"modules\":[{s}],\"right_modules\":[{s}],\"tmux_pane\":\"{s}\",\"rtl\":{},\"rtl_reverse\":{},\"cwd_options\":{{\"truncate_to\":{d},\"home_tilde\":{},\"max_width\":{d}}},\"cloud_ctx\":{{\"aws\":{},\"gcp\":{},\"azure\":{},\"kubernetes\":{}}},\"cdhint\":{{\"enabled\":{}}},\"tmux_pane_options\":{{\"enabled\":{}}},\"risk_tier\":{{\"unknown_bg\":\"{s}\",\"dev_bg\":\"{s}\",\"staging_bg\":\"{s}\",\"prod_bg\":\"{s}\"}},\"sso_expiry\":{{\"warning_minutes\":{d}}}}}",
        .{ modules_json, right_modules_json, escaped_tmux_pane, rtl, rtl_reverse, module_options.cwd.truncate_to, module_options.cwd.home_tilde, module_options.cwd.max_width, module_options.cloud_ctx.aws, module_options.cloud_ctx.gcp, module_options.cloud_ctx.azure, module_options.cloud_ctx.kubernetes, module_options.cdhint.enabled, module_options.tmux_pane.enabled, risk_tier_module.colorSlotName(module_options.risk_tier.unknown_bg), risk_tier_module.colorSlotName(module_options.risk_tier.dev_bg), risk_tier_module.colorSlotName(module_options.risk_tier.staging_bg), risk_tier_module.colorSlotName(module_options.risk_tier.prod_bg), module_options.sso_expiry.warning_minutes },
    );
    defer allocator.free(tail);
    return std.fmt.allocPrint(
        allocator,
        "{s}{s}",
        .{ head, tail },
    );
}

fn pathEnvJsonAlloc(allocator: std.mem.Allocator) ![]u8 {
    const path = std.process.getEnvVarOwned(allocator, "PATH") catch |err| switch (err) {
        error.EnvironmentVariableNotFound => return allocator.dupe(u8, ""),
        else => return err,
    };
    defer allocator.free(path);
    const hash = try sha256HexAlloc(allocator, path);
    defer allocator.free(hash);
    const escaped_path = try daemon_json.escapeAlloc(allocator, path);
    defer allocator.free(escaped_path);
    return std.fmt.allocPrint(allocator, ",\"env_hash\":\"{s}\",\"path_env\":\"{s}\"", .{ hash, escaped_path });
}

fn sha256HexAlloc(allocator: std.mem.Allocator, value: []const u8) ![]u8 {
    var digest: [std.crypto.hash.sha2.Sha256.digest_length]u8 = undefined;
    std.crypto.hash.sha2.Sha256.hash(value, &digest, .{});
    const hex = std.fmt.bytesToHex(digest, .lower);
    return allocator.dupe(u8, hex[0..]);
}

fn promptRtl(config: PromptConfig, module_options: PromptModuleOptions) bool {
    if (!std.mem.eql(u8, module_options.locale, "auto")) return shisa_config.localeIsRtl(module_options.locale);
    return config.rtl;
}

fn promptRtlReverse(config: PromptConfig, module_options: PromptModuleOptions) bool {
    return config.rtl_reverse or module_options.rtl_reverse;
}

fn promptModulesJsonAlloc(allocator: std.mem.Allocator, modules: []const shisa_config.ModuleId) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);
    for (modules, 0..) |module_id, index| {
        if (index != 0) try out.appendSlice(allocator, ",");
        try cli_util.appendFmt(allocator, &out, "\"{s}\"", .{shisa_config.moduleIdName(module_id)});
    }
    return out.toOwnedSlice(allocator);
}

fn promptColorCaps(config: PromptConfig) []const u8 {
    return if (config.a11y) "none" else "truecolor";
}

fn promptGlyphCaps(config: PromptConfig) []const u8 {
    return if (config.a11y) "ascii" else "unicode";
}

fn defaultPromptModuleOptions() PromptModuleOptions {
    return .{
        .locale = "auto",
        .rtl_reverse = false,
        .modules = default_prompt_modules[0..],
        .right_modules = &.{},
        .cwd = .{},
        .cloud_ctx = .{},
        .cdhint = .{},
        .tmux_pane = .{},
        .language_versions = .{},
        .risk_tier = .{},
        .sso_expiry = .{},
    };
}

fn promptModuleOptions(allocator: std.mem.Allocator) !PromptModuleOptions {
    const path = try cli_util.defaultConfigPath(allocator);
    defer allocator.free(path);
    const source = try cli_util.readConfigOrDefault(allocator, path);
    defer allocator.free(source);
    var diagnostic: shisa_config.Diagnostic = .{};
    var parsed = shisa_config.parse(allocator, source, &diagnostic) catch |err| switch (err) {
        error.InvalidConfig => {
            const message = try std.fmt.allocPrint(allocator, "{s}:{d}:{d}: {s}\n", .{ path, diagnostic.line, diagnostic.column, diagnostic.message });
            defer allocator.free(message);
            try std.fs.File.stderr().writeAll(message);
            return err;
        },
        else => return err,
    };
    defer parsed.deinit(allocator);
    const modules = try allocator.dupe(shisa_config.ModuleId, parsed.prompt_modules);
    errdefer allocator.free(modules);
    const right_modules = try allocator.dupe(shisa_config.ModuleId, parsed.right_prompt_modules);
    errdefer allocator.free(right_modules);
    const locale = try allocator.dupe(u8, parsed.locale);
    errdefer allocator.free(locale);
    return .{
        .locale = locale,
        .rtl_reverse = parsed.prompt.rtl_reverse,
        .modules = modules,
        .right_modules = right_modules,
        .owns_modules = true,
        .owns_locale = true,
        .cwd = parsed.modules.cwd,
        .cloud_ctx = parsed.modules.cloud_ctx,
        .cdhint = parsed.modules.cdhint,
        .tmux_pane = parsed.modules.tmux_pane,
        .language_versions = parsed.modules.language_versions,
        .risk_tier = parsed.modules.risk_tier,
        .sso_expiry = parsed.modules.sso_expiry,
    };
}

fn a11yPromptAlloc(allocator: std.mem.Allocator, prompt_text: []const u8) ![]u8 {
    const no_ansi = try stripAnsiAlloc(allocator, prompt_text);
    defer allocator.free(no_ansi);
    return normalizePromptGlyphsAlloc(allocator, no_ansi);
}

fn stripAnsiAlloc(allocator: std.mem.Allocator, value: []const u8) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);

    var index: usize = 0;
    while (index < value.len) {
        if (value[index] == 0x1b and index + 1 < value.len and value[index + 1] == '[') {
            index += 2;
            while (index < value.len) : (index += 1) {
                if (value[index] >= 0x40 and value[index] <= 0x7e) {
                    index += 1;
                    break;
                }
            }
            continue;
        }
        try out.append(allocator, value[index]);
        index += 1;
    }

    return out.toOwnedSlice(allocator);
}

fn normalizePromptGlyphsAlloc(allocator: std.mem.Allocator, value: []const u8) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);

    var index: usize = 0;
    while (index < value.len) {
        if (try replaceGlyph(&out, allocator, value[index..], "\xe2\x86\x92", "->")) {
            index += 3;
        } else if (try replaceGlyph(&out, allocator, value[index..], "\xe2\x86\x91", "up")) {
            index += 3;
        } else if (try replaceGlyph(&out, allocator, value[index..], "\xe2\x86\x93", "down")) {
            index += 3;
        } else if (try replaceGlyph(&out, allocator, value[index..], "\xe2\x9c\x93", "ok")) {
            index += 3;
        } else if (try replaceGlyph(&out, allocator, value[index..], "\xe2\x9c\x97", "x")) {
            index += 3;
        } else if (try replaceGlyph(&out, allocator, value[index..], "\xe2\x80\xa6", "...")) {
            index += 3;
        } else {
            try out.append(allocator, value[index]);
            index += 1;
        }
    }

    return out.toOwnedSlice(allocator);
}

fn replaceGlyph(out: *std.ArrayList(u8), allocator: std.mem.Allocator, tail: []const u8, glyph: []const u8, replacement: []const u8) !bool {
    if (!std.mem.startsWith(u8, tail, glyph)) return false;
    try out.appendSlice(allocator, replacement);
    return true;
}

test "prompt args parse a11y" {
    const config = try parsePrompt(&.{ "--a11y", "--no-async" });
    try std.testing.expect(config.a11y);
    try std.testing.expect(config.no_async);
}

test "prompt args parse explain a11y" {
    const config = try parsePrompt(&.{"--explain-a11y"});
    try std.testing.expect(config.explain_a11y);
}

test "prompt args parse rtl flags" {
    const config = try parsePrompt(&.{ "--rtl", "--rtl-reverse" });
    try std.testing.expect(config.rtl);
    try std.testing.expect(config.rtl_reverse);
}

test "prompt args parse right flag" {
    const config = try parsePrompt(&.{"--right"});
    try std.testing.expect(config.right);
}

test "prompt payload carries rtl flags" {
    const payload = try buildPromptPayload(std.testing.allocator, .{ .rtl = true, .rtl_reverse = true }, "/tmp");
    defer std.testing.allocator.free(payload);
    try std.testing.expect(std.mem.indexOf(u8, payload, "\"rtl\":true") != null);
    try std.testing.expect(std.mem.indexOf(u8, payload, "\"rtl_reverse\":true") != null);
}

test "prompt payload locale override controls rtl" {
    var rtl_options = defaultPromptModuleOptions();
    rtl_options.locale = "ar-EG";
    const rtl_payload = try buildPromptPayloadWithModuleOptions(std.testing.allocator, .{}, "/tmp", rtl_options);
    defer std.testing.allocator.free(rtl_payload);
    try std.testing.expect(std.mem.indexOf(u8, rtl_payload, "\"rtl\":true") != null);

    var ltr_options = defaultPromptModuleOptions();
    ltr_options.locale = "en-US";
    const ltr_payload = try buildPromptPayloadWithModuleOptions(std.testing.allocator, .{ .rtl = true }, "/tmp", ltr_options);
    defer std.testing.allocator.free(ltr_payload);
    try std.testing.expect(std.mem.indexOf(u8, ltr_payload, "\"rtl\":false") != null);
}

test "prompt payload carries right modules" {
    var options = defaultPromptModuleOptions();
    options.right_modules = &.{.time};
    const payload = try buildPromptPayloadWithModuleOptions(std.testing.allocator, .{}, "/tmp", options);
    defer std.testing.allocator.free(payload);
    try std.testing.expect(std.mem.indexOf(u8, payload, "\"right_modules\":[\"time\"]") != null);
}

test "prompt payload carries env hash and path only when enabled" {
    const digest = try sha256HexAlloc(std.testing.allocator, "");
    defer std.testing.allocator.free(digest);
    try std.testing.expectEqualStrings("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", digest);

    const disabled = defaultPromptModuleOptions();
    const disabled_payload = try buildPromptPayloadWithModuleOptions(std.testing.allocator, .{}, "/tmp", disabled);
    defer std.testing.allocator.free(disabled_payload);
    try std.testing.expect(std.mem.indexOf(u8, disabled_payload, "\"env_hash\"") == null);
    try std.testing.expect(std.mem.indexOf(u8, disabled_payload, "\"path_env\"") == null);

    const path = std.process.getEnvVarOwned(std.testing.allocator, "PATH") catch return error.SkipZigTest;
    std.testing.allocator.free(path);
    var enabled = defaultPromptModuleOptions();
    enabled.language_versions.path_hash_invalidate = true;
    const enabled_payload = try buildPromptPayloadWithModuleOptions(std.testing.allocator, .{}, "/tmp", enabled);
    defer std.testing.allocator.free(enabled_payload);
    const marker = "\"env_hash\":\"";
    const start = std.mem.indexOf(u8, enabled_payload, marker) orelse return error.MissingEnvHash;
    const hash_start = start + marker.len;
    try std.testing.expect(enabled_payload.len >= hash_start + 65);
    for (enabled_payload[hash_start .. hash_start + 64]) |byte| {
        try std.testing.expect(std.ascii.isDigit(byte) or (byte >= 'a' and byte <= 'f'));
    }
    try std.testing.expectEqual(@as(u8, '"'), enabled_payload[hash_start + 64]);
    try std.testing.expect(std.mem.indexOf(u8, enabled_payload, "\"path_env\":\"") != null);
}

test "prompt args parse auto spawn" {
    const config = try parsePrompt(&.{"--auto-spawn"});
    try std.testing.expect(config.auto_spawn);
}

test "auto spawn uses 100ms grace" {
    try std.testing.expectEqual(@as(i64, 100), prompt_auto_spawn_grace_ms);
}

test "sync prompt fallback renders cwd prompt" {
    const dir_path = try std.fmt.allocPrint(std.testing.allocator, "/tmp/shisa-sync-fallback-{x}", .{std.crypto.random.int(u64)});
    defer std.testing.allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    const output = try renderSyncPromptAlloc(std.testing.allocator, .{}, dir_path);
    defer std.testing.allocator.free(output);
    try std.testing.expect(std.mem.indexOf(u8, output, dir_path) != null);
    try std.testing.expect(std.mem.endsWith(u8, output, "> "));
}

test "prompt caps switch for a11y" {
    try std.testing.expectEqualStrings("none", promptColorCaps(.{ .a11y = true }));
    try std.testing.expectEqualStrings("ascii", promptGlyphCaps(.{ .a11y = true }));
    try std.testing.expectEqualStrings("truecolor", promptColorCaps(.{}));
    try std.testing.expectEqualStrings("unicode", promptGlyphCaps(.{}));
}

test "a11y prompt strips ansi and normalizes glyphs" {
    const output = try a11yPromptAlloc(std.testing.allocator, "\x1b[31mexit:2\x1b[0m \xe2\x86\x92 prod \xe2\x9c\x93\n");
    defer std.testing.allocator.free(output);
    try std.testing.expectEqualStrings("exit:2 -> prod ok\n", output);
}

test "a11y explanation dumps configured module labels" {
    var config_diagnostic: shisa_config.Diagnostic = .{};
    var parsed = try shisa_config.parse(std.testing.allocator, shisa_config.default_config_text, &config_diagnostic);
    defer parsed.deinit(std.testing.allocator);
    const theme_source = try std.fs.cwd().readFileAlloc(std.testing.allocator, "themes/plain.toml", max_config_bytes);
    defer std.testing.allocator.free(theme_source);
    var theme_diagnostic: theme_loader.Diagnostic = .{};
    var theme = try theme_loader.parse(std.testing.allocator, theme_source, &theme_diagnostic);
    defer theme.deinit(std.testing.allocator);

    const output = try a11yExplanationAlloc(std.testing.allocator, parsed, theme);
    defer std.testing.allocator.free(output);
    try std.testing.expect(std.mem.indexOf(u8, output, "  cwd: current directory\n") != null);
    try std.testing.expect(std.mem.indexOf(u8, output, "  risk_tier: risk tier\n") != null);
}

const help_text =
    \\usage: shisa <command> [options]
    \\
    \\commands:
    \\  bench         benchmark prompt render via hyperfine
    \\  cache         dump or clear cache state
    \\  cloud         cloud helpers: audit, doctor, explain, preexec
    \\  config        set persistent config values
    \\  doctor        diagnose socket, config, plugins, lua, fsnotify
    \\  explain       print resolved module pipeline
    \\  font          render glyph fallback probes
    \\  import-starship <path>
    \\                translate starship.toml to shisa.toml
    \\  import-p10k <path>
    \\                translate .p10k.zsh to shisa.toml
    \\  import-oh-my-posh <path>
    \\                translate Oh My Posh JSON/YAML to shisa.toml
    \\  import-tide <path>
    \\                translate Tide fish settings to shisa.toml
    \\  import-pure
    \\                print the minimal Pure-compatible preset
    \\  init          write default shisa.toml; --a11y and shell notification prefs supported
    \\  pin           mark a path as never-evicted
    \\  plugin        new, lint, doctor, verify, search, pack, install, list, enable, disable, or trust plugins
    \\  prompt        render prompt through shisad; --right prints configured right prompt
    \\  render        alias for prompt; --explain-a11y dumps segment labels
    \\  report        write a redacted support bundle .tar.gz
    \\  supervisor    run shisad under a crash-restart supervisor
    \\  theme         validate theme files
    \\  vouch         verify VOUCHES governance file
    \\
    \\options:
    \\  -h, --help    print help
    \\      --version print version
    \\
;

const vouch_help_text =
    \\usage: shisa vouch verify [path]
    \\
    \\commands:
    \\  verify [path] validate VOUCHES format; defaults to ./VOUCHES
    \\
;

const font_help_text =
    \\usage: shisa font check
    \\
    \\commands:
    \\  check         render Nerd Font, Unicode, and ASCII glyph probes
    \\
;
