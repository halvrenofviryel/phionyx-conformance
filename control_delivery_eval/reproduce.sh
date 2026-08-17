#!/usr/bin/env bash
# One command, from a clean clone, to the two .eval logs.
#
#   bash control_delivery_eval/reproduce.sh
#
# The experiment itself uses no network and calls no model; the only network
# use is pip installing two pinned packages into a throwaway virtualenv.
# Nothing outside that venv and this directory's out/ is written.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="${HERE}/.venv"

echo "=== 1/4 environment (pinned) ==="
python3 -m venv "${VENV}"
"${VENV}/bin/pip" install --quiet --upgrade pip
"${VENV}/bin/pip" install --quiet "phionyx-mcp-server==0.2.1" "inspect-ai==0.3.252"
"${VENV}/bin/python" - <<'PY'
from importlib.metadata import version
for pkg in ("phionyx-mcp-server", "inspect_ai"):
    print(f"  {pkg}: {version(pkg)}")
PY

echo "=== 2/4 inject the four control-path failures ==="
"${VENV}/bin/python" "${HERE}/inject.py" "${HERE}/out"

echo "=== 3/4 write baseline and instrumented .eval logs ==="
"${VENV}/bin/python" "${HERE}/to_eval_log.py"

echo "=== 4/4 read the logs back with Inspect's own reader ==="
LOGS="${HERE}/out/logs" "${VENV}/bin/python" - <<'PY'
import os
from pathlib import Path
from inspect_ai.log import read_eval_log

logs = Path(os.environ["LOGS"])
for posture in ("baseline", "instrumented"):
    log = read_eval_log(str(logs / f"{posture}.eval"))
    legible = sum(1 for s in log.samples if s.scores["failure_legible"].value == "C")
    print(f"  {posture:13s} {legible}/{len(log.samples)} control failures legible")
PY

echo
echo "Done. Inspect the logs interactively with:"
echo "  ${VENV}/bin/inspect view --log-dir ${HERE}/out/logs"
