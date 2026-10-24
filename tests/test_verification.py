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


@pytest.fixture
def nav_evidence():
    return Evidence(
        source="ledger:snapshot",
        service="portfolio-ledger",
        observed_at="2026-10-24T00:00:00Z",
        content=json.dumps(
            [
                {
                    "account": "desk-primary",
                    "local_nav": "1000000.00",
                    "exchange_nav": "998750.00",
                    "difference": "1250.00",
                }
            ]
        ),
    )


def nav_claim(item, pointer="/0/difference", value=1250, evidence_id=None):
    return Diagnosis(
        severity="high",
        category="nav_mismatch",
        confidence=0.8,
        hypotheses=[
            {
                "cause": "Recorded ledger discrepancy requires investigation",
                "evidence_ids": [item.evidence_id],
                "numeric_claims": [
                    {
                        "evidence_id": evidence_id or item.evidence_id,
                        "pointer": pointer,
                        "value": value,
                    }
                ],
            }
        ],
    )


@pytest.mark.parametrize("source", ["ledger:snapshot", "tool:reconcile_balances"])
@pytest.mark.parametrize(
    "field,raw,value",
    [
        ("local_nav", "1000000.00", 1000000),
        ("exchange_nav", "998750.00", 998750),
        ("difference", "1250.00", 1250),
        ("difference", "-1250.00", -1250),
        ("difference", "0.01", 0.01),
        ("local_nav", "1000000", 1000000),
        ("difference", "0", 0),
    ],
)
def test_ledger_decimal_claims_use_exact_generated_reference(
    nav_evidence, source, field, raw, value
):
    rows = json.loads(nav_evidence.content)
    rows[0][field] = raw
    item = nav_evidence.model_copy(update={"source": source, "content": json.dumps(rows)})
    report = nav_claim(item, "/0/" + field, value)
    assert report.hypotheses[0].numeric_claims[0].evidence_id == item.evidence_id
    assert verify_support(report, (item,)) == ()


def test_wrong_ledger_amount_is_a_mismatch_not_an_invalid_reference(nav_evidence):
    assert verify_support(nav_claim(nav_evidence, value=1251), (nav_evidence,)) == (
        "MissingSupport",
        "NumericMismatch",
    )


@pytest.mark.parametrize(
    "pointer",
    [
        "/0/missing",
        "/difference",
        "/00/difference",
        "/-1/difference",
        "/1/difference",
        "/0/diff~2erence",
    ],
)
def test_ledger_missing_and_malformed_paths_remain_invalid(nav_evidence, pointer):
    assert verify_support(nav_claim(nav_evidence, pointer), (nav_evidence,)) == (
        "InvalidNumericReference",
        "MissingSupport",
    )


@pytest.mark.parametrize(
    "raw",
    [
        "$1250.00",
        "1,250.00",
        "approximately 1250",
        "NaN",
        "Infinity",
        "1e6",
        "",
        " 1250.00 ",
        "HTTP 429",
        "+1250",
        ".01",
        "1250.",
        "１２５０",
        "1250\n",
    ],
)
def test_ledger_decimal_format_is_strict(nav_evidence, raw):
    item = nav_evidence.model_copy(update={"content": json.dumps([{"difference": raw}])})
    assert "InvalidNumericReference" in verify_support(nav_claim(item), (item,))


@pytest.mark.parametrize(
    "source",
    [
        "telemetry:event",
        "tool:get_service_metrics",
        "tool:query_logs",
        "ledger:snapshot:other",
        "tool:reconcile_balances:other",
    ],
)
def test_monetary_strings_from_other_sources_are_rejected(nav_evidence, source):
    item = nav_evidence.model_copy(update={"source": source})
    assert "InvalidNumericReference" in verify_support(nav_claim(item), (item,))


@pytest.mark.parametrize("raw,value", [("650", 650), ("HTTP 429", 429)])
def test_telemetry_strings_do_not_become_numeric(raw, value):
    item, _ = setup_report()
    item = item.model_copy(update={"content": json.dumps({"latency_ms": raw})})
    assert "InvalidNumericReference" in verify_support(
        nav_claim(item, "/latency_ms", value), (item,)
    )


@pytest.mark.parametrize("raw", [True, float("nan"), float("inf"), float("-inf")])
def test_nonfinite_values_and_booleans_remain_invalid_in_ledger(nav_evidence, raw):
    item = nav_evidence.model_copy(update={"content": json.dumps([{"difference": raw}])})
    assert "InvalidNumericReference" in verify_support(nav_claim(item), (item,))


def test_only_monetary_fields_accept_decimal_strings(nav_evidence):
    item = nav_evidence.model_copy(update={"content": json.dumps([{"account": "1250.00"}])})
    assert "InvalidNumericReference" in verify_support(nav_claim(item, "/0/account"), (item,))


def test_unknown_numeric_evidence_id_remains_uncited(nav_evidence):
    assert verify_support(nav_claim(nav_evidence, evidence_id="invented"), (nav_evidence,)) == (
        "MissingSupport",
        "UncitedSupport",
    )
    wrong = nav_claim(nav_evidence).model_copy(
        update={"hypotheses": (Hypothesis(cause="Claim", evidence_ids=("invented",)),)}
    )
    assert verify_support(wrong, (nav_evidence,)) == ("UnsupportedCitation",)


def test_native_numbers_and_pointer_escaping_remain_supported():
    from decimal import Decimal

    from triager.verification import numeric_value

    content = json.dumps({"a/b": {"~value": 650}, "float": 0.01})
    assert numeric_value(content, "/a~1b/~0value") == Decimal(650)
    assert numeric_value(content, "/float") == Decimal("0.01")
    # Decimal-string parsing must preserve digits that a float conversion would lose.
    assert numeric_value(
        '[{"difference":"9007199254740993.01"}]', "/0/difference", "ledger:snapshot"
    ) == Decimal("9007199254740993.01")
    with pytest.raises(ValueError):
        numeric_value('[{"difference":"1250.00"}]', "/0/difference")
    for pointer in ["", "float", "/a~2b/~0value"]:
        with pytest.raises(ValueError):
            numeric_value(content, pointer)


@pytest.mark.parametrize("value", [650, 650.25])
def test_native_json_numbers_still_verify(value):
    item, _ = setup_report()
    item = item.model_copy(update={"content": json.dumps({"latency_ms": value})})
    assert verify_support(nav_claim(item, "/latency_ms", value), (item,)) == ()


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_numeric_claim_schema_still_requires_finite_float(nav_evidence, value):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        nav_claim(nav_evidence, value=value)
