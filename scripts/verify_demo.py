"""Verify real demo sources from inside the triager container; no LLM charges."""

import json
import os
import time

import httpx

from triager.agent import TriageAgent
from triager.config import Settings
from triager.db import Database
from triager.observability import ObservabilityTools


def eventually(check, label, timeout=60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            result = check()
            if result:
                return result
        except (httpx.HTTPError, KeyError, ValueError):
            pass
        time.sleep(1)
    raise RuntimeError("Timed out waiting for " + label)


def main():
    settings = Settings(ai_provider="offline")
    sources = ObservabilityTools(settings).tools("execution-gateway")
    db = Database(settings.database_url)
    headers = {"X-Desk-Token": settings.token}
    try:
        with httpx.Client(timeout=5) as client:
            demo = settings.demo_service_url

            def inject(kind):
                response = client.post(
                    demo + "/faults",
                    json={"kind": kind},
                    headers={"X-Demo-Token": os.getenv("DEMO_TOKEN", "local-demo-token")},
                )
                response.raise_for_status()

            try:
                for kind in ["slow_query", "memory_pressure", "bad_deploy", "rate_limit"]:
                    inject(kind)
                    started = time.time()

                    def observed():
                        health = client.get(demo + "/health").json()
                        event = health["latest_event"]
                        if not event or health["delivery_errors"]:
                            return False
                        from datetime import datetime

                        if datetime.fromisoformat(event["timestamp"]).timestamp() <= started:
                            return False
                        if kind == "rate_limit" and event["reject_code"] != "429":
                            return False
                        if kind != "rate_limit" and event["fill_latency_ms"] < 350:
                            return False
                        logs = sources["query_logs"]()
                        if event["event_id"] not in json.dumps(logs):
                            return False
                        metrics = sources["get_metrics"]()["result"]
                        values = {r["metric"]["__name__"]: float(r["value"][1]) for r in metrics}
                        expected = {
                            "slow_query": values.get("demo_sql_duration_ms", 0) >= 600,
                            "memory_pressure": values.get("demo_memory_bytes", 0) > 0,
                            "bad_deploy": values.get("demo_error_ratio", 0) == 1,
                            "rate_limit": values.get("demo_error_ratio", 0) == 1,
                        }
                        return event if expected[kind] else False

                    eventually(observed, kind + " logs and metrics")
                    print("Observed real Loki and Prometheus evidence: " + kind, flush=True)
                    if kind == "slow_query":
                        # Real tools and graph, scripted reasoning: this tests integration, not accuracy.
                        agent = TriageAgent(db, settings)
                        agent.settings.ai_provider = "gemini"

                        def planner(state):
                            if state["rounds"] == 0:
                                return {
                                    "role": "model",
                                    "parts": [
                                        {"functionCall": {"name": name, "args": {}}}
                                        for name in sources
                                    ],
                                }
                            refs = [
                                e["evidence_id"]
                                for e in state["evidence_items"]
                                if e["source"] in {"tool:query_logs", "tool:get_metrics"}
                            ]
                            return {
                                "role": "model",
                                "parts": [
                                    {
                                        "text": json.dumps(
                                            {
                                                "severity": "high",
                                                "category": "latency",
                                                "confidence": 0.8,
                                                "hypotheses": [
                                                    {
                                                        "cause": "Controlled SQL delay in demo service",
                                                        "evidence_ids": refs,
                                                        "supporting_quotes": [
                                                            {
                                                                "evidence_id": e["evidence_id"],
                                                                "quote": e["content"][:120],
                                                            }
                                                            for e in state["evidence_items"]
                                                            if e["evidence_id"] in refs
                                                        ],
                                                    }
                                                ],
                                            }
                                        )
                                    }
                                ],
                            }

                        agent.model_turn = planner
                        result = agent.diagnose({"service": "execution-gateway"})
                        if not set(sources).issubset(result["tool_trace"]):
                            raise RuntimeError("Graph did not collect all external tools")
                        if result.get("fallback_reason"):
                            raise RuntimeError("Graph unexpectedly used fallback")
                        print("Graph used all four external read-only tools.", flush=True)
                    if kind == "bad_deploy":
                        diff = sources["get_deploy_diff"]()
                        if diff["deployment"]["version"] != "1.1-bad":
                            raise RuntimeError("Deployment registry did not record bad deploy")
                    expected_kind = "rate_limit" if kind == "rate_limit" else "latency"
                    incident = eventually(
                        lambda: next(
                            (
                                i
                                for i in client.get(
                                    "http://triager:8000/api/snapshot", headers=headers
                                ).json()["incidents"]
                                if i["service"] == "execution-gateway"
                                and i["kind"] == expected_kind
                            ),
                            None,
                        ),
                        "incident ingestion",
                    )
                    response = client.post(
                        "http://triager:8000/api/incidents/" + incident["id"] + "/triage",
                        headers=headers,
                    )
                    response.raise_for_status()
                    if response.json().get("workflow") != "langgraph-v1":
                        raise RuntimeError("API did not use LangGraph")
                print(
                    "Demo integration passed: faults, ingestion, graph, logs, metrics, deployments.",
                    flush=True,
                )
            finally:
                inject("healthy")
    finally:
        db.engine.dispose()


if __name__ == "__main__":
    main()
