# SSH Target

`ssh_target` detects remote SSH sessions from `SSH_CONNECTION`.

When `SSH_CONNECTION` is non-empty, the module treats the current host name as the SSH target.

The target host is classified with the same default and user `risk_tier` rules used elsewhere.
