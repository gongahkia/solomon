<!-- SPDX-License-Identifier: Apache-2.0 -->

# Evaluation Corpus

Solomon's synthetic evaluation corpus is deterministic. It creates internal positions, dependency edges,
one changed authority, and the expected stale item ids for impact-query recall.

Regenerate the committed sample:

```bash
uv run python scripts/export_synthetic_corpus.py --size 10 --output docs/evaluation-corpus.synthetic.json
```

Schema:

- `schema_id`: export format identifier.
- `items`: serialized `KnowledgeItem` records.
- `dependencies`: serialized dependency edges.
- `changed_authority_id`: the authority whose movement should trigger propagation.
- `expected_stale_item_ids`: the oracle set for impact-query recall.

The generator is intentionally synthetic. It tests Solomon's currency mechanics and baselines, not jurisdictional
coverage or external-law monitoring completeness.
