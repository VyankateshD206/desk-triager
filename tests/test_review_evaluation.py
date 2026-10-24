"""Review fixtures are synthetic tests, never human judgments or live eval results."""

import copy
import json

import pytest
from pydantic import ValidationError

from evals.benchmark import CORPUS, FixtureAgent, evaluate
from evals.review_packets import (
    apply_label_reviews,
    blind_packet,
    label_packet,
    load_diagnosis_reviews,
)
from triager.config import Settings


@pytest.fixture
def corpus():
    raw = json.loads(CORPUS.read_text())
    return {**raw, "cases": raw["cases"][:2]}


def approve(review):
    review.update(
        status="approved",
        reviewer="Test-only reviewer",
        reviewed_at="2026-10-24T00:00:00Z",
        notes="Test-only assessment",
    )
    if "labels" in review:
        review["root_cause_reference"] = "HIDDEN_REFERENCE_FOR_TEST: insufficient causal evidence"
    else:
        review.update(root_cause_correct=True, evidence_grounded=True, appropriate_abstention=True)


def test_label_packets_start_pending_and_do_not_mutate_corpus(corpus):
    original = copy.deepcopy(corpus)
    packet = label_packet(corpus)
    assert all(e["review"]["status"] == "pending" for e in packet["cases"])
    assert apply_label_reviews(corpus, packet) == original
    approve(packet["cases"][0]["review"])
    packet["cases"][0]["review"]["labels"]["severity"] = "unknown"
    reviewed = apply_label_reviews(corpus, packet)
    assert reviewed["cases"][0]["expected"]["severity"] == "unknown"
    assert reviewed["cases"][0]["label_review"]["status"] == "approved"
    assert "label_review" not in reviewed["cases"][1]
    assert corpus == original
    for a, b in zip(corpus["cases"], reviewed["cases"]):
        assert (a["family"], a["split"], a["input"]) == (b["family"], b["split"], b["input"])


@pytest.mark.parametrize(
    "change", ["corpus", "case", "duplicate", "identity", "timezone", "reference", "extra"]
)
def test_label_review_refuses_stale_or_incomplete_attestation(corpus, change):
    packet = label_packet(corpus)
    review = packet["cases"][0]["review"]
    approve(review)
    if change == "corpus":
        corpus["version"] = "changed"
    elif change == "case":
        packet["cases"][0]["case"]["input"]["service"] = "other"
    elif change == "duplicate":
        packet["cases"][1] = packet["cases"][0]
    elif change == "identity":
        review["reviewer"] = " "
    elif change == "timezone":
        review["reviewed_at"] = "2026-10-24T00:00:00"
    elif change == "reference":
        review["root_cause_reference"] = ""
    else:
        review["trust_me"] = True
    with pytest.raises((ValueError, ValidationError)):
        apply_label_reviews(corpus, packet)


def test_reviewed_labels_are_counted_once_and_never_enter_predictor(corpus, monkeypatch):
    packet = label_packet(corpus)
    approve(packet["cases"][0]["review"])
    reviewed = apply_label_reviews(corpus, packet)
    original = FixtureAgent.collect_context

    def collect(self, service):
        assert "HIDDEN_REFERENCE_FOR_TEST" not in json.dumps(self.inputs)
        assert "expected" not in self.inputs and "label_review" not in self.inputs
        return original(self, service)

    monkeypatch.setattr(FixtureAgent, "collect_context", collect)
    result = evaluate(reviewed["cases"], ["rules"], Settings(ai_provider="offline"), workers=2)
    assert result["human_validated_labels"] == 1
    assert all(r["evidence"] for r in result["rows"])
    assert all(r["provider"] == "offline" and not r["retrieval_executed"] for r in result["rows"])


@pytest.fixture
def report(corpus):
    packet = label_packet(corpus)
    for entry in packet["cases"]:
        approve(entry["review"])
    reviewed = apply_label_reviews(corpus, packet)
    # Only rules execute. Extra mode labels below are test bindings, not measured model results.
    result = evaluate(reviewed["cases"][:1], ["rules"], Settings(ai_provider="offline"))
    first = result["rows"][0]
    result["rows"] = [
        {**first, "mode": "graph"},
        {**copy.deepcopy(first), "mode": "graph_retrieval"},
    ]
    return result


def test_blind_packets_hide_mode_and_bind_scores_to_actual_result(report):
    packet, key = blind_packet(report, seed=42)
    assert all(
        "mode" not in s and "case_id" not in s and "provider" not in s for s in packet["samples"]
    )
    assert load_diagnosis_reviews(report, packet, key) == {}
    approve(packet["samples"][0]["review"])
    scores = load_diagnosis_reviews(report, packet, key)
    binding = key["samples"][packet["samples"][0]["sample_id"]]
    assert scores[(binding["case_id"], binding["mode"])]["root_cause_correct"] is True
    assert len(scores) == 1


@pytest.mark.parametrize(
    "change", ["prediction", "evidence", "report", "duplicate", "key", "missing_score"]
)
def test_blind_review_rejects_tampered_results_and_incomplete_scores(report, change):
    packet, key = blind_packet(report, seed=42)
    sample = packet["samples"][0]
    approve(sample["review"])
    if change == "prediction":
        sample["prediction"]["confidence"] = 0.123
    elif change == "evidence":
        sample["evidence"] = []
    elif change == "report":
        report["rows"][0]["latency_ms"] += 1
    elif change == "duplicate":
        packet["samples"][1] = sample
    elif change == "key":
        key["samples"][sample["sample_id"]]["case_id"] = "missing"
    else:
        sample["review"]["root_cause_correct"] = None
    with pytest.raises((ValueError, ValidationError)):
        load_diagnosis_reviews(report, packet, key)


def test_blind_export_requires_label_review_first(report):
    report["rows"][0]["label_review"] = None
    with pytest.raises(ValueError, match="Complete label review"):
        blind_packet(report)


@pytest.mark.parametrize(
    "arguments,message",
    [
        (["--provider", "gemini", "--modes", "graph,graph_retrieval"], "require --live"),
        (["--require-reviewed-labels"], "need completed independent label review"),
    ],
)
def test_benchmark_cli_refuses_unreviewed_or_unapproved_live_runs(
    monkeypatch, capsys, arguments, message
):
    from evals import benchmark

    def forbidden(*args, **kwargs):
        pytest.fail("Evaluation must not execute before opt-in and label checks")

    monkeypatch.setattr(benchmark, "evaluate", forbidden)
    monkeypatch.setattr("sys.argv", ["benchmark", *arguments])
    with pytest.raises(SystemExit) as error:
        benchmark.main()
    assert error.value.code == 2
    assert message in capsys.readouterr().err
