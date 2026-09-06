"""Pure-Python reference implementation of policy/solar_compliance.rego.

This exists so the example's tests run without an OPA binary installed,
and so the pipeline has a local fallback evaluator. It is a **parity
mirror** of the Rego policy, not an independent source of truth — any
rule change must be made in both places, and test_rules.py enforces that
both evaluators agree on the same fixture set.

This is a worked example for a residential solar/battery sales vertical.
It is not the ARF core engine's Bayesian risk-fusion pipeline.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum


class ClaimType(str, Enum):
    TAX_CREDIT = "TAX_CREDIT"
    UTILITY_SAVINGS = "UTILITY_SAVINGS"


@dataclass(frozen=True)
class Claim:
    claim_id: str
    type: ClaimType
    text: str


@dataclass(frozen=True)
class Pricing:
    system_size_kw: float
    gross_system_cost: float
    price_per_watt: float
    dealer_fee_percent: float


@dataclass(frozen=True)
class Customer:
    state: str
    utility_provider: str
    estimated_tax_liability: float
    is_commercial: bool = False


@dataclass(frozen=True)
class SystemDesign:
    has_battery_storage: bool
    estimated_annual_production_kwh: float


@dataclass(frozen=True)
class SolarProposal:
    proposal_id: str
    pricing: Pricing
    customer: Customer
    system_design: SystemDesign
    generated_claims: tuple[Claim, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class PolicyResult:
    allow: bool
    risk_score: int
    violations: tuple[str, ...]


MIN_PRICE_PER_WATT = 2.60
MAX_PRICE_PER_WATT = 5.20
MAX_DEALER_FEE_PERCENT = 25.0
NEM3_UTILITIES = frozenset({"PGE", "SCE", "SDGE"})

# Deliberately narrow: only phrasing that asserts certainty ("guaranteed",
# "you will get back") counts as a guarantee claim. Mentioning a dollar
# figure or a percentage on its own does not - the compliant, hedged
# rewrite this policy is meant to force ("may qualify for up to 30%,
# depending on your tax liability") legitimately mentions both and must
# not be blocked. An earlier draft flagged any "$" or "30%" and would
# have blocked its own compliant example - see test_rules.py.
_GUARANTEE_RE = re.compile(
    r"\b(guarantee|guaranteed|you will (get|receive)|will (get|receive) back)\b",
    re.IGNORECASE,
)
_FULL_ELIMINATION_RE = re.compile(
    r"(eliminate 100%|zero your bill|\$0 bill|no more power bill)", re.IGNORECASE
)


def _contains_guarantee_language(text: str) -> bool:
    return bool(_GUARANTEE_RE.search(text))


def _promises_full_bill_elimination(text: str) -> bool:
    return bool(_FULL_ELIMINATION_RE.search(text))


def evaluate(proposal: SolarProposal) -> PolicyResult:
    """Deterministic rule evaluation — mirrors solar_compliance.rego exactly."""
    violations: list[str] = []

    if proposal.pricing.price_per_watt < MIN_PRICE_PER_WATT:
        violations.append(
            f"PRICE_REDLINE_VIOLATION: price/W (${proposal.pricing.price_per_watt:.2f}) "
            f"is below the floor (${MIN_PRICE_PER_WATT:.2f})"
        )

    if proposal.pricing.price_per_watt > MAX_PRICE_PER_WATT:
        violations.append(
            f"PREDATORY_PRICING_VIOLATION: price/W (${proposal.pricing.price_per_watt:.2f}) "
            f"exceeds the ceiling (${MAX_PRICE_PER_WATT:.2f})"
        )

    if proposal.pricing.dealer_fee_percent > MAX_DEALER_FEE_PERCENT:
        violations.append(
            f"FINANCE_VIOLATION: dealer fee ({proposal.pricing.dealer_fee_percent:.1f}%) "
            f"exceeds the maximum ({MAX_DEALER_FEE_PERCENT:.1f}%)"
        )

    for claim in proposal.generated_claims:
        if (
            claim.type == ClaimType.TAX_CREDIT
            and proposal.customer.estimated_tax_liability <= 0
            and _contains_guarantee_language(claim.text)
        ):
            violations.append(
                "TAX_COMPLIANCE_VIOLATION: guaranteed tax-credit claim to a customer "
                f"with no tax liability (claim {claim.claim_id})"
            )

        if (
            claim.type == ClaimType.UTILITY_SAVINGS
            and proposal.customer.utility_provider in NEM3_UTILITIES
            and not proposal.system_design.has_battery_storage
            and _promises_full_bill_elimination(claim.text)
        ):
            violations.append(
                "UTILITY_COMPLIANCE_VIOLATION: full-bill-elimination claim under NEM 3.0 "
                f"without battery storage (claim {claim.claim_id})"
            )

    if violations:
        risk_score = 100
    elif proposal.pricing.dealer_fee_percent > 18.0:
        risk_score = 40
    else:
        risk_score = 0

    return PolicyResult(
        allow=not violations,
        risk_score=risk_score,
        violations=tuple(violations),
    )
