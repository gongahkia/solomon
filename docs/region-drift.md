# Region Drift

`region_drift` compares environment region overrides with cached provider config.

AWS drift checks `AWS_REGION`, then `AWS_DEFAULT_REGION`, against the selected profile's `region` in `~/.aws/config`. Drift is reported as `aws:<env>!=<config>`.
