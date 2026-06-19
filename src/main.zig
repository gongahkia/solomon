const std = @import("std");
const builtin = @import("builtin");
const daemon_cache = @import("daemon/cache.zig");
const dispatcher = @import("daemon/dispatcher.zig");
const fsnotify = @import("daemon/fsnotify.zig");
const client = @import("shisa-client.zig");
const cloud_ctx_module = @import("daemon/modules/cloud_ctx.zig");
const git_branch_module = @import("daemon/modules/git_branch.zig");
const language_versions_module = @import("daemon/modules/language_versions.zig");
const ai_explain = @import("ai/explain.zig");
const nextcmd = @import("ai/nextcmd.zig");
const nl2cmd = @import("ai/nl2cmd.zig");
const ollama = @import("ai/ollama.zig");
const ai_redact = @import("ai/redact.zig");
const ai_risk = @import("ai/risk.zig");
const shisa_config = @import("config.zig");
const paths = @import("daemon/paths.zig");
const proto = @import("proto/types.zig");
const plugin_lua = @import("plugin/lua.zig");
const plugin_manifest = @import("plugin/manifest.zig");
const prod_guard_module = @import("daemon/modules/prod_guard.zig");
const risk_tier_module = @import("daemon/modules/risk_tier.zig");
const supervisor = @import("supervisor.zig");
const theme_contrast = @import("theme/contrast.zig");
const theme_loader = @import("theme/loader.zig");
const vcs_stack = @import("vcs/stack.zig");
const vcs_worktree = @import("vcs_worktree");

const version = "0.1.0-dev";
const max_config_bytes = 1024 * 1024;
const max_vouches_bytes = 256 * 1024;
const plugin_slow_strike_limit: u8 = 3;

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
        try initConfig(allocator, args[2..]);
        return;
    }

    if (std.mem.eql(u8, args[1], "explain")) {
        try explainConfig(allocator, args[2..]);
        return;
    }

    if (std.mem.eql(u8, args[1], "doctor")) {
        try doctorCommand(allocator, args[2..]);
        return;
    }

    if (std.mem.eql(u8, args[1], "report")) {
        try reportCommand(allocator, args[2..]);
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

    if (std.mem.eql(u8, args[1], "ai")) {
        try aiCommand(allocator, args[2..]);
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
        try pluginCommand(allocator, args[2..]);
        return;
    }

    if (std.mem.eql(u8, args[1], "theme")) {
        try themeCommand(allocator, args[2..]);
        return;
    }

    if (std.mem.eql(u8, args[1], "stack")) {
        try stackCommand(allocator, args[2..]);
        return;
    }

    if (std.mem.eql(u8, args[1], "worktrees")) {
        try worktreesCommand(allocator, args[2..]);
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

fn initConfig(allocator: std.mem.Allocator, args: []const []const u8) !void {
    var a11y = false;
    for (args) |arg| {
        if (std.mem.eql(u8, arg, "--a11y")) {
            a11y = true;
        } else {
            return error.UnknownInitArgument;
        }
    }

    const path = try defaultConfigPath(allocator);
    defer allocator.free(path);
    if (std.fs.path.dirname(path)) |parent| {
        try std.fs.cwd().makePath(parent);
    }

    var file = try std.fs.createFileAbsolute(path, .{ .exclusive = true });
    defer file.close();
    try file.writeAll(if (a11y) shisa_config.a11y_config_text else shisa_config.default_config_text);

    const message = try std.fmt.allocPrint(allocator, "wrote {s}\n", .{path});
    defer allocator.free(message);
    try std.fs.File.stdout().writeAll(message);
}

fn defaultConfigPath(allocator: std.mem.Allocator) ![]u8 {
    const xdg = std.process.getEnvVarOwned(allocator, "XDG_CONFIG_HOME") catch |err| switch (err) {
        error.EnvironmentVariableNotFound => null,
        else => return err,
    };
    if (xdg) |xdg_config_home| {
        defer allocator.free(xdg_config_home);
        return defaultConfigPathFromEnv(allocator, xdg_config_home, null);
    }

    const home = try std.process.getEnvVarOwned(allocator, "HOME");
    defer allocator.free(home);
    return defaultConfigPathFromEnv(allocator, null, home);
}

fn themeCommand(allocator: std.mem.Allocator, args: []const []const u8) !void {
    if (args.len == 0 or std.mem.eql(u8, args[0], "--help") or std.mem.eql(u8, args[0], "-h")) {
        try std.fs.File.stdout().writeAll(theme_help_text);
        return;
    }
    if (std.mem.eql(u8, args[0], "validate")) {
        if (args.len != 2) return error.MissingThemePath;
        try themeValidateCommand(allocator, args[1]);
        return;
    }
    if (std.mem.eql(u8, args[0], "preview")) {
        if (args.len != 2) return error.MissingThemePath;
        try themePreviewCommand(allocator, args[1]);
        return;
    }
    if (std.mem.eql(u8, args[0], "gallery")) {
        try themeGalleryCommand(allocator, args[1..]);
        return;
    }
    return error.UnknownThemeCommand;
}

fn themeValidateCommand(allocator: std.mem.Allocator, path: []const u8) !void {
    const source = try std.fs.cwd().readFileAlloc(allocator, path, max_config_bytes);
    defer allocator.free(source);
    var diagnostic: theme_loader.Diagnostic = .{};
    var theme = theme_loader.parse(allocator, source, &diagnostic) catch |err| switch (err) {
        error.InvalidTheme => {
            const message = try std.fmt.allocPrint(allocator, "{s}:{d}:{d}: {s}\n", .{ path, diagnostic.line, diagnostic.column, diagnostic.message });
            defer allocator.free(message);
            try std.fs.File.stderr().writeAll(message);
            return err;
        },
        else => return err,
    };
    defer theme.deinit(allocator);
    const validation_failures = try theme_loader.validateAlloc(allocator, theme);
    defer allocator.free(validation_failures);
    if (validation_failures.len > 0) {
        const report = try theme_loader.formatValidationFailuresAlloc(allocator, validation_failures);
        defer allocator.free(report);
        try std.fs.File.stderr().writeAll(report);
        return error.InvalidTheme;
    }
    const failures = try theme_contrast.validateThemeContrastAlloc(allocator, source);
    defer allocator.free(failures);
    if (failures.len > 0) {
        const report = try theme_contrast.formatContrastFailuresAlloc(allocator, failures);
        defer allocator.free(report);
        try std.fs.File.stderr().writeAll(report);
        return error.ThemeContrastFailed;
    }
    try std.fs.File.stdout().writeAll("theme validate: ok\n");
}

fn themePreviewCommand(allocator: std.mem.Allocator, theme_arg: []const u8) !void {
    const path = try themePathAlloc(allocator, theme_arg);
    defer allocator.free(path);
    const source = try std.fs.cwd().readFileAlloc(allocator, path, max_config_bytes);
    defer allocator.free(source);
    var diagnostic: theme_loader.Diagnostic = .{};
    var theme = theme_loader.parse(allocator, source, &diagnostic) catch |err| switch (err) {
        error.InvalidTheme => {
            const message = try std.fmt.allocPrint(allocator, "{s}:{d}:{d}: {s}\n", .{ path, diagnostic.line, diagnostic.column, diagnostic.message });
            defer allocator.free(message);
            try std.fs.File.stderr().writeAll(message);
            return err;
        },
        else => return err,
    };
    defer theme.deinit(allocator);
    const validation_failures = try theme_loader.validateAlloc(allocator, theme);
    defer allocator.free(validation_failures);
    if (validation_failures.len > 0) {
        const report = try theme_loader.formatValidationFailuresAlloc(allocator, validation_failures);
        defer allocator.free(report);
        try std.fs.File.stderr().writeAll(report);
        return error.InvalidTheme;
    }

    const preview = try themePreviewAlloc(allocator, theme, 80);
    defer allocator.free(preview);
    try std.fs.File.stdout().writeAll(preview);
}

const built_in_theme_ids = [_][]const u8{
    "plain",
    "minimal-monochrome",
    "okiya-night",
    "okiya-day",
    "nord-dark",
    "gruvbox-rainbow",
    "tokyo-night",
    "pure",
    "a11y",
};

fn themePathAlloc(allocator: std.mem.Allocator, theme_arg: []const u8) ![]u8 {
    for (built_in_theme_ids) |id| {
        if (std.mem.eql(u8, theme_arg, id)) return std.fmt.allocPrint(allocator, "themes/{s}.toml", .{id});
    }
    return allocator.dupe(u8, theme_arg);
}

fn themePreviewAlloc(allocator: std.mem.Allocator, theme: theme_loader.Theme, cols: u16) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);

    if (theme.layout.lines.len == 0) {
        const left = try renderThemeSegmentListAlloc(allocator, theme, default_preview_segments[0..]);
        defer allocator.free(left);
        const line = try dispatcher.renderAlignedLineAlloc(allocator, left, "", cols);
        defer allocator.free(line);
        try out.appendSlice(allocator, line);
        try out.append(allocator, '\n');
    } else {
        for (theme.layout.lines) |layout_line| {
            const left = try renderThemeSegmentListAlloc(allocator, theme, layout_line.left);
            defer allocator.free(left);
            const right = try renderThemeSegmentListAlloc(allocator, theme, layout_line.right);
            defer allocator.free(right);
            const line = try dispatcher.renderAlignedLineAlloc(allocator, left, right, cols);
            defer allocator.free(line);
            try out.appendSlice(allocator, line);
            try out.append(allocator, '\n');
        }
    }

    return out.toOwnedSlice(allocator);
}

const default_preview_segments = [_][]const u8{ "cwd", "git_branch", "exit_status", "jobs", "cmd_duration" };

fn renderThemeSegmentListAlloc(allocator: std.mem.Allocator, theme: theme_loader.Theme, ids: anytype) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);
    for (ids, 0..) |id, index| {
        if (index > 0) try out.appendSlice(allocator, theme.separators.segment);
        const rendered = try renderThemeSegmentAlloc(allocator, theme, id);
        defer allocator.free(rendered);
        try out.appendSlice(allocator, rendered);
    }
    return out.toOwnedSlice(allocator);
}

fn renderThemeSegmentAlloc(allocator: std.mem.Allocator, theme: theme_loader.Theme, id: []const u8) ![]u8 {
    const segment = findThemeSegment(theme, id) orelse return allocator.dupe(u8, previewValue(id));
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);
    var styled = false;

    styled = try appendSegmentColorSgr(allocator, &out, theme, segment.fg, .foreground) or styled;
    styled = try appendSegmentColorSgr(allocator, &out, theme, segment.bg, .background) or styled;
    styled = try appendStyleSgr(&out, allocator, segment.style) or styled;

    try out.appendSlice(allocator, theme.separators.left);
    try out.appendSlice(allocator, segment.prefix);
    try out.appendSlice(allocator, theme_loader.resolveSegmentGlyph(segment, glyphTierForTheme(theme)));
    try out.appendSlice(allocator, previewValue(id));
    try out.appendSlice(allocator, segment.suffix);
    try out.appendSlice(allocator, theme.separators.right);
    if (styled) try out.appendSlice(allocator, "\x1b[0m");
    return out.toOwnedSlice(allocator);
}

fn appendSegmentColorSgr(allocator: std.mem.Allocator, out: *std.ArrayList(u8), theme: theme_loader.Theme, ref: []const u8, role: theme_contrast.ColorRole) !bool {
    if (ref.len == 0) return false;
    const rgb = theme_loader.resolvePaletteColor(theme, ref) orelse return false;
    const sgr = try theme_contrast.formatSgrColorAlloc(allocator, role, rgb, colorCapsForTheme(theme));
    defer allocator.free(sgr);
    if (sgr.len == 0) return false;
    try out.appendSlice(allocator, sgr);
    return true;
}

fn appendStyleSgr(out: *std.ArrayList(u8), allocator: std.mem.Allocator, style: []const u8) !bool {
    var wrote = false;
    var parts = std.mem.tokenizeAny(u8, style, " \t\r\n");
    while (parts.next()) |part| {
        if (std.mem.eql(u8, part, "bold")) {
            try out.appendSlice(allocator, "\x1b[1m");
            wrote = true;
        } else if (std.mem.eql(u8, part, "dim")) {
            try out.appendSlice(allocator, "\x1b[2m");
            wrote = true;
        } else if (std.mem.eql(u8, part, "italic")) {
            try out.appendSlice(allocator, "\x1b[3m");
            wrote = true;
        } else if (std.mem.eql(u8, part, "underline")) {
            try out.appendSlice(allocator, "\x1b[4m");
            wrote = true;
        }
    }
    return wrote;
}

fn findThemeSegment(theme: theme_loader.Theme, id: []const u8) ?theme_loader.Segment {
    for (theme.segments) |segment| {
        if (std.mem.eql(u8, segment.id, id)) return segment;
    }
    return null;
}

fn glyphTierForTheme(theme: theme_loader.Theme) theme_loader.GlyphTier {
    return switch (theme.capabilities.glyphs) {
        .nerd_font => .nerdfont,
        .ascii => .ascii,
    };
}

fn colorCapsForTheme(theme: theme_loader.Theme) theme_contrast.ColorCaps {
    return switch (theme.capabilities.color) {
        .truecolor => .truecolor,
        .ansi256 => .@"256",
        .ansi => .@"16",
        .none => .none,
    };
}

fn previewValue(id: []const u8) []const u8 {
    if (std.mem.eql(u8, id, "cwd")) return "~/work/shisa";
    if (std.mem.eql(u8, id, "git_branch")) return "main*";
    if (std.mem.eql(u8, id, "exit_status")) return "2";
    if (std.mem.eql(u8, id, "jobs")) return "2";
    if (std.mem.eql(u8, id, "cmd_duration")) return "1.5s";
    if (std.mem.eql(u8, id, "time")) return "14:32";
    if (std.mem.eql(u8, id, "language_versions")) return "zig:0.15";
    if (std.mem.eql(u8, id, "user_host")) return "dev@host";
    if (std.mem.eql(u8, id, "cloud_ctx")) return "cloud[aws:prod]";
    if (std.mem.eql(u8, id, "region_drift")) return "region[aws:us-west-2!=us-east-1]";
    if (std.mem.eql(u8, id, "cost_glance")) return "cost[aws:$1.20]";
    if (std.mem.eql(u8, id, "vpn_status")) return "vpn:corp";
    if (std.mem.eql(u8, id, "ssh_target")) return "-> prod";
    if (std.mem.eql(u8, id, "container_provenance")) return "docker:web";
    if (std.mem.eql(u8, id, "sso_expiry")) return "sso[op:20m]";
    if (std.mem.eql(u8, id, "iac_workspace")) return "tf:prod!";
    return id;
}

test "theme preview renders stub prompt" {
    const source =
        \\version = 1
        \\name = "preview"
        \\
        \\[palette]
        \\fg = "15"
        \\muted = "8"
        \\accent = "14"
        \\success = "10"
        \\warning = "11"
        \\danger = "9"
        \\
        \\[segments.cwd]
        \\fg = "@accent"
        \\style = "bold"
        \\
        \\[segments.git_branch]
        \\fg = "@success"
        \\ascii = "git:"
        \\
        \\[segments.exit_status]
        \\fg = "@danger"
        \\ascii = "exit:"
        \\
        \\[segments.jobs]
        \\fg = "@warning"
        \\ascii = "jobs:"
        \\
        \\[segments.cmd_duration]
        \\fg = "@muted"
        \\ascii = "took:"
        \\
    ;
    var diagnostic: theme_loader.Diagnostic = .{};
    var theme = try theme_loader.parse(std.testing.allocator, source, &diagnostic);
    defer theme.deinit(std.testing.allocator);
    const preview = try themePreviewAlloc(std.testing.allocator, theme, 80);
    defer std.testing.allocator.free(preview);

    try std.testing.expect(std.mem.indexOf(u8, preview, "~/work/shisa") != null);
    try std.testing.expect(std.mem.indexOf(u8, preview, "git:main*") != null);
    try std.testing.expect(std.mem.indexOf(u8, preview, "exit:2") != null);
    try std.testing.expect(std.mem.indexOf(u8, preview, "jobs:2") != null);
    try std.testing.expect(std.mem.indexOf(u8, preview, "took:1.5s") != null);
}

fn themeGalleryCommand(allocator: std.mem.Allocator, args: []const []const u8) !void {
    var open_browser = true;
    for (args) |arg| {
        if (std.mem.eql(u8, arg, "--no-open")) {
            open_browser = false;
        } else {
            return error.UnknownThemeArgument;
        }
    }

    const path = try writeThemeGalleryAlloc(allocator);
    defer allocator.free(path);
    if (open_browser) try openPathInBrowser(allocator, path);
    const message = try std.fmt.allocPrint(allocator, "theme gallery: {s}\n", .{path});
    defer allocator.free(message);
    try std.fs.File.stdout().writeAll(message);
}

fn writeThemeGalleryAlloc(allocator: std.mem.Allocator) ![]u8 {
    const out_dir = "zig-out/theme-gallery";
    try std.fs.cwd().makePath(out_dir);
    const html = try themeGalleryHtmlAlloc(allocator);
    defer allocator.free(html);
    const path = out_dir ++ "/index.html";
    var file = try std.fs.cwd().createFile(path, .{ .truncate = true });
    defer file.close();
    try file.writeAll(html);
    return allocator.dupe(u8, path);
}

fn themeGalleryHtmlAlloc(allocator: std.mem.Allocator) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);
    try out.appendSlice(allocator,
        \\<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
        \\<title>Shisa Theme Gallery</title><style>
        \\body{font:15px system-ui,sans-serif;margin:24px;background:#101216;color:#f2f4f8}
        \\main{max-width:1120px;margin:0 auto}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:14px}
        \\article{border:1px solid #303642;border-radius:8px;padding:14px;background:#171a21}
        \\h1{font-size:28px;margin:0 0 18px}h2{font-size:16px;margin:0 0 10px}
        \\pre{overflow:auto;margin:10px 0 0;padding:12px;background:#090b0f;border-radius:6px;color:#f8fafc}
        \\.swatches{display:flex;gap:6px}.swatch{width:24px;height:24px;border-radius:4px;border:1px solid rgba(255,255,255,.25)}
        \\</style></head><body><main><h1>Shisa Theme Gallery</h1><div class="grid">
    );
    for (built_in_theme_ids) |id| {
        const path = try themePathAlloc(allocator, id);
        defer allocator.free(path);
        const source = try std.fs.cwd().readFileAlloc(allocator, path, max_config_bytes);
        defer allocator.free(source);
        var diagnostic: theme_loader.Diagnostic = .{};
        var theme = try theme_loader.parse(allocator, source, &diagnostic);
        defer theme.deinit(allocator);
        const failures = try theme_loader.validateAlloc(allocator, theme);
        defer allocator.free(failures);
        if (failures.len > 0) return error.InvalidTheme;
        try appendThemeGalleryCard(allocator, &out, theme);
    }
    try out.appendSlice(allocator, "</div></main></body></html>\n");
    return out.toOwnedSlice(allocator);
}

fn appendThemeGalleryCard(allocator: std.mem.Allocator, out: *std.ArrayList(u8), theme: theme_loader.Theme) !void {
    const name = try htmlEscapeAlloc(allocator, theme.name);
    defer allocator.free(name);
    const preview = try themePreviewAlloc(allocator, theme, 80);
    defer allocator.free(preview);
    const plain_preview = try stripAnsiAlloc(allocator, preview);
    defer allocator.free(plain_preview);
    const escaped_preview = try htmlEscapeAlloc(allocator, plain_preview);
    defer allocator.free(escaped_preview);

    try appendFmt(allocator, out, "<article><h2>{s}</h2><div class=\"swatches\">", .{name});
    inline for (.{ "fg", "muted", "accent", "success", "warning", "danger" }) |slot| {
        if (theme_loader.resolvePaletteSlot(theme, slot)) |rgb| {
            try appendFmt(allocator, out, "<span class=\"swatch\" title=\"{s}\" style=\"background:rgb({d},{d},{d})\"></span>", .{ slot, rgb.r, rgb.g, rgb.b });
        }
    }
    try appendFmt(allocator, out, "</div><pre>{s}</pre></article>", .{escaped_preview});
}

fn htmlEscapeAlloc(allocator: std.mem.Allocator, value: []const u8) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);
    for (value) |byte| {
        switch (byte) {
            '&' => try out.appendSlice(allocator, "&amp;"),
            '<' => try out.appendSlice(allocator, "&lt;"),
            '>' => try out.appendSlice(allocator, "&gt;"),
            '"' => try out.appendSlice(allocator, "&quot;"),
            '\'' => try out.appendSlice(allocator, "&#39;"),
            else => try out.append(allocator, byte),
        }
    }
    return out.toOwnedSlice(allocator);
}

fn openPathInBrowser(allocator: std.mem.Allocator, path: []const u8) !void {
    switch (builtin.os.tag) {
        .macos => try runBrowserOpen(allocator, &.{ "open", path }),
        .linux, .freebsd, .openbsd, .netbsd => try runBrowserOpen(allocator, &.{ "xdg-open", path }),
        .windows => try runBrowserOpen(allocator, &.{ "cmd", "/C", "start", "", path }),
        else => return error.UnsupportedBrowserOpen,
    }
}

fn runBrowserOpen(allocator: std.mem.Allocator, argv: []const []const u8) !void {
    const result = try std.process.Child.run(.{
        .allocator = allocator,
        .argv = argv,
        .max_output_bytes = 4096,
    });
    defer allocator.free(result.stdout);
    defer allocator.free(result.stderr);
    if (!childExitedZero(result.term)) return error.OpenBrowserFailed;
}

fn childExitedZero(term: std.process.Child.Term) bool {
    return switch (term) {
        .Exited => |code| code == 0,
        else => false,
    };
}

test "theme gallery html lists built-in previews" {
    const html = try themeGalleryHtmlAlloc(std.testing.allocator);
    defer std.testing.allocator.free(html);
    try std.testing.expect(std.mem.indexOf(u8, html, "Shisa Theme Gallery") != null);
    try std.testing.expect(std.mem.indexOf(u8, html, "<h2>plain</h2>") != null);
    try std.testing.expect(std.mem.indexOf(u8, html, "~/work/shisa") != null);
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

fn defaultConfigPathFromEnv(allocator: std.mem.Allocator, xdg_config_home: ?[]const u8, home: ?[]const u8) ![]u8 {
    if (xdg_config_home) |base| return std.fmt.allocPrint(allocator, "{s}/shisa/shisa.toml", .{base});
    if (home) |base| return std.fmt.allocPrint(allocator, "{s}/.config/shisa/shisa.toml", .{base});
    return error.MissingHome;
}

test "default config path prefers xdg" {
    const path = try defaultConfigPathFromEnv(std.testing.allocator, "/tmp/xdg", "/tmp/home");
    defer std.testing.allocator.free(path);
    try std.testing.expectEqualStrings("/tmp/xdg/shisa/shisa.toml", path);
}

test "default config path falls back to home" {
    const path = try defaultConfigPathFromEnv(std.testing.allocator, null, "/tmp/home");
    defer std.testing.allocator.free(path);
    try std.testing.expectEqualStrings("/tmp/home/.config/shisa/shisa.toml", path);
}

fn explainConfig(allocator: std.mem.Allocator, args: []const []const u8) !void {
    if (args.len != 0) return error.UnknownExplainArgument;

    const path = try defaultConfigPath(allocator);
    defer allocator.free(path);
    const source = try readConfigOrDefault(allocator, path);
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

    const output = try explainAlloc(allocator, parsed);
    defer allocator.free(output);
    try std.fs.File.stdout().writeAll(output);
}

fn readConfigOrDefault(allocator: std.mem.Allocator, path: []const u8) ![]u8 {
    var file = std.fs.openFileAbsolute(path, .{}) catch |err| switch (err) {
        error.FileNotFound => return allocator.dupe(u8, shisa_config.default_config_text),
        else => return err,
    };
    defer file.close();
    return file.readToEndAlloc(allocator, max_config_bytes);
}

fn explainAlloc(allocator: std.mem.Allocator, parsed: shisa_config.Config) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);

    try appendFmt(allocator, &out, "theme: {s}\n", .{parsed.theme});
    try out.appendSlice(allocator, "pipeline:\n");
    for (parsed.prompt_modules, 0..) |module_id, index| {
        try appendFmt(
            allocator,
            &out,
            "  {d}. {s} ({s})\n",
            .{ index + 1, shisa_config.moduleIdName(module_id), shisa_config.moduleExecutionClass(module_id) },
        );
    }

    return try out.toOwnedSlice(allocator);
}

fn appendFmt(allocator: std.mem.Allocator, out: *std.ArrayList(u8), comptime format: []const u8, args: anytype) !void {
    const line = try std.fmt.allocPrint(allocator, format, args);
    defer allocator.free(line);
    try out.appendSlice(allocator, line);
}

test "explain output dumps pipeline" {
    var diagnostic: shisa_config.Diagnostic = .{};
    var parsed = try shisa_config.parse(std.testing.allocator, shisa_config.default_config_text, &diagnostic);
    defer parsed.deinit(std.testing.allocator);

    const output = try explainAlloc(std.testing.allocator, parsed);
    defer std.testing.allocator.free(output);

    try std.testing.expect(std.mem.indexOf(u8, output, "theme: plain\n") != null);
    try std.testing.expect(std.mem.indexOf(u8, output, "1. cwd (sync)") != null);
    try std.testing.expect(std.mem.indexOf(u8, output, "2. git_branch (async)") != null);
}

const DoctorConfig = struct {
    socket_path: ?[]const u8 = null,
};

const DeprecationRule = struct {
    kind: []const u8,
    pattern: []const u8,
    replacement: []const u8,
    since: []const u8,
    remove_before: []const u8,
};

const active_deprecation_rules = [_]DeprecationRule{};

fn doctorCommand(allocator: std.mem.Allocator, args: []const []const u8) !void {
    const config = try parseDoctorArgs(args);
    const socket_path = if (config.socket_path) |path| path else try paths.defaultSocketPath(allocator);
    defer if (config.socket_path == null) allocator.free(socket_path);

    const output = try doctorOutputAlloc(allocator, socket_path);
    defer allocator.free(output);
    try std.fs.File.stdout().writeAll(output);
}

fn parseDoctorArgs(args: []const []const u8) !DoctorConfig {
    var config = DoctorConfig{};
    var i: usize = 0;
    while (i < args.len) : (i += 1) {
        if (std.mem.eql(u8, args[i], "--socket")) {
            config.socket_path = try nextValue(args, &i);
        } else {
            return error.UnknownDoctorArgument;
        }
    }
    return config;
}

fn doctorOutputAlloc(allocator: std.mem.Allocator, socket_path: []const u8) ![]u8 {
    const config_path = try defaultConfigPath(allocator);
    defer allocator.free(config_path);
    const config_dir = try configDirPath(allocator);
    defer allocator.free(config_dir);
    const plugins_dir = try pluginsDirPath(allocator);
    defer allocator.free(plugins_dir);

    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);

    try appendFmt(allocator, &out, "socket: {s} {s}\n", .{ pathAccessStatus(socket_path), socket_path });
    try appendFmt(allocator, &out, "daemon: {s}\n", .{try daemonHealthStatus(allocator, socket_path)});
    try appendFmt(allocator, &out, "config_dir: {s} {s}\n", .{ pathAccessStatus(config_dir), config_dir });
    try appendFmt(allocator, &out, "plugins_dir: {s} {s}\n", .{ pathAccessStatus(plugins_dir), plugins_dir });
    try appendFmt(allocator, &out, "lua: {s}\n", .{luaRuntimeStatus(allocator)});
    try appendFmt(allocator, &out, "fsnotify: {s}\n", .{fsnotifyBackendName(fsnotify.selectBackend(builtin.os.tag))});
    try appendDoctorDeprecations(allocator, &out, config_path);

    if (builtin.os.tag == .linux) {
        const limit = fsnotify.readLinuxMaxUserWatches(allocator) catch null;
        if (limit) |value| {
            try appendFmt(allocator, &out, "inotify.max_user_watches: {d}\n", .{value});
        } else {
            try out.appendSlice(allocator, "inotify.max_user_watches: unknown\n");
        }
    }

    return out.toOwnedSlice(allocator);
}

fn appendDoctorDeprecations(allocator: std.mem.Allocator, out: *std.ArrayList(u8), config_path: []const u8) !void {
    const source = readConfigOrDefault(allocator, config_path) catch |err| {
        try appendFmt(allocator, out, "deprecations: unreadable ({s})\n", .{@errorName(err)});
        return;
    };
    defer allocator.free(source);

    const warnings = try deprecationWarningsAlloc(allocator, source, active_deprecation_rules[0..]);
    defer allocator.free(warnings);
    try out.appendSlice(allocator, warnings);
}

fn deprecationWarningsAlloc(allocator: std.mem.Allocator, source: []const u8, rules: []const DeprecationRule) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    var count: usize = 0;
    for (rules) |rule| {
        if (std.mem.indexOf(u8, source, rule.pattern) == null) continue;
        try appendFmt(
            allocator,
            &out,
            "deprecation: {s} `{s}` deprecated since {s}; use `{s}`; remove before {s}\n",
            .{ rule.kind, rule.pattern, rule.since, rule.replacement, rule.remove_before },
        );
        count += 1;
    }
    if (count == 0) try out.appendSlice(allocator, "deprecations: none\n");
    return out.toOwnedSlice(allocator);
}

const report_max_log_bytes = 1024 * 1024;
const report_bench_iterations = 8;

const ReportConfig = struct {
    output_path: ?[]const u8 = null,
};

fn reportCommand(allocator: std.mem.Allocator, args: []const []const u8) !void {
    if (args.len == 1 and (std.mem.eql(u8, args[0], "--help") or std.mem.eql(u8, args[0], "-h"))) {
        try std.fs.File.stdout().writeAll(report_help_text);
        return;
    }

    const config = try parseReportArgs(args);
    const output_path = if (config.output_path) |path| path else try defaultReportPathAlloc(allocator);
    defer if (config.output_path == null) allocator.free(output_path);

    const staging_dir = try reportStagingDirAlloc(allocator);
    defer allocator.free(staging_dir);
    defer std.fs.cwd().deleteTree(staging_dir) catch {};
    try std.fs.cwd().makePath(staging_dir);

    try writeReportBundleFiles(allocator, staging_dir);
    try createReportArchive(allocator, staging_dir, output_path);

    const message = try std.fmt.allocPrint(allocator, "wrote {s}\n", .{output_path});
    defer allocator.free(message);
    try std.fs.File.stdout().writeAll(message);
}

fn parseReportArgs(args: []const []const u8) !ReportConfig {
    var config = ReportConfig{};
    var i: usize = 0;
    while (i < args.len) : (i += 1) {
        if (std.mem.eql(u8, args[i], "--output") or std.mem.eql(u8, args[i], "-o")) {
            config.output_path = try nextValue(args, &i);
        } else {
            return error.UnknownReportArgument;
        }
    }
    return config;
}

fn defaultReportPathAlloc(allocator: std.mem.Allocator) ![]u8 {
    return std.fmt.allocPrint(allocator, "shisa-report-{d}.tar.gz", .{std.time.timestamp()});
}

fn reportStagingDirAlloc(allocator: std.mem.Allocator) ![]u8 {
    return std.fmt.allocPrint(allocator, "/tmp/shisa-report-{x}", .{std.crypto.random.int(u64)});
}

fn writeReportBundleFiles(allocator: std.mem.Allocator, staging_dir: []const u8) !void {
    const config_path = try defaultConfigPath(allocator);
    defer allocator.free(config_path);
    const log_path = try paths.defaultLogPath(allocator);
    defer allocator.free(log_path);

    const manifest = try reportManifestAlloc(allocator, config_path, log_path);
    defer allocator.free(manifest);
    try writeReportFile(allocator, staging_dir, "README.txt", manifest);

    const config_text = try reportConfigRedactedAlloc(allocator, config_path);
    defer allocator.free(config_text);
    try writeReportFile(allocator, staging_dir, "config.redacted.toml", config_text);

    const log_text = try reportLogRedactedAlloc(allocator, log_path);
    defer allocator.free(log_text);
    try writeReportFile(allocator, staging_dir, "shisad.log.redacted", log_text);

    const bench_text = try reportBenchAlloc(allocator);
    defer allocator.free(bench_text);
    try writeReportFile(allocator, staging_dir, "bench.txt", bench_text);
}

fn reportManifestAlloc(allocator: std.mem.Allocator, config_path: []const u8, log_path: []const u8) ![]u8 {
    return std.fmt.allocPrint(allocator,
        \\Shisa support bundle
        \\
        \\Files:
        \\- config.redacted.toml: active config from {s}, or built-in defaults when missing
        \\- shisad.log.redacted: last 1MiB of {s}, or missing/unreadable status
        \\- bench.txt: local prompt payload microbench metadata
        \\
        \\Redaction:
        \\Values matching documented secret patterns are replaced with [redacted] before archive creation.
        \\
    , .{ config_path, log_path });
}

fn reportConfigRedactedAlloc(allocator: std.mem.Allocator, config_path: []const u8) ![]u8 {
    const raw = try readConfigOrDefault(allocator, config_path);
    defer allocator.free(raw);
    return redactReportDataAlloc(allocator, raw);
}

fn reportLogRedactedAlloc(allocator: std.mem.Allocator, log_path: []const u8) ![]u8 {
    const raw = readFileTailAlloc(allocator, log_path, report_max_log_bytes) catch |err| switch (err) {
        error.FileNotFound => return std.fmt.allocPrint(allocator, "log_path: {s}\nstatus: missing\n", .{log_path}),
        else => return std.fmt.allocPrint(allocator, "log_path: {s}\nstatus: unreadable\nerror: {s}\n", .{ log_path, @errorName(err) }),
    };
    defer allocator.free(raw);
    return redactReportDataAlloc(allocator, raw);
}

fn redactReportDataAlloc(allocator: std.mem.Allocator, data: []const u8) ![]u8 {
    return ai_redact.redactAlloc(allocator, data);
}

fn readFileTailAlloc(allocator: std.mem.Allocator, path: []const u8, max_bytes: usize) ![]u8 {
    var file = try std.fs.openFileAbsolute(path, .{});
    defer file.close();
    const end = try file.getEndPos();
    const start = if (end > max_bytes) end - max_bytes else 0;
    try file.seekTo(start);
    return file.readToEndAlloc(allocator, max_bytes);
}

fn reportBenchAlloc(allocator: std.mem.Allocator) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);
    try appendFmt(allocator, &out, "version: {s}\n", .{version});
    try appendFmt(allocator, &out, "os: {s}\n", .{@tagName(builtin.os.tag)});
    try appendFmt(allocator, &out, "iterations: {d}\n", .{report_bench_iterations});

    const cwd = std.fs.cwd().realpathAlloc(allocator, ".") catch |err| {
        try appendFmt(allocator, &out, "status: failed\nerror: {s}\n", .{@errorName(err)});
        return out.toOwnedSlice(allocator);
    };
    defer allocator.free(cwd);

    var total_ns: u64 = 0;
    var min_ns: u64 = std.math.maxInt(u64);
    var max_ns: u64 = 0;
    const config = PromptConfig{ .no_async = true, .cols = 80, .rows = 24 };
    const module_options = defaultPromptModuleOptions();
    for (0..report_bench_iterations) |_| {
        const start = std.time.nanoTimestamp();
        const payload = buildPromptPayloadWithModuleOptions(allocator, config, cwd, module_options) catch |err| {
            try appendFmt(allocator, &out, "status: failed\nerror: {s}\n", .{@errorName(err)});
            return out.toOwnedSlice(allocator);
        };
        defer allocator.free(payload);
        const elapsed: u64 = @intCast(std.time.nanoTimestamp() - start);
        total_ns += elapsed;
        min_ns = @min(min_ns, elapsed);
        max_ns = @max(max_ns, elapsed);
    }
    try out.appendSlice(allocator, "status: ok\n");
    try appendFmt(allocator, &out, "avg_ns: {d}\n", .{total_ns / report_bench_iterations});
    try appendFmt(allocator, &out, "min_ns: {d}\n", .{min_ns});
    try appendFmt(allocator, &out, "max_ns: {d}\n", .{max_ns});
    return out.toOwnedSlice(allocator);
}

fn writeReportFile(allocator: std.mem.Allocator, staging_dir: []const u8, name: []const u8, data: []const u8) !void {
    const path = try std.fs.path.join(allocator, &.{ staging_dir, name });
    defer allocator.free(path);
    var file = try std.fs.createFileAbsolute(path, .{ .truncate = true });
    defer file.close();
    try file.writeAll(data);
}

fn createReportArchive(allocator: std.mem.Allocator, staging_dir: []const u8, output_path: []const u8) !void {
    const result = std.process.Child.run(.{
        .allocator = allocator,
        .argv = &.{ "tar", "-czf", output_path, "-C", staging_dir, "." },
        .max_output_bytes = 1024 * 1024,
        .expand_arg0 = .expand,
    }) catch |err| switch (err) {
        error.FileNotFound => {
            try std.fs.File.stderr().writeAll("shisa report: tar not found in PATH\n");
            return err;
        },
        else => return err,
    };
    defer allocator.free(result.stdout);
    defer allocator.free(result.stderr);
    try std.fs.File.stderr().writeAll(result.stderr);
    if (!exitedZero(result.term)) return error.ReportArchiveFailed;
}

test "report args parse output path" {
    const config = try parseReportArgs(&.{ "--output", "/tmp/shisa-report.tar.gz" });
    try std.testing.expectEqualStrings("/tmp/shisa-report.tar.gz", config.output_path.?);
}

test "report redaction scrubs documented patterns" {
    const input =
        \\password = "hunter2"
        \\Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig
        \\AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE
        \\aws_secret_access_key = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
        \\github=ghp_abcdefghijklmnopqrstuvwxyz1234567890
        \\openai=sk-abcdefghijklmnopqrst
        \\account=123456789012
        \\IdentityFile ~/.ssh/id_rsa
        \\client-key-data: kube-secret
        \\-----BEGIN OPENSSH PRIVATE KEY-----
        \\abc123
        \\-----END OPENSSH PRIVATE KEY-----
        \\
    ;
    const output = try redactReportDataAlloc(std.testing.allocator, input);
    defer std.testing.allocator.free(output);

    inline for (.{
        "hunter2",
        "eyJhbGciOiJIUzI1NiJ9.payload.sig",
        "AKIAIOSFODNN7EXAMPLE",
        "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        "ghp_abcdefghijklmnopqrstuvwxyz1234567890",
        "sk-abcdefghijklmnopqrst",
        "123456789012",
        "~/.ssh/id_rsa",
        "kube-secret",
        "abc123",
    }) |secret| {
        try std.testing.expect(std.mem.indexOf(u8, output, secret) == null);
    }
    try std.testing.expect(std.mem.indexOf(u8, output, ai_redact.marker) != null);
}

fn configDirPath(allocator: std.mem.Allocator) ![]u8 {
    const config_path = try defaultConfigPath(allocator);
    defer allocator.free(config_path);
    const dir = std.fs.path.dirname(config_path) orelse return error.MissingConfigDir;
    return allocator.dupe(u8, dir);
}

fn pathAccessStatus(path: []const u8) []const u8 {
    std.fs.cwd().access(path, .{}) catch |err| switch (err) {
        error.FileNotFound => return "missing",
        error.AccessDenied => return "denied",
        else => return "error",
    };
    return "present";
}

fn daemonHealthStatus(allocator: std.mem.Allocator, socket_path: []const u8) ![]const u8 {
    const response = client.requestAlloc(allocator, socket_path, "health\n") catch return "unreachable";
    defer allocator.free(response);
    const trimmed = std.mem.trim(u8, response, " \t\r\n");
    if (std.mem.eql(u8, trimmed, "ok")) return "ok";
    return "bad-response";
}

fn luaRuntimeStatus(allocator: std.mem.Allocator) []const u8 {
    var runtime = plugin_lua.Runtime.initSandboxed(allocator) catch |err| switch (err) {
        error.LuaUnavailable => return "unavailable",
        else => return "error",
    };
    runtime.deinit();
    return "available";
}

fn fsnotifyBackendName(backend: fsnotify.Backend) []const u8 {
    return switch (backend) {
        .fsevents => "fsevents",
        .inotify => "inotify",
        .unsupported => "unsupported",
    };
}

test "doctor args parse socket override" {
    const config = try parseDoctorArgs(&.{ "--socket", "/tmp/shisa.sock" });
    try std.testing.expectEqualStrings("/tmp/shisa.sock", config.socket_path.?);
}

test "doctor reports path and backend statuses" {
    try std.testing.expectEqualStrings("missing", pathAccessStatus("/tmp/shisa-doctor-missing"));
    try std.testing.expectEqualStrings("fsevents", fsnotifyBackendName(.fsevents));
    try std.testing.expectEqualStrings("inotify", fsnotifyBackendName(.inotify));
}

test "doctor deprecation scanner reports matching rules" {
    const rules = [_]DeprecationRule{.{
        .kind = "config",
        .pattern = "old_key",
        .replacement = "new_key",
        .since = "1.4.0",
        .remove_before = "2.0.0",
    }};
    const output = try deprecationWarningsAlloc(std.testing.allocator, "old_key = true\n", rules[0..]);
    defer std.testing.allocator.free(output);
    try std.testing.expect(std.mem.indexOf(u8, output, "deprecation: config `old_key` deprecated since 1.4.0") != null);
}

test "doctor deprecation scanner reports none" {
    const rules = [_]DeprecationRule{.{
        .kind = "config",
        .pattern = "old_key",
        .replacement = "new_key",
        .since = "1.4.0",
        .remove_before = "2.0.0",
    }};
    const output = try deprecationWarningsAlloc(std.testing.allocator, "new_key = true\n", rules[0..]);
    defer std.testing.allocator.free(output);
    try std.testing.expectEqualStrings("deprecations: none\n", output);
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
    try appendFmt(allocator, &out, "aws_profile: {s}\n", .{aws_profile orelse "-"});

    const gcp_path = try cloud_ctx_module.gcpConfigPathAlloc(allocator, home);
    defer if (gcp_path) |value| allocator.free(value);
    try appendCloudPathLine(allocator, &out, "gcp_config", gcp_path);
    const gcp_project = try cache.gcpProjectAlloc(allocator, home);
    defer if (gcp_project) |value| allocator.free(value);
    try appendFmt(allocator, &out, "gcp_project: {s}\n", .{gcp_project orelse "-"});

    const azure_path = try cloud_ctx_module.azureProfilePathAlloc(allocator, home);
    defer if (azure_path) |value| allocator.free(value);
    try appendCloudPathLine(allocator, &out, "azure_profile", azure_path);
    const azure_subscription = try cache.azureSubscriptionAlloc(allocator, home);
    defer if (azure_subscription) |value| allocator.free(value);
    try appendFmt(allocator, &out, "azure_subscription: {s}\n", .{azure_subscription orelse "-"});

    const kube_path = try cloud_ctx_module.kubeConfigPathAlloc(allocator, kubeconfig_env, home);
    defer if (kube_path) |value| allocator.free(value);
    try appendCloudPathLine(allocator, &out, "kubeconfig", kube_path);
    const kube_context = try cache.kubeContextAlloc(allocator, kubeconfig_env, home);
    defer if (kube_context) |value| allocator.free(value);
    try appendFmt(allocator, &out, "kube_context: {s}\n", .{kube_context orelse "-"});

    return out.toOwnedSlice(allocator);
}

fn appendCloudPathLine(allocator: std.mem.Allocator, out: *std.ArrayList(u8), label: []const u8, path: ?[]const u8) !void {
    if (path) |value| {
        try appendFmt(allocator, out, "{s}: {s} {s}\n", .{ label, pathAccessStatus(value), value });
    } else {
        try appendFmt(allocator, out, "{s}: missing\n", .{label});
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
    const path = try prodGuardAuditPathAlloc(allocator, home);
    defer allocator.free(path);
    return std.fs.cwd().readFileAlloc(allocator, path, max_config_bytes) catch |err| switch (err) {
        error.FileNotFound => try allocator.dupe(u8, ""),
        else => return err,
    };
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
            parsed.socket_path = try nextValue(args, &i);
        } else if (std.mem.eql(u8, arg, "--shell")) {
            parsed.shell = try nextValue(args, &i);
        } else if (std.mem.eql(u8, arg, "--force")) {
            parsed.force = true;
        } else if (std.mem.eql(u8, arg, "--")) {
            parsed.command = try nextValue(args, &i);
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
    const escaped_cwd = try jsonEscapeAlloc(allocator, cwd);
    defer allocator.free(escaped_cwd);
    const escaped_shell = try jsonEscapeAlloc(allocator, config.shell);
    defer allocator.free(escaped_shell);
    const escaped_command = try jsonEscapeAlloc(allocator, config.command);
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

    const path = try prodGuardAuditPathAlloc(allocator, dir_path);
    defer allocator.free(path);
    if (std.fs.path.dirname(path)) |parent| try std.fs.cwd().makePath(parent);
    {
        var file = try std.fs.createFileAbsolute(path, .{});
        defer file.close();
        try file.writeAll("{\"tier\":\"prod\"}\n");
    }

    const output = try cloudAuditAlloc(allocator, dir_path);
    defer allocator.free(output);
    try std.testing.expectEqualStrings("{\"tier\":\"prod\"}\n", output);
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

const AiBenchConfig = struct {
    model: []const u8 = ollama.recommended_model,
    prompt: []const u8 = "Reply with one short sentence.",
    cold: bool = false,
    warm: bool = false,
    memory: bool = false,
    all_supported: bool = false,

    fn hasExplicitMode(self: AiBenchConfig) bool {
        return self.cold or self.warm or self.memory;
    }

    fn runCold(self: AiBenchConfig) bool {
        return self.cold or !self.hasExplicitMode();
    }

    fn runWarm(self: AiBenchConfig) bool {
        return self.warm or !self.hasExplicitMode();
    }

    fn runMemory(self: AiBenchConfig) bool {
        return self.memory or !self.hasExplicitMode();
    }
};

fn aiCommand(allocator: std.mem.Allocator, args: []const []const u8) !void {
    if (args.len == 0 or (args.len == 1 and (std.mem.eql(u8, args[0], "--help") or std.mem.eql(u8, args[0], "-h")))) {
        try std.fs.File.stdout().writeAll(ai_help_text);
        return;
    }
    if (std.mem.eql(u8, args[0], "status")) {
        if (args.len != 1) return error.UnknownAiArgument;
        try aiStatus(allocator);
        return;
    }
    if (std.mem.eql(u8, args[0], "redact")) {
        try aiRedact(allocator, args[1..]);
        return;
    }
    if (args.len >= 1 and std.mem.eql(u8, args[0], "bench")) {
        const config = try parseAiBenchArgs(args[1..]);
        try aiBench(allocator, config);
        return;
    }
    if (args.len >= 1 and std.mem.eql(u8, args[0], "risk")) {
        const config = try parseAiRiskArgs(args[1..]);
        try aiRisk(allocator, config);
        return;
    }
    if (args.len >= 1 and std.mem.eql(u8, args[0], "explain")) {
        const config = try parseAiExplainArgs(args[1..]);
        try aiExplain(allocator, config);
        return;
    }
    if (args.len >= 1 and std.mem.eql(u8, args[0], "nextcmd")) {
        const config = try parseAiNextcmdArgs(args[1..]);
        try aiNextcmd(allocator, config);
        return;
    }
    if (args.len >= 1 and std.mem.eql(u8, args[0], "nl2cmd")) {
        const config = try parseAiNl2cmdArgs(args[1..]);
        try aiNl2cmd(allocator, config);
        return;
    }
    return error.UnknownAiArgument;
}

fn aiStatus(allocator: std.mem.Allocator) !void {
    const status = ollama.detect(allocator) catch ollama.Status{ .installed = false, .daemon_running = false };
    const home = std.process.getEnvVarOwned(allocator, "HOME") catch |err| switch (err) {
        error.EnvironmentVariableNotFound => null,
        else => return err,
    };
    defer if (home) |value| allocator.free(value);
    const output = try aiStatusOutputAlloc(allocator, status, home);
    defer allocator.free(output);
    try std.fs.File.stdout().writeAll(output);
}

const AiRedactMode = union(enum) {
    @"test": []const u8,
    add_literal: []const u8,
};

const AiRedactConfig = struct {
    mode: AiRedactMode,
    rules_path: ?[]const u8 = null,
};

fn aiRedact(allocator: std.mem.Allocator, args: []const []const u8) !void {
    if (args.len == 0 or (args.len == 1 and (std.mem.eql(u8, args[0], "--help") or std.mem.eql(u8, args[0], "-h")))) {
        try std.fs.File.stdout().writeAll(ai_redact_help_text);
        return;
    }
    const config = try parseAiRedactArgs(args);
    const default_rules_path = if (config.rules_path == null) try defaultAiRedactRulesPathAlloc(allocator) else null;
    defer if (default_rules_path) |path| allocator.free(path);
    const rules_path = config.rules_path orelse default_rules_path.?;
    switch (config.mode) {
        .@"test" => |text| {
            const output = try aiRedactWithRulesAlloc(allocator, text, rules_path);
            defer allocator.free(output);
            try std.fs.File.stdout().writeAll(output);
            try std.fs.File.stdout().writeAll("\n");
        },
        .add_literal => |literal| {
            try appendAiRedactLiteralRule(rules_path, literal);
            const message = try std.fmt.allocPrint(allocator, "added literal rule to {s}\n", .{rules_path});
            defer allocator.free(message);
            try std.fs.File.stdout().writeAll(message);
        },
    }
}

fn parseAiRedactArgs(args: []const []const u8) !AiRedactConfig {
    var rules_path: ?[]const u8 = null;
    var mode: ?AiRedactMode = null;
    var i: usize = 0;
    while (i < args.len) : (i += 1) {
        if (std.mem.eql(u8, args[i], "--rules")) {
            rules_path = try nextValue(args, &i);
        } else if (std.mem.eql(u8, args[i], "--test")) {
            if (mode != null) return error.UnknownAiArgument;
            mode = .{ .@"test" = try nextValue(args, &i) };
        } else if (std.mem.eql(u8, args[i], "--add-literal")) {
            if (mode != null) return error.UnknownAiArgument;
            mode = .{ .add_literal = try nextValue(args, &i) };
        } else {
            return error.UnknownAiArgument;
        }
    }
    return .{ .mode = mode orelse return error.MissingValue, .rules_path = rules_path };
}

fn defaultAiRedactRulesPathAlloc(allocator: std.mem.Allocator) ![]u8 {
    const dir = try configDirPath(allocator);
    defer allocator.free(dir);
    return std.fmt.allocPrint(allocator, "{s}/ai-redact.rules", .{dir});
}

fn aiRedactWithRulesAlloc(allocator: std.mem.Allocator, text: []const u8, rules_path: []const u8) ![]u8 {
    var redacted = try ai_redact.redactAlloc(allocator, text);
    errdefer allocator.free(redacted);
    const rules = try readAiRedactRulesAlloc(allocator, rules_path);
    defer freeOwnedStringSlice(allocator, rules);
    for (rules) |rule| {
        const next = try redactLiteralAlloc(allocator, redacted, rule);
        allocator.free(redacted);
        redacted = next;
    }
    return redacted;
}

fn readAiRedactRulesAlloc(allocator: std.mem.Allocator, rules_path: []const u8) ![][]u8 {
    const source = std.fs.cwd().readFileAlloc(allocator, rules_path, 256 * 1024) catch |err| switch (err) {
        error.FileNotFound => return allocator.alloc([]u8, 0),
        else => return err,
    };
    defer allocator.free(source);
    var rules: std.ArrayList([]u8) = .empty;
    errdefer {
        for (rules.items) |rule| allocator.free(rule);
        rules.deinit(allocator);
    }
    var lines = std.mem.splitScalar(u8, source, '\n');
    while (lines.next()) |line_raw| {
        const line = std.mem.trim(u8, line_raw, " \t\r\n");
        if (line.len == 0 or line[0] == '#') continue;
        try rules.append(allocator, try allocator.dupe(u8, line));
    }
    return rules.toOwnedSlice(allocator);
}

fn freeOwnedStringSlice(allocator: std.mem.Allocator, items: [][]u8) void {
    for (items) |item| allocator.free(item);
    allocator.free(items);
}

fn redactLiteralAlloc(allocator: std.mem.Allocator, text: []const u8, literal: []const u8) ![]u8 {
    if (literal.len == 0) return allocator.dupe(u8, text);
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);
    var index: usize = 0;
    while (index < text.len) {
        if (std.mem.startsWith(u8, text[index..], literal)) {
            try out.appendSlice(allocator, ai_redact.marker);
            index += literal.len;
        } else {
            try out.append(allocator, text[index]);
            index += 1;
        }
    }
    return out.toOwnedSlice(allocator);
}

fn appendAiRedactLiteralRule(rules_path: []const u8, literal: []const u8) !void {
    if (literal.len == 0 or std.mem.indexOfAny(u8, literal, "\r\n") != null) return error.InvalidRedactRule;
    if (std.fs.path.dirname(rules_path)) |parent| try std.fs.cwd().makePath(parent);
    var file = try std.fs.cwd().createFile(rules_path, .{ .read = true, .truncate = false });
    defer file.close();
    try file.seekFromEnd(0);
    try file.writeAll(literal);
    try file.writeAll("\n");
}

fn aiStatusOutputAlloc(allocator: std.mem.Allocator, status: ollama.Status, home: ?[]const u8) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);
    try appendFmt(allocator, &out, "local:\n  ollama_installed: {}\n  ollama_running: {}\n  recommended_model: {s}\n", .{ status.installed, status.daemon_running, ollama.recommended_model });
    try out.appendSlice(allocator, "cloud:\n  providers: none\n  enabled: false\n");
    try out.appendSlice(allocator, "logging:\n");
    if (home) |home_path| {
        const audit_path = try prodGuardAuditPathAlloc(allocator, home_path);
        defer allocator.free(audit_path);
        try appendFmt(allocator, &out, "  prod_guard_audit: {s} {s}\n", .{ pathAccessStatus(audit_path), audit_path });
    } else {
        try out.appendSlice(allocator, "  prod_guard_audit: missing HOME\n");
    }
    try out.appendSlice(allocator, "  ai_cloud_audit: not_configured\n");
    return out.toOwnedSlice(allocator);
}

fn parseAiBenchArgs(args: []const []const u8) !AiBenchConfig {
    var config = AiBenchConfig{};
    var i: usize = 0;
    while (i < args.len) : (i += 1) {
        if (std.mem.eql(u8, args[i], "--model")) {
            config.model = try nextValue(args, &i);
        } else if (std.mem.eql(u8, args[i], "--prompt")) {
            config.prompt = try nextValue(args, &i);
        } else if (std.mem.eql(u8, args[i], "--cold")) {
            config.cold = true;
        } else if (std.mem.eql(u8, args[i], "--warm")) {
            config.warm = true;
        } else if (std.mem.eql(u8, args[i], "--memory")) {
            config.memory = true;
        } else if (std.mem.eql(u8, args[i], "--all-supported")) {
            config.all_supported = true;
        } else {
            return error.UnknownAiArgument;
        }
    }
    return config;
}

const AiRiskConfig = struct {
    command: []const u8 = "",
    model: []const u8 = ollama.recommended_model,
    slm: bool = false,
    preexec: bool = false,
};

const AiExplainConfig = struct {
    command: []const u8 = "",
    model: []const u8 = ollama.recommended_model,
};

fn parseAiRiskArgs(args: []const []const u8) !AiRiskConfig {
    var config = AiRiskConfig{};
    var i: usize = 0;
    while (i < args.len) : (i += 1) {
        if (std.mem.eql(u8, args[i], "--command")) {
            config.command = try nextValue(args, &i);
        } else if (std.mem.eql(u8, args[i], "--model")) {
            config.model = try nextValue(args, &i);
        } else if (std.mem.eql(u8, args[i], "--slm")) {
            config.slm = true;
        } else if (std.mem.eql(u8, args[i], "--preexec")) {
            config.preexec = true;
        } else if (std.mem.eql(u8, args[i], "--")) {
            config.command = try nextValue(args, &i);
            if (i + 1 != args.len) return error.UnknownAiArgument;
        } else if (config.command.len == 0) {
            config.command = args[i];
        } else {
            return error.UnknownAiArgument;
        }
    }
    if (config.command.len == 0) return error.MissingValue;
    return config;
}

fn parseAiExplainArgs(args: []const []const u8) !AiExplainConfig {
    var config = AiExplainConfig{};
    var i: usize = 0;
    while (i < args.len) : (i += 1) {
        if (std.mem.eql(u8, args[i], "--command")) {
            config.command = try nextValue(args, &i);
        } else if (std.mem.eql(u8, args[i], "--model")) {
            config.model = try nextValue(args, &i);
        } else if (std.mem.eql(u8, args[i], "--")) {
            config.command = try nextValue(args, &i);
            if (i + 1 != args.len) return error.UnknownAiArgument;
        } else if (config.command.len == 0) {
            config.command = args[i];
        } else {
            return error.UnknownAiArgument;
        }
    }
    return config;
}

fn aiExplain(allocator: std.mem.Allocator, config: AiExplainConfig) !void {
    if (config.command.len == 0) return;
    const output = aiExplainModelAlloc(allocator, config) catch try ai_risk.outputAlloc(allocator, config.command);
    defer allocator.free(output);
    try std.fs.File.stdout().writeAll(output);
}

fn aiExplainModelAlloc(allocator: std.mem.Allocator, config: AiExplainConfig) ![]u8 {
    const status = try ollama.detect(allocator);
    if (!status.installed or !status.daemon_running) return error.OllamaUnavailable;
    const flags = try ai_explain.flagContextAlloc(allocator, config.command);
    defer allocator.free(flags);
    const template = try ai_explain.readDefaultPromptAlloc(allocator);
    defer allocator.free(template);
    const prompt_text = try ai_explain.promptWithInputAlloc(allocator, template, config.command, flags);
    defer allocator.free(prompt_text);
    const raw = try ollama.generateAlloc(allocator, ollama.default_host, ollama.default_port, config.model, prompt_text);
    defer allocator.free(raw);
    const cleaned = try ai_explain.cleanExplanationAlloc(allocator, raw);
    errdefer allocator.free(cleaned);
    if (cleaned.len == 0) return error.EmptyExplanation;
    return cleaned;
}

fn aiRisk(allocator: std.mem.Allocator, config: AiRiskConfig) !void {
    var result = ai_risk.explain(config.command);
    if (config.slm and result.risk == .medium) {
        result = aiRiskSlm(allocator, config, result) catch result;
    }
    const output = try ai_risk.outputExplanationAlloc(allocator, config.command, result);
    defer allocator.free(output);
    if (config.preexec) {
        if (result.risk == .high) {
            try std.fs.File.stderr().writeAll(output);
            std.process.exit(1);
        }
        if (result.risk == .medium) try std.fs.File.stderr().writeAll(output);
        return;
    }
    try std.fs.File.stdout().writeAll(output);
}

fn aiRiskSlm(allocator: std.mem.Allocator, config: AiRiskConfig, fallback: ai_risk.Explanation) !ai_risk.Explanation {
    const status = try ollama.detect(allocator);
    if (!status.installed or !status.daemon_running) return fallback;
    const prompt_text = try ai_risk.promptWithCommandAlloc(allocator, config.command);
    defer allocator.free(prompt_text);
    const raw = try ollama.generateAlloc(allocator, ollama.default_host, ollama.default_port, config.model, prompt_text);
    defer allocator.free(raw);
    const risk = ai_risk.parseSlmRisk(raw) orelse return fallback;
    return .{ .risk = risk, .source = "slm", .pattern = fallback.pattern };
}

fn aiBench(allocator: std.mem.Allocator, config: AiBenchConfig) !void {
    const status = try ollama.detect(allocator);
    if (!status.installed) {
        try std.fs.File.stderr().writeAll("shisa ai bench: ollama not installed\n");
        return error.OllamaUnavailable;
    }
    if (!status.daemon_running) {
        try std.fs.File.stderr().writeAll("shisa ai bench: ollama daemon not running\n");
        return error.OllamaUnavailable;
    }
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);
    const single_model = [_][]const u8{config.model};
    const models = if (config.all_supported) ollama.supported_models[0..] else single_model[0..];
    for (models, 0..) |model, index| {
        if (index != 0) try out.append(allocator, '\n');
        const output = try aiBenchModelOutputAlloc(allocator, config, model);
        defer allocator.free(output);
        try out.appendSlice(allocator, output);
    }
    try std.fs.File.stdout().writeAll(out.items);
}

const AiBenchResults = struct {
    cold: ?ollama.BenchmarkResult = null,
    warm: ?ollama.BenchmarkResult = null,
    memory_ceiling_bytes: ?u64 = null,
};

fn aiBenchModelOutputAlloc(allocator: std.mem.Allocator, config: AiBenchConfig, model: []const u8) ![]u8 {
    var results = AiBenchResults{};
    if (config.runCold()) {
        try ollama.unloadModel(allocator, ollama.default_host, ollama.default_port, model);
        results.cold = try ollama.benchmarkGenerate(allocator, ollama.default_host, ollama.default_port, model, config.prompt);
    }
    if (config.runWarm()) {
        try ollama.loadModel(allocator, ollama.default_host, ollama.default_port, model);
        results.warm = try ollama.benchmarkGenerate(allocator, ollama.default_host, ollama.default_port, model, config.prompt);
    }
    if (config.runMemory()) {
        try ollama.loadModel(allocator, ollama.default_host, ollama.default_port, model);
        results.memory_ceiling_bytes = try ollama.runningModelSize(allocator, ollama.default_host, ollama.default_port, model);
    }
    return aiBenchOutputAlloc(allocator, model, results);
}

fn aiBenchOutputAlloc(allocator: std.mem.Allocator, model: []const u8, results: AiBenchResults) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);
    try appendFmt(allocator, &out, "model: {s}\n", .{model});
    if (results.cold) |result| try appendAiBenchResult(allocator, &out, "cold", result);
    if (results.warm) |result| try appendAiBenchResult(allocator, &out, "warm", result);
    if (results.memory_ceiling_bytes) |bytes| {
        try out.appendSlice(allocator, "memory:\n");
        try appendFmt(allocator, &out, "  ceiling_bytes: {d}\n", .{bytes});
    }
    return out.toOwnedSlice(allocator);
}

fn appendAiBenchResult(allocator: std.mem.Allocator, out: *std.ArrayList(u8), label: []const u8, result: ollama.BenchmarkResult) !void {
    try appendFmt(allocator, out, "{s}:\n", .{label});
    try appendFmt(allocator, out, "  first_token_ms: {d}\n", .{@divFloor(result.first_token_ns, std.time.ns_per_ms)});
    try appendFmt(allocator, out, "  tokens_per_second_x100: {d}\n", .{result.tokens_per_second_x100});
    try appendFmt(allocator, out, "  peak_ram_bytes: {d}\n", .{result.peak_ram_bytes});
    try appendFmt(allocator, out, "  total_duration_ms: {d}\n", .{@divFloor(result.total_duration_ns, std.time.ns_per_ms)});
    try appendFmt(allocator, out, "  load_duration_ms: {d}\n", .{@divFloor(result.load_duration_ns, std.time.ns_per_ms)});
    try appendFmt(allocator, out, "  eval_count: {d}\n", .{result.eval_count});
    try appendFmt(allocator, out, "  eval_duration_ms: {d}\n", .{@divFloor(result.eval_duration_ns, std.time.ns_per_ms)});
}

fn aiNextcmd(allocator: std.mem.Allocator, config: AiNextcmdConfig) !void {
    const status = ollama.detect(allocator) catch return;
    if (!status.installed or !status.daemon_running) return;
    const history_source = if (config.history_path.len == 0) null else std.fs.cwd().readFileAlloc(allocator, config.history_path, 256 * 1024) catch null;
    defer if (history_source) |value| allocator.free(value);
    const suggestion = aiNextcmdSuggestionAlloc(allocator, config, history_source orelse "") catch return;
    defer allocator.free(suggestion);
    try std.fs.File.stdout().writeAll(suggestion);
}

fn aiNextcmdSuggestionAlloc(allocator: std.mem.Allocator, config: AiNextcmdConfig, history_source: []const u8) ![]u8 {
    const context = try nextcmd.buildContextAlloc(allocator, .{
        .cwd = config.cwd,
        .last_command = config.last_command,
        .last_exit = config.last_exit,
        .history_source = history_source,
        .history_limit = config.history_limit,
    });
    defer allocator.free(context);
    const template = try nextcmd.readDefaultPromptAlloc(allocator);
    defer allocator.free(template);
    const prompt_text = try nextcmd.promptWithContextAlloc(allocator, template, context);
    defer allocator.free(prompt_text);
    const raw = try ollama.generateAlloc(allocator, ollama.default_host, ollama.default_port, config.model, prompt_text);
    defer allocator.free(raw);
    return nextcmd.cleanSuggestionAlloc(allocator, raw);
}

fn aiNl2cmd(allocator: std.mem.Allocator, config: AiNl2cmdConfig) !void {
    if (config.exec_requested) {
        try std.fs.File.stderr().writeAll("shisa ai nl2cmd: refusing to execute generated commands; confirm manually\n");
        std.process.exit(1);
    }
    const request = nl2cmd.detectInput(config.input) orelse return;
    if (request.len == 0) return;
    if (config.detect_only) {
        try std.fs.File.stdout().writeAll(request);
        return;
    }
    const status = ollama.detect(allocator) catch {
        appendNl2cmdAudit(allocator, config, request, "", "error") catch {};
        return;
    };
    if (!status.installed or !status.daemon_running) {
        appendNl2cmdAudit(allocator, config, request, "", "unavailable") catch {};
        return;
    }
    const command = aiNl2cmdCommandAlloc(allocator, config, request) catch {
        appendNl2cmdAudit(allocator, config, request, "", "error") catch {};
        return;
    };
    defer allocator.free(command);
    if (command.len == 0) {
        appendNl2cmdAudit(allocator, config, request, "", "empty") catch {};
        return;
    }
    if (prod_guard_module.destructivePattern(command) != null) {
        appendNl2cmdAudit(allocator, config, request, command, "blocked") catch {};
        return;
    }
    appendNl2cmdAudit(allocator, config, request, command, "candidate") catch {};
    if (config.plain) {
        try std.fs.File.stdout().writeAll(command);
        return;
    }
    const output = try nl2cmd.candidateOutputAlloc(allocator, command);
    defer allocator.free(output);
    try std.fs.File.stdout().writeAll(output);
}

fn aiNl2cmdCommandAlloc(allocator: std.mem.Allocator, config: AiNl2cmdConfig, request: []const u8) ![]u8 {
    const template = try nl2cmd.readDefaultPromptAlloc(allocator);
    defer allocator.free(template);
    const prompt_text = try nl2cmd.promptWithInputAlloc(allocator, template, .{
        .shell = config.shell,
        .cwd = config.cwd,
        .request = request,
    });
    defer allocator.free(prompt_text);
    const raw = try ollama.generateAlloc(allocator, ollama.default_host, ollama.default_port, config.model, prompt_text);
    defer allocator.free(raw);
    return nl2cmd.cleanCommandAlloc(allocator, raw);
}

fn appendNl2cmdAudit(allocator: std.mem.Allocator, config: AiNl2cmdConfig, request: []const u8, candidate: []const u8, status: []const u8) !void {
    const home = std.process.getEnvVarOwned(allocator, "HOME") catch return;
    defer allocator.free(home);
    const path = try nl2cmdAuditPathAlloc(allocator, home);
    defer allocator.free(path);
    const line = try nl2cmdAuditLineAlloc(allocator, config, request, candidate, status);
    defer allocator.free(line);
    try appendLineToPath(path, line);
}

fn nl2cmdAuditPathAlloc(allocator: std.mem.Allocator, home: []const u8) ![]u8 {
    return std.fmt.allocPrint(allocator, "{s}/.local/state/shisa/nl2cmd.jsonl", .{home});
}

fn nl2cmdAuditLineAlloc(allocator: std.mem.Allocator, config: AiNl2cmdConfig, request: []const u8, candidate: []const u8, status: []const u8) ![]u8 {
    const escaped_shell = try jsonEscapeAlloc(allocator, config.shell);
    defer allocator.free(escaped_shell);
    const escaped_cwd = try jsonEscapeAlloc(allocator, config.cwd);
    defer allocator.free(escaped_cwd);
    const escaped_request = try jsonEscapeAlloc(allocator, request);
    defer allocator.free(escaped_request);
    const escaped_candidate = try jsonEscapeAlloc(allocator, candidate);
    defer allocator.free(escaped_candidate);
    const confidence = if (candidate.len == 0) "none" else nl2cmd.commandConfidence(candidate).label();
    return std.fmt.allocPrint(
        allocator,
        "{{\"ts\":{d},\"shell\":\"{s}\",\"cwd\":\"{s}\",\"request\":\"{s}\",\"candidate\":\"{s}\",\"confidence\":\"{s}\",\"status\":\"{s}\"}}\n",
        .{ std.time.timestamp(), escaped_shell, escaped_cwd, escaped_request, escaped_candidate, confidence, status },
    );
}

fn appendLineToPath(path: []const u8, line: []const u8) !void {
    if (std.fs.path.dirname(path)) |parent| try std.fs.cwd().makePath(parent);
    var file = try std.fs.createFileAbsolute(path, .{
        .read = true,
        .truncate = false,
        .mode = 0o600,
    });
    defer file.close();
    try file.seekFromEnd(0);
    try file.writeAll(line);
}

const AiNextcmdConfig = struct {
    shell: []const u8 = "",
    model: []const u8 = ollama.recommended_model,
    cwd: []const u8 = "",
    last_command: []const u8 = "",
    last_exit: i32 = 0,
    history_path: []const u8 = "",
    history_limit: usize = 20,
};

const AiNl2cmdConfig = struct {
    shell: []const u8 = "",
    model: []const u8 = ollama.recommended_model,
    cwd: []const u8 = "",
    input: []const u8 = "",
    detect_only: bool = false,
    plain: bool = false,
    exec_requested: bool = false,
};

fn parseAiNextcmdArgs(args: []const []const u8) !AiNextcmdConfig {
    var config = AiNextcmdConfig{};
    var i: usize = 0;
    while (i < args.len) : (i += 1) {
        if (std.mem.eql(u8, args[i], "--shell")) {
            config.shell = try nextValue(args, &i);
        } else if (std.mem.eql(u8, args[i], "--model")) {
            config.model = try nextValue(args, &i);
        } else if (std.mem.eql(u8, args[i], "--cwd")) {
            config.cwd = try nextValue(args, &i);
        } else if (std.mem.eql(u8, args[i], "--last-command")) {
            config.last_command = try nextValue(args, &i);
        } else if (std.mem.eql(u8, args[i], "--last-exit")) {
            config.last_exit = try std.fmt.parseInt(i32, try nextValue(args, &i), 10);
        } else if (std.mem.eql(u8, args[i], "--history-path")) {
            config.history_path = try nextValue(args, &i);
        } else if (std.mem.eql(u8, args[i], "--history-limit")) {
            config.history_limit = try std.fmt.parseInt(usize, try nextValue(args, &i), 10);
        } else {
            return error.UnknownAiArgument;
        }
    }
    return config;
}

fn parseAiNl2cmdArgs(args: []const []const u8) !AiNl2cmdConfig {
    var config = AiNl2cmdConfig{};
    var i: usize = 0;
    while (i < args.len) : (i += 1) {
        if (std.mem.eql(u8, args[i], "--shell")) {
            config.shell = try nextValue(args, &i);
        } else if (std.mem.eql(u8, args[i], "--model")) {
            config.model = try nextValue(args, &i);
        } else if (std.mem.eql(u8, args[i], "--cwd")) {
            config.cwd = try nextValue(args, &i);
        } else if (std.mem.eql(u8, args[i], "--input")) {
            config.input = try nextValue(args, &i);
        } else if (std.mem.eql(u8, args[i], "--detect-only")) {
            config.detect_only = true;
        } else if (std.mem.eql(u8, args[i], "--plain")) {
            config.plain = true;
        } else if (std.mem.eql(u8, args[i], "--exec")) {
            config.exec_requested = true;
        } else {
            return error.UnknownAiArgument;
        }
    }
    return config;
}

test "ai bench args parse" {
    const config = try parseAiBenchArgs(&.{ "--model", "gemma3:1b", "--prompt", "hi", "--cold", "--warm", "--memory", "--all-supported" });
    try std.testing.expectEqualStrings("gemma3:1b", config.model);
    try std.testing.expectEqualStrings("hi", config.prompt);
    try std.testing.expect(config.cold);
    try std.testing.expect(config.warm);
    try std.testing.expect(config.memory);
    try std.testing.expect(config.all_supported);
}

test "ai status output reports local cloud and logging state" {
    const output = try aiStatusOutputAlloc(std.testing.allocator, .{ .installed = true, .daemon_running = false }, "/tmp/shisa-ai-status-home");
    defer std.testing.allocator.free(output);
    try std.testing.expect(std.mem.indexOf(u8, output, "local:\n") != null);
    try std.testing.expect(std.mem.indexOf(u8, output, "ollama_installed: true") != null);
    try std.testing.expect(std.mem.indexOf(u8, output, "cloud:\n  providers: none\n") != null);
    try std.testing.expect(std.mem.indexOf(u8, output, "logging:\n") != null);
    try std.testing.expect(std.mem.indexOf(u8, output, "prod_guard_audit: missing /tmp/shisa-ai-status-home/.local/state/shisa/prod_guard.jsonl") != null);
    try std.testing.expect(std.mem.indexOf(u8, output, "ai_cloud_audit: not_configured") != null);
}

test "ai redact args parse test and add literal modes" {
    const test_config = try parseAiRedactArgs(&.{ "--rules", "/tmp/rules", "--test", "token=secret" });
    try std.testing.expectEqualStrings("/tmp/rules", test_config.rules_path.?);
    try std.testing.expectEqualStrings("token=secret", test_config.mode.@"test");

    const add_config = try parseAiRedactArgs(&.{ "--add-literal", "internal-host" });
    try std.testing.expectEqualStrings("internal-host", add_config.mode.add_literal);
}

test "ai redact applies built-in and local literal rules" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-ai-redact-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    const rules_path = try std.fmt.allocPrint(allocator, "{s}/ai-redact.rules", .{dir_path});
    defer allocator.free(rules_path);
    try appendAiRedactLiteralRule(rules_path, "internal-host");

    const output = try aiRedactWithRulesAlloc(allocator, "token=kube-secret host=internal-host", rules_path);
    defer allocator.free(output);
    try std.testing.expect(std.mem.indexOf(u8, output, "kube-secret") == null);
    try std.testing.expect(std.mem.indexOf(u8, output, "internal-host") == null);
    try std.testing.expect(std.mem.indexOf(u8, output, ai_redact.marker) != null);
}

test "ai risk args parse" {
    const config = try parseAiRiskArgs(&.{ "--command", "rm -rf /tmp/x", "--model", "gemma3:1b", "--slm", "--preexec" });
    try std.testing.expectEqualStrings("rm -rf /tmp/x", config.command);
    try std.testing.expectEqualStrings("gemma3:1b", config.model);
    try std.testing.expect(config.slm);
    try std.testing.expect(config.preexec);
}

test "ai explain args parse" {
    const config = try parseAiExplainArgs(&.{ "--command", "tar -xf app.tar", "--model", "gemma3:1b" });
    try std.testing.expectEqualStrings("tar -xf app.tar", config.command);
    try std.testing.expectEqualStrings("gemma3:1b", config.model);
}

test "ai nextcmd args parse" {
    const config = try parseAiNextcmdArgs(&.{ "--shell", "zsh", "--model", "gemma3:1b", "--cwd", "/tmp", "--last-command", "zig test", "--last-exit", "2", "--history-path", "/tmp/h", "--history-limit", "3" });
    try std.testing.expectEqualStrings("zsh", config.shell);
    try std.testing.expectEqualStrings("gemma3:1b", config.model);
    try std.testing.expectEqualStrings("/tmp", config.cwd);
    try std.testing.expectEqualStrings("zig test", config.last_command);
    try std.testing.expectEqual(@as(i32, 2), config.last_exit);
    try std.testing.expectEqualStrings("/tmp/h", config.history_path);
    try std.testing.expectEqual(@as(usize, 3), config.history_limit);
}

test "ai nl2cmd args parse" {
    const config = try parseAiNl2cmdArgs(&.{ "--shell", "zsh", "--model", "gemma3:1b", "--cwd", "/tmp", "--input", "?? list files", "--detect-only", "--plain", "--exec" });
    try std.testing.expectEqualStrings("zsh", config.shell);
    try std.testing.expectEqualStrings("gemma3:1b", config.model);
    try std.testing.expectEqualStrings("/tmp", config.cwd);
    try std.testing.expectEqualStrings("?? list files", config.input);
    try std.testing.expect(config.detect_only);
    try std.testing.expect(config.plain);
    try std.testing.expect(config.exec_requested);
}

test "ai nl2cmd audit line escapes fields" {
    const line = try nl2cmdAuditLineAlloc(std.testing.allocator, .{
        .shell = "zsh",
        .cwd = "/tmp/repo",
        .input = "?? list\nfiles",
    }, "list\nfiles", "ls -lS", "candidate");
    defer std.testing.allocator.free(line);
    try std.testing.expect(std.mem.indexOf(u8, line, "\"request\":\"list\\nfiles\"") != null);
    try std.testing.expect(std.mem.indexOf(u8, line, "\"candidate\":\"ls -lS\"") != null);
    try std.testing.expect(std.mem.indexOf(u8, line, "\"confidence\":\"high\"") != null);
    try std.testing.expect(std.mem.endsWith(u8, line, "\n"));
}

test "ai bench output reports metrics" {
    const result = ollama.BenchmarkResult{
        .first_token_ns = 12 * std.time.ns_per_ms,
        .tokens_per_second_x100 = 1234,
        .peak_ram_bytes = 815000000,
        .total_duration_ns = 100 * std.time.ns_per_ms,
        .load_duration_ns = 20 * std.time.ns_per_ms,
        .eval_count = 10,
        .eval_duration_ns = 80 * std.time.ns_per_ms,
    };
    const output = try aiBenchOutputAlloc(std.testing.allocator, "gemma3:1b", .{
        .cold = result,
        .warm = result,
        .memory_ceiling_bytes = 815000000,
    });
    defer std.testing.allocator.free(output);
    try std.testing.expect(std.mem.indexOf(u8, output, "model: gemma3:1b\n") != null);
    try std.testing.expect(std.mem.indexOf(u8, output, "cold:\n") != null);
    try std.testing.expect(std.mem.indexOf(u8, output, "warm:\n") != null);
    try std.testing.expect(std.mem.indexOf(u8, output, "  tokens_per_second_x100: 1234\n") != null);
    try std.testing.expect(std.mem.indexOf(u8, output, "memory:\n  ceiling_bytes: 815000000\n") != null);
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

const StackConfig = struct {
    cwd: ?[]const u8 = null,
};

fn stackCommand(allocator: std.mem.Allocator, args: []const []const u8) !void {
    const config = try parseStackArgs(args);
    const cwd = if (config.cwd) |path| path else try std.fs.cwd().realpathAlloc(allocator, ".");
    defer if (config.cwd == null) allocator.free(cwd);

    const output = try stackOutputAlloc(allocator, cwd);
    defer allocator.free(output);
    try std.fs.File.stdout().writeAll(output);
}

fn parseStackArgs(args: []const []const u8) !StackConfig {
    var config = StackConfig{};
    var i: usize = 0;
    while (i < args.len) : (i += 1) {
        if (std.mem.eql(u8, args[i], "--cwd")) {
            config.cwd = try nextValue(args, &i);
        } else {
            return error.UnknownStackArgument;
        }
    }
    return config;
}

fn stackOutputAlloc(allocator: std.mem.Allocator, cwd_path: []const u8) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);

    var detection = (try vcs_stack.detect(allocator, cwd_path)) orelse {
        try out.appendSlice(allocator, "stack: none\n");
        return out.toOwnedSlice(allocator);
    };
    defer detection.deinit(allocator);

    try appendFmt(allocator, &out, "provider: {s}\n", .{detection.provider.label()});
    try appendFmt(allocator, &out, "root: {s}\n", .{detection.root_path});
    try appendFmt(allocator, &out, "marker: {s}\n", .{detection.marker_path});
    if (detection.branch_name) |branch_name| {
        try appendFmt(allocator, &out, "branch: {s}\n", .{branch_name});
    }
    return out.toOwnedSlice(allocator);
}

test "stack args parse cwd override" {
    const config = try parseStackArgs(&.{ "--cwd", "/tmp/repo" });
    try std.testing.expectEqualStrings("/tmp/repo", config.cwd.?);
    try std.testing.expectError(error.UnknownStackArgument, parseStackArgs(&.{"--bad"}));
}

test "stack output reports no stack" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-cli-stack-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    const output = try stackOutputAlloc(allocator, dir_path);
    defer allocator.free(output);
    try std.testing.expectEqualStrings("stack: none\n", output);
}

test "stack output dumps detected stack" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-cli-stack-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    const marker_path = try std.fmt.allocPrint(allocator, "{s}/.graphite_repo_config", .{dir_path});
    defer allocator.free(marker_path);
    var file = try std.fs.createFileAbsolute(marker_path, .{});
    try file.writeAll("{}\n");
    file.close();

    const output = try stackOutputAlloc(allocator, dir_path);
    defer allocator.free(output);
    try std.testing.expect(std.mem.indexOf(u8, output, "provider: graphite\n") != null);
    try std.testing.expect(std.mem.indexOf(u8, output, dir_path) != null);
    try std.testing.expect(std.mem.indexOf(u8, output, marker_path) != null);
}

const WorktreesConfig = struct {
    cwd: ?[]const u8 = null,
};

fn worktreesCommand(allocator: std.mem.Allocator, args: []const []const u8) !void {
    const config = try parseWorktreesArgs(args);
    const cwd = if (config.cwd) |path| path else try std.fs.cwd().realpathAlloc(allocator, ".");
    defer if (config.cwd == null) allocator.free(cwd);

    const output = try worktreesOutputAlloc(allocator, cwd);
    defer allocator.free(output);
    try std.fs.File.stdout().writeAll(output);
}

fn parseWorktreesArgs(args: []const []const u8) !WorktreesConfig {
    var config = WorktreesConfig{};
    var i: usize = 0;
    while (i < args.len) : (i += 1) {
        if (std.mem.eql(u8, args[i], "--cwd")) {
            config.cwd = try nextValue(args, &i);
        } else {
            return error.UnknownWorktreesArgument;
        }
    }
    return config;
}

fn worktreesOutputAlloc(allocator: std.mem.Allocator, cwd_path: []const u8) ![]u8 {
    const active_root_output = gitOutputAlloc(allocator, cwd_path, &.{ "git", "rev-parse", "--show-toplevel" }) catch |err| switch (err) {
        error.CommandFailed, error.FileNotFound => return allocator.dupe(u8, "worktrees: none\n"),
        else => return err,
    };
    defer allocator.free(active_root_output);
    const active_root = std.mem.trim(u8, active_root_output, " \t\r\n");

    const porcelain = gitOutputAlloc(allocator, cwd_path, &.{ "git", "worktree", "list", "--porcelain" }) catch |err| switch (err) {
        error.CommandFailed, error.FileNotFound => return allocator.dupe(u8, "worktrees: none\n"),
        else => return err,
    };
    defer allocator.free(porcelain);

    var list = try vcs_worktree.parseListPorcelain(allocator, porcelain, active_root);
    defer list.deinit(allocator);
    try markDirtyWorktrees(allocator, &list);
    return vcs_worktree.renderListAlloc(allocator, list);
}

fn worktreesRenderAlloc(allocator: std.mem.Allocator, porcelain: []const u8, active_root: []const u8) ![]u8 {
    var list = try vcs_worktree.parseListPorcelain(allocator, porcelain, active_root);
    defer list.deinit(allocator);
    return vcs_worktree.renderListAlloc(allocator, list);
}

fn markDirtyWorktrees(allocator: std.mem.Allocator, list: *vcs_worktree.List) !void {
    for (list.entries) |*entry| {
        entry.dirty = try gitStatusDirty(allocator, entry.path);
    }
}

fn gitStatusDirty(allocator: std.mem.Allocator, cwd_path: []const u8) !bool {
    const output = gitOutputAlloc(allocator, cwd_path, &.{ "git", "status", "--porcelain" }) catch |err| switch (err) {
        error.CommandFailed, error.FileNotFound => return false,
        else => return err,
    };
    defer allocator.free(output);
    return std.mem.trim(u8, output, " \t\r\n").len != 0;
}

fn gitOutputAlloc(allocator: std.mem.Allocator, cwd_path: []const u8, argv: []const []const u8) ![]u8 {
    const result = try std.process.Child.run(.{
        .allocator = allocator,
        .argv = argv,
        .cwd = cwd_path,
        .max_output_bytes = 1024 * 1024,
        .expand_arg0 = .expand,
    });
    defer allocator.free(result.stderr);
    if (!exitedZero(result.term)) {
        allocator.free(result.stdout);
        return error.CommandFailed;
    }
    return result.stdout;
}

test "worktrees args parse cwd override" {
    const config = try parseWorktreesArgs(&.{ "--cwd", "/tmp/repo" });
    try std.testing.expectEqualStrings("/tmp/repo", config.cwd.?);
    try std.testing.expectError(error.UnknownWorktreesArgument, parseWorktreesArgs(&.{"--bad"}));
}

test "worktrees output marks active path" {
    const source =
        \\worktree /repo
        \\HEAD a
        \\branch refs/heads/main
        \\
        \\worktree /repo-linked
        \\HEAD b
        \\branch refs/heads/feature
        \\
    ;
    const output = try worktreesRenderAlloc(std.testing.allocator, source, "/repo-linked");
    defer std.testing.allocator.free(output);
    try std.testing.expectEqualStrings("  /repo main\n* /repo-linked feature\n", output);
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
        try appendFmt(allocator, &out, "# Powerlevel10k instant_prompt: {s}\n", .{value});
        try appendFmt(allocator, &out, "# Shisa instant prompt: SHISA_INSTANT={d}\n", .{@intFromBool(p10kInstantEnabled(value))});
    }
    try out.appendSlice(allocator, "[prompt]\nmodules = [");
    for (imported.modules.items, 0..) |module_id, index| {
        if (index != 0) try out.appendSlice(allocator, ", ");
        try appendFmt(allocator, &out, "\"{s}\"", .{shisa_config.moduleIdName(module_id)});
    }
    try out.appendSlice(allocator, "]\n");
    if (imported.right_modules.items.len != 0) {
        try out.appendSlice(allocator, "right_modules = [");
        for (imported.right_modules.items, 0..) |module_id, index| {
            if (index != 0) try out.appendSlice(allocator, ", ");
            try appendFmt(allocator, &out, "\"{s}\"", .{shisa_config.moduleIdName(module_id)});
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
    try appendFmt(allocator, out, "# Powerlevel10k {s} elements: ", .{side});
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
        try appendFmt(allocator, &out, "- `{s}`: {s}\n", .{ name, p10kUnsupportedReason(name) });
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
        try appendFmt(allocator, &out, "\"{s}\"", .{shisa_config.moduleIdName(module_id)});
    }
    try out.appendSlice(allocator, "]\n");
    if (imported.right_modules.items.len != 0) {
        try out.appendSlice(allocator, "right_modules = [");
        for (imported.right_modules.items, 0..) |module_id, index| {
            if (index != 0) try out.appendSlice(allocator, ", ");
            try appendFmt(allocator, &out, "\"{s}\"", .{shisa_config.moduleIdName(module_id)});
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
            try appendFmt(allocator, &out, "- `{s}`: {s}\n", .{ name, ompUnsupportedReason(name) });
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
                try appendFmt(allocator, &out, "- `{s}`: template requires manual port.\n", .{kind});
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
                    try appendFmt(allocator, &out, "- `{s}` foreground `{s}` could not be resolved.\n", .{ kind, foreground });
                }
            }
            if (segment.background) |background| {
                if (resolveOmpColorRgb(theme, background, 0) == null) {
                    if (color_count == 0) try out.appendSlice(allocator, "## Unresolved Colors\n\n");
                    color_count += 1;
                    count += 1;
                    try appendFmt(allocator, &out, "- `{s}` background `{s}` could not be resolved.\n", .{ kind, background });
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
    try appendFmt(allocator, out, "# Oh My Posh {s} layout: ", .{if (right) "right" else "left"});
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
            try appendFmt(allocator, &out, "\n[segments.{s}]\n", .{shisa_config.moduleIdName(module_id)});
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
        try appendFmt(allocator, out, "{s} = ", .{slot.name});
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
        try appendFmt(allocator, &out, "\"{s}\"", .{shisa_config.moduleIdName(module_id)});
    }
    try out.appendSlice(allocator, "]\n");
    if (imported.right_modules.items.len != 0) {
        try out.appendSlice(allocator, "right_modules = [");
        for (imported.right_modules.items, 0..) |module_id, index| {
            if (index != 0) try out.appendSlice(allocator, ", ");
            try appendFmt(allocator, &out, "\"{s}\"", .{shisa_config.moduleIdName(module_id)});
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
    try appendFmt(allocator, out, "# Tide {s} items: ", .{label});
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
            try appendFmt(allocator, &out, "- `{s}`: {s}\n", .{ name, tideUnsupportedReason(name) });
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
        try appendFmt(allocator, &out, "\"{s}\"", .{shisa_config.moduleIdName(module_id)});
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
    try appendFmt(allocator, out, "\"{s}\"", .{name});
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
            config.export_json = try nextValue(args, &i);
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
    if (!exitedZero(result.term)) return error.HyperfineUnavailable;
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
    if (!exitedZero(result.term)) return error.BenchmarkFailed;
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

fn exitedZero(term: std.process.Child.Term) bool {
    return switch (term) {
        .Exited => |code| code == 0,
        else => false,
    };
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
            module = try nextValue(args, &i);
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
        const escaped_module = try jsonEscapeAlloc(allocator, module_id);
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
    const config_path = try defaultConfigPath(allocator);
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

fn pluginCommand(allocator: std.mem.Allocator, args: []const []const u8) !void {
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

    if (std.mem.eql(u8, args[0], "pack")) {
        if (args.len != 2) return error.UnknownPluginArgument;
        const output_path = try pluginPack(allocator, args[1], ".");
        defer allocator.free(output_path);
        const message = try std.fmt.allocPrint(allocator, "packed {s}\n", .{output_path});
        defer allocator.free(message);
        try std.fs.File.stdout().writeAll(message);
        return;
    }

    const plugins_dir = try pluginsDirPath(allocator);
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

fn parsePluginTrustArgs(args: []const []const u8) !PluginTrustConfig {
    if (args.len == 0) return error.UnknownPluginArgument;
    var config = PluginTrustConfig{ .name = args[0] };
    var i: usize = 1;
    while (i < args.len) : (i += 1) {
        const arg = args[i];
        if (std.mem.eql(u8, arg, "--net")) {
            config.net = try nextValue(args, &i);
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
    try appendFmt(allocator, &out, "ok {s} {s}\n", .{ loaded.manifest.name, loaded.manifest.version });
    try appendPluginLintWarnings(allocator, &out, plugin_dir, loaded.manifest);
    return out.toOwnedSlice(allocator);
}

fn pluginDoctorAlloc(allocator: std.mem.Allocator, path: []const u8) ![]u8 {
    const lint = try pluginLintAlloc(allocator, path);
    defer allocator.free(lint);
    const status: []const u8 = if (std.mem.indexOf(u8, lint, "warning:") == null) "doctor ok\n" else "doctor warnings\n";
    return std.fmt.allocPrint(allocator, "{s}{s}", .{ status, lint });
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
    try appendFmt(allocator, &out, "format:shisa-plugin-bundle-v1\nname:{s}\nversion:{s}\n", .{ manifest.name, manifest.version });
    for (files) |file| {
        try appendFmt(allocator, &out, "file:{d}:{s}:{d}:{s}\n", .{ file.path.len, file.path, file.size, file.sha256_hex[0..] });
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
    const escaped_name = try jsonEscapeAlloc(allocator, manifest.name);
    defer allocator.free(escaped_name);
    const escaped_version = try jsonEscapeAlloc(allocator, manifest.version);
    defer allocator.free(escaped_version);
    try appendFmt(allocator, &out,
        \\{{"format":"shisa-plugin-bundle-v1","name":"{s}","version":"{s}","files":[
    , .{ escaped_name, escaped_version });
    for (files, 0..) |file, index| {
        if (index != 0) try out.append(allocator, ',');
        const escaped_path = try jsonEscapeAlloc(allocator, file.path);
        defer allocator.free(escaped_path);
        try appendFmt(allocator, &out, "{{\"path\":\"{s}\",\"size\":{d},\"sha256\":\"{s}\"}}", .{ escaped_path, file.size, file.sha256_hex[0..] });
    }
    try appendFmt(allocator, &out,
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
};

fn parsePluginInstallArgs(args: []const []const u8) !PluginInstallConfig {
    var config: PluginInstallConfig = undefined;
    var seen_url = false;
    config.yes = false;
    config.strict = false;

    for (args) |arg| {
        if (std.mem.eql(u8, arg, "--yes") or std.mem.eql(u8, arg, "-y")) {
            config.yes = true;
        } else if (std.mem.eql(u8, arg, "--plugin-sandbox-strict")) {
            config.strict = true;
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

    const temp_path = try std.fmt.allocPrint(allocator, "{s}/.install-{x}", .{ plugins_dir, std.crypto.random.int(u64) });
    defer allocator.free(temp_path);
    defer std.fs.cwd().deleteTree(temp_path) catch {};

    try runGitClone(allocator, config.url, temp_path);

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

fn runGitClone(allocator: std.mem.Allocator, url: []const u8, target_path: []const u8) !void {
    const result = try std.process.Child.run(.{
        .allocator = allocator,
        .argv = &.{ "git", "clone", "--depth", "1", url, target_path },
        .max_output_bytes = 1024 * 1024,
        .expand_arg0 = .expand,
    });
    defer allocator.free(result.stdout);
    defer allocator.free(result.stderr);
    if (!exitedZero(result.term)) return error.PluginCloneFailed;
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

fn pluginsDirPath(allocator: std.mem.Allocator) ![]u8 {
    const config_path = try defaultConfigPath(allocator);
    defer allocator.free(config_path);
    const dir = std.fs.path.dirname(config_path) orelse return error.MissingConfigDir;
    return std.fmt.allocPrint(allocator, "{s}/plugins", .{dir});
}

fn disabledPluginsPath(allocator: std.mem.Allocator) ![]u8 {
    const config_path = try defaultConfigPath(allocator);
    defer allocator.free(config_path);
    const dir = std.fs.path.dirname(config_path) orelse return error.MissingConfigDir;
    return std.fmt.allocPrint(allocator, "{s}/plugins.disabled", .{dir});
}

fn slowStrikesPluginsPath(allocator: std.mem.Allocator) ![]u8 {
    const config_path = try defaultConfigPath(allocator);
    defer allocator.free(config_path);
    const dir = std.fs.path.dirname(config_path) orelse return error.MissingConfigDir;
    return std.fmt.allocPrint(allocator, "{s}/plugins.slow-strikes", .{dir});
}

fn trustedPluginsPath(allocator: std.mem.Allocator) ![]u8 {
    const config_path = try defaultConfigPath(allocator);
    defer allocator.free(config_path);
    const dir = std.fs.path.dirname(config_path) orelse return error.MissingConfigDir;
    return std.fmt.allocPrint(allocator, "{s}/plugins.trusted", .{dir});
}

fn verifiedPluginsPath(allocator: std.mem.Allocator) ![]u8 {
    const config_path = try defaultConfigPath(allocator);
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
            try appendFmt(allocator, &out, "{s} {s}disabled slow-strikes={d}/{d}\n", .{ name, badge, slow_strikes, plugin_slow_strike_limit });
        } else if (disabled) {
            try appendFmt(allocator, &out, "{s} {s}disabled\n", .{ name, badge });
        } else if (slow_strikes > 0) {
            try appendFmt(allocator, &out, "{s} {s}slow-strikes={d}/{d}\n", .{ name, badge, slow_strikes, plugin_slow_strike_limit });
        } else {
            try appendFmt(allocator, &out, "{s} {s}enabled\n", .{ name, badge });
        }
    }
    return out.toOwnedSlice(allocator);
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
    try appendFmt(allocator, out, "{s}:list\n", .{label});
    const sorted = try allocator.dupe([]const u8, items);
    defer allocator.free(sorted);
    std.mem.sort([]const u8, sorted, {}, lessThanString);
    for (sorted) |item| try appendFmt(allocator, out, "{s}\n", .{item});
}

fn appendListCapability(allocator: std.mem.Allocator, out: *std.ArrayList(u8), label: []const u8, capability: plugin_manifest.ListCapability) !void {
    switch (capability) {
        .deny => try appendFmt(allocator, out, "{s}:deny\n", .{label}),
        .allow => |items| try appendCapabilityStringList(allocator, out, label, items),
    }
}

fn appendCapabilityBool(allocator: std.mem.Allocator, out: *std.ArrayList(u8), label: []const u8, value: bool) !void {
    try appendFmt(allocator, out, "{s}:bool:{s}\n", .{ label, if (value) "true" else "false" });
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
                try appendFmt(allocator, &out, "{s} {s}\n", .{ name, fingerprint });
                replaced = true;
            } else {
                try appendFmt(allocator, &out, "{s} {s}\n", .{ record.name, record.fingerprint });
            }
        }
    }

    if (!replaced) try appendFmt(allocator, &out, "{s} {s}\n", .{ name, fingerprint });
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
    const config = try parsePluginInstallArgs(&.{ "https://example.com/plugin.git", "--yes", "--plugin-sandbox-strict" });
    try std.testing.expectEqualStrings("https://example.com/plugin.git", config.url);
    try std.testing.expect(config.yes);
    try std.testing.expect(config.strict);
    try std.testing.expectError(error.UnknownPluginArgument, parsePluginInstallArgs(&.{"--yes"}));
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
    const equals_config = try parsePluginTrustArgs(&.{ "shisa.ai", "--net=openai" });
    try std.testing.expectEqualStrings("shisa.ai", equals_config.name);
    try std.testing.expectEqualStrings("openai", equals_config.net.?);

    const spaced_config = try parsePluginTrustArgs(&.{ "shisa.ai", "--net", "api.example.com" });
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
    try setPluginTrusted(allocator, trusted_path, "shisa.ai");
    try setPluginTrustedNet(allocator, trusted_path, "shisa.ai", "openai");
    try setPluginTrustedNet(allocator, trusted_path, "shisa.ai", "openai");
    try std.testing.expect(try pluginTrustedNet(allocator, trusted_path, "shisa.ai", "openai"));
    try std.testing.expect(!(try pluginTrustedNet(allocator, trusted_path, "shisa.ai", "anthropic")));

    const contents_path = try trustedNetProvidersPathAlloc(allocator, trusted_path);
    defer allocator.free(contents_path);
    const contents = try std.fs.cwd().readFileAlloc(allocator, contents_path, 4096);
    defer allocator.free(contents);
    try std.testing.expectEqualStrings("shisa.ai openai\n", contents);
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
    try setPluginTrusted(allocator, trusted_path, "shisa.ai");
    try setPluginTrustedNet(allocator, trusted_path, "shisa.ai", "openai");

    const openai = plugin_manifest.Manifest{
        .name = "shisa.ai",
        .version = "1.0.0",
        .api_version = plugin_manifest.supported_api_version,
        .license = "MIT",
        .capabilities = .{ .net = .{ .allow = &.{"openai"} } },
        .modules = &.{"ai"},
    };
    const anthropic = plugin_manifest.Manifest{
        .name = "shisa.ai",
        .version = "1.0.0",
        .api_version = plugin_manifest.supported_api_version,
        .license = "MIT",
        .capabilities = .{ .net = .{ .allow = &.{"anthropic"} } },
        .modules = &.{"ai"},
    };
    const openai_exec = plugin_manifest.Manifest{
        .name = "shisa.ai",
        .version = "1.0.0",
        .api_version = plugin_manifest.supported_api_version,
        .license = "MIT",
        .capabilities = .{ .net = .{ .allow = &.{"openai"} }, .exec = .{ .allow = &.{"git"} } },
        .modules = &.{"ai"},
    };

    try std.testing.expect(try pluginTrustedForManifest(allocator, trusted_path, openai));
    try std.testing.expect(!(try pluginTrustedForManifest(allocator, trusted_path, anthropic)));
    try std.testing.expect(!(try pluginTrustedForManifest(allocator, trusted_path, openai_exec)));
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

test "parses bench export json flag" {
    const args = [_][]const u8{ "--export-json", "/tmp/out.json" };
    const config = try parseBench(args[0..]);
    try std.testing.expectEqualStrings("/tmp/out.json", config.export_json.?);
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
            config.socket_path = try nextValue(args, &i);
        } else if (std.mem.eql(u8, arg, "--cwd")) {
            config.cwd = try nextValue(args, &i);
        } else if (std.mem.eql(u8, arg, "--exit")) {
            config.exit = try std.fmt.parseInt(i32, try nextValue(args, &i), 10);
        } else if (std.mem.eql(u8, arg, "--jobs")) {
            config.jobs = try std.fmt.parseInt(u32, try nextValue(args, &i), 10);
        } else if (std.mem.eql(u8, arg, "--duration-ms")) {
            config.duration_ms = try std.fmt.parseInt(u64, try nextValue(args, &i), 10);
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
            config.shell = try nextValue(args, &i);
        } else if (std.mem.eql(u8, arg, "--cols")) {
            config.cols = try std.fmt.parseInt(u16, try nextValue(args, &i), 10);
        } else if (std.mem.eql(u8, arg, "--rows")) {
            config.rows = try std.fmt.parseInt(u16, try nextValue(args, &i), 10);
        } else {
            return error.UnknownPromptArgument;
        }
    }

    return config;
}

fn promptA11yExplanationAlloc(allocator: std.mem.Allocator) ![]u8 {
    const path = try defaultConfigPath(allocator);
    defer allocator.free(path);
    const source = try readConfigOrDefault(allocator, path);
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

    const theme_path = try themePathAlloc(allocator, parsed.theme);
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
        const label = if (findThemeSegment(theme, id)) |segment|
            if (segment.a11y.len > 0) segment.a11y else coreA11yLabel(module_id)
        else
            coreA11yLabel(module_id);
        try appendFmt(allocator, &out, "  {s}: {s}\n", .{ id, label });
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
    const config_path = try defaultConfigPath(allocator);
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

fn nextValue(args: []const []const u8, index: *usize) ![]const u8 {
    if (index.* + 1 >= args.len) return error.MissingValue;
    index.* += 1;
    return args[index.*];
}

const PromptModuleOptions = struct {
    rtl_reverse: bool = false,
    modules: []const shisa_config.ModuleId,
    right_modules: []const shisa_config.ModuleId,
    owns_modules: bool = false,
    cwd: shisa_config.CwdOptions,
    cloud_ctx: shisa_config.CloudCtxOptions,
    cdhint: shisa_config.CdhintOptions,
    tmux_pane: shisa_config.TmuxPaneOptions,
    risk_tier: shisa_config.RiskTierOptions,
    sso_expiry: shisa_config.SsoExpiryOptions,

    fn deinit(self: *PromptModuleOptions, allocator: std.mem.Allocator) void {
        if (self.owns_modules) {
            allocator.free(self.modules);
            allocator.free(self.right_modules);
        }
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
    const escaped_cwd = try jsonEscapeAlloc(allocator, cwd);
    defer allocator.free(escaped_cwd);
    const escaped_shell = try jsonEscapeAlloc(allocator, config.shell);
    defer allocator.free(escaped_shell);
    const modules_json = try promptModulesJsonAlloc(allocator, module_options.modules);
    defer allocator.free(modules_json);
    const right_modules_json = try promptModulesJsonAlloc(allocator, module_options.right_modules);
    defer allocator.free(right_modules_json);
    const tmux_pane = std.process.getEnvVarOwned(allocator, "TMUX_PANE") catch null;
    defer if (tmux_pane) |value| allocator.free(value);
    const escaped_tmux_pane = try jsonEscapeAlloc(allocator, tmux_pane orelse "");
    defer allocator.free(escaped_tmux_pane);
    const request_id = try std.fmt.allocPrint(allocator, "cli-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(request_id);
    const rtl_reverse = config.rtl_reverse or module_options.rtl_reverse;

    return std.fmt.allocPrint(
        allocator,
        "{{\"v\":1,\"op\":\"render\",\"cwd\":\"{s}\",\"exit\":{d},\"jobs\":{d},\"duration_ms\":{d},\"time\":{},\"no_async\":{},\"shell\":\"{s}\",\"cols\":{d},\"rows\":{d},\"tty\":\"/dev/tty\",\"color_caps\":\"{s}\",\"glyph_caps\":\"{s}\",\"user_id\":{d},\"session\":\"cli\",\"request_id\":\"{s}\",\"modules\":[{s}],\"right_modules\":[{s}],\"tmux_pane\":\"{s}\",\"rtl\":{},\"rtl_reverse\":{},\"cwd_options\":{{\"truncate_to\":{d},\"home_tilde\":{},\"max_width\":{d}}},\"cloud_ctx\":{{\"aws\":{},\"gcp\":{},\"azure\":{},\"kubernetes\":{}}},\"cdhint\":{{\"enabled\":{}}},\"tmux_pane_options\":{{\"enabled\":{}}},\"risk_tier\":{{\"unknown_bg\":\"{s}\",\"dev_bg\":\"{s}\",\"staging_bg\":\"{s}\",\"prod_bg\":\"{s}\"}},\"sso_expiry\":{{\"warning_minutes\":{d}}}}}",
        .{ escaped_cwd, config.exit, config.jobs, config.duration_ms, config.time, config.no_async, escaped_shell, config.cols, config.rows, promptColorCaps(config), promptGlyphCaps(config), std.posix.getuid(), request_id, modules_json, right_modules_json, escaped_tmux_pane, config.rtl, rtl_reverse, module_options.cwd.truncate_to, module_options.cwd.home_tilde, module_options.cwd.max_width, module_options.cloud_ctx.aws, module_options.cloud_ctx.gcp, module_options.cloud_ctx.azure, module_options.cloud_ctx.kubernetes, module_options.cdhint.enabled, module_options.tmux_pane.enabled, risk_tier_module.colorSlotName(module_options.risk_tier.unknown_bg), risk_tier_module.colorSlotName(module_options.risk_tier.dev_bg), risk_tier_module.colorSlotName(module_options.risk_tier.staging_bg), risk_tier_module.colorSlotName(module_options.risk_tier.prod_bg), module_options.sso_expiry.warning_minutes },
    );
}

fn promptModulesJsonAlloc(allocator: std.mem.Allocator, modules: []const shisa_config.ModuleId) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);
    for (modules, 0..) |module_id, index| {
        if (index != 0) try out.appendSlice(allocator, ",");
        try appendFmt(allocator, &out, "\"{s}\"", .{shisa_config.moduleIdName(module_id)});
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
        .rtl_reverse = false,
        .modules = default_prompt_modules[0..],
        .right_modules = &.{},
        .cwd = .{},
        .cloud_ctx = .{},
        .cdhint = .{},
        .tmux_pane = .{},
        .risk_tier = .{},
        .sso_expiry = .{},
    };
}

fn promptModuleOptions(allocator: std.mem.Allocator) !PromptModuleOptions {
    const path = try defaultConfigPath(allocator);
    defer allocator.free(path);
    const source = try readConfigOrDefault(allocator, path);
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
    return .{
        .rtl_reverse = parsed.prompt.rtl_reverse,
        .modules = modules,
        .right_modules = right_modules,
        .owns_modules = true,
        .cwd = parsed.modules.cwd,
        .cloud_ctx = parsed.modules.cloud_ctx,
        .cdhint = parsed.modules.cdhint,
        .tmux_pane = parsed.modules.tmux_pane,
        .risk_tier = parsed.modules.risk_tier,
        .sso_expiry = parsed.modules.sso_expiry,
    };
}

fn jsonEscapeAlloc(allocator: std.mem.Allocator, value: []const u8) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);

    for (value) |byte| {
        switch (byte) {
            '"' => try out.appendSlice(allocator, "\\\""),
            '\\' => try out.appendSlice(allocator, "\\\\"),
            '\n' => try out.appendSlice(allocator, "\\n"),
            '\r' => try out.appendSlice(allocator, "\\r"),
            '\t' => try out.appendSlice(allocator, "\\t"),
            else => try out.append(allocator, byte),
        }
    }

    return out.toOwnedSlice(allocator);
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

test "prompt payload carries right modules" {
    var options = defaultPromptModuleOptions();
    options.right_modules = &.{.time};
    const payload = try buildPromptPayloadWithModuleOptions(std.testing.allocator, .{}, "/tmp", options);
    defer std.testing.allocator.free(payload);
    try std.testing.expect(std.mem.indexOf(u8, payload, "\"right_modules\":[\"time\"]") != null);
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
    \\  ai            local AI helpers: status, redact, bench, risk, explain, nextcmd, nl2cmd
    \\  bench         benchmark prompt render via hyperfine
    \\  cache         dump or clear cache state
    \\  cloud         cloud helpers: audit, doctor, explain, preexec
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
    \\  init          write default shisa.toml; --a11y uses the a11y theme
    \\  pin           mark a path as never-evicted
    \\  plugin        new, lint, doctor, pack, install, list, enable, disable, or trust plugins
    \\  prompt        render prompt through shisad; --right prints configured right prompt
    \\  render        alias for prompt; --explain-a11y dumps segment labels
    \\  report        write a redacted support bundle .tar.gz
    \\  stack         dump detected stacked-diff metadata
    \\  supervisor    run shisad under a crash-restart supervisor
    \\  theme         validate theme files
    \\  vouch         verify VOUCHES governance file
    \\  worktrees     list Git worktrees and mark active
    \\
    \\options:
    \\  -h, --help    print help
    \\      --version print version
    \\
;

const ai_help_text =
    \\usage: shisa ai <command> [args]
    \\
    \\commands:
    \\  status        show local model, cloud provider, and audit status
    \\  redact        test or edit local redaction literal rules
    \\  bench         benchmark local Ollama cold/warm/memory
    \\  risk          classify command risk
    \\  explain       explain a command
    \\  nextcmd       suggest a next command from local context
    \\  nl2cmd        convert ?? input to a command suggestion
    \\
;

const ai_redact_help_text =
    \\usage: shisa ai redact (--test text | --add-literal text) [--rules path]
    \\
    \\options:
    \\      --test <text>        print built-in + local-rule redacted text
    \\      --add-literal <text> append a literal local redaction rule
    \\      --rules <path>       override rules file; default is config dir ai-redact.rules
    \\
;

const report_help_text =
    \\usage: shisa report [--output path]
    \\
    \\options:
    \\  -o, --output <path> write bundle path; defaults to ./shisa-report-<timestamp>.tar.gz
    \\
;

const vouch_help_text =
    \\usage: shisa vouch verify [path]
    \\
    \\commands:
    \\  verify [path] validate VOUCHES format; defaults to ./VOUCHES
    \\
;

const theme_help_text =
    \\usage: shisa theme <command> [args]
    \\
    \\commands:
    \\  validate <path>   validate a theme file
    \\  preview <theme>   render a stub prompt from a built-in id or theme file
    \\  gallery [--no-open]
    \\                    generate a local static gallery and open it
    \\
;

const font_help_text =
    \\usage: shisa font check
    \\
    \\commands:
    \\  check         render Nerd Font, Unicode, and ASCII glyph probes
    \\
;
