# CLI and MCP verb audit

Decision date: 2026-06-14

Rule: MCP tool names use `solomon.<snake_case>`. CLI equivalents use kebab-case without the `solomon.` prefix.

## Mapping

| MCP tool | Preferred CLI | Migration shim |
| --- | --- | --- |
| `solomon.health` | `solomon health` | `solomon diagnostics` remains as richer local diagnostics |
| `solomon.preflight_context` | `solomon preflight <query>` | none |
| `solomon.check_currency` | `solomon check-currency <item-id>` | `solomon show-currency <item-id>` |
| `solomon.get_dependencies` | `solomon get-dependencies <item-id>` | none |
| `solomon.verify_position` | `solomon verify-position <item-id> --outcome <decision> --by <id>` | none |
| `solomon.ingest` | `solomon ingest ...` | none |
| `solomon.audit_pack` | `solomon audit-pack <item-id> <destination>` | `solomon export-audit-pack <destination>` |
| `solomon.dependency_suggestions` | `solomon dependency-suggestions ...` | none |
| no write MCP equivalent | `solomon defer-dependency-suggestion <suggestion-id> --by <id> --reason <text>` | none |
| `solomon.impact` | `solomon impact <authority-id>` | `solomon impact-query <authority-id>` |

## Shim policy

The older CLI verbs remain callable for one release and are hidden from help where a direct MCP-aligned replacement exists. They should be removed after downstream scripts have migrated to the preferred commands.
