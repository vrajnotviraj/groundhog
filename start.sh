#!/usr/bin/env bash
# Check every dependency, seed Mongo, build the web app and start the console.
# Usage: ./start.sh [--dev] [--check] [--yes] [--port 8000]
set -euo pipefail
cd "$(dirname "$0")"

DEV=0 CHECK=0 YES=0 PORT=8000
while [ $# -gt 0 ]; do
  case "$1" in
    --dev) DEV=1 ;;
    --check) CHECK=1 ;;
    --yes) YES=1 ;;
    --port) PORT="${2:?--port needs a number}"; shift ;;
    *) echo "usage: ./start.sh [--dev] [--check] [--yes] [--port 8000]" >&2; exit 2 ;;
  esac
  shift
done

ok() { printf '\033[32m✓\033[0m %s — %s\n' "$1" "$2"; }
fail() { printf '\033[31m✗\033[0m %s — %s\n' "$1" "$2"; exit 1; }

command -v uv >/dev/null || fail uv "install it: curl -LsSf https://astral.sh/uv/install.sh | sh"
ok uv "$(uv --version)"
command -v node >/dev/null && command -v npm >/dev/null || fail node "install Node 20 or newer: nvm install 20"
[ "$(node -p 'process.versions.node.split(".")[0]')" -ge 20 ] || fail node "$(node -v) is too old — nvm install 20"
ok node "$(node -v), npm $(npm -v)"

if [ ! -f .env ]; then
  cp .env.example .env
  fail .env "created from .env.example — fill BASE_URL, LOGIN_USER, LOGIN_PASS, LOGIN_WORKSPACE, TYPESAFE_API_KEY and ADMIN_EMAIL, then run again"
fi
ok .env "present"

uv sync --quiet || fail "uv sync" "see the error above"
ok "uv sync" "Python dependencies installed"

# .env is read the way the app reads it (python-dotenv): values may hold unquoted spaces, so it is not sourced
setting() { uv run python -c "from groundhog import config; print(config.$1)"; }
MONGO_URL="$(setting MONGO_URL)"
mongo_ping() {
  uv run python -c "import pymongo, sys; pymongo.MongoClient(sys.argv[1], serverSelectionTimeoutMS=3000).admin.command('ping')" "$MONGO_URL" >/dev/null 2>&1
}
start_mongo() {
  if docker ps -a --format '{{.Names}}' | grep -qx groundhog-mongo; then
    docker start groundhog-mongo >/dev/null
  else
    docker run -d --name groundhog-mongo -p 27017:27017 -v groundhog-mongo:/data/db mongo:7 >/dev/null
  fi
  for _ in $(seq 30); do mongo_ping && return 0; sleep 1; done
  return 1
}
MONGO_HOST="${MONGO_URL##*@}"
if ! mongo_ping; then
  command -v docker >/dev/null || fail mongo "unreachable at $MONGO_HOST — brew tap mongodb/brew && brew install mongodb-community, or install docker"
  if [ "$YES" = 0 ]; then
    answer=""
    read -r -p "Mongo is not running. Start it in docker as groundhog-mongo? [y/N] " answer || true
    [ "$answer" = y ] || [ "$answer" = Y ] || fail mongo "unreachable at $MONGO_HOST — start it, or run ./start.sh --yes to start it in docker"
  fi
  start_mongo || fail mongo "groundhog-mongo did not answer within 30 s — check: docker logs groundhog-mongo"
fi
ok mongo "reachable at $MONGO_HOST"

chromium_launches() {
  uv run python -c "import sys; from groundhog.checks import check_chromium; sys.exit(not check_chromium()[0])" >/dev/null 2>&1
}
if ! chromium_launches; then
  uv run playwright install chromium || fail chromium "install failed — run: uv run playwright install chromium"
  chromium_launches || fail chromium "still does not launch — run: uv run playwright install --with-deps chromium"
fi
ok chromium "launches"

# npm ci writes node_modules/.package-lock.json, so its age is the install's age
if [ web/package-lock.json -nt web/node_modules/.package-lock.json ]; then
  (cd web && npm ci) || fail "web deps" "npm ci failed — see the error above"
fi
ok "web deps" "installed"

if ! uv run groundhog db seed; then
  [ -n "$(setting ADMIN_EMAIL)" ] || fail seed "add ADMIN_EMAIL=you@example.com to .env (ADMIN_PASSWORD optional; empty prints a generated one)"
  fail seed "see the error above"
fi
ok seed "indexes and admin in Mongo"

if [ "$DEV" = 0 ]; then
  (cd web && npm run build --silent >/dev/null) || fail "web build" "run: cd web && npm run build"
  ok "web build" "web/dist"
fi

if [ "$CHECK" = 1 ]; then
  echo "all checks passed; run ./start.sh to start the console"
  exit 0
fi

! curl -s -o /dev/null "http://localhost:$PORT" || fail serve "port $PORT is already in use — stop that server, or pass --port"

# Each background job gets its own process group, so cleanup stops its children too
set -m
cleanup() { kill -- -"$API_PID" ${WEB_PID:+-"$WEB_PID"} 2>/dev/null || true; }
trap cleanup EXIT
trap 'exit 130' INT TERM

uv run groundhog serve --port "$PORT" &
API_PID=$!
if [ "$DEV" = 1 ]; then
  (cd web && npm run dev -- --port 5173 --strictPort) &
  WEB_PID=$!
fi

for _ in $(seq 20); do
  curl -sf "http://localhost:$PORT/api/health" >/dev/null && break
  kill -0 "$API_PID" 2>/dev/null || fail serve "the API exited — see the error above"
  sleep 1
done
curl -sf "http://localhost:$PORT/api/health" >/dev/null || fail serve "no answer from /api/health on port $PORT within 20 s"
echo "console: http://localhost:$PORT"
[ "$DEV" = 0 ] || echo "dev UI: http://localhost:5173"
wait
