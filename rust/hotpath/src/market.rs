use std::collections::BTreeMap;

#[derive(Clone, Debug, PartialEq)]
pub struct LiveMarketSnapshot {
    pub token_id: String,
    pub best_bid: Option<f64>,
    pub best_ask: Option<f64>,
    pub midpoint: Option<f64>,
    pub last_trade_price: Option<f64>,
    pub tick_size: f64,
    pub min_order_size: Option<f64>,
    pub resolved: bool,
    pub winning_token_id: Option<String>,
    pub winning_outcome: Option<String>,
}

impl LiveMarketSnapshot {
    pub fn new(token_id: impl Into<String>) -> Self {
        Self {
            token_id: token_id.into(),
            best_bid: None,
            best_ask: None,
            midpoint: None,
            last_trade_price: None,
            tick_size: 0.01,
            min_order_size: None,
            resolved: false,
            winning_token_id: None,
            winning_outcome: None,
        }
    }
}

#[derive(Clone, Debug, PartialEq)]
pub enum MarketEvent {
    BestBidAsk {
        token_id: String,
        best_bid: Option<f64>,
        best_ask: Option<f64>,
    },
    LastTradePrice {
        token_id: String,
        price: f64,
    },
    TickSizeChange {
        token_id: String,
        tick_size: f64,
    },
    MinOrderSize {
        token_id: String,
        min_order_size: f64,
    },
    MarketResolved {
        token_id: String,
        winning_token_id: Option<String>,
        winning_outcome: Option<String>,
    },
}

#[derive(Default, Debug)]
pub struct MarketStateCache {
    snapshots: BTreeMap<String, LiveMarketSnapshot>,
}

impl MarketStateCache {
    pub fn apply(&mut self, event: MarketEvent) -> &LiveMarketSnapshot {
        let token_id = match &event {
            MarketEvent::BestBidAsk { token_id, .. }
            | MarketEvent::LastTradePrice { token_id, .. }
            | MarketEvent::TickSizeChange { token_id, .. }
            | MarketEvent::MinOrderSize { token_id, .. }
            | MarketEvent::MarketResolved { token_id, .. } => token_id.clone(),
        };
        let snapshot = self
            .snapshots
            .entry(token_id.clone())
            .or_insert_with(|| LiveMarketSnapshot::new(token_id.clone()));
        match event {
            MarketEvent::BestBidAsk {
                best_bid, best_ask, ..
            } => {
                snapshot.best_bid = best_bid.or(snapshot.best_bid);
                snapshot.best_ask = best_ask.or(snapshot.best_ask);
                snapshot.midpoint =
                    midpoint(snapshot.best_bid, snapshot.best_ask, snapshot.midpoint);
            }
            MarketEvent::LastTradePrice { price, .. } => {
                snapshot.last_trade_price = Some(price);
            }
            MarketEvent::TickSizeChange { tick_size, .. } => {
                if tick_size > 0.0 {
                    snapshot.tick_size = tick_size;
                }
            }
            MarketEvent::MinOrderSize { min_order_size, .. } => {
                if min_order_size > 0.0 {
                    snapshot.min_order_size = Some(min_order_size);
                }
            }
            MarketEvent::MarketResolved {
                winning_token_id,
                winning_outcome,
                ..
            } => {
                snapshot.resolved = true;
                if winning_token_id.is_some() {
                    snapshot.winning_token_id = winning_token_id;
                }
                if winning_outcome.is_some() {
                    snapshot.winning_outcome = winning_outcome;
                }
            }
        }
        let key = snapshot.token_id.clone();
        self.snapshots.get(&key).expect("snapshot exists")
    }

    pub fn get(&self, token_id: &str) -> Option<&LiveMarketSnapshot> {
        self.snapshots.get(token_id)
    }

    pub fn len(&self) -> usize {
        self.snapshots.len()
    }

    pub fn iter(&self) -> impl Iterator<Item = (&String, &LiveMarketSnapshot)> {
        self.snapshots.iter()
    }

    pub fn insert_snapshot(&mut self, snapshot: LiveMarketSnapshot) {
        self.snapshots.insert(snapshot.token_id.clone(), snapshot);
    }
}

fn midpoint(best_bid: Option<f64>, best_ask: Option<f64>, fallback: Option<f64>) -> Option<f64> {
    match (best_bid, best_ask) {
        (Some(bid), Some(ask)) => Some(round8((bid + ask) / 2.0)),
        (Some(bid), None) => Some(bid),
        (None, Some(ask)) => Some(ask),
        (None, None) => fallback,
    }
}

fn round8(value: f64) -> f64 {
    (value * 100_000_000.0).round() / 100_000_000.0
}

#[cfg(test)]
mod tests {
    use super::{MarketEvent, MarketStateCache};

    #[test]
    fn cache_updates_midpoint() {
        let mut cache = MarketStateCache::default();
        let snapshot = cache.apply(MarketEvent::BestBidAsk {
            token_id: "YES1".into(),
            best_bid: Some(0.41),
            best_ask: Some(0.43),
        });
        assert_eq!(snapshot.midpoint, Some(0.42));
    }

    #[test]
    fn cache_tracks_resolution_metadata() {
        let mut cache = MarketStateCache::default();
        let snapshot = cache.apply(MarketEvent::MarketResolved {
            token_id: "YES1".into(),
            winning_token_id: Some("YES1".into()),
            winning_outcome: Some("YES".into()),
        });
        assert!(snapshot.resolved);
        assert_eq!(snapshot.winning_token_id.as_deref(), Some("YES1"));
        assert_eq!(snapshot.winning_outcome.as_deref(), Some("YES"));
    }
}
