# SPDX-License-Identifier: Apache-2.0

FROM python:3.12-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install --yes --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv

COPY . .

RUN uv sync --locked --extra dev

CMD ["sh", "-c", "uv run python examples/scenarios/04-boutique-sg/seed_console.py && SOLOMON_DATA_DIR=/app/data SOLOMON_JOURNAL_DIR=/app/journal uv run uvicorn solomon.console.app:create_console_app --factory --host 0.0.0.0 --port 8150"]
