# vNext package boundaries

`stonks_cli.vnext` isolates decision-support components from the research and carry packages.

| Package | Allowed dependencies | Broker access |
| --- | --- | --- |
| `foundation` | none | none |
| `broker` | `foundation` | read-only |
| `research` | `foundation`, `broker` | none |
| `portfolio` | `foundation`, `broker` | none |
| `operator` | `foundation`, `portfolio`, `research` | none |
| `reliability` | `foundation` | none |
| `execution` | `foundation`, `operator`, `portfolio`, `reliability` | none |

The boundary contract rejects missing packages, cycles, indirect execution dependencies, broker access outside `broker`, and every order-submission capability. `execution` is reserved for default-deny safeguards; it cannot submit orders.
