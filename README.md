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

If you see `command not found: stonks-cli`, your virtualenv is not active. Either run:

```bash
source .venv/bin/activate
```

or invoke the CLI directly:

```bash
./.venv/bin/stonks-cli --help
```

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

### Optional: local LLM chat (no Ollama service)

`stonks-cli` supports multiple local backends. By default, `model.backend` is set to `auto` and will pick a reasonable backend based on your platform + installed extras.

- macOS Apple Silicon: prefer `mlx` (fastest/easiest local experience)
- Cross-platform offline: prefer `llama_cpp` with a GGUF model file
- CUDA-heavy setups: prefer `transformers` (best when running on NVIDIA GPU)

Install an extra for your preferred backend:

```bash
python -m pip install -e ".[mlx]"           # macOS Apple Silicon (MLX)
python -m pip install -e ".[llama-cpp]"     # GGUF / llama.cpp (cross-platform)
python -m pip install -e ".[transformers]"  # transformers + torch
```

Run with an explicit backend override:

```bash
stonks-cli llm check --backend llama_cpp --path ~/models/model.gguf --offline
stonks-cli chat --backend llama_cpp
```

Or set it in config (persists across runs):

```bash
stonks-cli config set model.backend "llama_cpp"
stonks-cli config set model.path "~/models/model.gguf"
stonks-cli config set model.offline true
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
