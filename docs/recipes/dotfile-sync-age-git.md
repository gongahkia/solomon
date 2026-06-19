# Dotfile Sync with age and Git

This is a prototype for encrypted Shisa config sync through a user-owned Git remote.

It does not run automatically and does not sync secrets unless the user explicitly exports the config.

## Export

```sh
scripts/dotfile-sync-prototype.sh export \
  --repo ~/.local/share/shisa-dotfiles \
  --recipient age1example... \
  --remote git@example.com:me/shisa-dotfiles.git
```

Export writes `shisa.toml.age` and `SHISA_DOTFILE_SYNC`, then commits them locally. It pushes only when `SHISA_DOTFILE_SYNC_PUSH=1` is set.

## Import

```sh
scripts/dotfile-sync-prototype.sh import \
  --repo ~/.local/share/shisa-dotfiles \
  --identity ~/.config/age/keys.txt
```

Import decrypts to the normal `shisa.toml` path with mode `0600`.

## Safety Notes

- Review `shisa.toml` before exporting; config may contain local paths, plugin ids, or provider defaults.
- Use a dedicated age recipient for dotfile sync.
- Keep the Git remote private unless the encrypted config is intentionally public.
- This prototype does not manage merge conflicts or trust project-local configs.
