#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum WeatherDirection {
    Above,
    Below,
}

#[derive(Clone, Debug, PartialEq)]
pub enum WeatherMarketType {
    Binary {
        threshold_f: f32,
        direction: WeatherDirection,
    },
    BinaryRange {
        min_f: f32,
        max_f: f32,
    },
    Range {
        ranges: Vec<(usize, f32, f32)>,
    },
}

#[derive(Clone, Debug, PartialEq)]
pub struct WeatherMarket {
    pub market_id: String,
    pub clob_token_ids: Vec<String>,
    pub question: String,
    pub outcome_prices: Vec<f64>,
    pub market_type: WeatherMarketType,
}

#[derive(Clone, Debug, PartialEq)]
pub struct WeatherOpportunity {
    pub market_id: String,
    pub clob_token_id: String,
    pub outcome_index: usize,
    pub edge_estimate: f64,
    pub confidence: f64,
    pub current_price: f64,
    pub temp_f: f32,
    pub reason: String,
}

#[derive(Clone, Copy, Debug)]
pub struct WeatherEdgeConfig {
    pub confidence_buffer_f: f32,
    pub min_edge_threshold: f64,
}

impl Default for WeatherEdgeConfig {
    fn default() -> Self {
        Self {
            confidence_buffer_f: 1.5,
            min_edge_threshold: 0.10,
        }
    }
}

pub fn parse_metar_temp_f(content: &[u8]) -> Result<f32, String> {
    let text = std::str::from_utf8(content).map_err(|err| err.to_string())?;
    let observation = text
        .lines()
        .find(|line| {
            line.split_whitespace().any(|part| part.ends_with("KT"))
                && line.split_whitespace().any(|part| part.contains('/'))
        })
        .ok_or_else(|| "METAR observation missing temperature/dewpoint field".to_string())?;
    for part in observation.split_whitespace() {
        let Some((temp, _dewpoint)) = part.split_once('/') else { continue; };
        if let Some(celsius) = parse_metar_celsius(temp) {
            return Ok((celsius * 9.0 / 5.0) + 32.0);
        }
    }
    Err("METAR temperature field not found".to_string())
}

pub fn is_weather_market(question: &str, city_terms: &[&str]) -> bool {
    let lowered = question.to_ascii_lowercase();
    city_terms.iter().any(|term| lowered.contains(&term.to_ascii_lowercase()))
        && ["temperature", "temp", "degrees", "°f", "fahrenheit"]
            .iter()
            .any(|term| lowered.contains(term))
}

pub fn parse_weather_market_type(question: &str) -> Result<WeatherMarketType, String> {
    let lowered = question.to_ascii_lowercase();
    if let Some((min_f, max_f)) = parse_between_range(&lowered) {
        return Ok(WeatherMarketType::BinaryRange { min_f, max_f });
    }
    if let Some(ranges) = parse_bucket_ranges(&lowered) {
        return Ok(WeatherMarketType::Range { ranges });
    }
    if let Some(threshold_f) = first_number_before_or_after(&lowered, &["above", "over", "exceed", "higher than", "at least", "or higher"]) {
        return Ok(WeatherMarketType::Binary {
            threshold_f,
            direction: WeatherDirection::Above,
        });
    }
    if let Some(threshold_f) = first_number_before_or_after(&lowered, &["below", "under", "less than", "at most", "or lower"]) {
        return Ok(WeatherMarketType::Binary {
            threshold_f,
            direction: WeatherDirection::Below,
        });
    }
    Err(format!("could not parse weather market type: {question}"))
}

pub fn evaluate_weather_opportunity(
    temp_f: f32,
    markets: &[WeatherMarket],
    cfg: WeatherEdgeConfig,
) -> Option<WeatherOpportunity> {
    markets
        .iter()
        .filter_map(|market| calculate_edge(temp_f, market, cfg))
        .filter(|opportunity| opportunity.edge_estimate >= cfg.min_edge_threshold)
        .max_by(|a, b| {
            a.edge_estimate
                .partial_cmp(&b.edge_estimate)
                .unwrap_or(std::cmp::Ordering::Equal)
        })
}

fn calculate_edge(temp_f: f32, market: &WeatherMarket, cfg: WeatherEdgeConfig) -> Option<WeatherOpportunity> {
    match &market.market_type {
        WeatherMarketType::Binary { threshold_f, direction } => {
            calculate_binary_edge(temp_f, *threshold_f, *direction, market, cfg)
        }
        WeatherMarketType::BinaryRange { min_f, max_f } => {
            calculate_binary_range_edge(temp_f, *min_f, *max_f, market, cfg)
        }
        WeatherMarketType::Range { ranges } => calculate_range_edge(temp_f, ranges, market),
    }
}

fn calculate_binary_edge(
    temp_f: f32,
    threshold_f: f32,
    direction: WeatherDirection,
    market: &WeatherMarket,
    cfg: WeatherEdgeConfig,
) -> Option<WeatherOpportunity> {
    let buffer = cfg.confidence_buffer_f;
    let (buy_yes, distance) = match direction {
        WeatherDirection::Above if temp_f >= threshold_f + buffer => (true, temp_f - threshold_f),
        WeatherDirection::Above if temp_f <= threshold_f - buffer => (false, threshold_f - temp_f),
        WeatherDirection::Below if temp_f <= threshold_f - buffer => (true, threshold_f - temp_f),
        WeatherDirection::Below if temp_f >= threshold_f + buffer => (false, temp_f - threshold_f),
        _ => return None,
    };
    let outcome_index = if buy_yes { 0 } else { 1 };
    let current_price = *market.outcome_prices.get(outcome_index)?;
    let clob_token_id = market.clob_token_ids.get(outcome_index)?.clone();
    let confidence = (distance / (buffer * 2.0)).min(1.0) as f64;
    let side = if buy_yes { "YES" } else { "NO" };
    Some(WeatherOpportunity {
        market_id: market.market_id.clone(),
        clob_token_id,
        outcome_index,
        edge_estimate: 1.0 - current_price,
        confidence,
        current_price,
        temp_f,
        reason: format!("temperature {temp_f:.1}F vs threshold {threshold_f:.1}F -> {side}"),
    })
}

fn calculate_binary_range_edge(
    temp_f: f32,
    min_f: f32,
    max_f: f32,
    market: &WeatherMarket,
    cfg: WeatherEdgeConfig,
) -> Option<WeatherOpportunity> {
    let buffer = cfg.confidence_buffer_f;
    let (buy_yes, distance) = if temp_f >= min_f + buffer && temp_f <= max_f - buffer {
        (true, (temp_f - (min_f + buffer)).min((max_f - buffer) - temp_f).max(0.0))
    } else if temp_f <= min_f - buffer {
        (false, (min_f - buffer) - temp_f)
    } else if temp_f >= max_f + buffer {
        (false, temp_f - (max_f + buffer))
    } else {
        return None;
    };
    let outcome_index = if buy_yes { 0 } else { 1 };
    let current_price = *market.outcome_prices.get(outcome_index)?;
    let clob_token_id = market.clob_token_ids.get(outcome_index)?.clone();
    let confidence = if buy_yes {
        (distance / ((max_f - min_f).max(1.0) / 2.0)).min(1.0) as f64
    } else {
        (distance / (buffer * 2.0)).min(1.0) as f64
    };
    let side = if buy_yes { "YES" } else { "NO" };
    Some(WeatherOpportunity {
        market_id: market.market_id.clone(),
        clob_token_id,
        outcome_index,
        edge_estimate: 1.0 - current_price,
        confidence,
        current_price,
        temp_f,
        reason: format!("temperature {temp_f:.1}F vs range {min_f:.1}-{max_f:.1}F -> {side}"),
    })
}

fn calculate_range_edge(temp_f: f32, ranges: &[(usize, f32, f32)], market: &WeatherMarket) -> Option<WeatherOpportunity> {
    for (outcome_index, min_f, max_f) in ranges {
        if temp_f >= *min_f && temp_f < *max_f {
            let current_price = *market.outcome_prices.get(*outcome_index)?;
            let clob_token_id = market.clob_token_ids.get(*outcome_index)?.clone();
            let width = (*max_f - *min_f).max(1.0);
            let distance = (temp_f - *min_f).min(*max_f - temp_f).max(0.0);
            return Some(WeatherOpportunity {
                market_id: market.market_id.clone(),
                clob_token_id,
                outcome_index: *outcome_index,
                edge_estimate: 1.0 - current_price,
                confidence: (distance / (width / 2.0)).min(1.0) as f64,
                current_price,
                temp_f,
                reason: format!("temperature {temp_f:.1}F in bucket {min_f:.1}-{max_f:.1}F"),
            });
        }
    }
    None
}

fn parse_metar_celsius(value: &str) -> Option<f32> {
    if value.is_empty() || value.len() > 4 {
        return None;
    }
    if let Some(rest) = value.strip_prefix('M') {
        return rest.parse::<f32>().ok().map(|item| -item);
    }
    value.parse::<f32>().ok()
}

fn first_number_before_or_after(text: &str, phrases: &[&str]) -> Option<f32> {
    let numbers = extract_numbers(text);
    for phrase in phrases {
        if text.contains(phrase) {
            return numbers.first().copied();
        }
    }
    None
}

fn parse_between_range(text: &str) -> Option<(f32, f32)> {
    if !text.contains("between") && !text.contains("within") {
        return None;
    }
    let numbers = extract_numbers(text);
    if numbers.len() >= 2 {
        Some((numbers[0].min(numbers[1]), numbers[0].max(numbers[1])))
    } else {
        None
    }
}

fn parse_bucket_ranges(text: &str) -> Option<Vec<(usize, f32, f32)>> {
    let numbers = extract_numbers(text);
    if numbers.len() < 4 || numbers.len() % 2 != 0 {
        return None;
    }
    let mut ranges = Vec::new();
    for (idx, pair) in numbers.chunks_exact(2).enumerate() {
        if pair[0] < pair[1] {
            ranges.push((idx, pair[0], pair[1]));
        }
    }
    if ranges.len() >= 2 { Some(ranges) } else { None }
}

fn extract_numbers(text: &str) -> Vec<f32> {
    let mut out = Vec::new();
    let mut current = String::new();
    for ch in text.chars() {
        if ch.is_ascii_digit() || ch == '.' {
            current.push(ch);
        } else if !current.is_empty() {
            if let Ok(value) = current.parse::<f32>() {
                out.push(value);
            }
            current.clear();
        }
    }
    if !current.is_empty() {
        if let Ok(value) = current.parse::<f32>() {
            out.push(value);
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_metar_positive_and_negative_temperatures() {
        let hot = b"2025/07/15 18:00\nKNYC 151800Z 18012KT 10SM SCT250 36/18 A2990";
        let cold = b"2025/01/29 14:51\nKNYC 291451Z 32008KT 10SM FEW250 M04/M17 A3034";

        assert!((parse_metar_temp_f(hot).expect("hot") - 96.8).abs() < 0.1);
        assert!((parse_metar_temp_f(cold).expect("cold") - 24.8).abs() < 0.1);
    }

    #[test]
    fn parses_weather_market_types() {
        assert_eq!(
            parse_weather_market_type("Will NYC temperature exceed 95F?").expect("above"),
            WeatherMarketType::Binary {
                threshold_f: 95.0,
                direction: WeatherDirection::Above,
            }
        );
        assert_eq!(
            parse_weather_market_type("Will New York temp be between 90 and 94F?").expect("range"),
            WeatherMarketType::BinaryRange { min_f: 90.0, max_f: 94.0 }
        );
    }

    #[test]
    fn evaluates_best_weather_edge() {
        let markets = vec![WeatherMarket {
            market_id: "weather-1".to_string(),
            clob_token_ids: vec!["YES1".to_string(), "NO1".to_string()],
            question: "Will NYC temperature exceed 95F?".to_string(),
            outcome_prices: vec![0.40, 0.60],
            market_type: WeatherMarketType::Binary {
                threshold_f: 95.0,
                direction: WeatherDirection::Above,
            },
        }];
        let opportunity = evaluate_weather_opportunity(98.0, &markets, WeatherEdgeConfig::default()).expect("opportunity");

        assert_eq!(opportunity.clob_token_id, "YES1");
        assert_eq!(opportunity.outcome_index, 0);
        assert!((opportunity.edge_estimate - 0.60).abs() < 0.000001);
        assert!(opportunity.confidence > 0.9);
    }

    #[test]
    fn ignores_temperatures_inside_confidence_buffer() {
        let market = WeatherMarket {
            market_id: "weather-1".to_string(),
            clob_token_ids: vec!["YES1".to_string(), "NO1".to_string()],
            question: "Will NYC temperature exceed 95F?".to_string(),
            outcome_prices: vec![0.40, 0.60],
            market_type: WeatherMarketType::Binary {
                threshold_f: 95.0,
                direction: WeatherDirection::Above,
            },
        };

        assert!(evaluate_weather_opportunity(95.5, &[market], WeatherEdgeConfig::default()).is_none());
    }
}
