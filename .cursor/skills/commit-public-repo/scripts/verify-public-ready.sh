#!/usr/bin/env bash
# Public-repo readiness checks for TERRA (run from anywhere inside the git tree).
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

echo "== TERRA public-ready verification =="

run_py_tool() {
  local name="$1"
  shift
  if [[ -x .venv/bin/${name} ]]; then
    ".venv/bin/${name}" "$@"
  elif command -v "${name}" >/dev/null 2>&1; then
    "${name}" "$@"
  else
    echo "ERROR: ${name} not found (install dev deps: python -m venv .venv && . .venv/bin/activate && pip install -e '.[dev]')" >&2
    exit 1
  fi
}

if [[ -f pyproject.toml ]]; then
  run_py_tool ruff check src/terra tests
  run_py_tool mypy src/terra tests
fi

if [[ -f docker-compose.yml ]] && command -v docker >/dev/null 2>&1; then
  docker compose config -q
fi

if [[ -f package.json ]]; then
  if ! command -v npm >/dev/null 2>&1; then
    echo "ERROR: npm not found but package.json exists." >&2
    exit 1
  fi
  npm run lint
fi

run_py_tool pytest

# Conflict markers / whitespace issues (fails fast before a bad public commit).
if ! git diff --check >/dev/null 2>&1; then
  echo "ERROR: unstaged diff failed git diff --check (whitespace or conflict markers)." >&2
  exit 1
fi
if ! git diff --cached --check >/dev/null 2>&1; then
  echo "ERROR: staged diff failed git diff --cached --check (whitespace or conflict markers)." >&2
  exit 1
fi

echo "== All checks passed =="
