#!/usr/bin/env sh
# SPDX-License-Identifier: Apache-2.0

set -eu

SOLOMON_TEST_LOCAL_MODEL_URL="${SOLOMON_TEST_LOCAL_MODEL_URL:-http://127.0.0.1:11434/api/generate}"
SOLOMON_TEST_LOCAL_MODEL_NAME="${SOLOMON_TEST_LOCAL_MODEL_NAME:-qwen2.5-coder:1.5b}"
OLLAMA_BASE="${SOLOMON_TEST_LOCAL_MODEL_URL%/api/generate}"
OLLAMA_PID=""

cleanup() {
  if [ -n "$OLLAMA_PID" ]; then
    kill "$OLLAMA_PID" >/dev/null 2>&1 || true
  fi
}

trap cleanup EXIT INT TERM

if ! curl -fsS --max-time 2 "$OLLAMA_BASE/api/tags" >/dev/null 2>&1; then
  command -v ollama >/dev/null 2>&1 || {
    echo "ollama is required for demo-local" >&2
    exit 1
  }
  ollama serve >/tmp/solomon-ollama-demo.log 2>&1 &
  OLLAMA_PID="$!"
  ready=0
  for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
    if curl -fsS --max-time 2 "$OLLAMA_BASE/api/tags" >/dev/null 2>&1; then
      ready=1
      break
    fi
    sleep 1
  done
  if [ "$ready" != "1" ]; then
    echo "ollama did not become ready; see /tmp/solomon-ollama-demo.log" >&2
    exit 1
  fi
fi

if ! ollama show "$SOLOMON_TEST_LOCAL_MODEL_NAME" >/dev/null 2>&1; then
  echo "missing local model: run 'ollama pull $SOLOMON_TEST_LOCAL_MODEL_NAME'" >&2
  exit 1
fi

export SOLOMON_TEST_LOCAL_MODEL_URL
export SOLOMON_TEST_LOCAL_MODEL_NAME
uv run pytest tests/test_model_live_integration.py::test_live_local_model_answer_path_uses_sanitized_boundary_prompt
