from __future__ import annotations

from stonks_cli.whalemirror.ingestion import (
    DEFAULT_CAPTURE_FIXTURE,
    BackoffPolicy,
    IngestionMonitor,
    build_trades_subscription,
    build_unsubscribe,
    build_user_fills_subscription,
    build_user_fundings_subscription,
    decode_ws_message,
    replay_capture_fixture,
    write_capture_jsonl,
)
from stonks_cli.whalemirror.models import TradeSide


def test_subscription_builders_match_hyperliquid_shapes():
    trades = build_trades_subscription(coin="BTC")

    assert trades == {"method": "subscribe", "subscription": {"type": "trades", "coin": "BTC"}}
    assert build_user_fills_subscription(user="0xABC", aggregate_by_time=True) == {
        "method": "subscribe",
        "subscription": {"type": "userFills", "user": "0xabc", "aggregateByTime": True},
    }
    assert build_user_fundings_subscription(user="0xABC") == {
        "method": "subscribe",
        "subscription": {"type": "userFundings", "user": "0xabc"},
    }
    assert build_unsubscribe(trades) == {"method": "unsubscribe", "subscription": {"type": "trades", "coin": "BTC"}}


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
