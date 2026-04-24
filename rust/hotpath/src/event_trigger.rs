use std::collections::HashSet;
use std::time::{SystemTime, UNIX_EPOCH};

const V1_LEN: usize = 28;
const V2_LEN: usize = 176;
const STR_LEN: usize = 64;

#[derive(Clone, Debug, PartialEq)]
pub struct TriggerInstruction {
    pub market_id: String,
    pub clob_token_id: String,
    pub outcome_index: u32,
    pub edge_estimate: f64,
    pub confidence: f64,
    pub current_price: f64,
}

#[derive(Clone, Debug, PartialEq)]
pub enum TriggerMessage {
    Decision {
        action: u8,
    },
    V1 {
        message_id: [u8; 16],
        temp_f: f32,
        timestamp_ns: u64,
    },
    V2 {
        message_id: [u8; 16],
        temp_f: f32,
        timestamp_ns: u64,
        instruction: TriggerInstruction,
    },
}

#[derive(Debug, Default)]
pub struct TriggerDeduper {
    seen: HashSet<[u8; 16]>,
}

impl TriggerDeduper {
    pub fn accept(&mut self, message: &TriggerMessage) -> bool {
        let Some(id) = message.message_id() else {
            return true;
        };
        self.seen.insert(id)
    }
}

impl TriggerMessage {
    pub fn parse(data: &[u8]) -> Result<Self, String> {
        match data.len() {
            1 => Ok(Self::Decision { action: data[0] }),
            V1_LEN => Ok(Self::V1 {
                message_id: fixed_16(&data[0..16])?,
                temp_f: f32::from_be_bytes(fixed_4(&data[16..20])?),
                timestamp_ns: u64::from_be_bytes(fixed_8(&data[20..28])?),
            }),
            V2_LEN => {
                let version = u32::from_be_bytes(fixed_4(&data[172..176])?);
                if version != 2 {
                    return Err(format!("unsupported trigger protocol version: {version}"));
                }
                Ok(Self::V2 {
                    message_id: fixed_16(&data[0..16])?,
                    temp_f: f32::from_be_bytes(fixed_4(&data[16..20])?),
                    timestamp_ns: u64::from_be_bytes(fixed_8(&data[20..28])?),
                    instruction: TriggerInstruction {
                        market_id: parse_padded_string(&data[28..92])?,
                        clob_token_id: parse_padded_string(&data[92..156])?,
                        edge_estimate: f32::from_be_bytes(fixed_4(&data[156..160])?) as f64,
                        confidence: f32::from_be_bytes(fixed_4(&data[160..164])?) as f64,
                        current_price: f32::from_be_bytes(fixed_4(&data[164..168])?) as f64,
                        outcome_index: u32::from_be_bytes(fixed_4(&data[168..172])?),
                    },
                })
            }
            len => Err(format!("invalid trigger payload size: {len}")),
        }
    }

    pub fn message_id(&self) -> Option<[u8; 16]> {
        match self {
            Self::V1 { message_id, .. } | Self::V2 { message_id, .. } => Some(*message_id),
            Self::Decision { .. } => None,
        }
    }

    pub fn latency_ms(&self, now_ns: u64) -> Option<u64> {
        let timestamp_ns = match self {
            Self::V1 { timestamp_ns, .. } | Self::V2 { timestamp_ns, .. } => *timestamp_ns,
            Self::Decision { .. } => return None,
        };
        Some(now_ns.saturating_sub(timestamp_ns) / 1_000_000)
    }
}

pub fn build_trigger_v2(
    message_id: [u8; 16],
    temp_f: f32,
    timestamp_ns: u64,
    instruction: &TriggerInstruction,
) -> Result<[u8; V2_LEN], String> {
    let mut payload = [0u8; V2_LEN];
    payload[0..16].copy_from_slice(&message_id);
    payload[16..20].copy_from_slice(&temp_f.to_be_bytes());
    payload[20..28].copy_from_slice(&timestamp_ns.to_be_bytes());
    write_padded_string(&mut payload[28..92], &instruction.market_id)?;
    write_padded_string(&mut payload[92..156], &instruction.clob_token_id)?;
    payload[156..160].copy_from_slice(&(instruction.edge_estimate as f32).to_be_bytes());
    payload[160..164].copy_from_slice(&(instruction.confidence as f32).to_be_bytes());
    payload[164..168].copy_from_slice(&(instruction.current_price as f32).to_be_bytes());
    payload[168..172].copy_from_slice(&instruction.outcome_index.to_be_bytes());
    payload[172..176].copy_from_slice(&2u32.to_be_bytes());
    Ok(payload)
}

pub fn now_ns() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos() as u64
}

fn parse_padded_string(bytes: &[u8]) -> Result<String, String> {
    let end = bytes.iter().position(|byte| *byte == 0).unwrap_or(bytes.len());
    String::from_utf8(bytes[..end].to_vec()).map_err(|err| err.to_string())
}

fn write_padded_string(target: &mut [u8], value: &str) -> Result<(), String> {
    if target.len() != STR_LEN {
        return Err("invalid padded string target length".to_string());
    }
    let bytes = value.as_bytes();
    if bytes.len() > STR_LEN {
        return Err(format!("trigger string exceeds {STR_LEN} bytes: {value}"));
    }
    target[..bytes.len()].copy_from_slice(bytes);
    Ok(())
}

fn fixed_4(value: &[u8]) -> Result<[u8; 4], String> {
    value.try_into().map_err(|_| "expected 4 bytes".to_string())
}

fn fixed_8(value: &[u8]) -> Result<[u8; 8], String> {
    value.try_into().map_err(|_| "expected 8 bytes".to_string())
}

fn fixed_16(value: &[u8]) -> Result<[u8; 16], String> {
    value.try_into().map_err(|_| "expected 16 bytes".to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn trigger_v2_round_trip_preserves_instruction() {
        let instruction = TriggerInstruction {
            market_id: "m1".to_string(),
            clob_token_id: "token1".to_string(),
            outcome_index: 1,
            edge_estimate: 0.21,
            confidence: 0.82,
            current_price: 0.61,
        };
        let payload = build_trigger_v2([7u8; 16], 96.5, 1_000_000_000, &instruction).expect("payload");
        let parsed = TriggerMessage::parse(&payload).expect("parse");

        match parsed {
            TriggerMessage::V2 { message_id, temp_f, timestamp_ns, instruction: parsed_instruction } => {
                assert_eq!(message_id, [7u8; 16]);
                assert_eq!(temp_f, 96.5);
                assert_eq!(timestamp_ns, 1_000_000_000);
                assert_eq!(parsed_instruction.market_id, instruction.market_id);
                assert_eq!(parsed_instruction.clob_token_id, instruction.clob_token_id);
                assert_eq!(parsed_instruction.outcome_index, instruction.outcome_index);
                assert!((parsed_instruction.edge_estimate - instruction.edge_estimate).abs() < 0.000001);
            }
            other => panic!("unexpected trigger: {other:?}"),
        }
    }

    #[test]
    fn trigger_deduper_rejects_repeated_message_id() {
        let mut deduper = TriggerDeduper::default();
        let message = TriggerMessage::V1 {
            message_id: [9u8; 16],
            temp_f: 80.0,
            timestamp_ns: 1,
        };

        assert!(deduper.accept(&message));
        assert!(!deduper.accept(&message));
        assert!(deduper.accept(&TriggerMessage::Decision { action: 1 }));
    }

    #[test]
    fn trigger_parser_rejects_bad_version() {
        let mut payload = [0u8; V2_LEN];
        payload[172..176].copy_from_slice(&3u32.to_be_bytes());

        let err = TriggerMessage::parse(&payload).expect_err("bad version");
        assert!(err.contains("unsupported trigger protocol version"));
    }
}
