"""Labeled incident benchmark with label-blind prompt/graph/retrieval comparisons."""

import argparse
import hashlib
import json
import math
import re
import statistics
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from langgraph.checkpoint.sqlite import SqliteSaver

from triager.agent import TriageAgent
from triager.baseline import rules_baseline
from triager.config import Settings
from triager.contracts import (
    Diagnosis,
    Evidence,
    IncidentInput,
    SearchRunbooksArgs,
    parse_diagnosis,
)
from triager.db import Database
from triager.retrieval import Knowledge
from triager.security import redact_text
from triager.telemetry import estimate_cost
from triager.verification import verify_support
from triager.workflow import build_graph

CORPUS = Path(__file__).parent / "cases/incidents.json"
MIGRATION_LOCK = threading.Lock()  # Alembic's environment proxy is process-global.


class FixtureAgent(TriageAgent):
    def __init__(self, settings, inputs, checkpoint_path, knowledge):
        self.settings, self.inputs = settings, inputs
        self.checkpoint_path, self.knowledge = checkpoint_path, knowledge

    def collect_context(self, service):
        items = []
        for raw in self.inputs["evidence"]:
            item = Evidence.model_validate({**raw, "content": redact_text(raw["content"])})
            if item.service != service:
                raise ValueError("Fixture evidence outside service scope")
            items.append(
                {
                    **item.model_dump(mode="json"),
                    "evidence_id": item.evidence_id,
                    "content_hash": item.content_hash,
                }
            )
        return {"evidence": {"logs": [item["content"] for item in items]}, "evidence_items": items}

    def tools(self, service):
        if service != self.inputs["service"]:
            raise ValueError("Fixture scope mismatch")
        result = {name: (lambda data=data: data) for name, data in self.inputs["tools"].items()}
        if self.settings.retrieval_enabled:
            result["search_runbooks"] = lambda query: self.knowledge.search(
                service=service,
                query=SearchRunbooksArgs(query=query).query,
                method="vector",
                limit=3,
            )
        return result


def evidence_models(items):
    return tuple(
        Evidence.model_validate(
            {k: v for k, v in item.items() if k not in {"evidence_id", "content_hash"}}
        )
        for item in items
    )


def comparison_settings(settings, knowledge):
    """Allowlisted experimental controls; the retrieval treatment flag is intentionally omitted."""
    return {
        "provider": settings.ai_provider,
        "gemini_model": settings.gemini_model,
        "openai_model": settings.openai_model,
        "fallback_provider": settings.fallback_provider,
        "max_rounds": settings.agent_max_rounds,
        "max_tool_calls": settings.agent_max_tools,
        "timeout_seconds": settings.agent_timeout_seconds,
        "critic_enabled": settings.critic_enabled,
        "critic_provider": settings.critic_provider,
        "retrieval_embedding": knowledge.version,
        "retrieval_method": "vector",
        "retrieval_limit": 3,
        "knowledge_sha256": hashlib.sha256(
            Path(__file__)
            .resolve()
            .parents[1]
            .joinpath("triager/knowledge/runbooks.json")
            .read_bytes()
        ).hexdigest(),
    }


def run_case(inputs, mode, settings, directory, knowledge):
    # Only inputs enter the predictor. Labels, source URLs, and family IDs stay in the scorer.
    agent = FixtureAgent(
        replace(settings, retrieval_enabled=mode == "graph_retrieval"),
        inputs,
        str(directory / "graph.sqlite3"),
        knowledge,
    )
    started = time.perf_counter()
    collected = agent.collect_context(inputs["service"])
    items = list(collected["evidence_items"])
    metadata = {
        "model_calls": [],
        "fallback_reason": None,
        "tool_trace": [],
        "node_trace": [],
        "tool_events": [],
        "rounds": None,
        "tool_calls": None,
        "provider": "offline" if mode == "rules" else None,
    }
    if mode == "rules":
        report = rules_baseline(
            IncidentInput(service=inputs["service"], evidence=evidence_models(items))
        )
    elif mode == "prompt":
        # Strong context baseline: one prompt gets all fixture tool data, without retrieval.
        for name, data in inputs["tools"].items():
            items.append(
                agent.evidence_item(
                    "tool:" + name, inputs["service"], data, "2026-10-23T00:00:00+00:00"
                )
            )
        state = {
            "service": inputs["service"],
            "deadline": time.time() + settings.agent_timeout_seconds,
            "disable_tools": True,
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "text": json.dumps(
                                {"service": inputs["service"], "untrusted_evidence": items}
                            )
                        }
                    ],
                }
            ],
        }
        try:
            content = agent.model_turn(state)
            metadata["provider"] = content.get("_provider")
            if content.get("_usage"):
                metadata["model_calls"].append(content["_usage"])
            report = parse_diagnosis(
                "\n".join(
                    p["text"] for p in content["parts"] if "text" in p and not p.get("thought")
                )
            )
        except Exception as exc:
            metadata["fallback_reason"] = type(exc).__name__
            report = Diagnosis(
                severity="unknown",
                category="unknown",
                confidence=0,
                abstained=True,
                missing_information=("Provider output unavailable",),
            )
    else:
        with SqliteSaver.from_conn_string(agent.checkpoint_path) as saver:
            graph = build_graph(agent, saver)
            run_id = "benchmark-" + mode + "-" + uuid4().hex
            result = agent.result(
                graph.invoke(
                    {
                        "service": inputs["service"],
                        "run_id": run_id,
                        "deadline": time.time() + settings.agent_timeout_seconds,
                    },
                    agent.run_config(run_id),
                )
            )
        report = Diagnosis.model_validate(result["diagnosis"])
        items = result["evidence_items"]
        metadata = {key: result.get(key) for key in metadata}
    retrieval_events = [
        e for e in (metadata.get("tool_events") or []) if e["tool"] == "search_runbooks"
    ]
    retrieved_documents = []
    for item in items:
        if item["source"] == "tool:search_runbooks":
            documents = json.loads(item["content"])
            if isinstance(documents, list):
                retrieved_documents.extend(
                    d["document_id"]
                    for d in documents
                    if isinstance(d, dict) and isinstance(d.get("document_id"), str)
                )
    cost = estimate_cost(metadata["model_calls"])
    if mode != "rules" and (not metadata["model_calls"] or metadata["fallback_reason"]):
        cost = None
    return (
        report,
        evidence_models(items),
        {
            **metadata,
            "latency_ms": (time.perf_counter() - started) * 1000,
            "cost_estimate_usd": cost,
            "retrieval_requested": len(retrieval_events),
            "retrieval_executed": any(e["status"] == "ok" for e in retrieval_events),
            "retrieved_document_ids": sorted(set(retrieved_documents)),
            "comparison_settings": comparison_settings(settings, knowledge),
        },
    )


def summarize(rows):
    if not rows:
        raise ValueError("No benchmark rows")
    labels = sorted(
        {r["expected"]["category"] for r in rows} | {r["prediction"]["category"] for r in rows}
    )
    f1 = []
    for label in labels:
        tp = sum(r["expected"]["category"] == label == r["prediction"]["category"] for r in rows)
        fp = sum(r["expected"]["category"] != label == r["prediction"]["category"] for r in rows)
        fn = sum(r["expected"]["category"] == label != r["prediction"]["category"] for r in rows)
        f1.append(2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0)
    answered = [r for r in rows if not r["prediction"]["abstained"]]
    causal = [r for r in rows if r["expected"]["root_cause_terms"]]
    costs = [r["cost_estimate_usd"] for r in rows]
    latency = sorted(r["latency_ms"] for r in rows)
    return {
        "cases": len(rows),
        "severity_accuracy": statistics.mean(r["severity_correct"] for r in rows),
        "category_macro_f1": statistics.mean(f1),
        "root_cause_regex_proxy_hit_rate": statistics.mean(
            r["root_cause_proxy_hit"] for r in causal
        )
        if causal
        else None,
        "answer_coverage": len(answered) / len(rows),
        "answered_category_accuracy": statistics.mean(r["category_correct"] for r in answered)
        if answered
        else None,
        "confidence_brier_on_answered_categories": statistics.mean(
            (r["prediction"]["confidence"] - r["category_correct"]) ** 2 for r in answered
        )
        if answered
        else None,
        "extract_check_pass_rate": statistics.mean(not r["verification_issues"] for r in answered)
        if answered
        else None,
        "abstention_accuracy": statistics.mean(
            r["expected"]["abstained"] == r["prediction"]["abstained"] for r in rows
        ),
        "provider_error_or_fallback_rate": statistics.mean(
            bool(r["fallback_reason"]) for r in rows
        ),
        "successful_provider_cases": sum(not r["fallback_reason"] for r in rows),
        "median_latency_ms": statistics.median(latency),
        "p95_latency_ms": latency[max(0, math.ceil(0.95 * len(latency)) - 1)],
        "known_cost_runs": sum(c is not None for c in costs),
        "median_known_run_cost_usd": statistics.median(c for c in costs if c is not None)
        if any(c is not None for c in costs)
        else None,
        "estimated_total_cost_usd": sum(costs) if all(c is not None for c in costs) else None,
        "input_tokens": sum(
            call.get("input_tokens") or 0 for r in rows for call in r["model_calls"]
        ),
        "output_tokens": sum(
            call.get("output_tokens") or 0 for r in rows for call in r["model_calls"]
        ),
    }


def evaluate(cases, modes, settings, *, progress=None, workers=1):
    families = {}
    for case in cases:
        previous = families.setdefault(case["family"], case["split"])
        if previous != case["split"]:
            raise ValueError("Incident family crosses dev/test split")
    if len({c["id"] for c in cases}) != len(cases):
        raise ValueError("Duplicate benchmark case IDs")
    if workers > 1:
        # Each case owns its database/checkpoints; no shared mutable agent state.
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(
                pool.map(lambda case: evaluate([case], modes, settings, progress=progress), cases)
            )
        rows = [row for result in results for row in result["rows"]]
        return {
            **results[0],
            "summaries": {
                mode: summarize([r for r in rows if r["mode"] == mode]) for mode in modes
            },
            "rows": rows,
            "human_validated_labels": sum(
                (c.get("label_review") or {}).get("status") == "approved" for c in cases
            ),
        }
    rows = []
    with tempfile.TemporaryDirectory(prefix="desk-benchmark-") as name:
        directory = Path(name)
        db = Database("sqlite:///" + str(directory / "knowledge.db"))
        with MIGRATION_LOCK:
            db.initialize()
        knowledge = Knowledge(db)
        knowledge.seed()
        try:
            for index, case in enumerate(cases):
                for mode in modes:
                    work = directory / (str(index) + "-" + mode)
                    work.mkdir()
                    report, evidence, metrics = run_case(
                        case["input"], mode, settings, work, knowledge
                    )
                    cause = " ".join(h.cause.lower() for h in report.hypotheses)
                    terms = case["expected"]["root_cause_terms"]
                    row = {
                        "id": case["id"],
                        "family": case["family"],
                        "split": case["split"],
                        "mode": mode,
                        "expected": case["expected"],
                        "prediction": report.model_dump(mode="json"),
                        "annotation_status": case["annotation_status"],
                        "label_review": case.get("label_review"),
                        "evidence": [
                            {
                                **item.model_dump(mode="json"),
                                "evidence_id": item.evidence_id,
                                "content_hash": item.content_hash,
                            }
                            for item in evidence
                        ],
                        "severity_correct": report.severity == case["expected"]["severity"],
                        "category_correct": report.category == case["expected"]["category"],
                        "root_cause_proxy_hit": bool(terms)
                        and all(
                            any(re.search(re.escape(term), cause) for term in group)
                            for group in terms
                        ),
                        "verification_issues": list(verify_support(report, evidence)),
                        **metrics,
                    }
                    rows.append(row)
                    if progress:
                        progress(row)
        finally:
            db.engine.dispose()
    return {
        "summaries": {mode: summarize([r for r in rows if r["mode"] == mode]) for mode in modes},
        "rows": rows,
        "human_validated_labels": sum(
            (c.get("label_review") or {}).get("status") == "approved" for c in cases
        ),
        "root_cause_scoring": "regex proxy; requires judge and manual review for causal accuracy",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=["offline", "gemini", "openai"], default="offline")
    parser.add_argument("--modes", default="rules")
    parser.add_argument("--split", choices=["all", "dev", "test"], default="all")
    parser.add_argument("--limit", type=int)
    parser.add_argument(
        "--label-reviews", type=Path, help="Completed label packet; never sent to the predictor"
    )
    parser.add_argument(
        "--require-reviewed-labels",
        action="store_true",
        help="Refuse selected cases without completed label review",
    )
    parser.add_argument("--workers", type=int, choices=range(1, 5), default=1)
    parser.add_argument(
        "--request-interval",
        type=float,
        default=0,
        help="Minimum seconds between model requests; reduces quota pressure",
    )
    parser.add_argument("--live", action="store_true", help="Explicit opt-in to paid model calls")
    parser.add_argument("--output", type=Path, default=Path("/tmp/desk-benchmark.json"))
    args = parser.parse_args()
    if args.request_interval < 0 or args.request_interval > 30:
        parser.error("Request interval must be 0..30 seconds")
    if args.request_interval:
        from triager import providers

        request = providers.request_once
        pacing_lock, last_request = threading.Lock(), [0.0]

        def paced_request(*request_args, **request_kwargs):
            with pacing_lock:
                time.sleep(max(0, args.request_interval - (time.monotonic() - last_request[0])))
                last_request[0] = time.monotonic()
            return request(*request_args, **request_kwargs)

        providers.request_once = paced_request
    modes = args.modes.split(",")
    if not set(modes) <= {"rules", "prompt", "graph", "graph_retrieval"}:
        parser.error("Unknown benchmark mode")
    if any(mode != "rules" for mode in modes) and (not args.live or args.provider == "offline"):
        parser.error("Model comparisons require --live and a model provider")
    corpus = json.loads(CORPUS.read_text())
    if args.label_reviews:
        from evals.review_packets import apply_label_reviews

        corpus = apply_label_reviews(corpus, json.loads(args.label_reviews.read_text()))
    cases = [c for c in corpus["cases"] if args.split == "all" or c["split"] == args.split]
    if args.limit:
        cases = cases[: args.limit]
    if args.require_reviewed_labels and any(
        (c.get("label_review") or {}).get("status") != "approved" for c in cases
    ):
        parser.error("Selected cases need completed independent label review")
    settings = Settings(
        ai_provider=args.provider, fallback_provider="offline", retrieval_enabled=False
    )
    result = evaluate(
        cases,
        modes,
        settings,
        workers=args.workers,
        progress=lambda row: print(row["id"] + " " + row["mode"] + " complete", flush=True),
    )
    result.update(
        {
            "benchmark_version": corpus["version"],
            "provider": args.provider,
            "model": None
            if args.provider == "offline"
            else settings.openai_model
            if args.provider == "openai"
            else settings.gemini_model,
            "label_review_sha256": hashlib.sha256(args.label_reviews.read_bytes()).hexdigest()
            if args.label_reviews
            else None,
            "run_settings": {
                "max_rounds": settings.agent_max_rounds,
                "max_tool_calls": settings.agent_max_tools,
                "timeout_seconds": settings.agent_timeout_seconds,
                "critic_enabled": settings.critic_enabled,
                "critic_provider": settings.critic_provider,
                "retrieval_embedding": "hash-word12-768-v1",
                "retrieval_method": "vector",
                "retrieval_limit": 3,
                "knowledge_sha256": hashlib.sha256(
                    Path(__file__)
                    .resolve()
                    .parents[1]
                    .joinpath("triager/knowledge/runbooks.json")
                    .read_bytes()
                ).hexdigest(),
            },
            "corpus_sha256": hashlib.sha256(CORPUS.read_bytes()).hexdigest(),
        }
    )
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result["summaries"], indent=2))


if __name__ == "__main__":
    main()
