from __future__ import annotations

from pathlib import Path
import sys

import typer
from rich.console import Console

from pydantic import ValidationError

from stonks_cli.config import load_config
from stonks_cli.commands import (
    do_analyze,
    do_analyze_artifacts,
    do_backtest,
    do_bench,
    do_chart,
    do_chart_compare,
    do_chart_rsi,
    do_config_init,
    do_correlation,
    do_earnings,
    do_fundamentals,
    do_insider,
    do_news,
    do_portfolio_add,
    do_portfolio_allocation,
    do_portfolio_history,
    do_portfolio_remove,
    do_portfolio_show,
    do_sector,
    do_watch,
    do_config_set,
    do_config_show,
    do_config_validate,
    do_config_where,
    do_data_cache_info,
    do_data_fetch,
    do_data_purge,
    do_data_verify,
    do_history_list,
    do_history_show,
    do_doctor,
    do_plugins_list,
    do_quick,
    do_signals_diff,
    do_watchlist_analyze,
    do_watchlist_list,
    do_watchlist_remove,
    do_watchlist_set,
    do_report_latest,
    do_report_open,
    do_report_view,
    do_schedule_once,
    do_schedule_run,
    do_schedule_status,
    do_version,
)
from stonks_cli.errors import ExitCodes, StonksError
from stonks_cli.logging_utils import LoggingConfig, configure_logging

app = typer.Typer(add_completion=True)
config_app = typer.Typer()
schedule_app = typer.Typer()
data_app = typer.Typer()
report_app = typer.Typer()
history_app = typer.Typer()
plugins_app = typer.Typer()
watchlist_app = typer.Typer()
signals_app = typer.Typer()
portfolio_app = typer.Typer()
paper_app = typer.Typer()
alert_app = typer.Typer()

app.add_typer(config_app, name="config")
app.add_typer(schedule_app, name="schedule")
app.add_typer(data_app, name="data")
app.add_typer(report_app, name="report")
app.add_typer(history_app, name="history")
app.add_typer(plugins_app, name="plugins")
app.add_typer(watchlist_app, name="watchlist")
app.add_typer(signals_app, name="signals")
app.add_typer(portfolio_app, name="portfolio")
app.add_typer(paper_app, name="paper")
app.add_typer(alert_app, name="alert")


@app.callback()
def _global_options(
    verbose: int = typer.Option(0, "--verbose", "-v", count=True, help="Increase logging verbosity"),
    quiet: bool = typer.Option(False, "--quiet", help="Only show errors"),
    structured_logs: bool = typer.Option(False, "--structured-logs", help="Emit JSON lines logs to stderr"),
) -> None:
    configure_logging(LoggingConfig(verbose=verbose, quiet=quiet, structured=structured_logs))


def _exit_for_error(e: Exception) -> typer.Exit:
    if isinstance(e, StonksError):
        Console().print(f"[red]Error:[/red] {e}")
        return typer.Exit(code=e.code)
    if isinstance(e, ValidationError):
        Console().print(f"[red]Bad config:[/red] {e}")
        return typer.Exit(code=ExitCodes.BAD_CONFIG)
    if isinstance(e, (FileNotFoundError, IndexError, ValueError)):
        Console().print(f"[red]Error:[/red] {e}")
        return typer.Exit(code=ExitCodes.USAGE_ERROR)
    Console().print(f"[red]Error:[/red] {e}")
    return typer.Exit(code=ExitCodes.UNKNOWN_ERROR)


@app.command()
def version() -> None:
    """Print version."""
    try:
        Console().print(do_version())
    except Exception as e:
        raise _exit_for_error(e)


@app.command()
def doctor() -> None:
    """Diagnose environment (config, data)."""
    try:
        results = do_doctor()
        for k, v in results.items():
            Console().print(f"{k}: {v}")
    except Exception as e:
        raise _exit_for_error(e)


@app.command()
def quick(
    tickers: list[str] = typer.Argument(..., help="Ticker symbol(s) (e.g., AAPL MSFT GOOG)"),
    no_color: bool = typer.Option(False, "--no-color", help="Strip color formatting for piping"),
    spark: bool = typer.Option(False, "--spark", help="Append sparkline of last 20 days"),
    detailed: bool = typer.Option(False, "--detailed", help="Include fundamental data summary"),
) -> None:
    """Quick one-liner analysis for one or more tickers."""
    from stonks_cli.formatting.oneliner import format_quick_summary
    from stonks_cli.formatting.sparkline import generate_sparkline
    from stonks_cli.formatting.numbers import format_market_cap

    try:
        results = do_quick(tickers)
        console = Console(force_terminal=not no_color, no_color=no_color)

        for result in results:
            line = format_quick_summary(
                ticker=result.ticker,
                price=result.price,
                change_pct=result.change_pct,
                action=result.action,
                confidence=result.confidence,
                use_color=not no_color,
            )
            if spark and result.prices:
                sparkline = generate_sparkline(result.prices, width=20)
                line = f"{line} {sparkline}"
            console.print(line)

            if detailed:
                # Show fundamental summary
                try:
                    from stonks_cli.data.fundamentals import fetch_fundamentals_yahoo

                    base_ticker = result.ticker.split(".")[0]
                    fundamentals = fetch_fundamentals_yahoo(base_ticker)
                    if fundamentals:
                        pe = f"P/E: {fundamentals.pe_ratio:.1f}" if fundamentals.pe_ratio else "P/E: N/A"
                        mc = f"MCap: {format_market_cap(fundamentals.market_cap)}"
                        div = f"Div: {fundamentals.dividend_yield*100:.2f}%" if fundamentals.dividend_yield else "Div: N/A"
                        range_str = ""
                        if fundamentals.fifty_two_week_low and fundamentals.fifty_two_week_high:
                            range_str = f"52w: ${fundamentals.fifty_two_week_low:.2f}-${fundamentals.fifty_two_week_high:.2f}"
                        details = f"  {pe} | {mc} | {div}"
                        if range_str:
                            details = f"{details} | {range_str}"
                        console.print(details, style="dim")
                except ImportError:
                    console.print("  [dim](yfinance not installed for fundamentals)[/dim]")
                except Exception:
                    pass
    except Exception as e:
        raise _exit_for_error(e)


@app.command()
def chart(
    ticker: str = typer.Argument(..., help="Ticker symbol (e.g., AAPL)"),
    days: int = typer.Option(90, "--days", help="Number of days to display"),
    candle: bool = typer.Option(False, "--candle", help="Display candlestick chart instead of line chart"),
    volume: bool = typer.Option(False, "--volume", help="Include volume subplot below price chart"),
    sma: str = typer.Option(None, "--sma", help="Overlay SMAs (comma-separated periods, e.g., 20,50,200)"),
    bb: bool = typer.Option(False, "--bb", help="Overlay Bollinger Bands (20-period, 2 std dev)"),
) -> None:
    """Display an ASCII price chart for a ticker."""
    try:
        sma_periods = None
        if sma:
            sma_periods = [int(p.strip()) for p in sma.split(",") if p.strip()]
        do_chart(ticker, days=days, candle=candle, volume=volume, sma_periods=sma_periods, show_bb=bb)
    except Exception as e:
        raise _exit_for_error(e)


@app.command("chart-compare")
def chart_compare(
    tickers: list[str] = typer.Argument(..., help="Ticker symbols to compare (e.g., AAPL MSFT GOOG)"),
    days: int = typer.Option(90, "--days", help="Number of days to display"),
) -> None:
    """Compare performance of multiple tickers on a normalized chart."""
    try:
        do_chart_compare(tickers, days=days)
    except Exception as e:
        raise _exit_for_error(e)


@app.command("chart-rsi")
def chart_rsi(
    ticker: str = typer.Argument(..., help="Ticker symbol (e.g., AAPL)"),
    period: int = typer.Option(14, "--period", help="RSI period"),
    days: int = typer.Option(90, "--days", help="Number of days to display"),
) -> None:
    """Display RSI indicator chart with overbought/oversold zones."""
    try:
        do_chart_rsi(ticker, period=period, days=days)
    except Exception as e:
        raise _exit_for_error(e)


@app.command()
def correlation(
    tickers: list[str] = typer.Argument(..., help="Ticker symbols (e.g., AAPL MSFT GOOG)"),
    days: int = typer.Option(252, "--days", help="Number of trading days for correlation calculation"),
) -> None:
    """Display correlation matrix for multiple tickers."""
    from rich.table import Table

    try:
        result = do_correlation(tickers, days=days)
        console = Console()

        matrix = result["matrix"]
        ticker_list = result["tickers"]

        if matrix.empty:
            console.print("[yellow]No correlation data available[/yellow]")
            return

        table = Table(title=f"Correlation Matrix ({days} days)")
        table.add_column("", style="bold")

        for t in ticker_list:
            table.add_column(t, justify="right")

        for row_ticker in ticker_list:
            row_values = []
            for col_ticker in ticker_list:
                val = matrix.loc[row_ticker, col_ticker]
                # Color based on correlation value
                if row_ticker == col_ticker:
                    cell = "[dim]1.00[/dim]"
                elif val < 0.3:
                    cell = f"[green]{val:.2f}[/green]"
                elif val > 0.7:
                    cell = f"[red]{val:.2f}[/red]"
                else:
                    cell = f"[yellow]{val:.2f}[/yellow]"
                row_values.append(cell)
            table.add_row(row_ticker, *row_values)

        console.print(table)
    except Exception as e:
        raise _exit_for_error(e)


@app.command()
def sector(
    sector_name: str = typer.Argument(..., help="Sector name (e.g., Technology, Healthcare, Financials)"),
) -> None:
    """Display sector ETF performance compared to SPY."""
    from rich.table import Table

    try:
        result = do_sector(sector_name)
        console = Console()

        table = Table(title=f"{result['sector']} ({result['etf']}) vs SPY")
        table.add_column("Period", style="cyan")
        table.add_column(result["etf"], justify="right")
        table.add_column("SPY", justify="right")
        table.add_column("Relative", justify="right")

        def fmt_pct(val: float | None) -> str:
            if val is None:
                return "N/A"
            color = "green" if val >= 0 else "red"
            return f"[{color}]{val:+.2f}%[/{color}]"

        def fmt_relative(sector_val: float | None, spy_val: float | None) -> str:
            if sector_val is None or spy_val is None:
                return "N/A"
            diff = sector_val - spy_val
            color = "green" if diff >= 0 else "red"
            return f"[{color}]{diff:+.2f}%[/{color}]"

        periods = [("Daily", "daily"), ("Weekly", "weekly"), ("Monthly", "monthly"), ("YTD", "ytd")]
        for label, key in periods:
            sector_val = result["sector_performance"][key]
            spy_val = result["spy_performance"][key]
            table.add_row(
                label,
                fmt_pct(sector_val),
                fmt_pct(spy_val),
                fmt_relative(sector_val, spy_val),
            )

        console.print(table)
    except Exception as e:
        raise _exit_for_error(e)


@app.command()
def watch(
    watchlist: str = typer.Option(None, "--watchlist", help="Start with specific watchlist"),
    refresh: int = typer.Option(60, "--refresh", help="Refresh interval in seconds"),
) -> None:
    """Launch interactive watchlist TUI with live updates."""
    try:
        do_watch(watchlist_name=watchlist, refresh_interval=refresh)
    except Exception as e:
        raise _exit_for_error(e)


@app.command()
def fundamentals(
    ticker: str = typer.Argument(..., help="Ticker symbol (e.g., AAPL)"),
    json_out: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Display fundamental data for a ticker (requires yfinance)."""
    import json

    from rich.table import Table

    from stonks_cli.formatting.numbers import format_market_cap, format_percent, format_ratio

    try:
        data = do_fundamentals(ticker, as_json=True)
        console = Console()

        if data is None:
            console.print(f"[red]No fundamental data available for {ticker}[/red]")
            return

        if json_out:
            console.print(json.dumps(data, indent=2))
            return

        table = Table(title=f"Fundamentals: {ticker}")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", justify="right")

        table.add_row("P/E Ratio", format_ratio(data.get("pe_ratio")))
        table.add_row("Forward P/E", format_ratio(data.get("forward_pe")))
        table.add_row("PEG Ratio", format_ratio(data.get("peg_ratio")))
        table.add_row("Price/Book", format_ratio(data.get("price_to_book")))
        table.add_row("Market Cap", format_market_cap(data.get("market_cap")))
        table.add_row("Enterprise Value", format_market_cap(data.get("enterprise_value")))
        table.add_row("Profit Margin", format_percent(data.get("profit_margin")))
        table.add_row("Revenue Growth (YoY)", format_percent(data.get("revenue_growth_yoy")))
        table.add_row("Earnings Growth (YoY)", format_percent(data.get("earnings_growth_yoy")))
        table.add_row("Dividend Yield", format_percent(data.get("dividend_yield")))
        table.add_row("Beta", format_ratio(data.get("beta")))
        table.add_row("52-Week High", f"${data.get('fifty_two_week_high', 0):.2f}" if data.get("fifty_two_week_high") else "N/A")
        table.add_row("52-Week Low", f"${data.get('fifty_two_week_low', 0):.2f}" if data.get("fifty_two_week_low") else "N/A")

        console.print(table)
    except Exception as e:
        raise _exit_for_error(e)


@app.command()
def news(
    ticker: str = typer.Argument(..., help="Ticker symbol (e.g., AAPL)"),
    sentiment: bool = typer.Option(False, "--sentiment", help="Show only notable sentiment headlines"),
) -> None:
    """Display recent news headlines for a ticker with sentiment."""
    from rich.table import Table

    try:
        items = do_news(ticker, notable_only=sentiment)
        console = Console()

        if not items:
            console.print(f"[yellow]No news found for {ticker}[/yellow]")
            return

        table = Table(title=f"News: {ticker}")
        table.add_column("Date", style="dim", width=12)
        table.add_column("Source", width=15)
        table.add_column("Headline")
        table.add_column("Sent", justify="center", width=6)

        for item in items[:20]:
            # Date
            date_str = item["published_date"][:10] if item.get("published_date") else "N/A"

            # Truncate headline
            headline = item["title"][:80] + "..." if len(item["title"]) > 80 else item["title"]

            # Sentiment indicator
            score = item.get("sentiment_score", 0)
            if score > 0.2:
                sent_str = "[green]+[/green]"
            elif score < -0.2:
                sent_str = "[red]-[/red]"
            else:
                sent_str = "[dim]o[/dim]"

            table.add_row(date_str, item["source"], headline, sent_str)

        console.print(table)
    except Exception as e:
        raise _exit_for_error(e)


@app.command()
def earnings(
    ticker: str = typer.Option(None, "--ticker", help="Show earnings history for specific ticker"),
    show_next: bool = typer.Option(False, "--next", help="Show only next upcoming earnings date"),
) -> None:
    """Display earnings calendar or ticker history (requires yfinance)."""
    from rich.table import Table

    try:
        data = do_earnings(ticker=ticker, show_next=show_next)
        console = Console()

        if data["mode"] == "next":
            event = data["next_earnings"]
            days = data["days_until"]
            console.print(f"[bold]{data['ticker']}[/bold] Next Earnings")
            console.print(f"Date: {event['report_date']} ({days} days)")
            console.print(f"Time: {event['report_time']}")
            if event.get("eps_estimate"):
                console.print(f"EPS Estimate: ${event['eps_estimate']:.2f}")
            return

        if data["mode"] == "history":
            events = data["events"]
            if not events:
                console.print(f"[yellow]No earnings history for {data['ticker']}[/yellow]")
                return

            table = Table(title=f"Earnings History: {data['ticker']}")
            table.add_column("Date")
            table.add_column("Time")
            table.add_column("EPS Est", justify="right")
            table.add_column("EPS Actual", justify="right")
            table.add_column("Surprise", justify="right")

            for e in events:
                eps_est = f"${e['eps_estimate']:.2f}" if e.get("eps_estimate") else "N/A"
                eps_act = f"${e['eps_actual']:.2f}" if e.get("eps_actual") else "N/A"

                surprise_str = "N/A"
                if e.get("surprise_pct") is not None:
                    s = e["surprise_pct"]
                    color = "green" if s >= 0 else "red"
                    surprise_str = f"[{color}]{s:+.1f}%[/{color}]"

                table.add_row(e["report_date"], e["report_time"], eps_est, eps_act, surprise_str)

            console.print(table)
            return

        console.print("[yellow]Use --ticker to show earnings history[/yellow]")

    except Exception as e:
        raise _exit_for_error(e)


@app.command()
def insider(
    ticker: str = typer.Argument(..., help="Ticker symbol (e.g., AAPL)"),
    days: int = typer.Option(90, "--days", help="Days to look back"),
    buys_only: bool = typer.Option(False, "--buys-only", help="Show only buy transactions"),
    sells_only: bool = typer.Option(False, "--sells-only", help="Show only sell transactions"),
) -> None:
    """Display recent insider transactions for a ticker."""
    from rich.table import Table
    from stonks_cli.formatting.numbers import format_market_cap

    try:
        transactions = do_insider(ticker, days=days, buys_only=buys_only, sells_only=sells_only)
        console = Console()

        if not transactions:
            console.print(f"[yellow]No insider transactions found for {ticker}[/yellow]")
            return

        table = Table(title=f"Insider Transactions: {ticker}")
        table.add_column("Date", style="dim")
        table.add_column("Insider")
        table.add_column("Title")
        table.add_column("Type", style="bold")
        table.add_column("Shares", justify="right")
        table.add_column("Price", justify="right")
        table.add_column("Value", justify="right")

        for t in transactions:
            trans_type = t["transaction_type"]
            if trans_type == "buy":
                type_str = "[green]BUY[/green]"
            elif trans_type == "sell":
                type_str = "[red]SELL[/red]"
            else:
                type_str = trans_type.upper()

            shares_str = f"{t['shares']:,.0f}"
            price_str = f"${t['price_per_share']:.2f}" if t.get("price_per_share") else "N/A"
            value_str = format_market_cap(t.get("total_value"))

            table.add_row(
                t["filing_date"],
                t["insider_name"],
                t["insider_title"],
                type_str,
                shares_str,
                price_str,
                value_str,
            )

        console.print(table)
    except Exception as e:
        raise _exit_for_error(e)


@watchlist_app.command("list")
def watchlist_list() -> None:
    """List configured watchlists."""
    try:
        out = do_watchlist_list()
        console = Console()
        if not out:
            console.print("No watchlists configured")
            return
        for name in sorted(out.keys()):
            tickers = out.get(name) or []
            console.print(f"{name}: {', '.join(tickers) if tickers else '-'}")
    except Exception as e:
        raise _exit_for_error(e)


@watchlist_app.command("set")
def watchlist_set(name: str = typer.Argument(...), tickers: list[str] = typer.Argument(...)) -> None:
    """Create/replace a watchlist."""
    try:
        do_watchlist_set(name, tickers)
        Console().print(f"Updated watchlist: {name}")
    except Exception as e:
        raise _exit_for_error(e)


@watchlist_app.command("remove")
def watchlist_remove(name: str = typer.Argument(...)) -> None:
    """Remove a watchlist."""
    try:
        do_watchlist_remove(name)
        Console().print(f"Removed watchlist: {name}")
    except Exception as e:
        raise _exit_for_error(e)


@watchlist_app.command("analyze")
def watchlist_analyze(
    name: str = typer.Argument(...),
    start: str | None = typer.Option(None, "--start", help="YYYY-MM-DD"),
    end: str | None = typer.Option(None, "--end", help="YYYY-MM-DD"),
    out_dir: str = typer.Option("reports", "--out-dir"),
    report_name: str | None = typer.Option(None, "--name", help="Stable report filename (e.g. report_latest.txt)"),
    json_out: bool = typer.Option(False, "--json", "--no-json", help="Write JSON output alongside the report"),
    csv_out: bool = typer.Option(False, "--csv", "--no-csv", help="Write CSV summary alongside the report"),
    sandbox: bool = typer.Option(False, "--sandbox", help="Run without persisting last-run history"),
) -> None:
    """Analyze a named watchlist."""
    try:
        artifacts = do_watchlist_analyze(
            name,
            out_dir=Path(out_dir),
            start=start,
            end=end,
            report_name=report_name,
            json_out=json_out,
            csv_out=csv_out,
            sandbox=sandbox,
        )
        Console().print(f"Wrote report: {artifacts.report_path}")
        if artifacts.json_path:
            Console().print(f"Wrote json: {artifacts.json_path}")
    except Exception as e:
        raise _exit_for_error(e)


@signals_app.command("diff")
def signals_diff() -> None:
    """Compare latest vs previous run and highlight changes."""
    try:
        from rich.table import Table

        out = do_signals_diff()
        changes = list(out.get("changes") or [])
        if not changes:
            Console().print("No changes")
            return

        table = Table(title="Signals Diff")
        table.add_column("Ticker", style="cyan")
        table.add_column("Kind")
        table.add_column("Old")
        table.add_column("New")
        table.add_column("Δconf", justify="right")

        for row in changes:
            t = str(row.get("ticker"))
            kind = str(row.get("kind"))
            old = row.get("old")
            new = row.get("new")
            delta = row.get("delta")

            def fmt_side(v) -> str:
                if v is None:
                    return "-"
                if isinstance(v, dict):
                    a = v.get("action")
                    c = v.get("confidence")
                    try:
                        c_f = float(c)
                        return f"{a} ({c_f:.2f})"
                    except Exception:
                        return f"{a}"
                return str(v)

            d_s = "-"
            try:
                if delta is not None:
                    d_s = f"{float(delta):+.2f}"
            except Exception:
                d_s = "-"

            table.add_row(t, kind, fmt_side(old), fmt_side(new), d_s)

        Console().print(table)
    except Exception as e:
        raise _exit_for_error(e)


@plugins_app.command("list")
def plugins_list() -> None:
    """Show loaded plugins and discovered strategies/providers."""
    try:
        out = do_plugins_list()
        console = Console()

        configured = list(out.get("configured") or [])
        ok = set(out.get("ok") or [])
        errors = dict(out.get("errors") or {})

        if not configured:
            console.print("No plugins configured")
        else:
            for spec in configured:
                if spec in ok:
                    console.print(f"ok: {spec}")
                elif spec in errors:
                    console.print(f"error: {spec}: {errors[spec]}")
                else:
                    console.print(f"unknown: {spec}")

        strategies = list(out.get("strategies") or [])
        provider_factories = list(out.get("provider_factories") or [])
        console.print(f"strategies: {', '.join(strategies) if strategies else '-'}")
        console.print(f"provider_factories: {', '.join(provider_factories) if provider_factories else '-'}")
    except Exception as e:
        raise _exit_for_error(e)


@config_app.command("init")
def config_init(path: str | None = typer.Option(None, "--path")) -> None:
    """Create a default config file."""
    try:
        p = Path(path).expanduser() if path else None
        out = do_config_init(p)
        Console().print(f"Created config: {out}")
    except Exception as e:
        raise _exit_for_error(e)


@config_app.command("show")
def config_show() -> None:
    """Print effective config."""
    try:
        Console().print(do_config_show())
    except Exception as e:
        raise _exit_for_error(e)


@config_app.command("where")
def config_where() -> None:
    """Print config path."""
    try:
        Console().print(str(do_config_where()))
    except Exception as e:
        raise _exit_for_error(e)


@config_app.command("set")
def config_set(field: str = typer.Argument(...), value: str = typer.Argument(...)) -> None:
    """Set a config field value (supports basic JSON parsing)."""
    try:
        import json

        parsed = value
        try:
            parsed = json.loads(value)
        except Exception:
            parsed = value
        Console().print(do_config_set(field, parsed))
    except Exception as e:
        raise _exit_for_error(e)


@config_app.command("validate")
def config_validate() -> None:
    """Validate config and show effective provider selection."""
    try:
        out = do_config_validate()
        tickers = list(out.get("tickers") or [])
        providers = dict(out.get("providers") or {})

        console = Console()
        for t in tickers:
            console.print(t)
        for t in tickers:
            p = providers.get(t)
            if p:
                console.print(f"{t}: {p}")
    except Exception as e:
        raise _exit_for_error(e)


@app.command()
def analyze(
    tickers: list[str] = typer.Argument(None),
    start: str | None = typer.Option(None, "--start", help="YYYY-MM-DD"),
    end: str | None = typer.Option(None, "--end", help="YYYY-MM-DD"),
    out_dir: str = typer.Option("reports", "--out-dir"),
    name: str | None = typer.Option(None, "--name", help="Stable report filename (e.g. report_latest.txt)"),
    json_out: bool = typer.Option(False, "--json", "--no-json", help="Write JSON output alongside the report"),
    csv_out: bool = typer.Option(False, "--csv", "--no-csv", help="Write CSV summary alongside the report"),
    sandbox: bool = typer.Option(False, "--sandbox", help="Run without persisting last-run history"),
    benchmark: str | None = typer.Option(None, "--benchmark", help="Benchmark ticker for beta calculation (e.g., SPY)"),
) -> None:
    """Analyze tickers and write a report."""
    try:
        if json_out:
            artifacts = do_analyze_artifacts(
                tickers if tickers else None,
                out_dir=Path(out_dir),
                json_out=True,
                csv_out=csv_out,
                start=start,
                end=end,
                report_name=name,
                sandbox=sandbox,
                benchmark=benchmark,
            )
            Console().print(f"Wrote report: {artifacts.report_path}")
            if artifacts.json_path:
                Console().print(f"Wrote json: {artifacts.json_path}")
            return
        do_analyze(
            tickers if tickers else None,
            out_dir=Path(out_dir),
            start=start,
            end=end,
            report_name=name,
            csv_out=csv_out,
            sandbox=sandbox,
            benchmark=benchmark,
        )
    except Exception as e:
        raise _exit_for_error(e)


@app.command()
def backtest(
    tickers: list[str] = typer.Argument(None),
    start: str | None = typer.Option(None, "--start", help="YYYY-MM-DD"),
    end: str | None = typer.Option(None, "--end", help="YYYY-MM-DD"),
    out_dir: str = typer.Option("reports", "--out-dir"),
) -> None:
    """Run a simple walk-forward backtest and write a summary report."""
    try:
        path = do_backtest(
            tickers if tickers else None,
            start=start,
            end=end,
            out_dir=Path(out_dir),
        )
        Console().print(f"Wrote backtest: {path}")
    except Exception as e:
        raise _exit_for_error(e)


@app.command()
def bench(
    tickers: list[str] = typer.Argument(None),
    iterations: int = typer.Option(5, "--iterations", min=1, max=50),
    warmup: int = typer.Option(1, "--warmup", min=0, max=10),
) -> None:
    """Run a simple multi-ticker analysis benchmark."""
    try:
        summary = do_bench(tickers if tickers else None, iterations=iterations, warmup=warmup)
        Console().print(summary)
    except Exception as e:
        raise _exit_for_error(e)


@schedule_app.command("run")
def schedule_run(
    out_dir: str = typer.Option("reports", "--out-dir"),
    name: str | None = typer.Option(None, "--name", help="Stable report filename (overwrites each run)"),
    csv_out: bool = typer.Option(False, "--csv", "--no-csv", help="Write CSV summary alongside the report"),
    sandbox: bool = typer.Option(False, "--sandbox", help="Run without persisting last-run history"),
) -> None:
    """Run the cron-like scheduler in the foreground."""
    try:
        do_schedule_run(out_dir=Path(out_dir), report_name=name, csv_out=csv_out, sandbox=sandbox)
    except Exception as e:
        raise _exit_for_error(e)


@schedule_app.command("once")
def schedule_once(
    out_dir: str = typer.Option("reports", "--out-dir"),
    sandbox: bool = typer.Option(False, "--sandbox", help="Run without persisting last-run history"),
    name: str | None = typer.Option(None, "--name", help="Stable report filename"),
    csv_out: bool = typer.Option(False, "--csv", "--no-csv", help="Write CSV summary alongside the report"),
) -> None:
    """Run one analysis+report (same as a single scheduled job)."""
    try:
        do_schedule_once(out_dir=Path(out_dir), sandbox=sandbox, report_name=name, csv_out=csv_out)
    except Exception as e:
        raise _exit_for_error(e)


@schedule_app.command("status")
def schedule_status() -> None:
    """Show cron expression and next run time (best-effort)."""
    try:
        status = do_schedule_status()
        console = Console()
        console.print(f"cron: {status.cron}")
        if status.next_run:
            console.print(f"next: {status.next_run}")
        else:
            console.print(f"next: [red]unavailable[/red] ({status.error})")
    except Exception as e:
        raise _exit_for_error(e)


@data_app.command("fetch")
def data_fetch(tickers: list[str] = typer.Argument(None)) -> None:
    """Fetch price data for tickers (populates cache)."""
    try:
        fetched = do_data_fetch(tickers if tickers else None)
        Console().print(f"Fetched {len(fetched)} tickers")
    except Exception as e:
        raise _exit_for_error(e)


@data_app.command("verify")
def data_verify(tickers: list[str] = typer.Argument(None)) -> None:
    """Verify data provider(s) for tickers."""
    try:
        results = do_data_verify(tickers if tickers else None)
        for t, status in results.items():
            Console().print(f"{t}: {status}")
    except Exception as e:
        raise _exit_for_error(e)


@data_app.command("cache-info")
def data_cache_info() -> None:
    """Show cache directory info."""
    try:
        info = do_data_cache_info()
        Console().print(f"cache_dir: {info.get('cache_dir')}")
        Console().print(f"entries: {info.get('entries')}")
        Console().print(f"size_bytes: {info.get('size_bytes')}")
        examples = list(info.get("examples") or [])
        if examples:
            Console().print(f"examples: {', '.join(str(x) for x in examples)}")
    except Exception as e:
        raise _exit_for_error(e)


@data_app.command("purge")
def data_purge(older_than_days: int | None = typer.Option(None, "--older-than-days", min=0)) -> None:
    """Purge cache entries (optionally older than N days)."""
    try:
        out = do_data_purge(older_than_days=older_than_days)
        Console().print(f"cache_dir: {out.get('cache_dir')}")
        Console().print(f"deleted: {out.get('deleted')}")
    except Exception as e:
        raise _exit_for_error(e)


@report_app.command("open")
def report_open(
    json_out: bool = typer.Option(False, "--json", help="Also print the latest JSON path if available"),
) -> None:
    """Print latest report path (if any)."""
    try:
        if json_out:
            out = do_report_latest(include_json=True)
            Console().print(str(out.get("report_path")))
            if out.get("json_path"):
                Console().print(str(out.get("json_path")))
            return
        p = do_report_open()
        Console().print(str(p))
    except Exception as e:
        raise _exit_for_error(e)


@report_app.command("latest")
def report_latest(
    json_out: bool = typer.Option(False, "--json", help="Also print the latest JSON path if available"),
) -> None:
    """Print latest report path (and optionally JSON) from state."""
    try:
        out = do_report_latest(include_json=json_out)
        Console().print(str(out.get("report_path")))
        if json_out and out.get("json_path"):
            Console().print(str(out.get("json_path")))
    except Exception as e:
        raise _exit_for_error(e)


@report_app.command("view")
def report_view(path: Path | None = typer.Argument(None)) -> None:
    """View a report (defaults to latest) in a pager when interactive."""
    try:
        out = do_report_view(path)
        text = str(out.get("text") or "")
        console = Console()
        if sys.stdout.isatty():
            with console.pager():
                console.print(text, end="")
            return
        # Non-interactive: keep it scriptable.
        sys.stdout.write(text)
    except Exception as e:
        raise _exit_for_error(e)


@history_app.command("list")
def history_list(limit: int = typer.Option(20, "--limit", min=1, max=200)) -> None:
    """List recent runs."""
    try:
        records = do_history_list(limit=limit)
        if not records:
            Console().print("No history")
            return
        for i, r in enumerate(records):
            Console().print(f"{i}: {r.started_at}  {','.join(r.tickers)}  {r.report_path}  {r.json_path}")
    except Exception as e:
        raise _exit_for_error(e)


@history_app.command("show")
def history_show(index: int = typer.Argument(..., min=0), limit: int = typer.Option(2000, "--limit", min=1, max=2000)) -> None:
    """Show details for a prior run by index (within the last --limit entries)."""
    try:
        r = do_history_show(index, limit=limit)
        Console().print(f"started_at: {r.started_at}")
        Console().print(f"tickers: {','.join(r.tickers)}")
        Console().print(f"report_path: {r.report_path}")
        Console().print(f"json_path: {r.json_path}")
    except Exception as e:
        raise _exit_for_error(e)


@portfolio_app.command("add")
def portfolio_add(
    ticker: str = typer.Argument(..., help="Ticker symbol"),
    shares: float = typer.Argument(..., help="Number of shares"),
    cost_basis: float = typer.Argument(..., help="Cost basis per share"),
    purchase_date: str = typer.Option(None, "--date", help="Purchase date (YYYY-MM-DD)"),
    notes: str = typer.Option(None, "--notes", help="Optional notes"),
) -> None:
    """Add a position to the portfolio."""
    try:
        result = do_portfolio_add(
            ticker, shares, cost_basis, purchase_date=purchase_date, notes=notes
        )
        Console().print(
            f"Added {result['shares']} shares of {result['ticker']} at ${result['cost_basis']:.2f} cost basis"
        )
    except Exception as e:
        raise _exit_for_error(e)


@portfolio_app.command("remove")
def portfolio_remove(
    ticker: str = typer.Argument(..., help="Ticker symbol"),
    shares: float = typer.Argument(..., help="Number of shares to sell"),
    sale_price: float = typer.Argument(..., help="Sale price per share"),
) -> None:
    """Remove shares from the portfolio."""
    try:
        result = do_portfolio_remove(ticker, shares, sale_price)
        gain_loss = result["realized_gain_loss"]
        pct = result["gain_loss_pct"]
        color = "green" if gain_loss >= 0 else "red"

        Console().print(
            f"Sold {result['shares_sold']} shares of {result['ticker']} at ${result['sale_price']:.2f}"
        )
        Console().print(
            f"Realized Gain/Loss: [{color}]${gain_loss:.2f} ({pct:+.2f}%)[/{color}]"
        )
    except Exception as e:
        raise _exit_for_error(e)


@portfolio_app.command("show")
def portfolio_show(
    total: bool = typer.Option(False, "--total", help="Show portfolio totals"),
) -> None:
    """Show portfolio positions."""
    from rich.table import Table, Column

    try:
        data = do_portfolio_show(include_total=total)
        positions = data["positions"]
        totals = data["totals"]

        if not positions:
            Console().print("[yellow]Portfolio is empty[/yellow]")
            return

        table = Table(title="Portfolio positions", show_footer=total)
        
        # Format totals for footer if requested
        f_ticker = "TOTAL" if total else ""
        f_shares = ""
        f_cost_basis = ""
        f_price = ""
        f_value = ""
        f_gl_dollar = ""
        f_gl_pct = ""

        if totals:
             t_cb = totals["total_cost_basis"]
             t_mv = totals["total_market_value"]
             t_gl = totals["total_gain_loss"]
             t_ret = totals["total_return_pct"]
             
             gl_color = "green" if t_gl >= 0 else "red"
             
             f_cost_basis = f"${t_cb:.2f}"
             f_value = f"${t_mv:.2f}"
             f_gl_dollar = f"[{gl_color}]${t_gl:.2f}[/{gl_color}]"
             f_gl_pct = f"[{gl_color}]{t_ret:+.2f}%[/{gl_color}]"

        table.add_column("Ticker", style="cyan", footer=f_ticker)
        table.add_column("Shares", justify="right", footer=f_shares)
        table.add_column("Cost Basis", justify="right", footer=f_cost_basis)
        table.add_column("Price", justify="right", footer=f_price)
        table.add_column("Value", justify="right", footer=f_value)
        table.add_column("G/L ($)", justify="right", footer=f_gl_dollar)
        table.add_column("G/L (%)", justify="right", footer=f_gl_pct)

        for p in positions:
            gl_color = "green" if p["gain_loss"] >= 0 else "red"
            table.add_row(
                p["ticker"],
                f"{p['shares']:.2f}",
                f"${p['cost_basis']:.2f}",
                f"${p['current_price']:.2f}",
                f"${p['market_value']:.2f}",
                f"[{gl_color}]${p['gain_loss']:.2f}[/{gl_color}]",
                f"[{gl_color}]{p['gain_loss_pct']:+.2f}%[/{gl_color}]",
            )

        Console().print(table)
    except Exception as e:
        raise _exit_for_error(e)


@portfolio_app.command("allocation")
def portfolio_allocation() -> None:
    """Show portfolio allocation."""
    from rich.table import Table

    try:
        data = do_portfolio_allocation()
        allocations = data.get("allocations", {})

        if not allocations:
           Console().print("[yellow]Portfolio is empty[/yellow]")
           return

        # Sort by percentage descending
        sorted_allocs = sorted(allocations.items(), key=lambda x: x[1], reverse=True)

        table = Table(title="Portfolio Allocation")
        table.add_column("Asset", style="cyan")
        table.add_column("Allocation", justify="right")
        table.add_column("Chart", style="bold")

        for ticker, pct in sorted_allocs:
            # Simple ascii bar chart
            bar_len = int(pct / 2)  # 50 chars for 100%
            bar = "█" * bar_len
            table.add_row(ticker, f"{pct:.2f}%", f"[blue]{bar}[/blue]")

        Console().print(table)
    except Exception as e:
        raise _exit_for_error(e)


@portfolio_app.command("history")
def portfolio_history() -> None:
    """Show portfolio transaction history."""
    from rich.table import Table

    try:
        transactions = do_portfolio_history()

        if not transactions:
           Console().print("[yellow]No transaction history[/yellow]")
           return

        table = Table(title="Transaction History")
        table.add_column("Date", style="dim")
        table.add_column("Action", style="bold")
        table.add_column("Ticker")
        table.add_column("Shares", justify="right")
        table.add_column("Price", justify="right")
        table.add_column("Value", justify="right")
        table.add_column("G/L", justify="right")

        for t in transactions:
            # t has: timestamp, action, ticker, shares, price, gain_loss (optional)
            action = t["action"].upper()
            action_color = "green" if action in ("ADD", "BUY") else "red"

            ts = t["timestamp"][:16].replace("T", " ")  # YYYY-MM-DD HH:MM
            ticker = t["ticker"]
            shares = t["shares"]
            price = t["price"]
            value = shares * price
            gain_loss = t.get("gain_loss")

            gl_str = "-"
            if gain_loss is not None:
                color = "green" if gain_loss >= 0 else "red"
                gl_str = f"[{color}]${gain_loss:.2f}[/{color}]"

            table.add_row(
                ts,
                f"[{action_color}]{action}[/{action_color}]",
                ticker,
                f"{shares:.2f}",
                f"${price:.2f}",
                f"${value:.2f}",
                gl_str,
            )

        Console().print(table)
    except Exception as e:
        raise _exit_for_error(e)


@paper_app.command("init")
def paper_init(
    cash: float = typer.Option(10000.0, "--cash", help="Initial cash balance"),
) -> None:
    """Initialize paper trading portfolio."""
    from stonks_cli.portfolio.paper import init_paper_portfolio

    try:
        p = init_paper_portfolio(starting_cash=cash)
        Console().print(f"Initialized paper portfolio with ${p.cash_balance:.2f} cash")
    except Exception as e:
        raise _exit_for_error(e)


@paper_app.command("buy")
def paper_buy_cmd(
    ticker: str = typer.Argument(..., help="Ticker symbol"),
    shares: float = typer.Argument(..., help="Number of shares"),
) -> None:
    """Buy shares in paper portfolio."""
    from stonks_cli.commands import do_paper_buy

    try:
        res = do_paper_buy(ticker, shares)
        # Res: ticker, shares, price, total_cost, cash_remaining

        Console().print(
            f"Bought {res['shares']} {res['ticker']} @ ${res['price']:.2f} "
            f"(${res['total_cost']:.2f} total). "
            f"Cash remaining: ${res['cash_remaining']:.2f}"
        )
    except Exception as e:
        raise _exit_for_error(e)


@paper_app.command("sell")
def paper_sell_cmd(
    ticker: str = typer.Argument(..., help="Ticker symbol"),
    shares: float = typer.Argument(..., help="Number of shares"),
) -> None:
    """Sell shares from paper portfolio."""
    from stonks_cli.commands import do_paper_sell

    try:
        res = do_paper_sell(ticker, shares)
        color = "green" if res["gain_loss"] >= 0 else "red"

        Console().print(
            f"Sold {res['shares']} {res['ticker']} @ ${res['price']:.2f} "
            f"(${res['proceeds']:.2f} total). "
            f"Cash remaining: ${res['cash_remaining']:.2f}"
        )
        Console().print(
            f"Realized Gain/Loss: [{color}]${res['gain_loss']:.2f} ({res['gain_loss_pct']:+.2f}%)[/{color}]"
        )
    except Exception as e:
        raise _exit_for_error(e)


@paper_app.command("status")
def paper_status() -> None:
    """Show paper portfolio status."""
    from stonks_cli.commands import do_paper_status
    from rich.table import Table

    try:
        status = do_paper_status()

        Console().print(f"Cash Balance: ${status['cash_balance']:.2f}")

        # Positions Table
        if status["positions"]:
            table = Table(title="Positions")
            table.add_column("Ticker", style="cyan")
            table.add_column("Shares", justify="right")
            table.add_column("Price", justify="right")
            table.add_column("Value", justify="right")
            table.add_column("G/L", justify="right")

            for p in status["positions"]:
                gl_color = "green" if p["gain_loss"] >= 0 else "red"
                table.add_row(
                    p["ticker"],
                    f"{p['shares']:.2f}",
                    f"${p['current_price']:.2f}",
                    f"${p['market_value']:.2f}",
                    f"[{gl_color}]${p['gain_loss']:.2f} ({p['gain_loss_pct']:+.2f}%)[/{gl_color}]",
                )
            Console().print(table)
        else:
             Console().print("[yellow]No open positions[/yellow]")

        pl_color = "green" if status["overall_pl"] >= 0 else "red"
        Console().print(f"Total Portfolio Value: ${status['total_portfolio_value']:.2f}")
        Console().print(f"Overall P&L: [{pl_color}]${status['overall_pl']:.2f} ({status['overall_pl_pct']:+.2f}%)[/{pl_color}]")

    except Exception as e:
        raise _exit_for_error(e)


@paper_app.command("reset")
def paper_reset(
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
) -> None:
    """Reset paper trading portfolio."""
    from stonks_cli.portfolio.paper import get_paper_portfolio_path, get_paper_history_path

    if not force:
        typer.confirm(
            "Are you sure you want to reset your paper portfolio? This will delete all data.",
            abort=True,
        )

    p_path = get_paper_portfolio_path()
    h_path = get_paper_history_path()

    if p_path.exists():
        p_path.unlink()
    if h_path.exists():
        h_path.unlink()

    Console().print("[green]Paper portfolio reset successfully.[/green]")


@paper_app.command("leaderboard")
def paper_leaderboard() -> None:
    """Show paper trading performance metrics."""
    from stonks_cli.commands import do_paper_leaderboard
    from rich.table import Table

    try:
        metrics = do_paper_leaderboard()

        table = Table(title="Performance Metrics")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", justify="right")

        color = "green" if metrics["total_return_pct"] >= 0 else "red"
        table.add_row("Total Return %", f"[{color}]{metrics['total_return_pct']:+.2f}%[/{color}]")
        table.add_row("Sharpe Ratio (Trade)", f"{metrics['sharpe_ratio']:.2f}")
        table.add_row("Max Drawdown", f"{metrics['max_drawdown']*100:.2f}%")
        table.add_row("Trades", str(metrics['num_trades']))
        table.add_row("Win Rate", f"{metrics['win_rate']:.1f}%")

        Console().print(table)

    except Exception as e:
        raise _exit_for_error(e)


@alert_app.command("add")
def alert_add(
    ticker: str = typer.Argument(..., help="Ticker symbol"),
    condition: str = typer.Argument(..., help="Condition type (price-above, price-below, rsi-above, rsi-below, golden-cross, death-cross, new-high-52w, new-low-52w, volume-spike, earnings-soon)"),
    threshold: float = typer.Argument(None, help="Threshold value (not required for cross/52w alerts)"),
) -> None:
    """Add a new alert."""
    from stonks_cli.commands import do_alert_add

    try:
        # Normalize condition to use underscores
        cond_normalized = condition.replace("-", "_")
        
        # Conditions that don't require a threshold
        no_threshold_conditions = {"golden_cross", "death_cross", "new_high_52w", "new_low_52w"}
        
        if cond_normalized in no_threshold_conditions:
            final_threshold = threshold if threshold is not None else 0.0
        else:
            if threshold is None:
                # Default for volume-spike is 2.0x
                if cond_normalized == "volume_spike":
                    final_threshold = 2.0
                else:
                    Console().print(f"[red]Threshold required for condition: {condition}[/red]")
                    raise typer.Exit(code=1)
            else:
                final_threshold = threshold
            
        alert = do_alert_add(ticker, cond_normalized, final_threshold)
        
        # Format confirmation message
        condition_str = cond_normalized.replace("_", " ")
        if cond_normalized in no_threshold_conditions:
            msg_val = ""
        elif "rsi" in cond_normalized:
            msg_val = f" {final_threshold:.1f}"
        elif cond_normalized == "volume_spike":
            msg_val = f" {final_threshold:.1f}x"
        elif cond_normalized == "earnings_soon":
            msg_val = f" {int(final_threshold)} days"
        else:
            msg_val = f" ${final_threshold:.2f}"
            
        Console().print(
            f"Alert created: {alert['ticker']} {condition_str}{msg_val} (ID: {alert['id'][:6]})"
        )
    except Exception as e:
        raise _exit_for_error(e)


@alert_app.command("list")
def alert_list() -> None:
    """List all alerts."""
    from rich.table import Table
    from stonks_cli.commands import do_alert_list

    try:
        alerts = do_alert_list()
        if not alerts:
            Console().print("[yellow]No alerts configured[/yellow]")
            return

        table = Table(title="Active Alerts")
        table.add_column("ID", style="dim", width=8)
        table.add_column("Ticker", style="bold")
        table.add_column("Condition")
        table.add_column("Threshold", justify="right")
        table.add_column("Status")
        table.add_column("Created", style="dim")

        for a in alerts:
            cond = a["condition_type"].replace("_", " ")
            thr = a["threshold"]
            # Formatting threshold based on condition
            if "rsi" in a["condition_type"]:
                 val_str = f"{thr:.1f}"
            else:
                 val_str = f"${thr:.2f}"
            
            status = []
            if a["enabled"]:
                status.append("[green]enabled[/green]")
            else:
                status.append("[dim]disabled[/dim]")
            
            if a.get("triggered_at"):
                status.append("[red]TRIGGERED[/red]")
            
            created = a["created_at"][:10]  # Just date

            table.add_row(
                a["id"][:6],
                a["ticker"],
                cond,
                val_str,
                ", ".join(status),
                created
            )

        Console().print(table)
    except Exception as e:
        raise _exit_for_error(e)


@alert_app.command("remove")
def alert_remove(
    alert_id: str = typer.Argument(..., help="Alert ID (or prefix)"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
) -> None:
    """Remove an alert."""
    from stonks_cli.commands import do_alert_remove, do_alert_list

    try:
        # Resolve prefix
        alerts = do_alert_list()
        matches = [a for a in alerts if a["id"].startswith(alert_id)]
        
        if len(matches) == 0:
            Console().print(f"[red]No alert found with ID prefix: {alert_id}[/red]")
            raise typer.Exit(code=1)
        
        if len(matches) > 1:
            Console().print(f"[red]Multiple alerts match prefix {alert_id}. Be more specific.[/red]")
            raise typer.Exit(code=1)
            
        target = matches[0]
        
        if not force:
            typer.confirm(
                f"Remove alert {target['id'][:6]} ({target['ticker']} {target['condition_type']} {target['threshold']})?",
                abort=True
            )

        if do_alert_remove(target["id"]):
            Console().print(f"Removed alert: {target['id'][:6]}")
        else:
            Console().print(f"[red]Failed to remove alert[/red]")
            
    except Exception as e:
        raise _exit_for_error(e)


@alert_app.command("enable")
def alert_enable(
    alert_id: str = typer.Argument(..., help="Alert ID (or prefix)"),
) -> None:
    """Enable an alert."""
    _toggle_alert(alert_id, True)


@alert_app.command("disable")
def alert_disable(
    alert_id: str = typer.Argument(..., help="Alert ID (or prefix)"),
) -> None:
    """Disable an alert."""
    _toggle_alert(alert_id, False)


def _toggle_alert(alert_id: str, enabled: bool) -> None:
    from stonks_cli.commands import do_alert_list, do_alert_toggle
    
    try:
        # Resolve prefix
        alerts = do_alert_list()
        matches = [a for a in alerts if a["id"].startswith(alert_id)]
        
        if len(matches) == 0:
            Console().print(f"[red]No alert found with ID prefix: {alert_id}[/red]")
            raise typer.Exit(code=1)
        
        if len(matches) > 1:
            Console().print(f"[red]Multiple alerts match prefix {alert_id}. Be more specific.[/red]")
            raise typer.Exit(code=1)
            
        target = matches[0]
        result = do_alert_toggle(target["id"], enabled)
        
        if result:
            status = "enabled" if enabled else "disabled"
            color = "green" if enabled else "yellow"
            Console().print(f"Alert {result['id'][:6]} [{color}]{status}[/{color}]")
        else:
             Console().print(f"[red]Failed to update alert[/red]")

    except Exception as e:
        raise _exit_for_error(e)


@alert_app.command("check")
def alert_check() -> None:
    """Check all alerts and trigger notifications for conditions met."""
    from stonks_cli.commands import do_alert_check

    try:
        triggered = do_alert_check()
        
        if not triggered:
            Console().print("[green]No alerts triggered[/green]")
            return
            
        Console().print(f"[bold red]{len(triggered)} alert(s) triggered![/bold red]")
        for a in triggered:
            cond = a["condition_type"].replace("_", " ")
            Console().print(f"  • {a['ticker']} {cond} {a['threshold']}")
            
    except Exception as e:
        raise _exit_for_error(e)


def main() -> None:
    app()
