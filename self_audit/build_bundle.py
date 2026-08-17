#!/usr/bin/env python3
"""Reproduce the first two Measurement-Axioms self-audit findings against a pinned release.

The self-audit (published: measurement-axioms/audit/PHIONYX_MEASUREMENT_AXIOMS_SELF_AUDIT_2026-08-01.md)
named its own gap: no reproduction command, no per-finding record. This driver closes
that gap for the first two findings by DRIVING the installed wheel and recording what it
actually returns:

  SA-1  verify_chain([])                          -> valid must not be true (empty = NOT_MEASURED)
  SA-2  verify_chain([tampered]) with no verifier -> valid must not be true (unchecked signature)

Run it in a 0.2.0 venv and it reproduces the bug (both return valid=true; exit 1). Run it
in a 0.2.1 venv and it records the fix (both return valid=null / NOT_MEASURED; exit 0). The
static provenance (commit pin, file+line ranges, wheel digests) lives in findings.json; this
driver merges the live observation onto it and writes the result to actual/ (scratch).

Exit codes:
  0  every finding shows the FIXED behaviour in the measured release
  1  at least one finding still shows the bug (valid is true)
  3  harness/environment error (implementation absent, or an unexpected shape)
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
FINDINGS = HERE / "findings.json"


def _installed_version() -> str:
    from importlib.metadata import version

    return version("phionyx-mcp-server")


def _probe_empty(ac) -> dict:
    """SA-1: an empty chain has nothing to check."""
    result = ac.verify_chain([])
    return {
        "call": "verify_chain([])",
        "valid_present": "valid" in result,  # distinguishes explicit null from a missing key
        "valid": result.get("valid"),
        "measurement_status": result.get("measurement_status"),
        "non_measurement_cause": result.get("non_measurement_cause"),
    }


def _probe_tampered(ac) -> dict:
    """SA-2: a tampered signature verified with no verifier."""
    os.environ["PHIONYX_MCP_AUDIT_ROOT"] = tempfile.mkdtemp()
    signer = ac.HmacSigner("self-audit-fixture-key")
    ctx = ac.ToolCallContext(
        trace_id="self-audit", turn_index=0, user_text="self-audit probe", producer="phionyx-conformance",
        tool_descriptor_hash=None, descriptor_change_detected=None, tool_permission_scope=None,
        input_hash=None, output_hash=None, approval_state=None, anomaly_flag=None,
        decision="release", decision_reason="self-audit fixture", runtime_policy_basis=["input_safety_gate"],
    )
    env = ac.build_envelope(ctx, previous_hash=ac.GENESIS_HASH, server_version="self-audit", signer=signer)
    # Tamper ONLY the signature (the hash chain stays intact) so the finding is
    # about signature verification, not hash continuity.
    env["integrity"]["signature"] = "demo-hmac:" + "0" * 16
    result = ac.verify_chain([env])  # DEFAULT path: no verifier — the buggy call
    return {
        "call": "verify_chain([tampered]) with no verifier",
        "valid_present": "valid" in result,  # distinguishes explicit null from a missing key
        "valid": result.get("valid"),
        "measurement_status": result.get("measurement_status"),
        "signatures_verified": result.get("signatures_verified"),
        "broken_at": result.get("broken_at"),
    }


def _classify(finding_id: str, obs: dict) -> str:
    """Three outcomes, strictly. The bug is `valid is True`. FIXED requires the
    EXACT fixed shape the findings claim, not merely 'not True' — a False, a
    missing key, or an unrecognised sentinel is UNEXPECTED, never FIXED."""
    if obs.get("valid") is True:
        return "BUG-REPRODUCED"
    # FIXED demands the `valid` key be PRESENT and explicitly null — a missing key
    # is API drift, not the documented fix, and must fall through to UNEXPECTED.
    valid_is_explicit_null = obs.get("valid_present") is True and obs.get("valid") is None
    not_measured = obs.get("measurement_status") == "NOT_MEASURED"
    if finding_id == "SA-1":
        if valid_is_explicit_null and not_measured:
            return "FIXED"
    elif finding_id == "SA-2":
        if valid_is_explicit_null and not_measured and obs.get("signatures_verified") is False:
            return "FIXED"
    return "UNEXPECTED"


def _install_kind(ac) -> tuple[str, str]:
    """Where the measured code actually lives — so a reader can tell a real wheel
    install from an editable/source tree the pinned sha would not describe."""
    location = getattr(ac, "__file__", "unknown")
    kind = "wheel" if "site-packages" in location else "editable-or-source (pinned wheel sha256 does NOT describe this run)"
    return location, kind


def main() -> int:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "actual"
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        from phionyx_mcp_server import audit_chain as ac
    except ImportError as exc:
        print(f"HARNESS ERROR: {exc}. Install a pinned release: pip install phionyx-mcp-server==0.2.0 (bug) "
              f"or ==0.2.1 (fix)", file=sys.stderr)
        return 3

    static = json.loads(FINDINGS.read_text(encoding="utf-8"))
    version = _installed_version()
    location, kind = _install_kind(ac)

    try:
        observed = {"SA-1": _probe_empty(ac), "SA-2": _probe_tampered(ac)}
    except Exception as exc:  # unexpected API shape
        print(f"HARNESS ERROR: probe raised {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3

    merged = []
    shows = []
    for finding in static["findings"]:
        fid = finding["id"]
        obs = observed[fid]
        verdict = _classify(fid, obs)
        shows.append(verdict)
        merged.append({
            "id": fid,
            "title": finding["title"],
            "axiom": finding["axiom"],
            "expected": finding["expected"],
            "measured_version": version,
            "observed": obs,
            "shows": verdict,
        })

    # BUG present is the strongest signal (exit 1); an unclassifiable shape is
    # exit 2 (measured but not a determinate fixed/bug state); all-fixed is 0.
    if "BUG-REPRODUCED" in shows:
        exit_code, summary = 1, "at least one finding still shows the bug"
    elif "UNEXPECTED" in shows:
        exit_code, summary = 2, "a finding returned neither the documented bug nor the documented fix"
    else:
        exit_code, summary = 0, "all findings show the exact documented fixed behaviour"

    record = {
        "bundle": static["bundle"],
        "source_audit": static["source_audit"],
        "measured_version": version,
        "install_location": location,
        "install_kind": kind,
        "measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "command": "python self_audit/build_bundle.py",
        "exit_code": exit_code,
        "summary": summary,
        "artifact_binding_note": (
            "measured_version is read from installed metadata; the wheel_sha256 values in "
            "findings.json are static claims about the PyPI wheels and are NOT re-verified at "
            "runtime. If install_kind is not 'wheel', those sha claims do not describe this run."
        ),
        "findings": merged,
        "verification_status": "first-party; not independently reproduced (see findings.json)",
    }

    out = out_dir / f"self_audit_bundle.{version}.json"
    out.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(f"[self-audit bundle] measured {version} ({kind.split(' ')[0]}) -> {out}")
    for m in merged:
        o = m["observed"]
        print(f"  {m['shows']:15s} {m['id']}: {o['call']} -> valid={o['valid']!r} "
              f"measurement_status={o['measurement_status']!r}")
    print(f"  exit {exit_code}: {summary}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
