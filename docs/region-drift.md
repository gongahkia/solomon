# Region Drift

`region_drift` compares environment region overrides with cached provider config.

AWS drift checks `AWS_REGION`, then `AWS_DEFAULT_REGION`, against the selected profile's `region` in `~/.aws/config`. Drift is reported as `aws:<env>!=<config>`.

GCP drift checks `CLOUDSDK_COMPUTE_REGION` against the active Cloud SDK config's `[compute] region`. Drift is reported as `gcp:<env>!=<config>`.

Azure drift checks `AZURE_LOCATION`, then `ARM_LOCATION`, then `AZURE_DEFAULT_LOCATION`, against `~/.azure/config` `[defaults] location` or `region`. Drift is reported as `az:<env>!=<config>`.
