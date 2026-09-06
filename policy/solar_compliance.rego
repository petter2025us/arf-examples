package solar.compliance

import rego.v1

# Deterministic policy-as-code gate for a residential solar/battery sales
# pipeline. This is a WORKED EXAMPLE for a specific vertical, not the ARF
# core engine. It shows the pattern ARF recommends: keep hard redlines
# (price floors, tax-credit language, utility-tariff claims) in a
# deterministic rules engine, never delegated to an LLM's own judgment.
#
# Reference implementation for offline testing (no OPA binary required)
# lives in ../governance_demo/rules.py and must stay in sync with this
# file. See ../tests/test_rules.py for the parity check between the two.

default allow := false

# --- Redline thresholds (business-configurable, not policy-language-configurable) ---
min_price_per_watt := 2.60
max_price_per_watt := 5.20
max_dealer_fee_percent := 25.0

# NEM 3.0 / net-billing-tariff utilities where a "100% bill elimination"
# claim without battery storage is not substantiable.
nem3_utilities := {"PGE", "SCE", "SDGE"}

violations contains msg if {
	input.pricing.price_per_watt < min_price_per_watt
	msg := sprintf(
		"PRICE_REDLINE_VIOLATION: price/W ($%.2f) is below the floor ($%.2f)",
		[input.pricing.price_per_watt, min_price_per_watt],
	)
}

violations contains msg if {
	input.pricing.price_per_watt > max_price_per_watt
	msg := sprintf(
		"PREDATORY_PRICING_VIOLATION: price/W ($%.2f) exceeds the ceiling ($%.2f)",
		[input.pricing.price_per_watt, max_price_per_watt],
	)
}

violations contains msg if {
	input.pricing.dealer_fee_percent > max_dealer_fee_percent
	msg := sprintf(
		"FINANCE_VIOLATION: dealer fee (%.1f%%) exceeds the maximum (%.1f%%)",
		[input.pricing.dealer_fee_percent, max_dealer_fee_percent],
	)
}

# Block a guaranteed-tax-credit claim made to a customer with no tax
# liability to offset it against.
violations contains msg if {
	some claim in input.generated_claims
	claim.type == "TAX_CREDIT"
	input.customer.estimated_tax_liability <= 0
	contains_guarantee_language(claim.text)
	msg := sprintf(
		"TAX_COMPLIANCE_VIOLATION: guaranteed tax-credit claim to a customer with no tax liability (claim %s)",
		[claim.claim_id],
	)
}

# Block a "100% bill elimination" claim in a NEM 3.0 territory when no
# battery is attached to the system — under avoided-cost export pricing,
# that claim is not substantiable without storage.
violations contains msg if {
	input.customer.utility_provider in nem3_utilities
	input.system_design.has_battery_storage == false
	some claim in input.generated_claims
	claim.type == "UTILITY_SAVINGS"
	promises_full_bill_elimination(claim.text)
	msg := sprintf(
		"UTILITY_COMPLIANCE_VIOLATION: full-bill-elimination claim under NEM 3.0 without battery storage (claim %s)",
		[claim.claim_id],
	)
}

allow if {
	count(violations) == 0
}

# Coarse risk score for triage — NOT the ARF core engine's Bayesian risk
# fusion. This is a simple deterministic heuristic appropriate for a
# lightweight vertical gate: any violation is a hard block (100); a high
# but compliant dealer fee is flagged for review (40); otherwise clean (0).
risk_score := 100 if count(violations) > 0
else := 40 if input.pricing.dealer_fee_percent > 18.0
else := 0

# Deliberately narrow: only phrasing that asserts certainty counts as a
# guarantee claim. A dollar figure or percentage mentioned on its own does
# not - the compliant, hedged rewrite this policy exists to force ("may
# qualify for up to 30%, depending on your tax liability") legitimately
# mentions both and must not be blocked. See ../tests/test_rules.py.
contains_guarantee_language(text) if {
	lower_text := lower(text)
	regex.match(`(guarantee|guaranteed|you will (get|receive)|will (get|receive) back)`, lower_text)
}

promises_full_bill_elimination(text) if {
	lower_text := lower(text)
	regex.match(`(eliminate 100%|zero your bill|\$0 bill|no more power bill)`, lower_text)
}
