[![](https://img.shields.io/badge/stonks_cli_1.0.0-passing-green)](https://github.com/gongahkia/stonks-cli/releases/tag/1.0.0)

# `stonks-cli`

Batteries-included Stock Analysis [CLI](https://en.wikipedia.org/wiki/Command-line_interface) tool.

<div align="centre">
    <img src="./asset/logo/time.png">
</div>

## Stack

* *Backend*: ...  
* *...*: ...  
* *...*: ...  

- Python 3.11+
- CLI: Typer
- Output: Rich tables
- Data/analysis: pandas + numpy
- Scheduling: APScheduler (cron triggers)
- Config: Pydantic v2
- Paths/state/cache dirs: platformdirs
- Providers: Stooq (default), optional yfinance

## Usage

> [!IMPORTANT]  
> Please read the [legal disclaimer](#legal) before using `stonks-cli`.

The below instructions are for locally running `stonks-cli`. Also see [here](#available-commands) for `stonks-cli`'s out-of-the-box commands.

1. First run the below to install `stonks-cli` to your local machine.

```console
$ git clone https://github.com/gongahkia/stonks-cli && cd stonks-cli
$ python3 -m venv .venv && source .venv/bin/activate
$ python3 -m pip install -U pip && python3 -m pip install -e .
```

## Available Commands

### Sanity check

```console
$ stonks-cli --help
$ stonks-cli version
$ stonks-cli doctor
```

### Configure

```console
$ stonks-cli config init
$ stonks-cli config where
$ stonks-cli config show
$ stonks-cli config validate
```

### Analyze 

```console
$ stonks-cli analyze AAPL MSFT # analyse tickers and write textual report to reports/
$ stonks-cli analyze AAPL MSFT --json # write json output alongside text report
$ stonks-cli analyze AAPL MSFT --csv # write csv summary 
$ stonks-cli analyze AAPL --out-dir reports # configure output directory
```

### Backtest

```console
$ stonks-cli backtest AAPL --start 2020-01-01 --end 2024-12-31
```

### Schedule

```console
$ stonks-cli schedule once
$ stonks-cli schedule run
$ stonks-cli schedule status
```

### Watchlist

```console
$ stonks-cli watchlist set tech AAPL MSFT
$ stonks-cli watchlist list
$ stonks-cli watchlist analyze tech --json --csv --name report_tech_latest.txt
```

## Screenshots

![](./asset/reference/0.png)  
![](./asset/reference/1.png)  
![](./asset/reference/2.png)  
![](./asset/reference/3.png)  
![](./asset/reference/4.png)  
![](./asset/reference/5.png)  
![](./asset/reference/6.png)  

## Architecture

```mermaid
...
```

## Legal

...