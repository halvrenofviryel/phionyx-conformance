#!/usr/bin/env python3
"""S4 — A decision cannot be replayed/committed against unresolved or mismatched policy/state versions.

An envelope records the policy/state version it was produced under. The scenario
asks whether the shipped verifier does anything with that record on replay: does
it resolve the version to a fetchable artifact, fail a mismatch, decline to
measure when a required artifact is unavailable, and refuse to silently swap in
the current version? Or does it verify hash + signature and treat the recorded
version as decoration?

Target implementation: phionyx-mcp-server 0.2.1, imported in-process. The
surface under test is `audit_chain.verify_chain` (with a signature verifier, so
the base verdict is a real PASS, not the no-verifier NOT_MEASURED of S5). The
envelope records the version under `subject.version` and the schema id under
`schema`.

What this measures — and its honest split: the recorded version is hash-bound,
so it CANNOT be silently substituted (A4 passes: tampering it breaks the chain).
But the verifier takes no compatibility rule and no artifact set, performs no
resolution, and returns the SAME verdict whether the recorded version matches a
required one or not — so presence is never turned into fetchability (A1), a
mismatch is never a FAIL (A2), and an unavailable required artifact never yields
a NOT_MEASURED attributable to it (A3). The surface records the version
faithfully and does nothing with it.

Exit-code contract (draft-0.1, conformance scenario spec):
  0 all mandatory assertions passed and none unmeasured
  1 a measured assertion failed              <- expected against 0.2.1
  2 a required measurement was NOT_MEASURED / INCONCLUSIVE
  3 harness/environment error
"""
from __future__ import annotations

import copy
import inspect
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

SCENARIO_ID = "S4"  # schema pattern ^S[1-5]$; directory name carries the descriptive slug
SCENARIO_SLUG = "S4_policy_state_version_mismatch"
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

RECORDED_VERSION = "policy-v1"       # the version the decision was produced under
REQUIRED_VERSION = "policy-v2"       # the compatibility rule's required version (a mismatch)
SUBSTITUTED_VERSION = "policy-CURRENT-substituted"


def _implementation() -> dict:
    from importlib.metadata import version

    return {
        "repository": IMPL_REPOSITORY,
        "commit": IMPL_COMMIT,
        "package_versions": {"phionyx-mcp-server": version("phionyx-mcp-server")},
    }


def _assess() -> list[dict]:
    from phionyx_mcp_server.audit_chain import (
        GENESIS_HASH,
        HmacSigner,
        ToolCallContext,
        build_envelope,
        verify_chain,
    )

    os.environ["PHIONYX_MCP_AUDIT_ROOT"] = tempfile.mkdtemp()
    signer = HmacSigner("s4-fixture-key")

    # A signature verifier so the base verdict is a genuine PASS (not S5's
    # no-verifier NOT_MEASURED). The shipped HmacSigner satisfies the Verifier
    # protocol's .verify(current_hash, signature) -> bool; wrap it explicitly so
    # the delegation is visible.
    class _SignerVerifier:
        def __init__(self, s):
            self._s = s

        def verify(self, current_hash: str, signature: str) -> bool:
            return self._s.verify(current_hash, signature)

    verifier = _SignerVerifier(signer)

    def one_envelope(version: str) -> dict:
        ctx = ToolCallContext(
            trace_id="s4", turn_index=0, user_text="decision under a recorded policy version",
            producer="phionyx-conformance", tool_descriptor_hash=None, descriptor_change_detected=None,
            tool_permission_scope=None, input_hash=None, output_hash=None, approval_state=None,
            anomaly_flag=None, decision="release", decision_reason="S4 fixture",
            runtime_policy_basis=["input_safety_gate"],
        )
        return build_envelope(ctx, previous_hash=GENESIS_HASH, server_version=version, signer=signer)

    chain_recorded = [one_envelope(RECORDED_VERSION)]   # decision recorded at policy-v1
    chain_required = [one_envelope(REQUIRED_VERSION)]   # a chain recorded at policy-v2

    verdict_recorded = verify_chain(chain_recorded, verifier=verifier)
    verdict_required = verify_chain(chain_required, verifier=verifier)

    # The scenario's required inputs that this surface gives NO channel for: a
    # compatibility rule (require policy-v2) and an artifact set the recorded
    # version's artifact is absent from. We hold them here to make the point
    # concrete, then show verify_chain has nowhere to receive them — the finding
    # is the ABSENCE of a version-compatibility surface, not a defect within one.
    compatibility_rule = {"required_version": REQUIRED_VERSION}   # held by the fixture, unused by the surface
    available_artifacts: set[str] = set()                        # recorded version's artifact is NOT present
    verify_params = set(inspect.signature(verify_chain).parameters)
    resolution_channel = verify_params & {
        "available_artifacts", "compatibility_rule", "required_version", "artifacts",
        "policy_version", "state_version", "resolver", "registry",
    }
    has_resolution_channel = bool(resolution_channel)
    recorded_version_present = chain_recorded[0].get("subject", {}).get("version") == RECORDED_VERSION

    # A1 — presence != fetchability. Behavioural: verify reaches PASS from a
    # present version string while the recorded version's artifact is absent from
    # `available_artifacts` and there is no channel to supply it. So the PASS did
    # not depend on resolving the artifact — presence was accepted as if fetchable.
    recorded_artifact_available = RECORDED_VERSION in available_artifacts  # False by construction
    verify_passed_without_resolution = (
        verdict_recorded.get("measurement_status") == "PASS"
        and not recorded_artifact_available
        and not has_resolution_channel
    )
    presence_not_fetchability = not verify_passed_without_resolution

    # A2 — a mismatch must be FAIL. The compatibility rule has no channel into
    # verify_chain, and the verdict is invariant to the recorded version: a chain
    # recorded at policy-v1 verifies exactly like one at policy-v2 (both PASS).
    both_pass = (verdict_recorded.get("measurement_status") == "PASS"
                 and verdict_required.get("measurement_status") == "PASS")
    verdict_ignores_version = (
        verdict_recorded.get("measurement_status") == verdict_required.get("measurement_status")
        and verdict_recorded.get("valid") == verdict_required.get("valid")
    )
    mismatch_is_fail = not (both_pass and verdict_ignores_version and not has_resolution_channel)

    # A3 — an unavailable required artifact must yield NOT_MEASURED attributable to
    # it. There is no artifact channel, so the required-artifact premise cannot
    # enter; the fully-signed chain returns PASS, and no path exists by which an
    # unavailable artifact could produce a NOT_MEASURED.
    unavailable_artifact_not_measured = verdict_recorded.get("measurement_status") == "NOT_MEASURED"

    # A4 — the recorded version must not be silently substituted. It is hash-bound:
    # reading it back yields the recorded value, and substituting a "current" value
    # breaks the chain (verify detects it). Substitution cannot pass unnoticed.
    read_back = chain_recorded[0]["subject"]["version"]
    tampered = copy.deepcopy(chain_recorded)
    tampered[0]["subject"]["version"] = SUBSTITUTED_VERSION
    tampered_verdict = verify_chain(tampered, verifier=verifier)
    substitution_detected = (
        read_back == RECORDED_VERSION
        and tampered_verdict.get("valid") is False
        and tampered_verdict.get("broken_at") is not None
    )

    return [
        {
            "name": "S4-A1-digest-presence-not-equal-fetchability",
            "requirement": "a recorded version/digest being present must not be treated as the artifact being fetchable",
            "expected": "the PASS depends on resolving the recorded version's artifact (verifier can receive/resolve one)",
            "observed": f"recorded subject.version present={recorded_version_present}; its artifact in available_artifacts="
                        f"{recorded_artifact_available}; verify(recorded)={verdict_recorded.get('measurement_status')} "
                        f"reached with no resolution channel (params={sorted(verify_params)}) => presence accepted as fetchable",
            "result": "PASS" if presence_not_fetchability else "FAIL",
        },
        {
            "name": "S4-A2-mismatch-is-FAIL",
            "requirement": "a decision recorded under a version that mismatches the required one must verify as FAIL",
            "expected": "the compatibility rule can enter the verifier and a mismatched recorded version yields FAIL",
            "observed": f"compatibility rule {compatibility_rule} has no channel (resolution params="
                        f"{sorted(resolution_channel) or 'none'}); verify(recorded {RECORDED_VERSION})="
                        f"{verdict_recorded.get('measurement_status')} == verify({REQUIRED_VERSION})="
                        f"{verdict_required.get('measurement_status')}; verdict invariant to recorded version="
                        f"{verdict_ignores_version}",
            "result": "PASS" if mismatch_is_fail else "FAIL",
        },
        {
            "name": "S4-A4-current-version-not-silently-substituted",
            "requirement": "the recorded version must not be silently replaced by the current one",
            "expected": "the recorded version is read back verbatim and substituting it is detected",
            "observed": f"read_back={read_back!r}; after substituting to {SUBSTITUTED_VERSION!r}: "
                        f"valid={tampered_verdict.get('valid')!r}, broken_at={tampered_verdict.get('broken_at')!r}",
            "result": "PASS" if substitution_detected else "FAIL",
        },
        {
            "name": "S4-A3-unavailable-required-artifact-is-NOT_MEASURED",
            "requirement": "when a required policy/state artifact is unavailable, the verdict must be NOT_MEASURED, not PASS",
            "expected": "an unavailable required artifact produces a NOT_MEASURED attributable to it",
            "observed": f"no artifact channel exists (resolution params={sorted(resolution_channel) or 'none'}), so the "
                        f"required-artifact premise cannot enter; verify(recorded)={verdict_recorded.get('measurement_status')} "
                        f"(valid={verdict_recorded.get('valid')!r}) => no unavailable artifact can cause a NOT_MEASURED",
            "result": "PASS" if unavailable_artifact_not_measured else "FAIL",
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
        # verify_chain is an integrity verifier, not a replay/commit authority: it
        # returns a hash+signature verdict and makes NO policy/state-version
        # decision — that decision is left to a downstream consumer it gives no
        # version signal to make. That is a DEFER, not an ALLOW (ALLOW would claim
        # a permit this surface never issues). The expected outcome was DENY/DEFER
        # WITH the mismatch resolved; here it defers WITHOUT resolving (A1-A3).
        "decision_outcome": "DEFER",
        "measurement_status": "FAIL" if failed else "PASS",
        # No version-compatibility enforcement stage exists to request; the absence
        # is the gap, documented rather than dressed as an applied control.
        "enforcement_status": "NOT_REQUIRED",
        "evidence_status": "E2",  # envelopes signed + hash-chained
        "executed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "command": "python conformance/scenarios/S4_policy_state_version_mismatch/run.py",
        "exit_code": exit_code,
        "assertions": [
            {"name": a["name"], "status": a["result"],
             "note": f"{a['requirement']} | expected: {a['expected']} | observed: {a['observed']}"}
            for a in assertions
        ],
        "source_artifacts": [{"path_or_uri": WHEEL_URI, "sha256": WHEEL_SHA256, "resolvable": True}],
        "independent_rerun": {"status": "NOT_REQUESTED"},
        "limitations": [
            "in-process surface: drives verify_chain directly, not a running MCP host round-trip",
            "A3's 'required artifact unavailable' is a premise of the scenario, not a fetch this fixture "
            "attempts — the point is that verify_chain never requires or resolves such an artifact, so no "
            "verdict can be attributed to its absence; a host that added artifact resolution could exercise "
            "the fetch itself",
            "A1/A2/A3 measure the ABSENCE of a version-compatibility evaluator, not a defect within one; "
            "A4 confirms the recorded version is hash-bound and tamper-evident",
            "signature verification uses the fixture's own HMAC signer wrapped as the Verifier; the Ed25519 "
            "path and the shipped no-verifier default (see S5) are out of scope here",
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
