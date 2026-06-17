const std = @import("std");
const cloud_ctx = @import("daemon/modules/cloud_ctx.zig");
const frame = @import("proto/frame.zig");

const cold_budget_ns = 30 * std.time.ns_per_ms;
const warm_budget_ns = std.time.ns_per_ms;
const deframe_iterations = 100_000;
const deframe_budget_ns = std.time.ns_per_s;
const deframe_corpus_frames = 256;
const deframe_payload_max = 512;

pub fn main() !void {
    var gpa = std.heap.GeneralPurposeAllocator(.{}){};
    defer _ = gpa.deinit();
    const allocator = gpa.allocator();
    const cloud_result = try benchCloudCtx(allocator);
    if (cloud_result.cold_ns >= cold_budget_ns or cloud_result.warm_avg_ns >= warm_budget_ns) return error.CloudCtxBenchmarkRegression;
    const frame_result = try benchProtoFrame(allocator);
    if (frame_result.deframe_100k_ns >= deframe_budget_ns) return error.ProtoFrameBenchmarkRegression;
    const output = try std.fmt.allocPrint(
        allocator,
        "{{\"cloud_ctx\":{{\"cold_ns\":{d},\"warm_avg_ns\":{d},\"cold_budget_ns\":{d},\"warm_budget_ns\":{d}}},\"proto_frame\":{{\"deframe_100k_ns\":{d},\"iterations\":{d},\"budget_ns\":{d}}}}}\n",
        .{ cloud_result.cold_ns, cloud_result.warm_avg_ns, cold_budget_ns, warm_budget_ns, frame_result.deframe_100k_ns, frame_result.iterations, frame_result.budget_ns },
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
