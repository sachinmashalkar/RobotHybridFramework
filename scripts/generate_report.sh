#!/usr/bin/env bash
# Post-process results: robotframework-metrics + Allure report.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$HERE"

LATEST_RUN="$(ls -1dt results/2* 2>/dev/null | head -n1 || true)"
if [[ -z "$LATEST_RUN" ]]; then
  echo "No results/ subdirectory found. Run tests first." >&2
  exit 1
fi

echo "Processing $LATEST_RUN"

# robotframework-metrics
python -m robotframework_metrics --inputpath "$LATEST_RUN" --output "metrics.html" || true

# Allure (requires allure CLI in PATH; CI installs it)
if command -v allure >/dev/null 2>&1; then
  allure generate "$LATEST_RUN/allure-results" -o "$LATEST_RUN/allure-report" --clean
  echo "Allure report -> $LATEST_RUN/allure-report"
else
  echo "allure CLI not found; skipping Allure generation."
fi
