"""Labeled incident benchmark with label-blind prompt/graph/retrieval comparisons."""

import argparse
import hashlib
import json
import re
import statistics
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver

from triager.agent import TriageAgent
from triager.baseline import rules_baseline
from triager.config import Settings
from triager.contracts import Diagnosis, Evidence, IncidentInput, parse_diagnosis
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
            result["search_runbooks"] = lambda: self.knowledge.search(
                service, "\n".join(item["content"] for item in self.inputs["evidence"])
            )
        return result


def evidence_models(items):
    return tuple(
        Evidence.model_validate(
            {k: v for k, v in item.items() if k not in {"evidence_id", "content_hash"}}
        )
        for item in items
    )


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
    metadata = {"model_calls": [], "fallback_reason": None, "tool_trace": [], "node_trace": []}
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
            run_id = "benchmark-" + mode
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
        "p95_latency_ms": latency[max(0, int(0.95 * len(latency)) - 1)],
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
        "human_validated_labels": 0,
        "root_cause_scoring": "regex proxy; requires judge and manual review for causal accuracy",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=["offline", "gemini", "openai"], default="offline")
    parser.add_argument("--modes", default="rules")
    parser.add_argument("--split", choices=["all", "dev", "test"], default="all")
    parser.add_argument("--limit", type=int)
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
    cases = [c for c in corpus["cases"] if args.split == "all" or c["split"] == args.split]
    if args.limit:
        cases = cases[: args.limit]
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
            "model": settings.openai_model if args.provider == "openai" else settings.gemini_model,
            "corpus_sha256": hashlib.sha256(CORPUS.read_bytes()).hexdigest(),
        }
    )
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result["summaries"], indent=2))


if __name__ == "__main__":
    main()
