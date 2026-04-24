use std::fs;
use std::path::Path;

use crate::daemon::DaemonState;
use crate::protocol::handle_command;

pub fn replay_commands(path: &Path) -> Result<Vec<String>, String> {
    let text = fs::read_to_string(path).map_err(|err| err.to_string())?;
    let mut state = DaemonState::default();
    let mut out = Vec::new();
    for line in text.lines() {
        let trimmed = line.trim();
        if trimmed.is_empty() || trimmed.starts_with('#') {
            continue;
        }
        out.push(handle_command(&mut state, trimmed));
    }
    Ok(out)
}

#[cfg(test)]
mod tests {
    use std::path::PathBuf;

    use super::replay_commands;

    #[test]
    fn replay_runs_protocol_fixture() {
        let mut path = std::env::temp_dir();
        path.push("stonks-rust-hotpath-replay.txt");
        std::fs::write(
            &path,
            "PING\nBOOK token=YES1 bid=0.57 ask=0.60\nORDER id=o1 token=YES1 market=m1 side=BUY price=0.58 shares=10 post_only=true now=100\nSTATUS\n",
        )
        .unwrap();
        let out = replay_commands(&PathBuf::from(&path)).unwrap();
        assert_eq!(out[0], "PONG");
        assert!(out[2].starts_with("OK order_id=o1"));
        assert_eq!(out[3], "OK market_count=1 open_order_count=1");
        let _ = std::fs::remove_file(path);
    }
}
