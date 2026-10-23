"""Bounded investigation graph. All tools are read-only; execution stays in Desk."""

import json
import time
from typing import TypedDict

import httpx
from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from .contracts import Diagnosis, Evidence, unsupported_citations


class InvestigationState(TypedDict, total=False):
    service: str
    run_id: str
    deadline: float
    rounds: int
    schema_retries: int
    retry_schema: bool
    tool_calls: int
    contents: list
    evidence: dict
    evidence_items: list
    tool_trace: list
    pending_calls: list
    diagnosis: dict
    provider: str
    fallback_reason: str
    fallback_http_status: int
    result: dict


def build_graph(agent, checkpointer, *, interrupt_after=None):
    def collect(state):
        logs = agent.inspect(state["service"])
        balances = agent.db.reconcile()
        items = [
            agent.evidence_item("telemetry:" + row["event_id"], state["service"], row, row["at"])
            for row in logs
        ]
        items.append(agent.evidence_item("ledger:snapshot", state["service"], balances))
        return {
            "evidence": {"logs": logs, "reconciliation": balances},
            "evidence_items": items,
            "rounds": 0,
            "schema_retries": 0,
            "retry_schema": False,
            "tool_calls": 2,
            "tool_trace": ["inspect_service_logs", "reconcile_balances"],
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "text": json.dumps(
                                {"service": state["service"], "untrusted_evidence": items}
                            )
                        }
                    ],
                }
            ],
        }

    def fallback(state):
        diagnosis = agent.offline_diagnosis(state)
        return {"diagnosis": diagnosis.model_dump(mode="json"), "provider": "offline"}

    def exhausted(reason):
        diagnosis = Diagnosis(
            severity="unknown",
            category="unknown",
            confidence=0,
            abstained=True,
            missing_information=(reason,),
        )
        return {
            "diagnosis": diagnosis.model_dump(mode="json"),
            "provider": "offline",
            "fallback_reason": reason,
            "pending_calls": [],
            "retry_schema": False,
        }

    def reason(state):
        if agent.settings.ai_provider == "offline":
            return fallback(state)
        if state["rounds"] >= agent.settings.agent_max_rounds or time.time() >= state["deadline"]:
            return exhausted("InvestigationBudgetExceeded")
        try:
            content = agent.model_turn(state)
            contents = state["contents"] + [content]
            calls = [
                part["functionCall"] for part in content.get("parts", []) if "functionCall" in part
            ]
            if calls:
                return {
                    "contents": contents,
                    "pending_calls": calls,
                    "rounds": state["rounds"] + 1,
                    "retry_schema": False,
                }
            raw = "\n".join(
                part["text"]
                for part in content.get("parts", [])
                if "text" in part and not part.get("thought")
            )
            diagnosis = Diagnosis.model_validate_json(raw)
            return {
                "contents": contents,
                "pending_calls": [],
                "provider": "gemini",
                "rounds": state["rounds"] + 1,
                "diagnosis": diagnosis.model_dump(mode="json"),
                "retry_schema": False,
            }
        except Exception as exc:
            if (
                isinstance(exc, ValidationError)
                and state["schema_retries"] < 1
                and state["rounds"] + 1 < agent.settings.agent_max_rounds
            ):
                return {
                    "contents": state["contents"]
                    + [
                        {
                            "role": "user",
                            "parts": [
                                {
                                    "text": "The last response failed schema validation. Return only a valid Diagnosis "
                                    "JSON object with real evidence IDs, or abstain with missing_information."
                                }
                            ],
                        }
                    ],
                    "rounds": state["rounds"] + 1,
                    "schema_retries": state["schema_retries"] + 1,
                    "retry_schema": True,
                    "pending_calls": [],
                }
            # Exception messages may contain credentials or tool data.
            update = {
                **fallback(state),
                "pending_calls": [],
                "fallback_reason": type(exc).__name__,
                "rounds": state["rounds"] + 1,
                "retry_schema": False,
            }
            if isinstance(exc, httpx.HTTPStatusError):
                update["fallback_http_status"] = exc.response.status_code
            return update

    def tools(state):
        calls = state["pending_calls"]
        if len(calls) + state["tool_calls"] > agent.settings.agent_max_tools:
            return exhausted("ToolBudgetExceeded")
        parts, items, trace = [], list(state["evidence_items"]), list(state["tool_trace"])
        available = agent.tools(state["service"])
        for call in calls:
            name = call.get("name", "")
            if name not in available or call.get("args"):
                response = {"error": "Tool or arguments not allowed"}
            elif name in trace:
                response = {"error": "Already collected; use existing evidence"}
            else:
                try:
                    item = agent.evidence_item("tool:" + name, state["service"], available[name]())
                    items.append(item)
                    trace.append(name)
                    response = {"result": item}
                except Exception as exc:
                    response = {"error": type(exc).__name__}
            part = {"name": name, "response": response}
            if "id" in call:
                part["id"] = call["id"]
            parts.append({"functionResponse": part})
        return {
            "contents": state["contents"] + [{"role": "user", "parts": parts}],
            "evidence_items": items,
            "tool_trace": trace,
            "tool_calls": state["tool_calls"] + len(calls),
            "pending_calls": [],
        }

    def verify(state):
        report = Diagnosis.model_validate(state["diagnosis"])
        evidence = tuple(
            Evidence.model_validate(
                {k: v for k, v in item.items() if k not in {"evidence_id", "content_hash"}}
            )
            for item in state["evidence_items"]
        )
        invalid = unsupported_citations(report, evidence)
        if invalid:
            return {**fallback(state), "fallback_reason": "UnsupportedCitation"}
        return {}

    def finalize(state):
        diagnosis = Diagnosis.model_validate(state["diagnosis"])
        lines = [f"{diagnosis.severity.upper()} | {diagnosis.category}"]
        lines.extend(h.cause + " [" + ", ".join(h.evidence_ids) + "]" for h in diagnosis.hypotheses)
        if diagnosis.abstained:
            lines.append("Insufficient evidence.")
        lines.extend("Missing: " + item for item in diagnosis.missing_information)
        lines.append("Recovery requires separate approval and fresh telemetry verification.")
        result = {
            key: state[key]
            for key in (
                "provider",
                "evidence",
                "evidence_items",
                "tool_trace",
                "run_id",
                "diagnosis",
            )
        }
        result.update(
            {
                "report": "\n".join(lines),
                "workflow": "langgraph-v1",
                "rounds": state["rounds"],
                "tool_calls": state["tool_calls"],
            }
        )
        for key in ("fallback_reason", "fallback_http_status"):
            if state.get(key):
                result[key] = state[key]
        return {"result": result}

    graph = StateGraph(InvestigationState)
    for name, node in [
        ("collect_context", collect),
        ("reason", reason),
        ("tools", tools),
        ("verify", verify),
        ("final_report", finalize),
    ]:
        graph.add_node(name, node)
    graph.add_edge(START, "collect_context")
    graph.add_edge("collect_context", "reason")
    graph.add_conditional_edges(
        "reason",
        lambda state: (
            "reason"
            if state.get("retry_schema")
            else ("tools" if state.get("pending_calls") else "verify")
        ),
        {"reason": "reason", "tools": "tools", "verify": "verify"},
    )
    graph.add_conditional_edges(
        "tools",
        lambda state: "verify" if state.get("fallback_reason") else "reason",
        {"verify": "verify", "reason": "reason"},
    )
    graph.add_edge("verify", "final_report")
    graph.add_edge("final_report", END)
    return graph.compile(checkpointer=checkpointer, interrupt_after=interrupt_after)
