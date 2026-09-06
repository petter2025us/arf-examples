from governance_demo.rules import (
    Claim,
    ClaimType,
    Customer,
    Pricing,
    SolarProposal,
    SystemDesign,
    evaluate,
)


def _proposal(
    price_per_watt: float = 3.76,
    dealer_fee_percent: float = 22.0,
    utility_provider: str = "PGE",
    estimated_tax_liability: float = 0.0,
    has_battery_storage: bool = False,
    claims: tuple[Claim, ...] = (),
) -> SolarProposal:
    return SolarProposal(
        proposal_id="prop_test",
        pricing=Pricing(
            system_size_kw=8.5,
            gross_system_cost=32000.0,
            price_per_watt=price_per_watt,
            dealer_fee_percent=dealer_fee_percent,
        ),
        customer=Customer(
            state="CA",
            utility_provider=utility_provider,
            estimated_tax_liability=estimated_tax_liability,
        ),
        system_design=SystemDesign(
            has_battery_storage=has_battery_storage,
            estimated_annual_production_kwh=12500,
        ),
        generated_claims=claims,
    )


def test_clean_proposal_is_allowed():
    proposal = _proposal(
        estimated_tax_liability=5000.0,
        has_battery_storage=True,
        claims=(
            Claim(
                "c_01",
                ClaimType.TAX_CREDIT,
                "You may qualify for up to a 30% Federal ITC.",
            ),
            Claim(
                "c_02",
                ClaimType.UTILITY_SAVINGS,
                "Offset evening rates with battery storage.",
            ),
        ),
    )
    result = evaluate(proposal)
    assert result.allow is True
    assert result.risk_score == 40  # dealer fee 22% > 18% still flags for review
    assert result.violations == ()


def test_guaranteed_tax_credit_to_zero_liability_customer_is_blocked():
    proposal = _proposal(
        estimated_tax_liability=0.0,
        claims=(
            Claim(
                "c_01", ClaimType.TAX_CREDIT, "You are guaranteed to get $9,600 back."
            ),
        ),
    )
    result = evaluate(proposal)
    assert result.allow is False
    assert result.risk_score == 100
    assert any("TAX_COMPLIANCE_VIOLATION" in v for v in result.violations)


def test_full_bill_elimination_claim_without_battery_under_nem3_is_blocked():
    proposal = _proposal(
        utility_provider="PGE",
        has_battery_storage=False,
        claims=(
            Claim(
                "c_02",
                ClaimType.UTILITY_SAVINGS,
                "Eliminate 100% of your power bill by sending excess solar back to PG&E.",
            ),
        ),
    )
    result = evaluate(proposal)
    assert result.allow is False
    assert any("UTILITY_COMPLIANCE_VIOLATION" in v for v in result.violations)


def test_full_bill_elimination_claim_with_battery_under_nem3_is_allowed():
    proposal = _proposal(
        utility_provider="PGE",
        has_battery_storage=True,
        estimated_tax_liability=5000.0,
        claims=(
            Claim(
                "c_02",
                ClaimType.UTILITY_SAVINGS,
                "Eliminate 100% of your power bill by sending excess solar back to PG&E.",
            ),
        ),
    )
    result = evaluate(proposal)
    assert result.allow is True


def test_non_nem3_utility_allows_full_elimination_claim_without_battery():
    proposal = _proposal(
        utility_provider="GAP",  # Georgia Power - not in the NEM3 set
        has_battery_storage=False,
        estimated_tax_liability=5000.0,
        dealer_fee_percent=10.0,
        claims=(
            Claim(
                "c_02",
                ClaimType.UTILITY_SAVINGS,
                "Eliminate 100% of your power bill.",
            ),
        ),
    )
    result = evaluate(proposal)
    assert result.allow is True
    assert result.risk_score == 0


def test_price_below_floor_is_blocked():
    proposal = _proposal(price_per_watt=2.0, estimated_tax_liability=5000.0)
    result = evaluate(proposal)
    assert result.allow is False
    assert any("PRICE_REDLINE_VIOLATION" in v for v in result.violations)


def test_price_above_ceiling_is_blocked():
    proposal = _proposal(price_per_watt=6.0, estimated_tax_liability=5000.0)
    result = evaluate(proposal)
    assert result.allow is False
    assert any("PREDATORY_PRICING_VIOLATION" in v for v in result.violations)


def test_dealer_fee_above_max_is_blocked():
    proposal = _proposal(dealer_fee_percent=30.0, estimated_tax_liability=5000.0)
    result = evaluate(proposal)
    assert result.allow is False
    assert any("FINANCE_VIOLATION" in v for v in result.violations)


def test_hedged_tax_credit_language_is_not_blocked():
    # "may qualify... depending on your tax liability" is the corrected,
    # compliant phrasing this whole policy exists to force LLMs toward.
    # This is the case that caught the original guarantee-regex bug: an
    # earlier draft flagged any "$" or "30%" and would have blocked its
    # own compliant example.
    proposal = _proposal(
        estimated_tax_liability=0.0,
        dealer_fee_percent=10.0,
        claims=(
            Claim(
                "c_01",
                ClaimType.TAX_CREDIT,
                "You may qualify for up to a 30% Federal ITC depending on your personal tax liability.",
            ),
        ),
    )
    result = evaluate(proposal)
    assert result.allow is True
    assert result.violations == ()


def test_unhedged_dollar_guarantee_is_still_blocked():
    # The narrower regex must not swing so far the other way that it lets
    # a real guarantee through just because it avoids the word "guarantee".
    proposal = _proposal(
        estimated_tax_liability=0.0,
        claims=(
            Claim(
                "c_01",
                ClaimType.TAX_CREDIT,
                "You will receive $9,600 back from the government.",
            ),
        ),
    )
    result = evaluate(proposal)
    assert result.allow is False
    assert any("TAX_COMPLIANCE_VIOLATION" in v for v in result.violations)
