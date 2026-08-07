const std = @import("std");
const build_options = @import("build_options");
const cli_bench = @import("cli/bench.zig");
const cli_import = @import("cli/import.zig");
const cli_prompt = @import("cli/prompt.zig");
const cli_cache = @import("cli/cache.zig");
const cli_cloud = @import("cli/cloud.zig");
const cli_config = @import("cli/config.zig");
const cli_doctor = @import("cli/doctor.zig");
const cli_font = @import("cli/font.zig");
const cli_pin = @import("cli/pin.zig");
const cli_plugin = @import("cli/plugin.zig");
const cli_stack = @import("cli/stack.zig");
const cli_theme = @import("cli/theme.zig");
const cli_uninstall = @import("cli/uninstall.zig");
const cli_update = @import("cli/update.zig");
const cli_util = @import("cli/util.zig");
const cli_vouch = @import("cli/vouch.zig");
const cli_worktree = @import("cli/worktree.zig");
const supervisor = @import("supervisor.zig");

const version = "0.1.0-dev";

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

    if (std.mem.eql(u8, args[1], "trace")) {
        try cli_prompt.traceCmd(allocator, args[2..]);
        return;
    }

    if (std.mem.eql(u8, args[1], "report")) {
        try cli_doctor.reportCommand(allocator, args[2..], .{ .version = version, .iteration = cli_prompt.reportPromptPayloadBenchIterationAlloc });
        return;
    }

    if (std.mem.eql(u8, args[1], "font")) {
        try cli_font.fontCmd(allocator, args[2..]);
        return;
    }

    if (std.mem.eql(u8, args[1], "vouch")) {
        try cli_vouch.vouchCmd(allocator, args[2..]);
        return;
    }

    if (std.mem.eql(u8, args[1], "cloud")) {
        try cli_cloud.cloudCmd(allocator, args[2..]);
        return;
    }

    if (std.mem.eql(u8, args[1], "import-starship")) {
        try cli_import.importStarshipCmd(allocator, args[2..]);
        return;
    }

    if (std.mem.eql(u8, args[1], "import-p10k")) {
        try cli_import.importP10kCmd(allocator, args[2..]);
        return;
    }

    if (std.mem.eql(u8, args[1], "import-oh-my-posh")) {
        try cli_import.importOhMyPoshCmd(allocator, args[2..]);
        return;
    }

    if (std.mem.eql(u8, args[1], "import-tide")) {
        try cli_import.importTideCmd(allocator, args[2..]);
        return;
    }

    if (std.mem.eql(u8, args[1], "import-pure")) {
        try cli_import.importPureCmd(allocator, args[2..]);
        return;
    }

    if (std.mem.eql(u8, args[1], "bench")) {
        try cli_bench.benchCmd(allocator, args[2..]);
        return;
    }

    if (std.mem.eql(u8, args[1], "cache")) {
        try cli_cache.cacheCmd(allocator, args[2..]);
        return;
    }

    if (std.mem.eql(u8, args[1], "pin")) {
        try cli_pin.pinCmd(allocator, args[2..]);
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

    if (std.mem.eql(u8, args[1], "uninstall")) {
        try cli_uninstall.command(allocator, args[2..]);
        return;
    }

    if (std.mem.eql(u8, args[1], "update")) {
        try cli_update.updateCmd(allocator, args[2..]);
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
        try cli_prompt.promptCmd(allocator, args[2..]);
        return;
    }

    try std.fs.File.stderr().writeAll("shisa: unknown command; run `shisa --help`\n");
    return error.UnknownCommand;
}

test "smoke" {
    try std.testing.expect(true);
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
    \\  import-starship <path> [--dry-run|--diff] [--output PATH]
    \\                translate starship.toml to shisa.toml
    \\  import-p10k <path> [--dry-run|--diff] [--output PATH]
    \\                translate .p10k.zsh to shisa.toml
    \\  import-oh-my-posh <path> [--dry-run|--diff] [--output PATH]
    \\                translate Oh My Posh JSON/YAML to shisa.toml
    \\  import-tide <path> [--dry-run|--diff] [--output PATH]
    \\                translate Tide fish settings to shisa.toml
    \\  import-pure [--dry-run|--diff] [--output PATH]
    \\                print the minimal Pure-compatible preset
    \\  init          first-run wizard; --defaults writes without prompting
    \\  pin           mark a path as never-evicted
    \\  plugin        new, lint, doctor, verify, pack, install, list, enable, disable, or trust plugins
    \\  prompt        render prompt through shisad; --right or --transient select variants
    \\  render        alias for prompt; --explain-a11y dumps segment labels
    \\  report        write a redacted support bundle .tar.gz
    \\  supervisor    run shisad under a crash-restart supervisor
    \\  theme         validate theme files
    \\  trace         render once with module timing trace on stderr
    \\  uninstall     remove shell hooks and optionally purge local state
    \\  update        fetch, verify, and install a release artifact
    \\  vouch         verify VOUCHES governance file
    \\
    \\options:
    \\  -h, --help    print help
    \\      --version print version
    \\
;
