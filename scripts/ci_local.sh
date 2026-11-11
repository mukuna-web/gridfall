#!/usr/bin/env bash
# Run exactly what .github/workflows/ci.yml runs, the python and the app job, failing on the first error (RH-03).
#
# By default it clones HEAD into a temporary folder with `git clone --no-local`, so data/raw, data/interim and
# data/processed are absent as in CI, and local data cannot turn skipped tests into passing ones. Uncommitted
# changes are not in that clone; pass --in-place to run the same commands in this working tree before committing.
#
#   scripts/ci_local.sh             # faithful to CI: a temporary clone of HEAD
#   scripts/ci_local.sh --in-place  # this tree, uncommitted changes included
#
# tests/test_lockbox.py checks that every `run:` command of ci.yml appears below, verbatim.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
MODE="${1:-clone}"
case "$MODE" in
  clone)
    SCRATCH="$(mktemp -d "${TMPDIR:-/tmp}/blackout-ci.XXXXXX")"
    trap 'rm -rf "$SCRATCH"' EXIT
    git clone --quiet --no-local "$REPO" "$SCRATCH/repo"
    WORK="$SCRATCH/repo"
    ;;
  --in-place)
    WORK="$REPO"
    ;;
  *)
    echo "usage: $0 [--in-place]" >&2
    exit 2
    ;;
esac

step() {
  printf '\n== %s\n' "$*"
  "$@"
}

# python job
cd "$WORK"
step uv sync --locked
step uv run ruff check src tests scripts
step uv run pytest --cov=blackout --cov-report=term-missing --cov-fail-under=80
step uv run blackout export --sample

# app job (working-directory: app)
cd "$WORK/app"
step npm ci
step npx tsc --noEmit
step npm test
step npm run build

printf '\nci_local: every step passed (%s)\n' "$MODE"
