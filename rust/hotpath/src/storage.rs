use std::fs;
use std::path::Path;

use crate::daemon::DaemonState;
use crate::market::{LiveMarketSnapshot, MarketStateCache};
use crate::orders::{ExecutionSide, LiveOrderRecord, OrderManager};

pub fn save_state(state: &DaemonState, path: &Path) -> Result<(), String> {
    let mut lines: Vec<String> = Vec::new();
    for (_, snapshot) in state.market_cache().iter() {
        lines.push(format!(
            "M\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}",
            snapshot.token_id,
            encode_opt_f64(snapshot.best_bid),
            encode_opt_f64(snapshot.best_ask),
            encode_opt_f64(snapshot.midpoint),
            encode_opt_f64(snapshot.last_trade_price),
            snapshot.tick_size,
            encode_opt_f64(snapshot.min_order_size),
            snapshot.resolved,
            encode_opt_str(snapshot.winning_token_id.as_deref()),
            encode_opt_str(snapshot.winning_outcome.as_deref()),
        ));
    }
    for (_, record) in state.order_manager().iter() {
        lines.push(format!(
            "O\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}",
            record.order_id,
            record.token_id,
            record.market_id,
            encode_side(record.side),
            record.price,
            record.shares,
            record.status,
            record.created_at_s,
            record.updated_at_s,
            record.remaining_shares,
            record.filled_shares,
        ));
    }
    fs::write(path, lines.join("\n")).map_err(|err| err.to_string())
}

pub fn load_state(path: &Path) -> Result<DaemonState, String> {
    let text = fs::read_to_string(path).map_err(|err| err.to_string())?;
    let mut market_cache = MarketStateCache::default();
    let mut order_manager = OrderManager::default();
    for line in text.lines() {
        let line = line.trim();
        if line.is_empty() {
            continue;
        }
        let fields: Vec<&str> = line.split('\t').collect();
        match fields.first().copied() {
            Some("M") => {
                if fields.len() != 11 {
                    return Err(format!("invalid market line: {line}"));
                }
                market_cache.insert_snapshot(LiveMarketSnapshot {
                    token_id: fields[1].to_string(),
                    best_bid: decode_opt_f64(fields[2])?,
                    best_ask: decode_opt_f64(fields[3])?,
                    midpoint: decode_opt_f64(fields[4])?,
                    last_trade_price: decode_opt_f64(fields[5])?,
                    tick_size: fields[6]
                        .parse::<f64>()
                        .map_err(|_| format!("invalid tick_size: {line}"))?,
                    min_order_size: decode_opt_f64(fields[7])?,
                    resolved: fields[8]
                        .parse::<bool>()
                        .map_err(|_| format!("invalid resolved flag: {line}"))?,
                    winning_token_id: decode_opt_string(fields[9]),
                    winning_outcome: decode_opt_string(fields[10]),
                });
            }
            Some("O") => {
                if fields.len() != 12 {
                    return Err(format!("invalid order line: {line}"));
                }
                order_manager.insert_record(LiveOrderRecord {
                    order_id: fields[1].to_string(),
                    token_id: fields[2].to_string(),
                    market_id: fields[3].to_string(),
                    side: decode_side(fields[4])?,
                    price: fields[5]
                        .parse::<f64>()
                        .map_err(|_| format!("invalid price: {line}"))?,
                    shares: fields[6]
                        .parse::<f64>()
                        .map_err(|_| format!("invalid shares: {line}"))?,
                    status: fields[7].to_string(),
                    created_at_s: fields[8]
                        .parse::<u64>()
                        .map_err(|_| format!("invalid created_at_s: {line}"))?,
                    updated_at_s: fields[9]
                        .parse::<u64>()
                        .map_err(|_| format!("invalid updated_at_s: {line}"))?,
                    remaining_shares: fields[10]
                        .parse::<f64>()
                        .map_err(|_| format!("invalid remaining_shares: {line}"))?,
                    filled_shares: fields[11]
                        .parse::<f64>()
                        .map_err(|_| format!("invalid filled_shares: {line}"))?,
                });
            }
            _ => return Err(format!("invalid record prefix: {line}")),
        }
    }
    let mut state = DaemonState::default();
    state.replace_state(market_cache, order_manager);
    Ok(state)
}

fn encode_opt_f64(value: Option<f64>) -> String {
    value
        .map(|inner| inner.to_string())
        .unwrap_or_else(|| "-".to_string())
}

fn decode_opt_f64(raw: &str) -> Result<Option<f64>, String> {
    if raw == "-" {
        return Ok(None);
    }
    raw.parse::<f64>()
        .map(Some)
        .map_err(|_| format!("invalid optional float: {raw}"))
}

fn encode_opt_str(value: Option<&str>) -> String {
    value.unwrap_or("-").to_string()
}

fn decode_opt_string(raw: &str) -> Option<String> {
    if raw == "-" {
        None
    } else {
        Some(raw.to_string())
    }
}

fn encode_side(side: ExecutionSide) -> &'static str {
    match side {
        ExecutionSide::Buy => "BUY",
        ExecutionSide::Sell => "SELL",
    }
}

fn decode_side(raw: &str) -> Result<ExecutionSide, String> {
    match raw {
        "BUY" => Ok(ExecutionSide::Buy),
        "SELL" => Ok(ExecutionSide::Sell),
        _ => Err(format!("invalid side: {raw}")),
    }
}

#[cfg(test)]
mod tests {
    use std::path::PathBuf;

    use crate::daemon::DaemonState;
    use crate::market::MarketEvent;
    use crate::orders::GuardedOrderInput;

    use super::{load_state, save_state};

    #[test]
    fn save_and_load_round_trip() {
        let mut state = DaemonState::default();
        state.apply_market_event(MarketEvent::BestBidAsk {
            token_id: "YES1".into(),
            best_bid: Some(0.57),
            best_ask: Some(0.60),
        });
        state
            .register_order(
                &GuardedOrderInput {
                    order_id: "o1".into(),
                    token_id: "YES1".into(),
                    market_id: "m1".into(),
                    side: crate::orders::ExecutionSide::Buy,
                    price: 0.58,
                    shares: 10.0,
                    post_only: true,
                },
                100,
            )
            .unwrap();
        let mut path = std::env::temp_dir();
        path.push("stonks-rust-hotpath-roundtrip.txt");
        save_state(&state, &PathBuf::from(&path)).unwrap();
        let loaded = load_state(&PathBuf::from(&path)).unwrap();
        assert_eq!(loaded.status().market_count, 1);
        assert_eq!(loaded.status().open_order_count, 1);
        let _ = std::fs::remove_file(path);
    }
}
