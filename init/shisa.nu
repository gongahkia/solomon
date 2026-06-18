if not ("__SHISA_NU_INIT" in $env) {
    $env.__SHISA_NU_INIT = "1"
    if not ("SHISA_BIN" in $env) { $env.SHISA_BIN = "shisa" }
    if not ("SHISA_SOCKET" in $env) { $env.SHISA_SOCKET = "" }
    if not ("SHISA_INSTANT" in $env) { $env.SHISA_INSTANT = "0" }
    if not ("SHISA_A11Y" in $env) { $env.SHISA_A11Y = "0" }

    def shisa-detect-rtl-locale [] {
        let locale = if (($env.LC_ALL? | default "") != "") {
            $env.LC_ALL
        } else if (($env.LC_CTYPE? | default "") != "") {
            $env.LC_CTYPE
        } else {
            $env.LANG? | default ""
        }
        let tag = ($locale | str downcase | split row "." | get 0 | split row "@" | get 0 | split row "_" | get 0 | split row "-" | get 0)
        if ($tag in [ar he fa ur ps dv yi]) { "1" } else { "0" }
    }

    if not ("SHISA_RTL" in $env) { $env.SHISA_RTL = (shisa-detect-rtl-locale) }

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
        let args = if (($env.SHISA_A11Y? | default "0") == "1") { $args | append "--a11y" } else { $args }
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
        let suggestion = ($rendered.stdout | str trim)
        if $rendered.exit_code == 0 and $suggestion != "" {
            $"shisa next: ($suggestion)"
        } else {
            ""
        }
    }

    def shisa-nextcmd-accept [] {
        let preview = (shisa-nextcmd | str trim)
        if ($preview | str starts-with "shisa next: ") {
            $preview | str replace "shisa next: " ""
        } else {
            ""
        }
    }

    def shisa-nextcmd-reject [] { "" }

    def shisa-nextcmd-next [] { shisa-nextcmd }

    def shisa-explain [command: string] {
        if (($env.SHISA_EXPLAIN_LAST_COMMAND? | default "") == $command) and (($env.SHISA_EXPLAIN_LAST_OUTPUT? | default "") != "") {
            return $env.SHISA_EXPLAIN_LAST_OUTPUT
        }
        let args = [ai explain --command $command]
        let rendered = (try { run-external $env.SHISA_BIN ...$args e> /dev/null | complete } catch { { stdout: "", exit_code: 1 } })
        if $rendered.exit_code == 0 {
            $env.SHISA_EXPLAIN_LAST_COMMAND = $command
            $env.SHISA_EXPLAIN_LAST_OUTPUT = $rendered.stdout
            $rendered.stdout
        } else {
            ""
        }
    }

    $env.config.hooks.pre_prompt = ($env.config.hooks.pre_prompt | append {||
        if (($env.SHISA_REPROMPT_REQUESTED? | default "0") == "1") {
            $env.SHISA_REPROMPT_REQUESTED = "0"
        }
    })

    $env.PROMPT_COMMAND = {|| shisa-prompt-render }
}

def --env shisa-reprompt [] {
    $env.SHISA_REPROMPT_REQUESTED = "1"
}
