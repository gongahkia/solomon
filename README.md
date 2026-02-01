[![](https://img.shields.io/badge/stonks_cli_1.0.0-passing-light_green)](https://github.com/gongahkia/stonks-cli/releases/tag/1.0.0)
[![](https://img.shields.io/badge/stonks_cli_2.0.0-passing-green)](https://github.com/gongahkia/stonks-cli/releases/tag/2.0.0)
![](https://github.com/gongahkia/stonks-cli/actions/workflows/ci.yml/badge.svg)

# `stonks-cli`

A [batteries-included](https://en.wikipedia.org/wiki/Batteries_Included) stock analysis [CLI](https://en.wikipedia.org/wiki/Command-line_interface) tool *(now also available via **[MCP server](https://modelcontextprotocol.io/docs/getting-started/intro)**)*.

<div align="center">
    <img src="./asset/logo/time.png" width="25%">
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
* *AI Integration*: [MCP](https://modelcontextprotocol.io)
* *Data Providers*: [Stooq](https://stooq.com), [yfinance](https://github.com/ranaroussi/yfinance)
* *Package*: [setuptools](https://setuptools.pypa.io)
* *Dev/QA*: [pytest](https://docs.pytest.org), [ruff](https://docs.astral.sh/ruff/), [mypy](https://mypy.readthedocs.io)
* *CI/CD*: [GitHub Actions](https://github.com/features/actions)

## Screenshots

<div align="center">
    <img src="./asset/reference/7.png" width="45%">
    <img src="./asset/reference/0.png" width="45%">
</div>

<div align="center">
    <img src="./asset/reference/1.png" width="45%">
    <img src="./asset/reference/2.png" width="45%">
</div>

<div align="center">
    <img src="./asset/reference/5.png" width="45%">
    <img src="./asset/reference/3.png" width="45%">
</div>

<div align="center">
    <img src="./asset/reference/6.png" width="45%">
    <img src="./asset/reference/4.png" width="45%">
</div>

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

2. Then run the `stonks-cli` CLI client directly with any of the below commands.

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

3. `stonks-cli` also includes an optional [Model Context Protocol](https://modelcontextprotocol.io) server that allows for [AI Agents](https://modelcontextprotocol.io/docs/agents/) to directly interact with `stonks-cli` tooling.

4. Run the below to install `stonks-cli`'s MCP functionality.

```console
$ pip install -e ".[mcp]"
# or with uv
$ uv sync --extra mcp
```

5. Then execute these commands for usage.

```console
$ stonks-mcp
$ python -m stonks_cli.mcp_server  
```

### MCP Commands

* Quick Analysis: `quick_analysis`, `get_version`, `run_doctor`
* Market Data: `get_fundamentals`, `get_news`, `get_earnings`, `get_insider_transactions`, `get_dividend_info`, `get_sector_performance`, `get_correlation_matrix`, `get_market_movers`
* Charts: `get_chart_data`, `get_chart_compare_data`, `get_rsi_chart_data`
* Analysis: `run_analysis`, `run_backtest`, `get_signals_diff`
* Watchlists: `list_watchlists`, `create_watchlist`, `delete_watchlist`, `analyze_watchlist`
* Portfolio: `add_portfolio_position`, `remove_portfolio_position`, `get_portfolio`, `get_portfolio_allocation`, `get_portfolio_history`
* Paper Trading: `paper_buy`, `paper_sell`, `get_paper_status`, `get_paper_leaderboard`
* Alerts: `create_alert`, `list_alerts`, `delete_alert`, `check_alerts`
* Data: `fetch_data`, `verify_data`, `get_cache_info`
* Config: `get_config`, `validate_config`
* Reports: `get_latest_report`, `view_report`, `list_history`

## Architecture

```mermaid
flowchart TD
    %% High-level entrypoints
    subgraph Interfaces["Interfaces"]
        cli["stonks-cli<br/>Typer CLI"]
        mcp["stonks-mcp<br/>MCP Server"]
    end

    subgraph Config["Config & State"]
        cfg["Load config<br/>Pydantic"]
        cfgfile["config.json"]
        state["state.json"]
        hist["history.jsonl"]
        portStore["portfolio.json<br/>& history"]
        alertStore["alerts.json"]
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
        portfolioAgg["Portfolio aggregation<br/>optional equity blend"]
    end

    subgraph Portfolio["Portfolio & Paper Trading"]
        portMgr["Portfolio Manager"]
        paperMgr["Paper Trading Engine"]
    end

    subgraph Alerts["Alerts System"]
        alertCheck["Checker<br/>cron/manual"]
        alertNotifier["Notifier"]
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

    %% Config connections
    cli --> cfg
    mcp --> cfg
    cfg --> cfgfile
    cfg --> plugSpecs
    plugSpecs --> plugLoad
    plugLoad --> stratReg
    plugLoad --> provReg

    %% CLI/MCP Actions
    cli -->|analyze| tickers
    mcp -->|run_analysis| tickers
    cli -->|watchlist| tickers
    mcp -->|list_watchlists| cfgfile

    %% Pipeline connections
    tickers --> selectStrat
    stratReg --> selectStrat
    selectStrat --> fetchParallel
    fetchParallel --> providerSelect
    provReg --> providerSelect

    %% Data flow
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

    %% Analysis Logic
    pxDF --> prep
    prep --> strat
    strat --> risk
    risk --> bt
    bt --> results
    results --> portfolioAgg

    %% Reporting
    results --> textRep
    portfolioAgg --> textRep
    textRep --> outDir
    results -->|--json| jsonRep
    jsonRep --> outDir
    results -->|--csv| csvRep
    csvRep --> outDir

    %% State Persistence
    textRep -->|persist last run| state
    jsonRep --> state
    state --> hist

    %% Portfolio Module
    cli -->|portfolio| portMgr
    mcp -->|get_portfolio| portMgr
    cli -->|paper| paperMgr
    mcp -->|paper_buy/sell| paperMgr
    portMgr --> portStore
    paperMgr --> portStore
    portMgr -->|fetch price| providerSelect

    %% Alerts Module
    cli -->|alerts| alertCheck
    mcp -->|create_alert| alertStore
    mcp -->|check_alerts| alertCheck
    alertCheck --> alertStore
    alertCheck -->|fetch price| providerSelect
    alertCheck -->|trigger| alertNotifier

    %% Scheduler
    cli -->|schedule| cron
    schedRun --> pid
    schedRun --> cron
    cron --> lock
    lock -->|trigger| tickers
```

## Legal

`stonks-cli` is provided for educational and informational purposes only.

- **Not financial advice**: This tool does not provide investment, legal, tax, or accounting advice. Any outputs (signals, sizing suggestions, backtests) are heuristic and may be wrong.
- **No warranty**: Use at your own risk. The authors/contributors make no guarantees about correctness, uptime, or fitness for a particular purpose.
- **Data sources & terms**: Market data is fetched from third-party sources (e.g. [Stooq](https://stooq.com) and optional [yfinance](https://github.com/ranaroussi/yfinance) / Yahoo Finance). You are responsible for complying with the applicable terms of service, rate limits, and data-usage restrictions of those providers.
- **Trademarks**: “Yahoo” and “Stooq” are trademarks of their respective owners; this project is not affiliated with or endorsed by them.
- **Local storage**: Reports and run history are written to local disk (e.g. `reports/` plus OS-appropriate app state/cache directories). No intentional data is sent anywhere except to fetch price data from the configured provider.
