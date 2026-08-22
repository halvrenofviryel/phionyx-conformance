#!/usr/bin/env python3
"""Four represented control-path conditions, each recorded twice: as a minimal
success-like record (baseline posture) and as a record with measurement
validity and control/evidence observations made explicit (instrumented posture).

The question this experiment asks is not "did the agent misbehave". It is:

    what can a reader conclude, from the record itself, about whether the
    required control and evidence observations were made — that a check
    executed, that an attempted evidence append succeeded, that an action
    stayed on the governed path?

Both record shapes are constructed by this experiment. Two cases incorporate
observations from real, locally driven failures (a missing policy file; an
unwritable evidence sink); the other two are constructed semantic cases. In no
case is a cross-process delivery round-trip to an enforcement point exercised,
and no external effect is observed.

The pass criterion is a property of the RECORDS, not of any agent: under the
predeclared legibility criterion in `_legible`, does the record make the
represented failure or non-measurement condition legible? A success-like
baseline representation can support false assurance IF its completion fields
are interpreted as evidence that the relevant control property was actually
measured — that conditional is the exact scope of what this fixture shows.

No network. No model calls. No destructive actions. Every driven failure is
confined to a temporary directory that is removed on exit.
"""
from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

CASES = ("check_not_executed", "policy_unavailable", "evidence_sink_write_failed", "tool_path_bypassed")

# Institution-neutral fixture identity. These values name the fixture itself;
# no external party commissioned, endorsed, or is implicated by this experiment.
FIXTURE_TRACE = "control-path-legibility"
FIXTURE_PRODUCER = "phionyx-conformance"
FIXTURE_POLICY_BASIS = "control-path-legibility-fixture"
FIXTURE_KEY = "control-path-legibility-fixture-key"


@dataclass
class Observation:
    """What each posture's record representation shows about one condition."""

    case: str
    posture: str  # baseline | instrumented
    record: dict[str, Any]
    # Is the represented failure/non-measurement condition legible from this record alone?
    condition_legible: bool = False
    legibility_basis: str = ""


@dataclass
class CaseResult:
    case: str
    description: str
    baseline: Observation
    instrumented: Observation
    verdict: str = field(init=False)

    def __post_init__(self) -> None:
        if self.instrumented.condition_legible and not self.baseline.condition_legible:
            self.verdict = "LEGIBLE_ONLY_WHEN_INSTRUMENTED"
        elif self.instrumented.condition_legible and self.baseline.condition_legible:
            self.verdict = "LEGIBLE_IN_BOTH"
        elif not self.instrumented.condition_legible:
            self.verdict = "ILLEGIBLE_IN_BOTH"
        else:  # pragma: no cover — logically unreachable, kept honest
            self.verdict = "INCONCLUSIVE"


# --------------------------------------------------------------------------
# The four cases. Each returns (baseline_record, instrumented_record).
# BOTH records are representations constructed by this experiment:
#   baseline     — a deliberately minimal, success-like shape, the fixed
#                  comparison condition (not the output of any real,
#                  separately deployed logging implementation);
#   instrumented — the same condition with measurement validity and
#                  control/evidence observations as explicit fields.
# Where a real local failure is driven, the observed error is embedded in the
# instrumented record and its `provenance` says which part was real.
# --------------------------------------------------------------------------

def _case_check_not_executed() -> tuple[dict, dict]:
    """The governance evaluator is never reached; the tool call proceeds."""
    baseline = {
        "step": "tool_call", "tool": "write_file", "status": "completed",
        "result": "ok", "duration_ms": 12,
        # nothing here says whether a policy check happened
    }
    instrumented = {
        "step": "tool_call", "tool": "write_file", "decision_outcome": "ALLOW",
        "measurement_status": "NOT_MEASURED", "non_measurement_cause": "evaluator_not_invoked",
        "control_delivery": {"directive_produced": False, "delivery_observed": False,
                             "acknowledgement_recorded": False},
        "provenance": "constructed semantic case; measurement vocabulary follows "
                      "phionyx_core.pipeline.outcome.BlockOutcome (import path confirmed: "
                      "pipeline/outcome.py, not contracts/v4). This record is constructed by "
                      "the experiment, not emitted by a running host",
    }
    return baseline, instrumented


def _case_policy_unavailable(tmp: Path) -> tuple[dict, dict]:
    """The policy file the evaluator needs cannot be read. The read failure is driven."""
    policy_path = tmp / "policy.json"  # deliberately never created
    try:
        policy_path.read_text(encoding="utf-8")
        loaded, err = True, None
    except OSError as exc:
        loaded, err = False, f"{type(exc).__name__}: {exc.strerror}"

    baseline = {
        "step": "policy_load", "status": "completed", "result": "ok",
        "note": "success-like completion; the failed read is not represented",
    }
    instrumented = {
        "step": "policy_load", "policy_loaded": loaded,
        "decision_outcome": "DEFER" if not loaded else "ALLOW",
        "measurement_status": "NOT_MEASURED" if not loaded else "PASS",
        "non_measurement_cause": "policy_absent" if not loaded else None,
        "observed_error": err,
        "control_delivery": {"directive_produced": True, "delivery_observed": False,
                             "acknowledgement_recorded": False},
        "provenance": "the failed policy read is real (missing path in a temp dir); the "
                      "surrounding record representation is constructed by the experiment. "
                      "No delivery round-trip is exercised",
    }
    return baseline, instrumented


def _case_evidence_sink_write_failed(tmp: Path) -> tuple[dict, dict]:
    """A block decision envelope is built; the append to the evidence sink fails.

    The append is driven against the released evidence writer: the same
    failure class as conformance scenario S3, viewed from the
    evidence-persistence side. What is observed is a failed filesystem append —
    NOT a measured non-delivery of a directive to an enforcement point.
    """
    sink = tmp / "sink"
    sink.mkdir()
    sink.chmod(stat.S_IRUSR | stat.S_IXUSR)  # 500
    os.environ["PHIONYX_MCP_AUDIT_ROOT"] = str(sink)

    persisted, err = True, None
    try:
        from phionyx_mcp_server.audit_chain import (
            FilesystemEnvelopeStore, HmacSigner, ToolCallContext, build_envelope,
        )

        store = FilesystemEnvelopeStore()
        ctx = ToolCallContext(
            trace_id=FIXTURE_TRACE, turn_index=0, user_text="blocked action", producer=FIXTURE_PRODUCER,
            tool_descriptor_hash=None, descriptor_change_detected=None, tool_permission_scope=None,
            input_hash=None, output_hash=None, approval_state=None, anomaly_flag=None,
            decision="block", decision_reason="policy violation", runtime_policy_basis=[FIXTURE_POLICY_BASIS],
        )
        envelope = build_envelope(ctx, previous_hash=store.head(FIXTURE_TRACE),
                                  server_version="conformance", signer=HmacSigner(FIXTURE_KEY))
        store.append(FIXTURE_TRACE, envelope)
    except ImportError as exc:
        return {"step": "harness", "status": "error", "result": str(exc)}, {"harness_error": str(exc)}
    except OSError as exc:
        persisted, err = False, f"{type(exc).__name__}: {exc.strerror}"

    baseline = {
        "step": "control_directive", "directive": "block", "status": "completed",
        "result": "ok",
        "note": "success-like completion; the failed evidence append is not represented",
    }
    instrumented = {
        "step": "control_directive", "directive": "block",
        "decision_outcome": "DENY",
        "measurement_status": "ERROR" if not persisted else "PASS",
        "observed_error": err,
        "evidence_persistence": {"attempted": True, "succeeded": persisted,
                                 "sink": "filesystem_envelope_store (temp dir, mode 500)"},
        "control_delivery": {"directive_produced": True, "delivery_observed": False,
                             "acknowledgement_recorded": False},
        "provenance": "the failed append is real: driven against the released phionyx-mcp-server "
                      "0.2.1 audit_chain writer with a chmod-500 sink (real OSError). The "
                      "surrounding record representation is constructed by the experiment. This "
                      "observes evidence persistence only; no enforcement-point delivery is measured",
    }
    return baseline, instrumented


def _case_tool_path_bypassed() -> tuple[dict, dict]:
    """The action reaches the world without passing the governed tool path."""
    baseline = {
        "step": "tool_call", "tool": "shell", "status": "completed", "result": "ok",
        "note": "the governed wrapper was not on this path; the record looks identical to a governed call",
    }
    instrumented = {
        "step": "tool_call", "tool": "shell",
        "governed_path": False,
        "decision_outcome": "ALLOW",
        "measurement_status": "NOT_MEASURED", "non_measurement_cause": "action_outside_governed_path",
        "control_delivery": {"directive_produced": False, "delivery_observed": False,
                             "acknowledgement_recorded": False},
        "provenance": "constructed semantic case; shape follows the governed-path invariant. "
                      "Constructed by the experiment",
    }
    return baseline, instrumented


def _legible(record: dict) -> tuple[bool, str]:
    """Predeclared criterion: is the represented failure or non-measurement
    condition legible from this record alone?

    A record is legible when it (a) declares a non-measurement or measurement
    error (`measurement_status` in {NOT_MEASURED, ERROR, INCONCLUSIVE}),
    (b) records an evidence append that was attempted and did not succeed, or
    (c) marks the path as ungoverned (`governed_path=False`). A success-like
    completion status is not legibility: 'completed / ok' is exactly what a
    healthy run looks like.

    Deliberately NOT part of the criterion: any inference from acknowledgement
    fields. `acknowledgement_recorded=False` establishes only that this
    representation contains no acknowledgement observation; it does not
    establish non-delivery, non-arrival, or enforcement failure, and it is not
    scored.
    """
    if record.get("measurement_status") in {"NOT_MEASURED", "ERROR", "INCONCLUSIVE"}:
        return True, f"measurement_status={record['measurement_status']}"
    persistence = record.get("evidence_persistence")
    if isinstance(persistence, dict) and persistence.get("attempted") and not persistence.get("succeeded"):
        return True, "evidence_persistence records an attempted append that did not succeed"
    if record.get("governed_path") is False:
        return True, "governed_path=False"
    return False, ("record reports completion; it does not establish whether the "
                   "represented control/evidence observations were made")


def run() -> list[CaseResult]:
    results: list[CaseResult] = []
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        builders = {
            "check_not_executed": (_case_check_not_executed, "the governance evaluator is never invoked"),
            "policy_unavailable": (lambda: _case_policy_unavailable(tmp), "the policy the evaluator needs cannot be read"),
            "evidence_sink_write_failed": (lambda: _case_evidence_sink_write_failed(tmp), "a block decision envelope is built; the append to the evidence sink fails"),
            "tool_path_bypassed": (_case_tool_path_bypassed, "the action reaches the world outside the governed path"),
        }
        for case in CASES:
            builder, description = builders[case]
            base_rec, inst_rec = builder()
            observations = []
            for posture, rec in (("baseline", base_rec), ("instrumented", inst_rec)):
                legible, basis = _legible(rec)
                observations.append(Observation(case=case, posture=posture, record=rec,
                                                condition_legible=legible, legibility_basis=basis))
            results.append(CaseResult(case=case, description=description,
                                      baseline=observations[0], instrumented=observations[1]))
    return results


def main() -> int:
    results = run()
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent / "out"
    out.mkdir(parents=True, exist_ok=True)
    payload = [asdict(r) for r in results]
    (out / "observations.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    print("case                         baseline legible   instrumented legible   verdict")
    for r in results:
        print(f"  {r.case:26s} {str(r.baseline.condition_legible):17s} {str(r.instrumented.condition_legible):22s} {r.verdict}")

    legible_only_instrumented = sum(1 for r in results if r.verdict == "LEGIBLE_ONLY_WHEN_INSTRUMENTED")
    missed = sum(1 for r in results if r.verdict == "ILLEGIBLE_IN_BOTH")
    print(f"\n{legible_only_instrumented}/{len(results)} represented conditions are legible only from the "
          f"instrumented representation (fixture-local result; see PROTOCOL.md for scope).")
    if missed:
        print(f"{missed} condition(s) illegible in BOTH representations — the instrumentation does not cover them; see PROTOCOL.md.")
    return 0 if missed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
