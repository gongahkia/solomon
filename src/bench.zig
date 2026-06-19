const std = @import("std");
const ai_redact = @import("ai/redact.zig");
const cloud_ctx = @import("daemon/modules/cloud_ctx.zig");
const frame = @import("proto/frame.zig");
const git_state = @import("vcs/git_state.zig");
const hg = @import("vcs/hg.zig");
const jj = @import("vcs/jj.zig");

const cold_budget_ns = 30 * std.time.ns_per_ms;
const warm_budget_ns = std.time.ns_per_ms;
const deframe_iterations = 100_000;
const deframe_budget_ns = std.time.ns_per_s;
const deframe_corpus_frames = 256;
const deframe_payload_max = 512;
const vcs_pack_iterations = 1000;
const vcs_pack_budget_ns = 500 * std.time.ns_per_ms;
const ai_pack_iterations = 1000;
const ai_pack_budget_ns = 80 * std.time.ns_per_ms;

pub fn main() !void {
    var gpa = std.heap.GeneralPurposeAllocator(.{}){};
    defer _ = gpa.deinit();
    const allocator = gpa.allocator();
    const cloud_result = try benchCloudCtx(allocator);
    if (cloud_result.cold_ns >= cold_budget_ns or cloud_result.warm_avg_ns >= warm_budget_ns) return error.CloudCtxBenchmarkRegression;
    const frame_result = try benchProtoFrame(allocator);
    if (frame_result.deframe_100k_ns >= deframe_budget_ns) return error.ProtoFrameBenchmarkRegression;
    const vcs_result = try benchVcsPack(allocator);
    if (vcs_result.elapsed_ns >= vcs_pack_budget_ns) return error.VcsPackBenchmarkRegression;
    const ai_result = try benchAiPack(allocator);
    if (ai_result.elapsed_ns >= ai_pack_budget_ns) return error.AiPackBenchmarkRegression;
    const output = try std.fmt.allocPrint(
        allocator,
        "{{\"cloud_ctx\":{{\"cold_ns\":{d},\"warm_avg_ns\":{d},\"cold_budget_ns\":{d},\"warm_budget_ns\":{d}}},\"proto_frame\":{{\"deframe_100k_ns\":{d},\"iterations\":{d},\"budget_ns\":{d}}},\"packs\":{{\"shisa.cloud\":{{\"cloud_ctx_cold_ns\":{d},\"cloud_ctx_warm_avg_ns\":{d},\"cold_budget_ns\":{d},\"warm_budget_ns\":{d}}},\"shisa.vcs\":{{\"fixture_batch_ns\":{d},\"iterations\":{d},\"budget_ns\":{d}}},\"shisa.ai\":{{\"redact_batch_ns\":{d},\"iterations\":{d},\"budget_ns\":{d}}}}}}}\n",
        .{
            cloud_result.cold_ns,
            cloud_result.warm_avg_ns,
            cold_budget_ns,
            warm_budget_ns,
            frame_result.deframe_100k_ns,
            frame_result.iterations,
            frame_result.budget_ns,
            cloud_result.cold_ns,
            cloud_result.warm_avg_ns,
            cold_budget_ns,
            warm_budget_ns,
            vcs_result.elapsed_ns,
            vcs_result.iterations,
            vcs_result.budget_ns,
            ai_result.elapsed_ns,
            ai_result.iterations,
            ai_result.budget_ns,
        },
    );
    defer allocator.free(output);
    try std.fs.File.stdout().writeAll(output);
}

const CloudCtxBench = struct {
    cold_ns: u64,
    warm_avg_ns: u64,
};

const ProtoFrameBench = struct {
    deframe_100k_ns: u64,
    iterations: u32,
    budget_ns: u64,
};

const PackBench = struct {
    elapsed_ns: u64,
    iterations: u32,
    budget_ns: u64,
};

const DeframeCase = struct {
    encoded: []u8,
    expected_addend: usize,
};

fn benchProtoFrame(allocator: std.mem.Allocator) !ProtoFrameBench {
    var prng = std.Random.DefaultPrng.init(std.crypto.random.int(u64));
    const random = prng.random();
    var payload: [deframe_payload_max]u8 = undefined;
    const cases = try allocator.alloc(DeframeCase, deframe_corpus_frames);
    defer allocator.free(cases);
    for (cases, 0..) |*case, index| {
        const len = random.intRangeAtMost(usize, 0, deframe_payload_max);
        random.bytes(payload[0..len]);
        if (len > 0 and payload[0] == 0) payload[0] = @as(u8, @truncate(index + 1));
        case.* = .{
            .encoded = try frame.encodeAlloc(allocator, payload[0..len]),
            .expected_addend = len + if (len > 0) payload[0] else 0,
        };
    }
    defer {
        for (cases) |case| allocator.free(case.encoded);
    }

    var checksum: usize = 0;
    var expected: usize = 0;
    const start = std.time.nanoTimestamp();
    for (0..deframe_iterations) |index| {
        const case = cases[index % cases.len];
        const decoded = try frame.decode(case.encoded);
        checksum +%= decoded.len + if (decoded.len > 0) decoded[0] else 0;
        expected +%= case.expected_addend;
        std.mem.doNotOptimizeAway(decoded);
    }
    const elapsed: u64 = @intCast(std.time.nanoTimestamp() - start);
    std.mem.doNotOptimizeAway(checksum);
    if (checksum != expected) return error.UnexpectedDeframeChecksum;
    return .{
        .deframe_100k_ns = elapsed,
        .iterations = deframe_iterations,
        .budget_ns = deframe_budget_ns,
    };
}

fn benchCloudCtx(allocator: std.mem.Allocator) !CloudCtxBench {
    const root_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-cloud-bench-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(root_path);
    defer std.fs.cwd().deleteTree(root_path) catch {};
    const home_path = try std.fmt.allocPrint(allocator, "{s}/home", .{root_path});
    defer allocator.free(home_path);
    try setupCloudHome(allocator, home_path);

    var cold_best: u64 = std.math.maxInt(u64);
    for (0..5) |_| {
        var cache = cloud_ctx.Cache{};
        defer cache.deinit(allocator);
        const start = std.time.nanoTimestamp();
        try renderExpected(allocator, home_path, &cache);
        const elapsed: u64 = @intCast(std.time.nanoTimestamp() - start);
        cold_best = @min(cold_best, elapsed);
    }

    var cache = cloud_ctx.Cache{};
    defer cache.deinit(allocator);
    try renderExpected(allocator, home_path, &cache);
    const iterations = 512;
    const warm_start = std.time.nanoTimestamp();
    for (0..iterations) |_| try renderExpected(allocator, home_path, &cache);
    const warm_elapsed: u64 = @intCast(std.time.nanoTimestamp() - warm_start);
    return .{
        .cold_ns = cold_best,
        .warm_avg_ns = warm_elapsed / iterations,
    };
}

fn renderExpected(allocator: std.mem.Allocator, home_path: []const u8, cache: *cloud_ctx.Cache) !void {
    const rendered = (try cloud_ctx.render(allocator, "default", null, home_path, cache, .{})).?;
    defer allocator.free(rendered);
    if (!std.mem.eql(u8, rendered, "cloud[aws:default gcp:test-project az:prod-sub k8s:prod/default]")) return error.UnexpectedCloudCtxRender;
}

fn benchVcsPack(allocator: std.mem.Allocator) !PackBench {
    const git_root = "test/fixtures/vcs/git/state";
    const git_porcelain = try readFixture(allocator, git_root ++ "/porcelain.txt");
    defer allocator.free(git_porcelain);
    const git_sparse = try readFixture(allocator, git_root ++ "/sparse-config.txt");
    defer allocator.free(git_sparse);
    const git_submodules = try readFixture(allocator, git_root ++ "/submodules.txt");
    defer allocator.free(git_submodules);
    const git_attributes = try readFixture(allocator, git_root ++ "/attributes.txt");
    defer allocator.free(git_attributes);
    const git_lfs_pointer = try readFixture(allocator, git_root ++ "/lfs-pointer.txt");
    defer allocator.free(git_lfs_pointer);
    const git_branch_rules = try readFixture(allocator, git_root ++ "/branch-rules.json");
    defer allocator.free(git_branch_rules);
    const git_signed_commit = try readFixture(allocator, git_root ++ "/signed-commit.txt");
    defer allocator.free(git_signed_commit);
    const jj_change = try readFixture(allocator, "test/fixtures/vcs/jj/linear/current-change.txt");
    defer allocator.free(jj_change);
    const jj_conflict = try readFixture(allocator, "test/fixtures/vcs/jj/conflict/conflict.txt");
    defer allocator.free(jj_conflict);
    const hg_summary = try readFixture(allocator, "test/fixtures/vcs/hg/summary/summary.txt");
    defer allocator.free(hg_summary);
    const hg_refs = try readFixture(allocator, "test/fixtures/vcs/hg/summary/refs.txt");
    defer allocator.free(hg_refs);
    const hg_queue = try readFixture(allocator, "test/fixtures/vcs/hg/summary/mq-queue.txt");
    defer allocator.free(hg_queue);
    const hg_applied = try readFixture(allocator, "test/fixtures/vcs/hg/summary/mq-applied.txt");
    defer allocator.free(hg_applied);
    const hg_series = try readFixture(allocator, "test/fixtures/vcs/hg/summary/mq-series.txt");
    defer allocator.free(hg_series);

    var checksum: usize = 0;
    const start = std.time.nanoTimestamp();
    for (0..vcs_pack_iterations) |_| {
        const counts = git_state.parsePorcelainCounts(git_porcelain);
        const sparse = git_state.parseSparseCheckoutState(git_sparse);
        const submodules = git_state.parseSubmoduleStatus(git_submodules);
        const lfs = git_state.parseLfsSummary(git_attributes, &.{git_lfs_pointer});
        const protection = (try git_state.parseBranchProtectionHint(allocator, git_branch_rules)).?;
        const signal = git_state.branchProtectionSignal(protection).?;
        const signature = git_state.parseHeadSignature("G", git_signed_commit);
        const ahead_behind = git_state.parseAheadBehind("2 5\n").?;
        const stash_count = git_state.parseStashCount("stash@{0}: WIP\nstash@{1}: WIP\n");

        var jj_change_summary = (try jj.parseChangeSummary(allocator, jj_change)).?;
        defer jj_change_summary.deinit(allocator);
        const jj_rendered = try jj.formatChangeSummaryAlloc(allocator, jj_change_summary);
        defer allocator.free(jj_rendered);
        var jj_conflict_summary = (try jj.parseConflictSummary(allocator, jj_conflict)).?;
        defer jj_conflict_summary.deinit(allocator);
        const jj_conflict_rendered = try jj.formatConflictSummaryAlloc(allocator, jj_conflict_summary);
        defer allocator.free(jj_conflict_rendered);

        var hg_parsed_summary = (try hg.parseSummary(allocator, hg_summary)).?;
        defer hg_parsed_summary.deinit(allocator);
        var hg_ref_summary = (try hg.parseRefSummary(allocator, hg_refs)).?;
        defer hg_ref_summary.deinit(allocator);
        const hg_ref_rendered = try hg.formatRefSummaryAlloc(allocator, hg_ref_summary);
        defer allocator.free(hg_ref_rendered);
        var hg_mq_summary = (try hg.parseMqSummary(allocator, hg_queue, hg_applied, hg_series)).?;
        defer hg_mq_summary.deinit(allocator);
        const hg_mq_rendered = try hg.formatMqSummaryAlloc(allocator, hg_mq_summary);
        defer allocator.free(hg_mq_rendered);

        checksum +%= counts.staged + counts.unstaged + counts.untracked + counts.conflicts;
        checksum +%= @intFromEnum(sparse) + submodules.dirty + submodules.uninitialized + lfs.pointer_only;
        checksum +%= protection.rules + protection.required_status_checks + protection.required_approving_reviews + signal.glyph.len;
        checksum +%= @intFromEnum(signature.status) + @intFromEnum(signature.kind) + ahead_behind.ahead + ahead_behind.behind + stash_count;
        checksum +%= jj_rendered.len + jj_conflict_rendered.len + hg_parsed_summary.parent.len + hg_ref_rendered.len + hg_mq_rendered.len;
    }
    const elapsed: u64 = @intCast(std.time.nanoTimestamp() - start);
    std.mem.doNotOptimizeAway(checksum);
    return .{ .elapsed_ns = elapsed, .iterations = vcs_pack_iterations, .budget_ns = vcs_pack_budget_ns };
}

fn benchAiPack(allocator: std.mem.Allocator) !PackBench {
    const sample =
        \\aws_access_key_id = AKIA1234567890ABCDEF
        \\aws_secret_access_key = demo-secret
        \\Authorization: Bearer ghp_1234567890abcdef1234567890abcdef1234
        \\-----BEGIN OPENSSH PRIVATE KEY-----
        \\b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAA=
        \\-----END OPENSSH PRIVATE KEY-----
        \\safe command context remains visible
        \\
    ;
    var checksum: usize = 0;
    const start = std.time.nanoTimestamp();
    for (0..ai_pack_iterations) |_| {
        const redacted = try ai_redact.redactAlloc(allocator, sample);
        defer allocator.free(redacted);
        if (std.mem.indexOf(u8, redacted, "demo-secret") != null) return error.AiRedactionLeak;
        checksum +%= redacted.len;
    }
    const elapsed: u64 = @intCast(std.time.nanoTimestamp() - start);
    std.mem.doNotOptimizeAway(checksum);
    return .{ .elapsed_ns = elapsed, .iterations = ai_pack_iterations, .budget_ns = ai_pack_budget_ns };
}

fn setupCloudHome(allocator: std.mem.Allocator, home_path: []const u8) !void {
    try copyFixture(allocator, "test/fixtures/cloud/aws-config-default", try pathJoin(allocator, home_path, ".aws/config"));
    try copyFixture(allocator, "test/fixtures/cloud/gcloud-config", try pathJoin(allocator, home_path, ".config/gcloud/configurations/config_default"));
    try copyFixture(allocator, "test/fixtures/cloud/azureProfile.json", try pathJoin(allocator, home_path, ".azure/azureProfile.json"));
    try copyFixture(allocator, "test/fixtures/cloud/kubeconfig-with-namespace.yaml", try pathJoin(allocator, home_path, ".kube/config"));
}

fn pathJoin(allocator: std.mem.Allocator, base: []const u8, suffix: []const u8) ![]u8 {
    return std.fmt.allocPrint(allocator, "{s}/{s}", .{ base, suffix });
}

fn copyFixture(allocator: std.mem.Allocator, source_path: []const u8, dest_path: []u8) !void {
    defer allocator.free(dest_path);
    const source = try std.fs.cwd().readFileAlloc(allocator, source_path, 1024 * 1024);
    defer allocator.free(source);
    if (std.fs.path.dirname(dest_path)) |parent| try std.fs.cwd().makePath(parent);
    var file = try std.fs.createFileAbsolute(dest_path, .{ .truncate = true });
    defer file.close();
    try file.writeAll(source);
}

fn readFixture(allocator: std.mem.Allocator, path: []const u8) ![]u8 {
    return try std.fs.cwd().readFileAlloc(allocator, path, 1024 * 1024);
}
