#!/usr/bin/env python3
"""Turn the injection observations into two Inspect `.eval` logs — baseline and instrumented.

One sample per injected failure. The score answers one question and only that
one: *from this posture's record alone, can a reader establish that the control
did not do its job?* A sample scores I (incorrect) when the record reports
completion while the control silently did nothing — that is false assurance,
and it is what the baseline log is expected to be full of.

Written against Inspect AI's public log API (`inspect_ai.log`), measured at
version 0.3.252. It constructs logs directly rather than running a task,
because there is no model in this experiment: the subject under evaluation is
the RECORD, not an agent.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from inspect_ai.log import (
    EvalConfig,
    EvalDataset,
    EvalLog,
    EvalPlan,
    EvalResults,
    EvalSample,
    EvalSpec,
    EvalStats,
    write_eval_log,
)
from inspect_ai.scorer import Score

TASK = "control_delivery_legibility"


def _sample(index: int, case: dict, posture: str) -> EvalSample:
    obs = case[posture]
    legible = obs["failure_legible"]
    return EvalSample(
        id=case["case"],
        epoch=1,
        input=case["description"],
        target="the record makes the control failure legible",
        metadata={
            "posture": posture,
            "record": obs["record"],
            "legibility_basis": obs["legibility_basis"],
            "verdict": case["verdict"],
        },
        scores={
            "failure_legible": Score(
                value="C" if legible else "I",
                answer="legible" if legible else "reports completion; control status unknowable",
                explanation=obs["legibility_basis"],
            )
        },
    )


def _log(observations: list[dict], posture: str, created: str) -> EvalLog:
    samples = [_sample(i, case, posture) for i, case in enumerate(observations)]
    legible = sum(1 for s in samples if s.scores["failure_legible"].value == "C")
    return EvalLog(
        eval=EvalSpec(
            created=created,
            task=f"{TASK}/{posture}",
            dataset=EvalDataset(name="injected_control_path_failures", samples=len(samples)),
            model="none/record-under-evaluation",
            config=EvalConfig(),
            metadata={
                "posture": posture,
                "question": "does this posture's record establish that the control ran, "
                            "that its directive was delivered, and that a missing policy or failed "
                            "evidence write was not reported as success?",
                "no_network": True,
                "no_model_calls": True,
            },
        ),
        plan=EvalPlan(name=TASK),
        results=EvalResults(total_samples=len(samples), completed_samples=len(samples)),
        stats=EvalStats(started_at=created, completed_at=created),
        status="success",
        samples=samples,
        metadata={"legible_of_total": f"{legible}/{len(samples)}"},
    )


def main() -> int:
    here = Path(__file__).resolve().parent
    observations = json.loads((here / "out" / "observations.json").read_text(encoding="utf-8"))
    created = datetime.now(timezone.utc).isoformat(timespec="seconds")
    logs_dir = here / "out" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    written = []
    for posture in ("baseline", "instrumented"):
        log = _log(observations, posture, created)
        path = logs_dir / f"{posture}.eval"
        write_eval_log(log, str(path))
        legible = sum(1 for s in log.samples if s.scores["failure_legible"].value == "C")
        written.append((posture, path, legible, len(log.samples)))
        print(f"{posture:13s} {legible}/{len(log.samples)} failures legible -> {path}")

    base = next(w for w in written if w[0] == "baseline")
    inst = next(w for w in written if w[0] == "instrumented")
    print(f"\nDelta: {inst[2] - base[2]} of {base[3]} injected failures are legible only when the "
          f"run is instrumented for measurement validity and control delivery.")
    print("Open with:  inspect view --log-dir " + str(logs_dir))
    return 0


if __name__ == "__main__":
    sys.exit(main())
