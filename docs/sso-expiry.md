# SSO Expiry

`sso_expiry` reads cached token files only.

AWS SSO scans `~/.aws/sso/cache/*.json` and returns the soonest non-empty `expiresAt` value.
