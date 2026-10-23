import json

import pytest

from triager.contracts import Diagnosis, Evidence, Hypothesis
from triager.verification import verify_support


def setup_report(**support):
    item = Evidence(
        source="telemetry:event",
        service="execution-gateway",
        observed_at="2026-10-23T00:00:00+00:00",
        content=json.dumps({"log": "HTTP 429", "latency_ms": 650, "healthy": True}),
    )
    report = Diagnosis(
        severity="high",
        category="latency",
        confidence=0.8,
        hypotheses=(
            Hypothesis(cause="Investigate queue", evidence_ids=(item.evidence_id,), **support),
        ),
    )
    return item, report


def test_real_reference_without_extract_support_is_flagged():
    item, report = setup_report()
    assert verify_support(report, (item,)) == ("MissingSupport",)


@pytest.mark.parametrize("quote,valid", [("HTTP 429", True), ("database crashed", False)])
def test_quote_must_appear_verbatim(quote, valid):
    item, _ = setup_report()
    item, report = setup_report(
        supporting_quotes=[{"evidence_id": item.evidence_id, "quote": quote}]
    )
    assert (not verify_support(report, (item,))) == valid


@pytest.mark.parametrize(
    "pointer,value,valid",
    [
        ("/latency_ms", 650, True),
        ("/latency_ms", 651, False),
        ("/missing", 650, False),
        ("/healthy", 1, False),
        ("/log", 429, False),
    ],
)
def test_numeric_claims_match_typed_source_fields(pointer, value, valid):
    item, _ = setup_report()
    item, report = setup_report(
        numeric_claims=[{"evidence_id": item.evidence_id, "pointer": pointer, "value": value}]
    )
    assert (not verify_support(report, (item,))) == valid


def test_copying_an_unrelated_quote_does_not_establish_causality():
    item, _ = setup_report()
    item, report = setup_report(
        supporting_quotes=[{"evidence_id": item.evidence_id, "quote": "HTTP 429"}]
    )
    report = report.model_copy(
        update={
            "hypotheses": (
                report.hypotheses[0].model_copy(
                    update={"cause": "An unrelated database was destroyed"}
                ),
            )
        }
    )
    # Deliberately records the limitation: this verifier checks extracts, not semantics.
    assert verify_support(report, (item,)) == ()
