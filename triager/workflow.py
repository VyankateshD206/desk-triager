"""Bounded investigation graph. All tools are read-only; execution stays in Desk."""

import json
import time
from typing import TypedDict

import httpx
from langgraph.graph import END, START, StateGraph
from opentelemetry import trace
from pydantic import ValidationError

from .contracts import Diagnosis, Evidence, parse_diagnosis
from .critic import critique
from .security import sanitize
from .telemetry import estimate_cost
from .verification import verify_support


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
    verification: dict
    security_version: str
    model_calls: list
    node_trace: list
    disable_tools: bool


def build_graph(agent, checkpointer, *, interrupt_after=None):
    def collect(state):
        collected = agent.collect_context(state["service"])
        items = collected["evidence_items"]
        return {
            "evidence": collected["evidence"],
            "security_version": "1",
            "model_calls": [],
            "node_trace": [],
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
        model_calls = list(state.get("model_calls", []))
        if agent.settings.ai_provider == "offline":
            return fallback(state)
        if state["rounds"] >= agent.settings.agent_max_rounds or time.time() >= state["deadline"]:
            return exhausted("InvestigationBudgetExceeded")
        try:
            content = sanitize(agent.model_turn(state))
            provider = content.pop("_provider", agent.settings.ai_provider)
            usage = content.pop("_usage", None)
            if usage:
                model_calls.append(usage)
            content.pop("_provider_fallback", None)
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
                    "model_calls": model_calls,
                }
            raw = "\n".join(
                part["text"]
                for part in content.get("parts", [])
                if "text" in part and not part.get("thought")
            )
            diagnosis = parse_diagnosis(raw)
            return {
                "contents": contents,
                "pending_calls": [],
                "provider": provider,
                "model_calls": model_calls,
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
                    "model_calls": model_calls,
                }
            # Exception messages may contain credentials or tool data.
            update = {
                **fallback(state),
                "pending_calls": [],
                "fallback_reason": type(exc).__name__,
                "rounds": state["rounds"] + 1,
                "retry_schema": False,
                "model_calls": model_calls,
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
            if (
                name not in available
                or not isinstance(call.get("args", {}), dict)
                or call.get("args")
            ):
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
        issues = verify_support(report, evidence)
        verification = {
            "checks": "citations_quotes_numeric_values",
            "issues": list(issues),
            "semantic_support": "not_assessed",
        }
        if issues:
            return {**fallback(state), "fallback_reason": issues[0], "verification": verification}
        return {"verification": verification}

    def finalize(state):
        diagnosis = Diagnosis.model_validate(state["diagnosis"])
        lines = [f"{diagnosis.severity.upper()} | {diagnosis.category}"]
        lines.extend(h.cause + " [" + ", ".join(h.evidence_ids) + "]" for h in diagnosis.hypotheses)
        if diagnosis.abstained:
            lines.append("Insufficient evidence.")
        lines.extend("Missing: " + item for item in diagnosis.missing_information)
        lines.append(
            "Evidence extracts checked; causal support has not been independently assessed."
        )
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
                "verification",
                "model_calls",
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

    def critic(state):
        if (
            not agent.settings.critic_enabled
            or state["provider"] == "offline"
            or state["diagnosis"]["abstained"]
        ):
            return {}
        try:
            report, usage, verification = critique(agent.settings, state)
            return {
                "diagnosis": report.model_dump(mode="json"),
                "verification": verification,
                "model_calls": state["model_calls"] + ([usage] if usage else []),
            }
        except Exception as exc:
            report = Diagnosis(
                severity="unknown",
                category="unknown",
                confidence=0,
                abstained=True,
                missing_information=("Requested critic was unavailable",),
            )
            return {
                "diagnosis": report.model_dump(mode="json"),
                "verification": {
                    **state["verification"],
                    "semantic_support": "critic_unavailable",
                    "critic_error": type(exc).__name__,
                },
            }

    graph = StateGraph(InvestigationState)

    def observed(name, operation):
        def run(state):
            started = time.perf_counter()
            with trace.get_tracer("desk-triager").start_as_current_span(
                "triage." + name, record_exception=False, set_status_on_exception=False
            ) as span:
                span.set_attribute("incident.service", state["service"])
                span.set_attribute("triage.run_id", state["run_id"])
                try:
                    result = operation(state)
                except Exception as exc:
                    span.set_attribute("error.type", type(exc).__name__)
                    raise
                calls = result.get("model_calls", [])[len(state.get("model_calls", [])) :]
                usage = {
                    "input_tokens": sum(c.get("input_tokens") or 0 for c in calls),
                    "output_tokens": sum(c.get("output_tokens") or 0 for c in calls),
                    "estimated_cost_usd": estimate_cost(calls),
                }
                for key, value in usage.items():
                    if value is not None:
                        span.set_attribute("triage." + key, value)
                result["node_trace"] = state.get("node_trace", []) + [
                    {"node": name, "latency_ms": (time.perf_counter() - started) * 1000, **usage}
                ]
                return result

        return run

    for name, node in [
        ("collect_context", collect),
        ("reason", reason),
        ("tools", tools),
        ("verify", verify),
        ("critic", critic),
        ("final_report", finalize),
    ]:
        graph.add_node(name, observed(name, node))
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
    graph.add_edge("verify", "critic")
    graph.add_edge("critic", "final_report")
    graph.add_edge("final_report", END)
    return graph.compile(checkpointer=checkpointer, interrupt_after=interrupt_after)
