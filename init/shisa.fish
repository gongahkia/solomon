if not set -q FISH_VERSION
    return 0
end

if set -q __SHISA_FISH_INIT
    return 0
end

set -g __SHISA_FISH_INIT 1
set -q SHISA_BIN; or set -g SHISA_BIN shisa
set -q SHISA_SOCKET; or set -g SHISA_SOCKET ""
set -q SHISA_INSTANT; or set -g SHISA_INSTANT 1
set -q SHISA_PROD_GUARD; or set -g SHISA_PROD_GUARD 0

function shisa_socket_path
    if test -n "$SHISA_SOCKET"
        printf '%s' "$SHISA_SOCKET"
    else
        set -l os (uname 2>/dev/null)
        if test "$os" = Darwin
            printf '%s' "$HOME/Library/Caches/shisa/shisa.sock"
        else if test -n "$XDG_RUNTIME_DIR"
            printf '%s' "$XDG_RUNTIME_DIR/shisa.sock"
        else
            printf '%s' "/run/user/$UID/shisa.sock"
        end
    end
end

function shisa_prompt_fallback
    printf '%s> ' (prompt_pwd)
end

function shisa_prompt_render
    set -l last_status $status
    set -l socket_path (shisa_socket_path)
    set -l jobs_count (jobs -p 2>/dev/null | count)
    set -l duration_ms 0
    if set -q CMD_DURATION
        set duration_ms $CMD_DURATION
    end

    set -l args prompt --shell fish --cwd "$PWD" --exit "$last_status" --jobs "$jobs_count" --duration-ms "$duration_ms" --socket "$socket_path"
    if test "$SHISA_INSTANT" = 1
        set args $args --instant
    else if not test -S "$socket_path"
        shisa_prompt_fallback
        return 0
    end

    set -l rendered (command "$SHISA_BIN" $args 2>/dev/null)
    if test $status -eq 0
        printf '%s' "$rendered"
    else
        shisa_prompt_fallback
    end
end

function fish_prompt
    shisa_prompt_render
end

function shisa_preexec_guard --on-event fish_preexec
    test "$SHISA_PROD_GUARD" = 1; or return 0
    set -l command (string join ' ' -- $argv)
    test -n "$command"; or return 0
    set -l socket_path (shisa_socket_path)
    command "$SHISA_BIN" cloud preexec --socket "$socket_path" --shell fish -- "$command"
end

function shisa_async_redraw --on-event shisa_async_redraw
    commandline -f repaint 2>/dev/null
    or true
end
