# VPN Status

`vpn_status` detects active VPN clients from local command output.

WireGuard detection runs `wg show` and treats the first non-empty `interface:` line as active. No network calls are made.

Tailscale detection runs `tailscale status --json` and requires `BackendState` to be `Running`. It renders the local `Self.HostName` when available.

NetBird detection runs `netbird status --json` and requires `status` to be `Connected` or `Up`.

Cloudflare WARP detection runs `warp-cli status` and requires `Status update: Connected`.

ZeroTier detection runs `zerotier-cli status` and requires an `ONLINE` token.

macOS built-in VPN detection runs `scutil --nc list` and requires a connected `[VPN:<type>]` service.

Linux NetworkManager detection reads D-Bus properties with `busctl`, checks active connection `Vpn=true`, and uses the connection `Id` as the VPN name.
