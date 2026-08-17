#!/usr/bin/env python3
"""Run every conformance scenario, validate each record against the schema, summarise.

Exit code is the worst scenario exit code, so CI or a reviewer gets one answer:
  0 every scenario's mandatory assertions passed
  1 at least one measured assertion failed
  2 at least one required measurement was NOT_MEASURED / INCONCLUSIVE
  3 harness or environment error (including a record that fails its own schema)

A non-zero exit is not a broken harness. All five scenarios currently exit 1 by
design: each measures a gap that exists in the implementation under test, and the
day one exits 0 is the day that gap closed.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCENARIOS = sorted(p for p in (ROOT / "scenarios").iterdir() if p.is_dir() and (p / "run.py").exists())


def _validate(record_path: Path, schema: dict) -> str | None:
    try:
        import jsonschema
    except ImportError:
        return "jsonschema not installed — record NOT validated"
    try:
        jsonschema.validate(json.loads(record_path.read_text(encoding="utf-8")), schema)
    except Exception as exc:  # noqa: BLE001 — any validation failure is reportable
        return f"{type(exc).__name__}: {str(exc).splitlines()[0]}"
    return None


def main() -> int:
    schema = json.loads((ROOT / "schemas" / "result_record.schema.json").read_text(encoding="utf-8"))
    actual = ROOT / "actual"
    actual.mkdir(exist_ok=True)

    worst = 0
    rows: list[tuple[str, int, str]] = []
    for scenario in SCENARIOS:
        proc = subprocess.run(  # noqa: S603 — fixed, in-repo argv
            [sys.executable, str(scenario / "run.py"), str(actual)],
            capture_output=True, text=True,
        )
        sys.stdout.write(proc.stdout)
        if proc.returncode == 3:
            sys.stderr.write(proc.stderr)
        record = actual / f"{scenario.name}.result.json"
        note = "no record written" if not record.exists() else (_validate(record, schema) or "record schema-valid")
        if not record.exists() or note.startswith(("jsonschema", "ValidationError")):
            proc_rc = max(proc.returncode, 3)
        else:
            proc_rc = proc.returncode
        rows.append((scenario.name, proc_rc, note))
        worst = max(worst, proc_rc)

    # WP-17: per-chain RGE->AIREP projection golden fixture check (NOT an S1-S5 governance
    # scenario; NOT a workflow-global golden — that awaits WP-19). Additional worst-exit input.
    # Its result record is DELIBERATELY not an S1-S5 result_record: its shape is fixed by
    # check_golden.py and is intentionally NOT validated against schemas/result_record.schema.json
    # (that schema is S1-S5-specific). We fold its exit code in, but do not schema-check it here.
    golden = ROOT / "golden" / "check_golden.py"
    if golden.exists():
        proc = subprocess.run(  # noqa: S603 — fixed, in-repo argv
            [sys.executable, str(golden), str(actual)], capture_output=True, text=True,
        )
        sys.stdout.write(proc.stdout)
        if proc.returncode == 3:
            sys.stderr.write(proc.stderr)
        golden_record = actual / "golden_rge_airep_projection.result.json"
        # the result artifact is required; a missing record is a harness error (never a silent green).
        golden_rc = proc.returncode if golden_record.exists() else max(proc.returncode, 3)
        note = "per-chain golden fixture" if golden_record.exists() else "no golden record written"
        rows.append(("golden_rge_airep_projection", golden_rc, note))
        worst = max(worst, golden_rc)

    print("\n=== conformance summary ===")
    for name, rc, note in rows:
        print(f"  exit {rc}  {name:34s} {note}")
    print(f"  worst exit: {worst}")
    return worst


if __name__ == "__main__":
    sys.exit(main())
