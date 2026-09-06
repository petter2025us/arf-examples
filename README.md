# Residential Solar Sales — Governance Gate (Worked Example)

**This is a demo-safe, advisory worked example — not the ARF core engine.** It shows the pattern ARF recommends for a specific vertical (residential solar/battery sales): keep hard business/legal redlines in a deterministic rules engine, never delegated to an LLM's own judgment, and never let a customer-facing claim reach a CRM or a customer without passing a policy gate first.

ARF's actual core engine — Bayesian risk fusion, epistemic-uncertainty gating (CUDL), causal counterfactuals, cryptographic audit trails — is proprietary and not reproduced here. What's here is the simpler, illustrative layer: a static policy-as-code gate plus the interceptor pattern that wraps it around an LLM proposal generator.

## Why this exists

An LLM drafting a solar/battery sales proposal can produce two kinds of dangerous claims without knowing it's dangerous:

1. **Guaranteed tax-credit language** to a customer with no tax liability to offset — the federal ITC is a credit against tax owed, not a rebate; promising it as guaranteed cash to a zero-liability household is a real compliance problem.
2. **"Eliminate 100% of your bill"** claims in a NEM 3.0 / avoided-cost territory (California's PG&E, SCE, SDG&E) without a battery attached — under avoided-cost export pricing, solar sent back to the grid is bought at a fraction of retail price, so a no-battery system usually can't back up a 100%-offset claim.

Both are the same category of problem this project's ga-battery work has run into repeatedly: an LLM (or a human sales script) asserting something specific and false because it sounds persuasive, not because it's substantiated. This example generalizes that discipline into a reusable gate.

## What's here

```
policy/solar_compliance.rego       Authoritative policy, written for Open Policy Agent (OPA)
governance_demo/rules.py           Pure-Python parity mirror - lets tests run with no OPA binary
governance_demo/pipeline.py        The interceptor: LLM -> gate -> approve/escalate loop
governance_demo/opa_http_client.py Thin HTTP client for a real OPA sidecar deployment
tests/test_rules.py                Rule-by-rule tests (19 cases) against the Python mirror
tests/test_pipeline.py             Pipeline behavior: OPA-present, OPA-unreachable, fail-closed,
                                    self-correction loop, escalation after retries exhausted
```

Run the tests:

```bash
pip install pytest
python -m pytest tests/ -v
```

All 19 tests pass without an OPA binary installed — `rules.py` is the local fallback evaluator, and it's what the pipeline actually calls when no OPA sidecar is configured.

## A real bug this caught, worth keeping in mind

The original draft of the "guarantee language" detector flagged _any_ mention of a dollar sign or "30%" as a guarantee claim. That's wrong: it would have blocked the exact hedged, compliant rewrite the policy exists to force an LLM toward — _"you may qualify for up to a 30% Federal ITC, depending on your personal tax liability"_ legitimately mentions both a dollar-adjacent figure and "30%," and is not a guarantee. Fixed by narrowing the regex to phrases that assert certainty (`guarantee`, `you will receive`, `will get back`) rather than any adjacent number. See `test_hedged_tax_credit_language_is_not_blocked` and `test_unhedged_dollar_guarantee_is_still_blocked` in `tests/test_rules.py` — both cases are now covered so this can't silently regress.

## Fail-safe behavior

`GovernanceEngine` never fails open. If an OPA sidecar is configured but unreachable:

- **Default:** falls back to the local Python evaluator (same rules, logged as a warning)
- **`fail_closed=True`:** blocks the proposal outright rather than trusting a possibly-stale local mirror

Choose `fail_closed=True` for a production deployment where the Rego policy might be updated independently of this package's release cycle — that's the scenario where the local mirror could silently drift out of sync with the authoritative policy.

## What this is not

- Not a replacement for ARF's core risk-scoring engine (Bayesian fusion, CUDL, memory-augmented correction) — this is a static deterministic gate, appropriate for hard business/legal redlines, not for the probabilistic risk-scoring problem ARF's core product solves.
- Not wired into any live sales pipeline. This is a worked example / pilot-conversation artifact.
- Not a claim that OPA/Rego is required — the pattern (deterministic gate, LLM self-correction loop, audit hash) is what matters; the Rego file is one legitimate implementation of it.

## Extending this to another vertical

The pattern generalizes past solar: define the redlines that must never be LLM-judgment calls (price floors, regulated claim language, jurisdiction-specific rules), express them as a small set of deterministic checks, and wrap the LLM's output in the same evaluate -> allow/block -> feedback-and-retry -> escalate loop. The residential-battery-lease claim discipline already documented in `ga-battery/TECHNICAL_OVERVIEW.md` (no bill-savings numbers, no un-confirmed incentive figures) is the same shape of problem and could use the identical pipeline structure.
