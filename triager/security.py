"""Evidence redaction and independent simulation-action policy.

Pattern redaction is best effort, not a guarantee that arbitrary PII is detected.
"""

import os
import re
from typing import Literal

from pydantic import ValidationError

from .contracts import Contract
from .models import SERVICES

SENSITIVE_KEY = re.compile(
    r"(?i)^(password|passwd|secret|api[_-]?key|authorization|access[_-]?token|"
    r"refresh[_-]?token|cookie|client[_-]?secret|gemini_api_key|desk_token)$"
)
ASSIGNMENT = re.compile(
    r"""(?ix)(\b(?:password|passwd|secret|api[_-]?key|access[_-]?token|refresh[_-]?token)
    ["']?\s*[:=]\s*)("[^"\n]*"|'[^'\n]*'|[^\s,;]+)"""
)
EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
URL_AUTH = re.compile(r"([a-zA-Z][a-zA-Z0-9+.-]*://)[^\s/@]+:[^\s/@]+@")
TOKEN = re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|AIza[A-Za-z0-9_-]{30,})\b")


def redact_text(text):
    for name in ("GEMINI_API_KEY", "OPENAI_API_KEY", "DESK_TOKEN", "DATABASE_URL"):
        value = os.getenv(name, "")
        if len(value) >= 8:
            text = text.replace(value, "[REDACTED]")
    text = URL_AUTH.sub(r"\1[REDACTED]@", text)
    text = BEARER.sub("Bearer [REDACTED]", text)
    text = ASSIGNMENT.sub(r"\1[REDACTED]", text)
    text = TOKEN.sub("[REDACTED]", text)
    return EMAIL.sub("[REDACTED_EMAIL]", text)


def sanitize(value):
    if isinstance(value, dict):
        return {
            redact_text(str(key)): "[REDACTED]"
            if SENSITIVE_KEY.fullmatch(str(key))
            else sanitize(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [sanitize(item) for item in value]
    return redact_text(value) if isinstance(value, str) else value


class ActionProposal(Contract):
    action: Literal[
        "inspect_only", "reconnect_feed", "enable_backoff", "resync_orders", "resync_ledger"
    ]
    target: Literal["market-feed", "execution-gateway", "portfolio-ledger"]


class PolicyDecision(Contract):
    policy_version: Literal["1"] = "1"
    disposition: Literal["blocked", "read_only", "requires_approval"]
    risk_score: int
    reason: str


# Risk is an ordinal engineering policy score, not a calibrated probability.
RULES = {
    "inspect_only": ("ml_degradation", 0),
    "reconnect_feed": ("tick_gap", 3),
    "enable_backoff": ("rate_limit", 2),
    "resync_orders": ("latency", 5),
    "resync_ledger": ("nav_mismatch", 8),
}


def action_policy(proposal, *, incident_service, incident_kind, simulator):
    """Trusted context comes from SQL/settings, never model text or request risk flags."""

    def blocked(reason):
        return PolicyDecision(disposition="blocked", risk_score=10, reason=reason)

    try:
        action = ActionProposal.model_validate(proposal)
    except ValidationError:
        return blocked("Invalid or unknown typed action")
    if incident_service not in SERVICES or action.target != incident_service:
        return blocked("Target outside incident scope")
    expected_kind, risk = RULES[action.action]
    if incident_kind != expected_kind:
        return blocked("Action does not address incident kind")
    if action.action == "resync_ledger" and action.target != "portfolio-ledger":
        return blocked("Ledger synchronization requires portfolio-ledger")
    if action.action == "inspect_only":
        return PolicyDecision(disposition="read_only", risk_score=risk, reason="Investigation only")
    if not simulator:
        return blocked("No external recovery adapter; simulation only")
    return PolicyDecision(
        disposition="requires_approval",
        risk_score=risk,
        reason="Fixed simulation handler requires authenticated human approval",
    )
