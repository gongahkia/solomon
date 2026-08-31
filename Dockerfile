# SPDX-License-Identifier: Apache-2.0

FROM ghcr.io/astral-sh/uv:0.9.21 AS uv

FROM pgvector/pgvector:0.8.2-pg16-bookworm AS postgres-tools

FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:${PATH}"

WORKDIR /app

COPY --from=uv /uv /uvx /bin/
COPY --from=postgres-tools /usr/lib/postgresql/16/bin/pg_dump /usr/local/bin/pg_dump
COPY --from=postgres-tools /usr/lib/postgresql/16/bin/pg_restore /usr/local/bin/pg_restore
COPY pyproject.toml README.md uv.lock ./
COPY src ./src
RUN apt-get update \
    && apt-get install --yes --no-install-recommends build-essential libpq5 \
    && groupadd --gid 10001 solomon \
    && useradd --uid 10001 --gid 10001 --create-home --home-dir /nonexistent --shell /usr/sbin/nologin solomon \
    && uv sync --locked --no-dev --extra server \
    && apt-get purge --yes --auto-remove build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY packaging/production/entrypoint.sh /usr/local/bin/solomon-entrypoint
RUN chmod 0555 /usr/local/bin/solomon-entrypoint \
    && mkdir -p /var/lib/solomon/data /var/lib/solomon/journal \
    && chown -R solomon:solomon /var/lib/solomon

ENTRYPOINT ["/usr/local/bin/solomon-entrypoint"]
