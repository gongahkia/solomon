from __future__ import annotations

import csv
import json
from collections import defaultdict, deque
from dataclasses import asdict, dataclass
from pathlib import Path

from stonks_cli.logging_utils import log_suppressed_exception
from stonks_cli.paths import default_state_dir

_REQUIRED_TRADE_COLUMNS = {
    "maker",
    "market_id",
    "nonusdc_side",
    "maker_direction",
    "price",
    "token_amount",
}


@dataclass(frozen=True)
class WalletImportSummary:
    source_path: str
    row_count: int
    wallet_count: int
    imported_at: str
    detected_profit_column: bool


@dataclass(frozen=True)
class WalletTarget:
    wallet: str
    trades: int
    realized_pnl: float
    gross_volume: float
    win_rate: float
    closed_round_trips: int


@dataclass
class _WalletStats:
    trades: int = 0
    realized_pnl: float = 0.0
    gross_volume: float = 0.0
    closed_round_trips: int = 0
    winning_round_trips: int = 0
    explicit_profit_total: float = 0.0
    explicit_profit_count: int = 0


@dataclass
class _Lot:
    qty: float
    price: float


def _wallet_manifest_path() -> Path:
    return default_state_dir() / "polymarket_wallets.json"


def _wallet_targets_path() -> Path:
    return default_state_dir() / "polymarket_wallet_targets.json"


def _read_rows(csv_path: Path):
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = set(reader.fieldnames or [])
        missing = sorted(_REQUIRED_TRADE_COLUMNS - fieldnames)
        if missing:
            raise ValueError(f"wallet import requires columns: {', '.join(missing)}")
        yield fieldnames
        for row in reader:
            yield row


def _safe_float(value) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except Exception:
        return None


def import_wallet_trades(csv_path: Path) -> WalletImportSummary:
    path = csv_path.expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(path)

    row_count = 0
    wallets: set[str] = set()
    detected_profit = False
    rows = _read_rows(path)
    fieldnames = next(rows)
    profitish = {"profit", "pnl", "realized_pnl"}
    detected_profit = bool(fieldnames & profitish)
    for row in rows:
        row_count += 1
        maker = str(row.get("maker") or "").strip().lower()
        if maker:
            wallets.add(maker)

    from stonks_cli.polymarket.client import utc_now_iso

    summary = WalletImportSummary(
        source_path=str(path),
        row_count=row_count,
        wallet_count=len(wallets),
        imported_at=utc_now_iso(),
        detected_profit_column=detected_profit,
    )
    manifest_path = _wallet_manifest_path()
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(asdict(summary), indent=2), encoding="utf-8")
    return summary


def load_wallet_import_summary() -> WalletImportSummary | None:
    path = _wallet_manifest_path()
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return WalletImportSummary(
            source_path=str(payload.get("source_path") or ""),
            row_count=int(payload.get("row_count") or 0),
            wallet_count=int(payload.get("wallet_count") or 0),
            imported_at=str(payload.get("imported_at") or ""),
            detected_profit_column=bool(payload.get("detected_profit_column", False)),
        )
    except Exception as e:
        log_suppressed_exception(context="polymarket.wallets.load_import_summary", error=e, path=path)
        return None


def _resolve_source(csv_path: Path | None = None) -> Path:
    if csv_path is not None:
        return csv_path.expanduser().resolve()
    summary = load_wallet_import_summary()
    if summary is None or not summary.source_path:
        raise FileNotFoundError("no imported wallet trade source recorded")
    return Path(summary.source_path)


def rank_wallets(
    *,
    csv_path: Path | None = None,
    min_trades: int = 100,
    min_win_rate: float = 0.70,
    limit: int = 50,
) -> list[WalletTarget]:
    path = _resolve_source(csv_path)
    stats_by_wallet: dict[str, _WalletStats] = defaultdict(_WalletStats)
    long_books: dict[str, dict[tuple[str, str], deque[_Lot]]] = defaultdict(lambda: defaultdict(deque))
    short_books: dict[str, dict[tuple[str, str], deque[_Lot]]] = defaultdict(lambda: defaultdict(deque))

    rows = _read_rows(path)
    next(rows)  # fieldnames
    for row in rows:
        wallet = str(row.get("maker") or "").strip().lower()
        market_id = str(row.get("market_id") or "").strip()
        side = str(row.get("nonusdc_side") or "").strip()
        direction = str(row.get("maker_direction") or "").strip().upper()
        price = _safe_float(row.get("price"))
        qty = _safe_float(row.get("token_amount"))
        if not wallet or not market_id or not side or direction not in {"BUY", "SELL"} or price is None or qty is None:
            continue
        if qty <= 0:
            continue

        instrument = (market_id, side)
        stats = stats_by_wallet[wallet]
        stats.trades += 1
        stats.gross_volume += price * qty

        explicit_profit = None
        for col in ("profit", "pnl", "realized_pnl"):
            if col in row:
                explicit_profit = _safe_float(row.get(col))
                if explicit_profit is not None:
                    stats.explicit_profit_total += explicit_profit
                    stats.explicit_profit_count += 1
                    break

        if direction == "BUY":
            remaining = qty
            shorts = short_books[wallet][instrument]
            while remaining > 0 and shorts:
                lot = shorts[0]
                matched = min(remaining, lot.qty)
                pnl = (lot.price - price) * matched
                stats.realized_pnl += pnl
                stats.closed_round_trips += 1
                if pnl > 0:
                    stats.winning_round_trips += 1
                remaining -= matched
                lot.qty -= matched
                if lot.qty <= 1e-12:
                    shorts.popleft()
            if remaining > 0:
                long_books[wallet][instrument].append(_Lot(qty=remaining, price=price))
        else:
            remaining = qty
            longs = long_books[wallet][instrument]
            while remaining > 0 and longs:
                lot = longs[0]
                matched = min(remaining, lot.qty)
                pnl = (price - lot.price) * matched
                stats.realized_pnl += pnl
                stats.closed_round_trips += 1
                if pnl > 0:
                    stats.winning_round_trips += 1
                remaining -= matched
                lot.qty -= matched
                if lot.qty <= 1e-12:
                    longs.popleft()
            if remaining > 0:
                short_books[wallet][instrument].append(_Lot(qty=remaining, price=price))

    targets: list[WalletTarget] = []
    for wallet, stats in stats_by_wallet.items():
        if stats.trades < min_trades:
            continue
        if stats.explicit_profit_count > 0:
            realized = stats.explicit_profit_total
        else:
            realized = stats.realized_pnl
        if stats.closed_round_trips > 0:
            win_rate = stats.winning_round_trips / stats.closed_round_trips
        else:
            win_rate = 0.0
        if win_rate < min_win_rate:
            continue
        targets.append(
            WalletTarget(
                wallet=wallet,
                trades=stats.trades,
                realized_pnl=round(realized, 6),
                gross_volume=round(stats.gross_volume, 6),
                win_rate=round(win_rate, 6),
                closed_round_trips=stats.closed_round_trips,
            )
        )

    targets.sort(key=lambda item: (item.realized_pnl, item.gross_volume), reverse=True)
    trimmed = targets[: max(0, limit)]
    save_wallet_targets(trimmed)
    return trimmed


def save_wallet_targets(targets: list[WalletTarget]) -> None:
    path = _wallet_targets_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([asdict(target) for target in targets], indent=2),
        encoding="utf-8",
    )


def load_wallet_targets() -> list[WalletTarget]:
    path = _wallet_targets_path()
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        log_suppressed_exception(context="polymarket.wallets.load_targets", error=e, path=path)
        return []
    out: list[WalletTarget] = []
    if not isinstance(payload, list):
        return out
    for item in payload:
        if not isinstance(item, dict):
            continue
        out.append(
            WalletTarget(
                wallet=str(item.get("wallet") or ""),
                trades=int(item.get("trades") or 0),
                realized_pnl=float(item.get("realized_pnl") or 0.0),
                gross_volume=float(item.get("gross_volume") or 0.0),
                win_rate=float(item.get("win_rate") or 0.0),
                closed_round_trips=int(item.get("closed_round_trips") or 0),
            )
        )
    return out
