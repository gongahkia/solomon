const std = @import("std");
const builtin = @import("builtin");
const cli_util = @import("util.zig");

const default_repo = "gongahkia/shisa";
const issuer = "https://token.actions.githubusercontent.com";
const max_release_json = 1024 * 1024;
const max_cmd_output = 1024 * 1024;

pub fn updateCmd(allocator: std.mem.Allocator, args: []const []const u8) !void {
    const config = try parseUpdateArgs(args);
    if (config.help) {
        try std.fs.File.stdout().writeAll(help_text);
        return;
    }

    const install_dir = if (config.install_dir) |path| try allocator.dupe(u8, path) else try defaultInstallDirAlloc(allocator);
    defer allocator.free(install_dir);
    const current_path = try std.fs.path.join(allocator, &.{ install_dir, "shisa" });
    defer allocator.free(current_path);
    const previous_path = try std.fs.path.join(allocator, &.{ install_dir, "shisa.previous" });
    defer allocator.free(previous_path);

    if (config.rollback) {
        try rollbackUpdate(current_path, previous_path);
        try std.fs.File.stdout().writeAll("shisa update: rolled back to previous binary\n");
        return;
    }

    const tag = if (config.tag) |value| try allocator.dupe(u8, value) else try latestReleaseTagAlloc(allocator, config.repo);
    defer allocator.free(tag);
    const os_name = releaseOsName();
    const arch_name = releaseArchName();
    if (std.mem.eql(u8, os_name, "unsupported") or std.mem.eql(u8, arch_name, "unsupported")) return error.UnsupportedReleasePlatform;
    const package_name = try std.fmt.allocPrint(allocator, "shisa-{s}-{s}-{s}", .{ tag, os_name, arch_name });
    defer allocator.free(package_name);
    const archive_name = try std.fmt.allocPrint(allocator, "{s}.tar.gz", .{package_name});
    defer allocator.free(archive_name);
    const base_url = try std.fmt.allocPrint(allocator, "https://github.com/{s}/releases/download/{s}", .{ config.repo, tag });
    defer allocator.free(base_url);

    if (config.dry_run) {
        try printUpdatePlan(allocator, config, tag, package_name, install_dir);
        return;
    }

    var work = try makeWorkDir(allocator);
    defer work.deinit(allocator);

    const archive_path = try std.fs.path.join(allocator, &.{ work.path, archive_name });
    defer allocator.free(archive_path);
    const checksum_path = try std.fmt.allocPrint(allocator, "{s}.sha256", .{archive_path});
    defer allocator.free(checksum_path);
    const checksum_name = try std.fmt.allocPrint(allocator, "{s}.sha256", .{archive_name});
    defer allocator.free(checksum_name);
    try downloadFile(allocator, base_url, archive_name, archive_path);
    try downloadFile(allocator, base_url, checksum_name, checksum_path);

    if (config.verify) {
        const sig_path = try std.fmt.allocPrint(allocator, "{s}.sig", .{archive_path});
        defer allocator.free(sig_path);
        const pem_path = try std.fmt.allocPrint(allocator, "{s}.pem", .{archive_path});
        defer allocator.free(pem_path);
        const crt_path = try std.fmt.allocPrint(allocator, "{s}.crt", .{archive_path});
        defer allocator.free(crt_path);
        const sig_name = try std.fmt.allocPrint(allocator, "{s}.sig", .{archive_name});
        defer allocator.free(sig_name);
        const pem_name = try std.fmt.allocPrint(allocator, "{s}.pem", .{archive_name});
        defer allocator.free(pem_name);
        const crt_name = try std.fmt.allocPrint(allocator, "{s}.crt", .{archive_name});
        defer allocator.free(crt_name);
        try downloadFile(allocator, base_url, sig_name, sig_path);
        try downloadFile(allocator, base_url, pem_name, pem_path);
        try downloadFile(allocator, base_url, crt_name, crt_path);
        try verifyArchiveSignature(allocator, config.repo, tag, archive_path, sig_path, pem_path);
    }

    try verifyChecksum(allocator, archive_path, checksum_path);
    try runChecked(allocator, &.{ "tar", "-xzf", archive_path, "-C", work.path });
    const extracted = try std.fs.path.join(allocator, &.{ work.path, package_name, "shisa" });
    defer allocator.free(extracted);
    const new_path = try std.fs.path.join(allocator, &.{ install_dir, "shisa.new" });
    defer allocator.free(new_path);
    std.fs.deleteFileAbsolute(new_path) catch {};
    try std.fs.copyFileAbsolute(extracted, new_path, .{ .override_mode = 0o755 });
    try validateInstalledVersion(allocator, new_path, tag);
    applyUpdate(current_path, new_path, previous_path) catch |err| {
        rollbackUpdate(current_path, previous_path) catch {};
        return err;
    };
    validateInstalledVersion(allocator, current_path, tag) catch |err| {
        rollbackUpdate(current_path, previous_path) catch {};
        return err;
    };
    try std.fs.File.stdout().writeAll("shisa update: installed ");
    try std.fs.File.stdout().writeAll(tag);
    try std.fs.File.stdout().writeAll("\n");
}

const UpdateConfig = struct {
    repo: []const u8 = default_repo,
    tag: ?[]const u8 = null,
    install_dir: ?[]const u8 = null,
    verify: bool = true,
    dry_run: bool = false,
    rollback: bool = false,
    help: bool = false,
};

fn parseUpdateArgs(args: []const []const u8) !UpdateConfig {
    var config = UpdateConfig{};
    var i: usize = 0;
    while (i < args.len) : (i += 1) {
        const arg = args[i];
        if (std.mem.eql(u8, arg, "--help") or std.mem.eql(u8, arg, "-h")) {
            config.help = true;
        } else if (std.mem.eql(u8, arg, "--verify")) {
            config.verify = true;
        } else if (std.mem.eql(u8, arg, "--no-verify")) {
            config.verify = false;
        } else if (std.mem.eql(u8, arg, "--dry-run")) {
            config.dry_run = true;
        } else if (std.mem.eql(u8, arg, "--rollback")) {
            config.rollback = true;
        } else if (std.mem.eql(u8, arg, "--repo")) {
            config.repo = try cli_util.nextValue(args, &i);
        } else if (std.mem.eql(u8, arg, "--tag")) {
            config.tag = try cli_util.nextValue(args, &i);
        } else if (std.mem.eql(u8, arg, "--install-dir")) {
            config.install_dir = try cli_util.nextValue(args, &i);
        } else {
            return error.UnknownUpdateArgument;
        }
    }
    if (config.help and args.len != 1) return error.UnknownUpdateArgument;
    if (config.rollback and (config.dry_run or config.tag != null)) return error.UnknownUpdateArgument;
    return config;
}

fn latestReleaseTagAlloc(allocator: std.mem.Allocator, repo: []const u8) ![]u8 {
    const url = try std.fmt.allocPrint(allocator, "https://api.github.com/repos/{s}/releases/latest", .{repo});
    defer allocator.free(url);
    const result = try std.process.Child.run(.{
        .allocator = allocator,
        .argv = &.{ "curl", "-fsSL", url },
        .max_output_bytes = max_release_json,
        .expand_arg0 = .expand,
    });
    defer allocator.free(result.stderr);
    if (!cli_util.exitedZero(result.term)) {
        allocator.free(result.stdout);
        return error.ReleaseMetadataFetchFailed;
    }
    defer allocator.free(result.stdout);
    const Release = struct { tag_name: []const u8 };
    var parsed = try std.json.parseFromSlice(Release, allocator, result.stdout, .{ .ignore_unknown_fields = true });
    defer parsed.deinit();
    return allocator.dupe(u8, parsed.value.tag_name);
}

const WorkDir = struct {
    path: []u8,

    fn deinit(self: *WorkDir, allocator: std.mem.Allocator) void {
        std.fs.cwd().deleteTree(self.path) catch {};
        allocator.free(self.path);
        self.* = undefined;
    }
};

fn makeWorkDir(allocator: std.mem.Allocator) !WorkDir {
    const path = try std.fmt.allocPrint(allocator, "/tmp/shisa-update-{x}", .{std.crypto.random.int(u64)});
    errdefer allocator.free(path);
    try std.fs.cwd().makePath(path);
    return .{ .path = path };
}

fn downloadFile(allocator: std.mem.Allocator, base_url: []const u8, name: []const u8, dest: []const u8) !void {
    const url = try std.fmt.allocPrint(allocator, "{s}/{s}", .{ base_url, name });
    defer allocator.free(url);
    try runChecked(allocator, &.{ "curl", "-fsSL", url, "-o", dest });
}

fn verifyArchiveSignature(allocator: std.mem.Allocator, repo: []const u8, tag: []const u8, archive: []const u8, sig: []const u8, pem: []const u8) !void {
    const identity = try std.fmt.allocPrint(allocator, "https://github.com/{s}/.github/workflows/release.yml@refs/tags/{s}", .{ repo, tag });
    defer allocator.free(identity);
    try runChecked(allocator, &.{
        "cosign",
        "verify-blob",
        archive,
        "--certificate",
        pem,
        "--signature",
        sig,
        "--certificate-identity",
        identity,
        "--certificate-oidc-issuer",
        issuer,
    });
}

fn verifyChecksum(allocator: std.mem.Allocator, archive_path: []const u8, checksum_path: []const u8) !void {
    const expected_text = try readFileAbsoluteAlloc(allocator, checksum_path, 4096);
    defer allocator.free(expected_text);
    const expected = std.mem.sliceTo(std.mem.trimLeft(u8, expected_text, " \t\r\n"), ' ');
    const actual = try fileSha256HexAlloc(allocator, archive_path);
    defer allocator.free(actual);
    if (!std.ascii.eqlIgnoreCase(expected, actual)) return error.UpdateChecksumMismatch;
}

fn readFileAbsoluteAlloc(allocator: std.mem.Allocator, path: []const u8, max_bytes: usize) ![]u8 {
    var file = try std.fs.openFileAbsolute(path, .{});
    defer file.close();
    return file.readToEndAlloc(allocator, max_bytes);
}

fn fileSha256HexAlloc(allocator: std.mem.Allocator, path: []const u8) ![]u8 {
    var file = try std.fs.openFileAbsolute(path, .{});
    defer file.close();
    var hash = std.crypto.hash.sha2.Sha256.init(.{});
    var buffer: [8192]u8 = undefined;
    while (true) {
        const n = try file.read(&buffer);
        if (n == 0) break;
        hash.update(buffer[0..n]);
    }
    var digest: [std.crypto.hash.sha2.Sha256.digest_length]u8 = undefined;
    hash.final(&digest);
    const hex = std.fmt.bytesToHex(digest, .lower);
    return allocator.dupe(u8, hex[0..]);
}

fn applyUpdate(current_path: []const u8, new_path: []const u8, previous_path: []const u8) !void {
    std.fs.deleteFileAbsolute(previous_path) catch {};
    if (builtin.os.tag == .linux) {
        linuxRenameExchange(current_path, new_path) catch {
            try twoPhaseSwap(current_path, new_path, previous_path);
            return;
        };
        try std.fs.renameAbsolute(new_path, previous_path);
        return;
    }
    try twoPhaseSwap(current_path, new_path, previous_path);
}

fn twoPhaseSwap(current_path: []const u8, new_path: []const u8, previous_path: []const u8) !void {
    std.fs.renameAbsolute(current_path, previous_path) catch |err| switch (err) {
        error.FileNotFound => {},
        else => return err,
    };
    try std.fs.renameAbsolute(new_path, current_path);
}

fn rollbackUpdate(current_path: []const u8, previous_path: []const u8) !void {
    const failed_path = try std.fmt.allocPrint(std.heap.page_allocator, "{s}.failed", .{current_path});
    defer std.heap.page_allocator.free(failed_path);
    std.fs.deleteFileAbsolute(failed_path) catch {};
    std.fs.renameAbsolute(current_path, failed_path) catch |err| switch (err) {
        error.FileNotFound => {},
        else => return err,
    };
    try std.fs.renameAbsolute(previous_path, current_path);
}

fn linuxRenameExchange(current_path: []const u8, new_path: []const u8) !void {
    if (builtin.os.tag != .linux) return error.UnsupportedRenameExchange;
    const current_z = try std.heap.page_allocator.dupeZ(u8, current_path);
    defer std.heap.page_allocator.free(current_z);
    const new_z = try std.heap.page_allocator.dupeZ(u8, new_path);
    defer std.heap.page_allocator.free(new_z);
    const rename_exchange: u32 = 2;
    const rc = std.os.linux.renameat2(std.os.linux.AT.FDCWD, current_z.ptr, std.os.linux.AT.FDCWD, new_z.ptr, rename_exchange);
    return switch (std.posix.errno(rc)) {
        .SUCCESS => {},
        else => error.RenameExchangeFailed,
    };
}

fn validateInstalledVersion(allocator: std.mem.Allocator, current_path: []const u8, tag: []const u8) !void {
    const result = try std.process.Child.run(.{
        .allocator = allocator,
        .argv = &.{ current_path, "--version" },
        .max_output_bytes = 4096,
    });
    defer allocator.free(result.stdout);
    defer allocator.free(result.stderr);
    if (!cli_util.exitedZero(result.term)) return error.UpdateValidationFailed;
    if (outputMatchesTag(result.stdout, tag)) return;
    return error.UpdateVersionMismatch;
}

fn outputMatchesTag(output: []const u8, tag: []const u8) bool {
    if (std.mem.indexOf(u8, output, tag)) |_| return true;
    if (tag.len > 1 and tag[0] == 'v') {
        if (std.mem.indexOf(u8, output, tag[1..])) |_| return true;
    }
    return false;
}

fn runChecked(allocator: std.mem.Allocator, argv: []const []const u8) !void {
    const result = try std.process.Child.run(.{
        .allocator = allocator,
        .argv = argv,
        .max_output_bytes = max_cmd_output,
        .expand_arg0 = .expand,
    });
    defer allocator.free(result.stdout);
    defer allocator.free(result.stderr);
    if (!cli_util.exitedZero(result.term)) return error.UpdateCommandFailed;
}

fn defaultInstallDirAlloc(allocator: std.mem.Allocator) ![]u8 {
    const self_path = try std.fs.selfExePathAlloc(allocator);
    defer allocator.free(self_path);
    const dir = std.fs.path.dirname(self_path) orelse return error.MissingInstallDir;
    return allocator.dupe(u8, dir);
}

fn releaseOsName() []const u8 {
    return switch (builtin.os.tag) {
        .macos => "macos",
        .linux => "linux",
        else => "unsupported",
    };
}

fn releaseArchName() []const u8 {
    return switch (builtin.cpu.arch) {
        .x86_64 => "x64",
        .aarch64 => "arm64",
        else => "unsupported",
    };
}

fn printUpdatePlan(allocator: std.mem.Allocator, config: UpdateConfig, tag: []const u8, package_name: []const u8, install_dir: []const u8) !void {
    const text = try std.fmt.allocPrint(
        allocator,
        "repo: {s}\ntag: {s}\npackage: {s}.tar.gz\ninstall_dir: {s}\nverify: {}\n",
        .{ config.repo, tag, package_name, install_dir, config.verify },
    );
    defer allocator.free(text);
    try std.fs.File.stdout().writeAll(text);
}

test "parses update dry-run args" {
    const config = try parseUpdateArgs(&.{ "--dry-run", "--tag", "v0.1.0", "--no-verify" });
    try std.testing.expect(config.dry_run);
    try std.testing.expect(!config.verify);
    try std.testing.expectEqualStrings("v0.1.0", config.tag.?);
}

test "release asset names match workflow matrix" {
    try std.testing.expect(std.mem.eql(u8, releaseOsName(), "macos") or std.mem.eql(u8, releaseOsName(), "linux") or std.mem.eql(u8, releaseOsName(), "unsupported"));
    try std.testing.expect(std.mem.eql(u8, releaseArchName(), "x64") or std.mem.eql(u8, releaseArchName(), "arm64") or std.mem.eql(u8, releaseArchName(), "unsupported"));
}

test "version validation accepts v-prefixed release tags" {
    try std.testing.expect(outputMatchesTag("shisa 0.1.0\n", "v0.1.0"));
    try std.testing.expect(outputMatchesTag("shisa v0.1.0\n", "v0.1.0"));
    try std.testing.expect(!outputMatchesTag("shisa 0.1.0\n", "v0.2.0"));
}

const help_text =
    \\usage: shisa update [--verify|--no-verify] [--dry-run] [--rollback]
    \\
    \\options:
    \\  --verify             verify release signature before applying (default)
    \\  --no-verify          skip cosign verification
    \\  --dry-run            print update plan without downloading artifacts
    \\  --rollback           restore shisa.previous over the current binary
    \\  --repo OWNER/REPO    GitHub repo; default gongahkia/shisa
    \\  --tag TAG            install an explicit release tag instead of latest
    \\  --install-dir DIR    install directory; default current binary directory
    \\
;
