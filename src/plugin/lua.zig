const std = @import("std");
const builtin = @import("builtin");
const manifest_schema = @import("manifest.zig");
const capability_schema = @import("capability.zig");
const context_schema = @import("context.zig");

pub const manifest = manifest_schema;
pub const capability = capability_schema;
pub const context = context_schema;
pub const trust = @import("trust.zig");

const LuaState = opaque {};
const CInt = c_int;

const lua_ok = 0;
const lua_tnil = 0;
const lua_tboolean = 1;
const lua_tnumber = 3;
const lua_tstring = 4;
const lua_ttable = 5;
const lua_globalsindex = -10002;
const lua_maskline = 1 << 2;
const lua_maskcount = 1 << 3;
const lua_hook_count = 1;

pub const Vm = enum {
    luajit,
};

pub const selected_vm: Vm = .luajit;
pub const default_memory_limit_bytes: usize = 16 * 1024 * 1024;
pub const default_cpu_budget_ns: u64 = std.time.ns_per_ms;
pub const default_cpu_hard_limit_ns: u64 = if (builtin.mode == .Debug) 5 * std.time.ns_per_ms else default_cpu_budget_ns;

const always_removed_globals = [_][]const u8{
    "debug",
    "dofile",
    "io",
    "loadfile",
    "os",
    "package",
};

const LuaAlloc = *const fn (?*anyopaque, ?*anyopaque, usize, usize) callconv(.c) ?*anyopaque;
const LuaNewState = *const fn (LuaAlloc, ?*anyopaque) callconv(.c) ?*LuaState;
const LuaDebug = opaque {};
const LuaHook = *const fn (?*LuaState, ?*LuaDebug) callconv(.c) void;
const LuaClose = *const fn (?*LuaState) callconv(.c) void;
const LuaLOpenLibs = *const fn (?*LuaState) callconv(.c) void;
const LuaLLoadBuffer = *const fn (?*LuaState, [*]const u8, usize, [*:0]const u8) callconv(.c) CInt;
const LuaPCall = *const fn (?*LuaState, CInt, CInt, CInt) callconv(.c) CInt;
const LuaGetField = *const fn (?*LuaState, CInt, [*:0]const u8) callconv(.c) void;
const LuaSetField = *const fn (?*LuaState, CInt, [*:0]const u8) callconv(.c) void;
const LuaPushNil = *const fn (?*LuaState) callconv(.c) void;
const LuaToBoolean = *const fn (?*LuaState, CInt) callconv(.c) CInt;
const LuaToNumber = *const fn (?*LuaState, CInt) callconv(.c) f64;
const LuaToLString = *const fn (?*LuaState, CInt, *usize) callconv(.c) ?[*]const u8;
const LuaObjLen = *const fn (?*LuaState, CInt) callconv(.c) usize;
const LuaRawGetI = *const fn (?*LuaState, CInt, CInt) callconv(.c) void;
const LuaType = *const fn (?*LuaState, CInt) callconv(.c) CInt;
const LuaGetTop = *const fn (?*LuaState) callconv(.c) CInt;
const LuaNext = *const fn (?*LuaState, CInt) callconv(.c) CInt;
const LuaSetTop = *const fn (?*LuaState, CInt) callconv(.c) void;
const LuaSetHook = *const fn (?*LuaState, ?LuaHook, CInt, CInt) callconv(.c) CInt;
const LuaPushString = *const fn (?*LuaState, [*:0]const u8) callconv(.c) ?[*:0]const u8;
const LuaPushLString = *const fn (?*LuaState, [*]const u8, usize) callconv(.c) ?[*:0]const u8;
const LuaPushBoolean = *const fn (?*LuaState, CInt) callconv(.c) void;
const LuaPushLightUserData = *const fn (?*LuaState, ?*anyopaque) callconv(.c) void;
const LuaPushCClosure = *const fn (?*LuaState, LuaCFunction, CInt) callconv(.c) void;
const LuaToUserData = *const fn (?*LuaState, CInt) callconv(.c) ?*anyopaque;
const LuaError = *const fn (?*LuaState) callconv(.c) CInt;
const LuaCFunction = *const fn (?*LuaState) callconv(.c) CInt;

extern fn shisa_lua_install_budget_hook(LuaPushString, LuaError, *const fn () callconv(.c) CInt) void;
extern fn shisa_lua_budget_hook(?*LuaState, ?*LuaDebug) callconv(.c) void;

const Api = struct {
    lua_newstate: LuaNewState,
    lua_close: LuaClose,
    luaL_openlibs: LuaLOpenLibs,
    luaL_loadbuffer: LuaLLoadBuffer,
    lua_pcall: LuaPCall,
    lua_getfield: LuaGetField,
    lua_setfield: LuaSetField,
    lua_pushnil: LuaPushNil,
    lua_toboolean: LuaToBoolean,
    lua_tonumber: LuaToNumber,
    lua_tolstring: LuaToLString,
    lua_objlen: LuaObjLen,
    lua_rawgeti: LuaRawGetI,
    lua_type: LuaType,
    lua_gettop: LuaGetTop,
    lua_next: LuaNext,
    lua_settop: LuaSetTop,
    lua_sethook: LuaSetHook,
    lua_pushstring: LuaPushString,
    lua_pushlstring: LuaPushLString,
    lua_pushboolean: LuaPushBoolean,
    lua_pushlightuserdata: LuaPushLightUserData,
    lua_pushcclosure: LuaPushCClosure,
    lua_touserdata: LuaToUserData,
    lua_error: LuaError,
};

/// The host API is installed only after the manifest has been validated. Lua
/// code can access it solely through a lifecycle context constructed by Shisa;
/// the manifest itself therefore cannot perform host calls while loading.
pub const HostMethod = enum(c_int) {
    fs_read,
    fs_watch,
    env_get,
    secret_get,
    exec_run,
    net_get,
    cache_get,
    cache_set,
};

pub const HostCallback = *const fn (*Runtime, ?*anyopaque, HostMethod) callconv(.c) CInt;

const HostClosure = struct {
    host: *HostApi,
    method: HostMethod,
};

pub const HostApi = struct {
    callback: HostCallback,
    user_data: ?*anyopaque,
    runtime: ?*Runtime = null,
    closures: [@typeInfo(HostMethod).@"enum".fields.len]HostClosure = undefined,
};

pub const OwnedManifest = struct {
    manifest: manifest_schema.Manifest,
    name: []u8,
    version: []u8,
    license: []u8,
    modules: [][]u8,
    fs_read: [][]u8 = &.{},
    fs_watch: [][]u8 = &.{},
    exec_allow: ?[][]u8 = null,
    net_allow: ?[][]u8 = null,
    env_read: [][]u8 = &.{},
    on_load: ?[]u8 = null,
    render: []u8,
    update: ?[]u8 = null,
    pre_exec: ?[]u8 = null,
    on_unload: ?[]u8 = null,
    description: ?[]u8 = null,
    author: ?[]u8 = null,
    homepage: ?[]u8 = null,
    repository: ?[]u8 = null,

    pub fn deinit(self: *OwnedManifest, allocator: std.mem.Allocator) void {
        allocator.free(self.name);
        allocator.free(self.version);
        allocator.free(self.license);
        freeStringList(allocator, self.modules);
        freeStringList(allocator, self.fs_read);
        freeStringList(allocator, self.fs_watch);
        if (self.exec_allow) |items| freeStringList(allocator, items);
        if (self.net_allow) |items| freeStringList(allocator, items);
        freeStringList(allocator, self.env_read);
        if (self.on_load) |value| allocator.free(value);
        allocator.free(self.render);
        if (self.update) |value| allocator.free(value);
        if (self.pre_exec) |value| allocator.free(value);
        if (self.on_unload) |value| allocator.free(value);
        if (self.description) |value| allocator.free(value);
        if (self.author) |value| allocator.free(value);
        if (self.homepage) |value| allocator.free(value);
        if (self.repository) |value| allocator.free(value);
        self.* = undefined;
    }
};

pub const SandboxOptions = struct {
    require_root: ?[]const u8 = null,
    memory_limit_bytes: usize = default_memory_limit_bytes,
    cpu_budget_ns: u64 = default_cpu_budget_ns,
    cpu_hard_limit_ns: u64 = default_cpu_hard_limit_ns,
};

pub const RuntimeOptions = struct {
    memory_limit_bytes: usize = default_memory_limit_bytes,
    cpu_budget_ns: u64 = default_cpu_budget_ns,
    cpu_hard_limit_ns: u64 = default_cpu_hard_limit_ns,
};

pub const Runtime = struct {
    allocator: std.mem.Allocator,
    lib: std.DynLib,
    api: Api,
    state: *LuaState,
    memory_limiter: *LuaMemoryLimiter,
    cpu_budget_ns: u64,
    cpu_hard_limit_ns: u64,
    last_cpu_elapsed_ns: u64 = 0,

    pub fn init(allocator: std.mem.Allocator) !Runtime {
        return initWithOptions(allocator, .{});
    }

    pub fn initWithMemoryLimit(allocator: std.mem.Allocator, memory_limit_bytes: usize) !Runtime {
        return initWithOptions(allocator, .{ .memory_limit_bytes = memory_limit_bytes });
    }

    pub fn initWithOptions(allocator: std.mem.Allocator, options: RuntimeOptions) !Runtime {
        var lib = try openSelectedVm();
        errdefer lib.close();
        const api = try loadApi(&lib);
        const limiter = try allocator.create(LuaMemoryLimiter);
        errdefer allocator.destroy(limiter);
        limiter.* = .{ .limit = options.memory_limit_bytes };
        const state = api.lua_newstate(luaMemoryAlloc, limiter) orelse return error.LuaOutOfMemory;
        api.luaL_openlibs(state);
        var runtime = Runtime{
            .allocator = allocator,
            .lib = lib,
            .api = api,
            .state = state,
            .memory_limiter = limiter,
            .cpu_budget_ns = options.cpu_budget_ns,
            .cpu_hard_limit_ns = options.cpu_hard_limit_ns,
        };
        errdefer runtime.deinit();
        try runtime.disableJit();
        return runtime;
    }

    pub fn initSandboxed(allocator: std.mem.Allocator) !Runtime {
        return initSandboxedWithOptions(allocator, .{});
    }

    pub fn initSandboxedWithOptions(allocator: std.mem.Allocator, options: SandboxOptions) !Runtime {
        var runtime = try initWithOptions(allocator, .{
            .memory_limit_bytes = options.memory_limit_bytes,
            .cpu_budget_ns = options.cpu_budget_ns,
            .cpu_hard_limit_ns = options.cpu_hard_limit_ns,
        });
        errdefer runtime.deinit();
        if (options.require_root) |root| try runtime.configureLocalRequire(root);
        try runtime.stripDangerousGlobals(options.require_root != null);
        return runtime;
    }

    pub fn deinit(self: *Runtime) void {
        self.api.lua_close(self.state);
        self.allocator.destroy(self.memory_limiter);
        self.lib.close();
        self.* = undefined;
    }

    pub fn doString(self: *Runtime, source: []const u8) !void {
        try self.loadBuffer(source, "shisa-string");
        try self.protectedCall(0, 0);
        self.clearStack();
    }

    pub fn loadManifest(self: *Runtime, source: []const u8) !OwnedManifest {
        return self.loadManifestWithMode(source, false);
    }

    pub fn loadManifestStrict(self: *Runtime, source: []const u8) !OwnedManifest {
        return self.loadManifestWithMode(source, true);
    }

    fn loadManifestWithMode(self: *Runtime, source: []const u8, strict: bool) !OwnedManifest {
        try self.loadBuffer(source, "plugin.lua");
        try self.protectedCall(0, 1);
        defer self.clearStack();
        if (self.api.lua_type(self.state, 1) != lua_ttable) return error.InvalidManifest;
        if (strict) try self.rejectUnknownFields(1, &top_level_manifest_fields);
        var loaded = try self.readManifestAt(1, strict);
        errdefer loaded.deinit(self.allocator);
        try loaded.manifest.validate();
        return loaded;
    }

    pub fn globalIsNil(self: *Runtime, name: []const u8) !bool {
        const global = try self.allocator.dupeZ(u8, name);
        defer self.allocator.free(global);
        self.api.lua_getfield(self.state, lua_globalsindex, global.ptr);
        const is_nil = self.api.lua_type(self.state, -1) == lua_tnil;
        self.clearStack();
        return is_nil;
    }

    /// Bind the stable host state for this VM. Every callback receives a
    /// pointer to this runtime and an opaque host-owned context; neither is
    /// visible as a mutable Lua value.
    pub fn installHostApi(self: *Runtime, host: *HostApi) !void {
        host.runtime = self;
        inline for (std.meta.fields(HostMethod), 0..) |field, index| {
            host.closures[index] = .{
                .host = host,
                .method = @enumFromInt(field.value),
            };
            self.api.lua_pushlightuserdata(self.state, @ptrCast(&host.closures[index]));
            self.api.lua_pushcclosure(self.state, luaHostCallback, 1);
            try self.setGlobal(hostMethodName(@enumFromInt(field.value)));
        }
    }

    /// Borrow the string argument currently on the stack of a host callback.
    /// It must not outlive the callback invocation.
    pub fn hostArgumentString(self: *Runtime, index: CInt) ?[]const u8 {
        if (self.api.lua_type(self.state, index) != lua_tstring) return null;
        var len: usize = 0;
        const ptr = self.api.lua_tolstring(self.state, index, &len) orelse return null;
        return ptr[0..len];
    }

    pub fn hostArgumentStringArrayAlloc(self: *Runtime, allocator: std.mem.Allocator, index: CInt) !?[][]u8 {
        if (self.api.lua_type(self.state, index) != lua_ttable) return null;
        const len = self.api.lua_objlen(self.state, index);
        const out = try allocator.alloc([]u8, len);
        var initialized: usize = 0;
        errdefer {
            for (out[0..initialized]) |value| allocator.free(value);
            allocator.free(out);
        }
        for (out, 0..) |*slot, zero_index| {
            self.api.lua_rawgeti(self.state, index, @intCast(zero_index + 1));
            defer self.pop(1);
            const value = self.hostArgumentString(-1) orelse return error.InvalidHostArgument;
            slot.* = try allocator.dupe(u8, value);
            initialized += 1;
        }
        return out;
    }

    pub fn hostPushString(self: *Runtime, value: []const u8) void {
        _ = self.api.lua_pushlstring(self.state, value.ptr, value.len);
    }

    pub fn hostPushBoolean(self: *Runtime, value: bool) void {
        self.api.lua_pushboolean(self.state, if (value) 1 else 0);
    }

    pub fn hostPushNil(self: *Runtime) void {
        self.api.lua_pushnil(self.state);
    }

    /// Invoke a manifest-declared global with a host-created Lua expression.
    /// The expression is deliberately supplied by Zig, never by plugin input;
    /// it is used to construct the read-only lifecycle context without
    /// exposing the Lua loader or string-evaluation APIs to plugins.
    pub fn callGlobalStringAlloc(self: *Runtime, name: []const u8, context_expression: []const u8) !?[]u8 {
        const quoted_name = try luaQuoteAlloc(self.allocator, name);
        defer self.allocator.free(quoted_name);
        const source = try std.fmt.allocPrint(
            self.allocator,
            "local f = _G[{s}]; if type(f) ~= 'function' then return nil end; return f({s})",
            .{ quoted_name, context_expression },
        );
        defer self.allocator.free(source);
        try self.loadBuffer(source, "shisa-plugin-hook");
        try self.protectedCall(0, 1);
        defer self.clearStack();
        return switch (self.api.lua_type(self.state, -1)) {
            lua_tnil => null,
            lua_tstring => try self.stringAt(-1),
            else => error.InvalidPluginHookResult,
        };
    }

    pub fn callGlobalNoResult(self: *Runtime, name: []const u8, context_expression: []const u8) !void {
        const quoted_name = try luaQuoteAlloc(self.allocator, name);
        defer self.allocator.free(quoted_name);
        const source = try std.fmt.allocPrint(
            self.allocator,
            "local f = _G[{s}]; if type(f) == 'function' then f({s}) end",
            .{ quoted_name, context_expression },
        );
        defer self.allocator.free(source);
        try self.loadBuffer(source, "shisa-plugin-hook");
        try self.protectedCall(0, 0);
        self.clearStack();
    }

    pub const PreexecDecision = struct {
        allow: ?bool = null,
        message: ?[]u8 = null,

        pub fn deinit(self: *PreexecDecision, allocator: std.mem.Allocator) void {
            if (self.message) |value| allocator.free(value);
            self.* = undefined;
        }
    };

    /// A pre-exec hook may return nil (no opinion) or a table containing an
    /// optional boolean `allow` and optional string `message`.
    pub fn callGlobalPreexecDecisionAlloc(self: *Runtime, name: []const u8, context_expression: []const u8) !?PreexecDecision {
        const quoted_name = try luaQuoteAlloc(self.allocator, name);
        defer self.allocator.free(quoted_name);
        const source = try std.fmt.allocPrint(
            self.allocator,
            "local f = _G[{s}]; if type(f) ~= 'function' then return nil end; return f({s})",
            .{ quoted_name, context_expression },
        );
        defer self.allocator.free(source);
        try self.loadBuffer(source, "shisa-plugin-preexec");
        try self.protectedCall(0, 1);
        defer self.clearStack();
        if (self.api.lua_type(self.state, -1) == lua_tnil) return null;
        if (self.api.lua_type(self.state, -1) != lua_ttable) return error.InvalidPluginHookResult;
        const table_index = self.api.lua_gettop(self.state);
        var decision = PreexecDecision{};
        errdefer decision.deinit(self.allocator);
        {
            try self.pushField(table_index, "allow");
            defer self.pop(1);
            const allow_type = self.api.lua_type(self.state, -1);
            if (allow_type == lua_tboolean) {
                decision.allow = self.api.lua_toboolean(self.state, -1) != 0;
            } else if (allow_type != lua_tnil) {
                return error.InvalidPluginHookResult;
            }
        }
        {
            try self.pushField(table_index, "message");
            defer self.pop(1);
            const message_type = self.api.lua_type(self.state, -1);
            if (message_type == lua_tstring) {
                decision.message = try self.stringAt(-1);
            } else if (message_type != lua_tnil) {
                return error.InvalidPluginHookResult;
            }
        }
        return decision;
    }

    /// plugin-api: sandbox | removed_globals | `os`, `io`, `package`, `debug`, `dofile`, `loadfile` | always | sandbox startup removes direct shell, filesystem, loader, debug, and package APIs from Lua globals.
    /// plugin-api: sandbox | require | project-local module name | opt-in | `initSandboxedWithOptions(.require_root)` allows `require` only through `<root>/?.lua` and `<root>/?/init.lua`.
    fn stripDangerousGlobals(self: *Runtime, keep_require: bool) !void {
        for (always_removed_globals) |name| try self.stripGlobal(name);
        if (!keep_require) try self.stripGlobal("require");
    }

    fn configureLocalRequire(self: *Runtime, root: []const u8) !void {
        const quoted_root = try luaQuoteAlloc(self.allocator, root);
        defer self.allocator.free(quoted_root);
        const source = try std.fmt.allocPrint(
            self.allocator,
            \\do
            \\  local root = {s}
            \\  package.path = root .. "/?.lua;" .. root .. "/?/init.lua"
            \\  package.cpath = ""
            \\  package.loadlib = nil
            \\  local original_require = require
            \\  require = function(name)
            \\    if type(name) ~= "string" or name:find("/", 1, true) or name:find("\\", 1, true) or name:find("..", 1, true) then
            \\      error("require outside plugin root", 2)
            \\    end
            \\    return original_require(name)
            \\  end
            \\end
        ,
            .{quoted_root},
        );
        defer self.allocator.free(source);
        try self.doString(source);
    }

    fn stripGlobal(self: *Runtime, name: []const u8) !void {
        const global = try self.allocator.dupeZ(u8, name);
        defer self.allocator.free(global);
        self.api.lua_pushnil(self.state);
        self.api.lua_setfield(self.state, lua_globalsindex, global.ptr);
    }

    fn setGlobal(self: *Runtime, name: []const u8) !void {
        const global = try self.allocator.dupeZ(u8, name);
        defer self.allocator.free(global);
        self.api.lua_setfield(self.state, lua_globalsindex, global.ptr);
    }

    fn loadBuffer(self: *Runtime, source: []const u8, name: []const u8) !void {
        const name_z = try self.allocator.dupeZ(u8, name);
        defer self.allocator.free(name_z);
        if (self.api.luaL_loadbuffer(self.state, source.ptr, source.len, name_z.ptr) != lua_ok) {
            self.clearStack();
            return error.LuaLoadError;
        }
    }

    fn disableJit(self: *Runtime) !void {
        try self.loadBuffer("if jit then jit.off(true, true) end", "shisa-jit-off");
        if (self.api.lua_pcall(self.state, 0, 0, 0) != lua_ok) {
            self.clearStack();
            return error.LuaRuntimeError;
        }
        self.clearStack();
    }

    fn protectedCall(self: *Runtime, nargs: CInt, nresults: CInt) !void {
        var budget = LuaExecutionBudget{
            .start_ns = std.time.nanoTimestamp(),
            .hard_limit_ns = self.cpu_hard_limit_ns,
        };
        const previous_budget = active_lua_budget;
        const previous_api = active_lua_api;
        active_lua_budget = &budget;
        active_lua_api = &self.api;
        defer {
            active_lua_budget = previous_budget;
            active_lua_api = previous_api;
        }

        shisa_lua_install_budget_hook(self.api.lua_pushstring, self.api.lua_error, shisaLuaBudgetExceeded);
        _ = self.api.lua_sethook(self.state, shisa_lua_budget_hook, lua_maskline | lua_maskcount, lua_hook_count);
        defer _ = self.api.lua_sethook(self.state, null, 0, 0);

        const status = self.api.lua_pcall(self.state, nargs, nresults, 0);
        self.last_cpu_elapsed_ns = elapsedNsSince(budget.start_ns);
        if (status != lua_ok) {
            self.clearStack();
            if (budget.hit_hard_limit) return error.LuaCpuBudgetExceeded;
            return error.LuaRuntimeError;
        }
        if (self.last_cpu_elapsed_ns > self.cpu_budget_ns) {
            self.clearStack();
            return error.LuaCpuBudgetExceeded;
        }
    }

    fn readManifestAt(self: *Runtime, index: CInt, strict: bool) !OwnedManifest {
        const name = try self.requiredStringField(index, "name");
        errdefer self.allocator.free(name);
        const version = try self.requiredStringField(index, "version");
        errdefer self.allocator.free(version);
        const api_version = try self.requiredApiVersion(index);
        const license = try self.requiredStringField(index, "license");
        errdefer self.allocator.free(license);
        const modules = try self.requiredStringListField(index, "modules");
        errdefer freeStringList(self.allocator, modules);
        const on_load = try self.optionalStringField(index, "on_load");
        errdefer if (on_load) |value| self.allocator.free(value);
        const render = try self.optionalStringField(index, "render") orelse try self.allocator.dupe(u8, "render");
        errdefer self.allocator.free(render);
        const update = try self.optionalStringField(index, "update");
        errdefer if (update) |value| self.allocator.free(value);
        const pre_exec = try self.optionalStringField(index, "pre_exec");
        errdefer if (pre_exec) |value| self.allocator.free(value);
        const on_unload = try self.optionalStringField(index, "on_unload");
        errdefer if (on_unload) |value| self.allocator.free(value);

        var capabilities = try self.readCapabilities(index, strict);
        errdefer capabilities.deinit(self.allocator);

        const description = try self.optionalStringField(index, "description");
        errdefer if (description) |value| self.allocator.free(value);
        const author = try self.optionalStringField(index, "author");
        errdefer if (author) |value| self.allocator.free(value);
        const homepage = try self.optionalStringField(index, "homepage");
        errdefer if (homepage) |value| self.allocator.free(value);
        const repository = try self.optionalStringField(index, "repository");
        errdefer if (repository) |value| self.allocator.free(value);

        return buildOwnedManifest(.{
            .allocator = self.allocator,
            .name = name,
            .version = version,
            .api_version = api_version,
            .license = license,
            .modules = modules,
            .capabilities = capabilities,
            .on_load = on_load,
            .render = render,
            .update = update,
            .pre_exec = pre_exec,
            .on_unload = on_unload,
            .description = description,
            .author = author,
            .homepage = homepage,
            .repository = repository,
        });
    }

    fn readCapabilities(self: *Runtime, index: CInt, strict: bool) !OwnedCapabilities {
        try self.pushField(index, "capabilities");
        defer self.pop(1);
        if (self.api.lua_type(self.state, -1) == lua_tnil) return .{};
        if (self.api.lua_type(self.state, -1) != lua_ttable) return error.InvalidManifestCapabilities;
        const cap_index = self.api.lua_gettop(self.state);
        if (strict) try self.rejectUnknownFields(cap_index, &capability_fields);
        return .{
            .fs_read = try self.optionalStringListField(cap_index, "fs_read") orelse &.{},
            .fs_watch = try self.optionalStringListField(cap_index, "fs_watch") orelse &.{},
            .exec_allow = try self.optionalListCapabilityField(cap_index, "exec"),
            .net_allow = try self.optionalListCapabilityField(cap_index, "net"),
            .secrets = try self.optionalBoolField(cap_index, "secrets") orelse false,
            .env_read = try self.optionalStringListField(cap_index, "env_read") orelse &.{},
            .pre_exec = try self.optionalBoolField(cap_index, "pre_exec") orelse false,
        };
    }

    fn requiredStringField(self: *Runtime, index: CInt, key: []const u8) ![]u8 {
        return (try self.optionalStringField(index, key)) orelse error.MissingManifestField;
    }

    fn optionalStringField(self: *Runtime, index: CInt, key: []const u8) !?[]u8 {
        try self.pushField(index, key);
        defer self.pop(1);
        const value_type = self.api.lua_type(self.state, -1);
        if (value_type == lua_tnil) return null;
        if (value_type != lua_tstring) return error.InvalidManifestField;
        return try self.stringAt(-1);
    }

    fn requiredApiVersion(self: *Runtime, index: CInt) !u32 {
        try self.pushField(index, "api_version");
        defer self.pop(1);
        const value_type = self.api.lua_type(self.state, -1);
        if (value_type == lua_tnumber) return @intFromFloat(self.api.lua_tonumber(self.state, -1));
        if (value_type == lua_tstring) {
            const value = try self.stringAt(-1);
            defer self.allocator.free(value);
            return std.fmt.parseInt(u32, value, 10) catch error.InvalidManifestField;
        }
        return error.InvalidManifestField;
    }

    fn requiredStringListField(self: *Runtime, index: CInt, key: []const u8) ![][]u8 {
        return (try self.optionalStringListField(index, key)) orelse error.MissingManifestField;
    }

    fn optionalStringListField(self: *Runtime, index: CInt, key: []const u8) !?[][]u8 {
        try self.pushField(index, key);
        defer self.pop(1);
        const value_type = self.api.lua_type(self.state, -1);
        if (value_type == lua_tnil) return null;
        if (value_type != lua_ttable) return error.InvalidManifestField;
        return try self.stringListAt(-1);
    }

    fn optionalBoolField(self: *Runtime, index: CInt, key: []const u8) !?bool {
        try self.pushField(index, key);
        defer self.pop(1);
        const value_type = self.api.lua_type(self.state, -1);
        if (value_type == lua_tnil) return null;
        if (value_type != lua_tboolean) return error.InvalidManifestField;
        return self.api.lua_toboolean(self.state, -1) != 0;
    }

    fn optionalListCapabilityField(self: *Runtime, index: CInt, key: []const u8) !?[][]u8 {
        try self.pushField(index, key);
        defer self.pop(1);
        const value_type = self.api.lua_type(self.state, -1);
        if (value_type == lua_tnil) return null;
        if (value_type == lua_tboolean and self.api.lua_toboolean(self.state, -1) == 0) return null;
        if (value_type != lua_ttable) return error.InvalidManifestField;
        return try self.stringListAt(-1);
    }

    fn stringListAt(self: *Runtime, index: CInt) ![][]u8 {
        const len = self.api.lua_objlen(self.state, index);
        var items = try self.allocator.alloc([]u8, len);
        errdefer self.allocator.free(items);
        var initialized: usize = 0;
        errdefer {
            for (items[0..initialized]) |item| self.allocator.free(item);
        }
        for (items, 0..) |*slot, zero_index| {
            self.api.lua_rawgeti(self.state, index, @intCast(zero_index + 1));
            defer self.pop(1);
            if (self.api.lua_type(self.state, -1) != lua_tstring) return error.InvalidManifestField;
            slot.* = try self.stringAt(-1);
            initialized += 1;
        }
        return items;
    }

    fn stringAt(self: *Runtime, index: CInt) ![]u8 {
        var len: usize = 0;
        const ptr = self.api.lua_tolstring(self.state, index, &len) orelse return error.InvalidManifestField;
        return self.allocator.dupe(u8, ptr[0..len]);
    }

    fn pushField(self: *Runtime, index: CInt, key: []const u8) !void {
        const key_z = try self.allocator.dupeZ(u8, key);
        defer self.allocator.free(key_z);
        self.api.lua_getfield(self.state, index, key_z.ptr);
    }

    fn rejectUnknownFields(self: *Runtime, index: CInt, known: []const []const u8) !void {
        self.api.lua_pushnil(self.state);
        while (self.api.lua_next(self.state, index) != 0) {
            if (self.api.lua_type(self.state, -2) != lua_tstring) return error.UnknownManifestField;
            const key = try self.stringAt(-2);
            defer self.allocator.free(key);
            if (!stringListContains(known, key)) return error.UnknownManifestField;
            self.pop(1);
        }
    }

    fn pop(self: *Runtime, count: CInt) void {
        self.api.lua_settop(self.state, -count - 1);
    }

    fn clearStack(self: *Runtime) void {
        self.api.lua_settop(self.state, 0);
    }
};

const top_level_manifest_fields = [_][]const u8{
    "name",
    "version",
    "api_version",
    "license",
    "capabilities",
    "modules",
    "on_load",
    "render",
    "update",
    "pre_exec",
    "on_unload",
    "description",
    "author",
    "homepage",
    "repository",
};

const capability_fields = [_][]const u8{
    "fs_read",
    "fs_watch",
    "exec",
    "net",
    "secrets",
    "env_read",
    "pre_exec",
};

const OwnedCapabilities = struct {
    fs_read: [][]u8 = &.{},
    fs_watch: [][]u8 = &.{},
    exec_allow: ?[][]u8 = null,
    net_allow: ?[][]u8 = null,
    secrets: bool = false,
    env_read: [][]u8 = &.{},
    pre_exec: bool = false,

    fn deinit(self: *OwnedCapabilities, allocator: std.mem.Allocator) void {
        freeStringList(allocator, self.fs_read);
        freeStringList(allocator, self.fs_watch);
        if (self.exec_allow) |items| freeStringList(allocator, items);
        if (self.net_allow) |items| freeStringList(allocator, items);
        freeStringList(allocator, self.env_read);
        self.* = undefined;
    }
};

const BuildOwnedManifestArgs = struct {
    allocator: std.mem.Allocator,
    name: []u8,
    version: []u8,
    api_version: u32,
    license: []u8,
    modules: [][]u8,
    capabilities: OwnedCapabilities,
    on_load: ?[]u8,
    render: []u8,
    update: ?[]u8,
    pre_exec: ?[]u8,
    on_unload: ?[]u8,
    description: ?[]u8,
    author: ?[]u8,
    homepage: ?[]u8,
    repository: ?[]u8,
};

fn buildOwnedManifest(args: BuildOwnedManifestArgs) OwnedManifest {
    var owned = OwnedManifest{
        .manifest = undefined,
        .name = args.name,
        .version = args.version,
        .license = args.license,
        .modules = args.modules,
        .fs_read = args.capabilities.fs_read,
        .fs_watch = args.capabilities.fs_watch,
        .exec_allow = args.capabilities.exec_allow,
        .net_allow = args.capabilities.net_allow,
        .env_read = args.capabilities.env_read,
        .on_load = args.on_load,
        .render = args.render,
        .update = args.update,
        .pre_exec = args.pre_exec,
        .on_unload = args.on_unload,
        .description = args.description,
        .author = args.author,
        .homepage = args.homepage,
        .repository = args.repository,
    };
    owned.manifest = .{
        .name = owned.name,
        .version = owned.version,
        .api_version = args.api_version,
        .license = owned.license,
        .capabilities = .{
            .fs_read = owned.fs_read,
            .fs_watch = owned.fs_watch,
            .exec = if (owned.exec_allow) |items| .{ .allow = items } else .deny,
            .net = if (owned.net_allow) |items| .{ .allow = items } else .deny,
            .secrets = args.capabilities.secrets,
            .env_read = owned.env_read,
            .pre_exec = args.capabilities.pre_exec,
        },
        .modules = owned.modules,
        .entry_points = .{
            .on_load = owned.on_load,
            .render = owned.render,
            .update = owned.update,
            .pre_exec = owned.pre_exec,
            .on_unload = owned.on_unload,
        },
        .description = owned.description,
        .author = owned.author,
        .homepage = owned.homepage,
        .repository = owned.repository,
    };
    _ = args.allocator;
    return owned;
}

const LuaMemoryLimiter = struct {
    limit: usize,
    used: usize = 0,
    high_water: usize = 0,

    fn reserve(self: *LuaMemoryLimiter, bytes: usize) bool {
        if (bytes > self.limit -| self.used) return false;
        self.used += bytes;
        self.high_water = @max(self.high_water, self.used);
        return true;
    }

    fn release(self: *LuaMemoryLimiter, bytes: usize) void {
        self.used -|= bytes;
    }
};

const LuaExecutionBudget = struct {
    start_ns: i128,
    hard_limit_ns: u64,
    hit_hard_limit: bool = false,
};

threadlocal var active_lua_budget: ?*LuaExecutionBudget = null;
threadlocal var active_lua_api: ?*const Api = null;

const lua_first_upvalue_index = lua_globalsindex - 1;

fn luaHostCallback(state: ?*LuaState) callconv(.c) CInt {
    const api = active_lua_api orelse return 0;
    const raw_closure = api.lua_touserdata(state, lua_first_upvalue_index) orelse return 0;
    const closure: *HostClosure = @ptrCast(@alignCast(raw_closure));
    const runtime = closure.host.runtime orelse return 0;
    return closure.host.callback(runtime, closure.host.user_data, closure.method);
}

fn hostMethodName(method: HostMethod) []const u8 {
    return switch (method) {
        .fs_read => "_shisa_fs_read",
        .fs_watch => "_shisa_fs_watch",
        .env_get => "_shisa_env_get",
        .secret_get => "_shisa_secret_get",
        .exec_run => "_shisa_exec_run",
        .net_get => "_shisa_net_get",
        .cache_get => "_shisa_cache_get",
        .cache_set => "_shisa_cache_set",
    };
}

/// This function deliberately returns before the C shim calls `lua_error`.
/// Lua uses longjmp for errors; jumping across a Zig callback frame is not
/// supported, so the non-returning Lua API call must stay entirely in C.
pub export fn shisaLuaBudgetExceeded() callconv(.c) CInt {
    const budget = active_lua_budget orelse return 0;
    if (elapsedNsSince(budget.start_ns) <= budget.hard_limit_ns) return 0;
    budget.hit_hard_limit = true;
    return 1;
}

fn elapsedNsSince(start_ns: i128) u64 {
    const elapsed = std.time.nanoTimestamp() - start_ns;
    if (elapsed <= 0) return 0;
    return @intCast(@min(elapsed, std.math.maxInt(u64)));
}

fn luaMemoryAlloc(ud: ?*anyopaque, ptr: ?*anyopaque, osize: usize, nsize: usize) callconv(.c) ?*anyopaque {
    const limiter: *LuaMemoryLimiter = @ptrCast(@alignCast(ud.?));
    const old_size: usize = if (ptr == null) 0 else osize;
    if (nsize == 0) {
        if (ptr) |existing| {
            std.c.free(existing);
            limiter.release(old_size);
        }
        return null;
    }

    if (nsize > old_size and !limiter.reserve(nsize - old_size)) return null;
    const resized = if (ptr) |existing| std.c.realloc(existing, nsize) else std.c.malloc(nsize);
    if (resized == null) {
        if (nsize > old_size) limiter.release(nsize - old_size);
        return null;
    }
    if (nsize < old_size) limiter.release(old_size - nsize);
    return resized;
}

fn freeStringList(allocator: std.mem.Allocator, items: [][]u8) void {
    if (items.len == 0) return;
    for (items) |item| allocator.free(item);
    allocator.free(items);
}

fn stringListContains(items: []const []const u8, value: []const u8) bool {
    for (items) |item| {
        if (std.mem.eql(u8, item, value)) return true;
    }
    return false;
}

fn removedGlobalsSnapshotAlloc(allocator: std.mem.Allocator, keep_require: bool) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    errdefer out.deinit(allocator);
    for (always_removed_globals) |name| {
        try out.appendSlice(allocator, name);
        try out.append(allocator, '\n');
    }
    if (!keep_require) try out.appendSlice(allocator, "require\n");
    return out.toOwnedSlice(allocator);
}

fn openSelectedVm() !std.DynLib {
    return switch (selected_vm) {
        .luajit => openLuaJit(),
    };
}

fn openLuaJit() !std.DynLib {
    const candidates = [_][]const u8{
        "/opt/homebrew/lib/libluajit-5.1.dylib",
        "/opt/homebrew/lib/libluajit.dylib",
        "/usr/local/lib/libluajit-5.1.dylib",
        "/usr/local/lib/libluajit.dylib",
        "libluajit-5.1.dylib",
        "libluajit.dylib",
        "libluajit-5.1.so",
        "libluajit-5.1.so.2",
    };
    for (candidates) |name| {
        return std.DynLib.open(name) catch continue;
    }
    return error.LuaUnavailable;
}

fn loadApi(lib: *std.DynLib) !Api {
    return .{
        .lua_newstate = lib.lookup(LuaNewState, "lua_newstate") orelse return error.LuaSymbolMissing,
        .lua_close = lib.lookup(LuaClose, "lua_close") orelse return error.LuaSymbolMissing,
        .luaL_openlibs = lib.lookup(LuaLOpenLibs, "luaL_openlibs") orelse return error.LuaSymbolMissing,
        .luaL_loadbuffer = lib.lookup(LuaLLoadBuffer, "luaL_loadbuffer") orelse return error.LuaSymbolMissing,
        .lua_pcall = lib.lookup(LuaPCall, "lua_pcall") orelse return error.LuaSymbolMissing,
        .lua_getfield = lib.lookup(LuaGetField, "lua_getfield") orelse return error.LuaSymbolMissing,
        .lua_setfield = lib.lookup(LuaSetField, "lua_setfield") orelse return error.LuaSymbolMissing,
        .lua_pushnil = lib.lookup(LuaPushNil, "lua_pushnil") orelse return error.LuaSymbolMissing,
        .lua_toboolean = lib.lookup(LuaToBoolean, "lua_toboolean") orelse return error.LuaSymbolMissing,
        .lua_tonumber = lib.lookup(LuaToNumber, "lua_tonumber") orelse return error.LuaSymbolMissing,
        .lua_tolstring = lib.lookup(LuaToLString, "lua_tolstring") orelse return error.LuaSymbolMissing,
        .lua_objlen = lib.lookup(LuaObjLen, "lua_objlen") orelse return error.LuaSymbolMissing,
        .lua_rawgeti = lib.lookup(LuaRawGetI, "lua_rawgeti") orelse return error.LuaSymbolMissing,
        .lua_type = lib.lookup(LuaType, "lua_type") orelse return error.LuaSymbolMissing,
        .lua_gettop = lib.lookup(LuaGetTop, "lua_gettop") orelse return error.LuaSymbolMissing,
        .lua_next = lib.lookup(LuaNext, "lua_next") orelse return error.LuaSymbolMissing,
        .lua_settop = lib.lookup(LuaSetTop, "lua_settop") orelse return error.LuaSymbolMissing,
        .lua_sethook = lib.lookup(LuaSetHook, "lua_sethook") orelse return error.LuaSymbolMissing,
        .lua_pushstring = lib.lookup(LuaPushString, "lua_pushstring") orelse return error.LuaSymbolMissing,
        .lua_pushlstring = lib.lookup(LuaPushLString, "lua_pushlstring") orelse return error.LuaSymbolMissing,
        .lua_pushboolean = lib.lookup(LuaPushBoolean, "lua_pushboolean") orelse return error.LuaSymbolMissing,
        .lua_pushlightuserdata = lib.lookup(LuaPushLightUserData, "lua_pushlightuserdata") orelse return error.LuaSymbolMissing,
        .lua_pushcclosure = lib.lookup(LuaPushCClosure, "lua_pushcclosure") orelse return error.LuaSymbolMissing,
        .lua_touserdata = lib.lookup(LuaToUserData, "lua_touserdata") orelse return error.LuaSymbolMissing,
        .lua_error = lib.lookup(LuaError, "lua_error") orelse return error.LuaSymbolMissing,
    };
}

test "loads luajit and runs code" {
    var runtime = Runtime.init(std.testing.allocator) catch |err| switch (err) {
        error.LuaUnavailable => return error.SkipZigTest,
        else => return err,
    };
    defer runtime.deinit();

    try runtime.doString("shisa_test_value = 40 + 2");
    try std.testing.expect(!(try runtime.globalIsNil("shisa_test_value")));
}

const HostBridgeTestState = struct {
    called: bool = false,
};

fn hostBridgeTestCallback(runtime: *Runtime, user_data: ?*anyopaque, method: HostMethod) callconv(.c) CInt {
    const raw_state = user_data orelse return 0;
    const state: *HostBridgeTestState = @ptrCast(@alignCast(raw_state));
    if (method != .cache_get) return 0;
    const key = runtime.hostArgumentString(1) orelse return 0;
    if (!std.mem.eql(u8, key, "key")) return 0;
    state.called = true;
    runtime.hostPushString("value");
    return 1;
}

test "sandboxed hooks can call installed host APIs" {
    var runtime = Runtime.initSandboxed(std.testing.allocator) catch |err| switch (err) {
        error.LuaUnavailable => return error.SkipZigTest,
        else => return err,
    };
    defer runtime.deinit();
    var state = HostBridgeTestState{};
    var host = HostApi{ .callback = hostBridgeTestCallback, .user_data = @ptrCast(&state) };
    try runtime.installHostApi(&host);
    try runtime.doString("function render(ctx) return ctx.cache.get('key') end");
    const rendered = try runtime.callGlobalStringAlloc("render", "{ cache = { get = _shisa_cache_get } }");
    defer if (rendered) |value| std.testing.allocator.free(value);
    try std.testing.expect(state.called);
    try std.testing.expectEqualStrings("value", rendered.?);
}

test "selected plugin Lua VM is LuaJIT" {
    try std.testing.expectEqual(Vm.luajit, selected_vm);
}

test "lua memory limiter enforces hard cap" {
    var limiter = LuaMemoryLimiter{ .limit = 16 };

    try std.testing.expect(limiter.reserve(8));
    try std.testing.expectEqual(@as(usize, 8), limiter.used);
    try std.testing.expect(!limiter.reserve(9));
    try std.testing.expectEqual(@as(usize, 8), limiter.used);
    limiter.release(4);
    try std.testing.expect(limiter.reserve(8));
    try std.testing.expectEqual(@as(usize, 12), limiter.used);
    try std.testing.expectEqual(@as(usize, 12), limiter.high_water);
}

test "runtime enforces configured lua memory limit" {
    var runtime = Runtime.initWithOptions(std.testing.allocator, .{
        .memory_limit_bytes = 1024 * 1024,
        .cpu_budget_ns = std.math.maxInt(u64),
        .cpu_hard_limit_ns = std.math.maxInt(u64),
    }) catch |err| switch (err) {
        error.LuaUnavailable => return error.SkipZigTest,
        else => return err,
    };
    defer runtime.deinit();

    try std.testing.expectError(error.LuaRuntimeError, runtime.doString(
        \\local held = {}
        \\for i = 1, 4096 do
        \\  held[i] = tostring(i) .. string.rep("x", 1024)
        \\end
    ));
    try std.testing.expect(runtime.memory_limiter.high_water <= runtime.memory_limiter.limit);
}

test "runtime reports lua cpu budget overrun" {
    var runtime = Runtime.initWithOptions(std.testing.allocator, .{ .cpu_budget_ns = 1 }) catch |err| switch (err) {
        error.LuaUnavailable => return error.SkipZigTest,
        else => return err,
    };
    defer runtime.deinit();

    try std.testing.expectError(error.LuaCpuBudgetExceeded, runtime.doString("local x = 0; for i = 1, 100000 do x = x + i end"));
}

test "runtime hard-stops runaway lua" {
    var runtime = Runtime.initWithOptions(std.testing.allocator, .{
        .cpu_budget_ns = 0,
        .cpu_hard_limit_ns = std.time.ns_per_ms,
    }) catch |err| switch (err) {
        error.LuaUnavailable => return error.SkipZigTest,
        else => return err,
    };
    defer runtime.deinit();

    try std.testing.expectError(error.LuaCpuBudgetExceeded, runtime.doString("while true do end"));
    try std.testing.expect(runtime.last_cpu_elapsed_ns > 0);
}

test "sandbox strips dangerous globals" {
    var runtime = Runtime.initSandboxed(std.testing.allocator) catch |err| switch (err) {
        error.LuaUnavailable => return error.SkipZigTest,
        else => return err,
    };
    defer runtime.deinit();

    const expected = try std.fs.cwd().readFileAlloc(std.testing.allocator, "test/snapshots/lua-sandbox/removed-globals.txt", 4096);
    defer std.testing.allocator.free(expected);
    const actual = try removedGlobalsSnapshotAlloc(std.testing.allocator, false);
    defer std.testing.allocator.free(actual);
    try std.testing.expectEqualStrings(expected, actual);

    var lines = std.mem.tokenizeScalar(u8, actual, '\n');
    while (lines.next()) |name| try std.testing.expect(try runtime.globalIsNil(name));

    try std.testing.expectError(error.LuaRuntimeError, runtime.doString("return require('x')"));
    try runtime.doString("shisa_safe_value = tostring(42)");
    try std.testing.expect(!(try runtime.globalIsNil("shisa_safe_value")));
}

test "sandbox require is limited to plugin root" {
    const allocator = std.testing.allocator;
    var runtime_probe = Runtime.initSandboxed(allocator) catch |err| switch (err) {
        error.LuaUnavailable => return error.SkipZigTest,
        else => return err,
    };
    runtime_probe.deinit();

    const dir_path = try std.fmt.allocPrint(allocator, "/tmp/shisa-lua-require-{x}", .{std.crypto.random.int(u64)});
    defer allocator.free(dir_path);
    defer std.fs.cwd().deleteTree(dir_path) catch {};
    try std.fs.cwd().makePath(dir_path);
    const helper_path = try std.fmt.allocPrint(allocator, "{s}/helper.lua", .{dir_path});
    defer allocator.free(helper_path);
    try std.fs.cwd().writeFile(.{ .sub_path = helper_path, .data = "return { value = 42 }\n" });

    var runtime = try Runtime.initSandboxedWithOptions(allocator, .{ .require_root = dir_path });
    defer runtime.deinit();

    try runtime.doString("local helper = require('helper'); shisa_require_value = tostring(helper.value)");
    try std.testing.expect(!(try runtime.globalIsNil("shisa_require_value")));
    try std.testing.expect(try runtime.globalIsNil("package"));
    try std.testing.expectError(error.LuaRuntimeError, runtime.doString("return require('../outside')"));
}

test "loads plugin manifest table" {
    var runtime = Runtime.initSandboxed(std.testing.allocator) catch |err| switch (err) {
        error.LuaUnavailable => return error.SkipZigTest,
        else => return err,
    };
    defer runtime.deinit();

    var loaded = try runtime.loadManifest(
        \\return {
        \\  name = "kubectl-context",
        \\  version = "0.2.1",
        \\  api_version = "1",
        \\  license = "MIT",
        \\  capabilities = {
        \\    fs_read = { "~/.kube/config" },
        \\    fs_watch = { "~/.kube/config" },
        \\    exec = { "kubectl" },
        \\    net = false,
        \\    secrets = false,
        \\    env_read = { "KUBECONFIG" },
        \\    pre_exec = true,
        \\  },
        \\  modules = { "k8s_ctx" },
        \\  on_load = "on_load",
        \\  render = "render",
        \\  update = "update",
        \\  pre_exec = "pre_exec",
        \\  on_unload = "on_unload",
        \\}
    );
    defer loaded.deinit(std.testing.allocator);

    try std.testing.expectEqualStrings("kubectl-context", loaded.manifest.name);
    try std.testing.expectEqualStrings("0.2.1", loaded.manifest.version);
    try std.testing.expectEqual(@as(u32, 1), loaded.manifest.api_version);
    try std.testing.expectEqualStrings("MIT", loaded.manifest.license);
    try std.testing.expectEqualStrings("k8s_ctx", loaded.manifest.modules[0]);
    try std.testing.expectEqualStrings("~/.kube/config", loaded.manifest.capabilities.fs_read[0]);
    try std.testing.expectEqualStrings("kubectl", loaded.exec_allow.?[0]);
    try std.testing.expectEqual(manifest_schema.ListCapability.deny, loaded.manifest.capabilities.net);
    try std.testing.expect(loaded.manifest.capabilities.pre_exec);
    try std.testing.expectEqualStrings("on_load", loaded.manifest.entry_points.on_load.?);
    try std.testing.expectEqualStrings("render", loaded.manifest.entry_points.render);
    try std.testing.expectEqualStrings("update", loaded.manifest.entry_points.update.?);
    try std.testing.expectEqualStrings("pre_exec", loaded.manifest.entry_points.pre_exec.?);
    try std.testing.expectEqualStrings("on_unload", loaded.manifest.entry_points.on_unload.?);
}

test "loads minimal plugin manifest table" {
    var runtime = Runtime.initSandboxed(std.testing.allocator) catch |err| switch (err) {
        error.LuaUnavailable => return error.SkipZigTest,
        else => return err,
    };
    defer runtime.deinit();

    var loaded = try runtime.loadManifest(
        \\return {
        \\  name = "minimal",
        \\  version = "0.1.0",
        \\  api_version = 1,
        \\  license = "MIT",
        \\  modules = { "mini" },
        \\}
    );
    defer loaded.deinit(std.testing.allocator);

    try std.testing.expectEqualStrings("render", loaded.manifest.entry_points.render);
    try std.testing.expect(loaded.manifest.entry_points.on_load == null);
    try std.testing.expectEqual(manifest_schema.ListCapability.deny, loaded.manifest.capabilities.exec);
    try std.testing.expect(loaded.manifest.entry_points.update == null);
    try std.testing.expect(loaded.manifest.entry_points.pre_exec == null);
    try std.testing.expect(loaded.manifest.entry_points.on_unload == null);
    try std.testing.expectEqual(@as(usize, 0), loaded.manifest.capabilities.fs_read.len);
}

test "strict manifest stores each lifecycle hook" {
    var runtime = Runtime.initSandboxed(std.testing.allocator) catch |err| switch (err) {
        error.LuaUnavailable => return error.SkipZigTest,
        else => return err,
    };
    defer runtime.deinit();

    var loaded = try runtime.loadManifestStrict(
        \\return {
        \\  name = "lifecycle",
        \\  version = "0.1.0",
        \\  api_version = 1,
        \\  license = "MIT",
        \\  capabilities = {
        \\    pre_exec = true,
        \\  },
        \\  modules = { "life" },
        \\  on_load = "load_hook",
        \\  render = "render_hook",
        \\  update = "update_hook",
        \\  pre_exec = "pre_exec_hook",
        \\  on_unload = "unload_hook",
        \\}
    );
    defer loaded.deinit(std.testing.allocator);

    try std.testing.expectEqualStrings("load_hook", loaded.manifest.entry_points.on_load.?);
    try std.testing.expectEqualStrings("render_hook", loaded.manifest.entry_points.render);
    try std.testing.expectEqualStrings("update_hook", loaded.manifest.entry_points.update.?);
    try std.testing.expectEqualStrings("pre_exec_hook", loaded.manifest.entry_points.pre_exec.?);
    try std.testing.expectEqualStrings("unload_hook", loaded.manifest.entry_points.on_unload.?);
}

test "strict manifest rejects unknown fields" {
    var runtime = Runtime.initSandboxed(std.testing.allocator) catch |err| switch (err) {
        error.LuaUnavailable => return error.SkipZigTest,
        else => return err,
    };
    defer runtime.deinit();

    try std.testing.expectError(error.UnknownManifestField, runtime.loadManifestStrict(
        \\return {
        \\  name = "strict",
        \\  version = "0.1.0",
        \\  api_version = 1,
        \\  license = "MIT",
        \\  modules = { "strict" },
        \\  surprise = true,
        \\}
    ));
    try std.testing.expectError(error.UnknownManifestField, runtime.loadManifestStrict(
        \\return {
        \\  name = "strict",
        \\  version = "0.1.0",
        \\  api_version = 1,
        \\  license = "MIT",
        \\  capabilities = { mystery = true },
        \\  modules = { "strict" },
        \\}
    ));
}

test "rejects invalid plugin manifest table" {
    var runtime = Runtime.initSandboxed(std.testing.allocator) catch |err| switch (err) {
        error.LuaUnavailable => return error.SkipZigTest,
        else => return err,
    };
    defer runtime.deinit();

    try std.testing.expectError(error.InvalidName, runtime.loadManifest(
        \\return {
        \\  name = "Bad",
        \\  version = "0.1.0",
        \\  api_version = 1,
        \\  license = "MIT",
        \\  modules = { "ok" },
        \\}
    ));
}

test "fuzz lua manifest bridge invariants" {
    return std.testing.fuzz({}, fuzzLuaManifest, .{
        .corpus = &.{
            "",
            "\x00\xffnot lua",
            "ok",
            "bad-name",
            "demo_plugin",
        },
    });
}

fn fuzzLuaManifest(_: void, input: []const u8) !void {
    if (input.len > 1024) return;
    const quoted = try luaQuoteAlloc(std.testing.allocator, input);
    defer std.testing.allocator.free(quoted);
    const source = try std.fmt.allocPrint(
        std.testing.allocator,
        "return {{ name = {s}, version = '0.1.0', api_version = 1, license = 'MIT', modules = {{ {s} }} }}",
        .{ quoted, quoted },
    );
    defer std.testing.allocator.free(source);

    var runtime = Runtime.initSandboxed(std.testing.allocator) catch |err| switch (err) {
        error.LuaUnavailable => return,
        else => return err,
    };
    defer runtime.deinit();

    var loaded = runtime.loadManifest(source) catch return;
    defer loaded.deinit(std.testing.allocator);
    try loaded.manifest.validate();
}

fn luaQuoteAlloc(allocator: std.mem.Allocator, input: []const u8) ![]u8 {
    var out: std.ArrayList(u8) = .empty;
    defer out.deinit(allocator);
    try out.append(allocator, '\'');
    for (input) |byte| {
        if (byte == '\\') {
            try out.appendSlice(allocator, "\\\\");
        } else if (byte == '\'') {
            try out.appendSlice(allocator, "\\'");
        } else if (byte >= 32 and byte <= 126) {
            try out.append(allocator, byte);
        } else {
            try std.fmt.format(out.writer(allocator), "\\{d:0>3}", .{byte});
        }
    }
    try out.append(allocator, '\'');
    return out.toOwnedSlice(allocator);
}
