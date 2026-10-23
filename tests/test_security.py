import json

import pytest

from triager.security import action_policy, sanitize


@pytest.mark.parametrize(
    "payload,secret",
    [
        ({"password": "top-secret"}, "top-secret"),
        ('password="a long secret"', "a long secret"),
        ("api_key=synthetic-private-key", "synthetic-private-key"),
        ("Authorization: Bearer synthetic-bearer-token", "synthetic-bearer-token"),
        ("postgresql://user:privatepass@database/desk", "privatepass"),
        ("contact operator@example.com", "operator@example.com"),
        ("token ghp_abcdefghijklmnopqrstuvwxyz123456", "ghp_abcdefghijklmnopqrstuvwxyz123456"),
    ],
)
def test_redacts_common_sensitive_values(payload, secret):
    result = sanitize(payload)
    assert secret not in json.dumps(result)
    assert sanitize(result) == result


def test_configured_key_is_redacted_without_a_label(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "opaque-configured-test-key")
    assert "opaque-configured-test-key" not in sanitize("echo opaque-configured-test-key")


def test_redaction_preserves_diagnostic_numbers():
    assert sanitize({"latency_ms": 650, "account": "desk-primary", "difference": "1250.00"}) == {
        "latency_ms": 650,
        "account": "desk-primary",
        "difference": "1250.00",
    }


@pytest.mark.parametrize(
    "action,kind,disposition",
    [
        ("reconnect_feed", "tick_gap", "requires_approval"),
        ("resync_orders", "latency", "requires_approval"),
        ("enable_backoff", "rate_limit", "requires_approval"),
        ("resync_ledger", "nav_mismatch", "requires_approval"),
        ("inspect_only", "ml_degradation", "read_only"),
        ("remove the table", "latency", "blocked"),
        ("reconnect_feed", "nav_mismatch", "blocked"),
    ],
)
def test_policy_uses_typed_intent_and_trusted_context(action, kind, disposition):
    service = "portfolio-ledger" if kind == "nav_mismatch" else "execution-gateway"
    decision = action_policy(
        {"action": action, "target": service},
        incident_service=service,
        incident_kind=kind,
        simulator=True,
    )
    assert decision.disposition == disposition


@pytest.mark.parametrize(
    "extra",
    [
        {"requires_approval": False},
        {"risk_score": 0},
        {"approved": True},
        {"parameters": {"sql": "DROP TABLE ledger"}},
    ],
)
def test_model_cannot_override_policy(extra):
    decision = action_policy(
        {"action": "resync_orders", "target": "execution-gateway", **extra},
        incident_service="execution-gateway",
        incident_kind="latency",
        simulator=True,
    )
    assert decision.disposition == "blocked"


def test_scope_and_external_execution_are_blocked():
    proposal = {"action": "enable_backoff", "target": "market-feed"}
    assert (
        action_policy(
            proposal,
            incident_service="execution-gateway",
            incident_kind="rate_limit",
            simulator=True,
        ).disposition
        == "blocked"
    )
    assert (
        action_policy(
            proposal, incident_service="market-feed", incident_kind="rate_limit", simulator=False
        ).disposition
        == "blocked"
    )
