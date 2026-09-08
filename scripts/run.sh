#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
# A separate display protects any desktop session and makes window ownership unambiguous.
if [[ ${LVCE_BENCHMARK_DISPLAY:-} != 1 ]]; then
  exec xvfb-run --auto-servernum --server-args='-screen 0 1280x720x24 -nolisten tcp' env LVCE_BENCHMARK_DISPLAY=1 bash scripts/run.sh "$@"
fi
openbox > /tmp/lvce-memory-openbox-$$.log 2>&1 &
wm_pid=$!
trap 'kill "$wm_pid" 2>/dev/null || true' EXIT
sleep 1
sudo --preserve-env=DISPLAY,XAUTHORITY,BENCHMARK_COMMIT,BENCHMARK_RUN_URL python3 scripts/benchmark.py "$@"
