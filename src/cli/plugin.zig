const std = @import("std");
const build_options = @import("build_options");
const cli_util = @import("util.zig");
const daemon_json = @import("../daemon/json.zig");
const plugin_lua = @import("../plugin/lua.zig");
const plugin_manifest = @import("../plugin/manifest.zig");

const plugin_slow_strike_limit: u8 = 3;
const bundled_marketplace_index = build_options.marketplace_index;

pub fn command(allocator: std.mem.Allocator, args: []const []const u8) !void {
    if (args.len == 0) return error.UnknownPluginArgument;

    if (std.mem.eql(u8, args[0], "new")) {
        if (args.len != 2) return error.UnknownPluginArgument;
        try pluginNew(allocator, ".", args[1]);
        const message = try std.fmt.allocPrint(allocator, "created {s}\n", .{args[1]});
        defer allocator.free(message);
        try std.fs.File.stdout().writeAll(message);
        return;
    }

    if (std.mem.eql(u8, args[0], "lint")) {
        if (args.len != 2) return error.UnknownPluginArgument;
        const output = try pluginLintAlloc(allocator, args[1]);
        defer allocator.free(output);
        try std.fs.File.stdout().writeAll(output);
        return;
    }

    if (std.mem.eql(u8, args[0], "doctor")) {
        if (args.len > 2) return error.UnknownPluginArgument;
        const path = if (args.len == 2) args[1] else ".";
        const output = try pluginDoctorAlloc(allocator, path);
        defer allocator.free(output);
        try std.fs.File.stdout().writeAll(output);
        return;
    }

    if (std.mem.eql(u8, args[0], "verify")) {
        if (args.len != 2) return error.UnknownPluginArgument;
        const output = try pluginVerifyAlloc(allocator, args[1]);
        defer allocator.free(output);
        try std.fs.File.stdout().writeAll(output);
        return;
    }

    if (std.mem.eql(u8, args[0], "search")) {
        const config = try parsePluginSearchArgs(args[1..]);
        const output = if (config.index_path) |path|
            try pluginSearchPathAlloc(allocator, path, config.query)
        else
            try pluginSearchAlloc(allocator, bundled_marketplace_index, config.query);
        defer allocator.free(output);
        try std.fs.File.stdout().writeAll(output);
        return;
    }

    if (std.mem.eql(u8, args[0], "pack")) {
        if (args.len != 2) return error.UnknownPluginArgument;
        const output_path = try pluginPack(allocator, args[1], ".");
        defer allocator.free(output_path);
        const message = try std.fmt.allocPrint(allocator, "packed {s}\n", .{output_path});
        defer allocator.free(message);
        try std.fs.File.stdout().writeAll(message);
        return;
    }

    const plugins_dir = try cli_util.pluginsDirPath(allocator);
    defer allocator.free(plugins_dir);
    const disabled_path = try disabledPluginsPath(allocator);
    defer allocator.free(disabled_path);
    const slow_strikes_path = try slowStrikesPluginsPath(allocator);
    defer allocator.free(slow_strikes_path);
    const trusted_path = try trustedPluginsPath(allocator);
    defer allocator.free(trusted_path);
    const verified_path = try verifiedPluginsPath(allocator);
    defer allocator.free(verified_path);

    if (std.mem.eql(u8, args[0], "list")) {
        if (args.len != 1) return error.UnknownPluginArgument;
        const output = try pluginListAlloc(allocator, plugins_dir, disabled_path, slow_strikes_path, verified_path);
        defer allocator.free(output);
        try std.fs.File.stdout().writeAll(output);
    } else if (std.mem.eql(u8, args[0], "install")) {
        const config = try parsePluginInstallArgs(args[1..]);
        try pluginInstall(allocator, plugins_dir, trusted_path, config);
    } else if (std.mem.eql(u8, args[0], "disable")) {
        if (args.len != 2) return error.UnknownPluginArgument;
        try setPluginDisabled(allocator, disabled_path, args[1], true);
        const message = try std.fmt.allocPrint(allocator, "disabled {s}\n", .{args[1]});
        defer allocator.free(message);
        try std.fs.File.stdout().writeAll(message);
    } else if (std.mem.eql(u8, args[0], "enable")) {
        if (args.len != 2) return error.UnknownPluginArgument;
        try setPluginDisabled(allocator, disabled_path, args[1], false);
        const message = try std.fmt.allocPrint(allocator, "enabled {s}\n", .{args[1]});
        defer allocator.free(message);
        try std.fs.File.stdout().writeAll(message);
    } else if (std.mem.eql(u8, args[0], "trust")) {
        const config = try parsePluginTrustArgs(args[1..]);
        try setPluginTrusted(allocator, trusted_path, config.name);
        if (config.net) |provider| try setPluginTrustedNet(allocator, trusted_path, config.name, provider);
        const message = if (config.net) |provider|
            try std.fmt.allocPrint(allocator, "trusted {s} net={s}\n", .{ config.name, provider })
        else
            try std.fmt.allocPrint(allocator, "trusted {s}\n", .{config.name});
        defer allocator.free(message);
        try std.fs.File.stdout().writeAll(message);
    } else {
        return error.UnknownPluginArgument;
    }
}

const PluginTrustConfig = struct {
    name: []const u8,
    net: ?[]const u8 = null,
};

const PluginSearchConfig = struct {
    query: []const u8,
    index_path: ?[]const u8 = null,
};

fn parsePluginSearchArgs(args: []const []const u8) !PluginSearchConfig {
    var config: PluginSearchConfig = undefined;
    config.index_path = null;
    var seen_query = false;
    var i: usize = 0;
    while (i < args.len) : (i += 1) {
        const arg = args[i];
        if (std.mem.eql(u8, arg, "--index")) {
            i += 1;
            if (i >= args.len) return error.UnknownPluginArgument;
            config.index_path = args[i];
        } else if (!seen_query) {
            config.query = arg;
            seen_query = true;
        } else {
            return error.UnknownPluginArgument;
        }
    }
    if (!seen_query) return error.UnknownPluginArgument;
    return config;
}

fn parsePluginTrustArgs(args: []const []const u8) !PluginTrustConfig {
    if (args.len == 0) return error.UnknownPluginArgument;
    var config = PluginTrustConfig{ .name = args[0] };
    var i: usize = 1;
    while (i < args.len) : (i += 1) {
        const arg = args[i];
        if (std.mem.eql(u8, arg, "--net")) {
            config.net = try cli_util.nextValue(args, &i);
        } else if (std.mem.startsWith(u8, arg, "--net=")) {
            config.net = arg["--net=".len..];
            if (config.net.?.len == 0) return error.MissingValue;
        } else {
            return error.UnknownPluginArgument;
        }
    }
    return config;
}

fn pluginNew(allocator: std.mem.Allocator, parent_dir: []const u8, name: []const u8) !void {
    if (!plugin_manifest.isValidPluginName(name)) return error.InvalidPluginName;

    const target_path = try std.fs.path.join(allocator, &.{ parent_dir, name });
    defer allocator.free(target_path);
    try std.fs.cwd().makeDir(target_path);
    errdefer std.fs.cwd().deleteTree(target_path) catch {};

    const module_id = try pluginModuleNameAlloc(allocator, name);
    defer allocator.free(module_id);

    const plugin_source = try renderPluginScaffoldAlloc(allocator, name, module_id);
    defer allocator.free(plugin_source);
    const plugin_path = try std.fs.path.join(allocator, &.{ target_path, "plugin.lua" });
    defer allocator.free(plugin_path);
    try std.fs.cwd().writeFile(.{ .sub_path = plugin_path, .data = plugin_source });

    const readme_source = try renderPluginReadmeAlloc(allocator, name);
    defer allocator.free(readme_source);
    const readme_path = try std.fs.path.join(allocator, &.{ target_path, "README.md" });
    defer allocator.free(readme_path);
    try std.fs.cwd().writeFile(.{ .sub_path = readme_path, .data = readme_source });

    const license_source = try renderPluginLicenseAlloc(allocator, name);
    defer allocator.free(license_source);
    const license_path = try std.fs.path.join(allocator, &.{ target_path, "LICENSE" });
    defer allocator.free(license_path);
    try std.fs.cwd().writeFile(.{ .sub_path = license_path, .data = license_source });
}

fn pluginModuleNameAlloc(allocator: std.mem.Allocator, name: []const u8) ![]u8 {
    const module_id = try allocator.dupe(u8, name);
    for (module_id) |*byte| {
        if (byte.* == '-' or byte.* == '.') byte.* = '_';
    }
    return module_id;
}

fn renderPluginScaffoldAlloc(allocator: std.mem.Allocator, name: []const u8, module_id: []const u8) ![]u8 {
    return std.fmt.allocPrint(allocator,
        \\function on_load(ctx)
        \\  return nil
        \\end
        \\
        \\function render(ctx)
        \\  return nil
        \\end
        \\
        \\function update(ctx)
        \\  return nil
        \\end
        \\
        \\function on_unload(ctx)
        \\  return nil
        \\end
        \\
        \\return {{
        \\  name = "{s}",
        \\  version = "0.1.0",
        \\  api_version = 1,
        \\  license = "MIT",
        \\  description = "{s} plugin",
        \\  capabilities = {{
        \\    fs_read = {{}},
        \\    fs_watch = {{}},
        \\    exec = false,
        \\    net = false,
        \\    secrets = false,
        \\    env_read = {{}},
        \\    pre_exec = false,
        \\  }},
        \\  modules = {{ "{s}" }},
        \\  on_load = "on_load",
        \\  render = "render",
        \\  update = "update",
        \\  on_unload = "on_unload",
        \\}}
        \\
    , .{ name, name, module_id });
}

fn renderPluginReadmeAlloc(allocator: std.mem.Allocator, name: []const u8) ![]u8 {
    return std.fmt.allocPrint(allocator,
        \\# {s}
        \\
        \\Shisa plugin scaffold.
        \\
        \\Install locally:
        \\
        \\```sh
        \\shisa plugin install . --plugin-sandbox-strict
        \\```
        \\
    , .{name});
}

fn renderPluginLicenseAlloc(allocator: std.mem.Allocator, name: []const u8) ![]u8 {
    return std.fmt.allocPrint(allocator,
        \\MIT License
        \\
        \\Copyright (c) 2026 {s} contributors
        \\
        \\Permission is hereby granted, free of charge, to any person obtaining a copy
        \\of this software and associated documentation files (the "Software"), to deal
        \\in the Software without restriction, including without limitation the rights
        \\to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
        \\copies of the Software, and to permit persons to whom the Software is
        \\furnished to do so, subject to the following conditions:
        \\
        \\The above copyright notice and this permission notice shall be included in all
        \\copies or substantial portions of the Software.
        \\
        \\THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
        \\IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
        \\FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
        \\AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
        \\LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
        \\OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
        \\SOFTWARE.
        \\
    , .{name});
}

fn pluginLintAlloc(allocator: std.mem.Allocator, path: []const u8) ![]u8 {
    const manifest_path = try pluginManifestPathAlloc(allocator, path);
    defer allocator.free(manifest_path);
    const plugin_dir = std.fs.path.dirname(manifest_path) orelse ".";
    const source = try std.fs.cwd().readFileAlloc(allocator, manifest_path, 1024 * 1024);
    defer allocator.free(source);

    var runtime = try plugin_lua.Runtime.initSandboxedWithOptions(allocator, .{ .require_root = plugin_dir });
    defer runtime.deinit();
    var loaded = try runtime.loadManifestStrict(source);
    defer loaded.deinit(allocator);

    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);
    try cli_util.appendFmt(allocator, &out, "ok {s} {s}\n", .{ loaded.manifest.name, loaded.manifest.version });
    try appendPluginLintWarnings(allocator, &out, plugin_dir, loaded.manifest);
    return out.toOwnedSlice(allocator);
}

fn pluginDoctorAlloc(allocator: std.mem.Allocator, path: []const u8) ![]u8 {
    const lint = try pluginLintAlloc(allocator, path);
    defer allocator.free(lint);
    const status: []const u8 = if (std.mem.indexOf(u8, lint, "warning:") == null) "doctor ok\n" else "doctor warnings\n";
    return std.fmt.allocPrint(allocator, "{s}{s}", .{ status, lint });
}

fn pluginVerifyAlloc(allocator: std.mem.Allocator, path: []const u8) ![]u8 {
    const manifest_path = try pluginManifestPathAlloc(allocator, path);
    defer allocator.free(manifest_path);
    const plugin_dir = std.fs.path.dirname(manifest_path) orelse ".";
    const source = try std.fs.cwd().readFileAlloc(allocator, manifest_path, 1024 * 1024);
    defer allocator.free(source);

    try verifyPluginSourceStatic(source);
    var runtime = try plugin_lua.Runtime.initSandboxedWithOptions(allocator, .{ .require_root = plugin_dir });
    defer runtime.deinit();
    var loaded = try runtime.loadManifestStrict(source);
    defer loaded.deinit(allocator);
    try loaded.manifest.validate();

    return std.fmt.allocPrint(allocator, "verified {s} {s}\n", .{ loaded.manifest.name, loaded.manifest.version });
}

fn verifyPluginSourceStatic(source: []const u8) !void {
    if (std.mem.indexOf(u8, source, "os.execute") != null) return error.PluginStaticAnalysisFailed;
    if (std.mem.indexOf(u8, source, "io.popen") != null) return error.PluginStaticAnalysisFailed;
}

fn pluginManifestPathAlloc(allocator: std.mem.Allocator, path: []const u8) ![]u8 {
    if (std.mem.eql(u8, std.fs.path.basename(path), "plugin.lua")) return allocator.dupe(u8, path);
    return std.fs.path.join(allocator, &.{ path, "plugin.lua" });
}

fn appendPluginLintWarnings(allocator: std.mem.Allocator, out: *std.ArrayList(u8), plugin_dir: []const u8, manifest: plugin_manifest.Manifest) !void {
    if (!(try pathExistsInDir(allocator, plugin_dir, "README.md"))) try out.appendSlice(allocator, "warning: missing README.md\n");
    if (!(try pathExistsInDir(allocator, plugin_dir, "LICENSE"))) try out.appendSlice(allocator, "warning: missing LICENSE\n");
    if (manifest.capabilities.pre_exec and manifest.entry_points.pre_exec == null) try out.appendSlice(allocator, "warning: pre_exec capability without pre_exec hook\n");
    if (!manifest.capabilities.pre_exec and manifest.entry_points.pre_exec != null) try out.appendSlice(allocator, "warning: pre_exec hook without pre_exec capability\n");
}

fn pathExistsInDir(allocator: std.mem.Allocator, dir: []const u8, name: []const u8) !bool {
    const path = try std.fs.path.join(allocator, &.{ dir, name });
    defer allocator.free(path);
    std.fs.cwd().access(path, .{}) catch |err| switch (err) {
        error.FileNotFound => return false,
        else => return err,
    };
    return true;
}

const PluginBundleFile = struct {
    path: []u8,
    size: u64,
    sha256_hex: [std.crypto.hash.sha2.Sha256.digest_length * 2]u8,
};

fn pluginPack(allocator: std.mem.Allocator, path: []const u8, out_dir: []const u8) ![]u8 {
    const manifest_path = try pluginManifestPathAlloc(allocator, path);
    defer allocator.free(manifest_path);
    const plugin_dir = std.fs.path.dirname(manifest_path) orelse ".";
    const source = try std.fs.cwd().readFileAlloc(allocator, manifest_path, 1024 * 1024);
    defer allocator.free(source);

    var runtime = try plugin_lua.Runtime.initSandboxedWithOptions(allocator, .{ .require_root = plugin_dir });
    defer runtime.deinit();
    var loaded = try runtime.loadManifestStrict(source);
    defer loaded.deinit(allocator);

    var files = try collectPluginBundleFiles(allocator, plugin_dir);
    defer deinitPluginBundleFiles(allocator, &files);
    const canonical = try canonicalPluginBundleManifestAlloc(allocator, loaded.manifest, files.items);
    defer allocator.free(canonical);
    const metadata = try signedPluginBundleMetadataAlloc(allocator, loaded.manifest, files.items, canonical);
    defer allocator.free(metadata);

    const bundle_name = try std.fmt.allocPrint(allocator, "{s}-{s}.shisa-plugin", .{ loaded.manifest.name, loaded.manifest.version });
    defer allocator.free(bundle_name);
    const output_path = try std.fs.path.join(allocator, &.{ out_dir, bundle_name });
    errdefer allocator.free(output_path);
    var output = try std.fs.cwd().createFile(output_path, .{ .exclusive = true });
    defer output.close();
    try writePluginBundleTar(allocator, output, plugin_dir, files.items, metadata);
    return output_path;
}

fn collectPluginBundleFiles(allocator: std.mem.Allocator, plugin_dir: []const u8) !std.ArrayList(PluginBundleFile) {
    var dir = try openIterableDir(plugin_dir);
    defer dir.close();
    var walker = try dir.walk(allocator);
    defer walker.deinit();

    var files: std.ArrayList(PluginBundleFile) = .empty;
    errdefer deinitPluginBundleFiles(allocator, &files);
    while (try walker.next()) |entry| {
        if (entry.kind != .file) continue;
        if (std.mem.eql(u8, entry.path, "SHISA_PLUGIN_BUNDLE.json")) return error.PluginPackReservedPath;
        if (std.mem.eql(u8, entry.path, ".git") or std.mem.startsWith(u8, entry.path, ".git/")) continue;
        const full_path = try std.fs.path.join(allocator, &.{ plugin_dir, entry.path });
        defer allocator.free(full_path);
        const data = try std.fs.cwd().readFileAlloc(allocator, full_path, 16 * 1024 * 1024);
        defer allocator.free(data);
        var digest: [std.crypto.hash.sha2.Sha256.digest_length]u8 = undefined;
        std.crypto.hash.sha2.Sha256.hash(data, &digest, .{});
        const hex = std.fmt.bytesToHex(digest, .lower);
        try files.append(allocator, .{
            .path = try allocator.dupe(u8, entry.path),
            .size = data.len,
            .sha256_hex = hex,
        });
    }
    std.mem.sort(PluginBundleFile, files.items, {}, lessThanPluginBundleFile);
    return files;
}

fn openIterableDir(path: []const u8) !std.fs.Dir {
    if (std.fs.path.isAbsolute(path)) return std.fs.openDirAbsolute(path, .{ .iterate = true });
    return std.fs.cwd().openDir(path, .{ .iterate = true });
}

fn deinitPluginBundleFiles(allocator: std.mem.Allocator, files: *std.ArrayList(PluginBundleFile)) void {
    for (files.items) |file| allocator.free(file.path);
    files.deinit(allocator);
}

fn lessThanPluginBundleFile(_: void, lhs: PluginBundleFile, rhs: PluginBundleFile) bool {
    return std.mem.lessThan(u8, lhs.path, rhs.path);
}

fn canonicalPluginBundleManifestAlloc(allocator: std.mem.Allocator, manifest: plugin_manifest.Manifest, files: []const PluginBundleFile) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);
    try cli_util.appendFmt(allocator, &out, "format:shisa-plugin-bundle-v1\nname:{s}\nversion:{s}\n", .{ manifest.name, manifest.version });
    for (files) |file| {
        try cli_util.appendFmt(allocator, &out, "file:{d}:{s}:{d}:{s}\n", .{ file.path.len, file.path, file.size, file.sha256_hex[0..] });
    }
    return out.toOwnedSlice(allocator);
}

fn signedPluginBundleMetadataAlloc(allocator: std.mem.Allocator, manifest: plugin_manifest.Manifest, files: []const PluginBundleFile, canonical: []const u8) ![]u8 {
    const Ed25519 = std.crypto.sign.Ed25519;
    const key_pair = Ed25519.KeyPair.generate();
    const signature = try key_pair.sign(canonical, null);
    const public_key_hex = std.fmt.bytesToHex(key_pair.public_key.toBytes(), .lower);
    const signature_hex = std.fmt.bytesToHex(signature.toBytes(), .lower);

    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);
    const escaped_name = try daemon_json.escapeAlloc(allocator, manifest.name);
    defer allocator.free(escaped_name);
    const escaped_version = try daemon_json.escapeAlloc(allocator, manifest.version);
    defer allocator.free(escaped_version);
    try cli_util.appendFmt(allocator, &out,
        \\{{"format":"shisa-plugin-bundle-v1","name":"{s}","version":"{s}","files":[
    , .{ escaped_name, escaped_version });
    for (files, 0..) |file, index| {
        if (index != 0) try out.append(allocator, ',');
        const escaped_path = try daemon_json.escapeAlloc(allocator, file.path);
        defer allocator.free(escaped_path);
        try cli_util.appendFmt(allocator, &out, "{{\"path\":\"{s}\",\"size\":{d},\"sha256\":\"{s}\"}}", .{ escaped_path, file.size, file.sha256_hex[0..] });
    }
    try cli_util.appendFmt(allocator, &out,
        \\],"signature":{{"algorithm":"Ed25519","public_key":"{s}","signature":"{s}"}}}}
        \\
    , .{ public_key_hex[0..], signature_hex[0..] });
    return out.toOwnedSlice(allocator);
}

fn writePluginBundleTar(allocator: std.mem.Allocator, output: std.fs.File, plugin_dir: []const u8, files: []const PluginBundleFile, metadata: []const u8) !void {
    for (files) |file| {
        const full_path = try std.fs.path.join(allocator, &.{ plugin_dir, file.path });
        defer allocator.free(full_path);
        const data = try std.fs.cwd().readFileAlloc(allocator, full_path, 16 * 1024 * 1024);
        defer allocator.free(data);
        try writeTarEntry(output, file.path, data);
    }
    try writeTarEntry(output, "SHISA_PLUGIN_BUNDLE.json", metadata);
    const zero = [_]u8{0} ** 1024;
    try output.writeAll(&zero);
}

fn writeTarEntry(output: std.fs.File, name: []const u8, data: []const u8) !void {
    if (name.len == 0 or name.len > 100) return error.PluginPackPathTooLong;
    var header = [_]u8{0} ** 512;
    @memcpy(header[0..name.len], name);
    try writeTarOctal(header[100..108], 0o644);
    try writeTarOctal(header[108..116], 0);
    try writeTarOctal(header[116..124], 0);
    try writeTarOctal(header[124..136], data.len);
    try writeTarOctal(header[136..148], 0);
    @memset(header[148..156], ' ');
    header[156] = '0';
    @memcpy(header[257..263], "ustar\x00");
    @memcpy(header[263..265], "00");
    var checksum: u64 = 0;
    for (header) |byte| checksum += byte;
    try writeTarChecksum(header[148..156], checksum);
    try output.writeAll(&header);
    try output.writeAll(data);
    try writeTarPadding(output, data.len);
}

fn writeTarOctal(field: []u8, value: u64) !void {
    @memset(field, 0);
    var buffer: [32]u8 = undefined;
    const text = try std.fmt.bufPrint(&buffer, "{o}", .{value});
    const digits_len = field.len - 1;
    if (text.len > digits_len) return error.PluginPackTarFieldOverflow;
    const start = digits_len - text.len;
    @memset(field[0..start], '0');
    @memcpy(field[start..digits_len], text);
    field[digits_len] = 0;
}

fn writeTarChecksum(field: []u8, checksum: u64) !void {
    var buffer: [32]u8 = undefined;
    const text = try std.fmt.bufPrint(&buffer, "{o}", .{checksum});
    if (text.len > 6) return error.PluginPackTarFieldOverflow;
    @memset(field[0..6], '0');
    @memcpy(field[6 - text.len .. 6], text);
    field[6] = 0;
    field[7] = ' ';
}

fn writeTarPadding(output: std.fs.File, len: usize) !void {
    const remainder = len % 512;
    if (remainder == 0) return;
    const zero = [_]u8{0} ** 512;
    try output.writeAll(zero[0 .. 512 - remainder]);
}

const PluginInstallConfig = struct {
    url: []const u8,
    yes: bool = false,
    strict: bool = false,
    index_path: ?[]const u8 = null,
};

const PluginInstallSourceKind = enum {
    local_path,
    git_url,
};

const PluginInstallSource = struct {
    kind: PluginInstallSourceKind,
    value: []u8,

    fn deinit(self: PluginInstallSource, allocator: std.mem.Allocator) void {
        allocator.free(self.value);
    }
};

fn parsePluginInstallArgs(args: []const []const u8) !PluginInstallConfig {
    var config: PluginInstallConfig = undefined;
    var seen_url = false;
    config.yes = false;
    config.strict = false;
    config.index_path = null;

    var i: usize = 0;
    while (i < args.len) : (i += 1) {
        const arg = args[i];
        if (std.mem.eql(u8, arg, "--yes") or std.mem.eql(u8, arg, "-y")) {
            config.yes = true;
        } else if (std.mem.eql(u8, arg, "--plugin-sandbox-strict")) {
            config.strict = true;
        } else if (std.mem.eql(u8, arg, "--index")) {
            i += 1;
            if (i >= args.len) return error.UnknownPluginArgument;
            config.index_path = args[i];
        } else if (!seen_url) {
            config.url = arg;
            seen_url = true;
        } else {
            return error.UnknownPluginArgument;
        }
    }
    if (!seen_url) return error.UnknownPluginArgument;
    return config;
}

fn pluginInstall(allocator: std.mem.Allocator, plugins_dir: []const u8, trusted_path: []const u8, config: PluginInstallConfig) !void {
    try std.fs.cwd().makePath(plugins_dir);

    const source = try pluginInstallSourceAlloc(allocator, config);
    defer source.deinit(allocator);

    const temp_path = try std.fmt.allocPrint(allocator, "{s}/.install-{x}", .{ plugins_dir, std.crypto.random.int(u64) });
    defer allocator.free(temp_path);
    defer std.fs.cwd().deleteTree(temp_path) catch {};

    switch (source.kind) {
        .local_path => try copyPluginTree(allocator, source.value, temp_path),
        .git_url => try runGitClone(allocator, source.value, temp_path),
    }

    const manifest_path = try std.fmt.allocPrint(allocator, "{s}/plugin.lua", .{temp_path});
    defer allocator.free(manifest_path);
    const manifest_source = try std.fs.cwd().readFileAlloc(allocator, manifest_path, 1024 * 1024);
    defer allocator.free(manifest_source);

    var runtime = try plugin_lua.Runtime.initSandboxedWithOptions(allocator, .{ .require_root = temp_path });
    defer runtime.deinit();
    var loaded = if (config.strict)
        try runtime.loadManifestStrict(manifest_source)
    else
        try runtime.loadManifest(manifest_source);
    defer loaded.deinit(allocator);

    const target_path = try std.fmt.allocPrint(allocator, "{s}/{s}", .{ plugins_dir, loaded.manifest.name });
    defer allocator.free(target_path);
    if (std.fs.cwd().access(target_path, .{})) |_| return error.PluginAlreadyInstalled else |err| switch (err) {
        error.FileNotFound => {},
        else => return err,
    }

    const prompted = !config.yes and !(try pluginTrustedForManifest(allocator, trusted_path, loaded.manifest));
    if (prompted and !(try confirmPluginInstall(allocator, loaded.manifest))) return error.PluginInstallDeclined;

    try std.fs.renameAbsolute(temp_path, target_path);
    if (prompted) try setPluginTrustedManifest(allocator, trusted_path, loaded.manifest);
    const message = try std.fmt.allocPrint(allocator, "installed {s} {s}\n", .{ loaded.manifest.name, loaded.manifest.version });
    defer allocator.free(message);
    try std.fs.File.stdout().writeAll(message);
}

fn pluginInstallSourceAlloc(allocator: std.mem.Allocator, config: PluginInstallConfig) !PluginInstallSource {
    if (!pluginInstallSourceNeedsMarketplace(config.url)) {
        const kind: PluginInstallSourceKind = if (pluginInstallSourceIsGit(config.url)) .git_url else .local_path;
        const value = if (kind == .local_path) try expandPluginPathAlloc(allocator, config.url) else try allocator.dupe(u8, config.url);
        return .{ .kind = kind, .value = value };
    }
    if (config.index_path) |path| {
        const source = try std.fs.cwd().readFileAlloc(allocator, path, 1024 * 1024);
        defer allocator.free(source);
        return .{ .kind = .local_path, .value = try marketplacePluginPathAlloc(allocator, source, config.url) };
    }
    return .{ .kind = .local_path, .value = try marketplacePluginPathAlloc(allocator, bundled_marketplace_index, config.url) };
}

fn pluginInstallSourceNeedsMarketplace(source: []const u8) bool {
    if (!plugin_manifest.isValidPluginName(source)) return false;
    if (std.mem.startsWith(u8, source, ".") or std.mem.startsWith(u8, source, "/") or std.mem.startsWith(u8, source, "~")) return false;
    if (std.mem.indexOf(u8, source, "://") != null) return false;
    if (std.mem.indexOfScalar(u8, source, ':') != null) return false;
    if (std.mem.endsWith(u8, source, ".git")) return false;
    return true;
}

fn pluginInstallSourceIsGit(source: []const u8) bool {
    if (std.mem.indexOf(u8, source, "://") != null) return true;
    if (std.mem.endsWith(u8, source, ".git")) return true;
    return false;
}

fn expandPluginPathAlloc(allocator: std.mem.Allocator, path: []const u8) ![]u8 {
    if (std.mem.eql(u8, path, "~")) return std.process.getEnvVarOwned(allocator, "HOME");
    if (std.mem.startsWith(u8, path, "~/")) {
        const home = try std.process.getEnvVarOwned(allocator, "HOME");
        defer allocator.free(home);
        return std.fmt.allocPrint(allocator, "{s}/{s}", .{ home, path[2..] });
    }
    return allocator.dupe(u8, path);
}

fn runGitClone(allocator: std.mem.Allocator, url: []const u8, target_path: []const u8) !void {
    const result = try std.process.Child.run(.{
        .allocator = allocator,
        .argv = &.{ "git", "clone", "--depth", "1", url, target_path },
        .max_output_bytes = 1024 * 1024,
        .expand_arg0 = .expand,
    });
    defer allocator.free(result.stdout);
    defer allocator.free(result.stderr);
    if (!cli_util.exitedZero(result.term)) return error.PluginCloneFailed;
}

fn copyPluginTree(allocator: std.mem.Allocator, source_path: []const u8, target_path: []const u8) !void {
    var source_dir = try std.fs.cwd().openDir(source_path, .{ .iterate = true });
    defer source_dir.close();
    try std.fs.cwd().makePath(target_path);
    errdefer std.fs.cwd().deleteTree(target_path) catch {};
    try copyPluginDirContents(allocator, source_dir, target_path);
}

fn copyPluginDirContents(allocator: std.mem.Allocator, source_dir: std.fs.Dir, target_path: []const u8) !void {
    var it = source_dir.iterate();
    while (try it.next()) |entry| {
        const child_target = try std.fs.path.join(allocator, &.{ target_path, entry.name });
        defer allocator.free(child_target);
        switch (entry.kind) {
            .file => try source_dir.copyFile(entry.name, std.fs.cwd(), child_target, .{}),
            .directory => {
                try std.fs.cwd().makePath(child_target);
                var child_source = try source_dir.openDir(entry.name, .{ .iterate = true });
                defer child_source.close();
                try copyPluginDirContents(allocator, child_source, child_target);
            },
            else => return error.PluginUnsupportedFileType,
        }
    }
}

fn confirmPluginInstall(allocator: std.mem.Allocator, manifest: plugin_manifest.Manifest) !bool {
    const prompt_text = try std.fmt.allocPrint(allocator, "Install plugin {s} {s}? [y/N] ", .{ manifest.name, manifest.version });
    defer allocator.free(prompt_text);
    try std.fs.File.stdout().writeAll(prompt_text);
    const answer = try std.fs.File.stdin().readToEndAlloc(allocator, 16);
    defer allocator.free(answer);
    const trimmed = std.mem.trim(u8, answer, " \t\r\n");
    return trimmed.len > 0 and (trimmed[0] == 'y' or trimmed[0] == 'Y');
}

fn disabledPluginsPath(allocator: std.mem.Allocator) ![]u8 {
    const config_path = try cli_util.defaultConfigPath(allocator);
    defer allocator.free(config_path);
    const dir = std.fs.path.dirname(config_path) orelse return error.MissingConfigDir;
    return std.fmt.allocPrint(allocator, "{s}/plugins.disabled", .{dir});
}

fn slowStrikesPluginsPath(allocator: std.mem.Allocator) ![]u8 {
    const config_path = try cli_util.defaultConfigPath(allocator);
    defer allocator.free(config_path);
    const dir = std.fs.path.dirname(config_path) orelse return error.MissingConfigDir;
    return std.fmt.allocPrint(allocator, "{s}/plugins.slow-strikes", .{dir});
}

fn trustedPluginsPath(allocator: std.mem.Allocator) ![]u8 {
    const config_path = try cli_util.defaultConfigPath(allocator);
    defer allocator.free(config_path);
    const dir = std.fs.path.dirname(config_path) orelse return error.MissingConfigDir;
    return std.fmt.allocPrint(allocator, "{s}/plugins.trusted", .{dir});
}

fn verifiedPluginsPath(allocator: std.mem.Allocator) ![]u8 {
    const config_path = try cli_util.defaultConfigPath(allocator);
    defer allocator.free(config_path);
    const dir = std.fs.path.dirname(config_path) orelse return error.MissingConfigDir;
    return std.fmt.allocPrint(allocator, "{s}/plugins.verified", .{dir});
}

fn pluginListAlloc(allocator: std.mem.Allocator, plugins_dir: []const u8, disabled_path: []const u8, slow_strikes_path: []const u8, verified_path: []const u8) ![]u8 {
    var names: std.ArrayList([]u8) = .empty;
    defer {
        for (names.items) |name| allocator.free(name);
        names.deinit(allocator);
    }

    var dir = std.fs.openDirAbsolute(plugins_dir, .{ .iterate = true }) catch |err| switch (err) {
        error.FileNotFound => return allocator.dupe(u8, ""),
        else => return err,
    };
    defer dir.close();

    var it = dir.iterate();
    while (try it.next()) |entry| {
        if (entry.kind != .directory) continue;
        if (!plugin_manifest.isValidPluginName(entry.name)) continue;
        try names.append(allocator, try allocator.dupe(u8, entry.name));
    }
    std.mem.sort([]u8, names.items, {}, lessThanString);

    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);
    for (names.items) |name| {
        const disabled = try pluginDisabled(allocator, disabled_path, name);
        const slow_strikes = try pluginSlowStrikeCount(allocator, slow_strikes_path, name);
        const verified = try pluginVerified(allocator, verified_path, name);
        const badge = if (verified) "verified " else "";
        if (disabled and slow_strikes > 0) {
            try cli_util.appendFmt(allocator, &out, "{s} {s}disabled slow-strikes={d}/{d}\n", .{ name, badge, slow_strikes, plugin_slow_strike_limit });
        } else if (disabled) {
            try cli_util.appendFmt(allocator, &out, "{s} {s}disabled\n", .{ name, badge });
        } else if (slow_strikes > 0) {
            try cli_util.appendFmt(allocator, &out, "{s} {s}slow-strikes={d}/{d}\n", .{ name, badge, slow_strikes, plugin_slow_strike_limit });
        } else {
            try cli_util.appendFmt(allocator, &out, "{s} {s}enabled\n", .{ name, badge });
        }
    }
    return out.toOwnedSlice(allocator);
}

const PluginMarketplaceEntry = struct {
    name: []const u8,
    path: []const u8,
    homepage: ?[]const u8 = null,
    version: []const u8,
    capabilities: []const []const u8,
    sigstore_key: ?[]const u8 = null,
    status: []const u8,
    description: ?[]const u8 = null,
    keywords: []const []const u8 = &.{},
};

const PluginMarketplaceIndex = struct {
    plugins: []PluginMarketplaceEntry,

    fn deinit(self: PluginMarketplaceIndex, allocator: std.mem.Allocator) void {
        for (self.plugins) |entry| {
            allocator.free(entry.capabilities);
            allocator.free(entry.keywords);
        }
        allocator.free(self.plugins);
    }
};

const PluginMarketplaceEntryBuilder = struct {
    name: ?[]const u8 = null,
    path: ?[]const u8 = null,
    homepage: ?[]const u8 = null,
    version: ?[]const u8 = null,
    capabilities: ?[]const []const u8 = null,
    sigstore_key: ?[]const u8 = null,
    status: ?[]const u8 = null,
    description: ?[]const u8 = null,
    keywords: ?[]const []const u8 = null,

    fn deinit(self: *PluginMarketplaceEntryBuilder, allocator: std.mem.Allocator) void {
        if (self.capabilities) |items| allocator.free(items);
        if (self.keywords) |items| allocator.free(items);
    }
};

fn pluginSearchPathAlloc(allocator: std.mem.Allocator, index_path: []const u8, query: []const u8) ![]u8 {
    const source = try std.fs.cwd().readFileAlloc(allocator, index_path, 1024 * 1024);
    defer allocator.free(source);
    return pluginSearchAlloc(allocator, source, query);
}

fn pluginSearchAlloc(allocator: std.mem.Allocator, source: []const u8, query: []const u8) ![]u8 {
    var parsed = try parseMarketplaceIndexAlloc(allocator, source);
    defer parsed.deinit(allocator);

    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);
    for (parsed.plugins) |entry| {
        if (!marketplaceEntryMatches(entry, query)) continue;
        const sigstore_badge = if (entry.sigstore_key != null) " sigstore" else "";
        const location = entry.homepage orelse entry.path;
        try cli_util.appendFmt(allocator, &out, "{s} {s}{s} {s} {s}", .{ entry.name, entry.status, sigstore_badge, entry.version, location });
        if (entry.description) |description| try cli_util.appendFmt(allocator, &out, " - {s}", .{description});
        if (entry.capabilities.len != 0) {
            try out.appendSlice(allocator, " [");
            for (entry.capabilities, 0..) |capability, i| {
                if (i != 0) try out.append(allocator, ',');
                try out.appendSlice(allocator, capability);
            }
            try out.append(allocator, ']');
        }
        try out.append(allocator, '\n');
    }
    return out.toOwnedSlice(allocator);
}

fn marketplacePluginPathAlloc(allocator: std.mem.Allocator, source: []const u8, name: []const u8) ![]u8 {
    var parsed = try parseMarketplaceIndexAlloc(allocator, source);
    defer parsed.deinit(allocator);
    for (parsed.plugins) |entry| {
        if (std.mem.eql(u8, entry.name, name)) return allocator.dupe(u8, entry.path);
    }
    return error.PluginMarketplaceEntryNotFound;
}

fn marketplaceEntryMatches(entry: PluginMarketplaceEntry, query: []const u8) bool {
    if (containsIgnoreAsciiCase(entry.name, query)) return true;
    if (containsIgnoreAsciiCase(entry.path, query)) return true;
    if (entry.homepage) |homepage| if (containsIgnoreAsciiCase(homepage, query)) return true;
    if (containsIgnoreAsciiCase(entry.status, query)) return true;
    if (containsIgnoreAsciiCase(entry.version, query)) return true;
    if (entry.description) |description| if (containsIgnoreAsciiCase(description, query)) return true;
    for (entry.capabilities) |capability| if (containsIgnoreAsciiCase(capability, query)) return true;
    for (entry.keywords) |keyword| if (containsIgnoreAsciiCase(keyword, query)) return true;
    return false;
}

fn parseMarketplaceIndexAlloc(allocator: std.mem.Allocator, source: []const u8) !PluginMarketplaceIndex {
    var entries: std.ArrayList(PluginMarketplaceEntry) = .empty;
    errdefer {
        for (entries.items) |entry| {
            allocator.free(entry.capabilities);
            allocator.free(entry.keywords);
        }
        entries.deinit(allocator);
    }

    var builder = PluginMarketplaceEntryBuilder{};
    var have_entry = false;
    defer builder.deinit(allocator);

    var lines = std.mem.splitScalar(u8, source, '\n');
    while (lines.next()) |raw_line| {
        const line = stripTomlComment(std.mem.trim(u8, raw_line, " \t\r"));
        if (line.len == 0) continue;
        if (std.mem.eql(u8, line, "[[plugins]]")) {
            if (have_entry) {
                try entries.append(allocator, try finishMarketplaceEntryAlloc(allocator, &builder));
                builder = .{};
            }
            have_entry = true;
            continue;
        }
        if (!have_entry) return error.InvalidMarketplaceIndex;
        const eq = std.mem.indexOfScalar(u8, line, '=') orelse return error.InvalidMarketplaceIndex;
        const key = std.mem.trim(u8, line[0..eq], " \t");
        const value = std.mem.trim(u8, line[eq + 1 ..], " \t");
        try setMarketplaceEntryField(allocator, &builder, key, value);
    }
    if (have_entry) try entries.append(allocator, try finishMarketplaceEntryAlloc(allocator, &builder));
    return .{ .plugins = try entries.toOwnedSlice(allocator) };
}

fn setMarketplaceEntryField(allocator: std.mem.Allocator, builder: *PluginMarketplaceEntryBuilder, key: []const u8, value: []const u8) !void {
    if (std.mem.eql(u8, key, "name")) {
        if (builder.name != null) return error.InvalidMarketplaceIndex;
        builder.name = try parseTomlString(value);
    } else if (std.mem.eql(u8, key, "path")) {
        if (builder.path != null) return error.InvalidMarketplaceIndex;
        builder.path = try parseTomlString(value);
    } else if (std.mem.eql(u8, key, "homepage")) {
        if (builder.homepage != null) return error.InvalidMarketplaceIndex;
        builder.homepage = try parseTomlString(value);
    } else if (std.mem.eql(u8, key, "version")) {
        if (builder.version != null) return error.InvalidMarketplaceIndex;
        builder.version = try parseTomlString(value);
    } else if (std.mem.eql(u8, key, "capabilities")) {
        if (builder.capabilities != null) return error.InvalidMarketplaceIndex;
        builder.capabilities = try parseTomlStringArrayAlloc(allocator, value);
    } else if (std.mem.eql(u8, key, "sigstore_key")) {
        if (builder.sigstore_key != null) return error.InvalidMarketplaceIndex;
        builder.sigstore_key = try parseTomlString(value);
    } else if (std.mem.eql(u8, key, "status")) {
        if (builder.status != null) return error.InvalidMarketplaceIndex;
        builder.status = try parseTomlString(value);
    } else if (std.mem.eql(u8, key, "description")) {
        if (builder.description != null) return error.InvalidMarketplaceIndex;
        builder.description = try parseTomlString(value);
    } else if (std.mem.eql(u8, key, "keywords")) {
        if (builder.keywords != null) return error.InvalidMarketplaceIndex;
        builder.keywords = try parseTomlStringArrayAlloc(allocator, value);
    } else {
        return error.InvalidMarketplaceIndex;
    }
}

fn finishMarketplaceEntryAlloc(allocator: std.mem.Allocator, builder: *PluginMarketplaceEntryBuilder) !PluginMarketplaceEntry {
    const capabilities = builder.capabilities orelse return error.InvalidMarketplaceIndex;
    builder.capabilities = null;
    errdefer allocator.free(capabilities);
    const keywords = builder.keywords orelse try allocator.alloc([]const u8, 0);
    builder.keywords = null;
    errdefer allocator.free(keywords);

    const entry = PluginMarketplaceEntry{
        .name = builder.name orelse return error.InvalidMarketplaceIndex,
        .path = builder.path orelse return error.InvalidMarketplaceIndex,
        .homepage = builder.homepage,
        .version = builder.version orelse return error.InvalidMarketplaceIndex,
        .capabilities = capabilities,
        .sigstore_key = builder.sigstore_key,
        .status = builder.status orelse return error.InvalidMarketplaceIndex,
        .description = builder.description,
        .keywords = keywords,
    };
    try validateMarketplaceEntry(entry);
    return entry;
}

fn validateMarketplaceEntry(entry: PluginMarketplaceEntry) !void {
    if (!plugin_manifest.isValidPluginName(entry.name)) return error.InvalidMarketplaceIndex;
    if (!validMarketplacePath(entry.path)) return error.InvalidMarketplaceIndex;
    if (entry.homepage) |homepage| {
        if (!std.mem.startsWith(u8, homepage, "https://")) return error.InvalidMarketplaceIndex;
    }
    if (!validMarketplaceStatus(entry.status)) return error.InvalidMarketplaceIndex;
    if (entry.capabilities.len == 0) return error.InvalidMarketplaceIndex;
    for (entry.capabilities) |capability| {
        if (!validMarketplaceCapability(capability)) return error.InvalidMarketplaceIndex;
    }
}

fn validMarketplacePath(path: []const u8) bool {
    if (path.len == 0 or std.fs.path.isAbsolute(path)) return false;
    if (std.mem.indexOfAny(u8, path, " \t\r\n") != null) return false;
    var components = std.mem.splitScalar(u8, path, '/');
    while (components.next()) |component| {
        if (component.len == 0 or std.mem.eql(u8, component, ".") or std.mem.eql(u8, component, "..")) return false;
    }
    return true;
}

fn validMarketplaceStatus(status: []const u8) bool {
    return std.mem.eql(u8, status, "community") or std.mem.eql(u8, status, "official") or std.mem.eql(u8, status, "archived");
}

fn validMarketplaceCapability(capability: []const u8) bool {
    inline for (.{
        "fs_read",
        "fs_watch",
        "exec",
        "net",
        "secrets",
        "env_read",
        "pre_exec",
    }) |known| {
        if (std.mem.eql(u8, capability, known)) return true;
    }
    return false;
}

fn stripTomlComment(line: []const u8) []const u8 {
    var in_string = false;
    var escaped = false;
    for (line, 0..) |byte, i| {
        if (escaped) {
            escaped = false;
        } else if (byte == '\\' and in_string) {
            escaped = true;
        } else if (byte == '"') {
            in_string = !in_string;
        } else if (byte == '#' and !in_string) {
            return std.mem.trim(u8, line[0..i], " \t");
        }
    }
    return std.mem.trim(u8, line, " \t");
}

fn parseTomlString(value: []const u8) ![]const u8 {
    const trimmed = std.mem.trim(u8, value, " \t");
    if (trimmed.len < 2 or trimmed[0] != '"' or trimmed[trimmed.len - 1] != '"') return error.InvalidMarketplaceIndex;
    const inner = trimmed[1 .. trimmed.len - 1];
    if (std.mem.indexOfScalar(u8, inner, '\\') != null) return error.InvalidMarketplaceIndex;
    return inner;
}

fn parseTomlStringArrayAlloc(allocator: std.mem.Allocator, value: []const u8) ![]const []const u8 {
    const trimmed = std.mem.trim(u8, value, " \t");
    if (trimmed.len < 2 or trimmed[0] != '[' or trimmed[trimmed.len - 1] != ']') return error.InvalidMarketplaceIndex;
    var rest = std.mem.trim(u8, trimmed[1 .. trimmed.len - 1], " \t");
    var items: std.ArrayList([]const u8) = .empty;
    errdefer items.deinit(allocator);
    while (rest.len != 0) {
        if (rest[0] != '"') return error.InvalidMarketplaceIndex;
        const close = std.mem.indexOfScalar(u8, rest[1..], '"') orelse return error.InvalidMarketplaceIndex;
        const item = rest[1 .. close + 1];
        if (std.mem.indexOfScalar(u8, item, '\\') != null) return error.InvalidMarketplaceIndex;
        try items.append(allocator, item);
        rest = std.mem.trim(u8, rest[close + 2 ..], " \t");
        if (rest.len == 0) break;
        if (rest[0] != ',') return error.InvalidMarketplaceIndex;
        rest = std.mem.trim(u8, rest[1..], " \t");
    }
    return items.toOwnedSlice(allocator);
}

fn containsIgnoreAsciiCase(haystack: []const u8, needle: []const u8) bool {
    if (needle.len == 0) return true;
    if (needle.len > haystack.len) return false;
    var start: usize = 0;
    while (start + needle.len <= haystack.len) : (start += 1) {
        var index: usize = 0;
        while (index < needle.len) : (index += 1) {
            if (std.ascii.toLower(haystack[start + index]) != std.ascii.toLower(needle[index])) break;
        } else return true;
    }
    return false;
}

fn setPluginDisabled(allocator: std.mem.Allocator, disabled_path: []const u8, name: []const u8, disabled: bool) !void {
    if (!plugin_manifest.isValidPluginName(name)) return error.InvalidPluginName;

    var names = try readPluginNames(allocator, disabled_path);
    defer {
        for (names.items) |item| allocator.free(item);
        names.deinit(allocator);
    }

    const index = indexOfString(names.items, name);
    if (disabled and index == null) {
        try names.append(allocator, try allocator.dupe(u8, name));
    } else if (!disabled and index != null) {
        const removed = names.orderedRemove(index.?);
        allocator.free(removed);
    }
    std.mem.sort([]u8, names.items, {}, lessThanString);
    try writePluginNames(disabled_path, names.items);
}

fn pluginDisabled(allocator: std.mem.Allocator, disabled_path: []const u8, name: []const u8) !bool {
    var names = try readPluginNames(allocator, disabled_path);
    defer {
        for (names.items) |item| allocator.free(item);
        names.deinit(allocator);
    }
    return indexOfString(names.items, name) != null;
}

fn pluginVerified(allocator: std.mem.Allocator, verified_path: []const u8, name: []const u8) !bool {
    var names = try readPluginNames(allocator, verified_path);
    defer {
        for (names.items) |item| allocator.free(item);
        names.deinit(allocator);
    }
    return indexOfString(names.items, name) != null;
}

fn pluginSlowStrikeCount(allocator: std.mem.Allocator, slow_strikes_path: []const u8, name: []const u8) !u8 {
    const contents = std.fs.cwd().readFileAlloc(allocator, slow_strikes_path, 1024 * 1024) catch |err| switch (err) {
        error.FileNotFound => return 0,
        else => return err,
    };
    defer allocator.free(contents);

    var lines = std.mem.tokenizeScalar(u8, contents, '\n');
    while (lines.next()) |line| {
        var fields = std.mem.tokenizeAny(u8, std.mem.trim(u8, line, " \t\r"), " \t\r");
        const listed_name = fields.next() orelse continue;
        const count_text = fields.next() orelse continue;
        if (fields.next() != null or !plugin_manifest.isValidPluginName(listed_name)) continue;
        if (!std.mem.eql(u8, listed_name, name)) continue;
        const count = std.fmt.parseInt(u8, count_text, 10) catch return 0;
        return @min(count, plugin_slow_strike_limit);
    }
    return 0;
}

fn setPluginTrusted(allocator: std.mem.Allocator, trusted_path: []const u8, name: []const u8) !void {
    if (!plugin_manifest.isValidPluginName(name)) return error.InvalidPluginName;

    var names = try readPluginNames(allocator, trusted_path);
    defer {
        for (names.items) |item| allocator.free(item);
        names.deinit(allocator);
    }

    if (indexOfString(names.items, name) == null) {
        try names.append(allocator, try allocator.dupe(u8, name));
    }
    std.mem.sort([]u8, names.items, {}, lessThanString);
    try writePluginNames(trusted_path, names.items);
}

fn pluginTrusted(allocator: std.mem.Allocator, trusted_path: []const u8, name: []const u8) !bool {
    var names = try readPluginNames(allocator, trusted_path);
    defer {
        for (names.items) |item| allocator.free(item);
        names.deinit(allocator);
    }
    return indexOfString(names.items, name) != null;
}

fn pluginTrustedForManifest(allocator: std.mem.Allocator, trusted_path: []const u8, manifest: plugin_manifest.Manifest) !bool {
    if (!(try pluginTrusted(allocator, trusted_path, manifest.name))) return false;

    const capabilities_path = try trustedCapabilitiesPathAlloc(allocator, trusted_path);
    defer allocator.free(capabilities_path);
    const fingerprint = try manifestCapabilityFingerprintAlloc(allocator, manifest);
    defer allocator.free(fingerprint);
    if (try trustedCapabilityFingerprintMatches(allocator, capabilities_path, manifest.name, fingerprint)) return true;
    return pluginManifestTrustedByNetGrants(allocator, trusted_path, manifest);
}

fn setPluginTrustedManifest(allocator: std.mem.Allocator, trusted_path: []const u8, manifest: plugin_manifest.Manifest) !void {
    try setPluginTrusted(allocator, trusted_path, manifest.name);

    const capabilities_path = try trustedCapabilitiesPathAlloc(allocator, trusted_path);
    defer allocator.free(capabilities_path);
    const fingerprint = try manifestCapabilityFingerprintAlloc(allocator, manifest);
    defer allocator.free(fingerprint);
    try setTrustedCapabilityFingerprint(allocator, capabilities_path, manifest.name, fingerprint);
}

fn trustedCapabilitiesPathAlloc(allocator: std.mem.Allocator, trusted_path: []const u8) ![]u8 {
    return std.fmt.allocPrint(allocator, "{s}.capabilities", .{trusted_path});
}

fn trustedNetProvidersPathAlloc(allocator: std.mem.Allocator, trusted_path: []const u8) ![]u8 {
    return std.fmt.allocPrint(allocator, "{s}.net", .{trusted_path});
}

fn setPluginTrustedNet(allocator: std.mem.Allocator, trusted_path: []const u8, name: []const u8, provider: []const u8) !void {
    if (!plugin_manifest.isValidPluginName(name)) return error.InvalidPluginName;
    if (!validNetProviderId(provider)) return error.InvalidNetCapability;

    const path = try trustedNetProvidersPathAlloc(allocator, trusted_path);
    defer allocator.free(path);
    var grants = try readTrustedNetGrants(allocator, path);
    defer deinitTrustedNetGrants(allocator, &grants);

    if (indexOfTrustedNetGrant(grants.items, name, provider) == null) {
        const name_copy = try allocator.dupe(u8, name);
        errdefer allocator.free(name_copy);
        const provider_copy = try allocator.dupe(u8, provider);
        errdefer allocator.free(provider_copy);
        try grants.append(allocator, .{
            .name = name_copy,
            .provider = provider_copy,
        });
    }
    std.mem.sort(TrustedNetGrant, grants.items, {}, lessThanTrustedNetGrant);
    try writeTrustedNetGrants(path, grants.items);
}

fn pluginTrustedNet(allocator: std.mem.Allocator, trusted_path: []const u8, name: []const u8, provider: []const u8) !bool {
    const path = try trustedNetProvidersPathAlloc(allocator, trusted_path);
    defer allocator.free(path);
    var grants = try readTrustedNetGrants(allocator, path);
    defer deinitTrustedNetGrants(allocator, &grants);
    return indexOfTrustedNetGrant(grants.items, name, provider) != null;
}

fn pluginManifestTrustedByNetGrants(allocator: std.mem.Allocator, trusted_path: []const u8, manifest: plugin_manifest.Manifest) !bool {
    if (manifest.capabilities.fs_read.len != 0 or
        manifest.capabilities.fs_watch.len != 0 or
        !listCapabilityIsDeny(manifest.capabilities.exec) or
        manifest.capabilities.secrets or
        manifest.capabilities.env_read.len != 0 or
        manifest.capabilities.pre_exec)
    {
        return false;
    }
    return switch (manifest.capabilities.net) {
        .deny => false,
        .allow => |providers| {
            if (providers.len == 0) return false;
            for (providers) |provider| {
                if (!(try pluginTrustedNet(allocator, trusted_path, manifest.name, provider))) return false;
            }
            return true;
        },
    };
}

fn listCapabilityIsDeny(capability: plugin_manifest.ListCapability) bool {
    return switch (capability) {
        .deny => true,
        .allow => false,
    };
}

const TrustedNetGrant = struct {
    name: []u8,
    provider: []u8,
};

fn readTrustedNetGrants(allocator: std.mem.Allocator, path: []const u8) !std.ArrayList(TrustedNetGrant) {
    var grants: std.ArrayList(TrustedNetGrant) = .empty;
    errdefer deinitTrustedNetGrants(allocator, &grants);
    const contents = std.fs.cwd().readFileAlloc(allocator, path, 1024 * 1024) catch |err| switch (err) {
        error.FileNotFound => return grants,
        else => return err,
    };
    defer allocator.free(contents);

    var lines = std.mem.tokenizeScalar(u8, contents, '\n');
    while (lines.next()) |line| {
        const record = parseTrustedNetGrantLine(line) orelse continue;
        if (indexOfTrustedNetGrant(grants.items, record.name, record.provider) != null) continue;
        const name_copy = try allocator.dupe(u8, record.name);
        errdefer allocator.free(name_copy);
        const provider_copy = try allocator.dupe(u8, record.provider);
        errdefer allocator.free(provider_copy);
        try grants.append(allocator, .{
            .name = name_copy,
            .provider = provider_copy,
        });
    }
    return grants;
}

fn deinitTrustedNetGrants(allocator: std.mem.Allocator, grants: *std.ArrayList(TrustedNetGrant)) void {
    for (grants.items) |grant| {
        allocator.free(grant.name);
        allocator.free(grant.provider);
    }
    grants.deinit(allocator);
}

fn writeTrustedNetGrants(path: []const u8, grants: []const TrustedNetGrant) !void {
    if (std.fs.path.dirname(path)) |parent| {
        try std.fs.cwd().makePath(parent);
    }
    var file = try std.fs.createFileAbsolute(path, .{ .truncate = true, .mode = 0o600 });
    defer file.close();
    for (grants) |grant| {
        try file.writeAll(grant.name);
        try file.writeAll(" ");
        try file.writeAll(grant.provider);
        try file.writeAll("\n");
    }
}

const TrustedNetGrantLine = struct {
    name: []const u8,
    provider: []const u8,
};

fn parseTrustedNetGrantLine(line: []const u8) ?TrustedNetGrantLine {
    var fields = std.mem.tokenizeAny(u8, std.mem.trim(u8, line, " \t\r"), " \t\r");
    const name = fields.next() orelse return null;
    const provider = fields.next() orelse return null;
    if (fields.next() != null) return null;
    if (!plugin_manifest.isValidPluginName(name)) return null;
    if (!validNetProviderId(provider)) return null;
    return .{ .name = name, .provider = provider };
}

fn validNetProviderId(provider: []const u8) bool {
    if (provider.len == 0) return false;
    for (provider) |byte| {
        if (!(std.ascii.isAlphanumeric(byte) or byte == '.' or byte == '_' or byte == '-')) return false;
    }
    return true;
}

fn indexOfTrustedNetGrant(grants: []const TrustedNetGrant, name: []const u8, provider: []const u8) ?usize {
    for (grants, 0..) |grant, index| {
        if (std.mem.eql(u8, grant.name, name) and std.mem.eql(u8, grant.provider, provider)) return index;
    }
    return null;
}

fn lessThanTrustedNetGrant(_: void, lhs: TrustedNetGrant, rhs: TrustedNetGrant) bool {
    if (!std.mem.eql(u8, lhs.name, rhs.name)) return std.mem.lessThan(u8, lhs.name, rhs.name);
    return std.mem.lessThan(u8, lhs.provider, rhs.provider);
}

fn manifestCapabilityFingerprintAlloc(allocator: std.mem.Allocator, manifest: plugin_manifest.Manifest) ![]u8 {
    var canonical: std.ArrayList(u8) = .empty;
    defer canonical.deinit(allocator);

    try appendCapabilityStringList(allocator, &canonical, "fs_read", manifest.capabilities.fs_read);
    try appendCapabilityStringList(allocator, &canonical, "fs_watch", manifest.capabilities.fs_watch);
    try appendListCapability(allocator, &canonical, "exec", manifest.capabilities.exec);
    try appendListCapability(allocator, &canonical, "net", manifest.capabilities.net);
    try appendCapabilityBool(allocator, &canonical, "secrets", manifest.capabilities.secrets);
    try appendCapabilityStringList(allocator, &canonical, "env_read", manifest.capabilities.env_read);
    try appendCapabilityBool(allocator, &canonical, "pre_exec", manifest.capabilities.pre_exec);

    var digest: [std.crypto.hash.sha2.Sha256.digest_length]u8 = undefined;
    std.crypto.hash.sha2.Sha256.hash(canonical.items, &digest, .{});
    const hex = std.fmt.bytesToHex(digest, .lower);
    return std.fmt.allocPrint(allocator, "sha256:{s}", .{hex[0..]});
}

fn appendCapabilityStringList(allocator: std.mem.Allocator, out: *std.ArrayList(u8), label: []const u8, items: []const []const u8) !void {
    try cli_util.appendFmt(allocator, out, "{s}:list\n", .{label});
    const sorted = try allocator.dupe([]const u8, items);
    defer allocator.free(sorted);
    std.mem.sort([]const u8, sorted, {}, lessThanString);
    for (sorted) |item| try cli_util.appendFmt(allocator, out, "{s}\n", .{item});
}

fn appendListCapability(allocator: std.mem.Allocator, out: *std.ArrayList(u8), label: []const u8, capability: plugin_manifest.ListCapability) !void {
    switch (capability) {
        .deny => try cli_util.appendFmt(allocator, out, "{s}:deny\n", .{label}),
        .allow => |items| try appendCapabilityStringList(allocator, out, label, items),
    }
}

fn appendCapabilityBool(allocator: std.mem.Allocator, out: *std.ArrayList(u8), label: []const u8, value: bool) !void {
    try cli_util.appendFmt(allocator, out, "{s}:bool:{s}\n", .{ label, if (value) "true" else "false" });
}

fn trustedCapabilityFingerprintMatches(allocator: std.mem.Allocator, path: []const u8, name: []const u8, fingerprint: []const u8) !bool {
    const contents = std.fs.cwd().readFileAlloc(allocator, path, 1024 * 1024) catch |err| switch (err) {
        error.FileNotFound => return false,
        else => return err,
    };
    defer allocator.free(contents);

    var lines = std.mem.tokenizeScalar(u8, contents, '\n');
    while (lines.next()) |line| {
        const record = parseTrustedCapabilityLine(line) orelse continue;
        if (std.mem.eql(u8, record.name, name)) return std.mem.eql(u8, record.fingerprint, fingerprint);
    }
    return false;
}

fn setTrustedCapabilityFingerprint(allocator: std.mem.Allocator, path: []const u8, name: []const u8, fingerprint: []const u8) !void {
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);
    var replaced = false;

    const contents = std.fs.cwd().readFileAlloc(allocator, path, 1024 * 1024) catch |err| switch (err) {
        error.FileNotFound => null,
        else => return err,
    };
    defer if (contents) |text| allocator.free(text);

    if (contents) |text| {
        var lines = std.mem.tokenizeScalar(u8, text, '\n');
        while (lines.next()) |line| {
            const record = parseTrustedCapabilityLine(line) orelse continue;
            if (std.mem.eql(u8, record.name, name)) {
                if (replaced) continue;
                try cli_util.appendFmt(allocator, &out, "{s} {s}\n", .{ name, fingerprint });
                replaced = true;
            } else {
                try cli_util.appendFmt(allocator, &out, "{s} {s}\n", .{ record.name, record.fingerprint });
            }
        }
    }

    if (!replaced) try cli_util.appendFmt(allocator, &out, "{s} {s}\n", .{ name, fingerprint });
    if (std.fs.path.dirname(path)) |parent| {
        try std.fs.cwd().makePath(parent);
    }
    var file = try std.fs.createFileAbsolute(path, .{ .truncate = true, .mode = 0o600 });
    defer file.close();
    try file.writeAll(out.items);
}

const TrustedCapabilityLine = struct {
    name: []const u8,
    fingerprint: []const u8,
};

fn parseTrustedCapabilityLine(line: []const u8) ?TrustedCapabilityLine {
    var fields = std.mem.tokenizeAny(u8, std.mem.trim(u8, line, " \t\r"), " \t\r");
    const name = fields.next() orelse return null;
    const fingerprint = fields.next() orelse return null;
    if (fields.next() != null) return null;
    if (!plugin_manifest.isValidPluginName(name)) return null;
    if (!isValidCapabilityFingerprint(fingerprint)) return null;
    return .{ .name = name, .fingerprint = fingerprint };
}

fn isValidCapabilityFingerprint(fingerprint: []const u8) bool {
    const prefix = "sha256:";
    if (!std.mem.startsWith(u8, fingerprint, prefix)) return false;
    const hex = fingerprint[prefix.len..];
    if (hex.len != std.crypto.hash.sha2.Sha256.digest_length * 2) return false;
    for (hex) |byte| {
        if (!std.ascii.isHex(byte) or std.ascii.isUpper(byte)) return false;
    }
    return true;
}

fn readPluginNames(allocator: std.mem.Allocator, path: []const u8) !std.ArrayList([]u8) {
    var names: std.ArrayList([]u8) = .empty;
    const contents = std.fs.cwd().readFileAlloc(allocator, path, 1024 * 1024) catch |err| switch (err) {
        error.FileNotFound => return names,
        else => return err,
    };
    defer allocator.free(contents);

    var lines = std.mem.tokenizeScalar(u8, contents, '\n');
    while (lines.next()) |line| {
        const trimmed = std.mem.trim(u8, line, " \t\r");
        if (trimmed.len == 0 or !plugin_manifest.isValidPluginName(trimmed)) continue;
        if (indexOfString(names.items, trimmed) == null) {
            try names.append(allocator, try allocator.dupe(u8, trimmed));
        }
    }
    return names;
}

fn writePluginNames(path: []const u8, names: []const []const u8) !void {
    if (std.fs.path.dirname(path)) |parent| {
        try std.fs.cwd().makePath(parent);
    }

    var file = try std.fs.createFileAbsolute(path, .{ .truncate = true, .mode = 0o600 });
    defer file.close();
    for (names) |name| {
        try file.writeAll(name);
        try file.writeAll("\n");
    }
}

fn indexOfString(items: []const []const u8, name: []const u8) ?usize {
    for (items, 0..) |item, index| {
        if (std.mem.eql(u8, item, name)) return index;
    }
    return null;
}

fn lessThanString(_: void, lhs: []const u8, rhs: []const u8) bool {
    return std.mem.lessThan(u8, lhs, rhs);
}

test "plugin list reports enabled disabled and slow plugins" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-plugin-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};

    const plugins_dir = try std.fmt.allocPrint(allocator, "{s}/plugins", .{dir_path});
    defer allocator.free(plugins_dir);
    try std.fs.cwd().makePath(plugins_dir);
    const beta_path = try std.fmt.allocPrint(allocator, "{s}/beta", .{plugins_dir});
    defer allocator.free(beta_path);
    const alpha_path = try std.fmt.allocPrint(allocator, "{s}/alpha", .{plugins_dir});
    defer allocator.free(alpha_path);
    const slow_path = try std.fmt.allocPrint(allocator, "{s}/slow", .{plugins_dir});
    defer allocator.free(slow_path);
    const stuck_path = try std.fmt.allocPrint(allocator, "{s}/stuck", .{plugins_dir});
    defer allocator.free(stuck_path);
    const bad_path = try std.fmt.allocPrint(allocator, "{s}/Bad", .{plugins_dir});
    defer allocator.free(bad_path);
    try std.fs.cwd().makePath(beta_path);
    try std.fs.cwd().makePath(alpha_path);
    try std.fs.cwd().makePath(slow_path);
    try std.fs.cwd().makePath(stuck_path);
    try std.fs.cwd().makePath(bad_path);

    const disabled_path = try std.fmt.allocPrint(allocator, "{s}/plugins.disabled", .{dir_path});
    defer allocator.free(disabled_path);
    try setPluginDisabled(allocator, disabled_path, "beta", true);
    try setPluginDisabled(allocator, disabled_path, "stuck", true);
    const slow_strikes_path = try std.fmt.allocPrint(allocator, "{s}/plugins.slow-strikes", .{dir_path});
    defer allocator.free(slow_strikes_path);
    try std.fs.cwd().writeFile(.{
        .sub_path = slow_strikes_path,
        .data =
        \\slow 2
        \\stuck 3
        \\
        ,
    });
    const verified_path = try std.fmt.allocPrint(allocator, "{s}/plugins.verified", .{dir_path});
    defer allocator.free(verified_path);
    try writePluginNames(verified_path, &.{ "alpha", "stuck" });

    const output = try pluginListAlloc(allocator, plugins_dir, disabled_path, slow_strikes_path, verified_path);
    defer allocator.free(output);
    try std.testing.expectEqualStrings("alpha verified enabled\nbeta disabled\nslow slow-strikes=2/3\nstuck verified disabled slow-strikes=3/3\n", output);
}

test "parses plugin install args" {
    const config = try parsePluginInstallArgs(&.{ "https://example.com/plugin.git", "--yes", "--plugin-sandbox-strict", "--index", "/tmp/plugins.index.toml" });
    try std.testing.expectEqualStrings("https://example.com/plugin.git", config.url);
    try std.testing.expect(config.yes);
    try std.testing.expect(config.strict);
    try std.testing.expectEqualStrings("/tmp/plugins.index.toml", config.index_path.?);
    try std.testing.expectError(error.UnknownPluginArgument, parsePluginInstallArgs(&.{"--yes"}));
}

test "plugin search filters marketplace index" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-plugin-search-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    const index_path = try std.fmt.allocPrint(allocator, "{s}/plugins.index.toml", .{dir_path});
    defer allocator.free(index_path);
    try std.fs.cwd().writeFile(.{
        .sub_path = index_path,
        .data =
        \\[[plugins]]
        \\name = "git-tools"
        \\path = "examples/plugins/git"
        \\homepage = "https://example.com/git-tools"
        \\version = "0.1.0"
        \\capabilities = ["fs_read"]
        \\status = "community"
        \\description = "Git prompt helpers"
        \\
        \\[[plugins]]
        \\name = "cloud-risk"
        \\path = "examples/plugin-packs/cloud-safety"
        \\homepage = "https://example.com/cloud-risk"
        \\version = "0.2.0"
        \\capabilities = ["fs_read", "env_read"]
        \\status = "community"
        \\description = "Kubernetes and AWS risk"
        ,
    });

    const output = try pluginSearchPathAlloc(allocator, index_path, "git");
    defer allocator.free(output);
    try std.testing.expectEqualStrings("git-tools community 0.1.0 https://example.com/git-tools - Git prompt helpers [fs_read]\n", output);

    const config = try parsePluginSearchArgs(&.{ "risk", "--index", index_path });
    try std.testing.expectEqualStrings("risk", config.query);
    try std.testing.expectEqualStrings(index_path, config.index_path.?);

    const install_config = try parsePluginInstallArgs(&.{ "cloud-risk", "--index", index_path, "--yes" });
    const resolved_source = try pluginInstallSourceAlloc(allocator, install_config);
    defer resolved_source.deinit(allocator);
    try std.testing.expectEqual(.local_path, resolved_source.kind);
    try std.testing.expectEqualStrings("examples/plugin-packs/cloud-safety", resolved_source.value);
    try std.testing.expect(pluginInstallSourceNeedsMarketplace("cloud-risk"));
    try std.testing.expect(!pluginInstallSourceNeedsMarketplace("https://example.com/cloud-risk.git"));
}

test "checked-in marketplace index parses" {
    const allocator = std.testing.allocator;
    const source = try std.fs.cwd().readFileAlloc(allocator, "marketplace/index.toml", 64 * 1024);
    defer allocator.free(source);
    var parsed = try parseMarketplaceIndexAlloc(allocator, source);
    defer parsed.deinit(allocator);
    try std.testing.expectEqual(@as(usize, 1), parsed.plugins.len);
    try std.testing.expectEqualStrings("kubectx", parsed.plugins[0].name);

    const output = try pluginSearchAlloc(allocator, bundled_marketplace_index, "k8s");
    defer allocator.free(output);
    try std.testing.expect(std.mem.indexOf(u8, output, "kubectx community 0.1.0") != null);
}

test "plugin verify rejects direct shell execution" {
    try verifyPluginSourceStatic("return { name = \"ok\" }\n");
    try std.testing.expectError(error.PluginStaticAnalysisFailed, verifyPluginSourceStatic("os.execute('id')\n"));
    try std.testing.expectError(error.PluginStaticAnalysisFailed, verifyPluginSourceStatic("io.popen('id')\n"));
}

test "plugin new scaffolds valid strict manifest" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-plugin-new-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    try pluginNew(allocator, dir_path, "demo-plugin");

    const plugin_path = try std.fmt.allocPrint(allocator, "{s}/demo-plugin/plugin.lua", .{dir_path});
    defer allocator.free(plugin_path);
    const source = try std.fs.cwd().readFileAlloc(allocator, plugin_path, 16 * 1024);
    defer allocator.free(source);
    try std.testing.expect(std.mem.indexOf(u8, source, "name = \"demo-plugin\"") != null);
    try std.testing.expect(std.mem.indexOf(u8, source, "modules = { \"demo_plugin\" }") != null);
    try std.testing.expect(std.mem.indexOf(u8, source, "on_load = \"on_load\"") != null);

    const readme_path = try std.fmt.allocPrint(allocator, "{s}/demo-plugin/README.md", .{dir_path});
    defer allocator.free(readme_path);
    const readme = try std.fs.cwd().readFileAlloc(allocator, readme_path, 16 * 1024);
    defer allocator.free(readme);
    try std.testing.expect(std.mem.indexOf(u8, readme, "# demo-plugin") != null);
    const license_path = try std.fmt.allocPrint(allocator, "{s}/demo-plugin/LICENSE", .{dir_path});
    defer allocator.free(license_path);
    const license = try std.fs.cwd().readFileAlloc(allocator, license_path, 16 * 1024);
    defer allocator.free(license);
    try std.testing.expect(std.mem.indexOf(u8, license, "MIT License") != null);

    var runtime = plugin_lua.Runtime.initSandboxedWithOptions(allocator, .{ .require_root = dir_path }) catch |err| switch (err) {
        error.LuaUnavailable => return error.SkipZigTest,
        else => return err,
    };
    defer runtime.deinit();

    var loaded = try runtime.loadManifestStrict(source);
    defer loaded.deinit(allocator);
    try std.testing.expectEqualStrings("demo-plugin", loaded.manifest.name);
    try std.testing.expectEqualStrings("demo_plugin", loaded.manifest.modules[0]);
}

test "plugin new rejects invalid names" {
    try std.testing.expectError(error.InvalidPluginName, pluginNew(std.testing.allocator, "/tmp", "Bad"));
}

test "plugin lint validates strict manifest and reports warnings" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-plugin-lint-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    const manifest_path = try std.fmt.allocPrint(allocator, "{s}/plugin.lua", .{dir_path});
    defer allocator.free(manifest_path);
    try std.fs.cwd().writeFile(.{
        .sub_path = manifest_path,
        .data =
        \\return {
        \\  name = "linted",
        \\  version = "0.1.0",
        \\  api_version = 1,
        \\  license = "MIT",
        \\  capabilities = {
        \\    pre_exec = false,
        \\  },
        \\  modules = { "linted" },
        \\  pre_exec = "pre_exec",
        \\}
        ,
    });

    const output = pluginLintAlloc(allocator, dir_path) catch |err| switch (err) {
        error.LuaUnavailable => return error.SkipZigTest,
        else => return err,
    };
    defer allocator.free(output);
    try std.testing.expect(std.mem.indexOf(u8, output, "ok linted 0.1.0\n") != null);
    try std.testing.expect(std.mem.indexOf(u8, output, "warning: missing README.md\n") != null);
    try std.testing.expect(std.mem.indexOf(u8, output, "warning: missing LICENSE\n") != null);
    try std.testing.expect(std.mem.indexOf(u8, output, "warning: pre_exec hook without pre_exec capability\n") != null);
}

test "plugin lint accepts plugin.lua path" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-plugin-lint-file-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    const readme_path = try std.fmt.allocPrint(allocator, "{s}/README.md", .{dir_path});
    defer allocator.free(readme_path);
    try std.fs.cwd().writeFile(.{
        .sub_path = readme_path,
        .data = "# linted\n",
    });
    const license_path = try std.fmt.allocPrint(allocator, "{s}/LICENSE", .{dir_path});
    defer allocator.free(license_path);
    try std.fs.cwd().writeFile(.{
        .sub_path = license_path,
        .data = "MIT\n",
    });
    const manifest_path = try std.fmt.allocPrint(allocator, "{s}/plugin.lua", .{dir_path});
    defer allocator.free(manifest_path);
    try std.fs.cwd().writeFile(.{
        .sub_path = manifest_path,
        .data =
        \\return {
        \\  name = "linted-file",
        \\  version = "0.1.0",
        \\  api_version = 1,
        \\  license = "MIT",
        \\  modules = { "linted_file" },
        \\}
        ,
    });

    const output = pluginLintAlloc(allocator, manifest_path) catch |err| switch (err) {
        error.LuaUnavailable => return error.SkipZigTest,
        else => return err,
    };
    defer allocator.free(output);
    try std.testing.expectEqualStrings("ok linted-file 0.1.0\n", output);

    const doctor = try pluginDoctorAlloc(allocator, manifest_path);
    defer allocator.free(doctor);
    try std.testing.expectEqualStrings("doctor ok\nok linted-file 0.1.0\n", doctor);
}

test "plugin pack writes signed bundle" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-plugin-pack-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    try pluginNew(allocator, dir_path, "pack-plugin");
    const plugin_path = try std.fmt.allocPrint(allocator, "{s}/pack-plugin", .{dir_path});
    defer allocator.free(plugin_path);
    const bundle_path = pluginPack(allocator, plugin_path, dir_path) catch |err| switch (err) {
        error.LuaUnavailable => return error.SkipZigTest,
        else => return err,
    };
    defer allocator.free(bundle_path);
    try std.testing.expect(std.mem.endsWith(u8, bundle_path, "pack-plugin-0.1.0.shisa-plugin"));

    const bundle = try std.fs.cwd().readFileAlloc(allocator, bundle_path, 1024 * 1024);
    defer allocator.free(bundle);
    try std.testing.expect(std.mem.indexOf(u8, bundle, "plugin.lua") != null);
    try std.testing.expect(std.mem.indexOf(u8, bundle, "README.md") != null);
    try std.testing.expect(std.mem.indexOf(u8, bundle, "LICENSE") != null);
    try std.testing.expect(std.mem.indexOf(u8, bundle, "SHISA_PLUGIN_BUNDLE.json") != null);
    try std.testing.expect(std.mem.indexOf(u8, bundle, "\"algorithm\":\"Ed25519\"") != null);
    try std.testing.expect(std.mem.indexOf(u8, bundle, "\"signature\":\"") != null);
}

test "plugin enable disable is duplicate safe" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-plugin-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    const disabled_path = try std.fmt.allocPrint(allocator, "{s}/plugins.disabled", .{dir_path});
    defer allocator.free(disabled_path);
    try setPluginDisabled(allocator, disabled_path, "alpha", true);
    try setPluginDisabled(allocator, disabled_path, "alpha", true);
    try std.testing.expect(try pluginDisabled(allocator, disabled_path, "alpha"));
    try setPluginDisabled(allocator, disabled_path, "alpha", false);
    try std.testing.expect(!(try pluginDisabled(allocator, disabled_path, "alpha")));

    const contents = try std.fs.cwd().readFileAlloc(allocator, disabled_path, 4096);
    defer allocator.free(contents);
    try std.testing.expectEqualStrings("", contents);
}

test "plugin trust is duplicate safe" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-plugin-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    const trusted_path = try std.fmt.allocPrint(allocator, "{s}/plugins.trusted", .{dir_path});
    defer allocator.free(trusted_path);
    try setPluginTrusted(allocator, trusted_path, "alpha");
    try setPluginTrusted(allocator, trusted_path, "alpha");
    try std.testing.expect(try pluginTrusted(allocator, trusted_path, "alpha"));

    const contents = try std.fs.cwd().readFileAlloc(allocator, trusted_path, 4096);
    defer allocator.free(contents);
    try std.testing.expectEqualStrings("alpha\n", contents);
}

test "plugin trust args parse net provider" {
    const equals_config = try parsePluginTrustArgs(&.{ "shisa.example", "--net=remote" });
    try std.testing.expectEqualStrings("shisa.example", equals_config.name);
    try std.testing.expectEqualStrings("remote", equals_config.net.?);

    const spaced_config = try parsePluginTrustArgs(&.{ "shisa.example", "--net", "api.example.com" });
    try std.testing.expectEqualStrings("api.example.com", spaced_config.net.?);
}

test "plugin net trust is provider scoped" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-plugin-net-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    const trusted_path = try std.fmt.allocPrint(allocator, "{s}/plugins.trusted", .{dir_path});
    defer allocator.free(trusted_path);
    try setPluginTrusted(allocator, trusted_path, "shisa.example");
    try setPluginTrustedNet(allocator, trusted_path, "shisa.example", "remote");
    try setPluginTrustedNet(allocator, trusted_path, "shisa.example", "remote");
    try std.testing.expect(try pluginTrustedNet(allocator, trusted_path, "shisa.example", "remote"));
    try std.testing.expect(!(try pluginTrustedNet(allocator, trusted_path, "shisa.example", "other")));

    const contents_path = try trustedNetProvidersPathAlloc(allocator, trusted_path);
    defer allocator.free(contents_path);
    const contents = try std.fs.cwd().readFileAlloc(allocator, contents_path, 4096);
    defer allocator.free(contents);
    try std.testing.expectEqualStrings("shisa.example remote\n", contents);
}

test "plugin trust re-prompts on capability upgrade" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-plugin-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    const trusted_path = try std.fmt.allocPrint(allocator, "{s}/plugins.trusted", .{dir_path});
    defer allocator.free(trusted_path);
    const base = plugin_manifest.Manifest{
        .name = "alpha",
        .version = "1.0.0",
        .api_version = plugin_manifest.supported_api_version,
        .license = "MIT",
        .modules = &.{"alpha"},
    };
    const upgraded = plugin_manifest.Manifest{
        .name = "alpha",
        .version = "1.1.0",
        .api_version = plugin_manifest.supported_api_version,
        .license = "MIT",
        .capabilities = .{ .exec = .{ .allow = &.{"git"} } },
        .modules = &.{"alpha"},
    };

    try setPluginTrusted(allocator, trusted_path, "alpha");
    try std.testing.expect(!(try pluginTrustedForManifest(allocator, trusted_path, base)));
    try setPluginTrustedManifest(allocator, trusted_path, base);
    try std.testing.expect(try pluginTrustedForManifest(allocator, trusted_path, base));
    try std.testing.expect(!(try pluginTrustedForManifest(allocator, trusted_path, upgraded)));
    try setPluginTrustedManifest(allocator, trusted_path, upgraded);
    try std.testing.expect(try pluginTrustedForManifest(allocator, trusted_path, upgraded));
}

test "plugin net trust covers only matching net-only manifests" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-plugin-net-manifest-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    const trusted_path = try std.fmt.allocPrint(allocator, "{s}/plugins.trusted", .{dir_path});
    defer allocator.free(trusted_path);
    try setPluginTrusted(allocator, trusted_path, "shisa.example");
    try setPluginTrustedNet(allocator, trusted_path, "shisa.example", "remote");

    const net_only = plugin_manifest.Manifest{
        .name = "shisa.example",
        .version = "1.0.0",
        .api_version = plugin_manifest.supported_api_version,
        .license = "MIT",
        .capabilities = .{ .net = .{ .allow = &.{"remote"} } },
        .modules = &.{"example"},
    };
    const other_net = plugin_manifest.Manifest{
        .name = "shisa.example",
        .version = "1.0.0",
        .api_version = plugin_manifest.supported_api_version,
        .license = "MIT",
        .capabilities = .{ .net = .{ .allow = &.{"alt"} } },
        .modules = &.{"example"},
    };
    const net_plus_exec = plugin_manifest.Manifest{
        .name = "shisa.example",
        .version = "1.0.0",
        .api_version = plugin_manifest.supported_api_version,
        .license = "MIT",
        .capabilities = .{ .net = .{ .allow = &.{"remote"} }, .exec = .{ .allow = &.{"git"} } },
        .modules = &.{"example"},
    };

    try std.testing.expect(try pluginTrustedForManifest(allocator, trusted_path, net_only));
    try std.testing.expect(!(try pluginTrustedForManifest(allocator, trusted_path, other_net)));
    try std.testing.expect(!(try pluginTrustedForManifest(allocator, trusted_path, net_plus_exec)));
}

test "capability fingerprint is order independent" {
    const allocator = std.testing.allocator;
    const first = plugin_manifest.Manifest{
        .name = "alpha",
        .version = "1.0.0",
        .api_version = plugin_manifest.supported_api_version,
        .license = "MIT",
        .capabilities = .{
            .fs_read = &.{ "b", "a" },
            .exec = .{ .allow = &.{ "kubectl", "git" } },
            .env_read = &.{ "KUBECONFIG", "AWS_PROFILE" },
        },
        .modules = &.{"alpha"},
    };
    const second = plugin_manifest.Manifest{
        .name = "alpha",
        .version = "1.1.0",
        .api_version = plugin_manifest.supported_api_version,
        .license = "MIT",
        .capabilities = .{
            .fs_read = &.{ "a", "b" },
            .exec = .{ .allow = &.{ "git", "kubectl" } },
            .env_read = &.{ "AWS_PROFILE", "KUBECONFIG" },
        },
        .modules = &.{"alpha"},
    };

    const first_fingerprint = try manifestCapabilityFingerprintAlloc(allocator, first);
    defer allocator.free(first_fingerprint);
    const second_fingerprint = try manifestCapabilityFingerprintAlloc(allocator, second);
    defer allocator.free(second_fingerprint);
    try std.testing.expectEqualStrings(first_fingerprint, second_fingerprint);
}

test "plugin state rejects invalid names" {
    try std.testing.expectError(error.InvalidPluginName, setPluginDisabled(std.testing.allocator, "/tmp/shisa-plugin-invalid", "Bad", true));
    try std.testing.expectError(error.InvalidPluginName, setPluginTrusted(std.testing.allocator, "/tmp/shisa-plugin-invalid", "Bad"));
}
