# CurrencyBench Citable Submission

Submitting CurrencyBench somewhere citable is externally blocked until a release
owner signs in to the chosen archive and approves the release metadata. The repo
is prepared for a Zenodo-backed DOI through `.zenodo.json` and `CITATION.cff`.

## Recommended Path

Use GitHub-to-Zenodo release archiving:

1. Enable Zenodo archiving for `gongahkia/shibahama`.
2. Confirm `.zenodo.json` metadata is accepted.
3. Create the final `v0.1.0` GitHub release after registry publish succeeds.
4. Let Zenodo archive the release and mint the DOI.
5. Add the DOI to `CITATION.cff`, this file, and
   `benchmarks/currencybench/README.md`.

## Submission Scope

Submit the repository release, not a standalone claim that CurrencyBench is a
large public benchmark. The current citable artifact should be described as:

```text
CurrencyBench v0 is a deterministic fact-change benchmark included with
Shibahama. It measures stale-answer behavior and token cost for local
continuity tasks. Checked-in results currently cover Shibahama and the
warehouse baseline only.
```

## Pre-Submission Checklist

- `benchmarks/currencybench/currencybench-v0.jsonl` regenerated from
  `benchmarks/currencybench/generate.py`.
- `benchmarks/results/currencybench-local.json` and `.md` regenerated with the
  exact command in `benchmarks/currencybench/README.md`.
- README benchmark table matches the checked-in result artifact.
- No hosted external-system claims are present without checked-in successful
  runs.
- `CITATION.cff` and `.zenodo.json` metadata match the release title and
  version.
