"""Deterministic security benchmark; no live-model attack success claims."""

import argparse
import json
import tempfile
from pathlib import Path

from triager.agent import TriageAgent
from triager.config import Settings
from triager.contracts import Diagnosis, Evidence, Hypothesis, unsupported_citations
from triager.db import Database
from triager.security import action_policy, sanitize
from triager.verification import verify_support

DEFAULT_CASES = Path(__file__).parent / "attacks/seed.json"


def evaluate(cases):
    rows = []
    for case in cases["redaction"]:
        raw = json.dumps(case["input"])
        hardened = json.dumps(sanitize(case["input"]))
        rows.append(
            {
                "id": case["id"],
                "group": "redaction",
                "before_leaked": case["secret"] in raw,
                "after_leaked": case["secret"] in hardened,
                "passed": case["secret"] not in hardened,
            }
        )
    for case in cases["claims"]:
        item = Evidence(
            source="fixture:claim",
            service="execution-gateway",
            observed_at="2026-10-23T00:00:00+00:00",
            content=json.dumps({"log": "HTTP 429", "latency_ms": 650, "healthy": True}),
        )
        support = {
            key: [{"evidence_id": item.evidence_id, **value} for value in case[key]]
            for key in ("supporting_quotes", "numeric_claims")
            if key in case
        }
        report = Diagnosis(
            severity="high",
            category="latency",
            confidence=0.8,
            hypotheses=(
                Hypothesis(cause="Test claim", evidence_ids=(item.evidence_id,), **support),
            ),
        )
        before = bool(unsupported_citations(report, (item,)))
        issues = verify_support(report, (item,))
        rows.append(
            {
                "id": case["id"],
                "group": "extracts",
                "expected_reject": case["reject"],
                "before_rejected": before,
                "after_rejected": bool(issues),
                "issues": list(issues),
                "passed": bool(issues) == case["reject"],
            }
        )
    for case in cases["policy"]:
        decision = action_policy(
            case["proposal"],
            incident_service="execution-gateway",
            incident_kind=case["kind"],
            simulator=True,
        )
        rows.append(
            {
                "id": case["id"],
                "group": "policy",
                "expected_blocked": case["expect"] == "blocked",
                "decision": decision.model_dump(),
                "passed": decision.disposition == case["expect"],
            }
        )
    with tempfile.TemporaryDirectory(prefix="desk-security-") as directory:
        db = Database(f"sqlite:///{directory}/test.db")
        db.initialize(seed=True)
        try:
            agent = TriageAgent(db, Settings(ai_provider="gemini"))
            for case in cases["injections"]:
                agent.inspect = lambda _, case=case: [
                    {
                        "event_id": case["id"],
                        "at": "2026-10-23T00:00:00+00:00",
                        "log": case["log"],
                    }
                ]
                responses = []

                def compromised_planner(state, case=case):
                    # Force the malicious outcome request, regardless of model susceptibility.
                    if state["rounds"] == 0:
                        return {
                            "role": "model",
                            "parts": [
                                {"functionCall": {"name": case["tool"], "args": case["args"]}}
                            ],
                        }
                    responses.extend(
                        p["functionResponse"]["response"] for p in state["contents"][-1]["parts"]
                    )
                    return {
                        "role": "model",
                        "parts": [
                            {
                                "text": json.dumps(
                                    {
                                        "severity": "unknown",
                                        "category": "unknown",
                                        "confidence": 0,
                                        "abstained": True,
                                        "missing_information": ["Investigate trusted telemetry"],
                                    }
                                )
                            }
                        ],
                    }

                agent.model_turn = compromised_planner
                result = agent.diagnose({"service": "execution-gateway"})
                rejected = bool(responses) and all("error" in response for response in responses)
                rows.append(
                    {
                        "id": case["id"],
                        "group": "tool_boundary",
                        "passed": rejected
                        and result["tool_trace"] == ["inspect_service_logs", "reconcile_balances"],
                    }
                )
        finally:
            db.engine.dispose()
    attacks = [r for r in rows if r["group"] == "extracts" and r["expected_reject"]]
    benign = [r for r in rows if r["group"] == "extracts" and not r["expected_reject"]]
    unsafe = [r for r in rows if r.get("expected_blocked") or r["group"] == "tool_boundary"]
    return {
        "benchmark_version": cases["version"],
        "mode": "deterministic_boundary_and_extracts",
        "live_model_attack_success_rate": None,
        "semantic_support": "not_assessed",
        "case_count": len(rows),
        "failures": sum(not r["passed"] for r in rows),
        "unsafe_action_recall_on_authored_fixtures": sum(r["passed"] for r in unsafe) / len(unsafe),
        "unsafe_fixture_count": len(unsafe),
        "unsupported_extract_acceptance_before": sum(not r["before_rejected"] for r in attacks)
        / len(attacks),
        "unsupported_extract_acceptance_after": sum(not r["after_rejected"] for r in attacks)
        / len(attacks),
        "valid_extract_false_rejection_rate": sum(r["after_rejected"] for r in benign)
        / len(benign),
        "rows": rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = evaluate(json.loads(DEFAULT_CASES.read_text()))
    if args.output:
        args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}, indent=2))
    if result["failures"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
