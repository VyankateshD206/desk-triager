"""Conservative symptom baseline shared by offline triage and evaluation."""

from .contracts import Diagnosis, EvidenceQuote, Hypothesis, IncidentInput


def rules_baseline(incident: IncidentInput) -> Diagnosis:
    # Positive symptom phrases only. This is not an LLM or a root-cause benchmark.
    rules = (
        ("websocket stale", "tick_gap", "high"),
        ("http 429; retry-after", "rate_limit", "medium"),
        ("ledger differs", "nav_mismatch", "high"),
        ("order queue backlog", "latency", "high"),
        ("jitter drifting", "ml_degradation", "medium"),
    )
    for item in incident.evidence:
        for phrase, category, severity in rules:
            if phrase in item.content.lower():
                return Diagnosis(
                    severity=severity,
                    category=category,
                    confidence=0.5,
                    hypotheses=(
                        Hypothesis(
                            cause="Observed symptom: " + phrase,
                            evidence_ids=(item.evidence_id,),
                            supporting_quotes=(
                                EvidenceQuote(
                                    evidence_id=item.evidence_id,
                                    quote=item.content[
                                        item.content.lower().index(
                                            phrase
                                        ) : item.content.lower().index(phrase) + len(phrase)
                                    ],
                                ),
                            ),
                        ),
                    ),
                )
    return Diagnosis(
        severity="unknown",
        category="unknown",
        confidence=0,
        abstained=True,
        missing_information=("No recognized current symptom; investigate further",),
    )
