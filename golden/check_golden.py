#!/usr/bin/env python3
"""WP-17 — per-chain RGE→AIREP projection golden fixture + Py/Node verifier expected-verdict check.

This is NOT one of the S1–S5 governance scenarios, and NOT a workflow-global golden (that awaits
WP-19). It is a per-decision / per-chain regression anchor: a FROZEN projected AIREP chain
(``golden/chain.jsonl``, produced once by the WP-12 RGE→AIREP projection) plus a tamper negative
(``golden/tampered.jsonl``). Each is run through BOTH reference verifiers and the ACTUAL verdict is
asserted against the FROZEN EXPECTED verdict:

  - golden chain  → both verifiers PASS (exit 0);
  - tampered chain → both verifiers FAIL (exit != 0).

If the projection format, the canonicalization, or a verifier drifts, this check flips — that is
the point. The Node half is `NOT_MEASURED` when `node` is unavailable (the py↔node parity claim is
then honestly unmeasured, not silently passed).

Exit-code contract (draft-0.1, conformance):
  0 all expected verdicts matched          1 a measured verdict mismatched
  2 a required verdict was NOT_MEASURED     3 harness/environment error
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent  # repo root (golden -> root)


def _airep_conformance_dir() -> Path:
    """The AIREP reference verifiers live in the ai-runtime-evidence-protocol repo,
    not here. Resolution order: $AIREP_CONFORMANCE_DIR, then a sibling checkout
    (../ai-runtime-evidence-protocol). Absence is reported NOT_MEASURED, never a pass.
    """
    env = os.environ.get("AIREP_CONFORMANCE_DIR")
    if env:
        return Path(env)
    return ROOT.parent / "ai-runtime-evidence-protocol" / "spec" / "airep" / "v0.1" / "conformance"


_AIREP = _airep_conformance_dir()
VERIFY_PY = _AIREP / "verify.py"
VERIFY_MJS = _AIREP / "verify.mjs"
GOLDEN = HERE / "chain.jsonl"
TAMPERED = HERE / "tampered.jsonl"

SCENARIO = "golden_rge_airep_projection"
VERSION = "draft-0.1"


def _run(cmd: list[str], target: Path) -> int:
    return subprocess.run(cmd + [str(target)], capture_output=True, text=True).returncode


def main(argv: list[str]) -> int:
    actual_dir = Path(argv[0]) if argv else (ROOT / "conformance" / "actual")
    try:
        actual_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        # cannot even create the result sink -> harness error (exit 3), never a masquerading FAIL/green.
        print(f"[{SCENARIO}] ERROR — result sink unavailable: {type(exc).__name__}", file=sys.stderr)
        return 3
    assertions: list[dict] = []

    # harness precondition: the in-repo fixtures must exist (their absence is a harness error).
    if not (GOLDEN.exists() and TAMPERED.exists()):
        assertions.append({"name": "fixtures_present", "status": "ERROR",
                           "note": "missing golden/tampered fixture"})
        _write(actual_dir, assertions, 3)
        print(f"[{SCENARIO}] ERROR — missing fixtures")
        return 3

    # The AIREP verifiers are an EXTERNAL dependency (separate repo). Absent ->
    # NOT_MEASURED (exit 2), never an error and never a silent pass.
    if not VERIFY_PY.exists():
        note = ("AIREP verifier not found — clone "
                "https://github.com/halvrenofviryel/ai-runtime-evidence-protocol as a sibling "
                "checkout or set AIREP_CONFORMANCE_DIR; py+node parity unmeasured")
        for n in ("py_golden_verifies", "py_tampered_rejected", "mjs_golden_verifies", "mjs_tampered_rejected"):
            assertions.append({"name": n, "status": "NOT_MEASURED", "note": note})
        _write(actual_dir, assertions, 2)
        print(f"[{SCENARIO}] exit 2  AIREP verifiers absent — projection golden NOT_MEASURED")
        return 2

    py = [sys.executable, str(VERIFY_PY)]
    # Python (authoritative) — required.
    assertions.append({"name": "py_golden_verifies", "status":
                       "PASS" if _run(py, GOLDEN) == 0 else "FAIL",
                       "note": "verify.py must accept the frozen golden chain"})
    assertions.append({"name": "py_tampered_rejected", "status":
                       "PASS" if _run(py, TAMPERED) != 0 else "FAIL",
                       "note": "verify.py must reject the tamper negative (a fail-open here is the bug this guards)"})

    # Node parity — NOT_MEASURED if node is unavailable (never silently passed).
    if shutil.which("node") is None or not VERIFY_MJS.exists():
        reason = "node not installed" if shutil.which("node") is None else "verify.mjs absent"
        for n in ("mjs_golden_verifies", "mjs_tampered_rejected"):
            assertions.append({"name": n, "status": "NOT_MEASURED", "note": f"{reason} — py↔node parity unmeasured"})
    else:
        mjs = ["node", str(VERIFY_MJS)]
        assertions.append({"name": "mjs_golden_verifies", "status":
                           "PASS" if _run(mjs, GOLDEN) == 0 else "FAIL", "note": "verify.mjs must accept the golden chain"})
        assertions.append({"name": "mjs_tampered_rejected", "status":
                           "PASS" if _run(mjs, TAMPERED) != 0 else "FAIL", "note": "verify.mjs must reject the tamper negative"})

    statuses = {a["status"] for a in assertions}
    # ERROR (harness) takes precedence over a measured FAIL, then NOT_MEASURED, then clean.
    exit_code = 3 if "ERROR" in statuses else 1 if "FAIL" in statuses else 2 if "NOT_MEASURED" in statuses else 0
    if not _write(actual_dir, assertions, exit_code):
        exit_code = 3  # the result artifact is REQUIRED — a write failure is a harness error, never a silent green
    summary = " ".join(f"{a['name']}={a['status']}" for a in assertions)
    print(f"[{SCENARIO}] exit {exit_code}  {summary}")
    return exit_code


def _write(actual_dir: Path, assertions: list[dict], exit_code: int) -> bool:
    record = {
        "scenario": SCENARIO,
        "scenario_version": VERSION,
        "kind": "per_chain_rge_airep_projection_golden",
        "not_a_workflow_global_golden": True,  # workflow-global awaits WP-19
        "executed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "fixtures": {"golden": str(GOLDEN.name), "tampered": str(TAMPERED.name)},
        "assertions": assertions,
        "exit_code": exit_code,
        "limitations": [
            "Per-chain only; not a workflow-global golden (that requires the WP-19 obligation/closure tranche).",
            "Verifier run WITHOUT --pubkey: structural + neutrality + integrity + chain conformance, NOT Ed25519 signature conformance.",
        ],
    }
    try:
        (actual_dir / f"{SCENARIO}.result.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
        return True
    except OSError:
        return False  # caller escalates to exit 3 — the result artifact is required, not optional


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
