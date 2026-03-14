[![](https://img.shields.io/badge/senko_1.0-passing-light_green)](https://github.com/gongahkia/senko/releases/tag/1.0)
[![](https://img.shields.io/badge/senko_2.0-passing-green)](https://github.com/gongahkia/senko/releases/tag/2.0)

# `せんこ`

Memorise things fast.

Written in [curses](https://docs.python.org/3/howto/curses.html). 

## [quickstart](./quickstart.md)

## installation

```console
$ git clone https://github.com/gongahkia/senko
$ cd senko
$ python -m pip install .
$ senko
```

## highlights

- Versioned `.sko` files with validation and automatic legacy migration.
- Searchable file, set, and card pickers directly in the TUI with `/`.
- Multiline card editing plus duplicate, move, reorder, suspend, reset, and delete actions from one card-management screen.
- CSV, JSON, and plain-text import/export with field mapping, previews, and whole-set replacement.
- CLI commands for deck creation, set/card management, headless review, validation, migration, import, export, stats, and history maintenance.
- Persistent review history with richer stats including retention, review activity, overdue buckets, recent additions, workload, and leech candidates.
- Safer deck writes with atomic save behavior to reduce corruption risk.

## cli

```console
$ senko validate
$ senko create-deck japanese
$ senko create-set japanese core_2k
$ senko add-card japanese core_2k --name "ありがとう" --info "thank you" --tags greeting
$ senko edit-card japanese core_2k "ありがとう" --notes "formal enough for most situations"
$ senko duplicate-card japanese core_2k "ありがとう" --target-set review
$ senko move-card japanese core_2k review "ありがとう"
$ senko review japanese --set review --record-progress
$ senko stats --deck japanese
$ senko export-history ~/Desktop/japanese-history.json --deck japanese --format json
$ senko export japanese --format csv --output ~/Desktop/japanese.csv
```

## lightweight review

```console
$ senko-cards japanese --due-only --record-progress
$ senko-cards ~/Desktop/external_cards.csv --due-only
```
