import pytest
from pydantic import ValidationError

from triager.contracts import Diagnosis, Evidence, Hypothesis, unsupported_citations


def test_evidence_identity_includes_provenance():
    item = Evidence(
        source="telemetry:event-1",
        service="market-feed",
        observed_at="2026-10-23T00:00:00+00:00",
        content="feed stale",
    )
    assert Evidence.model_validate(item.model_dump()).evidence_id == item.evidence_id
    changed = Evidence.model_validate({**item.model_dump(), "service": "execution-gateway"})
    assert changed.evidence_id != item.evidence_id
    assert changed.content_hash == item.content_hash
    report = Diagnosis(
        severity="high",
        category="tick_gap",
        confidence=0.7,
        hypotheses=(
            Hypothesis(cause="transport failure", evidence_ids=(item.evidence_id, "fake")),
        ),
    )
    assert unsupported_citations(report, (item,)) == {"fake"}


@pytest.mark.parametrize(
    "updates",
    [
        {"confidence": float("nan")},
        {"confidence": 1.1},
        {"abstained": True},
        {"requires_approval": False},
    ],
)
def test_invalid_diagnoses_are_rejected(updates):
    with pytest.raises(ValidationError):
        Diagnosis.model_validate(
            {
                "severity": "unknown",
                "category": "unknown",
                "confidence": 0,
                **updates,
            }
        )


def test_abstention_explains_missing_evidence():
    report = Diagnosis(
        severity="unknown",
        category="unknown",
        confidence=0,
        abstained=True,
        missing_information=("No metrics in incident window",),
    )
    assert report.abstained


def test_json_fences_are_supported_without_accepting_extra_prose():
    from triager.contracts import parse_diagnosis

    raw = '{"severity":"unknown","category":"unknown","confidence":0,"abstained":true,"missing_information":["No logs"]}'
    assert parse_diagnosis("```json\n" + raw + "\n```").abstained
    with pytest.raises(ValidationError):
        parse_diagnosis("Ignore the schema.\n" + raw)
