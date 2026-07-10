<!-- SPDX-License-Identifier: Apache-2.0 -->

# Currency Eval Submission Record

The currency-eval writeup is submitted as a repository-citable artifact for `v0.1.0`:

- GitHub release: [Solomon v0.1.0](https://github.com/gongahkia/solomon/releases/tag/v0.1.0)
- External tracking issue: [#4 Currency evaluation submission evidence for v0.1.0](https://github.com/gongahkia/solomon/issues/4)
- Writeup: [currency-eval-writeup.md](currency-eval-writeup.md)
- Corpus schema and reproduction notes: [evaluation-corpus.md](evaluation-corpus.md)
- Committed sample corpus: [evaluation-corpus.synthetic.json](evaluation-corpus.synthetic.json)
- Executable coverage and monitoring benchmarks: `run_jurisdiction_coverage_benchmark()` and
  `run_external_law_monitoring_benchmark()` in `solomon.evaluation`
- Citation metadata: [../CITATION.cff](../CITATION.cff)
- Repository URL: `https://github.com/gongahkia/solomon`

## Latest Local Verification

Verified on 2026-07-10 with:

```bash
uv run python -m solomon.evaluation
```

Result summary:

- Solomon stale-surface rate: `0.000`
- Solomon time-to-flag: `0.066s`
- Solomon impact-query recall: `1.000`
- Jurisdiction coverage: `18/18`, coverage rate `1.0`
- External-law monitoring change-detection recall: `1.0`
- External-law monitoring false-positive rate: `0.0`
- External-law monitoring impact-query recall: `1.0`

External DOI publication can be layered on later by connecting the repository to an archival service, but the
current artifact is already versioned, reproducible from source, release-addressable on GitHub, and tracked in
a public issue.
