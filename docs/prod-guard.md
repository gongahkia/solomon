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

Current daemon responses include tier, tier reason, and destructive-pattern metadata. Blocking and typed confirmation are layered on top of this decision path.
