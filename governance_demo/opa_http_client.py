"""Thin HTTP client for an OPA sidecar running solar_compliance.rego.

Not exercised by the test suite (no network calls in tests) - see
tests/test_pipeline.py, which uses a stub implementing the same
`OPAClient` protocol from pipeline.py. Wire this in for a real
deployment:

    from governance_demo.opa_http_client import OPAHttpClient
    from governance_demo.pipeline import GovernanceEngine

    engine = GovernanceEngine(opa_client=OPAHttpClient())
"""

from __future__ import annotations

from typing import Any

import requests


class OPAHttpClient:
    def __init__(
        self,
        base_url: str = "http://localhost:8181/v1/data/solar/compliance",
        timeout_seconds: float = 2.0,
    ) -> None:
        self._url = base_url
        self._timeout = timeout_seconds

    def evaluate(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        response = requests.post(
            self._url,
            json={"input": payload},
            headers={"Content-Type": "application/json"},
            timeout=self._timeout,
        )
        response.raise_for_status()
        return response.json().get("result")
