# SSO Expiry

`sso_expiry` reads cached token files only.

AWS SSO scans `~/.aws/sso/cache/*.json` and returns the soonest non-empty `expiresAt` value.

gcloud expiry reads cached `gcloud auth list --format=json` output from `~/.cache/shisa/gcloud-auth-list.json` and returns the active account expiry field when present.
