#!/usr/bin/env python3
"""S5 — a governance result that is missing, inconclusive or erroneous must not collapse into approval.

The scenario drives the published chain verifier through four states and asks,
for each, whether the answer distinguishes *checked and fine* from *never
checked*. Two of the four reproduce findings the project published against
itself (self-audit #1 empty chain returns valid, #2 a tampered signature
returns valid when no verifier is passed), so this fixture doubles as the
first-party re-measurement those correction rows are waiting on (first-party:
run inside this project, not yet reproduced by anyone outside it).

Exit-code contract (draft-0.1, conformance scenario spec):
  0 all mandatory assertions passed and none unmeasured
  1 a measured assertion failed
  2 a required measurement was NOT_MEASURED or INCONCLUSIVE
  3 harness/environment error
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

SCENARIO_ID = "S5"
SCENARIO_SLUG = "S5_nonmeasurement_collapse"
SCENARIO_VERSION = "draft-0.1"
# Pins below were grounded 2026-08-06: `pip index versions`, `curl -sI` on the
# wheel (HTTP 200), `gh api .../commits/main`. The release-to-commit binding is
# itself unattested — see limitations.
IMPL_REPOSITORY = "https://github.com/halvrenofviryel/phionyx-mcp-server"
IMPL_COMMIT = "2fd258e7afcd9e1a5c092a74edb663808835af5d"
WHEEL_URI = (
    "https://files.pythonhosted.org/packages/f8/3e/"
    "8eca30e18432eca3683c678e946d47ad603abd08e597ab57c013f3466b36/"
    "phionyx_mcp_server-0.2.1-py3-none-any.whl"
)
WHEEL_SHA256 = "4d29b9a0b9ec87882daae125d827bd799ca43bee4d86d00b481f2cc554b7bd51"


def _implementation() -> dict:
    from importlib.metadata import version

    return {
        "repository": IMPL_REPOSITORY,
        "commit": IMPL_COMMIT,
        "package_versions": {"phionyx-mcp-server": version("phionyx-mcp-server")},
    }


def _two_envelope_chain() -> list[dict]:
    os.environ["PHIONYX_MCP_AUDIT_ROOT"] = tempfile.mkdtemp()
    from phionyx_mcp_server.audit_chain import (
        FilesystemEnvelopeStore,
        HmacSigner,
        ToolCallContext,
        build_envelope,
    )

    store = FilesystemEnvelopeStore()
    signer = HmacSigner("s5-fixture-key")
    envelopes: list[dict] = []
    previous = store.head("s5")
    for turn in range(2):
        ctx = ToolCallContext(
            trace_id="s5", turn_index=turn, user_text=f"turn {turn}", producer="phionyx-conformance",
            tool_descriptor_hash=None, descriptor_change_detected=None, tool_permission_scope=None,
            input_hash=None, output_hash=None, approval_state=None, anomaly_flag=None,
            decision="release", decision_reason="S5 fixture", runtime_policy_basis=["s5-fixture"],
        )
        envelope = build_envelope(ctx, previous_hash=previous, server_version="conformance", signer=signer)
        envelopes.append(envelope)
        previous = envelope["integrity"]["current"]
    return envelopes


def _clone(envelopes: list[dict]) -> list[dict]:
    return json.loads(json.dumps(envelopes))


def _assess() -> list[dict]:
    from phionyx_mcp_server.audit_chain import verify_chain

    chain = _two_envelope_chain()

    tampered = _clone(chain)
    tampered[1]["integrity"]["signature"] = "demo-hmac:" + "0" * 16

    broken = _clone(chain)
    broken[1]["integrity"]["previous"] = "sha256:" + "f" * 64

    empty_r = verify_chain([])
    tampered_r = verify_chain(tampered)
    intact_r = verify_chain(chain)
    broken_r = verify_chain(broken)

    def collapsed(result: dict) -> bool:
        """Did a non-measurement come back as a positive verdict?"""
        return result.get("valid") is True

    return [
        {
            "name": "S5-A1-empty-input-is-not-a-pass",
            "requirement": "an evaluator with nothing to check reports NOT_MEASURED, never valid",
            "expected": "valid is not True; measurement_status NOT_MEASURED",
            "observed": f"valid={empty_r.get('valid')!r} measurement_status={empty_r.get('measurement_status')!r} cause={empty_r.get('non_measurement_cause')!r}",
            "result": "PASS" if (not collapsed(empty_r) and empty_r.get("measurement_status") == "NOT_MEASURED") else "FAIL",
        },
        {
            "name": "S5-A2-unverified-signature-is-not-a-pass",
            "requirement": "a tampered signature must not read as valid merely because no verifier ran",
            "expected": "valid is not True; the answer says signatures were not verified",
            "observed": f"valid={tampered_r.get('valid')!r} measurement_status={tampered_r.get('measurement_status')!r} signatures_verified={tampered_r.get('signatures_verified')!r}",
            "result": "PASS" if (not collapsed(tampered_r) and tampered_r.get("signatures_verified") is False) else "FAIL",
        },
        {
            "name": "S5-A3-intact-chain-without-verifier-claims-no-more-than-it-checked",
            "requirement": "an intact chain checked WITHOUT signature verification is still not 'valid'",
            "expected": "valid is not True; the unchecked scope is named",
            "observed": f"valid={intact_r.get('valid')!r} measurement_status={intact_r.get('measurement_status')!r} reason={str(intact_r.get('reason'))[:70]!r}",
            "result": "PASS" if not collapsed(intact_r) else "FAIL",
        },
        {
            "name": "S5-A4-a-real-failure-reports-as-a-failure",
            "requirement": "a genuinely broken chain reports FAIL, not NOT_MEASURED (the mirror-image collapse)",
            "expected": "valid is False and the break is located",
            "observed": f"valid={broken_r.get('valid')!r} broken_at={broken_r.get('broken_at')!r}",
            "result": "PASS" if (broken_r.get("valid") is False and broken_r.get("broken_at") is not None) else "FAIL",
        },
        {
            "name": "S5-A5-every-answer-carries-a-measurement-status",
            "requirement": "the four states are distinguishable by a machine reading one field",
            "expected": "measurement_status present on all four results",
            "observed": "present on: " + (", ".join(
                n for n, r in (("empty", empty_r), ("tampered", tampered_r), ("intact", intact_r), ("broken", broken_r))
                if "measurement_status" in r
            ) or "none"),
            "result": "PASS" if all("measurement_status" in r for r in (empty_r, tampered_r, intact_r, broken_r)) else "FAIL",
        },
    ]


def main() -> int:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[2] / "actual"
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        assertions = _assess()
    except ImportError as exc:  # the implementation under test is absent
        print(f"HARNESS ERROR: {exc}. Install it: pip install phionyx-mcp-server==0.2.1", file=sys.stderr)
        return 3

    failed = [a for a in assertions if a["result"] == "FAIL"]
    exit_code = 1 if failed else 0

    record = {
        "scenario_id": SCENARIO_ID,
        "scenario_version": SCENARIO_VERSION,
        "implementation": _implementation(),
        "decision_outcome": "ALLOW",
        "measurement_status": "PASS" if not failed else "FAIL",
        "enforcement_status": "NOT_REQUIRED",
        "evidence_status": "E2",
        "executed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "command": "python conformance/scenarios/S5_nonmeasurement_collapse/run.py",
        "exit_code": exit_code,
        "assertions": [
            {"name": a["name"], "status": a["result"],
             "note": f"{a['requirement']} | expected: {a['expected']} | observed: {a['observed']}"}
            for a in assertions
        ],
        "source_artifacts": [{"path_or_uri": WHEEL_URI, "sha256": WHEEL_SHA256, "resolvable": True}],
        "independent_rerun": {"status": "NOT_REQUESTED"},
        "limitations": [
            "in-process surface: calls verify_chain directly, not through a running MCP host",
            "signature verification with a real verifier is not exercised — the scenario is about what "
            "the answer claims when verification did NOT run",
            "HMAC signer only; the Ed25519 path is not covered here",
            "four states only: a missing policy file, an evaluator raising, and an unrecognised return "
            "type are named in the scenario spec and are not yet driven",
            "the installed distribution's binding to IMPL_COMMIT is not attested by the artifact itself",
        ],
    }

    out = out_dir / f"{SCENARIO_SLUG}.result.json"
    out.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(f"[{SCENARIO_SLUG}] {len(assertions) - len(failed)}/{len(assertions)} assertions passed -> {out}")
    for a in assertions:
        print(f"  {a['result']:4s} {a['name']}: {a['observed'][:96]}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
