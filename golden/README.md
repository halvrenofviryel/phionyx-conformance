# Golden fixture — per-chain RGE→AIREP projection (WP-17)

A **per-chain RGE→AIREP projection golden fixture + Python/Node verifier expected-verdict check +
tamper negative.** It is a per-decision / per-chain regression anchor, deliberately **not**:

- not one of the S1–S5 governance scenarios (those ask "does the runtime govern X?"; this asks
  "does the frozen projected chain still verify, and does a tampered one still fail?");
- **not a workflow-global golden** — a workflow-global golden that makes an end-to-end,
  multi-turn / multi-agent PASS claim requires the WP-19 obligation/closure tranche and is
  deliberately deferred to after WP-19.

## Contents

- `chain.jsonl` — a FROZEN 2-record AIREP chain, produced once by the WP-12 RGE→AIREP projection
  (`phionyx_mcp_server.airep_projection.rge_to_airep`, HMAC-signed demo). The golden reference.
- `tampered.jsonl` — the same chain with one hash-domain field mutated and the integrity hash left
  unchanged, so recomputation must fail. The tamper negative.
- `check_golden.py` — runs BOTH AIREP reference verifiers (`verify.py` + `verify.mjs`, from the
  [ai-runtime-evidence-protocol](https://github.com/halvrenofviryel/ai-runtime-evidence-protocol)
  repo, path `spec/airep/v0.1/conformance/`) on both fixtures and asserts the ACTUAL
  verdict against the FROZEN EXPECTED verdict (golden → PASS, tampered → FAIL). Writes a result to
  `actual/golden_rge_airep_projection.result.json`. `run_all.py` invokes it after the
  S-scenario loop and folds its exit into the worst-exit.

The verifiers are an **external dependency**: clone `ai-runtime-evidence-protocol` as a sibling
checkout of this repo, or point `AIREP_CONFORMANCE_DIR` at its `spec/airep/v0.1/conformance/`
directory. When they are absent the check reports `NOT_MEASURED` (exit 2) — never an error,
never a silent pass.

The golden result record is **deliberately not** an S1–S5 `result_record` and is **not** validated
against `conformance/schemas/result_record.schema.json` (that schema is S1–S5-specific). Its shape
is fixed by `check_golden.py`; `run_all.py` folds in its exit code but does not schema-check it.

## Scope of the claim (honest)

Verifiers are run WITHOUT `--pubkey`: this establishes **structural + neutrality + integrity + chain**
conformance of the projected chain, and that tampering is detected — **not** Ed25519 signature
conformance (the projection is HMAC-signed; an Ed25519 round-trip is a separate follow-on). If
`node` is unavailable the Node half is reported `NOT_MEASURED` (the py↔node parity claim is then
honestly unmeasured, never silently passed).

Regenerating the fixtures is a deliberate, reviewable act (they are a frozen reference); re-run the
WP-12 projection to produce an updated chain if the format legitimately changes.
