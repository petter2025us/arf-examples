from governance_demo.pipeline import GovernanceEngine, SolarSalesPipeline
from governance_demo.rules import (
    Claim,
    ClaimType,
    Customer,
    Pricing,
    SolarProposal,
    SystemDesign,
)


def _compliant_proposal(proposal_id: str = "p1") -> SolarProposal:
    return SolarProposal(
        proposal_id=proposal_id,
        pricing=Pricing(8.5, 32000.0, 3.76, 10.0),
        customer=Customer("CA", "PGE", 5000.0),
        system_design=SystemDesign(True, 12500),
        generated_claims=(
            Claim(
                "c1",
                ClaimType.TAX_CREDIT,
                "May qualify for up to 30% ITC depending on liability.",
            ),
        ),
    )


def _noncompliant_proposal(proposal_id: str = "p1") -> SolarProposal:
    return SolarProposal(
        proposal_id=proposal_id,
        pricing=Pricing(8.5, 32000.0, 3.76, 22.0),
        customer=Customer("CA", "PGE", 0.0),
        system_design=SystemDesign(False, 12500),
        generated_claims=(
            Claim("c1", ClaimType.TAX_CREDIT, "You are guaranteed to get $9,600 back."),
        ),
    )


class _StubOPAClient:
    """Returns a fixed OPA-shaped response, or raises to simulate an
    unreachable sidecar."""

    def __init__(self, response: dict | None = None, raise_error: bool = False) -> None:
        self._response = response
        self._raise_error = raise_error

    def evaluate(self, payload: dict) -> dict | None:
        if self._raise_error:
            raise ConnectionError("OPA sidecar unreachable (simulated)")
        return self._response


def test_engine_with_no_opa_client_uses_local_evaluator():
    engine = GovernanceEngine(opa_client=None)
    decision = engine.evaluate_proposal(_compliant_proposal())
    assert decision.allowed is True
    assert decision.evaluator == "local_fallback"


def test_engine_prefers_opa_result_when_reachable():
    stub = _StubOPAClient(
        response={"allow": False, "risk_score": 100, "violations": ["FROM_OPA"]}
    )
    engine = GovernanceEngine(opa_client=stub)
    # Even though this proposal is locally compliant, OPA's answer wins.
    decision = engine.evaluate_proposal(_compliant_proposal())
    assert decision.allowed is False
    assert decision.evaluator == "opa"
    assert decision.violations == ("FROM_OPA",)


def test_engine_falls_back_to_local_when_opa_unreachable_and_not_fail_closed():
    stub = _StubOPAClient(raise_error=True)
    engine = GovernanceEngine(opa_client=stub, fail_closed=False)
    decision = engine.evaluate_proposal(_compliant_proposal())
    assert decision.allowed is True
    assert decision.evaluator == "local_fallback"


def test_engine_fails_closed_when_opa_unreachable_and_fail_closed_true():
    stub = _StubOPAClient(raise_error=True)
    engine = GovernanceEngine(opa_client=stub, fail_closed=True)
    decision = engine.evaluate_proposal(_compliant_proposal())
    assert decision.allowed is False
    assert "GOVERNANCE_SYSTEM_UNAVAILABLE" in decision.violations[0]


def test_audit_hash_is_deterministic_for_identical_payloads():
    engine = GovernanceEngine(opa_client=None)
    d1 = engine.evaluate_proposal(_compliant_proposal("same_id"))
    d2 = engine.evaluate_proposal(_compliant_proposal("same_id"))
    assert d1.audit_hash == d2.audit_hash


def test_audit_hash_differs_for_different_payloads():
    engine = GovernanceEngine(opa_client=None)
    d1 = engine.evaluate_proposal(_compliant_proposal("id_a"))
    d2 = engine.evaluate_proposal(_compliant_proposal("id_b"))
    assert d1.audit_hash != d2.audit_hash


def test_pipeline_approves_on_first_compliant_attempt():
    engine = GovernanceEngine(opa_client=None)
    pipeline = SolarSalesPipeline(engine, max_attempts=2)

    outcome = pipeline.submit(lambda feedback: _compliant_proposal())

    assert outcome.status == "approved"
    assert outcome.attempts == 1
    assert outcome.proposal is not None


def test_pipeline_self_corrects_after_one_block_then_approves():
    engine = GovernanceEngine(opa_client=None)
    pipeline = SolarSalesPipeline(engine, max_attempts=2)

    def generate(feedback: list[str]) -> SolarProposal:
        return _noncompliant_proposal() if not feedback else _compliant_proposal()

    outcome = pipeline.submit(generate)

    assert outcome.status == "approved"
    assert outcome.attempts == 2


def test_pipeline_escalates_to_human_after_exhausting_retries():
    engine = GovernanceEngine(opa_client=None)
    pipeline = SolarSalesPipeline(engine, max_attempts=2)

    outcome = pipeline.submit(lambda feedback: _noncompliant_proposal())

    assert outcome.status == "escalated"
    assert outcome.attempts == 2
    assert outcome.proposal is None
    assert outcome.decision.allowed is False
