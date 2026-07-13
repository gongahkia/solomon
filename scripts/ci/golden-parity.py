#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Run the golden-vector parity suite across Rust, Python, and Node."""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "scripts" / "ci" / "golden-parity.json"
PY_BINDING = ROOT / "bindings" / "python" / "python"
if PY_BINDING.exists():
    sys.path.insert(0, str(PY_BINDING))


def main() -> int:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    validate_fixture(fixture)
    expected = fixture["expected"]
    outputs = {
        "python": run_python_lane(fixture),
        "node": run_json_command(
            ["node", "scripts/ci/golden-parity-node.mjs", str(FIXTURE)],
        ),
        "rust": run_json_command(
            [
                "cargo",
                "run",
                "-q",
                "--manifest-path",
                "core/Cargo.toml",
                "--example",
                "golden_parity",
                "--",
                str(FIXTURE),
            ],
        ),
        "http": run_http_lane(fixture),
    }

    failures: list[str] = []
    for lane, output in outputs.items():
        if output != expected:
            failures.append(diff_payload(lane, expected, output))

    if failures:
        print("\n\n".join(failures), file=sys.stderr)
        return 1

    print("golden parity passed: rust, python, node, http")
    return 0


def validate_fixture(fixture: dict[str, Any]) -> None:
    if fixture.get("schema_version") != 1:
        raise AssertionError("unsupported fixture schema_version")
    if fixture.get("contract") != "shibahama.memory":
        raise AssertionError("unsupported fixture contract")


def run_json_command(command: list[str]) -> dict[str, Any]:
    output = subprocess.check_output(command, cwd=ROOT, text=True)
    return json.loads(output)


def run_python_lane(fixture: dict[str, Any]) -> dict[str, Any]:
    import shibahama

    with tempfile.NamedTemporaryFile() as store:
        engine = shibahama.Shibahama(
            store.name,
            fixture["dimensions"],
            fixture["capacity"],
        )
        ids: dict[str, str] = {}
        output: dict[str, Any] = {
            "queries": [],
            "timelines": [],
            "signals": [],
            "errors": [],
            "memories": [],
            "why": [],
        }

        for step in fixture["steps"]:
            if step["op"] == "write":
                item = engine.write(
                    step["content"],
                    vector=step["vector"],
                    source_kind=step["source_kind"],
                    source_ref=step["source_ref"],
                    ingested_by=step["ingested_by"],
                    valid_from_unix=step["valid_from_unix"],
                    ingested_at_unix=step["ingested_at_unix"],
                )
                ids[step["source_ref"]] = item.id
            elif step["op"] == "invalidate":
                if not engine.invalidate(ids[step["source_ref"]], step["valid_to_unix"]):
                    raise AssertionError(f"failed to invalidate {step['source_ref']}")
            else:
                raise AssertionError(f"unknown step op: {step['op']}")

        for query in fixture["queries"]:
            recalled = engine.recall(
                query["vector"],
                query["top_k"],
                now_unix=query["now_unix"],
                raw_query_context=query["raw_query_context"],
                include_cold=query["include_cold"],
            )
            output["queries"].append(
                {
                    "name": query["name"],
                    "recall": [normalize_python_candidate(candidate) for candidate in recalled],
                }
            )

        for query in fixture["timelines"]:
            recalled = engine.timeline(
                query["vector"],
                query["top_k"],
                as_of_unix=query["as_of_unix"],
                include_cold=query["include_cold"],
            )
            output["timelines"].append(
                {
                    "name": query["name"],
                    "recall": [normalize_python_candidate(candidate) for candidate in recalled],
                }
            )

        memories = sorted(
            [normalize_python_memory(memory) for memory in engine.memory_items()],
            key=lambda memory: memory["source_ref"],
        )
        output["memories"] = memories
        output["why"] = [
            normalize_python_why(
                require_trace(engine.why(ids[memory["source_ref"]], fixture["why_now_unix"]))
            )
            for memory in memories
        ]
        for signal in fixture["human_signals"]:
            if signal["op"] != "affirm":
                raise AssertionError(f"unknown human signal op: {signal['op']}")
            outcome = engine.affirm(ids[signal["source_ref"]])
            output["signals"].append({"name": signal["name"], "applied": outcome["applied"]})
        for query in fixture["errors"]:
            if query["op"] != "recall":
                raise AssertionError(f"unknown error operation: {query['op']}")
            try:
                engine.recall(query["vector"], query["top_k"], now_unix=query["now_unix"])
            except RuntimeError as error:
                code = error_code(str(error))
            else:
                raise AssertionError(f"{query['name']} should fail")
            if code != query["code"]:
                raise AssertionError(f"{query['name']} returned {code}")
            output["errors"].append({"name": query["name"], "code": code})

    return output


def run_http_lane(fixture: dict[str, Any]) -> dict[str, Any]:
    namespace = "golden-parity"
    api_key = "golden-parity"
    port = unused_local_port()
    base_url = f"http://127.0.0.1:{port}"

    with tempfile.TemporaryDirectory() as tempdir:
        process = subprocess.Popen(
            [
                "cargo",
                "run",
                "-q",
                "-p",
                "shibahama-cli",
                "--",
                "serve",
                "--path",
                str(Path(tempdir) / "server.redb"),
                "--dimensions",
                str(fixture["dimensions"]),
                "--capacity",
                str(fixture["capacity"]),
                "--api-key",
                api_key,
                "--namespace",
                namespace,
                "--bind",
                f"127.0.0.1:{port}",
            ],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            wait_for_server(base_url, api_key, namespace, process)
            ids: dict[str, str] = {}
            output: dict[str, Any] = {
                "queries": [],
                "timelines": [],
                "signals": [],
                "errors": [],
                "memories": [],
                "why": [],
            }

            for step in fixture["steps"]:
                if step["op"] == "write":
                    item = server_request(
                        base_url,
                        api_key,
                        namespace,
                        "POST",
                        "/write",
                        {
                            "content": step["content"],
                            "vector": step["vector"],
                            "source_kind": step["source_kind"],
                            "source_ref": step["source_ref"],
                            "ingested_by": step["ingested_by"],
                            "valid_from_unix": step["valid_from_unix"],
                            "ingested_at_unix": step["ingested_at_unix"],
                        },
                    )
                    ids[step["source_ref"]] = item["id"]
                elif step["op"] == "invalidate":
                    invalidated = server_request(
                        base_url,
                        api_key,
                        namespace,
                        "POST",
                        "/invalidate",
                        {
                            "memory_id": ids[step["source_ref"]],
                            "valid_to_unix": step["valid_to_unix"],
                        },
                    )
                    if not invalidated["applied"]:
                        raise AssertionError(f"failed to invalidate {step['source_ref']}")
                else:
                    raise AssertionError(f"unknown step op: {step['op']}")

            for query in fixture["queries"]:
                recalled = server_request(
                    base_url,
                    api_key,
                    namespace,
                    "POST",
                    "/recall",
                    {
                        "query_vector": query["vector"],
                        "top_k": query["top_k"],
                        "now_unix": query["now_unix"],
                        "raw_query_context": query["raw_query_context"],
                        "include_cold": query["include_cold"],
                    },
                )
                output["queries"].append(
                    {
                        "name": query["name"],
                        "recall": [normalize_server_candidate(candidate, namespace) for candidate in recalled],
                    }
                )

            for query in fixture["timelines"]:
                recalled = server_request(
                    base_url,
                    api_key,
                    namespace,
                    "POST",
                    "/timeline",
                    {
                        "query_vector": query["vector"],
                        "top_k": query["top_k"],
                        "as_of_unix": query["as_of_unix"],
                        "raw_query_context": query["raw_query_context"],
                        "include_cold": query["include_cold"],
                    },
                )
                output["timelines"].append(
                    {
                        "name": query["name"],
                        "recall": [
                            normalize_server_candidate(candidate, namespace) for candidate in recalled
                        ],
                    }
                )

            inspected = server_request(base_url, api_key, namespace, "GET", "/inspect")
            memories = sorted(
                [normalize_server_memory(memory, namespace) for memory in inspected["memories"]],
                key=lambda memory: memory["source_ref"],
            )
            output["memories"] = memories
            output["why"] = [
                normalize_server_why(
                    server_request(
                        base_url,
                        api_key,
                        namespace,
                        "GET",
                        f"/why/{urllib.parse.quote(ids[memory['source_ref']])}?now_unix={fixture['why_now_unix']}",
                    ),
                    namespace,
                )
                for memory in memories
            ]
            for signal in fixture["human_signals"]:
                if signal["op"] != "affirm":
                    raise AssertionError(f"unknown human signal op: {signal['op']}")
                outcome = server_request(
                    base_url,
                    api_key,
                    namespace,
                    "POST",
                    "/affirm",
                    {"memory_id": ids[signal["source_ref"]]},
                )
                output["signals"].append(
                    {"name": signal["name"], "applied": outcome["applied"]}
                )
            for query in fixture["errors"]:
                if query["op"] != "recall":
                    raise AssertionError(f"unknown error operation: {query['op']}")
                try:
                    server_request(
                        base_url,
                        api_key,
                        namespace,
                        "POST",
                        "/recall",
                        {
                            "query_vector": query["vector"],
                            "top_k": query["top_k"],
                            "now_unix": query["now_unix"],
                        },
                    )
                except urllib.error.HTTPError as error:
                    payload = json.loads(error.read().decode("utf-8"))
                    code = error_code(payload["error"])
                    if payload.get("code") != code:
                        raise AssertionError(f"HTTP error code mismatch: {payload}")
                    if payload.get("severity") != "fatal" or payload.get("retryable") is not False:
                        raise AssertionError(f"HTTP error metadata mismatch: {payload}")
                else:
                    raise AssertionError(f"{query['name']} should fail")
                if code != query["code"]:
                    raise AssertionError(f"{query['name']} returned {code}")
                output["errors"].append({"name": query["name"], "code": code})
            return output
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def unused_local_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def wait_for_server(
    base_url: str,
    api_key: str,
    namespace: str,
    process: subprocess.Popen[bytes],
) -> None:
    for _ in range(40):
        if process.poll() is not None:
            raise AssertionError(f"HTTP contract server exited with {process.returncode}")
        try:
            server_request(base_url, api_key, namespace, "GET", "/readyz")
            return
        except urllib.error.URLError:
            time.sleep(0.25)
    raise AssertionError("HTTP contract server did not become ready")


def server_request(
    base_url: str,
    api_key: str,
    namespace: str,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
) -> Any:
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url}{path}",
        data=data,
        method=method,
        headers={
            "content-type": "application/json",
            "x-api-key": api_key,
            "x-shibahama-namespace": namespace,
        },
    )
    with urllib.request.urlopen(request, timeout=2) as response:
        return json.loads(response.read().decode("utf-8"))


def normalize_python_candidate(candidate: Any) -> dict[str, Any]:
    return {
        "source_ref": candidate.item.provenance.source_ref,
        "tier": candidate.tier,
        "credence": candidate.item.credence,
        "currency": candidate.currency,
        "significance_score": fixed(candidate.significance_score),
        "rank_score": fixed(candidate.rank_score),
    }


def normalize_python_memory(memory: Any) -> dict[str, Any]:
    return {
        "source_ref": memory.provenance.source_ref,
        "tier": memory.tier,
        "credence": memory.credence,
        "significance": fixed(memory.significance),
        "valid_to_unix": memory.valid_to_unix,
    }


def normalize_python_why(trace: Any) -> dict[str, Any]:
    return {
        "source_ref": trace.item.provenance.source_ref,
        "currency_state": trace.currency_state,
        "tier_current": trace.tier_current,
        "tier_credence": trace.tier_credence,
        "final_score": fixed(trace.significance.final_score),
        "valid_to_unix": trace.valid_to_unix,
    }


def normalize_server_candidate(candidate: dict[str, Any], namespace: str) -> dict[str, Any]:
    return {
        "source_ref": strip_server_namespace(candidate["item"]["provenance"]["source_ref"], namespace),
        "tier": candidate["tier"],
        "credence": candidate["item"]["credence"],
        "currency": candidate["currency"],
        "significance_score": fixed(candidate["significance_score"]),
        "rank_score": fixed(candidate["rank_score"]),
    }


def normalize_server_memory(memory: dict[str, Any], namespace: str) -> dict[str, Any]:
    return {
        "source_ref": strip_server_namespace(memory["provenance"]["source_ref"], namespace),
        "tier": memory["tier"],
        "credence": memory["credence"],
        "significance": fixed(memory["significance"]),
        "valid_to_unix": memory["valid_to_unix"],
    }


def normalize_server_why(trace: dict[str, Any], namespace: str) -> dict[str, Any]:
    return {
        "source_ref": strip_server_namespace(trace["item"]["provenance"]["source_ref"], namespace),
        "currency_state": trace["currency_state"],
        "tier_current": trace["tier_current"],
        "tier_credence": trace["tier_credence"],
        "final_score": fixed(trace["significance"]["final_score"]),
        "valid_to_unix": trace["valid_to_unix"],
    }


def strip_server_namespace(source_ref: str | None, namespace: str) -> str | None:
    prefix = f"shibahama-server:namespace={namespace};"
    if source_ref is None or not source_ref.startswith(prefix):
        raise AssertionError(f"missing expected namespace prefix: {source_ref}")
    return source_ref.removeprefix(prefix)


def error_code(message: str) -> str:
    start = message.find("[SHIBA_")
    end = message.find("]", start)
    if start == -1 or end == -1:
        raise AssertionError(f"missing Shibahama error code: {message}")
    return message[start + 1 : end]


def require_trace(trace: Any | None) -> Any:
    if trace is None:
        raise AssertionError("missing why trace")
    return trace


def fixed(value: float) -> str:
    return f"{value:.6f}"


def diff_payload(lane: str, expected: dict[str, Any], actual: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"{lane} parity mismatch",
            "expected:",
            json.dumps(expected, indent=2, sort_keys=True),
            "actual:",
            json.dumps(actual, indent=2, sort_keys=True),
        ]
    )


if __name__ == "__main__":
    raise SystemExit(main())
