import json
import time

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver

from triager.agent import TriageAgent
from triager.config import Settings
from triager.db import Database
from triager.workflow import build_graph


@pytest.fixture
def agent(tmp_path):
    settings = Settings(database_url=f"sqlite:///{tmp_path}/test.db", ai_provider="gemini")
    db = Database(settings.database_url)
    db.initialize(seed=True)
    agent = TriageAgent(db, settings)
    agent.inspect = lambda service: [
        {
            "event_id": "event-1",
            "at": "2026-10-23T00:00:00+00:00",
            "log": "WARN simulated exchange HTTP 429; retry-after 5s",
            "score": -0.1,
            "latency_ms": 85,
            "reject_code": "429",
        }
    ]
    yield agent
    db.engine.dispose()


def report(state, citation=None):
    return {
        "role": "model",
        "parts": [
            {
                "text": json.dumps(
                    {
                        "severity": "medium",
                        "category": "rate_limit",
                        "confidence": 0.8,
                        "hypotheses": [
                            {
                                "cause": "Exchange throttling",
                                "evidence_ids": [
                                    citation or state["evidence_items"][0]["evidence_id"]
                                ],
                                "supporting_quotes": [
                                    {
                                        "evidence_id": citation
                                        or state["evidence_items"][0]["evidence_id"],
                                        "quote": "HTTP 429",
                                    }
                                ],
                            }
                        ],
                    }
                )
            }
        ],
    }


def call(name="get_service_metrics", **args):
    return {"role": "model", "parts": [{"functionCall": {"name": name, "args": args}}]}


def test_graph_requests_more_evidence_and_excludes_answer_hints(agent):
    turns = []

    def model(state):
        turns.append(state)
        assert "SECRET ANSWER" not in json.dumps(state)
        return call() if len(turns) == 1 else report(state)

    agent.model_turn = model
    result = agent.diagnose(
        {
            "service": "execution-gateway",
            "diagnosis": "SECRET ANSWER",
            "kind": "SECRET ANSWER",
            "action": "SECRET ANSWER",
        }
    )
    assert result["provider"] == "gemini"
    assert result["rounds"] == 2
    assert result["tool_calls"] == 3
    assert result["tool_trace"][-1] == "get_service_metrics"
    assert len(result["evidence_items"]) == 3


def test_fabricated_citation_is_replaced_by_grounded_fallback(agent):
    agent.model_turn = lambda state: report(state, "invented")
    result = agent.diagnose({"service": "execution-gateway"})
    assert result["provider"] == "offline"
    assert result["fallback_reason"] == "UnsupportedCitation"
    assert "invented" not in result["report"]


def test_repeated_tools_stop_at_round_budget(agent):
    agent.model_turn = lambda state: call()
    result = agent.diagnose({"service": "execution-gateway"})
    assert result["rounds"] == 4
    assert result["tool_trace"].count("get_service_metrics") == 1
    assert result["fallback_reason"] == "InvestigationBudgetExceeded"


def test_tool_budget_blocks_entire_batch(agent):
    agent.settings.agent_max_tools = 2
    agent.model_turn = lambda state: call()
    result = agent.diagnose({"service": "execution-gateway"})
    assert result["fallback_reason"] == "ToolBudgetExceeded"
    assert result["tool_calls"] == 2
    assert "get_service_metrics" not in result["tool_trace"]
    assert result["tool_events"][-1]["status"] == "blocked"
    assert "budget exceeded" in result["tool_events"][-1]["result_summary"]


def test_unknown_tools_and_arguments_never_execute(agent):
    seen = []

    def model(state):
        if state["rounds"] == 0:
            return {
                "role": "model",
                "parts": call("run_shell")["parts"] + call(service="other")["parts"],
            }
        seen.extend(p["functionResponse"]["response"] for p in state["contents"][-1]["parts"])
        return report(state)

    agent.model_turn = model
    result = agent.diagnose({"service": "execution-gateway"})
    assert all("error" in item for item in seen)
    assert result["tool_calls"] == 4
    assert result["tool_trace"] == ["inspect_service_logs", "reconcile_balances"]


def test_restart_resumes_without_recollecting_evidence(agent):
    config = agent.run_config("restart-test")
    with SqliteSaver.from_conn_string(agent.checkpoint_path) as saver:
        graph = build_graph(agent, saver, interrupt_after=["collect_context"])
        graph.invoke(
            {
                "service": "execution-gateway",
                "run_id": "restart-test",
                "deadline": time.time() + 60,
            },
            config,
        )
        assert graph.get_state(config).next == ("reason",)
    restarted = TriageAgent(agent.db, agent.settings)
    restarted.inspect = lambda _: pytest.fail("Must not recollect checkpointed evidence")
    restarted.model_turn = report
    result = restarted.resume("restart-test")
    assert result["provider"] == "gemini"
    assert result["run_id"] == "restart-test"
    assert restarted.resume("restart-test") == result


def test_expired_run_skips_model(agent):
    agent.model_turn = lambda _: pytest.fail("Expired run must not call provider")
    with SqliteSaver.from_conn_string(agent.checkpoint_path) as saver:
        graph = build_graph(agent, saver)
        result = graph.invoke(
            {"service": "execution-gateway", "run_id": "expired", "deadline": time.time() - 1},
            agent.run_config("expired"),
        )["result"]
    assert result["fallback_reason"] == "InvestigationBudgetExceeded"


def test_provider_error_exposes_type_only(agent):
    def model(_):
        raise ValueError("sensitive-secret")

    agent.model_turn = model
    result = agent.diagnose({"service": "execution-gateway"})
    assert result["fallback_reason"] == "ValueError"
    assert "sensitive-secret" not in json.dumps(result)


def test_resume_unknown_run(agent):
    with pytest.raises(KeyError):
        agent.resume("missing")


@pytest.mark.parametrize(
    "updates",
    [{"agent_max_rounds": 0}, {"agent_max_tools": 1}, {"agent_timeout_seconds": float("nan")}],
)
def test_invalid_budgets(updates):
    with pytest.raises(ValueError):
        Settings(**updates).validate()


def test_invalid_schema_has_one_repair_attempt(agent):
    calls = []

    def model(state):
        calls.append(state)
        if len(calls) == 1:
            return {"role": "model", "parts": [{"text": "not JSON"}]}
        return report(state)

    agent.model_turn = model
    result = agent.diagnose({"service": "execution-gateway"})
    assert result["provider"] == "gemini"
    assert result["rounds"] == 2
    assert "fallback_reason" not in result


def test_schema_repair_cannot_loop_forever(agent):
    agent.model_turn = lambda _: {"role": "model", "parts": [{"text": "{}"}]}
    result = agent.diagnose({"service": "execution-gateway"})
    assert result["rounds"] == 2
    assert result["fallback_reason"] == "ValidationError"


def test_expiration_during_schema_repair_terminates(agent, monkeypatch):
    from types import SimpleNamespace

    from triager import workflow

    clock = [time.time()]
    monkeypatch.setattr(
        workflow, "time", SimpleNamespace(time=lambda: clock[0], perf_counter=time.perf_counter)
    )

    def model(state):
        # Simulate the provider using the rest of the deadline on malformed output.
        clock[0] += 1000
        return {"role": "model", "parts": [{"text": "invalid"}]}

    agent.model_turn = model
    result = agent.diagnose({"service": "execution-gateway"})
    assert result["diagnosis"]["abstained"]
    assert result["fallback_reason"] == "InvestigationBudgetExceeded"


def test_legacy_checkpoint_requires_fresh_diagnosis(agent):
    from langgraph.graph import END, START, StateGraph

    from triager.workflow import InvestigationState

    with SqliteSaver.from_conn_string(agent.checkpoint_path) as saver:
        builder = StateGraph(InvestigationState)
        builder.add_edge(START, END)
        graph = builder.compile(checkpointer=saver)
        graph.invoke(
            {"service": "execution-gateway", "run_id": "legacy"}, agent.run_config("legacy")
        )
    with pytest.raises(ValueError, match="predates security"):
        agent.resume("legacy")


def test_critic_can_abstain_on_structurally_valid_causal_claim(agent, monkeypatch):
    from triager.contracts import Diagnosis

    agent.settings.critic_enabled = True
    agent.model_turn = report

    def reject(settings, state):
        return (
            Diagnosis(
                severity="unknown",
                category="unknown",
                confidence=0,
                abstained=True,
                missing_information=("Causality unsupported",),
            ),
            {"model": "gemini-3.5-flash-lite", "input_tokens": 10, "output_tokens": 5},
            {**state["verification"], "semantic_support": "model_critic_assessed"},
        )

    monkeypatch.setattr("triager.workflow.critique", reject)
    result = agent.diagnose({"service": "execution-gateway"})
    assert result["diagnosis"]["abstained"]
    assert result["verification"]["semantic_support"] == "model_critic_assessed"
    assert any(n["node"] == "critic" and n["input_tokens"] == 10 for n in result["node_trace"])


def test_failed_requested_critic_abstains_and_cost_is_unknown(agent, monkeypatch):
    agent.settings.critic_enabled = True
    agent.model_turn = report

    def fail(*args):
        raise ValueError("invalid verdict")

    monkeypatch.setattr("triager.workflow.critique", fail)
    result = agent.diagnose({"service": "execution-gateway"})
    assert result["diagnosis"]["abstained"]
    assert result["estimated_cost_usd"] is None


def test_tool_events_capture_scope_results_and_rejected_arguments(agent):
    def model(state):
        if state["rounds"] == 0:
            return call("get_service_metrics", api_key="private-tool-secret")
        if state["rounds"] == 1:
            return call("get_service_metrics")
        return report(state)

    agent.model_turn = model
    result = agent.diagnose({"service": "execution-gateway"})
    events = result["tool_events"]
    assert [e["tool"] for e in events[:2]] == ["inspect_service_logs", "reconcile_balances"]
    assert events[2]["status"] == "blocked"
    assert events[2]["arguments"]["api_key"] == "[REDACTED]"
    assert events[3]["status"] == "ok"
    assert events[3]["scope"] == {"service": "execution-gateway"}
    assert events[3]["latency_ms"] >= 0
    assert events[3]["evidence_ids"]
    assert "private-tool-secret" not in json.dumps(events)


@pytest.mark.parametrize(
    "pointer,value,issue",
    [
        ("/0/difference", 1250, None),
        ("/0/difference", 1251, "NumericMismatch"),
        ("/0/missing", 1250, "InvalidNumericReference"),
    ],
)
def test_gemini_nav_numeric_evidence_through_real_graph(agent, pointer, value, issue):
    from decimal import Decimal

    from sqlalchemy import func, select

    from triager.contracts import Diagnosis, Evidence
    from triager.models import Balance, RecoveryJob, RecoveryProposal
    from triager.verification import verify_support

    agent.settings.critic_enabled = False
    agent.inspect = lambda service: []
    with agent.db.Session.begin() as db:
        db.get(Balance, "desk-primary").exchange_nav = Decimal("998750.00")
    captured = {}

    def model(state):
        item = next(e for e in state["evidence_items"] if e["source"] == "ledger:snapshot")
        captured.update(item)
        return {
            "role": "model",
            "parts": [
                {
                    "text": json.dumps(
                        {
                            "severity": "high",
                            "category": "nav_mismatch",
                            "confidence": 0.8,
                            "hypotheses": [
                                {
                                    "cause": "Ledger and exchange NAV differ; cause remains unconfirmed",
                                    "evidence_ids": [item["evidence_id"]],
                                    "numeric_claims": [
                                        {
                                            "evidence_id": item["evidence_id"],
                                            "pointer": pointer,
                                            "value": value,
                                        }
                                    ],
                                }
                            ],
                        }
                    )
                }
            ],
        }

    # Bypass every provider adapter: this is a deterministic mock, never a live request.
    agent.model_turn = model
    result = agent.diagnose({"service": "portfolio-ledger"})
    stored = next(e for e in result["evidence_items"] if e["source"] == "ledger:snapshot")
    assert stored == captured
    item = Evidence.model_validate(
        {k: v for k, v in stored.items() if k not in {"evidence_id", "content_hash"}}
    )
    assert stored["evidence_id"] == item.evidence_id
    assert stored["content_hash"] == item.content_hash
    if issue is None:
        assert result["provider"] == "gemini"
        assert result["diagnosis"]["category"] == "nav_mismatch"
        assert result["diagnosis"]["severity"] == "high"
        assert "fallback_reason" not in result
        assert result["verification"]["issues"] == []
        assert verify_support(Diagnosis.model_validate(result["diagnosis"]), (item,)) == ()
    else:
        assert result["provider"] == "offline"
        assert issue in result["verification"]["issues"]
        assert result["fallback_reason"] == result["verification"]["issues"][0]
    with agent.db.Session() as db:
        assert db.scalar(select(func.count()).select_from(RecoveryJob)) == 0
        assert db.scalar(select(func.count()).select_from(RecoveryProposal)) == 0
