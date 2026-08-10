typedef struct lua_State lua_State;
typedef struct lua_Debug lua_Debug;

typedef const char *(*shisa_lua_pushstring_fn)(lua_State *, const char *);
typedef int (*shisa_lua_error_fn)(lua_State *);
typedef int (*shisa_lua_budget_check_fn)(void);

static shisa_lua_pushstring_fn shisa_lua_pushstring;
static shisa_lua_error_fn shisa_lua_error;
static shisa_lua_budget_check_fn shisa_lua_budget_check;

void shisa_lua_install_budget_hook(
    shisa_lua_pushstring_fn pushstring,
    shisa_lua_error_fn lua_error,
    shisa_lua_budget_check_fn budget_check
) {
    shisa_lua_pushstring = pushstring;
    shisa_lua_error = lua_error;
    shisa_lua_budget_check = budget_check;
}

void shisa_lua_budget_hook(lua_State *state, lua_Debug *debug) {
    (void)debug;
    if (shisa_lua_budget_check == 0 || !shisa_lua_budget_check()) return;
    shisa_lua_pushstring(state, "shisa plugin cpu budget exceeded");
    shisa_lua_error(state);
}
