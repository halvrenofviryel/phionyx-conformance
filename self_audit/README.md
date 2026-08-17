# Self-audit evidence bundle — first two findings

> **Status:** published alongside the conformance scenarios. First-party, not
> independently reproduced.

The Measurement Axioms self-audit
([`measurement-axioms/audit/PHIONYX_MEASUREMENT_AXIOMS_SELF_AUDIT_2026-08-01.md`](https://github.com/halvrenofviryel/measurement-axioms/blob/main/audit/PHIONYX_MEASUREMENT_AXIOMS_SELF_AUDIT_2026-08-01.md)) named
its own gap:

> *"no reproduction command is published, and no per-finding record is given …
> the bundle would make these findings independently reproducible."*

That quotes the self-audit's own stated aspiration. This bundle delivers the two
concrete pieces it said were missing — a reproduction command and a per-finding
record — for the **first two** of the eleven findings (the "absence read as
confirmation" family). It moves them toward reproducible; it does **not** achieve
independent reproduction, which needs an outside reviewer (see below):

| Finding | Buggy in 0.2.0 | Fixed in 0.2.1 |
|---|---|---|
| **SA-1** empty chain returns `valid` | `verify_chain([])` → `{valid: true}` (`audit_chain.py` 417–426) | `{valid: null, NOT_MEASURED, input_absent}` (483–490) |
| **SA-2** verifier-less call passes a tampered signature | `verify_chain(envelopes)` had no verifier and returned `{valid: true}` for a tampered record (417, 474) | `{valid: null, hash_chain_valid: true, signatures_verified: false, NOT_MEASURED}` (557–567) |

Fix commit: `adbbcb33` (2026-08-02) — *"stop four published packages reporting a
pass nobody measured"*. Wheel digests and exact line ranges are in
`findings.json`. Line numbers reference `audit_chain.py` **as shipped in the
pinned wheel** (the artifact the driver runs), not the repository tree, which
differs in absolute line numbers.

## Reproduce

```bash
# the bug, against the buggy release:
python -m venv .before && .before/bin/pip install phionyx-mcp-server==0.2.0
.before/bin/python self_audit/build_bundle.py    # exit 1, both BUG-REPRODUCED

# the fix, against the fixed release:
python -m venv .after && .after/bin/pip install phionyx-mcp-server==0.2.1
.after/bin/python self_audit/build_bundle.py     # exit 0, both FIXED
```

Each run writes a machine-readable record to `actual/self_audit_bundle.<version>.json`
(scratch; regenerated per run). The driver drives the installed wheel directly —
no mock — and exits 0 only when both findings show the fixed behaviour.

The same fix is re-measured, independently of this bundle, by conformance
scenario **S5** (assertions S5-A1 empty-chain and S5-A2 tampered-signature).

## What this bundle is and is not

- **Is:** a one-command reproduction that demonstrates the bug in `0.2.0` and its
  absence in `0.2.1`, pinned to wheel digests, a fix commit, and file+line ranges.
  It moves these two findings from `SUPPORTED_NARRATIVE` toward reproducible.
- **Is not:** independently verified. `verification_status` on every finding is
  *first-party re-measured; not independently reproduced*. Until an outside
  reviewer runs it on a clean clone, these are first-party measurements with a
  published method.
- The released wheels do not attest which commit built them, so the
  release-to-commit binding is itself unverified.
- Only the first two findings are covered here; the other nine in the self-audit
  are not, and their absence from this bundle is not evidence about them.
