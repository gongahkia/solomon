# Close Enough

Local, deterministic terminal repair hints. The current slice supports command, Git subcommand, and path typo suggestions with configurable hint, interrupt, rewrite, and off modes.

License: GPL-3.0-only. The complete license text is required before the first release artifact.

```sh
go build ./cmd/close-enough
./close-enough init --shell zsh >> ~/.zshrc
./close-enough check --command 'gti status'
```

`close-enough` never sends command data over the network by default and does not auto-apply risky transformations.

Exit codes are stable: `0` success, `1` unexpected internal failure, `2` invalid CLI usage, `3` configuration failure, `4` invalid command or pack input, and `5` local operation failure.
