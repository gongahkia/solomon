const std = @import("std");
const dispatcher = @import("../daemon/dispatcher.zig");
const theme_contrast = @import("../theme/contrast.zig");
const theme_loader = @import("../theme/loader.zig");

pub const max_config_bytes = 1024 * 1024;

pub const help_text =
    \\usage: shisa theme <command> [args]
    \\
    \\commands:
    \\  validate <path>   validate a theme file
    \\  preview <theme>   render a stub prompt from a built-in id or theme file
    \\
;

pub const built_in_theme_ids = [_][]const u8{
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

const default_preview_segments = [_][]const u8{ "cwd", "git_branch", "exit_status", "jobs", "cmd_duration" };

pub fn command(allocator: std.mem.Allocator, args: []const []const u8) !void {
    if (args.len == 0 or std.mem.eql(u8, args[0], "--help") or std.mem.eql(u8, args[0], "-h")) {
        try std.fs.File.stdout().writeAll(help_text);
        return;
    }
    if (std.mem.eql(u8, args[0], "validate")) {
        if (args.len != 2) return error.MissingThemePath;
        try validateCommand(allocator, args[1]);
        return;
    }
    if (std.mem.eql(u8, args[0], "preview")) {
        if (args.len != 2) return error.MissingThemePath;
        try previewCommand(allocator, args[1]);
        return;
    }
    return error.UnknownThemeCommand;
}

fn validateCommand(allocator: std.mem.Allocator, path: []const u8) !void {
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

fn previewCommand(allocator: std.mem.Allocator, theme_arg: []const u8) !void {
    const path = try pathAlloc(allocator, theme_arg);
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

    const preview = try previewAlloc(allocator, theme, 80);
    defer allocator.free(preview);
    try std.fs.File.stdout().writeAll(preview);
}

pub fn pathAlloc(allocator: std.mem.Allocator, theme_arg: []const u8) ![]u8 {
    for (built_in_theme_ids) |id| {
        if (std.mem.eql(u8, theme_arg, id)) return std.fmt.allocPrint(allocator, "themes/{s}.toml", .{id});
    }
    return allocator.dupe(u8, theme_arg);
}

pub fn previewAlloc(allocator: std.mem.Allocator, theme: theme_loader.Theme, cols: u16) ![]u8 {
    return previewAllocWithCwd(allocator, theme, cols, "~/work/shisa");
}

pub fn previewAllocWithCwd(allocator: std.mem.Allocator, theme: theme_loader.Theme, cols: u16, cwd: []const u8) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);

    if (theme.layout.lines.len == 0) {
        const left = try renderSegmentListAlloc(allocator, theme, default_preview_segments[0..], cwd);
        defer allocator.free(left);
        const line = try dispatcher.renderAlignedLineAlloc(allocator, left, "", cols);
        defer allocator.free(line);
        try out.appendSlice(allocator, line);
        try out.append(allocator, '\n');
    } else {
        for (theme.layout.lines) |layout_line| {
            const left = try renderSegmentListAlloc(allocator, theme, layout_line.left, cwd);
            defer allocator.free(left);
            const right = try renderSegmentListAlloc(allocator, theme, layout_line.right, cwd);
            defer allocator.free(right);
            const line = try dispatcher.renderAlignedLineAlloc(allocator, left, right, cols);
            defer allocator.free(line);
            try out.appendSlice(allocator, line);
            try out.append(allocator, '\n');
        }
    }

    return out.toOwnedSlice(allocator);
}

fn renderSegmentListAlloc(allocator: std.mem.Allocator, theme: theme_loader.Theme, ids: anytype, cwd: []const u8) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);
    for (ids, 0..) |id, index| {
        if (index > 0) try out.appendSlice(allocator, theme.separators.segment);
        const rendered = try renderSegmentAlloc(allocator, theme, id, cwd);
        defer allocator.free(rendered);
        try out.appendSlice(allocator, rendered);
    }
    return out.toOwnedSlice(allocator);
}

fn renderSegmentAlloc(allocator: std.mem.Allocator, theme: theme_loader.Theme, id: []const u8, cwd: []const u8) ![]u8 {
    const segment = findSegment(theme, id) orelse return allocator.dupe(u8, previewValue(id, cwd));
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);
    var styled = false;

    styled = try appendSegmentColorSgr(allocator, &out, theme, segment.fg, .foreground) or styled;
    styled = try appendSegmentColorSgr(allocator, &out, theme, segment.bg, .background) or styled;
    styled = try appendStyleSgr(&out, allocator, segment.style) or styled;

    try out.appendSlice(allocator, theme.separators.left);
    try out.appendSlice(allocator, segment.prefix);
    try out.appendSlice(allocator, theme_loader.resolveSegmentGlyph(segment, glyphTierForTheme(theme)));
    try out.appendSlice(allocator, previewValue(id, cwd));
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

pub fn findSegment(theme: theme_loader.Theme, id: []const u8) ?theme_loader.Segment {
    for (theme.segments) |segment| {
        if (std.mem.eql(u8, segment.id, id)) return segment;
    }
    return null;
}

pub fn glyphTierForTheme(theme: theme_loader.Theme) theme_loader.GlyphTier {
    return switch (theme.capabilities.glyphs) {
        .nerd_font => .nerdfont,
        .ascii => .ascii,
    };
}

pub fn colorCapsForTheme(theme: theme_loader.Theme) theme_contrast.ColorCaps {
    return switch (theme.capabilities.color) {
        .truecolor => .truecolor,
        .ansi256 => .@"256",
        .ansi => .@"16",
        .none => .none,
    };
}

fn previewValue(id: []const u8, cwd: []const u8) []const u8 {
    if (std.mem.eql(u8, id, "cwd")) return cwd;
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
    const preview = try previewAlloc(std.testing.allocator, theme, 80);
    defer std.testing.allocator.free(preview);

    try std.testing.expect(std.mem.indexOf(u8, preview, "~/work/shisa") != null);
    try std.testing.expect(std.mem.indexOf(u8, preview, "git:main*") != null);
    try std.testing.expect(std.mem.indexOf(u8, preview, "exit:2") != null);
    try std.testing.expect(std.mem.indexOf(u8, preview, "jobs:2") != null);
    try std.testing.expect(std.mem.indexOf(u8, preview, "took:1.5s") != null);
}

test "theme preview can render supplied cwd" {
    const source =
        \\version = 1
        \\name = "preview-cwd"
        \\
        \\[palette]
        \\fg = "15"
        \\
        \\[segments.cwd]
        \\fg = "@fg"
        \\
    ;
    var diagnostic: theme_loader.Diagnostic = .{};
    var theme = try theme_loader.parse(std.testing.allocator, source, &diagnostic);
    defer theme.deinit(std.testing.allocator);
    const preview = try previewAllocWithCwd(std.testing.allocator, theme, 80, "/tmp/shisa-wizard");
    defer std.testing.allocator.free(preview);

    try std.testing.expect(std.mem.indexOf(u8, preview, "/tmp/shisa-wizard") != null);
}
