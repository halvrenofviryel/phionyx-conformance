# phionyx-conformance — runtime-governance conformance scenarios

> **Status:** published 2026-08-17 (founder decision). Extracted from a private
> development repository; this repository is the public home of the scenario pack.
> First-party measurements with published method — nothing here has been
> independently reproduced yet (see Honest limits).

Reviewer-runnable scenarios that ask one question of a runtime governance
implementation: *when the answer says the action was allowed, blocked or
recorded, what establishes that the check actually ran, reached its consumer,
and left a record that says what happened?*

Scenario specifications: `scenarios/conformance_scenarios.yaml`
(the five-scenario spec — S1 unauthorized tool action · S2 prohibited path
composition · S3 unwritable evidence sink · S4 policy/state version mismatch ·
S5 non-measurement collapse). All five are implemented.

## Run

```bash
python -m venv .venv && .venv/bin/pip install phionyx-mcp-server==0.2.1 jsonschema
.venv/bin/python run_all.py
```

Each scenario writes a machine-readable record to `actual/` and is validated
against `schemas/result_record.schema.json`.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | all mandatory assertions passed, nothing unmeasured |
| 1 | a measured assertion failed |
| 2 | a required measurement was `NOT_MEASURED` / `INCONCLUSIVE` |
| 3 | harness or environment error (including a record failing its own schema) |

**A non-zero exit here is a result, not a broken harness.** All five scenarios
currently exit 1, because each measures a gap that is really there. The day one
of them exits 0 is the day that gap closed — that is the point of committing
them.

`run_all.py` also folds in the `golden/` RGE→AIREP projection golden check
(see `golden/README.md`). Its AIREP reference verifiers are an external
dependency — clone
[ai-runtime-evidence-protocol](https://github.com/halvrenofviryel/ai-runtime-evidence-protocol)
as a sibling checkout (or set `AIREP_CONFORMANCE_DIR`); absent, that check
reports `NOT_MEASURED` (exit 2), never a silent pass. So the expected worst
exit is **1** with the verifiers present, **2** without them.

## What is measured today

All five drive `phionyx-mcp-server` 0.2.1 in-process (pinned wheel; run in a
`0.2.1` venv). None passes clean — each records a real gap.

| Scenario | Surface | Result |
|---|---|---|
| S1 · unauthorized tool action | `descriptor_hash` comparator | 3/4 — the advisory comparator runs and cannot itself invoke a tool, and it *does* expose a signal distinguishing no-prior-approval from an approved match (`baseline_exists`). But it applies no enforcement: missing authority yields no DENY/STEP_UP, and the distinction lives only in `baseline_exists` while `change_detected` collides, so a consumer gating on that field alone misreads missing authority as unchanged |
| S2 · prohibited path composition | `audit_chain` | 1/3 — the first step records fine, but the second step's governance is identical whether or not the prohibited prior occurred, and both steps persist to the chain. The surface has no path-composition evaluator, so it records the prohibited composition rather than refusing it |
| S3 · unwritable evidence sink | `audit_chain` | 1/3 — the failed write surfaces loudly (no silent success), but it is not bound to a governance decision: no structured defer/deny under a mandatory-evidence profile, and no degraded-mode declaration surface exists |
| S4 · policy/state version mismatch | `verify_chain` (with a signature verifier) | 1/4 — the recorded version is hash-bound and cannot be silently substituted, but the verifier is version-blind: it takes no compatibility rule or artifact set, a chain at `policy-v1` verifies identically to one at `policy-v2`, and an unavailable required artifact can never yield `NOT_MEASURED` |
| S5 · non-measurement collapse | `verify_chain` | 4/5 — an empty chain, an unverified signature and an intact-but-unverified chain all refuse to report `valid`, each naming what was not checked; a genuinely broken chain reports a located failure. The one gap: the failure answer carries no `measurement_status`, so a machine cannot separate the four states by reading one field |

S5's first three assertions are a first-party re-measurement of two findings
this project published against itself (an empty chain returning valid; a
tampered signature returning valid with no verifier passed) — first-party, since
nothing here has yet been reproduced outside the project (see Honest limits).
Measured on 2026-08-06 against the released wheel: both are fixed.

Several scenarios carry an assertion that *passes* (S1-A2/A4, S2-A1, S3-A1,
S4-A4, S5-A1..A4). Those are not filler — each is a property the surface really
holds (a pure comparator cannot invoke; a recorded version is tamper-evident; a
non-measurement is not a pass). Reporting them alongside the failures is what
keeps the record honest in both directions.

## Honest limits

- All five drive the implementation **in-process**, not through a running MCP
  host round-trip. A host-level round-trip would test more, and would let S4's
  artifact resolution and S2's path composition be exercised rather than shown
  absent.
- Every record carries its own `limitations` array. Read it before citing a
  result. Several failures (S1-A3, S2-A2/A3, S4-A1/A2/A3) measure the **absence**
  of an evaluator, not a defect within one — the note says which.
- `independent_rerun.status` is `NOT_REQUESTED` on every record. Nothing here
  has been reproduced by anyone outside this project, and until it has, these
  are first-party measurements with published method — not verified findings.
- Each record's `implementation.commit` is the repository head at fixture-authoring
  time; the released wheel does not attest which commit built it, so the
  release-to-commit binding is itself unverified.
