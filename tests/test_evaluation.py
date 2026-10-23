import json
from pathlib import Path

import pytest

from evals.run import evaluate
from triager.contracts import Diagnosis, Hypothesis

CASES = json.loads((Path(__file__).parents[1] / "evals/cases/seed.json").read_text())


def test_seed_baseline():
    result = evaluate(CASES)
    assert result["case_count"] == 10
    assert result["category_macro_f1"] == 1
    assert result["severity_accuracy"] == 1
    assert result["answer_coverage"] == 0.5


def test_scorer_catches_wrong_labels_and_fabricated_citations():
    def bad_predictor(incident):
        assert not hasattr(incident, "expected")
        return Diagnosis(
            severity="low",
            category="unknown",
            confidence=1,
            hypotheses=(Hypothesis(cause="unsupported", evidence_ids=("invented",)),),
        )

    result = evaluate(CASES, bad_predictor)
    assert result["severity_accuracy"] == 0
    assert result["citation_validity"] == 0
    assert result["category_macro_f1"] < 1


@pytest.mark.parametrize("cases", [[], [CASES[0], CASES[0]]])
def test_reject_invalid_case_sets(cases):
    with pytest.raises(ValueError):
        evaluate(cases)


def test_security_suite_detects_a_disabled_redactor(monkeypatch):
    from evals import security

    cases = json.loads(security.DEFAULT_CASES.read_text())
    result = security.evaluate(cases)
    assert result["failures"] == 0
    monkeypatch.setattr(security, "sanitize", lambda value: value)
    broken = security.evaluate(cases)
    assert broken["failures"] == len(cases["redaction"])
