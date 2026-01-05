[![](https://img.shields.io/badge/stonks_cli_1.0.0-passing-green)](https://github.com/gongahkia/stonks-cli/releases/tag/1.0.0)

# `stonks-cli`

A [batteries-included](https://en.wikipedia.org/wiki/Batteries_Included) stock analysis [CLI](https://en.wikipedia.org/wiki/Command-line_interface) tool.

<div align="center">
    <img src="./asset/logo/time.png" width="60%">
</div>

## Stack

* *Language*: [Python](https://www.python.org) 
* *CLI Framework*: [Typer](https://typer.tiangolo.com)
* *TUI*: [Rich](https://rich.readthedocs.io)
* *Data computation*: [pandas](https://pandas.pydata.org), [NumPy](https://numpy.org)
* *HTTP Client*: [Requests](https://requests.readthedocs.io)
* *Scheduling*: [APScheduler](https://apscheduler.readthedocs.io) 
* *Config*: [Pydantic](https://docs.pydantic.dev/latest/) 
* *Local Paths*: [platformdirs](https://platformdirs.readthedocs.io)
* *Data Providers*: [Stooq](https://stooq.com), [yfinance](https://github.com/ranaroussi/yfinance)
* *Package*: [setuptools](https://setuptools.pypa.io)
* *Dev/QA*: [pytest](https://docs.pytest.org), [ruff](https://docs.astral.sh/ruff/), [mypy](https://mypy.readthedocs.io)

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
$ stonks-cli config set tickers '["AAPL","MSFT"]'
$ stonks-cli config validate
```

### Analyze 

```console
$ stonks-cli analyze AAPL MSFT # analyse tickers and write textual report to reports/
$ stonks-cli analyze AAPL MSFT --json # write json output alongside text report
$ stonks-cli analyze AAPL MSFT --csv # write csv summary 
$ stonks-cli analyze AAPL --out-dir reports # configure output directory
$ stonks-cli analyze AAPL --start 2020-01-01 --end 2024-12-31
$ stonks-cli analyze AAPL MSFT --name report_latest.txt # stable report filename
$ stonks-cli analyze AAPL MSFT --sandbox # run without persisting last-run history
```

### Backtest

```console
$ stonks-cli backtest AAPL --start 2020-01-01 --end 2024-12-31
$ stonks-cli backtest AAPL MSFT --out-dir reports
```

### Benchmark

```console
$ stonks-cli bench
$ stonks-cli bench AAPL MSFT --iterations 10 --warmup 2
```

### Schedule

```console
$ stonks-cli schedule once
$ stonks-cli schedule run
$ stonks-cli schedule status
$ stonks-cli schedule once --out-dir reports --name report_latest.txt --csv
$ stonks-cli schedule run --out-dir reports --csv
```

### Data

```console
$ stonks-cli data fetch AAPL MSFT
$ stonks-cli data verify AAPL MSFT
$ stonks-cli data cache-info
$ stonks-cli data purge
$ stonks-cli data purge --older-than-days 7
```

### Reports

```console
$ stonks-cli report latest
$ stonks-cli report latest --json
$ stonks-cli report open
$ stonks-cli report view
$ stonks-cli report view reports/report_2026-01-03_234154.txt
```

### History

```console
$ stonks-cli history list
$ stonks-cli history list --limit 50
$ stonks-cli history show 0
```

### Plugins

```console
$ stonks-cli plugins list
```

### Watchlist

```console
$ stonks-cli watchlist set tech AAPL MSFT
$ stonks-cli watchlist list
$ stonks-cli watchlist remove tech
$ stonks-cli watchlist analyze tech --json --csv --name report_tech_latest.txt
```

### Signals

```console
$ stonks-cli signals diff
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
flowchart TD
    %% High-level entrypoints
    subgraph CLI["CLI Entry"]
        cli["stonks-cli<br/>Typer CLI"]
    end

    subgraph Config["Config & State"]
        cfg["Load config<br/>Pydantic"]
        cfgfile["config.json"]
        state["state.json"]
        hist["history.jsonl"]
    end

    subgraph Plugins["Plugins"]
        plugSpecs["plugin specs<br/>from config"]
        plugLoad["Load plugins<br/>best-effort"]
        stratReg["Strategy registry"]
        provReg["Provider factory<br/>registry"]
    end

    subgraph Pipeline["Analysis Pipeline"]
        selectStrat["Select strategy<br/>built-in or plugin"]
        tickers["Tickers<br/>normalized"]
        fetchParallel["Fetch prices in parallel<br/>ThreadPoolExecutor"]
        prep["_prepare_df_for_strategy<br/>attach indicators"]
        strat["Run strategy<br/>Recommendation"]
        risk["Risk sizing & guardrails<br/>volatility, ATR, portfolio cap"]
        bt["Walk-forward backtest<br/>+ metrics"]
        results["Per-ticker results"]
        portfolio["Portfolio aggregation<br/>optional equity blend"]
    end

    subgraph Providers["Data Providers"]
        providerSelect["provider_for_config<br/>per ticker"]
        stooq["StooqProvider<br/>https://stooq.com"]
        yfin["YFinanceProvider<br/>optional"]
        csv["CsvProvider"]
        cache["Cache dir<br/>text blobs + TTL"]
        negCache["Negative cache<br/>empty results TTL"]
        net["HTTP GET / download"]
        csvFile["CSV file"]
        pxDF["OHLCV DataFrame"]
    end

    subgraph Reporting["Outputs"]
        textRep["Write text report<br/>Rich-friendly formatting"]
        jsonRep["Write JSON report<br/>optional"]
        csvRep["Write CSV summary<br/>optional"]
        outDir["reports/"]
    end

    subgraph Scheduler["Scheduler"]
        cron["APScheduler cron trigger"]
        schedRun["schedule run<br/>foreground"]
        schedOnce["schedule once<br/>single job"]
        lock["Run lock<br/>prevent overlap"]
        pid["PID file"]
        failure["Persist last failure<br/>best-effort"]
    end

    cli --> cfg
    cfg --> cfgfile
    cfg --> plugSpecs
    plugSpecs --> plugLoad
    plugLoad --> stratReg
    plugLoad --> provReg

    cli -->|analyze / watchlist analyze| tickers
    tickers --> selectStrat
    stratReg --> selectStrat
    selectStrat --> fetchParallel
    fetchParallel --> providerSelect
    provReg --> providerSelect

    providerSelect --> stooq
    providerSelect --> yfin
    providerSelect --> csv

    stooq -->|read/write| cache
    stooq -->|check| negCache
    stooq --> net
    net --> pxDF
    yfin --> pxDF
    csv --> csvFile
    csvFile --> pxDF

    pxDF --> prep
    prep --> strat
    strat --> risk
    risk --> bt
    bt --> results
    results --> portfolio

    results --> textRep
    portfolio --> textRep
    textRep --> outDir
    results -->|--json| jsonRep
    jsonRep --> outDir
    results -->|--csv| csvRep
    csvRep --> outDir

    textRep -->|persist last run<br/>unless --sandbox| state
    jsonRep -->|persist json path<br/>when enabled| state
    state --> hist

    cli -->|schedule status| cron
    cli -->|schedule run| schedRun
    cli -->|schedule once| schedOnce
    schedRun --> pid
    schedRun --> cron
    cron --> lock
    schedOnce --> lock
    lock -->|job executes| tickers
    schedRun -->|on error| failure
```

## Legal

`stonks-cli` is provided for educational and informational purposes only.

- **Not financial advice**: This tool does not provide investment, legal, tax, or accounting advice. Any outputs (signals, sizing suggestions, backtests) are heuristic and may be wrong.
- **No warranty**: Use at your own risk. The authors/contributors make no guarantees about correctness, uptime, or fitness for a particular purpose.
- **Data sources & terms**: Market data is fetched from third-party sources (e.g. [Stooq](https://stooq.com) and optional [yfinance](https://github.com/ranaroussi/yfinance) / Yahoo Finance). You are responsible for complying with the applicable terms of service, rate limits, and data-usage restrictions of those providers.
- **Trademarks**: “Yahoo” and “Stooq” are trademarks of their respective owners; this project is not affiliated with or endorsed by them.
- **Local storage**: Reports and run history are written to local disk (e.g. `reports/` plus OS-appropriate app state/cache directories). No intentional data is sent anywhere except to fetch price data from the configured provider.
