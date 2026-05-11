#!/usr/bin/env bash
set -euo pipefail

WORKSPACE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_ROOT="${WORKSPACE_ROOT}"
HOST="${DECISIONTRAIL_HOST:-127.0.0.1}"
PORT="${DECISIONTRAIL_PORT:-8765}"
URL="http://${HOST}:${PORT}"

show_help() {
  cat <<HELP
Start the DecisionTrail local web UI for Codex Run.

Usage:
  ./script/build_and_run.sh

Environment:
  DECISIONTRAIL_HOST   Host to bind. Default: 127.0.0.1
  DECISIONTRAIL_PORT   Port to bind. Default: 8765

Local UI:
  ${URL}
HELP
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  show_help
  exit 0
fi

if [[ ! -f "${APP_ROOT}/pyproject.toml" || ! -d "${APP_ROOT}/decisiontrail" ]]; then
  echo "DecisionTrail app root was not found at ${APP_ROOT}." >&2
  exit 1
fi

cd "${APP_ROOT}"

echo "Starting DecisionTrail UI at ${URL}"
echo "Using local project path: ${APP_ROOT}"

if command -v uv >/dev/null 2>&1; then
  exec uv run python -m decisiontrail.cli ui --path "${APP_ROOT}" --host "${HOST}" --port "${PORT}"
fi

if [[ -x "${APP_ROOT}/.venv/bin/python" ]]; then
  exec "${APP_ROOT}/.venv/bin/python" -m decisiontrail.cli ui --path "${APP_ROOT}" --host "${HOST}" --port "${PORT}"
fi

echo "Neither uv nor .venv/bin/python is available. Run 'uv sync' first." >&2
exit 1
