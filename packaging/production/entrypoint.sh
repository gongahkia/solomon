#!/bin/sh
# SPDX-License-Identifier: Apache-2.0

set -eu

load_file_secret() {
    name="$1"
    file_var="${name}_FILE"
    file="$(printenv "$file_var" || true)"
    if [ -z "$file" ]; then
        return
    fi
    if [ ! -r "$file" ]; then
        echo "secret file is not readable: $file_var" >&2
        exit 1
    fi
    value="$(cat "$file")"
    if [ -z "$value" ]; then
        echo "secret file is empty: $file_var" >&2
        exit 1
    fi
    export "$name=$value"
    unset "$file_var"
}

load_file_secret POSTGRES_PASSWORD
load_file_secret SOLOMON_SERVER_API_KEY
load_file_secret SOLOMON_CONTENT_ENCRYPTION_KEY

if [ -n "${SOLOMON_DATABASE_HOST:-}" ]; then
    : "${POSTGRES_PASSWORD:?set POSTGRES_PASSWORD_FILE}"
    : "${SOLOMON_DATABASE_USER:?set SOLOMON_DATABASE_USER}"
    : "${SOLOMON_DATABASE_NAME:?set SOLOMON_DATABASE_NAME}"
    encoded_password="$(printf %s "$POSTGRES_PASSWORD" | python -c 'import sys; from urllib.parse import quote; print(quote(sys.stdin.read(), safe=""))')"
    ssl_query=""
    if [ -n "${SOLOMON_DATABASE_SSLMODE:-}" ]; then
        encoded_sslmode="$(printf %s "$SOLOMON_DATABASE_SSLMODE" | python -c 'import sys; from urllib.parse import quote; print(quote(sys.stdin.read(), safe=""))')"
        ssl_query="?sslmode=${encoded_sslmode}"
    fi
    export SOLOMON_DATABASE_URL="postgresql://${SOLOMON_DATABASE_USER}:${encoded_password}@${SOLOMON_DATABASE_HOST}:${SOLOMON_DATABASE_PORT:-5432}/${SOLOMON_DATABASE_NAME}${ssl_query}"
    unset POSTGRES_PASSWORD
fi

if [ "$(id -u)" -eq 0 ]; then
    mkdir -p /var/lib/solomon/data /var/lib/solomon/journal
    chown -R solomon:solomon /var/lib/solomon/data /var/lib/solomon/journal
    exec setpriv --reuid=10001 --regid=10001 --init-groups -- "$@"
fi

exec "$@"
