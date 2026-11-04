#!/usr/bin/env bash
#
# Smoke test the compose file a stranger downloads.
#
# Usage: scripts/docker-smoke.sh <directory containing compose.yaml>
#
# The directory should contain nothing but compose.yaml, so the test exercises
# the same pull-and-run path as a fresh install. TRIBUTARY_VERSION selects the
# image tag; leave it unset to use the file's default.
set -euo pipefail

project_dir="${1:?usage: docker-smoke.sh <directory containing compose.yaml>}"
cd "$project_dir"

compose() { docker compose "$@"; }

cleanup() {
  status=$?
  if [ "$status" -ne 0 ]; then
    compose logs --no-color --tail 200 || true
  fi
  compose down --volumes --remove-orphans >/dev/null 2>&1 || true
  trap - EXIT
  exit "$status"
}
trap cleanup EXIT

compose up --wait --wait-timeout 300

# One origin: the reader serves the app and proxies /api/* to the API.
curl -fsS http://127.0.0.1:3000/ | grep -qi tributary
curl -fsS http://127.0.0.1:3000/api/me | grep -q '"mode":"local"'

# A write that needs no external network, so the persistence check is stable.
curl -fsS -X POST http://127.0.0.1:3000/api/labels \
  -H 'content-type: application/json' \
  -d '{"name":"smoke"}' >/dev/null

# Non-root, and the database is in the chowned child of the volume.
compose exec -T api id -u | grep -qx 10001
compose exec -T api test -f /data/tributary/tributary.db

# The AI-off hint is wired from compose into the API's error message.
compose exec -T api python -c '
from tributary.config import get_settings
from tributary.services.model import _describe_failure
import httpx

print(_describe_failure(
    httpx.ConnectError("refused"),
    host="http://ollama:11434",
    timeout=1,
    hint=get_settings().ollama_hint,
))
' | grep -q 'docker compose --profile ai up -d'

# Restart and confirm the named volume kept the row.
compose restart api
for _ in $(seq 1 60); do
  if curl -fsS http://127.0.0.1:3000/api/me >/dev/null 2>&1; then
    break
  fi
  sleep 2
done
curl -fsS http://127.0.0.1:3000/api/labels | grep -q smoke

echo "docker smoke test passed"
