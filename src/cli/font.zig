const std = @import("std");

pub fn fontCmd(allocator: std.mem.Allocator, args: []const []const u8) !void {
    if (args.len == 0 or std.mem.eql(u8, args[0], "--help") or std.mem.eql(u8, args[0], "-h")) {
        try std.fs.File.stdout().writeAll(help_text);
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

const help_text =
    \\usage: shisa font check
    \\
    \\commands:
    \\  check         render Nerd Font, Unicode, and ASCII glyph probes
    \\
;
