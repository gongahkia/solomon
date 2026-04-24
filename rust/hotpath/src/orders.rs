use std::collections::BTreeMap;

use crate::market::LiveMarketSnapshot;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ExecutionSide {
    Buy,
    Sell,
}

#[derive(Clone, Debug, PartialEq)]
pub struct GuardedOrderInput {
    pub order_id: String,
    pub token_id: String,
    pub market_id: String,
    pub side: ExecutionSide,
    pub price: f64,
    pub shares: f64,
    pub post_only: bool,
}

#[derive(Clone, Debug, PartialEq)]
pub struct LiveOrderRequest {
    pub order_id: String,
    pub token_id: String,
    pub market_id: String,
    pub side: ExecutionSide,
    pub price: f64,
    pub shares: f64,
    pub tick_size: f64,
    pub post_only: bool,
}

#[derive(Clone, Debug, PartialEq)]
pub struct LiveOrderRecord {
    pub order_id: String,
    pub token_id: String,
    pub market_id: String,
    pub side: ExecutionSide,
    pub price: f64,
    pub shares: f64,
    pub status: String,
    pub created_at_s: u64,
    pub updated_at_s: u64,
    pub remaining_shares: f64,
    pub filled_shares: f64,
}

#[derive(Clone, Debug, PartialEq)]
pub struct LiveOrderAction {
    pub action: String,
    pub order_id: String,
    pub token_id: String,
    pub reason: String,
}

#[derive(Clone, Debug, PartialEq)]
pub enum OrderEvent {
    OrderUpdate {
        order_id: String,
        status: String,
        filled_shares: Option<f64>,
        remaining_shares: Option<f64>,
    },
    Trade {
        order_id: String,
        matched_amount: f64,
        status: String,
    },
}

#[derive(Default, Debug)]
pub struct OrderManager {
    records: BTreeMap<String, LiveOrderRecord>,
}

impl OrderManager {
    pub fn register_submitted(
        &mut self,
        request: &LiveOrderRequest,
        now_s: u64,
    ) -> &LiveOrderRecord {
        let record = LiveOrderRecord {
            order_id: request.order_id.clone(),
            token_id: request.token_id.clone(),
            market_id: request.market_id.clone(),
            side: request.side,
            price: request.price,
            shares: request.shares,
            status: "OPEN".to_string(),
            created_at_s: now_s,
            updated_at_s: now_s,
            remaining_shares: request.shares,
            filled_shares: 0.0,
        };
        self.records.insert(record.order_id.clone(), record);
        self.records
            .get(&request.order_id)
            .expect("record inserted")
    }

    pub fn apply_event(&mut self, event: OrderEvent, now_s: u64) -> Option<&LiveOrderRecord> {
        match event {
            OrderEvent::OrderUpdate {
                order_id,
                status,
                filled_shares,
                remaining_shares,
            } => {
                let record = self.records.get_mut(&order_id)?;
                record.status = status;
                record.updated_at_s = now_s;
                if let Some(filled) = filled_shares {
                    record.filled_shares = filled;
                }
                if let Some(remaining) = remaining_shares {
                    record.remaining_shares = remaining;
                } else if filled_shares.is_some() {
                    record.remaining_shares = round8(record.shares - record.filled_shares).max(0.0);
                }
                self.records.get(&order_id)
            }
            OrderEvent::Trade {
                order_id,
                matched_amount,
                status,
            } => {
                let record = self.records.get_mut(&order_id)?;
                record.status = status;
                record.updated_at_s = now_s;
                record.filled_shares =
                    round8((record.filled_shares + matched_amount).min(record.shares));
                record.remaining_shares = round8((record.shares - record.filled_shares).max(0.0));
                self.records.get(&order_id)
            }
        }
    }

    pub fn stale_cancels(&self, now_s: u64, max_age_s: u64) -> Vec<LiveOrderAction> {
        self.records
            .values()
            .filter(|record| is_live(record))
            .filter(|record| now_s.saturating_sub(record.created_at_s) >= max_age_s)
            .map(|record| LiveOrderAction {
                action: "CANCEL".to_string(),
                order_id: record.order_id.clone(),
                token_id: record.token_id.clone(),
                reason: "stale_open_order".to_string(),
            })
            .collect()
    }

    pub fn open_count(&self) -> usize {
        self.records
            .values()
            .filter(|record| is_live(record))
            .count()
    }

    pub fn get(&self, order_id: &str) -> Option<&LiveOrderRecord> {
        self.records.get(order_id)
    }

    pub fn iter(&self) -> impl Iterator<Item = (&String, &LiveOrderRecord)> {
        self.records.iter()
    }

    pub fn insert_record(&mut self, record: LiveOrderRecord) {
        self.records.insert(record.order_id.clone(), record);
    }
}

pub fn build_live_order_request(
    input: &GuardedOrderInput,
    snapshot: &LiveMarketSnapshot,
) -> Result<LiveOrderRequest, String> {
    if input.token_id != snapshot.token_id {
        return Err("snapshot token does not match order token".to_string());
    }
    if snapshot.resolved {
        return Err("market is already resolved".to_string());
    }
    if input.shares <= 0.0 {
        return Err("shares must be positive".to_string());
    }
    if let Some(min_size) = snapshot.min_order_size {
        if input.shares < min_size {
            return Err("order size is below venue minimum".to_string());
        }
    }
    let tick_size = snapshot.tick_size;
    if tick_size <= 0.0 {
        return Err("tick_size must be positive".to_string());
    }
    let price = normalize_price_to_tick(input.price, input.side, tick_size)?;
    if input.post_only && is_marketable(input.side, price, snapshot) {
        return Err("post-only live order would cross the spread".to_string());
    }
    Ok(LiveOrderRequest {
        order_id: input.order_id.clone(),
        token_id: input.token_id.clone(),
        market_id: input.market_id.clone(),
        side: input.side,
        price,
        shares: round8(input.shares),
        tick_size,
        post_only: input.post_only,
    })
}

pub fn normalize_price_to_tick(
    price: f64,
    side: ExecutionSide,
    tick_size: f64,
) -> Result<f64, String> {
    if tick_size <= 0.0 {
        return Err("tick_size must be positive".to_string());
    }
    if !(0.0..1.0).contains(&price) {
        return Err("price must be between 0 and 1".to_string());
    }
    let ratio = price / tick_size;
    let snapped = match side {
        ExecutionSide::Buy => ratio.floor() * tick_size,
        ExecutionSide::Sell => ratio.ceil() * tick_size,
    };
    Ok(round8(snapped.clamp(tick_size, 1.0 - tick_size)))
}

fn is_marketable(side: ExecutionSide, price: f64, snapshot: &LiveMarketSnapshot) -> bool {
    match side {
        ExecutionSide::Buy => snapshot.best_ask.is_some_and(|ask| price >= ask),
        ExecutionSide::Sell => snapshot.best_bid.is_some_and(|bid| price <= bid),
    }
}

fn round8(value: f64) -> f64 {
    (value * 100_000_000.0).round() / 100_000_000.0
}

fn is_live(record: &LiveOrderRecord) -> bool {
    if record.remaining_shares <= 0.0 {
        return false;
    }
    !matches!(
        record.status.as_str(),
        "FILLED" | "CANCELLED" | "FAILED" | "CONFIRMED" | "MINED"
    )
}

#[cfg(test)]
mod tests {
    use crate::market::LiveMarketSnapshot;

    use super::{
        ExecutionSide, GuardedOrderInput, OrderEvent, OrderManager, build_live_order_request,
        normalize_price_to_tick,
    };

    #[test]
    fn normalize_price_is_side_aware() {
        assert_eq!(
            normalize_price_to_tick(0.537, ExecutionSide::Buy, 0.01).unwrap(),
            0.53
        );
        assert_eq!(
            normalize_price_to_tick(0.537, ExecutionSide::Sell, 0.01).unwrap(),
            0.54
        );
    }

    #[test]
    fn guarded_request_rejects_crossing_post_only_buy() {
        let snapshot = LiveMarketSnapshot {
            best_bid: Some(0.57),
            best_ask: Some(0.60),
            ..LiveMarketSnapshot::new("YES1")
        };
        let input = GuardedOrderInput {
            order_id: "o1".into(),
            token_id: "YES1".into(),
            market_id: "m1".into(),
            side: ExecutionSide::Buy,
            price: 0.61,
            shares: 10.0,
            post_only: true,
        };
        let err = build_live_order_request(&input, &snapshot).unwrap_err();
        assert!(err.contains("cross"));
    }

    #[test]
    fn guarded_request_rejects_resolved_market() {
        let mut snapshot = LiveMarketSnapshot::new("YES1");
        snapshot.resolved = true;
        let input = GuardedOrderInput {
            order_id: "o1".into(),
            token_id: "YES1".into(),
            market_id: "m1".into(),
            side: ExecutionSide::Buy,
            price: 0.58,
            shares: 10.0,
            post_only: true,
        };
        let err = build_live_order_request(&input, &snapshot).unwrap_err();
        assert!(err.contains("resolved"));
    }

    #[test]
    fn order_manager_tracks_partial_fill_and_stale_cancel() {
        let mut manager = OrderManager::default();
        let request = build_live_order_request(
            &GuardedOrderInput {
                order_id: "o1".into(),
                token_id: "YES1".into(),
                market_id: "m1".into(),
                side: ExecutionSide::Buy,
                price: 0.58,
                shares: 10.0,
                post_only: true,
            },
            &LiveMarketSnapshot {
                best_bid: Some(0.57),
                best_ask: Some(0.60),
                ..LiveMarketSnapshot::new("YES1")
            },
        )
        .unwrap();
        manager.register_submitted(&request, 100);
        manager.apply_event(
            OrderEvent::Trade {
                order_id: "o1".into(),
                matched_amount: 4.0,
                status: "MATCHED".into(),
            },
            110,
        );
        let record = manager.get("o1").unwrap();
        assert_eq!(record.filled_shares, 4.0);
        assert_eq!(record.remaining_shares, 6.0);
        let actions = manager.stale_cancels(140, 30);
        assert_eq!(actions.len(), 1);
        assert_eq!(actions[0].order_id, "o1");
    }
}
