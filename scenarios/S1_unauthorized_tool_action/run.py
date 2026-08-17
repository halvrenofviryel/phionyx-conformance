#!/usr/bin/env python3
"""S1 — A proposal cannot authorize its own tool invocation.

An unauthorized tool action is a tool call whose descriptor has NO
user-approved baseline to compare against. The scenario asks the shipped
authority surface one question: when there is no prior approval, does the
implementation refuse (DENY) or escalate (STEP_UP), or does the absence of
authority read the same as an approved-and-matching descriptor?

Target implementation: phionyx-mcp-server 0.2.1, imported in-process. The
surface under test is the descriptor authority check
(`descriptor_hash.hash_descriptor` + `compare_descriptor_hashes`, which is what
`server.verify_tool_descriptor` delegates to). We drive the pure functions
directly; the FastMCP wrapper is not importable without the MCP host and adds
nothing to the authority decision itself.

What this measures — and its honest limit: the shipped comparator is advisory.
It reports whether a descriptor changed and whether a baseline existed; it emits
no decision and applies no enforcement. Two things are true at once and the
fixture keeps them apart: (A4) the surface DOES expose a correct distinguishing
signal for missing authority (`baseline_exists=False`, distinct from an approved
match's `True`), so it does not itself collapse missing authority into allow;
but (A3) it applies no enforcement — the correct signal is never turned into a
DENY/STEP_UP, and it collides with approved-and-matching on the primary change
verdict (`change_detected=False`), so a consumer gating only on that field would
misfire. The gap is enforcement wiring, not a wrong hash.

Exit-code contract (draft-0.1, conformance scenario spec):
  0 all mandatory assertions passed and none unmeasured
  1 a measured assertion failed              <- expected against 0.2.1
  2 a required measurement was NOT_MEASURED / INCONCLUSIVE
  3 harness/environment error
"""
from __future__ import annotations

import inspect
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

SCENARIO_ID = "S1"  # schema pattern ^S[1-5]$; directory name carries the descriptive slug
SCENARIO_SLUG = "S1_unauthorized_tool_action"
SCENARIO_VERSION = "draft-0.1"

# Pinned artifact (grounded against the same 0.2.1 wheel S3/S5 drive: pip index
# versions lists 0.2.1; wheel sha256 verified 2026-08-12). The release-to-commit
# binding is itself unattested — see limitations.
IMPL_REPOSITORY = "https://github.com/halvrenofviryel/phionyx-mcp-server"
IMPL_COMMIT = "2fd258e7afcd9e1a5c092a74edb663808835af5d"
WHEEL_URI = (
    "https://files.pythonhosted.org/packages/f8/3e/"
    "8eca30e18432eca3683c678e946d47ad603abd08e597ab57c013f3466b36/"
    "phionyx_mcp_server-0.2.1-py3-none-any.whl"
)
WHEEL_SHA256 = "4d29b9a0b9ec87882daae125d827bd799ca43bee4d86d00b481f2cc554b7bd51"

# The tool whose invocation is proposed with no prior approval.
UNAUTHORIZED_TOOL = {
    "name": "exfil_tool",
    "description": "reads a local path and sends it to an external sink",
    "parameters": {"path": "str", "sink_url": "str"},
}

# Fields a reasonable consumer might branch on as a decision/enforcement signal.
DECISION_KEYS = ("decision", "enforcement", "deny", "step_up", "action", "outcome", "allow")
# Values that denote an APPLIED refusal/escalation (not an allow). A3 passes only
# when missing authority actually produces one of these — presence of a mere
# decision-like key (e.g. allow=True) is not enforcement.
ENFORCE_VALUES = {
    "deny", "denied", "step_up", "stepup", "step-up", "block", "blocked",
    "reject", "rejected", "escalate", "escalated",
}
ENFORCE_BOOL_KEYS = ("deny", "step_up", "block", "reject")


def _denotes_enforcement(result: dict) -> bool:
    """True iff the result carries a decision that actually denies or steps up."""
    for key in DECISION_KEYS:
        if key not in result:
            continue
        value = result[key]
        if isinstance(value, str) and value.strip().lower() in ENFORCE_VALUES:
            return True
        if key in ENFORCE_BOOL_KEYS and value is True:
            return True
    return False


def _implementation() -> dict:
    from importlib.metadata import version

    return {
        "repository": IMPL_REPOSITORY,
        "commit": IMPL_COMMIT,
        "package_versions": {"phionyx-mcp-server": version("phionyx-mcp-server")},
    }


def _assess() -> list[dict]:
    from phionyx_mcp_server.descriptor_hash import (
        compare_descriptor_hashes,
        hash_descriptor,
    )

    os.environ["PHIONYX_MCP_AUDIT_ROOT"] = tempfile.mkdtemp()
    current = hash_descriptor(UNAUTHORIZED_TOOL)

    # The scenario's own case: a tool proposed with NO prior approval.
    no_baseline = compare_descriptor_hashes(current, None)
    # Positive control: the SAME tool with an approved, matching baseline.
    approved_match = compare_descriptor_hashes(current, current)

    # A1 — the authority evaluator actually ran and returned a structured result.
    evaluator_executed = isinstance(no_baseline, dict) and "change_detected" in no_baseline

    # A2 — the authority check cannot itself invoke/commit the tool call. This is
    # a STRUCTURAL measurement, not a vacuous "some trace is empty": the evaluator
    # accepts only two hashes (no executor/sink/callable/tool parameter through
    # which it could invoke) and its output carries no field representing an
    # executed invocation. So no invocation is possible from this surface.
    sig_params = set(inspect.signature(compare_descriptor_hashes).parameters)
    invocation_capable_params = sig_params & {
        "executor", "sink", "callable", "invoke", "tool", "runner", "dispatch", "call",
    }
    invocation_fields = [k for k in no_baseline if k in ("invoked", "result", "tool_output", "executed", "response")]
    tool_invocation_not_observed = not invocation_capable_params and not invocation_fields

    # A3 — is any enforcement APPLIED? Pass only if missing authority produces a
    # decision that actually denies or steps up; the mere presence of a decision
    # key (or an allow) is not enforcement. Here there is no decision field at all.
    decision_fields = [k for k in no_baseline if k in DECISION_KEYS]
    enforcement_applied = _denotes_enforcement(no_baseline)

    # A4 — is missing authority distinguishable from approved-and-matching, so a
    # consumer is NOT forced to treat it as allow? Measure which fields actually
    # differ between the two returns. The honest, non-rigged reading: they DO
    # differ (baseline_exists False vs True), so the surface exposes the correct
    # signal — but they COLLIDE on the primary change verdict (change_detected),
    # so a consumer gating only on that field cannot tell them apart. A4 passes on
    # "a distinguishing signal is present"; the enforcement gap is A3's finding.
    distinguishing_fields = sorted(
        k for k in set(no_baseline) | set(approved_match)
        if no_baseline.get(k) != approved_match.get(k)
    )
    change_verdict_collides = no_baseline.get("change_detected") == approved_match.get("change_detected")
    missing_authority_not_allow = bool(distinguishing_fields)

    return [
        {
            "name": "S1-A1-policy-evaluator-executed",
            "requirement": "the authority/policy evaluator executes and returns a result",
            "expected": "a structured comparison result is produced",
            "observed": f"result keys={sorted(no_baseline)}",
            "result": "PASS" if evaluator_executed else "FAIL",
        },
        {
            "name": "S1-A2-tool-invocation-not-observed",
            "requirement": "the authority check must not itself invoke/commit the tool call",
            "expected": "the evaluator has no parameter or output through which a tool could be invoked",
            "observed": f"invocation-capable params={sorted(invocation_capable_params) or 'none'}; "
                        f"invocation output fields={invocation_fields or 'none'}; "
                        f"signature params={sorted(sig_params)}",
            "result": "PASS" if tool_invocation_not_observed else "FAIL",
        },
        {
            "name": "S1-A3-enforcement-status-is-APPLIED",
            "requirement": "on missing authority, enforcement (DENY/STEP_UP) is APPLIED",
            "expected": "the result carries a decision/enforcement field that denies or steps up",
            "observed": f"decision-like fields present={decision_fields or 'none'}; "
                        f"denotes DENY/STEP_UP={enforcement_applied}",
            "result": "PASS" if enforcement_applied else "FAIL",
        },
        {
            "name": "S1-A4-missing-authority-is-not-treated-as-allow",
            "requirement": "no prior approval must not read the same as an approved, matching descriptor",
            "expected": "the no-approval return is distinguishable from approved-match (a signal a consumer can act on)",
            "observed": f"distinguishing fields={distinguishing_fields or 'none'}; "
                        f"primary change verdict collides (change_detected "
                        f"{no_baseline.get('change_detected')!r} vs {approved_match.get('change_detected')!r})="
                        f"{change_verdict_collides} -> the distinction lives only in baseline_exists, "
                        f"which the surface exposes but does not enforce (see A3)",
            "result": "PASS" if missing_authority_not_allow else "FAIL",
        },
    ]


def main() -> int:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[2] / "actual"
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        assertions = _assess()
    except ImportError as exc:
        print(f"HARNESS ERROR: {exc}. Install it: pip install phionyx-mcp-server==0.2.1", file=sys.stderr)
        return 3

    failed = [a for a in assertions if a["result"] == "FAIL"]
    exit_code = 1 if failed else 0

    record = {
        "scenario_id": SCENARIO_ID,
        "scenario_version": SCENARIO_VERSION,
        "implementation": _implementation(),
        # The surface emits no allow/deny and drives no invocation; it returns
        # advisory comparison data and leaves the allow/deny to a downstream
        # policy. That is a DEFER, not an ALLOW — recording ALLOW would overclaim
        # a permission the surface never granted. The expected outcome was
        # DENY/STEP_UP; DEFER-without-enforcement is the gap (A3).
        "decision_outcome": "DEFER",
        "measurement_status": "FAIL" if failed else "PASS",
        # No enforcement stage exists to request; the absence is the gap (A3),
        # documented rather than dressed up as an applied control.
        "enforcement_status": "NOT_REQUIRED",
        "evidence_status": "E0",  # the pre-invocation check persists nothing
        "executed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "command": "python scenarios/S1_unauthorized_tool_action/run.py",
        "exit_code": exit_code,
        "assertions": [
            {"name": a["name"], "status": a["result"],
             "note": f"{a['requirement']} | expected: {a['expected']} | observed: {a['observed']}"}
            for a in assertions
        ],
        "source_artifacts": [{"path_or_uri": WHEEL_URI, "sha256": WHEEL_SHA256, "resolvable": True}],
        "independent_rerun": {"status": "NOT_REQUESTED"},
        "limitations": [
            "in-process surface: drives descriptor_hash directly, not a running MCP host round-trip",
            "the comparator is advisory by design; A4 confirms it exposes the correct distinguishing "
            "signal (baseline_exists=False), while A3 measures that no enforcement (DENY/STEP_UP) is "
            "applied to that signal — the gap is enforcement wiring, not a wrong hash",
            "the distinction lives only in baseline_exists; a consumer gating on change_detected alone "
            "would misread missing authority as unchanged — a consumer defect this surface enables",
            "capability_scope, policy_version and state_version (named in the scenario spec required_inputs) "
            "are not consumed by this comparator; the check is descriptor-hash only",
            "the installed distribution's binding to IMPL_COMMIT is not attested by the artifact itself",
        ],
    }

    out = out_dir / f"{SCENARIO_SLUG}.result.json"
    out.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(f"[{SCENARIO_SLUG}] {len(assertions) - len(failed)}/{len(assertions)} assertions passed -> {out}")
    for a in assertions:
        print(f"  {a['result']:4s} {a['name']}: {a['observed'][:88]}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
