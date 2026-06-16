# SSO Expiry

`sso_expiry` reads cached token files only.

AWS SSO scans `~/.aws/sso/cache/*.json` and returns the soonest non-empty `expiresAt` value.

gcloud expiry reads cached `gcloud auth list --format=json` output from `~/.cache/shisa/gcloud-auth-list.json` and returns the active account expiry field when present.

Azure expiry reads `~/.azure/accessTokens.json` and returns the soonest non-empty token expiry field.

Vault lease info reads `~/.vault-token`. Raw token-only files return no expiry; JSON metadata returns the first non-empty expiry or TTL field from the top level, `auth`, or `data`.
