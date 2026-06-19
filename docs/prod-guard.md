# Prod Guard

`prod_guard` receives pre-exec command payloads from shell hooks and returns a daemon decision.

Built-in destructive command patterns:

- `kubectl delete`
- `kubectl drain`
- `terraform destroy`
- `aws ec2 terminate*`
- `aws s3 rb`
- `gcloud * delete`
- `rm -rf` / `rm -fr`
- `dd of=/dev/`
- `mkfs*`
- SQL `DROP TABLE`

Daemon responses include tier, tier reason, and destructive-pattern metadata. Destructive commands classified as `prod` return `allow=false` and `confirm="prod"`; the CLI requires typing the tier name before proceeding.

`shisa cloud preexec --force -- <command>` bypasses the typed confirmation and emits a `prod_guard_force` daemon log event when the command matches a destructive pattern. Shell hooks pass `--force` when `SHISA_PROD_GUARD_FORCE=1`.

Every pre-exec cloud request is appended to `~/.local/state/shisa/cloud_requests.jsonl` with SHA-256 hashes for cwd and command text. Destructive pre-exec decisions are appended to `~/.local/state/shisa/prod_guard.jsonl` with `command_sha256`, not raw command text.

Review both audit logs:

```sh
shisa cloud audit
```
