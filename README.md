[![](https://img.shields.io/badge/senko_1.0-passing-light_green)](https://github.com/gongahkia/senko/releases/tag/1.0)
[![](https://img.shields.io/badge/senko_2.0-passing-green)](https://github.com/gongahkia/senko/releases/tag/2.0)

# `せんこ`

Memorise things fast.

Written in [curses](https://docs.python.org/3/howto/curses.html). 

## [quickstart](./quickstart.md)

## installation

```console
$ git clone https://github.com/gongahkia/senko
$ cd src && chmod +x senko.sh
$ ./senko.sh
```

## highlights

- Versioned `.sko` files with validation and automatic legacy migration.
- Searchable file, set, and card pickers directly in the TUI with `/`.
- Multiline card editing plus duplicate, move, reorder, suspend, reset, and delete actions from one card-management screen.
- CSV, JSON, and plain-text import/export with field mapping, previews, and whole-set replacement.
- CLI commands for `validate`, `migrate`, `import`, and `export`.
- Richer stats including retention, overdue buckets, recent additions, workload, and leech candidates.
- Safer deck writes with atomic save behavior to reduce corruption risk.

## cli

```console
$ ./senko.sh validate
$ ./senko.sh migrate ~/Downloads/legacy.sko --output ~/Desktop/fixed.sko
$ ./senko.sh import ~/Desktop/cards.csv japanese --strategy replace
$ ./senko.sh export japanese --format csv --output ~/Desktop/japanese.csv
```
