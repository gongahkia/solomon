const std = @import("std");

const LuaState = opaque {};
const CInt = c_int;

const lua_ok = 0;
const lua_tnil = 0;
const lua_globalsindex = -10002;

const LuaLNewState = *const fn () callconv(.c) ?*LuaState;
const LuaClose = *const fn (?*LuaState) callconv(.c) void;
const LuaLOpenLibs = *const fn (?*LuaState) callconv(.c) void;
const LuaLLoadString = *const fn (?*LuaState, [*:0]const u8) callconv(.c) CInt;
const LuaPCall = *const fn (?*LuaState, CInt, CInt, CInt) callconv(.c) CInt;
const LuaGetField = *const fn (?*LuaState, CInt, [*:0]const u8) callconv(.c) void;
const LuaType = *const fn (?*LuaState, CInt) callconv(.c) CInt;
const LuaSetTop = *const fn (?*LuaState, CInt) callconv(.c) void;

const Api = struct {
    luaL_newstate: LuaLNewState,
    lua_close: LuaClose,
    luaL_openlibs: LuaLOpenLibs,
    luaL_loadstring: LuaLLoadString,
    lua_pcall: LuaPCall,
    lua_getfield: LuaGetField,
    lua_type: LuaType,
    lua_settop: LuaSetTop,
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

    pub fn deinit(self: *Runtime) void {
        self.api.lua_close(self.state);
        self.lib.close();
        self.* = undefined;
    }

    pub fn doString(self: *Runtime, source: []const u8) !void {
        const code = try self.allocator.dupeZ(u8, source);
        defer self.allocator.free(code);
        if (self.api.luaL_loadstring(self.state, code.ptr) != lua_ok) {
            self.clearStack();
            return error.LuaLoadError;
        }
        if (self.api.lua_pcall(self.state, 0, 0, 0) != lua_ok) {
            self.clearStack();
            return error.LuaRuntimeError;
        }
        self.clearStack();
    }

    pub fn globalIsNil(self: *Runtime, name: []const u8) !bool {
        const global = try self.allocator.dupeZ(u8, name);
        defer self.allocator.free(global);
        self.api.lua_getfield(self.state, lua_globalsindex, global.ptr);
        const is_nil = self.api.lua_type(self.state, -1) == lua_tnil;
        self.clearStack();
        return is_nil;
    }

    fn clearStack(self: *Runtime) void {
        self.api.lua_settop(self.state, 0);
    }
};

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
        .luaL_loadstring = lib.lookup(LuaLLoadString, "luaL_loadstring") orelse return error.LuaSymbolMissing,
        .lua_pcall = lib.lookup(LuaPCall, "lua_pcall") orelse return error.LuaSymbolMissing,
        .lua_getfield = lib.lookup(LuaGetField, "lua_getfield") orelse return error.LuaSymbolMissing,
        .lua_type = lib.lookup(LuaType, "lua_type") orelse return error.LuaSymbolMissing,
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
