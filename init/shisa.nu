if not ("__SHISA_NU_INIT" in $env) {
    $env.__SHISA_NU_INIT = "1"
    if not ("SHISA_BIN" in $env) { $env.SHISA_BIN = "shisa" }
    if not ("SHISA_SOCKET" in $env) { $env.SHISA_SOCKET = "" }
    if not ("SHISA_INSTANT" in $env) { $env.SHISA_INSTANT = "0" }

    def shisa-socket-path [] {
        if (($env.SHISA_SOCKET? | default "") != "") {
            $env.SHISA_SOCKET
        } else if $nu.os-info.name == "macos" {
            $"($nu.home-dir)/Library/Caches/shisa/shisa.sock"
        } else if (($env.XDG_RUNTIME_DIR? | default "") != "") {
            $"($env.XDG_RUNTIME_DIR)/shisa.sock"
        } else {
            $"/run/user/(^id -u | str trim)/shisa.sock"
        }
    }

    def shisa-prompt-fallback [] {
        $"(pwd)> "
    }

    def shisa-prompt-render [] {
        let socket_path = (shisa-socket-path)
        let instant = (($env.SHISA_INSTANT? | default "0") == "1")
        if (not $instant) and (not ($socket_path | path exists)) {
            return (shisa-prompt-fallback)
        }

        let exit_code = ($env.LAST_EXIT_CODE? | default 0 | into int)
        let jobs_count = (job list | length)
        let args = [
            prompt
            --shell
            nu
            --cwd
            (pwd)
            --exit
            ($exit_code | into string)
            --jobs
            ($jobs_count | into string)
            --duration-ms
            "0"
            --socket
            $socket_path
        ]
        let args = if $instant { $args | append "--instant" } else { $args }
        let rendered = (try { run-external $env.SHISA_BIN ...$args e> /dev/null | complete } catch { { stdout: "", exit_code: 1 } })
        if $rendered.exit_code == 0 {
            $rendered.stdout
        } else {
            shisa-prompt-fallback
        }
    }

    def shisa-nextcmd [] {
        let last_exit = ($env.LAST_EXIT_CODE? | default 0 | into string)
        let args = [ai nextcmd --shell nu --cwd (pwd) --last-exit $last_exit]
        let rendered = (try { run-external $env.SHISA_BIN ...$args e> /dev/null | complete } catch { { stdout: "", exit_code: 1 } })
        if $rendered.exit_code == 0 { $rendered.stdout } else { "" }
    }

    $env.PROMPT_COMMAND = {|| shisa-prompt-render }
}
