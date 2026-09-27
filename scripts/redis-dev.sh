#!/bin/sh
set -eu
if ! command -v redis-server >/dev/null 2>&1; then
  export PATH="$HOME/.local/share/spaceport-redis/bin:$PATH"
fi
if ! command -v redis-server >/dev/null 2>&1; then
  echo 'Install Redis or run: docker compose up -d redis' >&2
  exit 1
fi
# This is a disposable local cache. PostgreSQL owns persistent data.
exec redis-server --bind 127.0.0.1 --port 6379 --save "" --appendonly no \
  --maxmemory 64mb --maxmemory-policy volatile-lru
