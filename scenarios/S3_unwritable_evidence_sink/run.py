#!/usr/bin/env python3
"""S3 — Evidence sink is unwritable.

Reproduces the documented failure class in which governance executes but the
evidence record cannot be written. The scenario asks one question and refuses
to blur it: when the write fails, does the implementation produce a
STRUCTURED outcome (a deferral/denial record, or an explicit degraded-mode
declaration with uncovered scope) — or does the failure disappear into an
unstructured error, or worse, a silent success?

Decision policy under test (D2, recorded 2026-08-05, founder):
  - mandatory-evidence profile: the governed decision must NOT release;
    expected decision_outcome DEFER or DENY, expected measurement_status for
    the evidence path ERROR (never PASS), expected evidence_status reflecting
    the failed write.
  - best-effort profile: the decision may proceed, but the result MUST declare
    degraded mode and the uncovered scope.

Target implementation: phionyx-mcp-server (PyPI), imported in-process.
The sink is a chmod-500 directory on a POSIX filesystem (run from tmpfs/ext4;
NTFS mounts silently ignore chmod and would invalidate the fixture).

Exit-code contract (draft-0.1, pack file 03):
  0 all mandatory assertions passed and none unmeasured
  1 a measured assertion failed              <- expected against v0.2.1
  2 a required measurement was NOT_MEASURED
  3 harness/environment error
"""
from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

SCENARIO_ID = "S3"  # schema pattern ^S[1-5]$; directory name carries the descriptive slug
SCENARIO_SLUG = "S3_unwritable_evidence_sink"
SCENARIO_VERSION = "draft-0.1"


IMPL_COMMIT = "2fd258e7afcd9e1a5c092a74edb663808835af5d"  # repository main at fixture-authoring time; see limitations


def _implementation() -> dict:
    from importlib.metadata import version as v

    return {
        "repository": "https://github.com/halvrenofviryel/phionyx-mcp-server",
        "commit": IMPL_COMMIT,
        "package_versions": {"phionyx-mcp-server": v("phionyx-mcp-server")},
    }


def _make_ro_sink(base: Path) -> Path:
    sink = base / "ro_sink"
    sink.mkdir(parents=True)
    sink.chmod(stat.S_IRUSR | stat.S_IXUSR)  # 500
    # Guard: on filesystems that ignore chmod (NTFS), the fixture is invalid.
    probe = sink / "probe"
    try:
        probe.write_text("x")
        probe.unlink()
        print("HARNESS ERROR: sink is writable after chmod 500 — run from a POSIX fs (tmpfs/ext4), not NTFS", file=sys.stderr)
        sys.exit(3)
    except PermissionError:
        return sink


def _attempt_write(sink: Path) -> dict:
    """Drive the real evidence writer against the read-only sink."""
    os.environ["PHIONYX_MCP_AUDIT_ROOT"] = str(sink)
    from phionyx_mcp_server.audit_chain import (
        FilesystemEnvelopeStore,
        HmacSigner,
        ToolCallContext,
        build_envelope,
    )

    store = FilesystemEnvelopeStore()
    ctx = ToolCallContext(
        trace_id="s3-fixture", turn_index=0, user_text="S3 fixture", producer="phionyx-conformance",
        tool_descriptor_hash=None, descriptor_change_detected=None, tool_permission_scope=None,
        input_hash=None, output_hash=None, approval_state=None, anomaly_flag=None,
        decision="release", decision_reason="S3 fixture", runtime_policy_basis=["s3-fixture"],
    )
    env = build_envelope(ctx, previous_hash=store.head("s3-fixture"),
                         server_version="conformance", signer=HmacSigner("s3-fixture-key"))
    try:
        store.append("s3-fixture", env)
        return {"outcome": "SILENT_SUCCESS_CLAIM", "detail": "append returned normally against a read-only sink"}
    except PermissionError as e:
        return {"outcome": "UNSTRUCTURED_ERROR", "detail": f"{type(e).__name__}: {e}"}
    except Exception as e:  # any structured refusal would be a distinct type
        return {"outcome": f"EXCEPTION:{type(e).__name__}", "detail": str(e)}


def main() -> int:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[2] / "actual"
    out_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as td:
        sink = _make_ro_sink(Path(td))
        observed = _attempt_write(sink)

    # Assertions per D2. Against v0.2.1 the structured expectations FAIL and the
    # no-silent-success expectation PASSES — that split IS the finding.
    assertions = [
        {
            "id": "S3-A1-no-silent-success",
            "requirement": "a failed evidence write must never look like a successful one",
            "expected": "write failure surfaces (any loud form)",
            "observed": observed["outcome"],
            "result": "PASS" if observed["outcome"] != "SILENT_SUCCESS_CLAIM" else "FAIL",
        },
        {
            "id": "S3-A2-structured-outcome-mandatory-profile",
            "requirement": "mandatory-evidence profile: failed write yields a structured DEFER/DENY decision record",
            "expected": "structured deferral/denial record with measurement_status=ERROR for the evidence path",
            "observed": observed["outcome"] + " — " + observed["detail"],
            "result": "PASS" if observed["outcome"].startswith("STRUCTURED") else "FAIL",
        },
        {
            "id": "S3-A3-degraded-declaration-best-effort-profile",
            "requirement": "best-effort profile: proceeding decision declares degraded mode + uncovered scope",
            "expected": "explicit degraded-mode declaration",
            "observed": "no degraded-mode surface exists in the implementation (measured: no such code path)",
            "result": "FAIL",
        },
    ]

    failed = [a for a in assertions if a["result"] == "FAIL"]
    exit_code = 1 if failed else 0

    record = {
        "scenario_id": SCENARIO_ID,
        "scenario_version": SCENARIO_VERSION,
        "implementation": _implementation(),
        "decision_outcome": "ALLOW",  # v0.2.1 envelope carried decision=release; the write, not the decision, failed
        "measurement_status": "ERROR",  # the evidence-path write was measured and it errored
        "enforcement_status": "NOT_REQUIRED",
        "evidence_status": "E0",  # nothing was persisted
        "executed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "command": "python scenarios/S3_unwritable_evidence_sink/run.py",
        "exit_code": exit_code,
        "assertions": [
            {"name": a["id"], "status": a["result"],
             "note": f"{a['requirement']} | expected: {a['expected']} | observed: {a['observed']}"}
            for a in assertions
        ],
        "source_artifacts": [
            # the wheel actually driven, with PyPI's own digest for it
            {"path_or_uri": "https://files.pythonhosted.org/packages/f8/3e/8eca30e18432eca3683c678e946d47ad603abd08e597ab57c013f3466b36/phionyx_mcp_server-0.2.1-py3-none-any.whl",
             "sha256": "4d29b9a0b9ec87882daae125d827bd799ca43bee4d86d00b481f2cc554b7bd51", "resolvable": True},
        ],
        "independent_rerun": {"status": "NOT_REQUESTED"},
        "limitations": [
            "in-process surface: drives audit_chain directly, not a running MCP host round-trip",
            "single POSIX read-only-directory failure mode; disk-full and mid-write truncation are not exercised",
            "assertion S3-A3 is currently definitional: the degraded-mode surface does not exist to test",
            "implementation.commit is the repository head at fixture-authoring time; the PyPI sdist does not attest which commit built it — the release-to-commit binding is itself unverified",
        ],
    }

    out = out_dir / f"{SCENARIO_SLUG}.result.json"
    out.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(f"[{SCENARIO_SLUG}] {len(assertions) - len(failed)}/{len(assertions)} assertions passed -> {out}")
    for a in assertions:
        print(f"  {a['result']:4s} {a['id']}: observed {a['observed'][:80]}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
