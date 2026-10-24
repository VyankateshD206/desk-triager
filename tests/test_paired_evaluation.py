"""Hand-authored scoring fixtures only; no simulated model accuracy is published."""

import copy

import pytest

from evals.paired import analyze_paired


def row(case, mode, correct, family=None, split="test"):
    return {
        "id": case,
        "mode": mode,
        "family": family or case,
        "split": split,
        "expected": {
            "category": "latency",
            "severity": "high",
            "abstained": False,
            "root_cause_terms": [["queue"]],
        },
        "prediction": {
            "category": "latency" if correct else "network",
            "severity": "high",
            "abstained": False,
        },
        "root_cause_proxy_hit": correct,
        "verification_issues": [],
        "fallback_reason": None,
        "provider": "gemini",
        "model_calls": [{"provider": "gemini", "model": "test-only-model", "input_tokens": 1}],
        "comparison_settings": {"max_rounds": 4, "model": "test-only-model"},
        "latency_ms": 20 if mode == "graph_retrieval" else 10,
        "cost_estimate_usd": 0.003 if mode == "graph_retrieval" else 0.001,
        "retrieval_executed": mode == "graph_retrieval",
        "retrieved_document_ids": ["runbook:slow-sql"] if mode == "graph_retrieval" else [],
    }


def paired(*rows):
    return {"rows": list(rows)}


def test_paired_improvements_regressions_cost_latency_and_usage():
    data = paired(
        row("a", "graph", False),
        row("a", "graph_retrieval", True),
        row("b", "graph", True),
        row("b", "graph_retrieval", False),
    )
    result = analyze_paired(data, samples=50)
    scope = result["comparisons"]["test"]["all_attempts_including_fallback"]
    assert scope["category_outcomes"] == {"improved": 1, "regressed": 1, "unchanged": 0}
    assert scope["metrics"]["category_accuracy"]["delta_rag_minus_graph"] == 0
    assert scope["median_paired_latency_delta_ms"] == 10
    assert scope["mean_paired_known_cost_delta_usd"] == pytest.approx(0.002)
    assert result["retrieval_usage"]["execution_rate_on_recorded_cases"] == 1
    assert scope["reviewed_label_and_prediction_pairs"] == 0
    assert scope["human_metrics"]["human_root_cause_correct"]["graph"] is None
    assert result == analyze_paired(data, samples=50)


def test_no_credit_for_fallback_or_unrecorded_provider_success():
    a, b = row("a", "graph", False), row("a", "graph_retrieval", True)
    b.update(provider="offline", fallback_reason="TimeoutError", cost_estimate_usd=None)
    result = analyze_paired(paired(a, b), samples=10)
    assert result["comparisons"]["all"]["all_attempts_including_fallback"]["cases"] == 1
    assert result["comparisons"]["all"]["matched_model_successes"]["cases"] == 0
    assert result["provider_failure_or_unverified_pairs"] == 1
    assert (
        result["comparisons"]["all"]["all_attempts_including_fallback"][
            "mean_paired_known_cost_delta_usd"
        ]
        is None
    )
    b.update(provider="gemini", fallback_reason=None, model_calls=[])
    assert analyze_paired(paired(a, b), samples=10)["provider_failure_or_unverified_pairs"] == 1


def test_missing_pairs_and_unknown_usage_are_visible():
    a, b = row("a", "graph", True), row("b", "graph_retrieval", True)
    b.pop("retrieval_executed")
    result = analyze_paired(paired(a, b), samples=10)
    assert result["complete_pairs"] == 0 and result["union_cases"] == 2
    assert result["missing_graph"] == ["b"]
    assert result["missing_graph_retrieval"] == ["a"]
    assert result["retrieval_usage"]["execution_rate_on_recorded_cases"] is None


def test_family_bootstrap_does_not_treat_variants_as_independent_families():
    rows = [
        row(case, mode, True, family="same")
        for case in ("a", "b")
        for mode in ("graph", "graph_retrieval")
    ]
    result = analyze_paired(paired(*rows), samples=30)
    scope = result["comparisons"]["all"]["all_attempts_including_fallback"]
    assert scope["cases"] == 2 and scope["families"] == 1
    assert scope["metrics"]["category_accuracy"]["family_cluster_95pct_interval"] is None
    rows[-2]["family"] = rows[-1]["family"] = "other"
    scope = analyze_paired(paired(*rows), samples=30)["comparisons"]["test"][
        "all_attempts_including_fallback"
    ]
    assert scope["metrics"]["category_accuracy"]["family_cluster_95pct_interval"] == [0, 0]


@pytest.mark.parametrize("field,value", [("split", "dev"), ("family", "other"), ("expected", {})])
def test_mismatched_references_or_splits_cannot_be_compared(field, value):
    a, b = row("a", "graph", True), row("a", "graph_retrieval", True)
    b[field] = value
    with pytest.raises(ValueError, match="disagree"):
        analyze_paired(paired(a, b), samples=10)


def test_duplicate_rows_and_invalid_bootstrap_count_are_rejected():
    a = row("a", "graph", True)
    with pytest.raises(ValueError, match="Duplicate"):
        analyze_paired(paired(a, copy.deepcopy(a)), samples=10)
    with pytest.raises(ValueError, match="positive"):
        analyze_paired(paired(a), samples=0)


def test_human_metrics_require_both_reviews_and_reviewed_reference_labels():
    a, b = row("a", "graph", False), row("a", "graph_retrieval", True)
    reviews = {
        (r["id"], r["mode"]): {
            "status": "approved",
            "root_cause_correct": r is b,
            "evidence_grounded": True,
            "appropriate_abstention": True,
        }
        for r in (a, b)
    }
    data = paired(a, b)
    assert (
        analyze_paired(data, reviews, samples=10)["comparisons"]["test"][
            "all_attempts_including_fallback"
        ]["reviewed_label_and_prediction_pairs"]
        == 0
    )
    a["label_review"] = b["label_review"] = {"status": "approved"}
    scope = analyze_paired(data, reviews, samples=10)["comparisons"]["test"][
        "all_attempts_including_fallback"
    ]
    assert scope["reviewed_label_and_prediction_pairs"] == 1
    assert scope["human_metrics"]["human_root_cause_correct"]["delta_rag_minus_graph"] == 1
    reviews[("a", "graph")]["status"] = "pending"
    assert (
        analyze_paired(data, reviews, samples=10)["comparisons"]["test"][
            "all_attempts_including_fallback"
        ]["reviewed_label_and_prediction_pairs"]
        == 0
    )


def test_no_pairs_means_no_claim_of_rag_effect():
    result = analyze_paired({"rows": []}, samples=10)
    assert result["status"] == "no_paired_rag_results"
    assert (
        result["comparisons"]["all"]["all_attempts_including_fallback"]["metrics"][
            "category_accuracy"
        ]["delta_rag_minus_graph"]
        is None
    )


def test_configuration_or_actual_provider_changes_are_not_a_fair_model_comparison():
    a, b = row("a", "graph", True), row("a", "graph_retrieval", True)
    b["comparison_settings"] = {"max_rounds": 8}
    with pytest.raises(ValueError, match="settings"):
        analyze_paired(paired(a, b), samples=10)
    b["comparison_settings"] = a["comparison_settings"]
    b["model_calls"][0]["model"] = "different-model"
    result = analyze_paired(paired(a, b), samples=10)
    assert result["provider_or_model_mismatch_pairs"] == 1
    assert result["comparisons"]["test"]["matched_model_successes"]["cases"] == 0
