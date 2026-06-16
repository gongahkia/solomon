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
