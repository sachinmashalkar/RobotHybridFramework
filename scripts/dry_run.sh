#!/usr/bin/env bash
# Fast offline lint: resolves every keyword/resource without launching a browser.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$HERE"

RESULT_DIR="results/dryrun"
mkdir -p "$RESULT_DIR"

robot \
  --dryrun \
  --pythonpath . \
  --outputdir "$RESULT_DIR" \
  --loglevel DEBUG \
  "$@" \
  tests

echo "Dry-run OK -> $RESULT_DIR"
