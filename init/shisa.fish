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
set -gx SHISA_HOOK_ACTIVE 1

function shisa_config_dir
    if set -q XDG_CONFIG_HOME; and test -n "$XDG_CONFIG_HOME"
        printf '%s' "$XDG_CONFIG_HOME/shisa"
    else
        printf '%s' "$HOME/.config/shisa"
    end
end

function shisa_shell_env_unquote
    set -l value "$argv[1]"
    set -l len (string length -- "$value")
    if test "$len" -ge 2
        set -l first (string sub -s 1 -l 1 -- "$value")
        set -l last (string sub -s "$len" -l 1 -- "$value")
        if test "$first" = "'"; and test "$last" = "'"
            set -l inner_len (math "$len - 2")
            if test "$inner_len" -gt 0
                set value (string sub -s 2 -l "$inner_len" -- "$value")
                set value (string replace -a "'\\''" "'" -- "$value")
            else
                set value ""
            end
        end
    end
    printf '%s' "$value"
end

function shisa_load_shell_prefs
    set -l path (shisa_config_dir)/shell.env
    test -r "$path"; or return 0
    while read -l line
        test -n "$line"; or continue
        string match -qr '^#' -- "$line"; and continue
        string match -q '*=*' -- "$line"; or continue
        set -l parts (string split -m1 = -- "$line")
        set -l key $parts[1]
        set -l value (shisa_shell_env_unquote "$parts[2]")
        switch "$key"
            case SHISA_ASYNC_FILL SHISA_CMD_COMPLETE_BELL SHISA_CMD_COMPLETE_BELL_MODE SHISA_CMD_COMPLETE_BELL_THRESHOLD_MS SHISA_CMD_COMPLETE_BELL_MESSAGE
                set -g $key "$value"
        end
    end <"$path"
end

shisa_load_shell_prefs

set -q SHISA_PROD_GUARD; or set -g SHISA_PROD_GUARD 0
set -q SHISA_PROD_GUARD_FORCE; or set -g SHISA_PROD_GUARD_FORCE 0
set -q SHISA_A11Y; or set -g SHISA_A11Y 0
set -q SHISA_ASYNC_FILL; or set -g SHISA_ASYNC_FILL 1
set -q SHISA_CMD_COMPLETE_BELL; or set -g SHISA_CMD_COMPLETE_BELL 0
set -q SHISA_CMD_COMPLETE_BELL_MODE; or set -g SHISA_CMD_COMPLETE_BELL_MODE bell
set -q SHISA_CMD_COMPLETE_BELL_THRESHOLD_MS; or set -g SHISA_CMD_COMPLETE_BELL_THRESHOLD_MS 10000
set -q SHISA_CMD_COMPLETE_BELL_MESSAGE; or set -g SHISA_CMD_COMPLETE_BELL_MESSAGE "shisa: command complete"
set -q SHISA_LONG_RUNNING; or set -g SHISA_LONG_RUNNING 0
set -q SHISA_LONG_RUNNING_THRESHOLD_SECONDS; or set -g SHISA_LONG_RUNNING_THRESHOLD_SECONDS 30
set -q SHISA_LONG_RUNNING_MESSAGE; or set -g SHISA_LONG_RUNNING_MESSAGE "shisa: command still running"
set -g SHISA_LONG_RUNNING_PID ""

function shisa_detect_rtl_locale
    set -l locale ""
    if set -q LC_ALL; and test -n "$LC_ALL"
        set locale "$LC_ALL"
    else if set -q LC_CTYPE; and test -n "$LC_CTYPE"
        set locale "$LC_CTYPE"
    else if set -q LANG
        set locale "$LANG"
    end
    set locale (string lower -- "$locale")
    set locale (string split -m1 . -- "$locale")[1]
    set locale (string split -m1 @ -- "$locale")[1]
    set locale (string split -m1 _ -- "$locale")[1]
    set locale (string split -m1 - -- "$locale")[1]
    switch "$locale"
        case ar he fa ur ps dv yi
            printf '1'
        case '*'
            printf '0'
    end
end

set -q SHISA_RTL; or set -g SHISA_RTL (shisa_detect_rtl_locale)
set -q SHISA_LAST_COMMAND; or set -g SHISA_LAST_COMMAND ""
set -q SHISA_LAST_STATUS; or set -g SHISA_LAST_STATUS 0
set -q SHISA_LAST_JOBS; or set -g SHISA_LAST_JOBS 0
set -q SHISA_LAST_DURATION_MS; or set -g SHISA_LAST_DURATION_MS 0

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
    set -g SHISA_LAST_STATUS $last_status
    set -g SHISA_LAST_JOBS $jobs_count
    set -g SHISA_LAST_DURATION_MS $duration_ms
    shisa_long_running_stop
    shisa_cmd_complete_bell $duration_ms

    set -l args prompt --shell fish --cwd "$PWD" --exit "$last_status" --jobs "$jobs_count" --duration-ms "$duration_ms" --socket "$socket_path"
    if test "$SHISA_INSTANT" = 1
        set args $args --instant
    else if not test -S "$socket_path"
        shisa_prompt_fallback
        return 0
    end
    if test "$SHISA_A11Y" = 1
        set args $args --a11y
    end
    if test "$SHISA_ASYNC_FILL" = 0
        set args $args --no-async
    end
    if test "$SHISA_RTL" = 1
        set args $args --rtl
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

function shisa_right_prompt_render
    set -l socket_path (shisa_socket_path)
    test -S "$socket_path"; or return 0
    set -l args prompt --right --shell fish --cwd "$PWD" --exit "$SHISA_LAST_STATUS" --jobs "$SHISA_LAST_JOBS" --duration-ms "$SHISA_LAST_DURATION_MS" --socket "$socket_path"
    if test "$SHISA_ASYNC_FILL" = 0
        set args $args --no-async
    end
    if test "$SHISA_RTL" = 1
        set args $args --rtl
    end
    command "$SHISA_BIN" $args 2>/dev/null
    or true
end

function fish_right_prompt
    shisa_right_prompt_render
end

function shisa_preexec_guard --on-event fish_preexec
    set -g SHISA_LAST_COMMAND (string join ' ' -- $argv)
    if test "$SHISA_PROD_GUARD" = 1
        set -l command "$SHISA_LAST_COMMAND"
        test -n "$command"; or return 0
        set -l socket_path (shisa_socket_path)
        set -l args cloud preexec --socket "$socket_path" --shell fish
        if test "$SHISA_PROD_GUARD_FORCE" = 1
            set args $args --force
        end
        command "$SHISA_BIN" $args -- "$command"; or return $status
    end
    shisa_long_running_start
end

function shisa_cmd_complete_bell
    test "$SHISA_CMD_COMPLETE_BELL" = 1; or return 0
    test -n "$SHISA_LAST_COMMAND"; or return 0
    set -l duration_ms $argv[1]
    string match -qr '^[0-9]+$' -- "$duration_ms"; or return 0
    string match -qr '^[0-9]+$' -- "$SHISA_CMD_COMPLETE_BELL_THRESHOLD_MS"; or return 0
    test $duration_ms -ge $SHISA_CMD_COMPLETE_BELL_THRESHOLD_MS; or return 0
    set -l message "$SHISA_CMD_COMPLETE_BELL_MESSAGE"
    switch "$SHISA_CMD_COMPLETE_BELL_MODE"
        case bell terminal
            printf '\a'
        case osc9
            printf '\e]9;%s\a' "$message"
        case notify notify-send
            type -q notify-send; and notify-send shisa "$message" >/dev/null 2>&1
        case macos osascript user-notification
            type -q osascript; and osascript -e 'on run argv' -e 'display notification (item 1 of argv) with title "shisa"' -e 'end run' "$message" >/dev/null 2>&1
    end
    return 0
end

function shisa_long_running_start
    shisa_long_running_stop
    test "$SHISA_LONG_RUNNING" = 1; or return 0
    string match -qr '^[0-9]+$' -- "$SHISA_LONG_RUNNING_THRESHOLD_SECONDS"; or return 0
    set -l message "$SHISA_LONG_RUNNING_MESSAGE"
    begin
        sleep "$SHISA_LONG_RUNNING_THRESHOLD_SECONDS"
        printf '\n%s\n' "$message"
    end &
    set -g SHISA_LONG_RUNNING_PID $last_pid
end

function shisa_long_running_stop
    if test -n "$SHISA_LONG_RUNNING_PID"
        kill "$SHISA_LONG_RUNNING_PID" >/dev/null 2>&1
        or true
        set -g SHISA_LONG_RUNNING_PID ""
    end
end

function shisa_long_running_cleanup --on-event fish_exit
    shisa_long_running_stop
end

function shisa_async_redraw --on-event shisa_async_redraw
    commandline -f repaint 2>/dev/null
    or true
end
