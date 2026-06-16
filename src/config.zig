const std = @import("std");
const risk_tier_module = @import("daemon/modules/risk_tier.zig");
const sso_expiry_module = @import("daemon/modules/sso_expiry.zig");

pub const default_config_text =
    \\version = 1
    \\theme = "plain"
    \\
    \\[prompt]
    \\modules = ["cwd", "git_branch", "language_versions", "exit_status", "jobs", "cmd_duration", "user_host", "sso_expiry"]
    \\
    \\[modules.cwd]
    \\truncate_to = 3
    \\home_tilde = true
    \\
    \\[modules.git_branch]
    \\show_dirty = true
    \\cache_ttl_ms = 250
    \\
    \\[modules.cmd_duration]
    \\threshold_ms = 1000
    \\
    \\[modules.user_host]
    \\mode = "ssh"
    \\
    \\[modules.cloud_ctx]
    \\aws = true
    \\gcp = true
    \\azure = true
    \\kubernetes = true
    \\
    \\[modules.risk_tier]
    \\unknown_bg = "muted"
    \\dev_bg = "success"
    \\staging_bg = "warning"
    \\prod_bg = "danger"
    \\
    \\[modules.sso_expiry]
    \\warning_minutes = 30
    \\
;

pub const Diagnostic = struct {
    message: []const u8 = "",
    line: usize = 0,
    column: usize = 0,
};

pub const ModuleId = enum {
    cwd,
    git_branch,
    language_versions,
    exit_status,
    jobs,
    cmd_duration,
    user_host,
    cloud_ctx,
    risk_tier,
    sso_expiry,
    time,
};

pub fn moduleIdName(module_id: ModuleId) []const u8 {
    return switch (module_id) {
        .cwd => "cwd",
        .git_branch => "git_branch",
        .language_versions => "language_versions",
        .exit_status => "exit_status",
        .jobs => "jobs",
        .cmd_duration => "cmd_duration",
        .user_host => "user_host",
        .cloud_ctx => "cloud_ctx",
        .risk_tier => "risk_tier",
        .sso_expiry => "sso_expiry",
        .time => "time",
    };
}

pub fn moduleExecutionClass(module_id: ModuleId) []const u8 {
    return switch (module_id) {
        .git_branch, .language_versions => "async",
        else => "sync",
    };
}

pub const UserHostMode = enum {
    ssh,
    always,
    never,
};

pub const ModuleOptions = struct {
    cwd: CwdOptions = .{},
    git_branch: GitBranchOptions = .{},
    language_versions: LanguageVersionsOptions = .{},
    exit_status: ExitStatusOptions = .{},
    jobs: JobsOptions = .{},
    cmd_duration: CmdDurationOptions = .{},
    user_host: UserHostOptions = .{},
    cloud_ctx: CloudCtxOptions = .{},
    risk_tier: RiskTierOptions = .{},
    sso_expiry: SsoExpiryOptions = .{},
    time: TimeOptions = .{},
};

pub const CwdOptions = struct {
    truncate_to: u8 = 3,
    home_tilde: bool = true,
};

pub const GitBranchOptions = struct {
    show_dirty: bool = true,
    cache_ttl_ms: u32 = 250,
};

pub const LanguageVersionsOptions = struct {
    python: bool = true,
    node: bool = true,
    rust: bool = true,
    go: bool = true,
};

pub const ExitStatusOptions = struct {
    show_zero: bool = false,
};

pub const JobsOptions = struct {
    show_zero: bool = false,
};

pub const CmdDurationOptions = struct {
    threshold_ms: u64 = 1000,
};

pub const UserHostOptions = struct {
    mode: UserHostMode = .ssh,
};

pub const CloudCtxOptions = struct {
    aws: bool = true,
    gcp: bool = true,
    azure: bool = true,
    kubernetes: bool = true,
};

pub const RiskTierOptions = risk_tier_module.BarColors;
pub const RiskTierColor = risk_tier_module.ColorSlot;
pub const SsoExpiryOptions = sso_expiry_module.Options;

pub const TimeOptions = struct {
    format_24h: bool = true,
    utc: bool = true,
};

pub const Config = struct {
    version: u32,
    theme: []u8,
    prompt_modules: []ModuleId,
    modules: ModuleOptions = .{},

    pub fn deinit(self: *Config, allocator: std.mem.Allocator) void {
        allocator.free(self.theme);
        allocator.free(self.prompt_modules);
        self.* = undefined;
    }
};

const Table = enum {
    root,
    prompt,
    cwd,
    git_branch,
    language_versions,
    exit_status,
    jobs,
    cmd_duration,
    user_host,
    cloud_ctx,
    risk_tier,
    sso_expiry,
    time,
};

const Seen = struct {
    version: bool = false,
    theme: bool = false,
    prompt_modules: bool = false,
    cwd_truncate_to: bool = false,
    cwd_home_tilde: bool = false,
    git_branch_show_dirty: bool = false,
    git_branch_cache_ttl_ms: bool = false,
    language_versions_detect: bool = false,
    exit_status_show_zero: bool = false,
    jobs_show_zero: bool = false,
    cmd_duration_threshold_ms: bool = false,
    user_host_mode: bool = false,
    cloud_ctx_aws: bool = false,
    cloud_ctx_gcp: bool = false,
    cloud_ctx_azure: bool = false,
    cloud_ctx_kubernetes: bool = false,
    risk_tier_unknown_bg: bool = false,
    risk_tier_dev_bg: bool = false,
    risk_tier_staging_bg: bool = false,
    risk_tier_prod_bg: bool = false,
    sso_expiry_warning_minutes: bool = false,
    time_format: bool = false,
    time_utc: bool = false,
};

const Trimmed = struct {
    text: []const u8,
    column: usize,
};

const default_modules = [_]ModuleId{ .cwd, .git_branch, .language_versions, .exit_status, .jobs, .cmd_duration, .user_host, .sso_expiry };

pub fn parse(allocator: std.mem.Allocator, source: []const u8, diagnostic: *Diagnostic) !Config {
    diagnostic.* = .{};
    var parser = Parser{
        .allocator = allocator,
        .source = source,
        .diagnostic = diagnostic,
    };
    errdefer parser.deinitWorking();
    return parser.parse();
}

const Parser = struct {
    allocator: std.mem.Allocator,
    source: []const u8,
    diagnostic: *Diagnostic,
    table: Table = .root,
    seen: Seen = .{},
    theme: ?[]u8 = null,
    prompt_modules: std.ArrayList(ModuleId) = .empty,
    modules: ModuleOptions = .{},

    fn parse(self: *Parser) !Config {
        var offset: usize = 0;
        var line_no: usize = 1;
        while (offset <= self.source.len) : (line_no += 1) {
            const rest = self.source[offset..];
            const line_len = std.mem.indexOfScalar(u8, rest, '\n') orelse rest.len;
            var line = rest[0..line_len];
            if (line.len > 0 and line[line.len - 1] == '\r') line = line[0 .. line.len - 1];
            try self.parseLine(line_no, line);
            offset += line_len + 1;
            if (offset > self.source.len) break;
        }

        if (!self.seen.version) return self.fail(1, 1, "missing version");

        const theme = if (self.theme) |value| value else try self.allocator.dupe(u8, "plain");
        self.theme = null;
        const modules = if (self.seen.prompt_modules)
            try self.prompt_modules.toOwnedSlice(self.allocator)
        else
            try self.allocator.dupe(ModuleId, default_modules[0..]);

        return .{
            .version = 1,
            .theme = theme,
            .prompt_modules = modules,
            .modules = self.modules,
        };
    }

    fn deinitWorking(self: *Parser) void {
        if (self.theme) |value| self.allocator.free(value);
        self.prompt_modules.deinit(self.allocator);
    }

    fn parseLine(self: *Parser, line_no: usize, line: []const u8) !void {
        const no_comment = stripComment(line);
        const trimmed = trimWithColumn(no_comment, 1);
        if (trimmed.text.len == 0) return;

        if (trimmed.text[0] == '[') {
            try self.parseTable(line_no, trimmed);
            return;
        }

        try self.parseKeyValue(line_no, trimmed);
    }

    fn parseTable(self: *Parser, line_no: usize, trimmed: Trimmed) !void {
        if (trimmed.text.len < 3 or trimmed.text[trimmed.text.len - 1] != ']') {
            return self.fail(line_no, trimmed.column, "invalid table header");
        }

        const inner = trimWithColumn(trimmed.text[1 .. trimmed.text.len - 1], trimmed.column + 1);
        if (inner.text.len == 0) return self.fail(line_no, inner.column, "empty table name");

        self.table = parseTableName(inner.text) orelse return self.fail(line_no, inner.column, "unknown table");
    }

    fn parseKeyValue(self: *Parser, line_no: usize, trimmed: Trimmed) !void {
        const eq_index = findEquals(trimmed.text) orelse return self.fail(line_no, trimmed.column, "expected key-value pair");
        const key = trimWithColumn(trimmed.text[0..eq_index], trimmed.column);
        const value = trimWithColumn(trimmed.text[eq_index + 1 ..], trimmed.column + eq_index + 1);
        if (key.text.len == 0) return self.fail(line_no, key.column, "empty key");
        if (value.text.len == 0) return self.fail(line_no, value.column, "empty value");

        switch (self.table) {
            .root => try self.parseRootKey(line_no, key, value),
            .prompt => try self.parsePromptKey(line_no, key, value),
            .cwd => try self.parseCwdKey(line_no, key, value),
            .git_branch => try self.parseGitBranchKey(line_no, key, value),
            .language_versions => try self.parseLanguageVersionsKey(line_no, key, value),
            .exit_status => try self.parseExitStatusKey(line_no, key, value),
            .jobs => try self.parseJobsKey(line_no, key, value),
            .cmd_duration => try self.parseCmdDurationKey(line_no, key, value),
            .user_host => try self.parseUserHostKey(line_no, key, value),
            .cloud_ctx => try self.parseCloudCtxKey(line_no, key, value),
            .risk_tier => try self.parseRiskTierKey(line_no, key, value),
            .sso_expiry => try self.parseSsoExpiryKey(line_no, key, value),
            .time => try self.parseTimeKey(line_no, key, value),
        }
    }

    fn parseRootKey(self: *Parser, line_no: usize, key: Trimmed, value: Trimmed) !void {
        if (std.mem.eql(u8, key.text, "version")) {
            try self.markUnseen(&self.seen.version, line_no, key.column);
            const parsed = try self.parseIntRange(value, line_no, 1, 1);
            _ = parsed;
        } else if (std.mem.eql(u8, key.text, "theme")) {
            try self.markUnseen(&self.seen.theme, line_no, key.column);
            self.theme = try self.parseStringAlloc(value, line_no);
        } else {
            return self.fail(line_no, key.column, "unknown key");
        }
    }

    fn parsePromptKey(self: *Parser, line_no: usize, key: Trimmed, value: Trimmed) !void {
        if (!std.mem.eql(u8, key.text, "modules")) return self.fail(line_no, key.column, "unknown key");
        try self.markUnseen(&self.seen.prompt_modules, line_no, key.column);
        try self.parseModuleArray(value, line_no);
    }

    fn parseCwdKey(self: *Parser, line_no: usize, key: Trimmed, value: Trimmed) !void {
        if (std.mem.eql(u8, key.text, "truncate_to")) {
            try self.markUnseen(&self.seen.cwd_truncate_to, line_no, key.column);
            self.modules.cwd.truncate_to = @intCast(try self.parseIntRange(value, line_no, 0, 16));
        } else if (std.mem.eql(u8, key.text, "home_tilde")) {
            try self.markUnseen(&self.seen.cwd_home_tilde, line_no, key.column);
            self.modules.cwd.home_tilde = try self.parseBool(value, line_no);
        } else {
            return self.fail(line_no, key.column, "unknown key");
        }
    }

    fn parseGitBranchKey(self: *Parser, line_no: usize, key: Trimmed, value: Trimmed) !void {
        if (std.mem.eql(u8, key.text, "show_dirty")) {
            try self.markUnseen(&self.seen.git_branch_show_dirty, line_no, key.column);
            self.modules.git_branch.show_dirty = try self.parseBool(value, line_no);
        } else if (std.mem.eql(u8, key.text, "cache_ttl_ms")) {
            try self.markUnseen(&self.seen.git_branch_cache_ttl_ms, line_no, key.column);
            self.modules.git_branch.cache_ttl_ms = @intCast(try self.parseIntRange(value, line_no, 0, 60000));
        } else {
            return self.fail(line_no, key.column, "unknown key");
        }
    }

    fn parseLanguageVersionsKey(self: *Parser, line_no: usize, key: Trimmed, value: Trimmed) !void {
        if (!std.mem.eql(u8, key.text, "detect")) return self.fail(line_no, key.column, "unknown key");
        try self.markUnseen(&self.seen.language_versions_detect, line_no, key.column);
        self.modules.language_versions = try self.parseLanguageDetectArray(value, line_no);
    }

    fn parseExitStatusKey(self: *Parser, line_no: usize, key: Trimmed, value: Trimmed) !void {
        if (!std.mem.eql(u8, key.text, "show_zero")) return self.fail(line_no, key.column, "unknown key");
        try self.markUnseen(&self.seen.exit_status_show_zero, line_no, key.column);
        self.modules.exit_status.show_zero = try self.parseBool(value, line_no);
    }

    fn parseJobsKey(self: *Parser, line_no: usize, key: Trimmed, value: Trimmed) !void {
        if (!std.mem.eql(u8, key.text, "show_zero")) return self.fail(line_no, key.column, "unknown key");
        try self.markUnseen(&self.seen.jobs_show_zero, line_no, key.column);
        self.modules.jobs.show_zero = try self.parseBool(value, line_no);
    }

    fn parseCmdDurationKey(self: *Parser, line_no: usize, key: Trimmed, value: Trimmed) !void {
        if (!std.mem.eql(u8, key.text, "threshold_ms")) return self.fail(line_no, key.column, "unknown key");
        try self.markUnseen(&self.seen.cmd_duration_threshold_ms, line_no, key.column);
        self.modules.cmd_duration.threshold_ms = @intCast(try self.parseIntRange(value, line_no, 0, 86400000));
    }

    fn parseUserHostKey(self: *Parser, line_no: usize, key: Trimmed, value: Trimmed) !void {
        if (!std.mem.eql(u8, key.text, "mode")) return self.fail(line_no, key.column, "unknown key");
        try self.markUnseen(&self.seen.user_host_mode, line_no, key.column);
        const mode = try self.parseStringAlloc(value, line_no);
        defer self.allocator.free(mode);
        self.modules.user_host.mode = if (std.mem.eql(u8, mode, "ssh"))
            .ssh
        else if (std.mem.eql(u8, mode, "always"))
            .always
        else if (std.mem.eql(u8, mode, "never"))
            .never
        else
            return self.fail(line_no, value.column, "invalid user_host mode");
    }

    fn parseCloudCtxKey(self: *Parser, line_no: usize, key: Trimmed, value: Trimmed) !void {
        if (std.mem.eql(u8, key.text, "aws")) {
            try self.markUnseen(&self.seen.cloud_ctx_aws, line_no, key.column);
            self.modules.cloud_ctx.aws = try self.parseBool(value, line_no);
        } else if (std.mem.eql(u8, key.text, "gcp")) {
            try self.markUnseen(&self.seen.cloud_ctx_gcp, line_no, key.column);
            self.modules.cloud_ctx.gcp = try self.parseBool(value, line_no);
        } else if (std.mem.eql(u8, key.text, "azure")) {
            try self.markUnseen(&self.seen.cloud_ctx_azure, line_no, key.column);
            self.modules.cloud_ctx.azure = try self.parseBool(value, line_no);
        } else if (std.mem.eql(u8, key.text, "kubernetes")) {
            try self.markUnseen(&self.seen.cloud_ctx_kubernetes, line_no, key.column);
            self.modules.cloud_ctx.kubernetes = try self.parseBool(value, line_no);
        } else {
            return self.fail(line_no, key.column, "unknown key");
        }
    }

    fn parseRiskTierKey(self: *Parser, line_no: usize, key: Trimmed, value: Trimmed) !void {
        if (std.mem.eql(u8, key.text, "unknown_bg")) {
            try self.markUnseen(&self.seen.risk_tier_unknown_bg, line_no, key.column);
            self.modules.risk_tier.unknown_bg = try self.parseRiskTierColor(value, line_no);
        } else if (std.mem.eql(u8, key.text, "dev_bg")) {
            try self.markUnseen(&self.seen.risk_tier_dev_bg, line_no, key.column);
            self.modules.risk_tier.dev_bg = try self.parseRiskTierColor(value, line_no);
        } else if (std.mem.eql(u8, key.text, "staging_bg")) {
            try self.markUnseen(&self.seen.risk_tier_staging_bg, line_no, key.column);
            self.modules.risk_tier.staging_bg = try self.parseRiskTierColor(value, line_no);
        } else if (std.mem.eql(u8, key.text, "prod_bg")) {
            try self.markUnseen(&self.seen.risk_tier_prod_bg, line_no, key.column);
            self.modules.risk_tier.prod_bg = try self.parseRiskTierColor(value, line_no);
        } else {
            return self.fail(line_no, key.column, "unknown key");
        }
    }

    fn parseRiskTierColor(self: *Parser, value: Trimmed, line_no: usize) !RiskTierColor {
        const color = try self.parseStringAlloc(value, line_no);
        defer self.allocator.free(color);
        return risk_tier_module.parseColorSlot(color) orelse self.fail(line_no, value.column, "invalid risk_tier color");
    }

    fn parseSsoExpiryKey(self: *Parser, line_no: usize, key: Trimmed, value: Trimmed) !void {
        if (!std.mem.eql(u8, key.text, "warning_minutes")) return self.fail(line_no, key.column, "unknown key");
        try self.markUnseen(&self.seen.sso_expiry_warning_minutes, line_no, key.column);
        self.modules.sso_expiry.warning_minutes = @intCast(try self.parseIntRange(value, line_no, 1, 1440));
    }

    fn parseTimeKey(self: *Parser, line_no: usize, key: Trimmed, value: Trimmed) !void {
        if (std.mem.eql(u8, key.text, "format")) {
            try self.markUnseen(&self.seen.time_format, line_no, key.column);
            const format = try self.parseStringAlloc(value, line_no);
            defer self.allocator.free(format);
            if (!std.mem.eql(u8, format, "24h")) return self.fail(line_no, value.column, "invalid time format");
            self.modules.time.format_24h = true;
        } else if (std.mem.eql(u8, key.text, "utc")) {
            try self.markUnseen(&self.seen.time_utc, line_no, key.column);
            const utc = try self.parseBool(value, line_no);
            if (!utc) return self.fail(line_no, value.column, "local time unsupported");
            self.modules.time.utc = utc;
        } else {
            return self.fail(line_no, key.column, "unknown key");
        }
    }

    fn parseModuleArray(self: *Parser, value: Trimmed, line_no: usize) !void {
        if (value.text.len < 2 or value.text[0] != '[' or value.text[value.text.len - 1] != ']') {
            return self.fail(line_no, value.column, "expected array");
        }

        var index: usize = 1;
        while (index < value.text.len - 1) {
            skipSpaces(value.text, &index);
            if (index >= value.text.len - 1) break;
            if (value.text[index] != '"') return self.fail(line_no, value.column + index, "expected string");
            const start = index + 1;
            index = start;
            while (index < value.text.len - 1 and value.text[index] != '"') : (index += 1) {}
            if (index >= value.text.len - 1) return self.fail(line_no, value.column + start, "unterminated string");

            const raw_id = value.text[start..index];
            if (std.mem.indexOfScalar(u8, raw_id, '\\') != null) return self.fail(line_no, value.column + start, "invalid module id");
            const module_id = parseModuleId(raw_id) orelse return self.fail(line_no, value.column + start, "unknown module id");
            for (self.prompt_modules.items) |existing| {
                if (existing == module_id) return self.fail(line_no, value.column + start, "duplicate module id");
            }
            try self.prompt_modules.append(self.allocator, module_id);

            index += 1;
            skipSpaces(value.text, &index);
            if (index >= value.text.len - 1) break;
            if (value.text[index] != ',') return self.fail(line_no, value.column + index, "expected comma");
            index += 1;
        }
    }

    fn parseLanguageDetectArray(self: *Parser, value: Trimmed, line_no: usize) !LanguageVersionsOptions {
        if (value.text.len < 2 or value.text[0] != '[' or value.text[value.text.len - 1] != ']') {
            return self.fail(line_no, value.column, "expected array");
        }

        var options = LanguageVersionsOptions{ .python = false, .node = false, .rust = false, .go = false };
        var index: usize = 1;
        while (index < value.text.len - 1) {
            skipSpaces(value.text, &index);
            if (index >= value.text.len - 1) break;
            if (value.text[index] != '"') return self.fail(line_no, value.column + index, "expected string");
            const start = index + 1;
            index = start;
            while (index < value.text.len - 1 and value.text[index] != '"') : (index += 1) {}
            if (index >= value.text.len - 1) return self.fail(line_no, value.column + start, "unterminated string");

            const name = value.text[start..index];
            if (std.mem.eql(u8, name, "python")) {
                if (options.python) return self.fail(line_no, value.column + start, "duplicate language id");
                options.python = true;
            } else if (std.mem.eql(u8, name, "node")) {
                if (options.node) return self.fail(line_no, value.column + start, "duplicate language id");
                options.node = true;
            } else if (std.mem.eql(u8, name, "rust")) {
                if (options.rust) return self.fail(line_no, value.column + start, "duplicate language id");
                options.rust = true;
            } else if (std.mem.eql(u8, name, "go")) {
                if (options.go) return self.fail(line_no, value.column + start, "duplicate language id");
                options.go = true;
            } else {
                return self.fail(line_no, value.column + start, "unknown language id");
            }

            index += 1;
            skipSpaces(value.text, &index);
            if (index >= value.text.len - 1) break;
            if (value.text[index] != ',') return self.fail(line_no, value.column + index, "expected comma");
            index += 1;
        }

        return options;
    }

    fn parseStringAlloc(self: *Parser, value: Trimmed, line_no: usize) ![]u8 {
        if (value.text.len < 2 or value.text[0] != '"' or value.text[value.text.len - 1] != '"') {
            return self.fail(line_no, value.column, "expected string");
        }

        var out: std.ArrayList(u8) = .empty;
        errdefer out.deinit(self.allocator);

        var index: usize = 1;
        while (index < value.text.len - 1) : (index += 1) {
            const byte = value.text[index];
            if (byte == '\\') {
                index += 1;
                if (index >= value.text.len - 1) return self.fail(line_no, value.column + index, "invalid escape");
                switch (value.text[index]) {
                    '"' => try out.append(self.allocator, '"'),
                    '\\' => try out.append(self.allocator, '\\'),
                    'n' => try out.append(self.allocator, '\n'),
                    'r' => try out.append(self.allocator, '\r'),
                    't' => try out.append(self.allocator, '\t'),
                    else => return self.fail(line_no, value.column + index, "invalid escape"),
                }
            } else {
                try out.append(self.allocator, byte);
            }
        }

        return out.toOwnedSlice(self.allocator);
    }

    fn parseBool(self: *Parser, value: Trimmed, line_no: usize) !bool {
        if (std.mem.eql(u8, value.text, "true")) return true;
        if (std.mem.eql(u8, value.text, "false")) return false;
        return self.fail(line_no, value.column, "expected bool");
    }

    fn parseIntRange(self: *Parser, value: Trimmed, line_no: usize, min: i64, max: i64) !i64 {
        const parsed = std.fmt.parseInt(i64, value.text, 10) catch return self.fail(line_no, value.column, "expected integer");
        if (parsed < min or parsed > max) return self.fail(line_no, value.column, "integer out of range");
        return parsed;
    }

    fn markUnseen(self: *Parser, seen: *bool, line_no: usize, column: usize) !void {
        if (seen.*) return self.fail(line_no, column, "duplicate key");
        seen.* = true;
    }

    fn fail(self: *Parser, line_no: usize, column: usize, message: []const u8) error{InvalidConfig} {
        self.diagnostic.* = .{
            .message = message,
            .line = line_no,
            .column = column,
        };
        return error.InvalidConfig;
    }
};

fn parseTableName(name: []const u8) ?Table {
    if (std.mem.eql(u8, name, "prompt")) return .prompt;
    if (std.mem.eql(u8, name, "modules.cwd")) return .cwd;
    if (std.mem.eql(u8, name, "modules.git_branch")) return .git_branch;
    if (std.mem.eql(u8, name, "modules.language_versions")) return .language_versions;
    if (std.mem.eql(u8, name, "modules.exit_status")) return .exit_status;
    if (std.mem.eql(u8, name, "modules.jobs")) return .jobs;
    if (std.mem.eql(u8, name, "modules.cmd_duration")) return .cmd_duration;
    if (std.mem.eql(u8, name, "modules.user_host")) return .user_host;
    if (std.mem.eql(u8, name, "modules.cloud_ctx")) return .cloud_ctx;
    if (std.mem.eql(u8, name, "modules.risk_tier")) return .risk_tier;
    if (std.mem.eql(u8, name, "modules.sso_expiry")) return .sso_expiry;
    if (std.mem.eql(u8, name, "modules.time")) return .time;
    return null;
}

fn parseModuleId(id: []const u8) ?ModuleId {
    if (std.mem.eql(u8, id, "cwd")) return .cwd;
    if (std.mem.eql(u8, id, "git_branch")) return .git_branch;
    if (std.mem.eql(u8, id, "language_versions")) return .language_versions;
    if (std.mem.eql(u8, id, "exit_status")) return .exit_status;
    if (std.mem.eql(u8, id, "jobs")) return .jobs;
    if (std.mem.eql(u8, id, "cmd_duration")) return .cmd_duration;
    if (std.mem.eql(u8, id, "user_host")) return .user_host;
    if (std.mem.eql(u8, id, "cloud_ctx")) return .cloud_ctx;
    if (std.mem.eql(u8, id, "risk_tier")) return .risk_tier;
    if (std.mem.eql(u8, id, "sso_expiry")) return .sso_expiry;
    if (std.mem.eql(u8, id, "time")) return .time;
    return null;
}

fn stripComment(line: []const u8) []const u8 {
    var in_string = false;
    var escaped = false;
    for (line, 0..) |byte, index| {
        if (escaped) {
            escaped = false;
            continue;
        }
        if (byte == '\\' and in_string) {
            escaped = true;
            continue;
        }
        if (byte == '"') {
            in_string = !in_string;
            continue;
        }
        if (byte == '#' and !in_string) return line[0..index];
    }
    return line;
}

fn trimWithColumn(value: []const u8, base_column: usize) Trimmed {
    var start: usize = 0;
    var end: usize = value.len;
    while (start < end and isSpace(value[start])) : (start += 1) {}
    while (end > start and isSpace(value[end - 1])) : (end -= 1) {}
    return .{
        .text = value[start..end],
        .column = base_column + start,
    };
}

fn findEquals(value: []const u8) ?usize {
    var in_string = false;
    var escaped = false;
    for (value, 0..) |byte, index| {
        if (escaped) {
            escaped = false;
            continue;
        }
        if (byte == '\\' and in_string) {
            escaped = true;
            continue;
        }
        if (byte == '"') {
            in_string = !in_string;
            continue;
        }
        if (byte == '=' and !in_string) return index;
    }
    return null;
}

fn skipSpaces(value: []const u8, index: *usize) void {
    while (index.* < value.len and isSpace(value[index.*])) : (index.* += 1) {}
}

fn isSpace(byte: u8) bool {
    return byte == ' ' or byte == '\t' or byte == '\r' or byte == '\n';
}

test "parses minimal config with defaults" {
    const source =
        \\version = 1
        \\theme = "plain"
        \\
        \\[prompt]
        \\modules = ["cwd", "git_branch", "exit_status"]
        \\
    ;

    var diagnostic: Diagnostic = .{};
    var config = try parse(std.testing.allocator, source, &diagnostic);
    defer config.deinit(std.testing.allocator);

    try std.testing.expectEqual(@as(u32, 1), config.version);
    try std.testing.expectEqualStrings("plain", config.theme);
    try std.testing.expectEqualSlices(ModuleId, &.{ .cwd, .git_branch, .exit_status }, config.prompt_modules);
    try std.testing.expectEqual(@as(u8, 3), config.modules.cwd.truncate_to);
}

test "module metadata names execution classes" {
    try std.testing.expectEqualStrings("cwd", moduleIdName(.cwd));
    try std.testing.expectEqualStrings("sync", moduleExecutionClass(.cwd));
    try std.testing.expectEqualStrings("risk_tier", moduleIdName(.risk_tier));
    try std.testing.expectEqualStrings("sync", moduleExecutionClass(.risk_tier));
    try std.testing.expectEqualStrings("async", moduleExecutionClass(.git_branch));
    try std.testing.expectEqualStrings("async", moduleExecutionClass(.language_versions));
}

test "default config parses" {
    var diagnostic: Diagnostic = .{};
    var config = try parse(std.testing.allocator, default_config_text, &diagnostic);
    defer config.deinit(std.testing.allocator);

    try std.testing.expectEqualStrings("plain", config.theme);
    try std.testing.expectEqualSlices(ModuleId, default_modules[0..], config.prompt_modules);
}

test "parses per-module options" {
    const source =
        \\version = 1
        \\theme = "minimal"
        \\
        \\[prompt]
        \\modules = ["cwd", "time"]
        \\
        \\[modules.cwd]
        \\truncate_to = 2
        \\home_tilde = false
        \\
        \\[modules.git_branch]
        \\show_dirty = false
        \\cache_ttl_ms = 0
        \\
        \\[modules.language_versions]
        \\detect = ["python", "go"]
        \\
        \\[modules.cmd_duration]
        \\threshold_ms = 42
        \\
        \\[modules.user_host]
        \\mode = "always"
        \\
        \\[modules.cloud_ctx]
        \\aws = false
        \\gcp = true
        \\azure = false
        \\kubernetes = true
        \\
        \\[modules.risk_tier]
        \\unknown_bg = "muted"
        \\dev_bg = "accent"
        \\staging_bg = "warning"
        \\prod_bg = "danger"
        \\
        \\[modules.time]
        \\format = "24h"
        \\utc = true
        \\
    ;

    var diagnostic: Diagnostic = .{};
    var config = try parse(std.testing.allocator, source, &diagnostic);
    defer config.deinit(std.testing.allocator);

    try std.testing.expectEqualStrings("minimal", config.theme);
    try std.testing.expectEqualSlices(ModuleId, &.{ .cwd, .time }, config.prompt_modules);
    try std.testing.expectEqual(@as(u8, 2), config.modules.cwd.truncate_to);
    try std.testing.expect(!config.modules.cwd.home_tilde);
    try std.testing.expect(!config.modules.git_branch.show_dirty);
    try std.testing.expectEqual(@as(u32, 0), config.modules.git_branch.cache_ttl_ms);
    try std.testing.expect(config.modules.language_versions.python);
    try std.testing.expect(!config.modules.language_versions.node);
    try std.testing.expect(!config.modules.language_versions.rust);
    try std.testing.expect(config.modules.language_versions.go);
    try std.testing.expectEqual(@as(u64, 42), config.modules.cmd_duration.threshold_ms);
    try std.testing.expectEqual(UserHostMode.always, config.modules.user_host.mode);
    try std.testing.expect(!config.modules.cloud_ctx.aws);
    try std.testing.expect(config.modules.cloud_ctx.gcp);
    try std.testing.expect(!config.modules.cloud_ctx.azure);
    try std.testing.expect(config.modules.cloud_ctx.kubernetes);
    try std.testing.expectEqual(RiskTierColor.muted, config.modules.risk_tier.unknown_bg);
    try std.testing.expectEqual(RiskTierColor.accent, config.modules.risk_tier.dev_bg);
    try std.testing.expectEqual(RiskTierColor.warning, config.modules.risk_tier.staging_bg);
    try std.testing.expectEqual(RiskTierColor.danger, config.modules.risk_tier.prod_bg);
    try std.testing.expect(config.modules.time.utc);
}

test "reports unknown key span" {
    const source =
        \\version = 1
        \\bogus = true
        \\
    ;

    var diagnostic: Diagnostic = .{};
    try std.testing.expectError(error.InvalidConfig, parse(std.testing.allocator, source, &diagnostic));
    try std.testing.expectEqual(@as(usize, 2), diagnostic.line);
    try std.testing.expectEqual(@as(usize, 1), diagnostic.column);
    try std.testing.expectEqualStrings("unknown key", diagnostic.message);
}

test "rejects duplicate module id" {
    const source =
        \\version = 1
        \\
        \\[prompt]
        \\modules = ["cwd", "cwd"]
        \\
    ;

    var diagnostic: Diagnostic = .{};
    try std.testing.expectError(error.InvalidConfig, parse(std.testing.allocator, source, &diagnostic));
    try std.testing.expectEqualStrings("duplicate module id", diagnostic.message);
    try std.testing.expectEqual(@as(usize, 4), diagnostic.line);
}

test "rejects option range violation" {
    const source =
        \\version = 1
        \\
        \\[modules.cwd]
        \\truncate_to = 99
        \\
    ;

    var diagnostic: Diagnostic = .{};
    try std.testing.expectError(error.InvalidConfig, parse(std.testing.allocator, source, &diagnostic));
    try std.testing.expectEqual(@as(usize, 4), diagnostic.line);
    try std.testing.expectEqual(@as(usize, 15), diagnostic.column);
    try std.testing.expectEqualStrings("integer out of range", diagnostic.message);
}
