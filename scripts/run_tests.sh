#!/usr/bin/env bash
# Primary entry point for running the framework locally and in CI.
#
# Examples:
#   scripts/run_tests.sh                               # full suite, default browser
#   scripts/run_tests.sh --suite tests/ui              # just UI tests
#   scripts/run_tests.sh --tags smoke                  # only @smoke tagged tests
#   scripts/run_tests.sh --browser headlesschrome     # run headless
#   scripts/run_tests.sh --parallel 4                 # run with pabot (4 workers)
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$HERE"

SUITE="tests"
BROWSER="${BROWSER:-chrome}"
TAGS=""
EXCLUDE_TAGS=""
PARALLEL=""
ENVIRONMENT="${TEST_ENV:-dev}"
EXTRA_ARGS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --suite) SUITE="$2"; shift 2 ;;
    --browser) BROWSER="$2"; shift 2 ;;
    --env) ENVIRONMENT="$2"; shift 2 ;;
    --tags) TAGS="$2"; shift 2 ;;
    --exclude-tags) EXCLUDE_TAGS="$2"; shift 2 ;;
    --parallel) PARALLEL="$2"; shift 2 ;;
    --) shift; EXTRA_ARGS+=("$@"); break ;;
    *) EXTRA_ARGS+=("$1"); shift ;;
  esac
done

export TEST_ENV="$ENVIRONMENT"
export BROWSER

RESULT_DIR="results/$(date +%Y%m%d_%H%M%S)"
mkdir -p "$RESULT_DIR/screenshots"

COMMON=(
  --pythonpath .
  --outputdir "$RESULT_DIR"
  --variable BROWSER:"$BROWSER"
  --variable ENVIRONMENT:"$ENVIRONMENT"
  --listener "libraries.CustomListener.CustomListener:$RESULT_DIR/screenshots"
  --loglevel INFO
)

if [[ -n "$TAGS" ]]; then
  COMMON+=(--include "$TAGS")
fi
if [[ -n "$EXCLUDE_TAGS" ]]; then
  COMMON+=(--exclude "$EXCLUDE_TAGS")
fi

echo "=== Robot Hybrid Framework ==="
echo "Env:      $ENVIRONMENT"
echo "Browser:  $BROWSER"
echo "Suite:    $SUITE"
echo "Tags:     ${TAGS:-<all>}"
echo "Parallel: ${PARALLEL:-<off>}"
echo "Output:   $RESULT_DIR"

if [[ -n "$PARALLEL" ]]; then
  pabot --processes "$PARALLEL" "${COMMON[@]}" "${EXTRA_ARGS[@]}" "$SUITE"
else
  robot "${COMMON[@]}" "${EXTRA_ARGS[@]}" "$SUITE"
fi

echo "Reports written to $RESULT_DIR"
