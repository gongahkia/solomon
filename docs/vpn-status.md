# VPN Status

`vpn_status` detects active VPN clients from local command output.

WireGuard detection runs `wg show` and treats the first non-empty `interface:` line as active. No network calls are made.
