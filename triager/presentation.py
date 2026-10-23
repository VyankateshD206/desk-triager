"""Read-only incident summaries and evidence-based temporal grouping."""

from datetime import datetime


def overview(incident, audit=None):
    detail = audit.detail if audit else {}
    diagnosis = detail.get("diagnosis", {})
    return {
        "severity": diagnosis.get("severity", "unknown"),
        "analysis_source": detail.get("provider"),
        "abstained": diagnosis.get("abstained"),
        "summary": " · ".join(h.get("cause", "") for h in diagnosis.get("hypotheses", [])[:1])
        or ("Insufficient evidence" if diagnosis.get("abstained") else "Investigation pending"),
        "fallback_reason": detail.get("fallback_reason"),
        "signal": "Telemetry silence"
        if incident.evidence.get("source") == "receipt-time watchdog"
        else None,
    }


def correlate(rows, window_seconds):
    # Time proximity is evidence of a common observation gap, not proof of a dependency failure.
    candidates = sorted(
        (
            r
            for r in rows
            if r["status"] != "resolved" and r["evidence"].get("source") == "receipt-time watchdog"
        ),
        key=lambda r: r["opened_at"],
    )
    clusters = []
    for row in candidates:
        if (
            not clusters
            or (
                datetime.fromisoformat(row["opened_at"])
                - datetime.fromisoformat(clusters[-1][0]["opened_at"])
            ).total_seconds()
            > window_seconds
        ):
            clusters.append([])
        clusters[-1].append(row)
    for cluster in clusters:
        services = sorted({r["service"] for r in cluster})
        if len(services) < 2:
            continue
        for row in cluster:
            row["correlation"] = {
                "id": cluster[0]["id"],
                "impacted_services": services,
                "incident_ids": [r["id"] for r in cluster],
                "basis": "Receipt gaps detected together; common cause unconfirmed",
            }
    return rows
