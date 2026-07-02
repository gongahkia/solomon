// SPDX-License-Identifier: MIT

//! Records Phase A perf result artifacts.
#![allow(missing_docs)]

use serde::Serialize;
use shibahama_perf::harness::{
    BenchResult, BenchStore, DEFAULT_SEED, EMBEDDING_DIMENSIONS, TOP_K, generated_item,
};
use std::env;
use std::fs;
use std::io::{Error as IoError, ErrorKind};
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::Instant;
use time::OffsetDateTime;
use time::format_description::well_known::Rfc3339;

const CONTENT_BYTES: usize = "item_00000000".len();

#[derive(Clone, Debug)]
struct Args {
    tiers: Vec<ScaleTier>,
    queries: usize,
    output_dir: PathBuf,
    omit_1m: Option<String>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct ScaleTier {
    label: &'static str,
    items: usize,
}

impl ScaleTier {
    const ONE_K: Self = Self {
        label: "1k",
        items: 1_000,
    };
    const TEN_K: Self = Self {
        label: "10k",
        items: 10_000,
    };
    const HUNDRED_K: Self = Self {
        label: "100k",
        items: 100_000,
    };
    const ONE_M: Self = Self {
        label: "1m",
        items: 1_000_000,
    };

    fn parse(value: &str) -> BenchResult<Self> {
        match value {
            "1k" => Ok(Self::ONE_K),
            "10k" => Ok(Self::TEN_K),
            "100k" => Ok(Self::HUNDRED_K),
            "1m" => Ok(Self::ONE_M),
            _ => Err(invalid_input(format!("unknown scale tier `{value}`"))),
        }
    }
}

#[derive(Debug, Serialize)]
struct PerfArtifact {
    manifest: Manifest,
    results: PerfResults,
}

#[derive(Debug, Serialize)]
struct Manifest {
    commit: String,
    rustc: String,
    os: String,
    cpu: String,
    ram_gb: f64,
    embedding_dim: usize,
    content_bytes: usize,
    seed: u64,
    scale: String,
    item_count: usize,
    query_count: usize,
    command: String,
    timestamp_utc: String,
}

#[derive(Debug, Serialize)]
struct PerfResults {
    recall_latency_ns: Option<LatencyStats>,
    resident_memory_bytes: Option<u64>,
    omitted: Option<String>,
}

#[derive(Clone, Copy, Debug, Serialize)]
struct LatencyStats {
    p50: u128,
    p95: u128,
    p99: u128,
}

fn main() -> BenchResult<()> {
    let args = parse_args()?;
    fs::create_dir_all(&args.output_dir)?;

    for tier in &args.tiers {
        let tier = *tier;
        let artifact = if tier == ScaleTier::ONE_M {
            if let Some(reason) = &args.omit_1m {
                omitted_artifact(tier, args.queries, reason.clone())?
            } else {
                measure_tier(tier, args.queries)?
            }
        } else {
            measure_tier(tier, args.queries)?
        };

        write_artifacts(&args.output_dir, &artifact)?;
    }

    if let Some(reason) = args.omit_1m
        && !args.tiers.contains(&ScaleTier::ONE_M)
    {
        let artifact = omitted_artifact(ScaleTier::ONE_M, args.queries, reason)?;
        write_artifacts(&args.output_dir, &artifact)?;
    }

    Ok(())
}

fn parse_args() -> BenchResult<Args> {
    let mut tiers = vec![ScaleTier::ONE_K];
    let mut queries = 30_usize;
    let mut output_dir = PathBuf::from("benchmarks/results/perf");
    let mut omit_1m = None;
    let mut raw_args = env::args().skip(1);

    while let Some(arg) = raw_args.next() {
        match arg.as_str() {
            "--tiers" => {
                let value = raw_args.next().ok_or_else(|| {
                    invalid_input("--tiers requires a comma-separated value".to_owned())
                })?;
                tiers = value
                    .split(',')
                    .map(ScaleTier::parse)
                    .collect::<BenchResult<Vec<_>>>()?;
            }
            "--queries" => {
                let value = raw_args
                    .next()
                    .ok_or_else(|| invalid_input("--queries requires a value".to_owned()))?;
                queries = value.parse()?;
            }
            "--output-dir" => {
                let value = raw_args
                    .next()
                    .ok_or_else(|| invalid_input("--output-dir requires a value".to_owned()))?;
                output_dir = PathBuf::from(value);
            }
            "--omit-1m" => {
                omit_1m = Some(
                    raw_args
                        .next()
                        .ok_or_else(|| invalid_input("--omit-1m requires a reason".to_owned()))?,
                );
            }
            "--help" | "-h" => {
                print_help();
                std::process::exit(0);
            }
            _ => return Err(invalid_input(format!("unknown argument `{arg}`"))),
        }
    }

    if queries == 0 {
        return Err(invalid_input(
            "--queries must be greater than zero".to_owned(),
        ));
    }

    Ok(Args {
        tiers,
        queries,
        output_dir,
        omit_1m,
    })
}

fn print_help() {
    eprintln!(
        "usage: record_perf --tiers 1k,10k,100k --queries 30 --output-dir benchmarks/results/perf [--omit-1m REASON]"
    );
}

fn measure_tier(tier: ScaleTier, queries: usize) -> BenchResult<PerfArtifact> {
    let store = BenchStore::populated(tier.items)?;
    let resident_memory_bytes = current_rss_bytes();
    let mut latencies = Vec::with_capacity(queries);

    for query_index in 0..queries {
        let query = generated_item(tier.items.saturating_add(query_index), DEFAULT_SEED).vector;
        let started_at = Instant::now();
        let candidates = store.recall(&query, TOP_K)?;
        let latency = started_at.elapsed().as_nanos();

        if candidates.is_empty() {
            return Err(invalid_input(format!(
                "recall returned no candidates for tier {}",
                tier.label
            )));
        }

        latencies.push(latency);
    }

    Ok(PerfArtifact {
        manifest: manifest(tier, queries)?,
        results: PerfResults {
            recall_latency_ns: Some(latency_stats(&mut latencies)),
            resident_memory_bytes,
            omitted: None,
        },
    })
}

fn omitted_artifact(tier: ScaleTier, queries: usize, reason: String) -> BenchResult<PerfArtifact> {
    Ok(PerfArtifact {
        manifest: manifest(tier, queries)?,
        results: PerfResults {
            recall_latency_ns: None,
            resident_memory_bytes: None,
            omitted: Some(reason),
        },
    })
}

fn manifest(tier: ScaleTier, queries: usize) -> BenchResult<Manifest> {
    Ok(Manifest {
        commit: command_output("git", &["rev-parse", "HEAD"])?,
        rustc: command_output("rustc", &["--version"])?,
        os: command_output("uname", &["-a"])?,
        cpu: cpu_name(),
        ram_gb: ram_gb(),
        embedding_dim: EMBEDDING_DIMENSIONS,
        content_bytes: CONTENT_BYTES,
        seed: DEFAULT_SEED,
        scale: tier.label.to_owned(),
        item_count: tier.items,
        query_count: queries,
        command: env::args().collect::<Vec<_>>().join(" "),
        timestamp_utc: OffsetDateTime::now_utc().format(&Rfc3339)?,
    })
}

fn latency_stats(latencies: &mut [u128]) -> LatencyStats {
    latencies.sort_unstable();

    LatencyStats {
        p50: percentile(latencies, 50, 100),
        p95: percentile(latencies, 95, 100),
        p99: percentile(latencies, 99, 100),
    }
}

fn percentile(sorted_values: &[u128], numerator: usize, denominator: usize) -> u128 {
    let max_index = sorted_values.len().saturating_sub(1);
    let position = max_index
        .saturating_mul(numerator)
        .saturating_add(denominator.saturating_sub(1))
        / denominator;

    sorted_values[position.min(max_index)]
}

fn write_artifacts(output_dir: &Path, artifact: &PerfArtifact) -> BenchResult<()> {
    let json_path = output_dir.join(format!("scale-{}.json", artifact.manifest.scale));
    let md_path = output_dir.join(format!("scale-{}.md", artifact.manifest.scale));
    let json = serde_json::to_string_pretty(artifact)?;

    fs::write(json_path, format!("{json}\n"))?;
    fs::write(md_path, markdown_table(artifact))?;

    Ok(())
}

fn markdown_table(artifact: &PerfArtifact) -> String {
    let (p50, p95, p99, rss, status) = if let Some(latency) = artifact.results.recall_latency_ns {
        (
            latency.p50.to_string(),
            latency.p95.to_string(),
            latency.p99.to_string(),
            artifact
                .results
                .resident_memory_bytes
                .map_or_else(|| "n/a".to_owned(), |bytes| bytes.to_string()),
            "measured".to_owned(),
        )
    } else {
        (
            "n/a".to_owned(),
            "n/a".to_owned(),
            "n/a".to_owned(),
            "n/a".to_owned(),
            artifact
                .results
                .omitted
                .clone()
                .unwrap_or_else(|| "omitted".to_owned()),
        )
    };

    format!(
        "# Perf Scale {scale}\n\n| scale | items | queries | recall p50 ns | recall p95 ns | recall p99 ns | rss bytes | status |\n| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |\n| {scale} | {items} | {queries} | {p50} | {p95} | {p99} | {rss} | {status} |\n",
        scale = artifact.manifest.scale,
        items = artifact.manifest.item_count,
        queries = artifact.manifest.query_count,
    )
}

fn current_rss_bytes() -> Option<u64> {
    let pid = std::process::id().to_string();
    let output = Command::new("ps")
        .args(["-o", "rss=", "-p", &pid])
        .output()
        .ok()?;

    if !output.status.success() {
        return None;
    }

    let rss_kib = String::from_utf8(output.stdout)
        .ok()?
        .trim()
        .parse::<u64>()
        .ok()?;

    rss_kib.checked_mul(1024)
}

fn cpu_name() -> String {
    command_output("sysctl", &["-n", "machdep.cpu.brand_string"])
        .or_else(|_| {
            command_output(
                "sh",
                &["-c", "grep -m1 'model name' /proc/cpuinfo | cut -d: -f2-"],
            )
        })
        .unwrap_or_else(|_| "unknown".to_owned())
        .trim()
        .to_owned()
}

fn ram_gb() -> f64 {
    let bytes = command_output("sysctl", &["-n", "hw.memsize"])
        .ok()
        .and_then(|value| value.parse::<f64>().ok())
        .or_else(|| {
            command_output(
                "sh",
                &["-c", "awk '/MemTotal/ { print $2 * 1024 }' /proc/meminfo"],
            )
            .ok()
            .and_then(|value| value.parse::<f64>().ok())
        })
        .unwrap_or(0.0);

    bytes / 1_073_741_824.0
}

fn command_output(command: &str, args: &[&str]) -> BenchResult<String> {
    let output = Command::new(command).args(args).output()?;

    if !output.status.success() {
        return Err(invalid_input(format!("command `{command}` failed")));
    }

    Ok(String::from_utf8(output.stdout)?.trim().to_owned())
}

fn invalid_input(message: String) -> Box<dyn std::error::Error + Send + Sync> {
    Box::new(IoError::new(ErrorKind::InvalidInput, message))
}
