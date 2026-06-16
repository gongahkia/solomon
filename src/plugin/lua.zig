const std = @import("std");
const manifest_schema = @import("manifest.zig");

const LuaState = opaque {};
const CInt = c_int;

const lua_ok = 0;
const lua_tnil = 0;
const lua_tboolean = 1;
const lua_tnumber = 3;
const lua_tstring = 4;
const lua_ttable = 5;
const lua_globalsindex = -10002;

const LuaLNewState = *const fn () callconv(.c) ?*LuaState;
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

const Api = struct {
    luaL_newstate: LuaLNewState,
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
    render: []u8,
    update: ?[]u8 = null,
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
        allocator.free(self.render);
        if (self.update) |value| allocator.free(value);
        if (self.description) |value| allocator.free(value);
        if (self.author) |value| allocator.free(value);
        if (self.homepage) |value| allocator.free(value);
        if (self.repository) |value| allocator.free(value);
        self.* = undefined;
    }
};

pub const Runtime = struct {
    allocator: std.mem.Allocator,
    lib: std.DynLib,
    api: Api,
    state: *LuaState,

    pub fn init(allocator: std.mem.Allocator) !Runtime {
        var lib = try openLuaJit();
        errdefer lib.close();
        const api = try loadApi(&lib);
        const state = api.luaL_newstate() orelse return error.LuaOutOfMemory;
        errdefer api.lua_close(state);
        api.luaL_openlibs(state);
        return .{
            .allocator = allocator,
            .lib = lib,
            .api = api,
            .state = state,
        };
    }

    pub fn initSandboxed(allocator: std.mem.Allocator) !Runtime {
        var runtime = try init(allocator);
        errdefer runtime.deinit();
        try runtime.stripDangerousGlobals();
        return runtime;
    }

    pub fn deinit(self: *Runtime) void {
        self.api.lua_close(self.state);
        self.lib.close();
        self.* = undefined;
    }

    pub fn doString(self: *Runtime, source: []const u8) !void {
        try self.loadBuffer(source, "shisa-string");
        if (self.api.lua_pcall(self.state, 0, 0, 0) != lua_ok) {
            self.clearStack();
            return error.LuaRuntimeError;
        }
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
        if (self.api.lua_pcall(self.state, 0, 1, 0) != lua_ok) {
            self.clearStack();
            return error.LuaRuntimeError;
        }
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

    fn stripDangerousGlobals(self: *Runtime) !void {
        const globals = [_][]const u8{
            "os",
            "io",
            "package",
            "require",
            "dofile",
            "loadfile",
        };
        for (globals) |name| try self.stripGlobal(name);
    }

    fn stripGlobal(self: *Runtime, name: []const u8) !void {
        const global = try self.allocator.dupeZ(u8, name);
        defer self.allocator.free(global);
        self.api.lua_pushnil(self.state);
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
        const render = try self.optionalStringField(index, "render") orelse try self.allocator.dupe(u8, "render");
        errdefer self.allocator.free(render);
        const update = try self.optionalStringField(index, "update");
        errdefer if (update) |value| self.allocator.free(value);

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
            .render = render,
            .update = update,
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
    "render",
    "update",
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
    render: []u8,
    update: ?[]u8,
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
        .render = args.render,
        .update = args.update,
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
            .render = owned.render,
            .update = owned.update,
        },
        .description = owned.description,
        .author = owned.author,
        .homepage = owned.homepage,
        .repository = owned.repository,
    };
    _ = args.allocator;
    return owned;
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
        .luaL_newstate = lib.lookup(LuaLNewState, "luaL_newstate") orelse return error.LuaSymbolMissing,
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

test "sandbox strips dangerous globals" {
    var runtime = Runtime.initSandboxed(std.testing.allocator) catch |err| switch (err) {
        error.LuaUnavailable => return error.SkipZigTest,
        else => return err,
    };
    defer runtime.deinit();

    try std.testing.expect(try runtime.globalIsNil("os"));
    try std.testing.expect(try runtime.globalIsNil("io"));
    try std.testing.expect(try runtime.globalIsNil("package"));
    try std.testing.expect(try runtime.globalIsNil("require"));
    try std.testing.expect(try runtime.globalIsNil("dofile"));
    try std.testing.expect(try runtime.globalIsNil("loadfile"));
    try std.testing.expectError(error.LuaRuntimeError, runtime.doString("return require('x')"));
    try runtime.doString("shisa_safe_value = tostring(42)");
    try std.testing.expect(!(try runtime.globalIsNil("shisa_safe_value")));
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
        \\  render = "render",
        \\  update = "update",
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
    try std.testing.expectEqualStrings("update", loaded.manifest.entry_points.update.?);
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
    try std.testing.expectEqual(manifest_schema.ListCapability.deny, loaded.manifest.capabilities.exec);
    try std.testing.expectEqual(@as(usize, 0), loaded.manifest.capabilities.fs_read.len);
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
