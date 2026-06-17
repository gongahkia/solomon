# 5-Min Setup

Purpose: install walkthrough for a local source checkout before packaged releases exist.

Target length: 4:45 to 5:15.

## Message

Build Shisa locally, start the daemon, source one shell hook, and verify the prompt path with `doctor` and `explain`.

## Prereqs

- macOS or Linux shell session.
- Zig matching `build.zig.zon`.
- Git.
- Repo checkout.

Do not claim Homebrew, AUR, nixpkgs, or curl installer support in this video until release engineering lands.

## Structure

| Time | Visual | Voiceover |
| --- | --- | --- |
| 0:00-0:20 | Open `docs/quickstart.md`. | "This walkthrough sets up Shisa from a local checkout. Packaged installers are separate release-engineering work." |
| 0:20-0:50 | Show `git clone`, `cd shisa`, `zig build debug`. | "Clone the repo, enter it, and build the debug binaries. This produces `shisa` and `shisad` under `zig-out/bin`." |
| 0:50-1:20 | Run `./zig-out/bin/shisad --foreground`. | "Start the daemon in the foreground for the first smoke test. Keep this terminal open so logs stay visible." |
| 1:20-2:20 | Open a second terminal and source one hook. | "Set `SHISA_BIN` to the built CLI and source the hook for your shell. For zsh and bash, this can go into your startup file after the smoke test." |
| 2:20-2:55 | Run `./zig-out/bin/shisa doctor`. | "`doctor` checks the socket, config directory, plugin directory, Lua runtime, and filesystem notification backend." |
| 2:55-3:25 | Run `./zig-out/bin/shisa explain`. | "`explain` prints the resolved prompt pipeline so you can confirm which modules are active." |
| 3:25-4:05 | Demonstrate fallback by stopping the daemon, then rendering again. | "If the daemon is unavailable, the hook still falls back to a minimal prompt. That keeps shell input responsive." |
| 4:05-4:35 | Show `docs/shells.md`. | "Each shell has a slightly different redraw and instant-prompt path. Use the shell matrix when debugging setup issues." |
| 4:35-5:00 | End on quickstart and profiling commands. | "After setup, run the quickstart checks and benchmark locally before changing prompt modules or shell hooks." |

## Commands

```sh
git clone https://github.com/gongahkia/shisa.git
cd shisa
zig build debug
./zig-out/bin/shisad --foreground
```

In another zsh session:

```sh
export SHISA_BIN="$PWD/zig-out/bin/shisa"
source "$PWD/init/shisa.zsh"
./zig-out/bin/shisa doctor
./zig-out/bin/shisa explain
```

Bash:

```sh
export SHISA_BIN="$PWD/zig-out/bin/shisa"
source "$PWD/init/shisa.bash"
```

Fish:

```fish
set -gx SHISA_BIN "$PWD/zig-out/bin/shisa"
source "$PWD/init/shisa.fish"
```

Nushell:

```nu
$env.SHISA_BIN = $"($env.PWD)/zig-out/bin/shisa"
source init/shisa.nu
```

PowerShell:

```powershell
$env:SHISA_BIN = "$PWD/zig-out/bin/shisa"
. ./init/shisa.ps1
```

## Transcript

This walkthrough sets up Shisa from a local checkout. Packaged installers are separate release-engineering work, so this video uses the source build path.

Clone the repo, enter it, and build the debug binaries with `zig build debug`.

That produces the CLI, `shisa`, and the daemon, `shisad`, under `zig-out/bin`.

For the first run, start the daemon in the foreground with `./zig-out/bin/shisad --foreground`.

Keep that terminal open so socket and log behavior are visible while you test.

In another terminal, set `SHISA_BIN` to the built CLI and source the hook for your shell.

For zsh, export `SHISA_BIN="$PWD/zig-out/bin/shisa"` and source `init/shisa.zsh`.

For bash, source `init/shisa.bash`.

For fish, use `set -gx SHISA_BIN "$PWD/zig-out/bin/shisa"` and source `init/shisa.fish`.

Nushell and PowerShell have their own init files too.

Once the hook loads, run `./zig-out/bin/shisa doctor`.

`doctor` checks the daemon socket, config directory, plugin directory, Lua runtime, and filesystem notification backend.

Then run `./zig-out/bin/shisa explain`.

`explain` prints the resolved module pipeline, so you can confirm the prompt is using the modules you expect.

If the daemon is unavailable, the hook still falls back to a minimal prompt. That fallback is part of the setup contract: the shell stays responsive even when the daemon is down.

If setup behaves differently in another shell, check the shell matrix in `docs/shells.md`.

After setup works, run the quickstart checks and local benchmarks before changing prompt modules or shell hooks.

## Captions

- [SRT captions](setup-walkthrough.srt)

## Recording Checklist

- Use a clean shell profile or explicitly show temporary sourcing.
- Keep daemon foreground logs visible for the first run.
- Use one primary shell for the main flow; mention others through quick commands only.
- Show `doctor` and `explain` output.
- Show fallback behavior without implying the daemon crash path was tested.
- End on docs, not packaged installers.

## Cut List

- Remove package-manager install instructions until release packaging lands.
- Remove any benchmark numbers unless recorded in the same session.
- Remove edits to permanent shell startup files unless the command is shown as optional.
