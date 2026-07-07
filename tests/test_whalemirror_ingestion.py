from __future__ import annotations

from stonks_cli.whalemirror.carry_storage import CarryStorage
from stonks_cli.whalemirror.ingestion import (
    DEFAULT_CAPTURE_FIXTURE,
    BackoffPolicy,
    IngestionMonitor,
    build_active_asset_ctx_subscription,
    build_all_mids_subscription,
    build_carry_capture_subscriptions,
    build_live_capture_subscriptions,
    build_trades_subscription,
    build_unsubscribe,
    build_user_fills_subscription,
    build_user_fundings_subscription,
    decode_carry_ws_message,
    decode_ws_message,
    record_carry_ws_message,
    replay_capture_fixture,
    write_capture_jsonl,
)
from stonks_cli.whalemirror.models import FundingSnapshot, TradeSide


def test_subscription_builders_match_hyperliquid_shapes():
    trades = build_trades_subscription(coin="BTC")

    assert trades == {"method": "subscribe", "subscription": {"type": "trades", "coin": "BTC"}}
    assert build_all_mids_subscription() == {"method": "subscribe", "subscription": {"type": "allMids"}}
    assert build_user_fills_subscription(user="0xABC", aggregate_by_time=True) == {
        "method": "subscribe",
        "subscription": {"type": "userFills", "user": "0xabc", "aggregateByTime": True},
    }
    assert build_user_fundings_subscription(user="0xABC") == {
        "method": "subscribe",
        "subscription": {"type": "userFundings", "user": "0xabc"},
    }
    assert build_active_asset_ctx_subscription(coin="BTC") == {
        "method": "subscribe",
        "subscription": {"type": "activeAssetCtx", "coin": "BTC"},
    }
    assert build_unsubscribe(trades) == {"method": "unsubscribe", "subscription": {"type": "trades", "coin": "BTC"}}


def test_live_capture_subscription_builder_defaults_to_perps_and_all_mids():
    subscriptions = build_live_capture_subscriptions(coins=("BTC", "ETH"), user_fill_wallets=("0xABC",))

    assert subscriptions == [
        {"method": "subscribe", "subscription": {"type": "trades", "coin": "BTC"}},
        {"method": "subscribe", "subscription": {"type": "trades", "coin": "ETH"}},
        {"method": "subscribe", "subscription": {"type": "allMids"}},
        {
            "method": "subscribe",
            "subscription": {"type": "userFills", "user": "0xabc", "aggregateByTime": False},
        },
    ]


def test_carry_capture_subscription_builder_includes_mids_and_asset_contexts():
    subscriptions = build_carry_capture_subscriptions(assets=("BTC", "ETH"))

    assert subscriptions == [
        {"method": "subscribe", "subscription": {"type": "allMids"}},
        {"method": "subscribe", "subscription": {"type": "activeAssetCtx", "coin": "BTC"}},
        {"method": "subscribe", "subscription": {"type": "activeAssetCtx", "coin": "ETH"}},
    ]


def test_decode_public_trade_emits_buyer_and_seller_records():
    trades = decode_ws_message(
        {
            "channel": "trades",
            "data": [
                {
                    "coin": "BTC",
                    "side": "B",
                    "px": "65000",
                    "sz": "0.02",
                    "hash": "0xabc",
                    "time": 1770000000000,
                    "tid": 1001,
                    "users": [
                        "0x1111111111111111111111111111111111111111",
                        "0x2222222222222222222222222222222222222222",
                    ],
                }
            ],
        }
    )

    assert len(trades) == 2
    assert trades[0].wallet == "0x1111111111111111111111111111111111111111"
    assert trades[0].side is TradeSide.BUY
    assert trades[0].market == "BTC-PERP"
    assert trades[0].notional_usd == 1300.0
    assert trades[1].wallet == "0x2222222222222222222222222222222222222222"
    assert trades[1].side is TradeSide.SELL


def test_decode_spot_trade_keeps_spot_market_identifier():
    trades = decode_ws_message(
        {
            "channel": "trades",
            "data": [
                {
                    "coin": "@107",
                    "side": "A",
                    "px": "1.25",
                    "sz": "200",
                    "hash": "0xdef",
                    "time": 1770000000500,
                    "tid": 1002,
                    "users": [
                        "0x3333333333333333333333333333333333333333",
                        "0x4444444444444444444444444444444444444444",
                    ],
                }
            ],
        }
    )

    assert trades[0].market == "@107"
    assert trades[0].asset == "@107"
    assert trades[0].notional_usd == 250.0


def test_decode_user_fills_uses_user_wallet_and_fill_side():
    trades = decode_ws_message(
        {
            "channel": "userFills",
            "data": {
                "isSnapshot": False,
                "user": "0x5555555555555555555555555555555555555555",
                "fills": [
                    {
                        "coin": "ETH",
                        "px": "3425.5",
                        "sz": "0.4",
                        "side": "A",
                        "time": 1770000001000,
                        "dir": "Close Long",
                        "closedPnl": "12.4",
                        "hash": "0xfill",
                        "oid": 99,
                        "crossed": True,
                        "fee": "0.12",
                        "tid": 2001,
                        "feeToken": "USDC",
                    }
                ],
            },
        }
    )

    assert len(trades) == 1
    assert trades[0].wallet == "0x5555555555555555555555555555555555555555"
    assert trades[0].side is TradeSide.SELL
    assert trades[0].market == "ETH-PERP"
    assert trades[0].raw["closedPnl"] == "12.4"


def test_ingestion_monitor_tracks_sequence_gaps_and_malformed_messages():
    monitor = IngestionMonitor()

    assert len(monitor.record_message('{"channel":"trades","sequence":1,"data":[]}')) == 0
    assert len(monitor.record_message('{"channel":"trades","sequence":4,"data":[]}')) == 0
    assert monitor.record_message("not-json") == []

    assert monitor.health.messages_received == 3
    assert monitor.health.dropped_messages == 2
    assert monitor.health.malformed_messages == 1
    assert monitor.health.last_sequence_by_channel["trades"] == 4


def test_ingestion_monitor_counts_non_trade_events():
    monitor = IngestionMonitor()

    trades = monitor.record_message({"channel": "allMids", "data": {"mids": {"BTC": "65000", "@107": "1.25"}}})

    assert trades == []
    assert monitor.health.messages_received == 1
    assert monitor.health.decoded_events == 1
    assert monitor.health.decoded_trades == 0


def test_decode_carry_ws_message_builds_quotes_from_all_mids():
    snapshots = decode_carry_ws_message(
        {"channel": "allMids", "data": {"mids": {"BTC": "100100", "BTC/USDC": "100000", "ETH": "3100"}}},
        received_at_utc="2026-07-02T00:00:00Z",
    )

    assert len(snapshots) == 2
    assert snapshots[0].asset == "BTC"
    assert snapshots[0].spot_mid == 100000.0
    assert snapshots[0].perp_mid == 100100.0
    assert snapshots[1].source_health == "ws_allMids_missing:spot_mid"


def test_record_carry_ws_message_persists_asset_ctx_quote_and_funding(tmp_path):
    storage = CarryStorage(tmp_path / "carry.sqlite3")

    count = record_carry_ws_message(
        {
            "channel": "activeAssetCtx",
            "data": {
                "coin": "BTC",
                "ctx": {"markPx": "100090", "oraclePx": "100050", "funding": "0.0001", "premium": "0.001"},
            },
        },
        storage=storage,
        received_at_utc="2026-07-02T00:00:00Z",
    )
    decoded = decode_carry_ws_message(
        {
            "channel": "activeAssetCtx",
            "data": {"coin": "BTC", "ctx": {"markPx": "100090", "oraclePx": "100050", "funding": "0.0001"}},
        },
        received_at_utc="2026-07-02T00:00:00Z",
    )

    assert count == 2
    assert any(isinstance(row, FundingSnapshot) for row in decoded)
    assert storage.count_rows("carry_quotes") == 1
    assert storage.count_rows("carry_funding_snapshots") == 1


def test_replay_fixture_produces_capture_output_for_attribution(tmp_path):
    trades, health = replay_capture_fixture(DEFAULT_CAPTURE_FIXTURE)
    capture_path = tmp_path / "capture.jsonl"
    write_capture_jsonl(trades, capture_path)

    assert health.messages_received == 4
    assert health.decoded_trades == 5
    assert health.dropped_messages == 1
    assert health.malformed_messages == 0
    assert "BTC-PERP" in capture_path.read_text(encoding="utf-8")


def test_backoff_policy_is_bounded():
    policy = BackoffPolicy(base_seconds=0.5, max_seconds=5.0, multiplier=2.0)

    assert [policy.delay(i) for i in range(5)] == [0.0, 0.5, 1.0, 2.0, 4.0]
    assert policy.delay(20) == 5.0
