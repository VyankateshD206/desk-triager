import json

import pytest

from evals.benchmark import CORPUS, evaluate, summarize
from triager.config import Settings
from triager.limits import RateLimits
from triager.telemetry import estimate_cost


def test_corpus_is_complete_and_label_blind_with_parallel_isolation():
    cases = json.loads(CORPUS.read_text())["cases"]
    assert 30 <= len(cases) <= 50
    assert sum(c["source_url"] is not None for c in cases) == 10
    assert all("expected" not in c["input"] for c in cases)
    result = evaluate(cases[:3], ["rules"], Settings(ai_provider="offline"), workers=3)
    assert result["summaries"]["rules"]["cases"] == 3
    assert result["human_validated_labels"] == 0
    bad = [cases[0], {**cases[1], "family": cases[0]["family"], "split": "test"}]
    with pytest.raises(ValueError, match="crosses"):
        evaluate(bad, ["rules"], Settings())


def test_scorer_penalizes_wrong_answers_and_unsupported_claims():
    row = {
        "expected": {"category": "database", "abstained": False, "root_cause_terms": [["lock"]]},
        "prediction": {"category": "network", "abstained": False, "confidence": 1},
        "severity_correct": False,
        "category_correct": False,
        "root_cause_proxy_hit": False,
        "verification_issues": ["invented evidence"],
        "fallback_reason": None,
        "latency_ms": 10,
        "cost_estimate_usd": None,
        "model_calls": [],
    }
    scores = summarize([row])
    assert scores["category_macro_f1"] == 0
    assert scores["severity_accuracy"] == 0
    assert scores["extract_check_pass_rate"] == 0
    assert scores["confidence_brier_on_answered_categories"] == 1
    assert scores["estimated_total_cost_usd"] is None


def test_unknown_or_incomplete_cost_is_not_free():
    assert estimate_cost([]) == 0
    assert estimate_cost([{"model": "unknown", "input_tokens": 1, "output_tokens": 1}]) is None
    call = {"model": "gemini-3.5-flash-lite", "input_tokens": 1000, "output_tokens": 1000}
    assert estimate_cost([call]) == pytest.approx(0.0028)
    assert estimate_cost([{**call, "prior_failed_attempts": 1}]) is None


def test_rate_limits_are_separate_and_expire(monkeypatch):
    now = [0]
    monkeypatch.setattr("triager.limits.time.monotonic", lambda: now[0])
    limits = RateLimits(per_minute=2, triage_per_minute=1)
    limits.check("a", "/api/incidents/1/triage")
    with pytest.raises(Exception) as caught:
        limits.check("a", "/api/incidents/1/triage")
    assert caught.value.status_code == 429
    limits.check("a", "/api/snapshot")
    limits.check("b", "/api/incidents/1/triage")
    now[0] = 61
    limits.check("a", "/api/incidents/1/triage")


def test_expanded_offline_regression_gate():
    cases = json.loads(CORPUS.read_text())["cases"]
    scores = evaluate(cases, ["rules"], Settings(ai_provider="offline"))["summaries"]["rules"]
    assert scores["severity_accuracy"] >= 0.60
    assert scores["category_macro_f1"] >= 0.29
    assert scores["extract_check_pass_rate"] == 1
    assert scores["provider_error_or_fallback_rate"] == 0
