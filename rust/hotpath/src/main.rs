use std::io::{self, BufRead as _, Read as _, Write as _};
use std::path::PathBuf;

use stonks_polymarket_hotpath::{DaemonState, control::{ControlRequest, handle_control}, protocol::handle_command, replay::replay_commands};

fn main() {
    let mut args = std::env::args().skip(1);
    match args.next().as_deref() {
        Some("ping") => {
            println!("PONG");
        }
        Some("replay") => {
            let Some(path) = args.next() else {
                eprintln!("usage: stonks-polymarket-hotpath replay <path>");
                std::process::exit(2);
            };
            match replay_commands(&PathBuf::from(path)) {
                Ok(lines) => {
                    for line in lines {
                        println!("{line}");
                    }
                }
                Err(err) => {
                    eprintln!("{err}");
                    std::process::exit(1);
                }
            }
        }
        Some("daemon") => {
            let stdin = io::stdin();
            let mut state = DaemonState::default();
            let mut stdout = io::stdout().lock();
            for line in stdin.lock().lines() {
                let Ok(line) = line else {
                    let _ = writeln!(stdout, "ERR failed to read line");
                    break;
                };
                let response = handle_command(&mut state, &line);
                let _ = writeln!(stdout, "{response}");
                let _ = stdout.flush();
            }
        }
        Some("control") => {
            let Some(op) = args.next() else {
                eprintln!("usage: stonks-polymarket-hotpath control <op>");
                std::process::exit(2);
            };
            let mut body = String::new();
            if let Err(err) = io::stdin().read_to_string(&mut body) {
                eprintln!("{err}");
                std::process::exit(1);
            }
            let request = if body.trim().is_empty() {
                ControlRequest::default()
            } else {
                match serde_json::from_str::<ControlRequest>(&body) {
                    Ok(request) => request,
                    Err(err) => {
                        eprintln!("{err}");
                        std::process::exit(1);
                    }
                }
            };
            match handle_control(&op, request) {
                Ok(value) => println!("{}", serde_json::to_string(&value).unwrap_or_else(|_| "{}".to_string())),
                Err(err) => {
                    eprintln!("{err}");
                    std::process::exit(1);
                }
            }
        }
        _ => {
            eprintln!("usage: stonks-polymarket-hotpath <ping|replay|daemon|control>");
            std::process::exit(2);
        }
    }
}
