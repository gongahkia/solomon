const std = @import("std");

pub const provider_id = "llamacpp";
pub const default_model = "env:SHISA_LLAMA_CPP_MODEL";
pub const default_bin_path = "llama-cli";
const max_output_bytes = 16 * 1024 * 1024;
const default_predict_tokens = "512";

pub const GenerateConfig = struct {
    bin_path: []const u8 = default_bin_path,
    model: []const u8 = default_model,
    input: []const u8,
};

pub fn binPathFromEnvAlloc(allocator: std.mem.Allocator) ![]u8 {
    const path = std.process.getEnvVarOwned(allocator, "SHISA_LLAMA_CPP_BIN") catch |err| switch (err) {
        error.EnvironmentVariableNotFound => return allocator.dupe(u8, default_bin_path),
        else => return err,
    };
    errdefer allocator.free(path);
    if (std.mem.trim(u8, path, " \t\r\n").len == 0) return error.LlamaCppBinMissing;
    return path;
}

pub fn modelPathConfiguredEnv(allocator: std.mem.Allocator) bool {
    const path = std.process.getEnvVarOwned(allocator, "SHISA_LLAMA_CPP_MODEL") catch return false;
    defer allocator.free(path);
    return std.mem.trim(u8, path, " \t\r\n").len != 0;
}

pub fn modelPathFromEnvAlloc(allocator: std.mem.Allocator) ![]u8 {
    const path = std.process.getEnvVarOwned(allocator, "SHISA_LLAMA_CPP_MODEL") catch |err| switch (err) {
        error.EnvironmentVariableNotFound => return error.LlamaCppModelMissing,
        else => return err,
    };
    errdefer allocator.free(path);
    if (std.mem.trim(u8, path, " \t\r\n").len == 0) return error.LlamaCppModelMissing;
    return path;
}

pub fn resolveModelPathAlloc(allocator: std.mem.Allocator, model: []const u8) ![]u8 {
    if (std.mem.eql(u8, model, default_model)) return modelPathFromEnvAlloc(allocator);
    return allocator.dupe(u8, model);
}

pub fn generateAlloc(allocator: std.mem.Allocator, config: GenerateConfig) ![]u8 {
    const model_path = try resolveModelPathAlloc(allocator, config.model);
    defer allocator.free(model_path);
    const prompt_path = try writePromptTempFileAlloc(allocator, config.input);
    defer allocator.free(prompt_path);
    defer std.fs.deleteFileAbsolute(prompt_path) catch {};

    const result = try std.process.Child.run(.{
        .allocator = allocator,
        .argv = &.{
            config.bin_path,
            "-m",
            model_path,
            "-f",
            prompt_path,
            "-n",
            default_predict_tokens,
            "--no-display-prompt",
            "--no-show-timings",
            "--log-disable",
            "-st",
        },
        .max_output_bytes = max_output_bytes,
        .expand_arg0 = .expand,
    });
    defer allocator.free(result.stderr);
    if (!exitedZero(result.term)) {
        allocator.free(result.stdout);
        return error.LlamaCppCommandFailed;
    }
    const trimmed = std.mem.trim(u8, result.stdout, " \t\r\n");
    if (trimmed.len == 0) {
        allocator.free(result.stdout);
        return error.EmptyLlamaCppResponse;
    }
    const output = try allocator.dupe(u8, trimmed);
    allocator.free(result.stdout);
    return output;
}

fn writePromptTempFileAlloc(allocator: std.mem.Allocator, input: []const u8) ![]u8 {
    const tmp_dir = try tempDirAlloc(allocator);
    defer allocator.free(tmp_dir);
    const trimmed_tmp = std.mem.trimRight(u8, tmp_dir, "/");
    var attempt: usize = 0;
    while (attempt < 8) : (attempt += 1) {
        const path = try std.fmt.allocPrint(allocator, "{s}/shisa-llamacpp-{x}.prompt", .{ trimmed_tmp, std.crypto.random.int(u64) });
        errdefer allocator.free(path);
        var file = std.fs.createFileAbsolute(path, .{ .exclusive = true, .mode = 0o600 }) catch |err| switch (err) {
            error.PathAlreadyExists => {
                allocator.free(path);
                continue;
            },
            else => return err,
        };
        errdefer std.fs.deleteFileAbsolute(path) catch {};
        defer file.close();
        try file.writeAll(input);
        return path;
    }
    return error.TempPathUnavailable;
}

fn tempDirAlloc(allocator: std.mem.Allocator) ![]u8 {
    return std.process.getEnvVarOwned(allocator, "TMPDIR") catch |err| switch (err) {
        error.EnvironmentVariableNotFound => allocator.dupe(u8, "/tmp"),
        else => err,
    };
}

fn exitedZero(term: std.process.Child.Term) bool {
    return switch (term) {
        .Exited => |code| code == 0,
        else => false,
    };
}

test "explicit model path bypasses env model" {
    const model = try resolveModelPathAlloc(std.testing.allocator, "/tmp/model.gguf");
    defer std.testing.allocator.free(model);
    try std.testing.expectEqualStrings("/tmp/model.gguf", model);
}

test "generate uses prompt file instead of prompt argv" {
    const text = try generateAlloc(std.testing.allocator, .{
        .bin_path = "/bin/echo",
        .model = "/tmp/model.gguf",
        .input = "secret prompt",
    });
    defer std.testing.allocator.free(text);
    try std.testing.expect(std.mem.indexOf(u8, text, "secret prompt") == null);
    try std.testing.expect(std.mem.indexOf(u8, text, "-f") != null);
    try std.testing.expect(std.mem.indexOf(u8, text, "--no-display-prompt") != null);
}
