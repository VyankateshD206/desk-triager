from types import SimpleNamespace

from triager.presentation import correlate, overview


def row(id, service, at="2026-10-23T12:00:00+00:00", source="receipt-time watchdog", status="open"):
    return dict(id=id, service=service, opened_at=at, status=status, evidence={"source": source})


def test_only_simultaneous_watchdog_gaps_are_correlated():
    rows = [
        row("a", "market-feed"),
        row("b", "execution-gateway", "2026-10-23T12:00:01+00:00"),
        row("c", "portfolio-ledger", "2026-10-23T13:00:00+00:00"),
        row("d", "portfolio-ledger", source="sample"),
        row("e", "portfolio-ledger", status="resolved"),
    ]
    result = correlate(rows, 8)
    assert result[0]["correlation"]["impacted_services"] == ["execution-gateway", "market-feed"]
    assert "unconfirmed" in result[0]["correlation"]["basis"]
    assert all("correlation" not in r for r in result[2:])


def test_summary_preserves_actual_model_and_abstention():
    incident = SimpleNamespace(evidence={"source": "receipt-time watchdog"})
    audit = SimpleNamespace(
        detail={
            "provider": "offline",
            "diagnosis": {"severity": "unknown", "abstained": True, "hypotheses": []},
            "fallback_reason": "TimeoutError",
        }
    )
    result = overview(incident, audit)
    assert result["signal"] == "Telemetry silence"
    assert result["analysis_source"] == "offline"
    assert result["abstained"]
    assert result["summary"] == "Insufficient evidence"
    assert result["fallback_reason"] == "TimeoutError"
    assert overview(incident)["severity"] == "unknown"
