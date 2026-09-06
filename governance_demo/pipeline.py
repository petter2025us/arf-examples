"""Governance interceptor for a residential solar sales pipeline.

Sits between an LLM that drafts a customer-facing proposal and the CRM
that would dispatch it. Every proposal is evaluated against a
deterministic policy (solar_compliance.rego, mirrored in rules.py)
before it can reach a customer.

This is a worked example of the pattern ARF recommends for a specific
vertical (residential solar/battery sales) — it is not the ARF core
engine. The core engine's Bayesian risk fusion, epistemic-uncertainty
gating, and cryptographic audit trail are proprietary and not
reproduced here.

Fail-safe behavior: if the OPA sidecar is unreachable, this does NOT
fail open. It falls back to the local pure-Python evaluator (rules.py),
which enforces the same rules. If a caller wants strict fail-closed
behavior even when OPA is configured but unreachable (e.g. because the
local evaluator has drifted out of sync with a newer Rego policy in
production), pass fail_closed=True.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from governance_demo.rules import PolicyResult, SolarProposal, evaluate

logger = logging.getLogger("governance_demo")


class OPAClient(Protocol):
    """Anything that can evaluate a proposal payload against OPA and
    return the raw `result` object OPA's HTTP API returns."""

    def evaluate(self, payload: dict[str, Any]) -> dict[str, Any] | None: ...


@dataclass(frozen=True)
class GovernanceDecision:
    allowed: bool
    risk_score: int
    violations: tuple[str, ...]
    audit_hash: str
    evaluator: str  # "opa" | "local_fallback"


def _proposal_to_dict(proposal: SolarProposal) -> dict[str, Any]:
    return {
        "proposal_id": proposal.proposal_id,
        "pricing": {
            "system_size_kw": proposal.pricing.system_size_kw,
            "gross_system_cost": proposal.pricing.gross_system_cost,
            "price_per_watt": proposal.pricing.price_per_watt,
            "dealer_fee_percent": proposal.pricing.dealer_fee_percent,
        },
        "customer": {
            "state": proposal.customer.state,
            "utility_provider": proposal.customer.utility_provider,
            "estimated_tax_liability": proposal.customer.estimated_tax_liability,
            "is_commercial": proposal.customer.is_commercial,
        },
        "system_design": {
            "has_battery_storage": proposal.system_design.has_battery_storage,
            "estimated_annual_production_kwh": proposal.system_design.estimated_annual_production_kwh,
        },
        "generated_claims": [
            {"claim_id": c.claim_id, "type": c.type.value, "text": c.text}
            for c in proposal.generated_claims
        ],
    }


def _audit_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class GovernanceEngine:
    """Evaluates a SolarProposal, preferring an OPA sidecar and falling
    back to the local rules.py evaluator when OPA is unavailable."""

    def __init__(
        self, opa_client: OPAClient | None = None, fail_closed: bool = False
    ) -> None:
        self._opa_client = opa_client
        self._fail_closed = fail_closed

    def evaluate_proposal(self, proposal: SolarProposal) -> GovernanceDecision:
        payload = _proposal_to_dict(proposal)
        audit_hash = _audit_hash(payload)

        if self._opa_client is not None:
            try:
                opa_result = self._opa_client.evaluate(payload)
            except Exception as exc:  # noqa: BLE001 - any transport failure
                logger.error("OPA sidecar unreachable: %s", exc)
                opa_result = None

            if opa_result is not None:
                return GovernanceDecision(
                    allowed=bool(opa_result.get("allow", False)),
                    risk_score=int(opa_result.get("risk_score", 100)),
                    violations=tuple(opa_result.get("violations", [])),
                    audit_hash=audit_hash,
                    evaluator="opa",
                )

            if self._fail_closed:
                return GovernanceDecision(
                    allowed=False,
                    risk_score=100,
                    violations=(
                        "GOVERNANCE_SYSTEM_UNAVAILABLE: OPA unreachable, fail_closed=True",
                    ),
                    audit_hash=audit_hash,
                    evaluator="opa",
                )

            logger.warning(
                "OPA unreachable; falling back to local evaluator for this decision."
            )

        result: PolicyResult = evaluate(proposal)
        return GovernanceDecision(
            allowed=result.allow,
            risk_score=result.risk_score,
            violations=result.violations,
            audit_hash=audit_hash,
            evaluator="local_fallback",
        )


class SolarSalesPipeline:
    """Wraps an LLM proposal generator with the governance gate and a
    bounded self-correction loop: on a block, the violation list is
    handed back to the caller so the LLM can be re-prompted."""

    def __init__(self, governance: GovernanceEngine, max_attempts: int = 2) -> None:
        self._governance = governance
        self._max_attempts = max_attempts

    def submit(
        self, generate_proposal: Callable[[list[str]], SolarProposal]
    ) -> "PipelineOutcome":
        feedback: list[str] = []
        last_decision: GovernanceDecision | None = None

        for attempt in range(1, self._max_attempts + 1):
            proposal = generate_proposal(feedback)
            decision = self._governance.evaluate_proposal(proposal)
            last_decision = decision

            if decision.allowed:
                return PipelineOutcome(
                    status="approved",
                    attempts=attempt,
                    decision=decision,
                    proposal=proposal,
                )

            logger.warning(
                "Proposal %s blocked on attempt %d (risk=%d): %s",
                proposal.proposal_id,
                attempt,
                decision.risk_score,
                "; ".join(decision.violations),
            )
            feedback = list(decision.violations)

        assert last_decision is not None
        return PipelineOutcome(
            status="escalated",
            attempts=self._max_attempts,
            decision=last_decision,
            proposal=None,
        )


@dataclass(frozen=True)
class PipelineOutcome:
    status: str  # "approved" | "escalated"
    attempts: int
    decision: GovernanceDecision
    proposal: SolarProposal | None
