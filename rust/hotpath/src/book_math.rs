use serde::{Deserialize, Serialize};

#[derive(Clone, Copy, Debug, PartialEq, Serialize, Deserialize)]
pub struct PriceLevel {
    pub price: f64,
    pub size: f64,
}

#[derive(Clone, Copy, Debug, PartialEq, Serialize, Deserialize)]
pub struct BuyFillEstimate {
    pub requested_notional: f64,
    pub spent_notional: f64,
    pub unfilled_notional: f64,
    pub shares: f64,
    pub avg_price: f64,
    pub worst_price: f64,
    pub payout_if_win: f64,
    pub gross_profit_if_win: f64,
    pub fully_filled: bool,
}

#[derive(Clone, Copy, Debug, PartialEq, Serialize, Deserialize)]
pub struct SellFillEstimate {
    pub requested_shares: f64,
    pub sold_shares: f64,
    pub unfilled_shares: f64,
    pub proceeds: f64,
    pub avg_price: f64,
    pub worst_price: f64,
    pub fully_filled: bool,
}

pub fn estimate_buy_fill(asks: &[PriceLevel], notional: f64) -> Option<BuyFillEstimate> {
    if notional <= 0.0 {
        return None;
    }
    let mut levels = sane_levels(asks);
    if levels.is_empty() {
        return None;
    }
    levels.sort_by(|a, b| a.price.partial_cmp(&b.price).unwrap_or(std::cmp::Ordering::Equal));

    let mut remaining = notional;
    let mut shares = 0.0;
    let mut worst_price = 0.0;
    for level in levels {
        if remaining <= 1e-9 {
            break;
        }
        let level_notional = level.price * level.size;
        if level_notional <= remaining + 1e-9 {
            shares += level.size;
            remaining -= level_notional;
            worst_price = level.price;
        } else {
            shares += remaining / level.price;
            worst_price = level.price;
            remaining = 0.0;
        }
    }

    let spent = (notional - remaining).max(0.0);
    if spent <= 0.0 || shares <= 0.0 {
        return None;
    }
    Some(BuyFillEstimate {
        requested_notional: round6(notional),
        spent_notional: round6(spent),
        unfilled_notional: round6(remaining.max(0.0)),
        shares: round6(shares),
        avg_price: round6(spent / shares),
        worst_price: round6(worst_price),
        payout_if_win: round6(shares),
        gross_profit_if_win: round6(shares - spent),
        fully_filled: remaining <= 1e-6,
    })
}

pub fn estimate_sell_fill(bids: &[PriceLevel], shares_to_sell: f64) -> Option<SellFillEstimate> {
    if shares_to_sell <= 0.0 {
        return None;
    }
    let mut levels = sane_levels(bids);
    if levels.is_empty() {
        return None;
    }
    levels.sort_by(|a, b| b.price.partial_cmp(&a.price).unwrap_or(std::cmp::Ordering::Equal));

    let mut remaining = shares_to_sell;
    let mut sold = 0.0;
    let mut proceeds = 0.0;
    let mut worst_price = 0.0;
    for level in levels {
        if remaining <= 1e-9 {
            break;
        }
        let take = remaining.min(level.size);
        sold += take;
        proceeds += take * level.price;
        remaining -= take;
        worst_price = level.price;
    }
    if sold <= 0.0 || proceeds <= 0.0 {
        return None;
    }
    Some(SellFillEstimate {
        requested_shares: round6(shares_to_sell),
        sold_shares: round6(sold),
        unfilled_shares: round6(remaining.max(0.0)),
        proceeds: round6(proceeds),
        avg_price: round6(proceeds / sold),
        worst_price: round6(worst_price),
        fully_filled: remaining <= 1e-6,
    })
}

fn sane_levels(levels: &[PriceLevel]) -> Vec<PriceLevel> {
    levels
        .iter()
        .copied()
        .filter(|level| level.price.is_finite() && level.size.is_finite() && level.price > 0.0 && level.size > 0.0)
        .collect()
}

fn round6(value: f64) -> f64 {
    (value * 1_000_000.0).round() / 1_000_000.0
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn buy_fill_walks_asks_from_cheapest_to_most_expensive() {
        let estimate = estimate_buy_fill(
            &[
                PriceLevel { price: 0.60, size: 10.0 },
                PriceLevel { price: 0.50, size: 10.0 },
            ],
            8.0,
        )
        .expect("estimate");

        assert!(estimate.fully_filled);
        assert_eq!(estimate.spent_notional, 8.0);
        assert_eq!(estimate.shares, 15.0);
        assert_eq!(estimate.avg_price, 0.533333);
        assert_eq!(estimate.worst_price, 0.6);
        assert_eq!(estimate.gross_profit_if_win, 7.0);
    }

    #[test]
    fn buy_fill_handles_partial_top_level() {
        let estimate = estimate_buy_fill(&[PriceLevel { price: 0.25, size: 100.0 }], 5.0).expect("estimate");

        assert!(estimate.fully_filled);
        assert_eq!(estimate.shares, 20.0);
        assert_eq!(estimate.avg_price, 0.25);
        assert_eq!(estimate.unfilled_notional, 0.0);
    }

    #[test]
    fn buy_fill_reports_insufficient_liquidity() {
        let estimate = estimate_buy_fill(&[PriceLevel { price: 0.50, size: 4.0 }], 5.0).expect("estimate");

        assert!(!estimate.fully_filled);
        assert_eq!(estimate.spent_notional, 2.0);
        assert_eq!(estimate.unfilled_notional, 3.0);
        assert_eq!(estimate.shares, 4.0);
    }

    #[test]
    fn sell_fill_walks_bids_from_highest_to_lowest() {
        let estimate = estimate_sell_fill(
            &[
                PriceLevel { price: 0.30, size: 10.0 },
                PriceLevel { price: 0.40, size: 10.0 },
            ],
            15.0,
        )
        .expect("estimate");

        assert!(estimate.fully_filled);
        assert_eq!(estimate.sold_shares, 15.0);
        assert_eq!(estimate.proceeds, 5.5);
        assert_eq!(estimate.avg_price, 0.366667);
        assert_eq!(estimate.worst_price, 0.3);
    }

    #[test]
    fn fill_estimates_ignore_invalid_levels() {
        let estimate = estimate_buy_fill(
            &[
                PriceLevel { price: 0.0, size: 100.0 },
                PriceLevel { price: 0.50, size: 10.0 },
            ],
            5.0,
        )
        .expect("estimate");

        assert!(estimate.fully_filled);
        assert_eq!(estimate.avg_price, 0.5);
    }
}
