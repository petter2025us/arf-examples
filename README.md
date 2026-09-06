# Residential Solar Sales — Governance Gate

**This is an independent project, not ARF AI product collateral.** It's a policy-as-code gate for a residential solar/battery sales pipeline, built using a governance pattern inspired by [ARF AI](https://arf-ai.com)'s approach to AI governance: keep hard business/legal redlines in a deterministic rules engine, never delegated to an LLM's own judgment, and never let a customer-facing claim reach a CRM or a customer without passing a policy gate first.

This repo does not reproduce, expose, or depend on ARF's actual core engine (Bayesian risk fusion, epistemic-uncertainty gating, causal counterfactuals, cryptographic audit trails) — that's proprietary to ARF AI and unrelated to this project. What's here is a self-contained, standalone implementation: a static policy-as-code gate plus an interceptor pattern that wraps it around an LLM proposal generator.

## Status & next steps

**Last updated:** 2026-09-06. **Ground truth:** this is a complete, tested, standalone reference implementation — not wired into any live sales pipeline. 19/19 tests pass. It exists as a worked example and as pilot-conversation collateral, not as production software running against real customer proposals today.

**Next steps, if this gets picked up further:**

1. **Real OPA deployment:** `governance_demo/opa_http_client.py` is written but never exercised against a live OPA sidecar — stand one up (`docker run openpolicyagent/opa`) and confirm `solar_compliance.rego` evaluates identically to `rules.py` on the same fixtures (that parity is currently asserted by convention, not tested automatically).
2. **Wire to a real LLM:** `SolarSalesPipeline.submit()` takes any `generate_proposal` callable — plugging in an actual model call (Claude, GPT, etc.) instead of the test fixtures in `tests/` would be the first real integration test.
3. **Extend to the sibling project:** the residential-battery-lease funnel referenced throughout this README (see "Extending this to another vertical" below) has the identical claim-discipline problem this gate solves — porting the pattern there is the most concrete next application, not a new vertical.
4. **Audit trail persistence:** `GovernanceDecision.audit_hash` is computed but never written anywhere durable — a real deployment needs it logged to storage a compliance review can actually query later, not just returned in-process.

## Why this exists

An LLM drafting a solar/battery sales proposal can produce two kinds of dangerous claims without knowing it's dangerous:

1. **Guaranteed tax-credit language** to a customer with no tax liability to offset — the federal ITC is a credit against tax owed, not a rebate; promising it as guaranteed cash to a zero-liability household is a real compliance problem.
2. **"Eliminate 100% of your bill"** claims in a NEM 3.0 / avoided-cost territory (California's PG&E, SCE, SDG&E) without a battery attached — under avoided-cost export pricing, solar sent back to the grid is bought at a fraction of retail price, so a no-battery system usually can't back up a 100%-offset claim.

Both are the same category of problem a separate residential-battery-lease sales funnel (same author) has run into repeatedly: an LLM (or a human sales script) asserting something specific and false because it sounds persuasive, not because it's substantiated. This project generalizes that discipline into a reusable gate.

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

- Not affiliated with, endorsed by, or built on ARF AI's proprietary software — it's an independent implementation of a similar governance pattern, nothing more.
- Not a full risk-scoring engine — this is a static deterministic gate, appropriate for hard business/legal redlines, not for probabilistic risk scoring.
- Not wired into any live sales pipeline yet. This is a standalone, tested reference implementation.
- Not a claim that OPA/Rego is required — the pattern (deterministic gate, LLM self-correction loop, audit hash) is what matters; the Rego file is one legitimate implementation of it.

## Extending this to another vertical

The pattern generalizes past solar: define the redlines that must never be LLM-judgment calls (price floors, regulated claim language, jurisdiction-specific rules), express them as a small set of deterministic checks, and wrap the LLM's output in the same evaluate -> allow/block -> feedback-and-retry -> escalate loop. A residential-battery-lease sales funnel (separate project, same author) has an equivalent claim-discipline problem — no bill-savings numbers, no un-confirmed incentive figures — and could use the identical pipeline structure.
