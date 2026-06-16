# Pack Status

Pack lifecycle:

| State | Meaning | Exit criteria |
| --- | --- | --- |
| `incubation` | Experimental plugin pack or template. | Basic docs, smoke test, owner. |
| `graduated` | Supported pack with stable manifest/API usage. | Benchmarks, compatibility docs, release notes. |
| `vetted` | Maintainer-reviewed pack eligible for verified marketplace badge. | Signed manifest, capability review, security owner. |
| `eol` | Deprecated or unsupported pack. | Migration path or removal note. |

Current packs:

| Pack | State | Owner | Notes |
| --- | --- | --- | --- |
| `shisa.vcs` | incubation | core | jj/sapling core support plus fossil/pijul/bazaar community templates. |
| `shisa.cloud` | incubation | core | AWS, cached GCP, cached Azure, and cached Kubernetes context landed; no network by default. |
| `shisa.ai` | incubation | core | Optional local-first hint pack; outside core. |
| community templates | incubation | community | Template repos planned before marketplace verification. |

Status changes require a changelog entry and capability review when capabilities change.
