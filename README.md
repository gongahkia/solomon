[![](https://img.shields.io/badge/stonks_cli_1.0.0-passing-green)](https://github.com/gongahkia/stonks-cli/releases/tag/1.0.0)

# `stonks-cli`

A batteries-included stock analysis CLI that writes reports to `reports/`.

## Quickstart

### Prerequisites

- Python 3.11+

### Install (recommended)

Using `pip` (editable install for development):

```bash
python3.11 -m venv .venv
source .venv/bin/activate

python -m pip install -U pip
python -m pip install -e .
```

Or using `uv`:

```bash
uv venv
source .venv/bin/activate
uv pip install -e .
```

After installing, the CLI is available as `stonks-cli`.

### Sanity check

```bash
stonks-cli --help
stonks-cli version
stonks-cli doctor
```

### Configure

Create a default config file:

```bash
stonks-cli config init
stonks-cli config where
stonks-cli config show
```

### Analyze (writes a report)

Analyze one or more tickers and write a text report to `reports/` (default):

```bash
stonks-cli analyze AAPL MSFT
```

Write JSON output alongside the text report:

```bash
stonks-cli analyze AAPL MSFT --json
```

Change output directory:

```bash
stonks-cli analyze AAPL --out-dir reports
```

### Backtest

```bash
stonks-cli backtest AAPL --start 2020-01-01 --end 2024-12-31
```

### Scheduler

Run once (same as a single scheduled job):

```bash
stonks-cli schedule once
```

Run the scheduler in the foreground:

```bash
stonks-cli schedule run
```

Check scheduler status (cron + next run time):

```bash
stonks-cli schedule status
```

### Reports + history

Print the latest report path:

```bash
stonks-cli report open
```

List prior runs:

```bash
stonks-cli history list
stonks-cli history show 0
```

### Optional: local LLM chat (Ollama)

Install the optional extra:

```bash
python -m pip install -e ".[ollama]"
```

Then:

```bash
stonks-cli llm check
stonks-cli chat
```

## Stack

* ...
* ...
* ...

## Usage

See **Quickstart** above.

## Available Commands

Run `stonks-cli --help` for the full command list.

## Available Tools

...

## Screenshots

...

## Architecture

```mermaid

```

## Legal

...
