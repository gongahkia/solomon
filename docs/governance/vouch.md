# Vouch

Shisa tracks explicit contributor trust in the root `VOUCHES` file.

## Rules

- New contributors start unvouched.
- Unvouched PRs are welcome, but require review from at least two vouched reviewers.
- Vouching is granted only by people with repository write access.
- Vouched contributors cannot grant vouches unless they also have write access.
- Update `VOUCHES` whenever write access or vouch state changes.

## File Format

`VOUCHES` is POSIX shell syntax. It must pass:

```sh
sh -n VOUCHES
```

Do not source `VOUCHES` from untrusted checkouts.

Required header:

```sh
VOUCHES_FORMAT=1
```

Entries use dense four-digit ordinals:

```sh
VOUCH_0001_ID=founder
VOUCH_0001_NAME='Gabriel Ong Zhe Mian'
VOUCH_0001_GITHUB=gongahkia
VOUCH_0001_ROLE=founder
VOUCH_0001_DATE=2026-06-17
VOUCH_0001_BY=self
```

Required fields:

| Field | Meaning |
| --- | --- |
| `ID` | stable local id, lowercase slug |
| `NAME` | display name |
| `GITHUB` | GitHub username without `@` |
| `ROLE` | `founder`, `maintainer`, or `contributor` |
| `DATE` | date granted, `YYYY-MM-DD` |
| `BY` | grantor id, or `self` for the bootstrap founder entry |

The verifier rejects missing header, non-dense ordinals, missing required fields, duplicate `ID` values, duplicate `GITHUB` values, invalid dates, and unknown roles.

## Current State

Only the founder is vouched at bootstrap.

Reference: `north-star.md` section 35.3.
