use crate::market::{LiveMarketSnapshot, MarketEvent, MarketStateCache};
use crate::orders::{
    ExecutionSide, GuardedOrderInput, LiveOrderAction, LiveOrderRecord, LiveOrderRequest,
    OrderEvent, OrderManager, build_live_order_request,
};

#[derive(Clone, Debug, PartialEq)]
pub struct DaemonStatus {
    pub market_count: usize,
    pub open_order_count: usize,
}

#[derive(Default, Debug)]
pub struct DaemonState {
    market_cache: MarketStateCache,
    order_manager: OrderManager,
}

impl DaemonState {
    pub fn apply_market_event(&mut self, event: MarketEvent) -> &LiveMarketSnapshot {
        self.market_cache.apply(event)
    }

    pub fn guard_order(&self, input: &GuardedOrderInput) -> Result<LiveOrderRequest, String> {
        let snapshot = self
            .market_cache
            .get(&input.token_id)
            .ok_or_else(|| "missing market snapshot".to_string())?;
        build_live_order_request(input, snapshot)
    }

    pub fn register_order(
        &mut self,
        input: &GuardedOrderInput,
        now_s: u64,
    ) -> Result<&LiveOrderRecord, String> {
        let request = self.guard_order(input)?;
        Ok(self.order_manager.register_submitted(&request, now_s))
    }

    pub fn sync_order(&mut self, record: LiveOrderRecord) -> &LiveOrderRecord {
        let order_id = record.order_id.clone();
        self.order_manager.insert_record(record);
        self.order_manager
            .get(&order_id)
            .expect("record inserted")
    }

    pub fn apply_order_event(&mut self, event: OrderEvent, now_s: u64) -> Option<&LiveOrderRecord> {
        self.order_manager.apply_event(event, now_s)
    }

    pub fn stale_cancels(&self, now_s: u64, max_age_s: u64) -> Vec<LiveOrderAction> {
        self.order_manager.stale_cancels(now_s, max_age_s)
    }

    pub fn snapshot(&self, token_id: &str) -> Option<&LiveMarketSnapshot> {
        self.market_cache.get(token_id)
    }

    pub fn order(&self, order_id: &str) -> Option<&LiveOrderRecord> {
        self.order_manager.get(order_id)
    }

    pub fn status(&self) -> DaemonStatus {
        DaemonStatus {
            market_count: self.market_cache.len(),
            open_order_count: self.order_manager.open_count(),
        }
    }

    pub fn market_cache(&self) -> &MarketStateCache {
        &self.market_cache
    }

    pub fn order_manager(&self) -> &OrderManager {
        &self.order_manager
    }

    pub fn replace_state(&mut self, market_cache: MarketStateCache, order_manager: OrderManager) {
        self.market_cache = market_cache;
        self.order_manager = order_manager;
    }

    pub fn into_parts(self) -> (MarketStateCache, OrderManager) {
        (self.market_cache, self.order_manager)
    }
}

pub fn parse_side(raw: &str) -> Result<ExecutionSide, String> {
    match raw.to_ascii_uppercase().as_str() {
        "BUY" => Ok(ExecutionSide::Buy),
        "SELL" => Ok(ExecutionSide::Sell),
        _ => Err(format!("unsupported side: {raw}")),
    }
}

#[cfg(test)]
mod tests {
    use super::{DaemonState, parse_side};
    use crate::market::MarketEvent;
    use crate::orders::{GuardedOrderInput, OrderEvent};

    #[test]
    fn daemon_registers_order_after_book_update() {
        let mut daemon = DaemonState::default();
        daemon.apply_market_event(MarketEvent::BestBidAsk {
            token_id: "YES1".into(),
            best_bid: Some(0.57),
            best_ask: Some(0.60),
        });
        let order = daemon
            .register_order(
                &GuardedOrderInput {
                    order_id: "o1".into(),
                    token_id: "YES1".into(),
                    market_id: "m1".into(),
                    side: parse_side("BUY").unwrap(),
                    price: 0.58,
                    shares: 10.0,
                    post_only: true,
                },
                100,
            )
            .unwrap();
        assert_eq!(order.order_id, "o1");
        assert_eq!(daemon.status().open_order_count, 1);
    }

    #[test]
    fn daemon_applies_fill_event() {
        let mut daemon = DaemonState::default();
        daemon.apply_market_event(MarketEvent::BestBidAsk {
            token_id: "YES1".into(),
            best_bid: Some(0.57),
            best_ask: Some(0.60),
        });
        daemon
            .register_order(
                &GuardedOrderInput {
                    order_id: "o1".into(),
                    token_id: "YES1".into(),
                    market_id: "m1".into(),
                    side: parse_side("BUY").unwrap(),
                    price: 0.58,
                    shares: 10.0,
                    post_only: true,
                },
                100,
            )
            .unwrap();
        daemon.apply_order_event(
            OrderEvent::OrderUpdate {
                order_id: "o1".into(),
                status: "FILLED".into(),
                filled_shares: Some(10.0),
                remaining_shares: Some(0.0),
            },
            101,
        );
        let order = daemon.order("o1").unwrap();
        assert_eq!(order.remaining_shares, 0.0);
    }
}
