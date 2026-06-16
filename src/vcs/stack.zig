const std = @import("std");

pub const module_id = "vcs_stack";

pub const Provider = enum {
    graphite,
    ghstack,
    spr,
    stax,
    git_spice,
    git_town,
    github_stack,

    pub fn label(self: Provider) []const u8 {
        return switch (self) {
            .graphite => "graphite",
            .ghstack => "ghstack",
            .spr => "spr",
            .stax => "st",
            .git_spice => "gs",
            .git_town => "git-town",
            .github_stack => "gh-stack",
        };
    }
};

pub const Detection = struct {
    provider: Provider,
    root_path: []u8,
    marker_path: []u8,
    branch_name: ?[]u8 = null,

    pub fn deinit(self: *Detection, allocator: std.mem.Allocator) void {
        allocator.free(self.root_path);
        allocator.free(self.marker_path);
        if (self.branch_name) |branch_name| allocator.free(branch_name);
        self.* = undefined;
    }
};

const GitBranch = struct {
    root_path: []u8,
    head_path: []u8,
    branch_name: []u8,

    fn deinit(self: *GitBranch, allocator: std.mem.Allocator) void {
        allocator.free(self.root_path);
        allocator.free(self.head_path);
        allocator.free(self.branch_name);
        self.* = undefined;
    }
};

pub fn detect(allocator: std.mem.Allocator, cwd_path: []const u8) !?Detection {
    if (try findMarkerRoot(allocator, cwd_path, ".graphite_repo_config")) |root| {
        errdefer allocator.free(root);
        const marker_path = try std.fs.path.join(allocator, &.{ root, ".graphite_repo_config" });
        return .{
            .provider = .graphite,
            .root_path = root,
            .marker_path = marker_path,
        };
    }
    if (try detectGhstack(allocator, cwd_path)) |detection| return detection;
    if (try detectSpr(allocator, cwd_path)) |detection| return detection;
    if (try detectStax(allocator, cwd_path)) |detection| return detection;
    if (try detectGitSpice(allocator, cwd_path)) |detection| return detection;
    if (try detectGitTown(allocator, cwd_path)) |detection| return detection;
    if (try detectGithubStack(allocator, cwd_path)) |detection| return detection;
    return null;
}

pub fn isGraphiteStack(allocator: std.mem.Allocator, cwd_path: []const u8) !bool {
    const found = try findMarkerRoot(allocator, cwd_path, ".graphite_repo_config");
    if (found) |root| {
        allocator.free(root);
        return true;
    }
    return false;
}

pub fn isGhstackBranchName(branch_name: []const u8) bool {
    var parts = std.mem.splitScalar(u8, branch_name, '/');
    const prefix = parts.next() orelse return false;
    const user = parts.next() orelse return false;
    const number = parts.next() orelse return false;
    const suffix = parts.next() orelse return false;
    if (parts.next() != null) return false;
    if (!std.mem.eql(u8, prefix, "gh") or user.len == 0 or number.len == 0) return false;
    for (number) |byte| {
        if (!std.ascii.isDigit(byte)) return false;
    }
    return std.mem.eql(u8, suffix, "base") or std.mem.eql(u8, suffix, "head") or std.mem.eql(u8, suffix, "orig");
}

pub fn isGhstack(allocator: std.mem.Allocator, cwd_path: []const u8) !bool {
    const detection = try detectGhstack(allocator, cwd_path);
    if (detection) |value| {
        var owned = value;
        owned.deinit(allocator);
        return true;
    }
    return false;
}

pub fn isSpr(allocator: std.mem.Allocator, cwd_path: []const u8) !bool {
    const detection = try detectSpr(allocator, cwd_path);
    if (detection) |value| {
        var owned = value;
        owned.deinit(allocator);
        return true;
    }
    return false;
}

pub fn isStax(allocator: std.mem.Allocator, cwd_path: []const u8) !bool {
    const detection = try detectStax(allocator, cwd_path);
    if (detection) |value| {
        var owned = value;
        owned.deinit(allocator);
        return true;
    }
    return false;
}

pub fn isGitSpice(allocator: std.mem.Allocator, cwd_path: []const u8) !bool {
    const detection = try detectGitSpice(allocator, cwd_path);
    if (detection) |value| {
        var owned = value;
        owned.deinit(allocator);
        return true;
    }
    return false;
}

pub fn isGitTown(allocator: std.mem.Allocator, cwd_path: []const u8) !bool {
    const detection = try detectGitTown(allocator, cwd_path);
    if (detection) |value| {
        var owned = value;
        owned.deinit(allocator);
        return true;
    }
    return false;
}

pub fn isGithubStack(allocator: std.mem.Allocator, cwd_path: []const u8) !bool {
    const detection = try detectGithubStack(allocator, cwd_path);
    if (detection) |value| {
        var owned = value;
        owned.deinit(allocator);
        return true;
    }
    return false;
}

fn detectGhstack(allocator: std.mem.Allocator, cwd_path: []const u8) !?Detection {
    if (try readCurrentGitBranch(allocator, cwd_path)) |git_branch| {
        var branch = git_branch;
        if (isGhstackBranchName(branch.branch_name)) {
            return .{
                .provider = .ghstack,
                .root_path = branch.root_path,
                .marker_path = branch.head_path,
                .branch_name = branch.branch_name,
            };
        }
        branch.deinit(allocator);
    }

    if (try findMarkerRoot(allocator, cwd_path, ".ghstackrc")) |root| {
        errdefer allocator.free(root);
        const marker_path = try std.fs.path.join(allocator, &.{ root, ".ghstackrc" });
        return .{
            .provider = .ghstack,
            .root_path = root,
            .marker_path = marker_path,
        };
    }
    return null;
}

fn detectSpr(allocator: std.mem.Allocator, cwd_path: []const u8) !?Detection {
    const root = (try findMarkerRoot(allocator, cwd_path, ".git")) orelse return null;
    errdefer allocator.free(root);
    const marker_path = try std.fs.path.join(allocator, &.{ root, ".git", "refs", "spr" });

    std.fs.cwd().access(marker_path, .{}) catch |err| switch (err) {
        error.FileNotFound => {
            allocator.free(root);
            allocator.free(marker_path);
            return null;
        },
        else => {
            allocator.free(marker_path);
            return err;
        },
    };
    return .{
        .provider = .spr,
        .root_path = root,
        .marker_path = marker_path,
    };
}

fn detectStax(allocator: std.mem.Allocator, cwd_path: []const u8) !?Detection {
    const root = (try findMarkerRoot(allocator, cwd_path, ".git")) orelse return null;
    errdefer allocator.free(root);

    const metadata_path = try std.fs.path.join(allocator, &.{ root, ".git", "refs", "branch-metadata" });
    const has_metadata = pathExists(metadata_path) catch |err| {
        allocator.free(metadata_path);
        return err;
    };
    if (has_metadata) {
        return .{
            .provider = .stax,
            .root_path = root,
            .marker_path = metadata_path,
        };
    }
    allocator.free(metadata_path);

    const refs_path = try std.fs.path.join(allocator, &.{ root, ".git", "refs", "stax" });
    const has_refs = pathExists(refs_path) catch |err| {
        allocator.free(refs_path);
        return err;
    };
    if (has_refs) {
        return .{
            .provider = .stax,
            .root_path = root,
            .marker_path = refs_path,
        };
    }
    allocator.free(refs_path);

    const config_path = try std.fs.path.join(allocator, &.{ root, "stax.toml" });
    const has_config = pathExists(config_path) catch |err| {
        allocator.free(config_path);
        return err;
    };
    if (has_config) {
        return .{
            .provider = .stax,
            .root_path = root,
            .marker_path = config_path,
        };
    }
    allocator.free(config_path);
    allocator.free(root);
    return null;
}

fn detectGitSpice(allocator: std.mem.Allocator, cwd_path: []const u8) !?Detection {
    const root = (try findMarkerRoot(allocator, cwd_path, ".git")) orelse return null;
    errdefer allocator.free(root);

    const data_ref_path = try std.fs.path.join(allocator, &.{ root, ".git", "refs", "spice", "data" });
    const has_data_ref = pathExists(data_ref_path) catch |err| {
        allocator.free(data_ref_path);
        return err;
    };
    if (has_data_ref) {
        return .{
            .provider = .git_spice,
            .root_path = root,
            .marker_path = data_ref_path,
        };
    }
    allocator.free(data_ref_path);

    const namespace_path = try std.fs.path.join(allocator, &.{ root, ".git", "refs", "spice" });
    const has_namespace = pathExists(namespace_path) catch |err| {
        allocator.free(namespace_path);
        return err;
    };
    if (has_namespace) {
        return .{
            .provider = .git_spice,
            .root_path = root,
            .marker_path = namespace_path,
        };
    }
    allocator.free(namespace_path);

    const packed_refs_path = try std.fs.path.join(allocator, &.{ root, ".git", "packed-refs" });
    errdefer allocator.free(packed_refs_path);
    if (try packedRefsContains(allocator, packed_refs_path, "refs/spice/data")) {
        return .{
            .provider = .git_spice,
            .root_path = root,
            .marker_path = packed_refs_path,
        };
    }
    allocator.free(packed_refs_path);
    allocator.free(root);
    return null;
}

fn detectGitTown(allocator: std.mem.Allocator, cwd_path: []const u8) !?Detection {
    const marker_names = [_][]const u8{ ".git-town-branches.yml", "git-town.toml", ".git-town.toml", ".git-branches.toml" };
    for (&marker_names) |marker_name| {
        if (try findMarkerRoot(allocator, cwd_path, marker_name)) |root| {
            errdefer allocator.free(root);
            const marker_path = try std.fs.path.join(allocator, &.{ root, marker_name });
            return .{
                .provider = .git_town,
                .root_path = root,
                .marker_path = marker_path,
            };
        }
    }

    const root = (try findMarkerRoot(allocator, cwd_path, ".git")) orelse return null;
    errdefer allocator.free(root);
    const config_path = try std.fs.path.join(allocator, &.{ root, ".git", "config" });
    errdefer allocator.free(config_path);
    if (try gitConfigContainsGitTown(allocator, config_path)) {
        return .{
            .provider = .git_town,
            .root_path = root,
            .marker_path = config_path,
        };
    }
    allocator.free(config_path);
    allocator.free(root);
    return null;
}

fn detectGithubStack(allocator: std.mem.Allocator, cwd_path: []const u8) !?Detection {
    const root = (try findMarkerRoot(allocator, cwd_path, ".git")) orelse return null;
    errdefer allocator.free(root);

    const stack_path = try std.fs.path.join(allocator, &.{ root, ".git", "gh-stack" });
    const has_stack = pathExists(stack_path) catch |err| {
        allocator.free(stack_path);
        return err;
    };
    if (has_stack) {
        return .{
            .provider = .github_stack,
            .root_path = root,
            .marker_path = stack_path,
        };
    }
    allocator.free(stack_path);

    const rebase_path = try std.fs.path.join(allocator, &.{ root, ".git", "gh-stack-rebase-state" });
    const has_rebase = pathExists(rebase_path) catch |err| {
        allocator.free(rebase_path);
        return err;
    };
    if (has_rebase) {
        return .{
            .provider = .github_stack,
            .root_path = root,
            .marker_path = rebase_path,
        };
    }
    allocator.free(rebase_path);

    const config_path = try std.fs.path.join(allocator, &.{ root, ".git", "config" });
    errdefer allocator.free(config_path);
    if (try gitConfigContainsGithubStack(allocator, config_path)) {
        return .{
            .provider = .github_stack,
            .root_path = root,
            .marker_path = config_path,
        };
    }
    allocator.free(config_path);
    allocator.free(root);
    return null;
}

fn readCurrentGitBranch(allocator: std.mem.Allocator, cwd_path: []const u8) !?GitBranch {
    const root = (try findMarkerRoot(allocator, cwd_path, ".git")) orelse return null;
    const head_path = try std.fs.path.join(allocator, &.{ root, ".git", "HEAD" });
    const head = std.fs.cwd().readFileAlloc(allocator, head_path, 4096) catch {
        allocator.free(root);
        allocator.free(head_path);
        return null;
    };
    defer allocator.free(head);

    const prefix = "ref: refs/heads/";
    if (!std.mem.startsWith(u8, head, prefix)) {
        allocator.free(root);
        allocator.free(head_path);
        return null;
    }
    const raw_branch = std.mem.trim(u8, head[prefix.len..], " \t\r\n");
    if (raw_branch.len == 0) {
        allocator.free(root);
        allocator.free(head_path);
        return null;
    }
    errdefer allocator.free(root);
    errdefer allocator.free(head_path);
    const branch_name = try allocator.dupe(u8, raw_branch);
    return .{
        .root_path = root,
        .head_path = head_path,
        .branch_name = branch_name,
    };
}

fn findMarkerRoot(allocator: std.mem.Allocator, cwd_path: []const u8, marker_name: []const u8) !?[]u8 {
    var current = try allocator.dupe(u8, cwd_path);
    errdefer allocator.free(current);

    while (current.len > 0) {
        const marker_path = try std.fs.path.join(allocator, &.{ current, marker_name });
        const found = found: {
            std.fs.cwd().access(marker_path, .{}) catch |err| switch (err) {
                error.FileNotFound => break :found false,
                else => {
                    allocator.free(marker_path);
                    return err;
                },
            };
            break :found true;
        };
        allocator.free(marker_path);
        if (found) return current;

        const parent = std.fs.path.dirname(current) orelse {
            allocator.free(current);
            break;
        };
        if (std.mem.eql(u8, parent, current)) {
            allocator.free(current);
            break;
        }
        const next = try allocator.dupe(u8, parent);
        allocator.free(current);
        current = next;
    }

    return null;
}

fn pathExists(path: []const u8) !bool {
    std.fs.cwd().access(path, .{}) catch |err| switch (err) {
        error.FileNotFound => return false,
        else => return err,
    };
    return true;
}

fn packedRefsContains(allocator: std.mem.Allocator, path: []const u8, ref_name: []const u8) !bool {
    const contents = std.fs.cwd().readFileAlloc(allocator, path, 1024 * 1024) catch |err| switch (err) {
        error.FileNotFound => return false,
        else => return err,
    };
    defer allocator.free(contents);

    var lines = std.mem.splitScalar(u8, contents, '\n');
    while (lines.next()) |raw_line| {
        const line = std.mem.trim(u8, raw_line, " \t\r");
        if (line.len == 0 or line[0] == '#' or line[0] == '^') continue;
        var fields = std.mem.splitScalar(u8, line, ' ');
        _ = fields.next() orelse continue;
        const ref_field = fields.next() orelse continue;
        if (std.mem.eql(u8, ref_field, ref_name)) return true;
    }
    return false;
}

fn gitConfigContainsGitTown(allocator: std.mem.Allocator, path: []const u8) !bool {
    const contents = std.fs.cwd().readFileAlloc(allocator, path, 256 * 1024) catch |err| switch (err) {
        error.FileNotFound => return false,
        else => return err,
    };
    defer allocator.free(contents);
    return std.mem.indexOf(u8, contents, "[git-town") != null or std.mem.indexOf(u8, contents, "git-town.") != null;
}

fn gitConfigContainsGithubStack(allocator: std.mem.Allocator, path: []const u8) !bool {
    const contents = std.fs.cwd().readFileAlloc(allocator, path, 256 * 1024) catch |err| switch (err) {
        error.FileNotFound => return false,
        else => return err,
    };
    defer allocator.free(contents);
    const has_github_remote = std.mem.indexOf(u8, contents, "github.com") != null;
    const has_stack_keys = std.mem.indexOf(u8, contents, "[stack]") != null or
        std.mem.indexOf(u8, contents, "stackParent") != null or
        std.mem.indexOf(u8, contents, "stackparent") != null or
        std.mem.indexOf(u8, contents, "stackPR") != null or
        std.mem.indexOf(u8, contents, "stackpr") != null;
    return has_github_remote and has_stack_keys;
}

test "detects graphite stack in current directory" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-stack-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    const marker_path = try std.fmt.allocPrint(allocator, "{s}/.graphite_repo_config", .{dir_path});
    defer allocator.free(marker_path);
    try writeFile(marker_path, "{}\n");

    var detection = (try detect(allocator, dir_path)).?;
    defer detection.deinit(allocator);
    try std.testing.expectEqual(Provider.graphite, detection.provider);
    try std.testing.expectEqualStrings("graphite", detection.provider.label());
    try std.testing.expectEqualStrings(dir_path, detection.root_path);
    try std.testing.expectEqualStrings(marker_path, detection.marker_path);
    try std.testing.expect(try isGraphiteStack(allocator, dir_path));
}

test "detects graphite stack from descendants" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-stack-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    const marker_path = try std.fmt.allocPrint(allocator, "{s}/.graphite_repo_config", .{dir_path});
    defer allocator.free(marker_path);
    try writeFile(marker_path, "{}\n");

    const nested = try std.fmt.allocPrint(allocator, "{s}/a/b", .{dir_path});
    defer allocator.free(nested);
    try std.fs.cwd().makePath(nested);

    var detection = (try detect(allocator, nested)).?;
    defer detection.deinit(allocator);
    try std.testing.expectEqual(Provider.graphite, detection.provider);
    try std.testing.expectEqualStrings(dir_path, detection.root_path);
}

test "ignores directories without stack metadata" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-stack-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    try std.testing.expect((try detect(allocator, dir_path)) == null);
    try std.testing.expect(!(try isGraphiteStack(allocator, dir_path)));
    try std.testing.expect(!(try isGhstack(allocator, dir_path)));
    try std.testing.expect(!(try isSpr(allocator, dir_path)));
    try std.testing.expect(!(try isStax(allocator, dir_path)));
    try std.testing.expect(!(try isGitSpice(allocator, dir_path)));
    try std.testing.expect(!(try isGitTown(allocator, dir_path)));
    try std.testing.expect(!(try isGithubStack(allocator, dir_path)));
}

test "detects ghstack branch names" {
    try std.testing.expect(isGhstackBranchName("gh/alice/42/head"));
    try std.testing.expect(isGhstackBranchName("gh/alice/42/base"));
    try std.testing.expect(isGhstackBranchName("gh/alice/42/orig"));
    try std.testing.expect(!isGhstackBranchName("gh/alice/x/head"));
    try std.testing.expect(!isGhstackBranchName("feature/gh/alice/42/head"));
    try std.testing.expect(!isGhstackBranchName("gh/alice/42/other"));
}

test "detects ghstack from git branch" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-stack-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    const git_path = try std.fmt.allocPrint(allocator, "{s}/.git", .{dir_path});
    defer allocator.free(git_path);
    try std.fs.cwd().makePath(git_path);

    const head_path = try std.fmt.allocPrint(allocator, "{s}/HEAD", .{git_path});
    defer allocator.free(head_path);
    try writeFile(head_path, "ref: refs/heads/gh/alice/42/head\n");

    var detection = (try detect(allocator, dir_path)).?;
    defer detection.deinit(allocator);
    try std.testing.expectEqual(Provider.ghstack, detection.provider);
    try std.testing.expectEqualStrings(dir_path, detection.root_path);
    try std.testing.expectEqualStrings(head_path, detection.marker_path);
    try std.testing.expectEqualStrings("gh/alice/42/head", detection.branch_name.?);
    try std.testing.expect(try isGhstack(allocator, dir_path));
}

test "detects ghstack rc marker" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-stack-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    const marker_path = try std.fmt.allocPrint(allocator, "{s}/.ghstackrc", .{dir_path});
    defer allocator.free(marker_path);
    try writeFile(marker_path, "[ghstack]\n");

    var detection = (try detect(allocator, dir_path)).?;
    defer detection.deinit(allocator);
    try std.testing.expectEqual(Provider.ghstack, detection.provider);
    try std.testing.expectEqualStrings(dir_path, detection.root_path);
    try std.testing.expectEqualStrings(marker_path, detection.marker_path);
    try std.testing.expect(detection.branch_name == null);
}

test "detects spr refs marker" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-stack-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    const marker_path = try std.fmt.allocPrint(allocator, "{s}/.git/refs/spr", .{dir_path});
    defer allocator.free(marker_path);
    try std.fs.cwd().makePath(marker_path);

    var detection = (try detect(allocator, dir_path)).?;
    defer detection.deinit(allocator);
    try std.testing.expectEqual(Provider.spr, detection.provider);
    try std.testing.expectEqualStrings("spr", detection.provider.label());
    try std.testing.expectEqualStrings(dir_path, detection.root_path);
    try std.testing.expectEqualStrings(marker_path, detection.marker_path);
    try std.testing.expect(try isSpr(allocator, dir_path));
}

test "detects stax branch metadata refs" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-stack-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    const marker_path = try std.fmt.allocPrint(allocator, "{s}/.git/refs/branch-metadata", .{dir_path});
    defer allocator.free(marker_path);
    try std.fs.cwd().makePath(marker_path);

    var detection = (try detect(allocator, dir_path)).?;
    defer detection.deinit(allocator);
    try std.testing.expectEqual(Provider.stax, detection.provider);
    try std.testing.expectEqualStrings("st", detection.provider.label());
    try std.testing.expectEqualStrings(dir_path, detection.root_path);
    try std.testing.expectEqualStrings(marker_path, detection.marker_path);
    try std.testing.expect(try isStax(allocator, dir_path));
}

test "detects stax refs namespace" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-stack-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    const marker_path = try std.fmt.allocPrint(allocator, "{s}/.git/refs/stax", .{dir_path});
    defer allocator.free(marker_path);
    try std.fs.cwd().makePath(marker_path);

    var detection = (try detect(allocator, dir_path)).?;
    defer detection.deinit(allocator);
    try std.testing.expectEqual(Provider.stax, detection.provider);
    try std.testing.expectEqualStrings(marker_path, detection.marker_path);
}

test "detects stax repo config" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-stack-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);
    const git_path = try std.fmt.allocPrint(allocator, "{s}/.git", .{dir_path});
    defer allocator.free(git_path);
    try std.fs.cwd().makePath(git_path);

    const marker_path = try std.fmt.allocPrint(allocator, "{s}/stax.toml", .{dir_path});
    defer allocator.free(marker_path);
    try writeFile(marker_path, "[submit]\n");

    var detection = (try detect(allocator, dir_path)).?;
    defer detection.deinit(allocator);
    try std.testing.expectEqual(Provider.stax, detection.provider);
    try std.testing.expectEqualStrings(marker_path, detection.marker_path);
}

test "detects git-spice data ref" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-stack-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    const refs_path = try std.fmt.allocPrint(allocator, "{s}/.git/refs/spice", .{dir_path});
    defer allocator.free(refs_path);
    try std.fs.cwd().makePath(refs_path);
    const marker_path = try std.fmt.allocPrint(allocator, "{s}/data", .{refs_path});
    defer allocator.free(marker_path);
    try writeFile(marker_path, "0000000000000000000000000000000000000000\n");

    var detection = (try detect(allocator, dir_path)).?;
    defer detection.deinit(allocator);
    try std.testing.expectEqual(Provider.git_spice, detection.provider);
    try std.testing.expectEqualStrings("gs", detection.provider.label());
    try std.testing.expectEqualStrings(dir_path, detection.root_path);
    try std.testing.expectEqualStrings(marker_path, detection.marker_path);
    try std.testing.expect(try isGitSpice(allocator, dir_path));
}

test "detects git-spice packed data ref" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-stack-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);
    const git_path = try std.fmt.allocPrint(allocator, "{s}/.git", .{dir_path});
    defer allocator.free(git_path);
    try std.fs.cwd().makePath(git_path);

    const marker_path = try std.fmt.allocPrint(allocator, "{s}/packed-refs", .{git_path});
    defer allocator.free(marker_path);
    try writeFile(marker_path,
        \\# pack-refs with: peeled fully-peeled sorted
        \\0000000000000000000000000000000000000000 refs/spice/data
        \\
    );

    var detection = (try detect(allocator, dir_path)).?;
    defer detection.deinit(allocator);
    try std.testing.expectEqual(Provider.git_spice, detection.provider);
    try std.testing.expectEqualStrings(marker_path, detection.marker_path);
}

test "detects legacy git-town branches file" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-stack-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    const marker_path = try std.fmt.allocPrint(allocator, "{s}/.git-town-branches.yml", .{dir_path});
    defer allocator.free(marker_path);
    try writeFile(marker_path, "main: main\n");

    var detection = (try detect(allocator, dir_path)).?;
    defer detection.deinit(allocator);
    try std.testing.expectEqual(Provider.git_town, detection.provider);
    try std.testing.expectEqualStrings("git-town", detection.provider.label());
    try std.testing.expectEqualStrings(dir_path, detection.root_path);
    try std.testing.expectEqualStrings(marker_path, detection.marker_path);
    try std.testing.expect(try isGitTown(allocator, dir_path));
}

test "detects git-town toml config file" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-stack-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);

    const marker_path = try std.fmt.allocPrint(allocator, "{s}/.git-town.toml", .{dir_path});
    defer allocator.free(marker_path);
    try writeFile(marker_path, "[branches]\nmain = \"main\"\n");

    var detection = (try detect(allocator, dir_path)).?;
    defer detection.deinit(allocator);
    try std.testing.expectEqual(Provider.git_town, detection.provider);
    try std.testing.expectEqualStrings(marker_path, detection.marker_path);
}

test "detects git-town git config entries" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-stack-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);
    const git_path = try std.fmt.allocPrint(allocator, "{s}/.git", .{dir_path});
    defer allocator.free(git_path);
    try std.fs.cwd().makePath(git_path);

    const marker_path = try std.fmt.allocPrint(allocator, "{s}/config", .{git_path});
    defer allocator.free(marker_path);
    try writeFile(marker_path,
        \\[git-town]
        \\  main-branch = main
        \\
    );

    var detection = (try detect(allocator, dir_path)).?;
    defer detection.deinit(allocator);
    try std.testing.expectEqual(Provider.git_town, detection.provider);
    try std.testing.expectEqualStrings(marker_path, detection.marker_path);
}

test "detects github stack metadata file" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-stack-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);
    const git_path = try std.fmt.allocPrint(allocator, "{s}/.git", .{dir_path});
    defer allocator.free(git_path);
    try std.fs.cwd().makePath(git_path);

    const marker_path = try std.fmt.allocPrint(allocator, "{s}/gh-stack", .{git_path});
    defer allocator.free(marker_path);
    try writeFile(marker_path, "{\"stacks\":[]}\n");

    var detection = (try detect(allocator, dir_path)).?;
    defer detection.deinit(allocator);
    try std.testing.expectEqual(Provider.github_stack, detection.provider);
    try std.testing.expectEqualStrings("gh-stack", detection.provider.label());
    try std.testing.expectEqualStrings(dir_path, detection.root_path);
    try std.testing.expectEqualStrings(marker_path, detection.marker_path);
    try std.testing.expect(try isGithubStack(allocator, dir_path));
}

test "detects github stack git config entries" {
    const allocator = std.testing.allocator;
    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-stack-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);
    const git_path = try std.fmt.allocPrint(allocator, "{s}/.git", .{dir_path});
    defer allocator.free(git_path);
    try std.fs.cwd().makePath(git_path);

    const marker_path = try std.fmt.allocPrint(allocator, "{s}/config", .{git_path});
    defer allocator.free(marker_path);
    try writeFile(marker_path,
        \\[remote "origin"]
        \\  url = git@github.com:owner/repo.git
        \\[branch "feature-auth"]
        \\  stackParent = main
        \\  stackPR = 123
        \\
    );

    var detection = (try detect(allocator, dir_path)).?;
    defer detection.deinit(allocator);
    try std.testing.expectEqual(Provider.github_stack, detection.provider);
    try std.testing.expectEqualStrings(marker_path, detection.marker_path);
}

fn writeFile(path: []const u8, contents: []const u8) !void {
    var file = try std.fs.createFileAbsolute(path, .{ .truncate = true });
    defer file.close();
    try file.writeAll(contents);
}
