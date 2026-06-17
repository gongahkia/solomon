# AI Hotkey Suggestion with a Local Model

Use the shell bindings for `shisa ai nextcmd` with a local Ollama model.

## 1. Start the local model server

Shisa detects Ollama with `ollama --version` and checks the local API at `127.0.0.1:11434`.

```sh
ollama serve
```

In another terminal, make the default Shisa model available:

```sh
ollama pull gemma3:1b
```

`gemma3:1b` is the CLI default for `shisa ai nextcmd`, `shisa ai explain`, `shisa ai risk --slm`, and `shisa ai bench`.

## 2. Smoke-test the model path

Run the benchmark first because `nextcmd` exits quietly when Ollama is unavailable.

```sh
shisa ai bench --model gemma3:1b --prompt "Reply with ok."
```

Then ask for one suggestion from the CLI:

```sh
shisa ai nextcmd --shell zsh --cwd "$PWD" --last-command "git status" --last-exit 0 --history-path "${HISTFILE:-}"
```

The prompt template asks for one command, no Markdown, and prefers read-only commands unless the recent context clearly asks for a write. Review the suggestion before running it.

## 3. Use the shell hotkey

Source the matching shell init file from [Quickstart](../quickstart.md). Defaults:

| Shell | Suggest | Accept | Reject | Next |
| --- | --- | --- | --- | --- |
| zsh | `^X^N` | `^I` | `^[` | `^[]` |
| bash | `\C-x\C-n` | `\C-i` | `\e` | `\e]` |
| fish | `\cx\cn` | `\t` | `\e` | `\e\]` |
| PowerShell | `Ctrl+x,Ctrl+n` | `Tab` | `Escape` | `Alt+]` |

Nushell init defines `shisa-nextcmd`, `shisa-nextcmd-accept`, `shisa-nextcmd-reject`, and `shisa-nextcmd-next`; it does not install a key binding in `init/shisa.nu`.

## 4. Customize bindings

Set binding variables before sourcing the init file.

```sh
export SHISA_NEXTCMD_KEYSEQ='\C-x\C-n'
export SHISA_NEXTCMD_ACCEPT_KEYSEQ='\C-i'
export SHISA_NEXTCMD_REJECT_KEYSEQ='\e'
export SHISA_NEXTCMD_NEXT_KEYSEQ='\e]'
```

```fish
set -gx SHISA_NEXTCMD_KEYSEQ \cx\cn
set -gx SHISA_NEXTCMD_ACCEPT_KEYSEQ \t
set -gx SHISA_NEXTCMD_REJECT_KEYSEQ \e
set -gx SHISA_NEXTCMD_NEXT_KEYSEQ \e\]
```

```powershell
$env:SHISA_NEXTCMD_CHORD = "Ctrl+x,Ctrl+n"
$env:SHISA_NEXTCMD_ACCEPT_CHORD = "Tab"
$env:SHISA_NEXTCMD_REJECT_CHORD = "Escape"
$env:SHISA_NEXTCMD_NEXT_CHORD = "Alt+]"
```

See [Ollama](../ai-ollama.md) and [Shells](../shells.md).
