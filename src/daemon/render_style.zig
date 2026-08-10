const std = @import("std");
const dispatcher = @import("dispatcher.zig");
const theme_loader = @import("theme_loader");

pub const RequestColorCaps = enum {
    truecolor,
    @"256",
    @"16",
    none,
};

pub const RequestGlyphCaps = enum {
    nerdfont,
    unicode,
    ascii,
};

pub const State = struct {
    theme: theme_loader.Theme,

    pub fn deinit(self: *State, allocator: std.mem.Allocator) void {
        self.theme.deinit(allocator);
        self.* = undefined;
    }

    pub fn styleFor(self: *const State, color_caps: RequestColorCaps, glyph_caps: RequestGlyphCaps) dispatcher.StyleConfig {
        return .{
            .theme = &self.theme,
            .color_caps = effectiveThemeColorCaps(self.theme, color_caps),
            .glyph_tier = effectiveThemeGlyphTier(self.theme, glyph_caps),
        };
    }
};

pub fn loadAlloc(allocator: std.mem.Allocator, theme_arg: []const u8, color_caps: RequestColorCaps, glyph_caps: RequestGlyphCaps) !State {
    const theme_path = try themePathAlloc(allocator, theme_arg);
    defer allocator.free(theme_path);
    const theme_source = try std.fs.cwd().readFileAlloc(allocator, theme_path, 1024 * 1024);
    defer allocator.free(theme_source);
    var diagnostic: theme_loader.Diagnostic = .{};
    var theme = try theme_loader.parse(allocator, theme_source, &diagnostic);
    errdefer theme.deinit(allocator);
    _ = color_caps;
    _ = glyph_caps;
    return .{ .theme = theme };
}

fn themePathAlloc(allocator: std.mem.Allocator, theme_arg: []const u8) ![]u8 {
    if (themePathForBuiltInId(theme_arg)) |path| return allocator.dupe(u8, path);
    if (std.mem.startsWith(u8, theme_arg, "~/")) {
        const home = try std.process.getEnvVarOwned(allocator, "HOME");
        defer allocator.free(home);
        return std.fmt.allocPrint(allocator, "{s}/{s}", .{ home, theme_arg[2..] });
    }
    return allocator.dupe(u8, theme_arg);
}

fn themePathForBuiltInId(id: []const u8) ?[]const u8 {
    if (std.mem.eql(u8, id, "plain")) return "themes/plain.toml";
    if (std.mem.eql(u8, id, "minimal-monochrome")) return "themes/minimal-monochrome.toml";
    if (std.mem.eql(u8, id, "okiya-night")) return "themes/okiya-night.toml";
    if (std.mem.eql(u8, id, "okiya-day")) return "themes/okiya-day.toml";
    if (std.mem.eql(u8, id, "nord-dark")) return "themes/nord-dark.toml";
    if (std.mem.eql(u8, id, "gruvbox-rainbow")) return "themes/gruvbox-rainbow.toml";
    if (std.mem.eql(u8, id, "tokyo-night")) return "themes/tokyo-night.toml";
    if (std.mem.eql(u8, id, "pure")) return "themes/pure.toml";
    if (std.mem.eql(u8, id, "a11y")) return "themes/a11y.toml";
    return null;
}

fn effectiveThemeColorCaps(theme: theme_loader.Theme, request_caps: RequestColorCaps) theme_loader.contrast.ColorCaps {
    const theme_caps = switch (theme.capabilities.color) {
        .truecolor => theme_loader.contrast.ColorCaps.truecolor,
        .ansi256 => theme_loader.contrast.ColorCaps.@"256",
        .ansi => theme_loader.contrast.ColorCaps.@"16",
        .none => theme_loader.contrast.ColorCaps.none,
    };
    const request_theme_caps = switch (request_caps) {
        .truecolor => theme_loader.contrast.ColorCaps.truecolor,
        .@"256" => theme_loader.contrast.ColorCaps.@"256",
        .@"16" => theme_loader.contrast.ColorCaps.@"16",
        .none => theme_loader.contrast.ColorCaps.none,
    };
    return if (colorCapRank(theme_caps) <= colorCapRank(request_theme_caps)) theme_caps else request_theme_caps;
}

fn colorCapRank(caps: theme_loader.contrast.ColorCaps) u8 {
    return switch (caps) {
        .none => 0,
        .@"16" => 1,
        .@"256" => 2,
        .truecolor => 3,
    };
}

fn effectiveThemeGlyphTier(theme: theme_loader.Theme, request_caps: RequestGlyphCaps) theme_loader.GlyphTier {
    return switch (request_caps) {
        .ascii => .ascii,
        .unicode => switch (theme.capabilities.glyphs) {
            .ascii => .ascii,
            .nerd_font => .unicode,
        },
        .nerdfont => switch (theme.capabilities.glyphs) {
            .ascii => .ascii,
            .nerd_font => .nerdfont,
        },
    };
}
