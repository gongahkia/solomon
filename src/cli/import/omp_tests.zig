const std = @import("std");
const omp = @import("omp.zig");
const common = @import("common.zig");

const OmpTheme = omp.OmpTheme;
const StarshipImport = common.StarshipImport;
const parseOmpTheme = omp.parseOmpTheme;
const scanOmpTheme = omp.scanOmpTheme;
const translateOmpTemplateLayoutAlloc = omp.translateOmpTemplateLayoutAlloc;
const importOhMyPoshResultAlloc = omp.importOhMyPoshResultAlloc;
const appendOmpPaletteEntry = omp.appendOmpPaletteEntry;
const mapOmpPalette = omp.mapOmpPalette;
const nearestMappedPaletteSlot = omp.nearestMappedPaletteSlot;
const containsModule = common.containsModule;

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
