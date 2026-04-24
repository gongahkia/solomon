use std::collections::{BTreeMap, HashMap, HashSet, VecDeque};
use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::thread;
use std::time::Duration;

use chrono::{DateTime, Utc};
use reqwest::blocking::Client;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};

const GAMMA_URL: &str = "https://gamma-api.polymarket.com/markets";
const CLOB_BOOK_URL: &str = "https://clob.polymarket.com/book";

#[derive(Debug, Default, Deserialize)]
pub struct ControlRequest {
    #[serde(default)]
    pub state_dir: String,
    #[serde(default)]
    pub config: ControlConfig,
    #[serde(default)]
    pub args: Value,
}

#[derive(Clone, Debug, Deserialize)]
pub struct ControlConfig {
    #[serde(default = "default_true")]
    pub paper: bool,
    #[serde(default = "default_scanner_limit")]
    pub scanner_limit: usize,
    #[serde(default = "default_min_market_liquidity")]
    pub min_market_liquidity_usd: f64,
    #[serde(default = "default_min_book_depth")]
    pub min_book_depth_usd: f64,
    #[serde(default = "default_min_hours")]
    pub min_hours_to_resolution: f64,
    #[serde(default = "default_max_hours")]
    pub max_hours_to_resolution: f64,
    #[serde(default = "default_true")]
    pub require_active: bool,
    #[serde(default)]
    pub allowed_market_keywords: Vec<String>,
    #[serde(default)]
    pub blocked_market_keywords: Vec<String>,
    #[serde(default)]
    pub allowed_market_slugs: Vec<String>,
    #[serde(default)]
    pub blocked_market_slugs: Vec<String>,
    #[serde(default)]
    pub crypto_only: bool,
    #[serde(default)]
    pub block_sports: bool,
    #[serde(default)]
    pub target_wallet_addresses: Vec<String>,
    #[serde(default)]
    pub auto_trade_enabled: bool,
    #[serde(default = "default_auto_trade_min_score")]
    pub auto_trade_min_score: f64,
    #[serde(default = "default_auto_trade_min_wallets")]
    pub auto_trade_min_target_wallets: usize,
    #[serde(default = "default_true")]
    pub consensus_enabled: bool,
    #[serde(default = "default_consensus_min_buy_votes")]
    pub consensus_min_buy_votes: usize,
    #[serde(default = "default_consensus_single_vote_fraction")]
    pub consensus_single_vote_fraction: f64,
    #[serde(default = "default_consensus_arbitrage_min_deviation_bps")]
    pub consensus_arbitrage_min_deviation_bps: f64,
    #[serde(default = "default_max_position_fraction")]
    pub max_position_fraction: f64,
    #[serde(default = "default_min_cash_reserve_fraction")]
    pub min_cash_reserve_fraction: f64,
    #[serde(default = "default_max_open_positions")]
    pub max_open_positions: usize,
    #[serde(default = "default_take_profit")]
    pub take_profit_price_delta: f64,
    #[serde(default = "default_stop_loss")]
    pub stop_loss_price_delta: f64,
    #[serde(default = "default_stale_hours")]
    pub stale_position_hours: f64,
    #[serde(default)]
    pub max_market_notional: f64,
    #[serde(default = "default_max_live_open_orders")]
    pub max_live_open_orders: usize,
    #[serde(default = "default_true")]
    pub live_post_only: bool,
    #[serde(default = "default_live_order_max_age_seconds")]
    pub live_order_max_age_seconds: usize,
    #[serde(default = "default_live_min_order_notional")]
    pub live_min_order_notional_usd: f64,
    #[serde(default)]
    pub max_daily_loss: f64,
    #[serde(default = "default_live_require_armed_env")]
    pub live_require_armed_env: bool,
    #[serde(default = "default_live_armed_env")]
    pub live_armed_env: String,
    #[serde(default = "default_loop_interval_ms")]
    pub loop_interval_ms: u64,
    #[serde(default)]
    pub auto_exit_enabled: bool,
    #[serde(default = "default_paper_starting_cash")]
    pub paper_starting_cash: f64,
}

impl Default for ControlConfig {
    fn default() -> Self {
        Self {
            paper: true,
            scanner_limit: default_scanner_limit(),
            min_market_liquidity_usd: default_min_market_liquidity(),
            min_book_depth_usd: default_min_book_depth(),
            min_hours_to_resolution: default_min_hours(),
            max_hours_to_resolution: default_max_hours(),
            require_active: true,
            allowed_market_keywords: Vec::new(),
            blocked_market_keywords: Vec::new(),
            allowed_market_slugs: Vec::new(),
            blocked_market_slugs: Vec::new(),
            crypto_only: false,
            block_sports: false,
            target_wallet_addresses: Vec::new(),
            auto_trade_enabled: false,
            auto_trade_min_score: default_auto_trade_min_score(),
            auto_trade_min_target_wallets: default_auto_trade_min_wallets(),
            consensus_enabled: true,
            consensus_min_buy_votes: default_consensus_min_buy_votes(),
            consensus_single_vote_fraction: default_consensus_single_vote_fraction(),
            consensus_arbitrage_min_deviation_bps: default_consensus_arbitrage_min_deviation_bps(),
            max_position_fraction: default_max_position_fraction(),
            min_cash_reserve_fraction: default_min_cash_reserve_fraction(),
            max_open_positions: default_max_open_positions(),
            take_profit_price_delta: default_take_profit(),
            stop_loss_price_delta: default_stop_loss(),
            stale_position_hours: default_stale_hours(),
            max_market_notional: 0.0,
            max_live_open_orders: default_max_live_open_orders(),
            live_post_only: true,
            live_order_max_age_seconds: default_live_order_max_age_seconds(),
            live_min_order_notional_usd: default_live_min_order_notional(),
            max_daily_loss: 0.0,
            live_require_armed_env: true,
            live_armed_env: default_live_armed_env(),
            loop_interval_ms: default_loop_interval_ms(),
            auto_exit_enabled: true,
            paper_starting_cash: default_paper_starting_cash(),
        }
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct MarketToken {
    pub token_id: String,
    pub outcome: Option<String>,
    pub price: Option<f64>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct PolymarketMarket {
    pub market_id: String,
    pub question: String,
    pub slug: Option<String>,
    pub condition_id: Option<String>,
    pub active: Option<bool>,
    pub closed: Option<bool>,
    pub liquidity_usd: Option<f64>,
    pub volume_usd: Option<f64>,
    pub end_date_iso: Option<String>,
    pub tokens: Vec<MarketToken>,
    #[serde(default)]
    pub raw: Value,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct BookLevel {
    pub price: f64,
    pub size: f64,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct OrderBook {
    pub token_id: String,
    pub bids: Vec<BookLevel>,
    pub asks: Vec<BookLevel>,
    pub midpoint: Option<f64>,
    pub best_bid: Option<f64>,
    pub best_ask: Option<f64>,
    #[serde(default)]
    pub raw: Value,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct MarketScan {
    pub market_id: String,
    pub slug: Option<String>,
    pub question: String,
    pub token_id: Option<String>,
    pub outcome: Option<String>,
    pub midpoint: Option<f64>,
    pub bids_depth_usd: f64,
    pub asks_depth_usd: f64,
    pub liquidity_usd: Option<f64>,
    pub volume_usd: Option<f64>,
    pub hours_to_resolution: Option<f64>,
    pub complement_deviation_bps: Option<f64>,
    pub score: f64,
    pub status: String,
    pub reasons: Vec<String>,
    #[serde(default)]
    pub target_wallet_count: usize,
    #[serde(default)]
    pub target_trade_count: usize,
    #[serde(default)]
    pub target_net_volume: f64,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct RuntimeStatus {
    pub mode: String,
    pub state: String,
    pub paper: bool,
    pub last_scan_at: Option<String>,
    pub last_scan_count: usize,
    pub last_pass_count: usize,
    pub open_positions: usize,
    pub last_actions: Vec<String>,
    pub last_error: Option<String>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct PaperPosition {
    pub token_id: String,
    pub market_id: String,
    pub slug: Option<String>,
    pub outcome: Option<String>,
    pub shares: f64,
    pub avg_price: f64,
    pub opened_at: String,
    pub target_price: Option<f64>,
    pub stop_price: Option<f64>,
    pub thesis: Option<String>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct PaperTrade {
    pub ts: String,
    pub action: String,
    pub token_id: String,
    pub market_id: String,
    pub slug: Option<String>,
    pub outcome: Option<String>,
    pub shares: f64,
    pub price: f64,
    pub notional: f64,
    pub realized_pnl: Option<f64>,
    pub reason: Option<String>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct PaperAccount {
    pub cash: f64,
    pub realized_pnl: f64,
    pub positions: Vec<PaperPosition>,
    pub trades: Vec<PaperTrade>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct WalletImportSummary {
    pub source_path: String,
    pub row_count: usize,
    pub wallet_count: usize,
    pub imported_at: String,
    pub detected_profit_column: bool,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct WalletTarget {
    pub wallet: String,
    pub trades: usize,
    pub realized_pnl: f64,
    pub gross_volume: f64,
    pub win_rate: f64,
    pub closed_round_trips: usize,
    #[serde(default)]
    pub source: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct WalletMarketSignal {
    pub market_id: String,
    pub outcome: String,
    pub wallet_count: usize,
    pub trade_count: usize,
    pub net_volume: f64,
    pub gross_volume: f64,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct StrategyVote {
    pub agent: String,
    pub action: String,
    pub confidence: f64,
    pub reason: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ConsensusDecision {
    pub accepted: bool,
    pub buy_votes: usize,
    pub required_buy_votes: usize,
    pub position_fraction: f64,
    pub votes: Vec<StrategyVote>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct GuardState {
    pub trading_day: String,
    pub halted: bool,
    pub halt_reason: Option<String>,
    pub live_error_count: usize,
    pub stream_error_count: usize,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct LiveOrderRecord {
    pub order_id: String,
    pub token_id: String,
    pub market_id: String,
    pub side: String,
    pub price: f64,
    pub shares: f64,
    pub status: String,
    pub created_at: String,
    pub updated_at: String,
    pub remaining_shares: f64,
    pub filled_shares: f64,
    pub post_only: bool,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct LiveTrade {
    pub trade_id: Option<String>,
    pub token_id: String,
    pub market_id: String,
    pub outcome: Option<String>,
    pub side: String,
    pub shares: f64,
    pub price: f64,
    pub matched_at: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct LivePosition {
    pub token_id: String,
    pub market_id: String,
    pub outcome: Option<String>,
    pub shares: f64,
    pub avg_price: f64,
    pub opened_at: String,
}

#[derive(Clone, Debug, Default)]
struct LiveAccountSnapshot {
    collateral_balance: f64,
    realized_pnl: f64,
    positions: Vec<LivePosition>,
}

#[derive(Clone, Debug, Default)]
struct WalletStats {
    trades: usize,
    realized_pnl: f64,
    gross_volume: f64,
    closed_round_trips: usize,
    winning_round_trips: usize,
    explicit_profit_total: f64,
    explicit_profit_count: usize,
}

#[derive(Clone, Debug)]
struct Lot {
    qty: f64,
    price: f64,
    opened_at: String,
}

fn default_true() -> bool { true }
fn default_scanner_limit() -> usize { 200 }
fn default_min_market_liquidity() -> f64 { 50_000.0 }
fn default_min_book_depth() -> f64 { 500.0 }
fn default_min_hours() -> f64 { 4.0 }
fn default_max_hours() -> f64 { 168.0 }
fn default_auto_trade_min_score() -> f64 { 12.0 }
fn default_auto_trade_min_wallets() -> usize { 1 }
fn default_consensus_min_buy_votes() -> usize { 2 }
fn default_consensus_single_vote_fraction() -> f64 { 0.5 }
fn default_consensus_arbitrage_min_deviation_bps() -> f64 { 700.0 }
fn default_max_position_fraction() -> f64 { 0.10 }
fn default_min_cash_reserve_fraction() -> f64 { 0.10 }
fn default_max_open_positions() -> usize { 5 }
fn default_take_profit() -> f64 { 0.10 }
fn default_stop_loss() -> f64 { 0.08 }
fn default_stale_hours() -> f64 { 24.0 }
fn default_max_live_open_orders() -> usize { 20 }
fn default_live_order_max_age_seconds() -> usize { 30 }
fn default_live_min_order_notional() -> f64 { 5.0 }
fn default_live_require_armed_env() -> bool { true }
fn default_live_armed_env() -> String { "STONKS_CLI_POLYMARKET_LIVE_ARMED".to_string() }
fn default_loop_interval_ms() -> u64 { 1000 }
fn default_paper_starting_cash() -> f64 { 1000.0 }

pub fn handle_control(op: &str, request: ControlRequest) -> Result<Value, String> {
    let state_dir = resolve_state_dir(&request)?;
    match op {
        "markets_list" => Ok(json!(markets_list(&request.args)?)),
        "market_get" => Ok(json!(market_get(&request.args)?)),
        "book" => Ok(json!(book_get(&request.args)?)),
        "scan" => Ok(json!(scan_markets(&state_dir, &request.config, &request.args)?)),
        "paper_init" => Ok(json!(paper_init(&state_dir, &request.args)?)),
        "paper_status" => Ok(json!(paper_status(&state_dir, &request.args)?)),
        "paper_buy" => Ok(json!(paper_buy(&state_dir, &request.args)?)),
        "paper_sell" => Ok(json!(paper_sell(&state_dir, &request.args)?)),
        "wallets_import" => Ok(json!(wallets_import(&state_dir, &request.args)?)),
        "wallets_rank" => Ok(json!(wallets_rank(&state_dir, &request.config, &request.args)?)),
        "wallet_targets" => Ok(json!(wallet_targets_get(&state_dir, &request.config)?)),
        "wallet_signals" => Ok(json!(read_json_vec::<WalletMarketSignal>(&wallet_signals_path(&state_dir))?)),
        "journal" => Ok(json!(read_journal(&state_dir, arg_usize(&request.args, "limit").unwrap_or(100))?)),
        "runtime_status" => Ok(json!(load_runtime_status(&state_dir)?)),
        "guard_status" => Ok(guard_status_value(&state_dir)?),
        "guard_halt" => Ok(json!(halt_guard(&state_dir, arg_str(&request.args, "reason").unwrap_or("manual_halt"))?)),
        "guard_resume" => Ok(json!(resume_guard(&state_dir)?)),
        "doctor" => Ok(json!(preflight(&state_dir, &request.config, &request.args))),
        "settle" => Ok(json!(settle_market(&state_dir, &request.args)?)),
        "replay_market" => Ok(json!(replay_market_events(&request.args)?)),
        "replay_user" => Ok(json!(replay_user_events(&request.args)?)),
        "runtime_soak" => Ok(runtime_soak(&state_dir, &request.config, &request.args)?),
        "runtime_once" => Ok(runtime_once(&state_dir, &request.config, &request.args)?),
        "runtime_loop" => Ok(runtime_loop(&state_dir, &request.config, &request.args)?),
        other => Err(format!("unsupported control op: {other}")),
    }
}

fn resolve_state_dir(request: &ControlRequest) -> Result<PathBuf, String> {
    if !request.state_dir.trim().is_empty() {
        return Ok(PathBuf::from(request.state_dir.trim()));
    }
    if let Ok(path) = env::var("STONKS_CLI_STATE_DIR") {
        if !path.trim().is_empty() {
            return Ok(PathBuf::from(path));
        }
    }
    Err("state_dir is required".to_string())
}

fn json_client() -> Result<Client, String> {
    Client::builder()
        .timeout(Duration::from_secs(15))
        .build()
        .map_err(|err| err.to_string())
}

fn markets_list(args: &Value) -> Result<Vec<PolymarketMarket>, String> {
    let limit = arg_usize(args, "limit").unwrap_or(100);
    let active = arg_bool(args, "active");
    let closed = arg_bool(args, "closed");
    let order = arg_str(args, "order").unwrap_or("volume");
    let client = json_client()?;
    let mut req = client.get(GAMMA_URL).query(&[("limit", limit.to_string()), ("offset", "0".to_string()), ("order", order.to_string())]);
    if let Some(v) = active { req = req.query(&[("active", v.to_string())]); }
    if let Some(v) = closed { req = req.query(&[("closed", v.to_string())]); }
    let payload: Value = req.send().map_err(|err| err.to_string())?.error_for_status().map_err(|err| err.to_string())?.json().map_err(|err| err.to_string())?;
    parse_market_list(payload)
}

fn market_get(args: &Value) -> Result<PolymarketMarket, String> {
    let slug_or_id = required_str(args, "slug_or_id")?;
    let client = json_client()?;
    let req = if slug_or_id.chars().all(|c| c.is_ascii_digit()) {
        client.get(GAMMA_URL).query(&[("id", slug_or_id.to_string())])
    } else {
        client.get(GAMMA_URL).query(&[("slug", slug_or_id.to_string())])
    };
    let payload: Value = req.send().map_err(|err| err.to_string())?.error_for_status().map_err(|err| err.to_string())?.json().map_err(|err| err.to_string())?;
    match payload {
        Value::Array(items) => items.into_iter().next().map(parse_market).transpose()?.ok_or_else(|| format!("market not found: {slug_or_id}")),
        Value::Object(_) => parse_market(payload),
        _ => Err("unexpected market payload".to_string()),
    }
}

fn book_get(args: &Value) -> Result<OrderBook, String> {
    let token_id = required_str(args, "token_id")?;
    let client = json_client()?;
    let payload: Value = client
        .get(CLOB_BOOK_URL)
        .query(&[("token_id", token_id.to_string())])
        .send()
        .map_err(|err| err.to_string())?
        .error_for_status()
        .map_err(|err| err.to_string())?
        .json()
        .map_err(|err| err.to_string())?;
    parse_order_book(token_id, payload)
}

fn scan_markets(state_dir: &Path, cfg: &ControlConfig, args: &Value) -> Result<Vec<MarketScan>, String> {
    let limit = arg_usize(args, "limit").unwrap_or(cfg.scanner_limit);
    let include_filtered = arg_bool(args, "include_filtered").unwrap_or(false);
    let markets = markets_list(&json!({
        "limit": limit,
        "active": cfg.require_active,
        "closed": false,
        "order": "volume"
    }))?;
    let signals = read_json_vec::<WalletMarketSignal>(&wallet_signals_path(state_dir)).unwrap_or_default();
    let mut by_signal: HashMap<(String, String), WalletMarketSignal> = HashMap::new();
    for signal in signals {
        by_signal.insert((signal.market_id.clone(), signal.outcome.to_ascii_uppercase()), signal);
    }
    let mut out = Vec::new();
    for market in markets {
        let token = primary_token(&market);
        if token.is_none() {
            if include_filtered {
                out.push(MarketScan {
                    market_id: market.market_id.clone(),
                    slug: market.slug.clone(),
                    question: market.question.clone(),
                    token_id: None,
                    outcome: None,
                    midpoint: None,
                    bids_depth_usd: 0.0,
                    asks_depth_usd: 0.0,
                    liquidity_usd: market.liquidity_usd,
                    volume_usd: market.volume_usd,
                    hours_to_resolution: hours_to_resolution(market.end_date_iso.as_deref()),
                    complement_deviation_bps: complement_deviation_bps(&market),
                    score: 0.0,
                    status: "FILTERED".to_string(),
                    reasons: vec!["missing_token".to_string()],
                    target_wallet_count: 0,
                    target_trade_count: 0,
                    target_net_volume: 0.0,
                });
            }
            continue;
        }
        let token = token.unwrap();
        let book = book_get(&json!({ "token_id": token.token_id }))?;
        let mut scan = structural_scan_market(&market, &book, cfg);
        if let Some(signal) = by_signal.get(&(scan.market_id.clone(), scan.outcome.clone().unwrap_or_default().to_ascii_uppercase())) {
            scan.target_wallet_count = signal.wallet_count;
            scan.target_trade_count = signal.trade_count;
            scan.target_net_volume = signal.net_volume;
            let extra_score = (signal.wallet_count as f64 * 2.0).min(10.0) + ((signal.trade_count as f64) / 10.0).min(5.0);
            scan.score = round2(scan.score + extra_score);
        }
        if include_filtered || scan.status == "PASS" {
            out.push(scan);
        }
    }
    out.sort_by(|a, b| b.score.partial_cmp(&a.score).unwrap_or(std::cmp::Ordering::Equal));
    Ok(out)
}

fn structural_scan_market(market: &PolymarketMarket, book: &OrderBook, cfg: &ControlConfig) -> MarketScan {
    let token = primary_token(market);
    let bids_depth = round2(book.bids.iter().map(|level| level.price * level.size).sum());
    let asks_depth = round2(book.asks.iter().map(|level| level.price * level.size).sum());
    let hrs = hours_to_resolution(market.end_date_iso.as_deref());
    let deviation_bps = complement_deviation_bps(market);
    let mut reasons = Vec::new();
    if cfg.require_active && market.active == Some(false) {
        reasons.push("inactive".to_string());
    }
    if market.closed == Some(true) {
        reasons.push("closed".to_string());
    }
    reasons.extend(market_universe_rejections(market, cfg));
    if let Some(liq) = market.liquidity_usd {
        if liq < cfg.min_market_liquidity_usd {
            reasons.push(format!("liquidity<{}", cfg.min_market_liquidity_usd as i64));
        }
    }
    if bids_depth < cfg.min_book_depth_usd || asks_depth < cfg.min_book_depth_usd {
        reasons.push(format!("depth<{}", cfg.min_book_depth_usd as i64));
    }
    if let Some(h) = hrs {
        if h < cfg.min_hours_to_resolution {
            reasons.push(format!("hours<{:.1}", cfg.min_hours_to_resolution));
        }
        if h > cfg.max_hours_to_resolution {
            reasons.push(format!("hours>{:.1}", cfg.max_hours_to_resolution));
        }
    }
    let depth_balance = bids_depth.min(asks_depth);
    let time_score = hrs
        .map(|h| (1.0 - ((h - 24.0).abs() / 24.0).min(1.0)).max(0.0))
        .unwrap_or(0.0);
    let deviation_score = deviation_bps.unwrap_or(0.0) / 100.0;
    let status = if reasons.is_empty() { "PASS" } else { "FILTERED" }.to_string();
    MarketScan {
        market_id: market.market_id.clone(),
        slug: market.slug.clone(),
        question: market.question.clone(),
        token_id: token.as_ref().map(|token| token.token_id.clone()),
        outcome: token.and_then(|token| token.outcome.clone()),
        midpoint: book.midpoint,
        bids_depth_usd: bids_depth,
        asks_depth_usd: asks_depth,
        liquidity_usd: market.liquidity_usd,
        volume_usd: market.volume_usd,
        hours_to_resolution: hrs.map(round2),
        complement_deviation_bps: deviation_bps.map(round2),
        score: round2((depth_balance / 1000.0) + deviation_score + time_score * 10.0),
        status,
        reasons,
        target_wallet_count: 0,
        target_trade_count: 0,
        target_net_volume: 0.0,
    }
}

fn market_universe_rejections(market: &PolymarketMarket, cfg: &ControlConfig) -> Vec<String> {
    let mut reasons = Vec::new();
    let slug = market.slug.clone().unwrap_or_default().to_ascii_lowercase();
    let haystack = format!(
        "{} {} {}",
        market.question.to_ascii_lowercase(),
        slug,
        market.raw.get("category").and_then(|v| v.as_str()).unwrap_or("").to_ascii_lowercase()
    );
    if !cfg.allowed_market_slugs.is_empty()
        && !cfg.allowed_market_slugs.iter().any(|item| slug == normalize_filter_text(item))
    {
        reasons.push("not_in_allowed_market_slugs".to_string());
    }
    if cfg.blocked_market_slugs.iter().any(|item| slug == normalize_filter_text(item)) {
        reasons.push("blocked_market_slug".to_string());
    }
    if !cfg.allowed_market_keywords.is_empty()
        && !cfg.allowed_market_keywords.iter().any(|item| haystack.contains(&normalize_filter_text(item)))
    {
        reasons.push("not_in_allowed_market_keywords".to_string());
    }
    if cfg.blocked_market_keywords.iter().any(|item| haystack.contains(&normalize_filter_text(item))) {
        reasons.push("blocked_market_keyword".to_string());
    }
    if cfg.crypto_only && !CRYPTO_KEYWORDS.iter().any(|keyword| haystack.contains(keyword)) {
        reasons.push("not_crypto_market".to_string());
    }
    if cfg.block_sports && SPORTS_KEYWORDS.iter().any(|keyword| haystack.contains(keyword)) {
        reasons.push("blocked_sports_market".to_string());
    }
    reasons
}

fn normalize_filter_text(value: &str) -> String {
    value.trim().to_ascii_lowercase()
}

const CRYPTO_KEYWORDS: &[&str] = &[
    "bitcoin", "btc", "ethereum", "eth", "solana", "sol", "crypto", "stablecoin", "usdc", "tether",
    "defi", "blockchain", "etf", "binance", "coinbase",
];

const SPORTS_KEYWORDS: &[&str] = &[
    "sport", "sports", "nba", "nfl", "mlb", "nhl", "ufc", "soccer", "football", "basketball", "baseball", "hockey",
    "tennis", "golf", "formula 1", "f1", "champions league", "premier league", "world cup",
    "super bowl", "march madness",
];

fn paper_init(state_dir: &Path, args: &Value) -> Result<PaperAccount, String> {
    let cash = arg_f64(args, "cash").unwrap_or(default_paper_starting_cash());
    let account = PaperAccount { cash, realized_pnl: 0.0, positions: Vec::new(), trades: Vec::new() };
    write_json(&paper_path(state_dir), &account)?;
    Ok(account)
}

fn paper_status(state_dir: &Path, args: &Value) -> Result<Value, String> {
    let account = load_paper(state_dir)?;
    let mut midpoints: HashMap<String, f64> = HashMap::new();
    if let Some(map) = args.get("midpoints").and_then(|value| value.as_object()) {
        for (key, value) in map {
            if let Some(price) = value.as_f64() {
                midpoints.insert(key.clone(), price);
            }
        }
    }
    let mut unrealized = 0.0;
    let mut positions = Vec::new();
    for position in &account.positions {
        let mark = *midpoints.get(&position.token_id).unwrap_or(&position.avg_price);
        let u = (mark - position.avg_price) * position.shares;
        unrealized += u;
        positions.push(json!({
            "token_id": position.token_id,
            "market_id": position.market_id,
            "slug": position.slug,
            "outcome": position.outcome,
            "shares": position.shares,
            "avg_price": position.avg_price,
            "opened_at": position.opened_at,
            "target_price": position.target_price,
            "stop_price": position.stop_price,
            "thesis": position.thesis,
            "mark_price": mark,
            "market_value": round8(mark * position.shares),
            "unrealized_pnl": round8(u),
        }));
    }
    let equity = round8(account.cash + positions.iter().filter_map(|value| value.get("market_value").and_then(|v| v.as_f64())).sum::<f64>());
    Ok(json!({
        "cash": account.cash,
        "realized_pnl": account.realized_pnl,
        "unrealized_pnl": round8(unrealized),
        "equity": equity,
        "positions": positions,
        "trades": account.trades.iter().rev().take(20).cloned().collect::<Vec<_>>().into_iter().rev().collect::<Vec<_>>(),
    }))
}

fn paper_buy(state_dir: &Path, args: &Value) -> Result<Value, String> {
    let mut account = load_paper(state_dir)?;
    let token_id = required_str(args, "token_id")?.to_string();
    let market_id = required_str(args, "market_id")?.to_string();
    let shares = required_f64(args, "shares")?;
    let price = required_f64(args, "price")?;
    if shares <= 0.0 || price <= 0.0 {
        return Err("shares and price must be positive".to_string());
    }
    let notional = shares * price;
    if account.cash < notional {
        return Err(format!("Insufficient paper cash. Need ${notional:.2}, have ${:.2}", account.cash));
    }
    let slug = arg_str(args, "slug").map(str::to_string);
    let outcome = arg_str(args, "outcome").map(str::to_string);
    let target_price = arg_f64(args, "target_price");
    let stop_price = arg_f64(args, "stop_price");
    let thesis = arg_str(args, "thesis").map(str::to_string);
    if let Some(index) = account.positions.iter().position(|p| p.token_id == token_id) {
        let position = account.positions[index].clone();
        let new_shares = position.shares + shares;
        let new_avg = ((position.avg_price * position.shares) + notional) / new_shares;
        account.positions[index] = PaperPosition {
            token_id: position.token_id,
            market_id: position.market_id,
            slug: position.slug,
            outcome: position.outcome,
            shares: new_shares,
            avg_price: round8(new_avg),
            opened_at: position.opened_at,
            target_price: target_price.or(position.target_price),
            stop_price: stop_price.or(position.stop_price),
            thesis: thesis.or(position.thesis),
        };
    } else {
        account.positions.push(PaperPosition {
            token_id: token_id.clone(),
            market_id: market_id.clone(),
            slug,
            outcome,
            shares,
            avg_price: price,
            opened_at: utc_now_iso(),
            target_price,
            stop_price,
            thesis,
        });
    }
    account.cash = round8(account.cash - notional);
    account.trades.push(PaperTrade {
        ts: utc_now_iso(),
        action: "BUY".to_string(),
        token_id: token_id.clone(),
        market_id: market_id.clone(),
        slug: arg_str(args, "slug").map(str::to_string),
        outcome: arg_str(args, "outcome").map(str::to_string),
        shares,
        price,
        notional,
        realized_pnl: None,
        reason: arg_str(args, "reason").map(str::to_string),
    });
    write_json(&paper_path(state_dir), &account)?;
    Ok(json!({
        "action": "BUY",
        "token_id": token_id,
        "shares": shares,
        "price": price,
        "notional": round8(notional),
        "cash": account.cash,
    }))
}

fn paper_sell(state_dir: &Path, args: &Value) -> Result<Value, String> {
    let mut account = load_paper(state_dir)?;
    let token_id = required_str(args, "token_id")?.to_string();
    let shares = required_f64(args, "shares")?;
    let price = required_f64(args, "price")?;
    let index = account.positions.iter().position(|p| p.token_id == token_id).ok_or_else(|| "Insufficient paper position to sell".to_string())?;
    let position = account.positions[index].clone();
    if position.shares < shares {
        return Err("Insufficient paper position to sell".to_string());
    }
    let notional = shares * price;
    let realized = (price - position.avg_price) * shares;
    let remaining = round8(position.shares - shares);
    account.cash = round8(account.cash + notional);
    account.realized_pnl = round8(account.realized_pnl + realized);
    account.positions.remove(index);
    if remaining > 0.0 {
        account.positions.push(PaperPosition { shares: remaining, ..position.clone() });
    }
    account.trades.push(PaperTrade {
        ts: utc_now_iso(),
        action: "SELL".to_string(),
        token_id: token_id.clone(),
        market_id: position.market_id.clone(),
        slug: position.slug.clone(),
        outcome: position.outcome.clone(),
        shares,
        price,
        notional,
        realized_pnl: Some(round8(realized)),
        reason: arg_str(args, "reason").map(str::to_string),
    });
    write_json(&paper_path(state_dir), &account)?;
    Ok(json!({
        "action": "SELL",
        "token_id": token_id,
        "shares": shares,
        "price": price,
        "notional": round8(notional),
        "realized_pnl": round8(realized),
        "cash": account.cash,
    }))
}

fn wallets_import(state_dir: &Path, args: &Value) -> Result<WalletImportSummary, String> {
    let source_path = PathBuf::from(required_str(args, "csv_path")?);
    let rows = read_csv_rows(&source_path)?;
    let fieldnames = rows.first().ok_or_else(|| "wallet import requires a header row".to_string())?;
    for required in ["maker", "market_id", "nonusdc_side", "maker_direction", "price", "token_amount"] {
        if !fieldnames.contains_key(required) {
            return Err(format!("wallet import requires columns: {required}"));
        }
    }
    let mut wallets = HashSet::new();
    for row in rows.iter().skip(1) {
        if let Some(maker) = row.get("maker").map(|value| value.trim().to_ascii_lowercase()).filter(|value| !value.is_empty()) {
            wallets.insert(maker);
        }
    }
    let detected_profit_column = fieldnames.contains_key("profit") || fieldnames.contains_key("pnl") || fieldnames.contains_key("realized_pnl");
    let summary = WalletImportSummary {
        source_path: source_path.canonicalize().unwrap_or(source_path).display().to_string(),
        row_count: rows.len().saturating_sub(1),
        wallet_count: wallets.len(),
        imported_at: utc_now_iso(),
        detected_profit_column,
    };
    write_json(&wallet_manifest_path(state_dir), &summary)?;
    Ok(summary)
}

fn wallets_rank(state_dir: &Path, cfg: &ControlConfig, args: &Value) -> Result<Vec<WalletTarget>, String> {
    let summary: WalletImportSummary = read_json(&wallet_manifest_path(state_dir))?;
    let csv_path = arg_str(args, "csv_path").map(PathBuf::from).unwrap_or_else(|| PathBuf::from(summary.source_path));
    let rows = read_csv_rows(&csv_path)?;
    let min_trades = arg_usize(args, "min_trades").unwrap_or(100);
    let min_win_rate = arg_f64(args, "min_win_rate").unwrap_or(0.70);
    let limit = arg_usize(args, "limit").unwrap_or(50);
    let mut stats_by_wallet: HashMap<String, WalletStats> = HashMap::new();
    let mut long_books: HashMap<String, HashMap<(String, String), VecDeque<Lot>>> = HashMap::new();
    let mut short_books: HashMap<String, HashMap<(String, String), VecDeque<Lot>>> = HashMap::new();
    let mut market_counts: HashMap<String, HashMap<(String, String), (usize, f64, f64)>> = HashMap::new();

    for row in rows.iter().skip(1) {
        let wallet = row.get("maker").map(|v| v.trim().to_ascii_lowercase()).unwrap_or_default();
        let market_id = row.get("market_id").cloned().unwrap_or_default();
        let side = row.get("nonusdc_side").cloned().unwrap_or_default();
        let direction = row.get("maker_direction").map(|v| v.trim().to_ascii_uppercase()).unwrap_or_default();
        let ts = row.get("timestamp").cloned().unwrap_or_else(utc_now_iso);
        let price = row.get("price").and_then(|v| v.parse::<f64>().ok());
        let qty = row.get("token_amount").and_then(|v| v.parse::<f64>().ok());
        if wallet.is_empty() || market_id.is_empty() || side.is_empty() || !matches!(direction.as_str(), "BUY" | "SELL") || price.is_none() || qty.is_none() {
            continue;
        }
        let price = price.unwrap();
        let qty = qty.unwrap();
        if qty <= 0.0 { continue; }
        let instrument = (market_id.clone(), side.clone());
        let stats = stats_by_wallet.entry(wallet.clone()).or_default();
        stats.trades += 1;
        stats.gross_volume += price * qty;
        let counts = market_counts.entry(wallet.clone()).or_default().entry(instrument.clone()).or_insert((0, 0.0, 0.0));
        counts.0 += 1;
        counts.1 += if direction == "BUY" { qty } else { -qty };
        counts.2 += price * qty;
        for col in ["profit", "pnl", "realized_pnl"] {
            if let Some(value) = row.get(col).and_then(|v| v.parse::<f64>().ok()) {
                stats.explicit_profit_total += value;
                stats.explicit_profit_count += 1;
                break;
            }
        }
        if direction == "BUY" {
            let books = short_books.entry(wallet.clone()).or_default();
            let shorts = books.entry(instrument.clone()).or_default();
            let mut remaining = qty;
            while remaining > 0.0 && !shorts.is_empty() {
                let mut lot = shorts.front().cloned().unwrap();
                let matched = remaining.min(lot.qty);
                let pnl = (lot.price - price) * matched;
                stats.realized_pnl += pnl;
                stats.closed_round_trips += 1;
                if pnl > 0.0 { stats.winning_round_trips += 1; }
                remaining -= matched;
                lot.qty -= matched;
                shorts.pop_front();
                if lot.qty > 1e-12 { shorts.push_front(lot); }
            }
            if remaining > 0.0 {
                long_books.entry(wallet.clone()).or_default().entry(instrument).or_default().push_back(Lot { qty: remaining, price, opened_at: ts.clone() });
            }
        } else {
            let books = long_books.entry(wallet.clone()).or_default();
            let longs = books.entry(instrument.clone()).or_default();
            let mut remaining = qty;
            while remaining > 0.0 && !longs.is_empty() {
                let mut lot = longs.front().cloned().unwrap();
                let matched = remaining.min(lot.qty);
                let pnl = (price - lot.price) * matched;
                stats.realized_pnl += pnl;
                stats.closed_round_trips += 1;
                if pnl > 0.0 { stats.winning_round_trips += 1; }
                remaining -= matched;
                lot.qty -= matched;
                longs.pop_front();
                if lot.qty > 1e-12 { longs.push_front(lot); }
            }
            if remaining > 0.0 {
                short_books.entry(wallet.clone()).or_default().entry(instrument).or_default().push_back(Lot { qty: remaining, price, opened_at: ts.clone() });
            }
        }
    }

    let mut targets = Vec::new();
    for (wallet, stats) in stats_by_wallet {
        if stats.trades < min_trades { continue; }
        let realized = if stats.explicit_profit_count > 0 { stats.explicit_profit_total } else { stats.realized_pnl };
        let win_rate = if stats.closed_round_trips > 0 { stats.winning_round_trips as f64 / stats.closed_round_trips as f64 } else { 0.0 };
        if win_rate < min_win_rate { continue; }
        targets.push(WalletTarget {
            wallet,
            trades: stats.trades,
            realized_pnl: round6(realized),
            gross_volume: round6(stats.gross_volume),
            win_rate: round6(win_rate),
            closed_round_trips: stats.closed_round_trips,
            source: "ranked".to_string(),
        });
    }
    targets.sort_by(|a, b| b.realized_pnl.partial_cmp(&a.realized_pnl).unwrap_or(std::cmp::Ordering::Equal));
    targets.truncate(limit);
    merge_configured_wallet_targets(cfg, &mut targets);
    write_json(&wallet_targets_path(state_dir), &targets)?;
    let selected: HashSet<String> = targets.iter().map(|t| t.wallet.clone()).collect();
    let mut signals = Vec::new();
    for ((market_id, outcome), buckets) in market_counts.into_iter().flat_map(|(wallet, by_inst)| by_inst.into_iter().map(move |(inst, counts)| ((inst.0, inst.1), (wallet.clone(), counts)))) .fold(BTreeMap::<(String,String), Vec<(String,(usize,f64,f64))>>::new(), |mut acc, (inst, payload)| { acc.entry(inst).or_default().push(payload); acc }) {
        let mut wallets = HashSet::new();
        let mut trade_count = 0usize;
        let mut net_volume = 0.0;
        let mut gross_volume = 0.0;
        for (wallet, counts) in buckets {
            if !selected.contains(&wallet) { continue; }
            wallets.insert(wallet);
            trade_count += counts.0;
            net_volume += counts.1;
            gross_volume += counts.2;
        }
        if !wallets.is_empty() {
            signals.push(WalletMarketSignal {
                market_id,
                outcome,
                wallet_count: wallets.len(),
                trade_count,
                net_volume: round6(net_volume),
                gross_volume: round6(gross_volume),
            });
        }
    }
    signals.sort_by(|a, b| b.wallet_count.cmp(&a.wallet_count).then(b.trade_count.cmp(&a.trade_count)));
    write_json(&wallet_signals_path(state_dir), &signals)?;
    Ok(targets)
}

fn wallet_targets_get(state_dir: &Path, cfg: &ControlConfig) -> Result<Vec<WalletTarget>, String> {
    let mut targets = read_json_vec::<WalletTarget>(&wallet_targets_path(state_dir)).unwrap_or_default();
    merge_configured_wallet_targets(cfg, &mut targets);
    Ok(targets)
}

fn merge_configured_wallet_targets(cfg: &ControlConfig, targets: &mut Vec<WalletTarget>) {
    let mut seen: HashSet<String> = targets.iter().map(|target| target.wallet.to_ascii_lowercase()).collect();
    for wallet in &cfg.target_wallet_addresses {
        let normalized = normalize_wallet(wallet);
        if normalized.is_empty() || seen.contains(&normalized) {
            continue;
        }
        targets.push(WalletTarget {
            wallet: normalized.clone(),
            trades: 0,
            realized_pnl: 0.0,
            gross_volume: 0.0,
            win_rate: 0.0,
            closed_round_trips: 0,
            source: "configured".to_string(),
        });
        seen.insert(normalized);
    }
}

fn normalize_wallet(wallet: &str) -> String {
    wallet.trim().to_ascii_lowercase()
}

fn runtime_once(state_dir: &Path, cfg: &ControlConfig, args: &Value) -> Result<Value, String> {
    let limit = arg_usize(args, "limit").unwrap_or(cfg.scanner_limit);
    let scans = scan_markets(state_dir, cfg, &json!({ "limit": limit, "include_filtered": false }))?;
    let mut actions = Vec::new();
    if cfg.paper {
        actions.extend(auto_exit_positions(state_dir, cfg, &scans)?);
    } else {
        actions.extend(auto_exit_live_positions(state_dir, cfg, &scans)?);
        actions.extend(cancel_stale_live_orders(state_dir, cfg)?);
    }
    if cfg.auto_trade_enabled {
        if let Some(action) = maybe_open_position(state_dir, cfg, &scans)? {
            actions.push(action);
        }
    }
    let status = RuntimeStatus {
        mode: "polymarket".to_string(),
        state: if actions.is_empty() { "idle".to_string() } else { "traded".to_string() },
        paper: cfg.paper,
        last_scan_at: Some(utc_now_iso()),
        last_scan_count: limit,
        last_pass_count: scans.len(),
        open_positions: current_open_count(state_dir, cfg),
        last_actions: actions.iter().filter_map(|value| value.get("action").and_then(|v| v.as_str()).zip(value.get("token_id").and_then(|v| v.as_str()))).map(|(a,t)| format!("{a}:{t}")).collect(),
        last_error: None,
    };
    write_json(&runtime_status_path(state_dir), &status)?;
    append_journal(state_dir, json!({"event":"runtime_cycle_completed","state":status.state,"open_positions":status.open_positions,"action_count":actions.len()}))?;
    Ok(json!({
        "status": status,
        "queue": scans,
        "actions": actions,
        "journal": read_journal(state_dir, 20)?,
    }))
}

fn runtime_loop(state_dir: &Path, cfg: &ControlConfig, args: &Value) -> Result<Value, String> {
    let cycles = arg_usize(args, "cycles").unwrap_or(1);
    let limit = arg_usize(args, "limit").unwrap_or(cfg.scanner_limit);
    let sleep_seconds = arg_f64(args, "sleep_seconds").unwrap_or(cfg.loop_interval_ms as f64 / 1000.0);
    let mut iterations = Vec::new();
    for iteration in 1..=cycles {
        let guard = load_guard_state(state_dir)?;
        if guard.halted {
            append_journal(state_dir, json!({"event":"runtime_loop_halted","iteration":iteration,"reason":guard.halt_reason}))?;
            break;
        }
        let result = runtime_once(state_dir, cfg, &json!({ "limit": limit }))?;
        iterations.push(json!({
            "iteration": iteration,
            "status": result.get("status").cloned().unwrap_or(json!({})),
            "action_count": result.get("actions").and_then(|v| v.as_array()).map(|v| v.len()).unwrap_or(0),
        }));
        if iteration < cycles && sleep_seconds > 0.0 {
            thread::sleep(Duration::from_secs_f64(sleep_seconds));
        }
    }
    Ok(json!({
        "cycles": cycles,
        "sleep_seconds": sleep_seconds,
        "final_status": load_runtime_status(state_dir)?,
        "guard_state": load_guard_state(state_dir)?,
        "iterations": iterations,
    }))
}

fn maybe_open_position(state_dir: &Path, cfg: &ControlConfig, scans: &[MarketScan]) -> Result<Option<Value>, String> {
    let account = load_paper_opt(state_dir).unwrap_or(PaperAccount { cash: cfg.paper_starting_cash, realized_pnl: 0.0, positions: Vec::new(), trades: Vec::new() });
    let live_snapshot = if cfg.paper { None } else { Some(live_account_snapshot()?) };
    let guard = load_guard_state(state_dir)?;
    for scan in scans {
        let consensus = consensus_decision(cfg, scan);
        let reasons = trade_guard_reasons(state_dir, cfg, &guard, &account, live_snapshot.as_ref(), scan);
        if !reasons.is_empty() {
            append_journal(state_dir, json!({"event":"proposal_rejected","token_id":scan.token_id,"market_id":scan.market_id,"slug":scan.slug,"reasons":reasons,"score":scan.score,"consensus":consensus}))?;
            continue;
        }
        let max_notional = {
            let available_cash = if cfg.paper {
                account.cash.max(0.0)
            } else {
                live_snapshot.as_ref().map(|snapshot| snapshot.collateral_balance).unwrap_or(0.0).max(0.0)
            };
            let mut max_notional = available_cash * cfg.max_position_fraction;
            let reserve_cash = available_cash * cfg.min_cash_reserve_fraction;
            if available_cash - max_notional < reserve_cash {
                max_notional = (available_cash - reserve_cash).max(0.0);
            }
            max_notional * consensus.position_fraction
        };
        if max_notional <= 0.0 || scan.midpoint.is_none() { continue; }
        let shares = round6(max_notional / scan.midpoint.unwrap());
        if shares <= 0.0 { continue; }
        let target = (scan.midpoint.unwrap() + cfg.take_profit_price_delta).min(0.99);
        let stop = (scan.midpoint.unwrap() - cfg.stop_loss_price_delta).max(0.01);
        let action = if cfg.paper {
            let result = paper_buy(
                state_dir,
                &json!({
                    "token_id": scan.token_id,
                    "market_id": scan.market_id,
                    "slug": scan.slug,
                    "outcome": scan.outcome,
                    "shares": shares,
                    "price": scan.midpoint,
                    "target_price": target,
                    "stop_price": stop,
                    "thesis": format!("score={:.2}|wallets={}|votes={}/{}", scan.score, scan.target_wallet_count, consensus.buy_votes, consensus.required_buy_votes),
                    "reason": format!("score={:.2}|wallets={}|votes={}/{}", scan.score, scan.target_wallet_count, consensus.buy_votes, consensus.required_buy_votes),
                }),
            )?;
            append_journal(state_dir, json!({"event":"paper_execution","result":result.clone(),"consensus":consensus}))?;
            result
        } else {
            live_place_order(
                state_dir,
                cfg,
                scan,
                shares,
                format!("score={:.2}|wallets={}|votes={}/{}", scan.score, scan.target_wallet_count, consensus.buy_votes, consensus.required_buy_votes),
                None,
            )?
        };
        return Ok(Some(action));
    }
    Ok(None)
}

fn auto_exit_positions(state_dir: &Path, cfg: &ControlConfig, scans: &[MarketScan]) -> Result<Vec<Value>, String> {
    if !cfg.auto_exit_enabled { return Ok(Vec::new()); }
    let account = match load_paper_opt(state_dir) {
        Some(account) => account,
        None => return Ok(Vec::new()),
    };
    let price_map: HashMap<String, f64> = scans.iter().filter_map(|scan| scan.token_id.clone().zip(scan.midpoint)).collect();
    let mut actions = Vec::new();
    for position in account.positions {
        let current_price = price_map.get(&position.token_id).copied();
        let should_exit = if let Some(price) = current_price {
            position.target_price.is_some_and(|target| price >= target)
                || position.stop_price.is_some_and(|stop| price <= stop)
                || hours_since(&position.opened_at).unwrap_or(0.0) >= cfg.stale_position_hours
        } else {
            hours_since(&position.opened_at).unwrap_or(0.0) >= cfg.stale_position_hours
        };
        if !should_exit { continue; }
        let price = current_price.unwrap_or(position.avg_price);
        let reason = if position.target_price.is_some_and(|target| price >= target) {
            "TARGET_HIT"
        } else if position.stop_price.is_some_and(|stop| price <= stop) {
            "STOP_LOSS"
        } else {
            "STALE_POSITION"
        };
        let action = paper_sell(state_dir, &json!({
            "token_id": position.token_id,
            "shares": position.shares,
            "price": price,
            "reason": reason,
        }))?;
        append_journal(state_dir, json!({"event":"auto_exit","token_id":position.token_id,"market_id":position.market_id,"slug":position.slug,"reason":reason,"price":price,"shares":position.shares}))?;
        actions.push(action);
    }
    Ok(actions)
}

fn auto_exit_live_positions(state_dir: &Path, cfg: &ControlConfig, scans: &[MarketScan]) -> Result<Vec<Value>, String> {
    if !cfg.auto_exit_enabled {
        return Ok(Vec::new());
    }
    let snapshot = live_account_snapshot()?;
    if snapshot.positions.is_empty() {
        return Ok(Vec::new());
    }
    let prices: HashMap<String, f64> = scans
        .iter()
        .filter_map(|scan| scan.token_id.clone().zip(scan.midpoint))
        .collect();
    let mut actions = Vec::new();
    for position in snapshot.positions {
        let Some(current_price) = prices.get(&position.token_id).copied() else { continue; };
        let target = (position.avg_price + cfg.take_profit_price_delta).min(0.99);
        let stop = (position.avg_price - cfg.stop_loss_price_delta).max(0.01);
        let should_exit =
            current_price >= target
                || current_price <= stop
                || hours_since(&position.opened_at).unwrap_or(0.0) >= cfg.stale_position_hours;
        if !should_exit {
            continue;
        }
        let reason = if current_price >= target {
            "TARGET_HIT"
        } else if current_price <= stop {
            "STOP_LOSS"
        } else {
            "STALE_POSITION"
        };
        let result = live_place_order(
            state_dir,
            cfg,
            &MarketScan {
                market_id: position.market_id.clone(),
                slug: None,
                question: String::new(),
                token_id: Some(position.token_id.clone()),
                outcome: position.outcome.clone(),
                midpoint: Some(current_price),
                bids_depth_usd: 0.0,
                asks_depth_usd: 0.0,
                liquidity_usd: None,
                volume_usd: None,
                hours_to_resolution: None,
                complement_deviation_bps: None,
                score: 0.0,
                status: "PASS".to_string(),
                reasons: Vec::new(),
                target_wallet_count: 0,
                target_trade_count: 0,
                target_net_volume: 0.0,
            },
            position.shares,
            reason.to_string(),
            Some("sell"),
        )?;
        append_journal(
            state_dir,
            json!({"event":"auto_exit","token_id":position.token_id,"market_id":position.market_id,"reason":reason,"price":current_price,"shares":position.shares}),
        )?;
        actions.push(result);
    }
    Ok(actions)
}

fn trade_guard_reasons(
    state_dir: &Path,
    cfg: &ControlConfig,
    guard: &GuardState,
    account: &PaperAccount,
    live_snapshot: Option<&LiveAccountSnapshot>,
    scan: &MarketScan,
) -> Vec<String> {
    let mut reasons = Vec::new();
    let live_orders = if cfg.paper {
        Vec::new()
    } else {
        load_live_orders(state_dir).unwrap_or_default()
    };
    if guard.halted {
        reasons.push(format!("halted:{}", guard.halt_reason.clone().unwrap_or_else(|| "manual_halt".to_string())));
    }
    if !cfg.paper && cfg.live_require_armed_env && !live_trading_armed(cfg) {
        reasons.push("live_trading_not_armed".to_string());
    }
    if !cfg.auto_trade_enabled { reasons.push("auto_trade_disabled".to_string()); }
    if scan.status != "PASS" { reasons.push("scan_not_pass".to_string()); }
    if scan.token_id.is_none() { reasons.push("missing_token".to_string()); }
    if scan.midpoint.is_none() || !(0.0..1.0).contains(&scan.midpoint.unwrap()) { reasons.push("invalid_midpoint".to_string()); }
    if scan.score < cfg.auto_trade_min_score { reasons.push("score_below_threshold".to_string()); }
    if scan.target_wallet_count < cfg.auto_trade_min_target_wallets { reasons.push("wallet_signal_below_threshold".to_string()); }
    if cfg.consensus_enabled {
        let consensus = consensus_decision(cfg, scan);
        if !consensus.accepted {
            reasons.push(format!("consensus_buy_votes<{}/{}", consensus.buy_votes, consensus.required_buy_votes));
        }
    }
    if cfg.paper {
        if account.positions.iter().any(|p| Some(&p.token_id) == scan.token_id.as_ref()) { reasons.push("position_already_open".to_string()); }
        if account.positions.len() >= cfg.max_open_positions { reasons.push("max_open_positions_reached".to_string()); }
    } else {
        let live_positions = live_snapshot.map(|snapshot| snapshot.positions.as_slice()).unwrap_or(&[]);
        if live_orders.iter().any(|record| scan.token_id.as_deref() == Some(record.token_id.as_str()) && is_live_open_status(&record.status)) {
            reasons.push("position_already_open".to_string());
        }
        if live_positions.iter().any(|position| scan.token_id.as_deref() == Some(position.token_id.as_str())) {
            reasons.push("position_already_open".to_string());
        }
        if live_orders.iter().filter(|record| is_live_open_status(&record.status)).count() >= cfg.max_open_positions {
            reasons.push("max_open_positions_reached".to_string());
        }
        if live_orders.iter().filter(|record| is_live_open_status(&record.status)).count() >= cfg.max_live_open_orders {
            reasons.push("max_live_open_orders_reached".to_string());
        }
        if let (Some(midpoint), Some(snapshot)) = (scan.midpoint, live_snapshot) {
            let notional = snapshot.collateral_balance.max(0.0) * cfg.max_position_fraction;
            if midpoint > 0.0 && notional < cfg.live_min_order_notional_usd {
                reasons.push("live_notional_below_minimum".to_string());
            }
        }
    }
    if cfg.paper {
        if cfg.max_daily_loss > 0.0 && account.realized_pnl <= -cfg.max_daily_loss { reasons.push("max_daily_loss_reached".to_string()); }
    } else if let Some(snapshot) = live_snapshot {
        if cfg.max_daily_loss > 0.0 && snapshot.realized_pnl <= -cfg.max_daily_loss {
            reasons.push("max_daily_loss_reached".to_string());
        }
    }
    if cfg.max_market_notional > 0.0 {
        let market_notional: f64 = if cfg.paper {
            account.positions.iter().filter(|p| p.market_id == scan.market_id).map(|p| p.shares * p.avg_price).sum()
        } else {
            live_snapshot
                .map(|snapshot| {
                    snapshot
                        .positions
                        .iter()
                        .filter(|p| p.market_id == scan.market_id)
                        .map(|p| p.shares * p.avg_price)
                        .sum()
                })
                .unwrap_or(0.0)
        };
        let available_cash = if cfg.paper {
            account.cash
        } else {
            live_snapshot.map(|snapshot| snapshot.collateral_balance).unwrap_or(0.0)
        };
        let current_notional = scan.midpoint.unwrap_or(0.0) * (available_cash * cfg.max_position_fraction).max(0.0);
        if market_notional + current_notional > cfg.max_market_notional {
            reasons.push("max_market_notional_reached".to_string());
        }
    }
    reasons
}

fn consensus_decision(cfg: &ControlConfig, scan: &MarketScan) -> ConsensusDecision {
    let votes = strategy_votes(cfg, scan);
    let buy_votes = votes.iter().filter(|vote| vote.action == "BUY").count();
    let required_buy_votes = cfg.consensus_min_buy_votes.max(1).min(votes.len().max(1));
    let accepted = !cfg.consensus_enabled || buy_votes >= required_buy_votes;
    let position_fraction = if !accepted {
        0.0
    } else if buy_votes >= 2 {
        1.0
    } else if buy_votes == 1 {
        cfg.consensus_single_vote_fraction.clamp(0.0, 1.0)
    } else {
        0.0
    };
    ConsensusDecision {
        accepted,
        buy_votes,
        required_buy_votes,
        position_fraction,
        votes,
    }
}

fn strategy_votes(cfg: &ControlConfig, scan: &MarketScan) -> Vec<StrategyVote> {
    vec![
        arbitrage_vote(cfg, scan),
        convergence_vote(cfg, scan),
        whale_copy_vote(cfg, scan),
    ]
}

fn arbitrage_vote(cfg: &ControlConfig, scan: &MarketScan) -> StrategyVote {
    let deviation = scan.complement_deviation_bps.unwrap_or(0.0);
    if scan.status == "PASS" && deviation >= cfg.consensus_arbitrage_min_deviation_bps {
        return StrategyVote {
            agent: "arbitrage".to_string(),
            action: "BUY".to_string(),
            confidence: round6((0.50 + (deviation / 2_000.0)).min(0.95)),
            reason: format!("complement_deviation_bps={deviation:.2}"),
        };
    }
    StrategyVote {
        agent: "arbitrage".to_string(),
        action: "HOLD".to_string(),
        confidence: 0.0,
        reason: format!("deviation_below_threshold:{deviation:.2}"),
    }
}

fn convergence_vote(cfg: &ControlConfig, scan: &MarketScan) -> StrategyVote {
    if scan.status == "PASS" && scan.score >= cfg.auto_trade_min_score {
        return StrategyVote {
            agent: "convergence".to_string(),
            action: "BUY".to_string(),
            confidence: round6((scan.score / (cfg.auto_trade_min_score * 2.0).max(1.0)).min(0.95)),
            reason: format!("score={:.2}", scan.score),
        };
    }
    StrategyVote {
        agent: "convergence".to_string(),
        action: "HOLD".to_string(),
        confidence: 0.0,
        reason: format!("score_below_threshold:{:.2}", scan.score),
    }
}

fn whale_copy_vote(cfg: &ControlConfig, scan: &MarketScan) -> StrategyVote {
    if scan.status == "PASS"
        && scan.target_wallet_count >= cfg.auto_trade_min_target_wallets
        && scan.target_net_volume > 0.0
    {
        return StrategyVote {
            agent: "whale_copy".to_string(),
            action: "BUY".to_string(),
            confidence: round6((0.55 + (scan.target_wallet_count as f64 * 0.08)).min(0.95)),
            reason: format!("wallets={}|net_volume={:.2}", scan.target_wallet_count, scan.target_net_volume),
        };
    }
    StrategyVote {
        agent: "whale_copy".to_string(),
        action: "HOLD".to_string(),
        confidence: 0.0,
        reason: format!("wallet_signal_weak:{}|{:.2}", scan.target_wallet_count, scan.target_net_volume),
    }
}

fn settle_market(state_dir: &Path, args: &Value) -> Result<Value, String> {
    let market_id = required_str(args, "market_id")?;
    let winning_token_id = required_str(args, "winning_token_id")?;
    let mut account = load_paper(state_dir)?;
    let mut settled = Vec::new();
    let mut remaining = Vec::new();
    for position in account.positions {
        if position.market_id != market_id {
            remaining.push(position);
            continue;
        }
        let payout = if position.token_id == winning_token_id { position.shares } else { 0.0 };
        let realized_pnl = payout - (position.shares * position.avg_price);
        account.cash = round8(account.cash + payout);
        account.realized_pnl = round8(account.realized_pnl + realized_pnl);
        settled.push(json!({"token_id":position.token_id,"market_id":position.market_id,"shares":position.shares,"payout":payout,"realized_pnl":round8(realized_pnl)}));
    }
    account.positions = remaining;
    write_json(&paper_path(state_dir), &account)?;
    Ok(json!({"market_id":market_id,"winning_token_id":winning_token_id,"settled":settled,"cash":account.cash,"realized_pnl":account.realized_pnl}))
}

fn runtime_status_path(state_dir: &Path) -> PathBuf { state_dir.join("polymarket_runtime.json") }
fn paper_path(state_dir: &Path) -> PathBuf { state_dir.join("polymarket_paper.json") }
fn wallet_manifest_path(state_dir: &Path) -> PathBuf { state_dir.join("polymarket_wallets.json") }
fn wallet_targets_path(state_dir: &Path) -> PathBuf { state_dir.join("polymarket_wallet_targets.json") }
fn wallet_signals_path(state_dir: &Path) -> PathBuf { state_dir.join("polymarket_wallet_market_stats.json") }
fn journal_path(state_dir: &Path) -> PathBuf { state_dir.join("polymarket_journal.jsonl") }
fn guard_path(state_dir: &Path) -> PathBuf { state_dir.join("polymarket_guard.json") }
fn manual_halt_path(state_dir: &Path) -> PathBuf { state_dir.join("polymarket.halt") }
fn live_orders_path(state_dir: &Path) -> PathBuf { state_dir.join("polymarket_live_orders.json") }

fn load_paper(state_dir: &Path) -> Result<PaperAccount, String> {
    read_json(&paper_path(state_dir))
}

fn load_paper_opt(state_dir: &Path) -> Option<PaperAccount> {
    read_json(&paper_path(state_dir)).ok()
}

fn load_live_orders(state_dir: &Path) -> Result<Vec<LiveOrderRecord>, String> {
    if !live_orders_path(state_dir).exists() {
        return Ok(Vec::new());
    }
    read_json(&live_orders_path(state_dir))
}

fn save_live_orders(state_dir: &Path, records: &[LiveOrderRecord]) -> Result<(), String> {
    write_json(&live_orders_path(state_dir), &records)
}

fn load_runtime_status(state_dir: &Path) -> Result<RuntimeStatus, String> {
    if !runtime_status_path(state_dir).exists() {
        return Ok(RuntimeStatus {
            mode: "polymarket".to_string(),
            state: "idle".to_string(),
            paper: true,
            last_scan_at: None,
            last_scan_count: 0,
            last_pass_count: 0,
            open_positions: 0,
            last_actions: Vec::new(),
            last_error: None,
        });
    }
    read_json(&runtime_status_path(state_dir))
}

fn load_guard_state(state_dir: &Path) -> Result<GuardState, String> {
    if !guard_path(state_dir).exists() {
        return Ok(GuardState {
            trading_day: Utc::now().date_naive().to_string(),
            halted: false,
            halt_reason: None,
            live_error_count: 0,
            stream_error_count: 0,
        });
    }
    read_json(&guard_path(state_dir))
}

fn current_open_count(state_dir: &Path, cfg: &ControlConfig) -> usize {
    if cfg.paper {
        return load_paper_opt(state_dir).map(|account| account.positions.len()).unwrap_or(0);
    }
    live_account_snapshot().map(|snapshot| snapshot.positions.len()).unwrap_or_else(|_| {
        load_live_orders(state_dir)
            .map(|records| records.into_iter().filter(|record| is_live_open_status(&record.status)).count())
            .unwrap_or(0)
    })
}

fn guard_status_value(state_dir: &Path) -> Result<Value, String> {
    let state = load_guard_state(state_dir)?;
    Ok(json!({
        "trading_day": state.trading_day,
        "halted": state.halted,
        "halt_reason": state.halt_reason,
        "live_error_count": state.live_error_count,
        "stream_error_count": state.stream_error_count,
        "active_halt_reason": active_halt_reason(state_dir, Some(&state)),
    }))
}

fn halt_guard(state_dir: &Path, reason: &str) -> Result<GuardState, String> {
    let state = GuardState {
        halted: true,
        halt_reason: Some(reason.to_string()),
        ..load_guard_state(state_dir)?
    };
    write_json(&guard_path(state_dir), &state)?;
    fs::write(manual_halt_path(state_dir), reason).map_err(|err| err.to_string())?;
    Ok(state)
}

fn resume_guard(state_dir: &Path) -> Result<GuardState, String> {
    if manual_halt_path(state_dir).exists() {
        fs::remove_file(manual_halt_path(state_dir)).map_err(|err| err.to_string())?;
    }
    let state = GuardState {
        halted: false,
        halt_reason: None,
        live_error_count: 0,
        stream_error_count: 0,
        ..load_guard_state(state_dir)?
    };
    write_json(&guard_path(state_dir), &state)?;
    Ok(state)
}

fn preflight(state_dir: &Path, cfg: &ControlConfig, args: &Value) -> Value {
    let mut checks = Vec::new();
    let deep_auth = arg_bool(args, "deep_auth").unwrap_or(false);
    checks.push(json!({"name":"state_dir","status":if ensure_dir(state_dir).is_ok() {"pass"} else {"fail"},"detail":state_dir.display().to_string()}));
    let guard = load_guard_state(state_dir).ok();
    let halt_reason = active_halt_reason(state_dir, guard.as_ref());
    checks.push(json!({"name":"guard_state","status":if halt_reason.is_some() {"fail"} else {"pass"},"detail":halt_reason.unwrap_or_else(|| "trading guards clear".to_string())}));
    checks.push(json!({"name":"mode","status":if cfg.paper {"warn"} else {"pass"},"detail":if cfg.paper {"paper mode enabled; live execution disabled"} else {"live mode enabled"}}));
    if !cfg.paper {
        let has_key = env::var("POLYMARKET_PRIVATE_KEY").map(|v| !v.trim().is_empty()).unwrap_or(false);
        checks.push(json!({"name":"private_key","status":if has_key {"pass"} else {"fail"},"detail":if has_key {"private key env present"} else {"missing private key in POLYMARKET_PRIVATE_KEY"}}));
        let armed = live_trading_armed(cfg);
        checks.push(json!({"name":"live_arm","status":if armed || !cfg.live_require_armed_env {"pass"} else {"warn"},"detail":if armed {format!("{} armed", cfg.live_armed_env)} else {format!("set {}=1 to allow live auto-trading", cfg.live_armed_env)}}));
        let cli_present = Command::new(polymarket_cli_bin()).arg("--help").output().is_ok();
        checks.push(json!({"name":"polymarket_cli","status":if cli_present {"pass"} else {"fail"},"detail":if cli_present {"polymarket CLI available"} else {"install Polymarket's official `polymarket-cli` for Rust live execution"}}));
        if cli_present && deep_auth {
            checks.extend(deep_auth_checks());
        }
    }
    let overall = if checks.iter().any(|c| c.get("status").and_then(|v| v.as_str()) == Some("fail")) {
        "fail"
    } else if checks.iter().any(|c| c.get("status").and_then(|v| v.as_str()) == Some("warn")) {
        "warn"
    } else {
        "pass"
    };
    json!({"overall":overall,"paper":cfg.paper,"deep_auth":deep_auth,"checks":checks})
}

fn deep_auth_checks() -> Vec<Value> {
    let mut checks = Vec::new();
    checks.push(cli_command_check("wallet_show", &["wallet", "show"], None));
    checks.push(cli_command_check("wallet_address", &["wallet", "address"], None));
    checks.push(cli_command_check("approve_check", &["approve", "check"], None));
    checks.push(cli_command_check(
        "clob_balance_collateral",
        &["clob", "balance", "--asset-type", "collateral"],
        Some(extract_first_numeric_expected),
    ));
    checks.push(cli_command_check("clob_orders", &["clob", "orders"], None));
    checks.push(cli_command_check("clob_trades", &["clob", "trades"], None));
    checks
}

fn cli_command_check(
    name: &str,
    args: &[&str],
    validator: Option<fn(&Value) -> Result<String, String>>,
) -> Value {
    let result = polymarket_cli_json(&args.iter().map(|item| item.to_string()).collect::<Vec<_>>());
    match result {
        Ok(payload) => {
            let detail = match validator {
                Some(validate) => match validate(&payload) {
                    Ok(detail) => detail,
                    Err(err) => {
                        return json!({"name":name,"status":"fail","detail":err});
                    }
                },
                None => "ok".to_string(),
            };
            json!({"name":name,"status":"pass","detail":detail})
        }
        Err(err) => json!({"name":name,"status":"fail","detail":err}),
    }
}

fn extract_first_numeric_expected(payload: &Value) -> Result<String, String> {
    let value = extract_first_numeric(
        payload,
        &["available", "available_balance", "availableBalance", "balance", "amount", "total"],
    )
    .ok_or_else(|| "could not parse numeric balance payload".to_string())?;
    Ok(format!("{value:.4}"))
}

fn active_halt_reason(state_dir: &Path, state: Option<&GuardState>) -> Option<String> {
    let halt_path = manual_halt_path(state_dir);
    if halt_path.exists() {
        return fs::read_to_string(halt_path).ok().map(|v| {
            let trimmed = v.trim().to_string();
            if trimmed.is_empty() { "manual_halt".to_string() } else { trimmed }
        }).or_else(|| Some("manual_halt".to_string()));
    }
    state.and_then(|current| if current.halted { current.halt_reason.clone() } else { None })
}

fn polymarket_cli_bin() -> String {
    env::var("POLYMARKET_CLI_BIN").unwrap_or_else(|_| "polymarket".to_string())
}

fn polymarket_cli_json(args: &[String]) -> Result<Value, String> {
    let mut cmd = Command::new(polymarket_cli_bin());
    cmd.arg("-o").arg("json");
    cmd.args(args);
    let output = cmd.output().map_err(|err| err.to_string())?;
    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
        let stdout = String::from_utf8_lossy(&output.stdout).trim().to_string();
        return Err(if !stderr.is_empty() { stderr } else { stdout });
    }
    let stdout = String::from_utf8(output.stdout).map_err(|err| err.to_string())?;
    serde_json::from_str(&stdout).map_err(|err| err.to_string())
}

fn live_sync_open_orders(state_dir: &Path) -> Result<Vec<LiveOrderRecord>, String> {
    let payload = polymarket_cli_json(&["clob".to_string(), "orders".to_string()])?;
    let records = normalize_live_orders(&payload);
    save_live_orders(state_dir, &records)?;
    if !records.is_empty() {
        append_journal(state_dir, json!({"event":"live_open_orders_synced","orders":records}))?;
    }
    Ok(records)
}

fn live_collateral_balance() -> Result<f64, String> {
    let payload = polymarket_cli_json(&[
        "clob".to_string(),
        "balance".to_string(),
        "--asset-type".to_string(),
        "collateral".to_string(),
    ])?;
    extract_first_numeric(
        &payload,
        &[
            "available",
            "available_balance",
            "availableBalance",
            "balance",
            "amount",
            "total",
        ],
    )
    .ok_or_else(|| "unable to parse collateral balance from polymarket-cli".to_string())
}

fn live_trades() -> Result<Vec<LiveTrade>, String> {
    let payload = polymarket_cli_json(&["clob".to_string(), "trades".to_string()])?;
    Ok(normalize_live_trades(&payload))
}

fn live_tick_size(token_id: &str) -> Result<f64, String> {
    let payload = polymarket_cli_json(&["clob".to_string(), "tick-size".to_string(), token_id.to_string()])?;
    extract_first_numeric(&payload, &["tick_size", "tickSize", "minimum_tick_size", "minimumTickSize", "size", "value"])
        .or_else(|| value_to_f64(&payload))
        .ok_or_else(|| format!("unable to parse tick size for token {token_id}"))
}

fn live_account_snapshot() -> Result<LiveAccountSnapshot, String> {
    let collateral_balance = live_collateral_balance()?;
    let trades = live_trades()?;
    let mut books: HashMap<(String, String, Option<String>), VecDeque<Lot>> = HashMap::new();
    let mut realized_pnl = 0.0;
    let mut ordered = trades;
    ordered.sort_by(|a, b| a.matched_at.cmp(&b.matched_at));
    for trade in ordered {
        let key = (trade.market_id.clone(), trade.token_id.clone(), trade.outcome.clone());
        match trade.side.to_ascii_uppercase().as_str() {
            "BUY" => {
                books.entry(key).or_default().push_back(Lot {
                    qty: trade.shares,
                    price: trade.price,
                    opened_at: trade.matched_at,
                });
            }
            "SELL" => {
                let lots = books.entry(key).or_default();
                let mut remaining = trade.shares;
                while remaining > 0.0 && !lots.is_empty() {
                    let mut lot = lots.front().cloned().unwrap();
                    let matched = remaining.min(lot.qty);
                    realized_pnl += (trade.price - lot.price) * matched;
                    remaining -= matched;
                    lot.qty -= matched;
                    lots.pop_front();
                    if lot.qty > 1e-12 {
                        lots.push_front(lot);
                    }
                }
            }
            _ => {}
        }
    }
    let mut positions = Vec::new();
    for ((market_id, token_id, outcome), lots) in books {
        if lots.is_empty() {
            continue;
        }
        let shares: f64 = lots.iter().map(|lot| lot.qty).sum();
        if shares <= 1e-12 {
            continue;
        }
        let notional: f64 = lots.iter().map(|lot| lot.qty * lot.price).sum();
        let opened_at = lots
            .front()
            .map(|lot| lot.opened_at.clone())
            .unwrap_or_else(utc_now_iso);
        positions.push(LivePosition {
            token_id,
            market_id,
            outcome,
            shares: round6(shares),
            avg_price: round8(notional / shares),
            opened_at,
        });
    }
    Ok(LiveAccountSnapshot {
        collateral_balance: round8(collateral_balance),
        realized_pnl: round8(realized_pnl),
        positions,
    })
}

fn cancel_stale_live_orders(state_dir: &Path, cfg: &ControlConfig) -> Result<Vec<Value>, String> {
    let records = live_sync_open_orders(state_dir)?;
    let mut actions = Vec::new();
    for record in records {
        if !is_live_open_status(&record.status) {
            continue;
        }
        if order_age_seconds(&record.created_at).unwrap_or(0) < cfg.live_order_max_age_seconds as i64 {
            continue;
        }
        let response = polymarket_cli_json(&[
            "clob".to_string(),
            "cancel".to_string(),
            record.order_id.clone(),
        ])?;
        actions.push(json!({
            "mode": "live",
            "action": "CANCEL",
            "token_id": record.token_id,
            "order_id": record.order_id,
            "response": response,
        }));
    }
    if !actions.is_empty() {
        let _ = live_sync_open_orders(state_dir);
    }
    Ok(actions)
}

fn live_place_order(
    state_dir: &Path,
    cfg: &ControlConfig,
    scan: &MarketScan,
    shares: f64,
    reason: String,
    side_hint: Option<&str>,
) -> Result<Value, String> {
    let token_id = scan.token_id.clone().ok_or_else(|| "missing token_id".to_string())?;
    let side = side_hint.unwrap_or("buy").to_ascii_lowercase();
    let raw_price = scan.midpoint.ok_or_else(|| "missing midpoint".to_string())?;
    let tick_size = live_tick_size(&token_id)?;
    let price = normalize_price_for_side(raw_price, &side, tick_size)?;
    let notional = price * shares;
    if notional < cfg.live_min_order_notional_usd {
        return Err(format!(
            "live order notional ${notional:.2} is below configured minimum ${:.2}",
            cfg.live_min_order_notional_usd
        ));
    }
    let mut args = vec![
        "clob".to_string(),
        "create-order".to_string(),
        "--token".to_string(),
        token_id.clone(),
        "--side".to_string(),
        side.clone(),
        "--price".to_string(),
        price.to_string(),
        "--size".to_string(),
        shares.to_string(),
    ];
    if cfg.live_post_only {
        args.push("--post-only".to_string());
    }
    let response = polymarket_cli_json(&args)?;
    validate_live_order_response(&response)?;
    let order_id = response
        .get("orderID")
        .or_else(|| response.get("orderId"))
        .or_else(|| response.get("id"))
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    if order_id.is_empty() {
        return Err(format!("live order response did not include an order id: {response}"));
    }
    if !order_id.is_empty() {
        let mut records = load_live_orders(state_dir)?;
        records.retain(|record| record.order_id != order_id);
        records.push(LiveOrderRecord {
            order_id: order_id.clone(),
            token_id: token_id.clone(),
            market_id: scan.market_id.clone(),
            side: side.to_ascii_uppercase(),
            price,
            shares,
            status: response
                .get("status")
                .and_then(|v| v.as_str())
                .unwrap_or("live")
                .to_string()
                .to_ascii_uppercase(),
            created_at: utc_now_iso(),
            updated_at: utc_now_iso(),
            remaining_shares: shares,
            filled_shares: 0.0,
            post_only: cfg.live_post_only,
        });
        save_live_orders(state_dir, &records)?;
    }
    let result = json!({
        "mode": "live",
        "action": side.to_ascii_uppercase(),
        "token_id": token_id,
        "market_id": scan.market_id,
        "price": price,
        "shares": shares,
        "order_id": if order_id.is_empty() { Value::Null } else { json!(order_id) },
        "reason": reason,
        "response": response,
    });
    append_journal(state_dir, json!({"event":"live_execution","result":result.clone()}))?;
    Ok(result)
}

fn normalize_price_for_side(price: f64, side: &str, tick_size: f64) -> Result<f64, String> {
    if !(0.0..1.0).contains(&price) {
        return Err("price must be between 0 and 1".to_string());
    }
    if tick_size <= 0.0 {
        return Err("tick size must be positive".to_string());
    }
    let units = price / tick_size;
    let snapped = if side.eq_ignore_ascii_case("buy") {
        units.floor() * tick_size
    } else {
        units.ceil() * tick_size
    };
    let decimals = tick_decimals(tick_size);
    let factor = 10_f64.powi(decimals as i32);
    let normalized = (snapped * factor).round() / factor;
    if !(0.0..1.0).contains(&normalized) {
        return Err("normalized price must be between 0 and 1".to_string());
    }
    Ok(normalized)
}

fn tick_decimals(tick_size: f64) -> usize {
    let text = format!("{tick_size:.8}");
    text.trim_end_matches('0')
        .split('.')
        .nth(1)
        .map(|v| v.len())
        .unwrap_or(0)
}

fn validate_live_order_response(response: &Value) -> Result<(), String> {
    if response.get("success").and_then(|v| v.as_bool()) == Some(false) {
        let detail = response
            .get("errorMsg")
            .or_else(|| response.get("error"))
            .and_then(|v| v.as_str())
            .unwrap_or("order rejected");
        return Err(detail.to_string());
    }
    Ok(())
}

fn normalize_live_orders(payload: &Value) -> Vec<LiveOrderRecord> {
    let items = if let Some(items) = payload.as_array() {
        items.clone()
    } else if let Some(items) = payload.get("orders").and_then(|v| v.as_array()) {
        items.clone()
    } else {
        Vec::new()
    };
    items
        .into_iter()
        .filter_map(|item| {
            let obj = item.as_object()?;
            let order_id = pick_string(obj, &["id", "order_id", "orderId"])?;
            let token_id = pick_string(obj, &["asset_id", "assetId", "token_id", "tokenId"]).unwrap_or_default();
            let market_id = pick_string(obj, &["market", "market_id", "marketId"]).unwrap_or_default();
            let side = pick_string(obj, &["side"]).unwrap_or_else(|| "BUY".to_string());
            let price = pick_f64(obj, &["price"]).unwrap_or(0.0);
            let shares = pick_f64(obj, &["original_size", "size", "shares"]).unwrap_or(0.0);
            let filled_shares = pick_f64(obj, &["size_matched", "filled_size", "filled"]).unwrap_or(0.0);
            let remaining = (shares - filled_shares).max(0.0);
            let created_at = normalize_created_at(obj.get("created_at").or_else(|| obj.get("createdAt")));
            Some(LiveOrderRecord {
                order_id,
                token_id,
                market_id,
                side,
                price,
                shares,
                status: pick_string(obj, &["status"]).unwrap_or_else(|| "LIVE".to_string()).to_ascii_uppercase(),
                created_at: created_at.clone(),
                updated_at: created_at,
                remaining_shares: round6(remaining),
                filled_shares: round6(filled_shares),
                post_only: false,
            })
        })
        .collect()
}

fn normalize_live_trades(payload: &Value) -> Vec<LiveTrade> {
    let items = if let Some(items) = payload.as_array() {
        items.clone()
    } else if let Some(items) = payload.get("trades").and_then(|v| v.as_array()) {
        items.clone()
    } else {
        Vec::new()
    };
    items
        .into_iter()
        .filter_map(|item| {
            let obj = item.as_object()?;
            let token_id = pick_string(obj, &["asset_id", "assetId", "token_id", "tokenId"])?;
            let market_id = pick_string(obj, &["market", "market_id", "marketId"]).unwrap_or_default();
            let side = pick_string(obj, &["side"]).unwrap_or_default();
            let shares = pick_f64(obj, &["size", "shares", "matched_amount"])?;
            let price = pick_f64(obj, &["price"])?;
            let matched_at = pick_string(obj, &["match_time", "matched_at", "created_at", "timestamp"])
                .map(|raw| {
                    if let Ok(ts) = raw.parse::<i64>() {
                        epoch_seconds_to_iso(ts)
                    } else {
                        raw
                    }
                })
                .unwrap_or_else(utc_now_iso);
            Some(LiveTrade {
                trade_id: pick_string(obj, &["id", "trade_id", "tradeId"]),
                token_id,
                market_id,
                outcome: pick_string(obj, &["outcome"]),
                side,
                shares,
                price,
                matched_at,
            })
        })
        .collect()
}

fn normalize_created_at(value: Option<&Value>) -> String {
    let Some(value) = value else { return utc_now_iso(); };
    if let Some(raw) = value.as_str() {
        if let Ok(ts) = raw.parse::<i64>() {
            return epoch_seconds_to_iso(ts);
        }
        return raw.to_string();
    }
    if let Some(ts) = value.as_i64() {
        return epoch_seconds_to_iso(ts);
    }
    utc_now_iso()
}

fn epoch_seconds_to_iso(ts: i64) -> String {
    DateTime::<Utc>::from_timestamp(ts, 0)
        .map(|value| value.to_rfc3339_opts(chrono::SecondsFormat::Secs, true))
        .unwrap_or_else(utc_now_iso)
}

fn order_age_seconds(created_at: &str) -> Option<i64> {
    let parsed = DateTime::parse_from_rfc3339(created_at).ok()?;
    Some((Utc::now() - parsed.with_timezone(&Utc)).num_seconds())
}

fn is_live_open_status(status: &str) -> bool {
    matches!(status.to_ascii_uppercase().as_str(), "LIVE" | "OPEN" | "PLACEMENT" | "UPDATE" | "PARTIAL" | "UNMATCHED" | "DELAYED")
}

fn replay_market_events(args: &Value) -> Result<Value, String> {
    let path = PathBuf::from(required_str(args, "path")?);
    let events = load_event_file(&path)?;
    let mut snapshots: BTreeMap<String, Value> = BTreeMap::new();
    let mut applied = 0usize;
    for event in events {
        let token_id = event_token_id(&event);
        let Some(token_id) = token_id else { continue; };
        let entry = snapshots.entry(token_id.clone()).or_insert_with(|| json!({
            "best_bid": Value::Null,
            "best_ask": Value::Null,
            "midpoint": Value::Null,
            "last_trade_price": Value::Null,
            "resolved": false,
        }));
        let Some(obj) = entry.as_object_mut() else { continue; };
        match event_type(&event).as_deref() {
            Some("book") | Some("best_bid_ask") => {
                if let Some(bid) = event.get("best_bid").and_then(value_to_f64).or_else(|| best_price(event.get("bids"), true)) {
                    obj.insert("best_bid".to_string(), json!(bid));
                }
                if let Some(ask) = event.get("best_ask").and_then(value_to_f64).or_else(|| best_price(event.get("asks"), false)) {
                    obj.insert("best_ask".to_string(), json!(ask));
                }
            }
            Some("price_change") | Some("last_trade_price") => {
                if let Some(price) = event.get("price").and_then(value_to_f64) {
                    obj.insert("last_trade_price".to_string(), json!(price));
                }
            }
            Some("market_resolved") => {
                obj.insert("resolved".to_string(), json!(true));
                if let Some(winner) = event.get("winning_asset_id").or_else(|| event.get("winner_asset_id")).and_then(|v| v.as_str()) {
                    obj.insert("winner_token_id".to_string(), json!(winner));
                }
            }
            _ => {}
        }
        let bid = obj.get("best_bid").and_then(value_to_f64);
        let ask = obj.get("best_ask").and_then(value_to_f64);
        let midpoint = match (bid, ask) {
            (Some(b), Some(a)) => Some(round6((b + a) / 2.0)),
            (Some(b), None) => Some(b),
            (None, Some(a)) => Some(a),
            _ => None,
        };
        obj.insert("midpoint".to_string(), midpoint.map_or(Value::Null, |v| json!(v)));
        applied += 1;
    }
    Ok(json!({"applied": applied, "snapshots": snapshots}))
}

fn replay_user_events(args: &Value) -> Result<Value, String> {
    let path = PathBuf::from(required_str(args, "path")?);
    let events = load_event_file(&path)?;
    let mut orders: BTreeMap<String, Value> = BTreeMap::new();
    let mut updates = 0usize;
    for event in events {
        let Some(order_id) = event.get("order_id").or_else(|| event.get("id")).and_then(|v| v.as_str()) else { continue; };
        let status = event
            .get("status")
            .or_else(|| event.get("type"))
            .and_then(|v| v.as_str())
            .unwrap_or("UPDATE");
        let filled = event
            .get("filled_size")
            .or_else(|| event.get("size_matched"))
            .and_then(value_to_f64)
            .unwrap_or(0.0);
        let remaining = event
            .get("remaining_size")
            .or_else(|| event.get("size_remaining"))
            .and_then(value_to_f64)
            .unwrap_or(0.0);
        orders.insert(order_id.to_string(), json!({
            "order_id": order_id,
            "status": status,
            "filled_shares": filled,
            "remaining_shares": remaining,
        }));
        updates += 1;
    }
    Ok(json!({
        "applied": updates,
        "orders": orders.into_values().collect::<Vec<_>>(),
    }))
}

fn runtime_soak(state_dir: &Path, cfg: &ControlConfig, args: &Value) -> Result<Value, String> {
    let market_events = arg_str(args, "market_events_path")
        .map(PathBuf::from)
        .map(|path| load_event_file(&path))
        .transpose()?
        .unwrap_or_default();
    let user_events = arg_str(args, "user_events_path")
        .map(PathBuf::from)
        .map(|path| load_event_file(&path))
        .transpose()?
        .unwrap_or_default();
    let batch_size = arg_usize(args, "batch_size").unwrap_or(1);
    let cycles = arg_usize(args, "cycles").unwrap_or(1);
    let limit = arg_usize(args, "limit").unwrap_or(cfg.scanner_limit);
    let mut market_idx = 0usize;
    let mut user_idx = 0usize;
    let mut iterations = Vec::new();
    for iteration in 1..=cycles {
        market_idx = (market_idx + batch_size).min(market_events.len());
        user_idx = (user_idx + batch_size).min(user_events.len());
        let result = runtime_once(state_dir, cfg, &json!({ "limit": limit }))?;
        iterations.push(json!({
            "iteration": iteration,
            "status": result.get("status").cloned().unwrap_or(json!({})),
            "action_count": result.get("actions").and_then(|v| v.as_array()).map(|v| v.len()).unwrap_or(0),
        }));
    }
    Ok(json!({
        "cycles": cycles,
        "market_events_consumed": market_idx,
        "user_events_consumed": user_idx,
        "final_status": load_runtime_status(state_dir)?,
        "iterations": iterations,
    }))
}

fn ensure_dir(path: &Path) -> Result<(), String> {
    fs::create_dir_all(path).map_err(|err| err.to_string())
}

fn read_journal(state_dir: &Path, limit: usize) -> Result<Vec<Value>, String> {
    let path = journal_path(state_dir);
    if !path.exists() { return Ok(Vec::new()); }
    let text = fs::read_to_string(path).map_err(|err| err.to_string())?;
    let mut out = Vec::new();
    for line in text.lines().rev().take(limit).collect::<Vec<_>>().into_iter().rev() {
        if let Ok(value) = serde_json::from_str::<Value>(line) {
            out.push(value);
        }
    }
    Ok(out)
}

fn append_journal(state_dir: &Path, payload: Value) -> Result<(), String> {
    let path = journal_path(state_dir);
    ensure_dir(state_dir)?;
    let mut current = if path.exists() { fs::read_to_string(&path).map_err(|err| err.to_string())? } else { String::new() };
    current.push_str(&serde_json::to_string(&payload).map_err(|err| err.to_string())?);
    current.push('\n');
    fs::write(path, current).map_err(|err| err.to_string())
}

fn read_json<T: for<'de> Deserialize<'de>>(path: &Path) -> Result<T, String> {
    let text = fs::read_to_string(path).map_err(|err| err.to_string())?;
    serde_json::from_str(&text).map_err(|err| err.to_string())
}

fn read_json_vec<T: for<'de> Deserialize<'de>>(path: &Path) -> Result<Vec<T>, String> {
    if !path.exists() { return Ok(Vec::new()); }
    read_json(path)
}

fn write_json<T: Serialize>(path: &Path, value: &T) -> Result<(), String> {
    if let Some(parent) = path.parent() { ensure_dir(parent)?; }
    let text = serde_json::to_string_pretty(value).map_err(|err| err.to_string())?;
    fs::write(path, text).map_err(|err| err.to_string())
}

fn parse_market_list(payload: Value) -> Result<Vec<PolymarketMarket>, String> {
    let items = payload.as_array().ok_or_else(|| "unexpected markets payload".to_string())?;
    items.iter().cloned().map(parse_market).collect()
}

fn parse_market(raw: Value) -> Result<PolymarketMarket, String> {
    let obj = raw.as_object().ok_or_else(|| "unexpected market payload".to_string())?;
    let tokens = if let Some(items) = obj.get("tokens").and_then(|v| v.as_array()) {
        items.iter().map(|item| {
            let token = item.as_object().ok_or_else(|| "invalid token".to_string())?;
            Ok(MarketToken {
                token_id: pick_string(token, &["token_id", "tokenId", "id", "asset_id", "assetId"]).unwrap_or_default(),
                outcome: pick_string(token, &["outcome", "name"]),
                price: pick_f64(token, &["price", "last_price", "lastPrice"]),
            })
        }).collect::<Result<Vec<_>, String>>()?
    } else {
        let token_ids = obj.get("clobTokenIds").and_then(parse_string_list).unwrap_or_default();
        let outcomes = obj.get("outcomes").and_then(parse_string_list).unwrap_or_default();
        let prices = obj.get("outcomePrices").and_then(parse_f64_list).unwrap_or_default();
        token_ids.iter().enumerate().map(|(idx, token_id)| MarketToken {
            token_id: token_id.clone(),
            outcome: outcomes.get(idx).cloned(),
            price: prices.get(idx).copied(),
        }).collect()
    };
    Ok(PolymarketMarket {
        market_id: pick_string(obj, &["id", "market_id", "marketId"]).unwrap_or_default(),
        question: pick_string(obj, &["question", "title"]).unwrap_or_default(),
        slug: pick_string(obj, &["slug", "market_slug"]),
        condition_id: pick_string(obj, &["condition_id", "conditionId"]),
        active: pick_bool(obj, &["active"]),
        closed: pick_bool(obj, &["closed"]),
        liquidity_usd: pick_f64(obj, &["liquidityNum", "liquidity", "liquidity_usd"]),
        volume_usd: pick_f64(obj, &["volumeNum", "volume", "volume_usd"]),
        end_date_iso: pick_string(obj, &["endDate", "end_date_iso", "endDateIso", "closedTime"]),
        tokens,
        raw,
    })
}

fn parse_order_book(token_id: &str, payload: Value) -> Result<OrderBook, String> {
    let obj = payload.as_object().ok_or_else(|| "unexpected order book payload".to_string())?;
    let bids = parse_levels(obj.get("bids"));
    let asks = parse_levels(obj.get("asks"));
    let best_bid = bids.iter().map(|lvl| lvl.price).reduce(f64::max);
    let best_ask = asks.iter().map(|lvl| lvl.price).reduce(f64::min);
    let midpoint = match (best_bid, best_ask) {
        (Some(bid), Some(ask)) => Some(round6((bid + ask) / 2.0)),
        (Some(bid), None) => Some(bid),
        (None, Some(ask)) => Some(ask),
        (None, None) => None,
    };
    Ok(OrderBook {
        token_id: token_id.to_string(),
        bids,
        asks,
        midpoint,
        best_bid,
        best_ask,
        raw: payload,
    })
}

fn parse_levels(value: Option<&Value>) -> Vec<BookLevel> {
    let Some(Value::Array(levels)) = value else { return Vec::new(); };
    levels.iter().filter_map(|item| match item {
        Value::Object(obj) => Some(BookLevel {
            price: pick_f64(obj, &["price"])?,
            size: pick_f64(obj, &["size", "amount"])?,
        }),
        Value::Array(items) if items.len() >= 2 => Some(BookLevel {
            price: value_to_f64(&items[0])?,
            size: value_to_f64(&items[1])?,
        }),
        _ => None,
    }).collect()
}

fn primary_token(market: &PolymarketMarket) -> Option<MarketToken> {
    market.tokens.iter().find(|token| token.outcome.as_deref().is_some_and(|o| o.eq_ignore_ascii_case("yes"))).cloned().or_else(|| market.tokens.first().cloned())
}

fn complement_deviation_bps(market: &PolymarketMarket) -> Option<f64> {
    let prices: Vec<f64> = market.tokens.iter().filter_map(|t| t.price).collect();
    if prices.len() < 2 { return None; }
    Some(round2((prices.iter().sum::<f64>() - 1.0).abs() * 10_000.0))
}

fn hours_to_resolution(value: Option<&str>) -> Option<f64> {
    let raw = value?;
    let parsed = DateTime::parse_from_rfc3339(raw).ok()?;
    let hours = (parsed.with_timezone(&Utc) - Utc::now()).num_seconds() as f64 / 3600.0;
    Some(hours)
}

fn utc_now_iso() -> String {
    Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Secs, true)
}

fn hours_since(raw: &str) -> Option<f64> {
    let parsed = DateTime::parse_from_rfc3339(raw).ok()?;
    Some((Utc::now() - parsed.with_timezone(&Utc)).num_seconds() as f64 / 3600.0)
}

fn live_trading_armed(cfg: &ControlConfig) -> bool {
    env::var(&cfg.live_armed_env).map(|v| matches!(v.trim().to_ascii_lowercase().as_str(), "1" | "true" | "yes" | "armed")).unwrap_or(false)
}

fn read_csv_rows(path: &Path) -> Result<Vec<HashMap<String, String>>, String> {
    let text = fs::read_to_string(path).map_err(|err| err.to_string())?;
    let mut lines = text.lines();
    let header = lines.next().ok_or_else(|| "empty csv".to_string())?;
    let columns: Vec<String> = header.split(',').map(|v| v.trim().to_string()).collect();
    let mut rows = Vec::new();
    rows.push(columns.iter().map(|c| (c.clone(), c.clone())).collect());
    for line in lines {
        if line.trim().is_empty() { continue; }
        let values: Vec<&str> = line.split(',').collect();
        let mut row = HashMap::new();
        for (idx, key) in columns.iter().enumerate() {
            row.insert(key.clone(), values.get(idx).copied().unwrap_or("").trim().to_string());
        }
        rows.push(row);
    }
    Ok(rows)
}

fn load_event_file(path: &Path) -> Result<Vec<Value>, String> {
    let text = fs::read_to_string(path).map_err(|err| err.to_string())?;
    let trimmed = text.trim();
    if trimmed.is_empty() {
        return Ok(Vec::new());
    }
    if trimmed.starts_with('[') {
        let payload = serde_json::from_str::<Vec<Value>>(trimmed).map_err(|err| err.to_string())?;
        return Ok(payload.into_iter().filter(|value| value.is_object()).collect());
    }
    let mut out = Vec::new();
    for line in trimmed.lines() {
        let line = line.trim();
        if line.is_empty() {
            continue;
        }
        let payload = serde_json::from_str::<Value>(line).map_err(|err| err.to_string())?;
        if payload.is_object() {
            out.push(payload);
        }
    }
    Ok(out)
}

fn event_type(event: &Value) -> Option<String> {
    event
        .get("event_type")
        .or_else(|| event.get("event"))
        .or_else(|| event.get("type"))
        .and_then(|v| v.as_str())
        .map(ToString::to_string)
}

fn event_token_id(event: &Value) -> Option<String> {
    ["asset_id", "assetId", "token_id", "tokenId"]
        .iter()
        .find_map(|key| event.get(*key))
        .and_then(|v| v.as_str())
        .map(ToString::to_string)
}

fn best_price(value: Option<&Value>, descending: bool) -> Option<f64> {
    let Some(Value::Array(levels)) = value else { return None; };
    let mut prices: Vec<f64> = levels
        .iter()
        .filter_map(|item| match item {
            Value::Object(obj) => obj.get("price").and_then(value_to_f64),
            Value::Array(items) if !items.is_empty() => value_to_f64(&items[0]),
            _ => None,
        })
        .collect();
    if prices.is_empty() {
        return None;
    }
    prices.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
    if descending { prices.last().copied() } else { prices.first().copied() }
}

fn extract_first_numeric(value: &Value, keys: &[&str]) -> Option<f64> {
    match value {
        Value::Object(obj) => {
            for key in keys {
                if let Some(found) = obj.get(*key).and_then(value_to_f64) {
                    return Some(found);
                }
            }
            obj.values().find_map(|child| extract_first_numeric(child, keys))
        }
        Value::Array(items) => items.iter().find_map(|child| extract_first_numeric(child, keys)),
        _ => None,
    }
}

fn arg_str<'a>(args: &'a Value, key: &str) -> Option<&'a str> {
    args.get(key).and_then(|v| v.as_str())
}
fn arg_bool(args: &Value, key: &str) -> Option<bool> {
    args.get(key).and_then(|v| v.as_bool())
}
fn arg_usize(args: &Value, key: &str) -> Option<usize> {
    args.get(key).and_then(|v| v.as_u64()).map(|v| v as usize)
}
fn arg_f64(args: &Value, key: &str) -> Option<f64> {
    args.get(key).and_then(value_to_f64)
}
fn required_str<'a>(args: &'a Value, key: &str) -> Result<&'a str, String> {
    arg_str(args, key).ok_or_else(|| format!("missing required key: {key}"))
}
fn required_f64(args: &Value, key: &str) -> Result<f64, String> {
    arg_f64(args, key).ok_or_else(|| format!("missing required key: {key}"))
}
fn pick_string(map: &serde_json::Map<String, Value>, keys: &[&str]) -> Option<String> {
    keys.iter().find_map(|k| map.get(*k)).and_then(|v| v.as_str().map(ToString::to_string))
}
fn pick_f64(map: &serde_json::Map<String, Value>, keys: &[&str]) -> Option<f64> {
    keys.iter().find_map(|k| map.get(*k)).and_then(value_to_f64)
}
fn pick_bool(map: &serde_json::Map<String, Value>, keys: &[&str]) -> Option<bool> {
    keys.iter().find_map(|k| map.get(*k)).and_then(|v| v.as_bool().or_else(|| v.as_str().and_then(|s| match s.to_ascii_lowercase().as_str() { "true" | "1" | "yes" => Some(true), "false" | "0" | "no" => Some(false), _ => None })))
}
fn value_to_f64(value: &Value) -> Option<f64> {
    value.as_f64().or_else(|| value.as_str().and_then(|v| v.parse::<f64>().ok()))
}
fn parse_string_list(value: &Value) -> Option<Vec<String>> {
    match value {
        Value::Array(items) => Some(items.iter().filter_map(|v| v.as_str().map(ToString::to_string)).collect()),
        Value::String(text) if text.starts_with('[') => serde_json::from_str::<Vec<String>>(text).ok(),
        _ => None,
    }
}
fn parse_f64_list(value: &Value) -> Option<Vec<f64>> {
    match value {
        Value::Array(items) => Some(items.iter().filter_map(value_to_f64).collect()),
        Value::String(text) if text.starts_with('[') => serde_json::from_str::<Vec<Value>>(text).ok().map(|items| items.iter().filter_map(value_to_f64).collect()),
        _ => None,
    }
}

fn round2(value: f64) -> f64 { (value * 100.0).round() / 100.0 }
fn round6(value: f64) -> f64 { (value * 1_000_000.0).round() / 1_000_000.0 }
fn round8(value: f64) -> f64 { (value * 100_000_000.0).round() / 100_000_000.0 }

#[cfg(test)]
mod tests {
    use super::*;
    use std::os::unix::fs::PermissionsExt;
    use std::time::{SystemTime, UNIX_EPOCH};

    fn temp_state_dir(name: &str) -> PathBuf {
        let suffix = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("time")
            .as_nanos();
        let path = std::env::temp_dir().join(format!("stonks-cli-{name}-{suffix}"));
        fs::create_dir_all(&path).expect("create temp state dir");
        path
    }

    fn write_mock_cli(state_dir: &Path) -> PathBuf {
        let script = state_dir.join("mock-polymarket");
        fs::write(
            &script,
            r#"#!/bin/sh
set -eu
if [ "${1:-}" = "-o" ]; then
  shift 2
fi
if [ "$1" = "clob" ] && [ "$2" = "balance" ]; then
  printf '%s\n' '{"balance":"250"}'
elif [ "$1" = "clob" ] && [ "$2" = "trades" ]; then
  printf '%s\n' '[{"id":"trade-1","asset_id":"YES1","market":"m1","side":"BUY","size":"10","price":"0.40","match_time":"1710000000","outcome":"YES"},{"id":"trade-2","asset_id":"YES1","market":"m1","side":"SELL","size":"4","price":"0.55","match_time":"1710000100","outcome":"YES"}]'
elif [ "$1" = "clob" ] && [ "$2" = "orders" ]; then
  printf '%s\n' '[]'
elif [ "$1" = "clob" ] && [ "$2" = "tick-size" ]; then
  printf '%s\n' '{"tick_size":"0.01"}'
elif [ "$1" = "clob" ] && [ "$2" = "create-order" ]; then
  printf '%s\n' '{"success":true,"orderID":"order-live-1","status":"live"}'
elif [ "$1" = "clob" ] && [ "$2" = "cancel" ]; then
  printf '%s\n' '{"canceled":["order-live-1"],"not_canceled":{}}'
else
  printf '%s\n' '{}'
fi
"#,
        )
        .expect("write cli script");
        let mut perms = fs::metadata(&script).expect("metadata").permissions();
        perms.set_mode(0o755);
        fs::set_permissions(&script, perms).expect("chmod");
        script
    }

    #[test]
    fn paper_buy_sell_round_trip_updates_account() {
        let state_dir = temp_state_dir("paper-round-trip");
        paper_init(&state_dir, &json!({ "cash": 1000.0 })).expect("init");

        let buy = paper_buy(
            &state_dir,
            &json!({
                "token_id": "YES1",
                "market_id": "m1",
                "slug": "btc-higher",
                "outcome": "YES",
                "shares": 100.0,
                "price": 0.40,
            }),
        )
        .expect("buy");
        let sell = paper_sell(&state_dir, &json!({ "token_id": "YES1", "shares": 50.0, "price": 0.60 })).expect("sell");
        let status = paper_status(&state_dir, &json!({ "midpoints": { "YES1": 0.58 } })).expect("status");

        assert_eq!(buy.get("action").and_then(|v| v.as_str()), Some("BUY"));
        assert_eq!(sell.get("action").and_then(|v| v.as_str()), Some("SELL"));
        assert_eq!(status.get("cash").and_then(|v| v.as_f64()), Some(990.0));
        assert_eq!(status.get("realized_pnl").and_then(|v| v.as_f64()), Some(10.0));
        assert_eq!(status.get("positions").and_then(|v| v.as_array()).map(|v| v.len()), Some(1));
    }

    #[test]
    fn settle_market_realizes_binary_payout() {
        let state_dir = temp_state_dir("paper-settle");
        paper_init(&state_dir, &json!({ "cash": 1000.0 })).expect("init");
        paper_buy(
            &state_dir,
            &json!({
                "token_id": "YES1",
                "market_id": "m1",
                "shares": 10.0,
                "price": 0.60,
            }),
        )
        .expect("buy");

        let settled = settle_market(&state_dir, &json!({ "market_id": "m1", "winning_token_id": "YES1" })).expect("settle");

        assert_eq!(settled.get("cash").and_then(|v| v.as_f64()), Some(1004.0));
        assert_eq!(settled.get("realized_pnl").and_then(|v| v.as_f64()), Some(4.0));
        assert_eq!(settled.get("settled").and_then(|v| v.as_array()).map(|v| v.len()), Some(1));
    }

    #[test]
    fn wallet_rank_uses_fifo_fallback_and_persists_signals() {
        let state_dir = temp_state_dir("wallet-rank");
        let csv_path = state_dir.join("trades.csv");
        fs::write(
            &csv_path,
            "\
timestamp,market_id,maker,taker,nonusdc_side,maker_direction,taker_direction,price,usd_amount,token_amount,transactionHash\n\
2026-01-01T00:00:00Z,1,0xgood,0xdef,YES,BUY,SELL,0.40,40,100,0x1\n\
2026-01-01T01:00:00Z,1,0xgood,0xdef,YES,SELL,BUY,0.60,60,100,0x2\n\
2026-01-01T02:00:00Z,2,0xbad,0xdef,YES,BUY,SELL,0.70,70,100,0x3\n\
2026-01-01T03:00:00Z,2,0xbad,0xdef,YES,SELL,BUY,0.50,50,100,0x4\n",
        )
        .expect("write csv");

        wallets_import(&state_dir, &json!({ "csv_path": csv_path })).expect("import");
        let targets = wallets_rank(
            &state_dir,
            &ControlConfig::default(),
            &json!({ "min_trades": 2, "min_win_rate": 0.60, "limit": 10 }),
        )
        .expect("rank");
        let signals: Vec<WalletMarketSignal> = read_json(&wallet_signals_path(&state_dir)).expect("signals");

        assert_eq!(targets.len(), 1);
        assert_eq!(targets[0].wallet, "0xgood");
        assert_eq!(targets[0].realized_pnl, 20.0);
        assert_eq!(signals.len(), 1);
        assert_eq!(signals[0].market_id, "1");
        assert_eq!(signals[0].wallet_count, 1);
    }

    #[test]
    fn configured_wallet_targets_are_merged_without_overwriting_ranked_wallets() {
        let state_dir = temp_state_dir("wallet-config-targets");
        write_json(
            &wallet_targets_path(&state_dir),
            &vec![WalletTarget {
                wallet: "0xranked".to_string(),
                trades: 100,
                realized_pnl: 42.0,
                gross_volume: 1_000.0,
                win_rate: 0.75,
                closed_round_trips: 20,
                source: "ranked".to_string(),
            }],
        )
        .expect("write targets");

        let targets = wallet_targets_get(
            &state_dir,
            &ControlConfig {
                target_wallet_addresses: vec![
                    "0xRanked".to_string(),
                    "0x6e1d5040d0ac73709b0621f620d2a60b80d2d0f".to_string(),
                ],
                ..ControlConfig::default()
            },
        )
        .expect("targets");

        assert_eq!(targets.len(), 2);
        assert!(targets.iter().any(|target| target.wallet == "0xranked" && target.source == "ranked"));
        assert!(targets.iter().any(|target| {
            target.wallet == "0x6e1d5040d0ac73709b0621f620d2a60b80d2d0f" && target.source == "configured"
        }));
    }

    #[test]
    fn guard_status_reports_manual_halt_reason() {
        let state_dir = temp_state_dir("guard");
        let halted = halt_guard(&state_dir, "manual_risk").expect("halt");
        let status = guard_status_value(&state_dir).expect("guard status");

        assert!(halted.halted);
        assert_eq!(status.get("active_halt_reason").and_then(|v| v.as_str()), Some("manual_risk"));

        let resumed = resume_guard(&state_dir).expect("resume");
        let resumed_status = guard_status_value(&state_dir).expect("guard status");
        assert!(!resumed.halted);
        assert_eq!(resumed_status.get("active_halt_reason"), Some(&Value::Null));
    }

    #[test]
    fn replay_helpers_reduce_market_and_user_events() {
        let state_dir = temp_state_dir("replay");
        let market_path = state_dir.join("market.jsonl");
        let user_path = state_dir.join("user.json");
        fs::write(
            &market_path,
            concat!(
                "{\"event_type\":\"best_bid_ask\",\"asset_id\":\"YES1\",\"best_bid\":\"0.41\",\"best_ask\":\"0.43\"}\n",
                "{\"event_type\":\"last_trade_price\",\"asset_id\":\"YES1\",\"price\":\"0.42\"}\n"
            ),
        )
        .expect("market events");
        fs::write(
            &user_path,
            "[{\"order_id\":\"order-1\",\"status\":\"FILLED\",\"filled_size\":12,\"remaining_size\":0}]",
        )
        .expect("user events");

        let market = replay_market_events(&json!({ "path": market_path })).expect("market replay");
        let user = replay_user_events(&json!({ "path": user_path })).expect("user replay");

        assert_eq!(market.get("applied").and_then(|v| v.as_u64()), Some(2));
        assert_eq!(
            market
                .get("snapshots")
                .and_then(|v| v.get("YES1"))
                .and_then(|v| v.get("last_trade_price"))
                .and_then(|v| v.as_f64()),
            Some(0.42)
        );
        assert_eq!(user.get("applied").and_then(|v| v.as_u64()), Some(1));
        assert_eq!(
            user.get("orders")
                .and_then(|v| v.as_array())
                .and_then(|v| v.first())
                .and_then(|v| v.get("status"))
                .and_then(|v| v.as_str()),
            Some("FILLED")
        );
    }

    #[test]
    fn normalize_live_orders_parses_cli_payload() {
        let records = normalize_live_orders(&json!([
            {
                "id": "order-1",
                "asset_id": "YES1",
                "market": "m1",
                "side": "BUY",
                "price": "0.45",
                "original_size": "10",
                "size_matched": "4",
                "status": "live",
                "created_at": "1710000000"
            }
        ]));

        assert_eq!(records.len(), 1);
        assert_eq!(records[0].order_id, "order-1");
        assert_eq!(records[0].remaining_shares, 6.0);
        assert_eq!(records[0].status, "LIVE");
        assert!(records[0].created_at.ends_with('Z'));
    }

    #[test]
    fn live_trade_guards_block_duplicate_open_orders() {
        let state_dir = temp_state_dir("live-guards");
        save_live_orders(
            &state_dir,
            &[LiveOrderRecord {
                order_id: "order-1".to_string(),
                token_id: "YES1".to_string(),
                market_id: "m1".to_string(),
                side: "BUY".to_string(),
                price: 0.45,
                shares: 10.0,
                status: "LIVE".to_string(),
                created_at: utc_now_iso(),
                updated_at: utc_now_iso(),
                remaining_shares: 10.0,
                filled_shares: 0.0,
                post_only: true,
            }],
        )
        .expect("save live orders");
        let guard = GuardState {
            trading_day: Utc::now().date_naive().to_string(),
            halted: false,
            halt_reason: None,
            live_error_count: 0,
            stream_error_count: 0,
        };
        let reasons = trade_guard_reasons(
            &state_dir,
            &ControlConfig {
                paper: false,
                auto_trade_enabled: true,
                ..ControlConfig::default()
            },
            &guard,
            &PaperAccount {
                cash: 0.0,
                realized_pnl: 0.0,
                positions: Vec::new(),
                trades: Vec::new(),
            },
            None,
            &MarketScan {
                market_id: "m1".to_string(),
                slug: Some("btc-higher".to_string()),
                question: "Will BTC close higher today?".to_string(),
                token_id: Some("YES1".to_string()),
                outcome: Some("YES".to_string()),
                midpoint: Some(0.45),
                bids_depth_usd: 1000.0,
                asks_depth_usd: 1000.0,
                liquidity_usd: Some(100_000.0),
                volume_usd: Some(1_000_000.0),
                hours_to_resolution: Some(8.0),
                complement_deviation_bps: Some(0.0),
                score: 20.0,
                status: "PASS".to_string(),
                reasons: Vec::new(),
                target_wallet_count: 2,
                target_trade_count: 10,
                target_net_volume: 100.0,
            },
        );

        assert!(reasons.iter().any(|reason| reason == "position_already_open"));
    }

    #[test]
    fn live_account_snapshot_uses_cli_balance_and_trade_history() {
        let state_dir = temp_state_dir("live-account");
        let script = write_mock_cli(&state_dir);
        unsafe { env::set_var("POLYMARKET_CLI_BIN", &script); }
        let snapshot = live_account_snapshot().expect("live snapshot");

        assert_eq!(snapshot.collateral_balance, 250.0);
        assert_eq!(snapshot.realized_pnl, 0.6);
        assert_eq!(snapshot.positions.len(), 1);
        assert_eq!(snapshot.positions[0].shares, 6.0);
        assert_eq!(snapshot.positions[0].avg_price, 0.4);
    }

    #[test]
    fn maybe_open_position_live_uses_cli_collateral_balance() {
        let state_dir = temp_state_dir("live-open");
        let script = write_mock_cli(&state_dir);
        unsafe { env::set_var("POLYMARKET_CLI_BIN", &script); }
        unsafe { env::set_var("STONKS_CLI_POLYMARKET_LIVE_ARMED", "1"); }
        let action = maybe_open_position(
            &state_dir,
            &ControlConfig {
                paper: false,
                auto_trade_enabled: true,
                auto_trade_min_score: 1.0,
                auto_trade_min_target_wallets: 1,
                max_position_fraction: 0.10,
                ..ControlConfig::default()
            },
            &[MarketScan {
                market_id: "m2".to_string(),
                slug: Some("eth-up".to_string()),
                question: "Will ETH rise?".to_string(),
                token_id: Some("YES2".to_string()),
                outcome: Some("YES".to_string()),
                midpoint: Some(0.50),
                bids_depth_usd: 1000.0,
                asks_depth_usd: 1000.0,
                liquidity_usd: Some(100_000.0),
                volume_usd: Some(1_000_000.0),
                hours_to_resolution: Some(8.0),
                complement_deviation_bps: Some(0.0),
                score: 20.0,
                status: "PASS".to_string(),
                reasons: Vec::new(),
                target_wallet_count: 2,
                target_trade_count: 10,
                target_net_volume: 100.0,
            }],
        )
        .expect("open position")
        .expect("action");

        assert_eq!(action.get("action").and_then(|v| v.as_str()), Some("BUY"));
        assert_eq!(action.get("shares").and_then(|v| v.as_f64()), Some(50.0));
        let records = load_live_orders(&state_dir).expect("live orders");
        assert_eq!(records.len(), 1);
        assert_eq!(records[0].order_id, "order-live-1");
    }

    #[test]
    fn live_price_normalization_is_side_aware() {
        assert_eq!(normalize_price_for_side(0.537, "buy", 0.01).expect("buy"), 0.53);
        assert_eq!(normalize_price_for_side(0.537, "sell", 0.01).expect("sell"), 0.54);
        assert_eq!(normalize_price_for_side(0.5800000000000001, "buy", 0.01).expect("drift"), 0.58);
    }

    #[test]
    fn live_order_response_rejection_is_error() {
        let response = json!({"success": false, "errorMsg": "INVALID_ORDER_MIN_SIZE"});
        let err = validate_live_order_response(&response).expect_err("reject");
        assert_eq!(err, "INVALID_ORDER_MIN_SIZE");
    }

    #[test]
    fn live_trade_guard_rejects_notional_below_minimum() {
        let state_dir = temp_state_dir("live-min-notional");
        let guard = GuardState {
            trading_day: Utc::now().date_naive().to_string(),
            halted: false,
            halt_reason: None,
            live_error_count: 0,
            stream_error_count: 0,
        };
        let snapshot = LiveAccountSnapshot {
            collateral_balance: 20.0,
            realized_pnl: 0.0,
            positions: Vec::new(),
        };
        let reasons = trade_guard_reasons(
            &state_dir,
            &ControlConfig {
                paper: false,
                auto_trade_enabled: true,
                auto_trade_min_score: 1.0,
                auto_trade_min_target_wallets: 1,
                max_position_fraction: 0.05,
                live_min_order_notional_usd: 5.0,
                ..ControlConfig::default()
            },
            &guard,
            &PaperAccount {
                cash: 0.0,
                realized_pnl: 0.0,
                positions: Vec::new(),
                trades: Vec::new(),
            },
            Some(&snapshot),
            &MarketScan {
                market_id: "m1".to_string(),
                slug: Some("btc-higher".to_string()),
                question: "Will BTC close higher today?".to_string(),
                token_id: Some("YES1".to_string()),
                outcome: Some("YES".to_string()),
                midpoint: Some(0.45),
                bids_depth_usd: 1000.0,
                asks_depth_usd: 1000.0,
                liquidity_usd: Some(100_000.0),
                volume_usd: Some(1_000_000.0),
                hours_to_resolution: Some(8.0),
                complement_deviation_bps: Some(0.0),
                score: 20.0,
                status: "PASS".to_string(),
                reasons: Vec::new(),
                target_wallet_count: 2,
                target_trade_count: 10,
                target_net_volume: 100.0,
            },
        );

        assert!(reasons.iter().any(|reason| reason == "live_notional_below_minimum"));
    }

    #[test]
    fn consensus_requires_multiple_agents_and_halves_single_vote_when_allowed() {
        let scan = MarketScan {
            market_id: "m1".to_string(),
            slug: Some("btc-higher".to_string()),
            question: "Will BTC close higher today?".to_string(),
            token_id: Some("YES1".to_string()),
            outcome: Some("YES".to_string()),
            midpoint: Some(0.45),
            bids_depth_usd: 1000.0,
            asks_depth_usd: 1000.0,
            liquidity_usd: Some(100_000.0),
            volume_usd: Some(1_000_000.0),
            hours_to_resolution: Some(8.0),
            complement_deviation_bps: Some(100.0),
            score: 20.0,
            status: "PASS".to_string(),
            reasons: Vec::new(),
            target_wallet_count: 0,
            target_trade_count: 0,
            target_net_volume: 0.0,
        };
        let strict = consensus_decision(
            &ControlConfig {
                auto_trade_min_score: 10.0,
                auto_trade_min_target_wallets: 1,
                consensus_min_buy_votes: 2,
                ..ControlConfig::default()
            },
            &scan,
        );
        let article_style = consensus_decision(
            &ControlConfig {
                auto_trade_min_score: 10.0,
                auto_trade_min_target_wallets: 1,
                consensus_min_buy_votes: 1,
                consensus_single_vote_fraction: 0.5,
                ..ControlConfig::default()
            },
            &scan,
        );

        assert_eq!(strict.buy_votes, 1);
        assert!(!strict.accepted);
        assert!(article_style.accepted);
        assert_eq!(article_style.position_fraction, 0.5);
    }

    #[test]
    fn consensus_accepts_convergence_and_whale_copy_agreement() {
        let scan = MarketScan {
            market_id: "m1".to_string(),
            slug: Some("btc-higher".to_string()),
            question: "Will BTC close higher today?".to_string(),
            token_id: Some("YES1".to_string()),
            outcome: Some("YES".to_string()),
            midpoint: Some(0.45),
            bids_depth_usd: 1000.0,
            asks_depth_usd: 1000.0,
            liquidity_usd: Some(100_000.0),
            volume_usd: Some(1_000_000.0),
            hours_to_resolution: Some(8.0),
            complement_deviation_bps: Some(100.0),
            score: 20.0,
            status: "PASS".to_string(),
            reasons: Vec::new(),
            target_wallet_count: 2,
            target_trade_count: 10,
            target_net_volume: 100.0,
        };
        let decision = consensus_decision(
            &ControlConfig {
                auto_trade_min_score: 10.0,
                auto_trade_min_target_wallets: 1,
                consensus_min_buy_votes: 2,
                ..ControlConfig::default()
            },
            &scan,
        );

        assert!(decision.accepted);
        assert_eq!(decision.buy_votes, 2);
        assert_eq!(decision.position_fraction, 1.0);
        assert!(decision.votes.iter().any(|vote| vote.agent == "whale_copy" && vote.action == "BUY"));
    }

    #[test]
    fn structural_scan_enforces_market_universe_filters() {
        let market = PolymarketMarket {
            market_id: "m1".to_string(),
            question: "Will the Lakers win tonight?".to_string(),
            slug: Some("lakers-vs-warriors".to_string()),
            condition_id: None,
            active: Some(true),
            closed: Some(false),
            liquidity_usd: Some(100_000.0),
            volume_usd: Some(500_000.0),
            end_date_iso: None,
            tokens: vec![MarketToken {
                token_id: "YES1".to_string(),
                outcome: Some("YES".to_string()),
                price: Some(0.5),
            }],
            raw: json!({"category":"sports"}),
        };
        let book = OrderBook {
            token_id: "YES1".to_string(),
            bids: vec![BookLevel { price: 0.49, size: 2_000.0 }],
            asks: vec![BookLevel { price: 0.51, size: 2_000.0 }],
            midpoint: Some(0.50),
            best_bid: Some(0.49),
            best_ask: Some(0.51),
            raw: json!({}),
        };
        let scan = structural_scan_market(
            &market,
            &book,
            &ControlConfig {
                crypto_only: true,
                block_sports: true,
                ..ControlConfig::default()
            },
        );

        assert_eq!(scan.status, "FILTERED");
        assert!(scan.reasons.iter().any(|reason| reason == "not_crypto_market"));
        assert!(scan.reasons.iter().any(|reason| reason == "blocked_sports_market"));
    }

    #[test]
    fn deep_auth_preflight_checks_mock_cli() {
        let state_dir = temp_state_dir("deep-auth");
        let script = write_mock_cli(&state_dir);
        unsafe { env::set_var("POLYMARKET_CLI_BIN", &script); }
        unsafe { env::set_var("POLYMARKET_PRIVATE_KEY", "0xtest"); }
        unsafe { env::set_var("STONKS_CLI_POLYMARKET_LIVE_ARMED", "1"); }

        let result = preflight(
            &state_dir,
            &ControlConfig {
                paper: false,
                ..ControlConfig::default()
            },
            &json!({ "deep_auth": true }),
        );

        assert_eq!(result.get("overall").and_then(|v| v.as_str()), Some("pass"));
        let checks = result.get("checks").and_then(|v| v.as_array()).expect("checks");
        assert!(checks.iter().any(|check| check.get("name").and_then(|v| v.as_str()) == Some("wallet_show")));
        assert!(checks.iter().any(|check| check.get("name").and_then(|v| v.as_str()) == Some("clob_balance_collateral")));
    }
}
