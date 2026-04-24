use std::collections::BTreeMap;
use std::path::PathBuf;

use crate::daemon::{DaemonState, parse_side};
use crate::market::MarketEvent;
use crate::orders::{GuardedOrderInput, OrderEvent};
use crate::storage::{load_state, save_state};

pub fn handle_command(state: &mut DaemonState, line: &str) -> String {
    let trimmed = line.trim();
    if trimmed.is_empty() {
        return "ERR empty command".to_string();
    }
    let mut parts = trimmed.split_whitespace();
    let command = parts.next().unwrap_or_default().to_ascii_uppercase();
    let kv = match parse_kv(parts) {
        Ok(kv) => kv,
        Err(err) => return format!("ERR {err}"),
    };

    let outcome = match command.as_str() {
        "PING" => Ok("PONG".to_string()),
        "STATUS" => {
            let status = state.status();
            Ok(format!(
                "OK market_count={} open_order_count={}",
                status.market_count, status.open_order_count
            ))
        }
        "BOOK" => handle_book(state, &kv),
        "PRICE" => handle_price(state, &kv),
        "TICK" => handle_tick(state, &kv),
        "MINSIZE" => handle_min_size(state, &kv),
        "RESOLVE" => handle_resolve(state, &kv),
        "GUARD" => handle_guard(state, &kv),
        "ORDER" => handle_order(state, &kv),
        "FILL" => handle_fill(state, &kv),
        "TRADE" => handle_trade(state, &kv),
        "STALE" => handle_stale(state, &kv),
        "SNAPSHOT" => handle_snapshot(state, &kv),
        "SAVE" => handle_save(state, &kv),
        "LOAD" => handle_load(state, &kv),
        _ => Err(format!("unsupported command: {command}")),
    };

    match outcome {
        Ok(value) => value,
        Err(err) => format!("ERR {err}"),
    }
}

fn handle_book(state: &mut DaemonState, kv: &BTreeMap<String, String>) -> Result<String, String> {
    let token_id = required(kv, "token")?;
    let best_bid = optional_f64(kv, "bid");
    let best_ask = optional_f64(kv, "ask");
    let snapshot = state.apply_market_event(MarketEvent::BestBidAsk {
        token_id,
        best_bid,
        best_ask,
    });
    Ok(format!(
        "OK token={} midpoint={}",
        snapshot.token_id,
        display_opt(snapshot.midpoint)
    ))
}

fn handle_price(state: &mut DaemonState, kv: &BTreeMap<String, String>) -> Result<String, String> {
    let token_id = required(kv, "token")?;
    let price = required_f64(kv, "price")?;
    let snapshot = state.apply_market_event(MarketEvent::LastTradePrice { token_id, price });
    Ok(format!(
        "OK token={} last_trade_price={}",
        snapshot.token_id,
        display_opt(snapshot.last_trade_price)
    ))
}

fn handle_tick(state: &mut DaemonState, kv: &BTreeMap<String, String>) -> Result<String, String> {
    let token_id = required(kv, "token")?;
    let tick_size = required_f64(kv, "size")?;
    let snapshot = state.apply_market_event(MarketEvent::TickSizeChange {
        token_id,
        tick_size,
    });
    Ok(format!("OK token={} tick_size={}", snapshot.token_id, snapshot.tick_size))
}

fn handle_min_size(state: &mut DaemonState, kv: &BTreeMap<String, String>) -> Result<String, String> {
    let token_id = required(kv, "token")?;
    let min_order_size = required_f64(kv, "size")?;
    let snapshot = state.apply_market_event(MarketEvent::MinOrderSize {
        token_id,
        min_order_size,
    });
    Ok(format!(
        "OK token={} min_order_size={}",
        snapshot.token_id,
        display_opt(snapshot.min_order_size)
    ))
}

fn handle_resolve(
    state: &mut DaemonState,
    kv: &BTreeMap<String, String>,
) -> Result<String, String> {
    let token_id = required(kv, "token")?;
    let winner = kv.get("winner").cloned();
    let outcome = kv.get("outcome").cloned();
    let snapshot = state.apply_market_event(MarketEvent::MarketResolved {
        token_id,
        winning_token_id: winner,
        winning_outcome: outcome,
    });
    Ok(format!(
        "OK token={} resolved={} winner={}",
        snapshot.token_id,
        snapshot.resolved,
        snapshot
            .winning_token_id
            .clone()
            .unwrap_or_else(|| "-".to_string())
    ))
}

fn handle_order(state: &mut DaemonState, kv: &BTreeMap<String, String>) -> Result<String, String> {
    let now_s = required_u64(kv, "now")?;
    let input = guarded_input(kv)?;
    let record = state.register_order(&input, now_s)?;
    Ok(format!(
        "OK order_id={} price={} shares={} status={}",
        record.order_id, record.price, record.shares, record.status
    ))
}

fn handle_guard(state: &mut DaemonState, kv: &BTreeMap<String, String>) -> Result<String, String> {
    let input = guarded_input(kv)?;
    let request = state.guard_order(&input)?;
    Ok(format!(
        "OK token={} market={} side={} price={} shares={} post_only={}",
        request.token_id,
        request.market_id,
        encode_side(request.side),
        request.price,
        request.shares,
        request.post_only
    ))
}

fn guarded_input(kv: &BTreeMap<String, String>) -> Result<GuardedOrderInput, String> {
    Ok(GuardedOrderInput {
        order_id: required(kv, "id")?,
        token_id: required(kv, "token")?,
        market_id: required(kv, "market")?,
        side: parse_side(&required(kv, "side")?)?,
        price: required_f64(kv, "price")?,
        shares: required_f64(kv, "shares")?,
        post_only: required_bool(kv, "post_only")?,
    })
}

fn handle_fill(state: &mut DaemonState, kv: &BTreeMap<String, String>) -> Result<String, String> {
    let now_s = required_u64(kv, "now")?;
    let order_id = required(kv, "id")?;
    let status = kv
        .get("status")
        .cloned()
        .unwrap_or_else(|| "FILLED".to_string());
    let filled_shares = optional_f64(kv, "filled");
    let remaining_shares = optional_f64(kv, "remaining");
    match state.apply_order_event(
        OrderEvent::OrderUpdate {
            order_id: order_id.clone(),
            status,
            filled_shares,
            remaining_shares,
        },
        now_s,
    ) {
        Some(record) => Ok(format!(
            "OK order_id={} filled={} remaining={}",
            record.order_id, record.filled_shares, record.remaining_shares
        )),
        None => Err("unknown order".to_string()),
    }
}

fn handle_trade(state: &mut DaemonState, kv: &BTreeMap<String, String>) -> Result<String, String> {
    let now_s = required_u64(kv, "now")?;
    let order_id = required(kv, "id")?;
    let matched_amount = required_f64(kv, "matched")?;
    let status = kv
        .get("status")
        .cloned()
        .unwrap_or_else(|| "MATCHED".to_string());
    match state.apply_order_event(
        OrderEvent::Trade {
            order_id: order_id.clone(),
            matched_amount,
            status,
        },
        now_s,
    ) {
        Some(record) => Ok(format!(
            "OK order_id={} filled={} remaining={}",
            record.order_id, record.filled_shares, record.remaining_shares
        )),
        None => Err("unknown order".to_string()),
    }
}

fn handle_stale(state: &mut DaemonState, kv: &BTreeMap<String, String>) -> Result<String, String> {
    let now_s = required_u64(kv, "now")?;
    let max_age = required_u64(kv, "max_age")?;
    let actions = state.stale_cancels(now_s, max_age);
    let ids = actions
        .iter()
        .map(|action| action.order_id.as_str())
        .collect::<Vec<_>>()
        .join(",");
    Ok(format!(
        "OK stale_cancel_count={} order_ids={}",
        actions.len(),
        ids
    ))
}

fn handle_snapshot(
    state: &mut DaemonState,
    kv: &BTreeMap<String, String>,
) -> Result<String, String> {
    let token_id = required(kv, "token")?;
    match state.snapshot(&token_id) {
        Some(snapshot) => Ok(format!(
            "OK token={} best_bid={} best_ask={} midpoint={} resolved={}",
            snapshot.token_id,
            display_opt(snapshot.best_bid),
            display_opt(snapshot.best_ask),
            display_opt(snapshot.midpoint),
            snapshot.resolved
        )),
        None => Err("unknown token".to_string()),
    }
}

fn handle_save(state: &mut DaemonState, kv: &BTreeMap<String, String>) -> Result<String, String> {
    let path = PathBuf::from(required(kv, "path")?);
    save_state(state, &path)?;
    Ok(format!("OK saved={}", path.display()))
}

fn handle_load(state: &mut DaemonState, kv: &BTreeMap<String, String>) -> Result<String, String> {
    let path = PathBuf::from(required(kv, "path")?);
    let loaded = load_state(&path)?;
    let (market_cache, order_manager) = loaded.into_parts();
    state.replace_state(market_cache, order_manager);
    Ok(format!("OK loaded={}", path.display()))
}

fn parse_kv<'a>(parts: impl Iterator<Item = &'a str>) -> Result<BTreeMap<String, String>, String> {
    let mut out = BTreeMap::new();
    for part in parts {
        let Some((key, value)) = part.split_once('=') else {
            return Err(format!("invalid key=value pair: {part}"));
        };
        out.insert(key.to_string(), value.to_string());
    }
    Ok(out)
}

fn required(map: &BTreeMap<String, String>, key: &str) -> Result<String, String> {
    map.get(key)
        .cloned()
        .ok_or_else(|| format!("missing required key: {key}"))
}

fn required_f64(map: &BTreeMap<String, String>, key: &str) -> Result<f64, String> {
    required(map, key)?
        .parse::<f64>()
        .map_err(|_| format!("invalid float for {key}"))
}

fn optional_f64(map: &BTreeMap<String, String>, key: &str) -> Option<f64> {
    map.get(key).and_then(|value| value.parse::<f64>().ok())
}

fn required_u64(map: &BTreeMap<String, String>, key: &str) -> Result<u64, String> {
    required(map, key)?
        .parse::<u64>()
        .map_err(|_| format!("invalid integer for {key}"))
}

fn required_bool(map: &BTreeMap<String, String>, key: &str) -> Result<bool, String> {
    match required(map, key)?.to_ascii_lowercase().as_str() {
        "true" | "1" | "yes" => Ok(true),
        "false" | "0" | "no" => Ok(false),
        _ => Err(format!("invalid boolean for {key}")),
    }
}

fn display_opt(value: Option<f64>) -> String {
    value
        .map(|inner| inner.to_string())
        .unwrap_or_else(|| "-".to_string())
}

fn encode_side(side: crate::orders::ExecutionSide) -> &'static str {
    match side {
        crate::orders::ExecutionSide::Buy => "BUY",
        crate::orders::ExecutionSide::Sell => "SELL",
    }
}

#[cfg(test)]
mod tests {
    use crate::daemon::DaemonState;

    use super::handle_command;

    #[test]
    fn protocol_handles_ping_and_status() {
        let mut state = DaemonState::default();
        assert_eq!(handle_command(&mut state, "PING"), "PONG");
        assert_eq!(
            handle_command(&mut state, "STATUS"),
            "OK market_count=0 open_order_count=0"
        );
    }

    #[test]
    fn protocol_runs_book_order_and_snapshot_flow() {
        let mut state = DaemonState::default();
        let _ = handle_command(&mut state, "BOOK token=YES1 bid=0.57 ask=0.60");
        let order = handle_command(
            &mut state,
            "ORDER id=o1 token=YES1 market=m1 side=BUY price=0.58 shares=10 post_only=true now=100",
        );
        assert!(order.starts_with("OK order_id=o1"));
        let snapshot = handle_command(&mut state, "SNAPSHOT token=YES1");
        assert!(snapshot.contains("midpoint=0.585"));
    }

    #[test]
    fn protocol_handles_guard_and_stale_ids() {
        let mut state = DaemonState::default();
        let _ = handle_command(&mut state, "BOOK token=YES1 bid=0.57 ask=0.60");
        let guard = handle_command(
            &mut state,
            "GUARD id=o1 token=YES1 market=m1 side=BUY price=0.58 shares=10 post_only=true",
        );
        assert!(guard.contains("price=0.58"));
        let _ = handle_command(
            &mut state,
            "ORDER id=o1 token=YES1 market=m1 side=BUY price=0.58 shares=10 post_only=true now=100",
        );
        let stale = handle_command(&mut state, "STALE now=150 max_age=30");
        assert!(stale.contains("order_ids=o1"));
    }

    #[test]
    fn protocol_handles_trade_increment() {
        let mut state = DaemonState::default();
        let _ = handle_command(&mut state, "BOOK token=YES1 bid=0.57 ask=0.60");
        let _ = handle_command(
            &mut state,
            "ORDER id=o1 token=YES1 market=m1 side=BUY price=0.58 shares=10 post_only=true now=100",
        );
        let trade = handle_command(&mut state, "TRADE id=o1 matched=4 status=MATCHED now=105");
        assert!(trade.contains("filled=4"));
        assert!(trade.contains("remaining=6"));
    }
}
