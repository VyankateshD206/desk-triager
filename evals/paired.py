"""Paired RAG ablation with family-cluster uncertainty; no provider execution."""

import random
import statistics

BASE = "graph"
RAG = "graph_retrieval"


def model_signature(row):
    calls = row.get("model_calls") or []
    identities = {(c.get("provider") or row.get("provider"), c.get("model")) for c in calls}
    if not identities or any(
        p not in {"gemini", "openai"} or not isinstance(m, str) or not m for p, m in identities
    ):
        return None
    return frozenset(identities)


def model_success(row):
    return (
        not row.get("fallback_reason")
        and row.get("provider") != "offline"
        and model_signature(row) is not None
    )


def score(rows, metric, labels, reviews):
    if not rows:
        return None
    if metric == "category_macro_f1":
        values = []
        for label in labels:
            tp = sum(
                r["expected"]["category"] == label == r["prediction"]["category"] for r in rows
            )
            fp = sum(
                r["expected"]["category"] != label == r["prediction"]["category"] for r in rows
            )
            fn = sum(
                r["expected"]["category"] == label != r["prediction"]["category"] for r in rows
            )
            values.append(2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0)
        return statistics.mean(values)
    if metric == "root_cause_regex_proxy_hit_rate":
        eligible = [r for r in rows if r["expected"].get("root_cause_terms")]
        return statistics.mean(r["root_cause_proxy_hit"] for r in eligible) if eligible else None
    if metric in {
        "human_root_cause_correct",
        "human_evidence_grounded",
        "human_appropriate_abstention",
    }:
        field = metric.removeprefix("human_")
        return statistics.mean(reviews[(r["id"], r["mode"])][field] for r in rows)
    values = {
        "category_accuracy": lambda r: r["prediction"]["category"] == r["expected"]["category"],
        "severity_accuracy": lambda r: r["prediction"]["severity"] == r["expected"]["severity"],
        "abstention_accuracy": lambda r: r["prediction"]["abstained"] == r["expected"]["abstained"],
        "answer_coverage": lambda r: not r["prediction"]["abstained"],
        "unsupported_answer_rate": lambda r: (
            not r["prediction"]["abstained"] and bool(r["verification_issues"])
        ),
    }
    return statistics.mean(values[metric](r) for r in rows)


def metric_comparison(pairs, metric, reviews, samples, seed):
    labels = sorted(
        {r["expected"]["category"] for pair in pairs for r in pair}
        | {r["prediction"]["category"] for pair in pairs for r in pair}
    )
    left = score([a for a, _ in pairs], metric, labels, reviews)
    right = score([b for _, b in pairs], metric, labels, reviews)
    result = {
        BASE: left,
        RAG: right,
        "delta_rag_minus_graph": right - left if left is not None and right is not None else None,
        "family_cluster_95pct_interval": None,
    }
    groups = {}
    for pair in pairs:
        groups.setdefault(pair[0]["family"], []).append(pair)
    if left is None or right is None or len(groups) < 2:
        return result
    families, draws, rng = sorted(groups), [], random.Random(seed)
    for _ in range(samples):
        selected = [p for family in rng.choices(families, k=len(families)) for p in groups[family]]
        a = score([a for a, _ in selected], metric, labels, reviews)
        b = score([b for _, b in selected], metric, labels, reviews)
        if a is not None and b is not None:
            draws.append(b - a)
    if draws:
        draws.sort()
        result["family_cluster_95pct_interval"] = [
            draws[int(0.025 * (len(draws) - 1))],
            draws[int(0.975 * (len(draws) - 1))],
        ]
    return result


def compare_pairs(pairs, reviews, samples, seed):
    metrics = (
        "category_accuracy",
        "category_macro_f1",
        "severity_accuracy",
        "abstention_accuracy",
        "answer_coverage",
        "unsupported_answer_rate",
        "root_cause_regex_proxy_hit_rate",
    )
    results = {m: metric_comparison(pairs, m, reviews, samples, seed) for m in metrics}
    wins = losses = ties = 0
    for a, b in pairs:
        left = a["expected"]["category"] == a["prediction"]["category"]
        right = b["expected"]["category"] == b["prediction"]["category"]
        wins += right > left
        losses += right < left
        ties += left == right
    known_costs = [
        b["cost_estimate_usd"] - a["cost_estimate_usd"]
        for a, b in pairs
        if a.get("cost_estimate_usd") is not None and b.get("cost_estimate_usd") is not None
    ]
    latencies = [
        b["latency_ms"] - a["latency_ms"]
        for a, b in pairs
        if a.get("latency_ms") is not None and b.get("latency_ms") is not None
    ]
    human_pairs = [
        (a, b)
        for a, b in pairs
        if all(
            (r["id"], r["mode"]) in reviews
            and reviews[(r["id"], r["mode"])].get("status") == "approved"
            and (r.get("label_review") or {}).get("status") == "approved"
            for r in (a, b)
        )
    ]
    return {
        "cases": len(pairs),
        "families": len({a["family"] for a, _ in pairs}),
        "metrics": results,
        "category_outcomes": {"improved": wins, "regressed": losses, "unchanged": ties},
        "median_paired_latency_delta_ms": statistics.median(latencies) if latencies else None,
        "latency_pairs": len(latencies),
        "mean_paired_known_cost_delta_usd": statistics.mean(known_costs) if known_costs else None,
        "known_cost_pairs": len(known_costs),
        "reviewed_label_and_prediction_pairs": len(human_pairs),
        "human_metrics": {
            m: metric_comparison(human_pairs, m, reviews, samples, seed)
            for m in (
                "human_root_cause_correct",
                "human_evidence_grounded",
                "human_appropriate_abstention",
            )
        },
    }


def analyze_paired(report, reviews=None, samples=1000, seed=42):
    if samples < 1:
        raise ValueError("Bootstrap samples must be positive")
    rows = [r for r in report["rows"] if r["mode"] in {BASE, RAG}]
    indexed = {(r["id"], r["mode"]): r for r in rows}
    if len(indexed) != len(rows):
        raise ValueError("Duplicate paired case/mode rows")
    ids = sorted({r["id"] for r in rows})
    pairs = [
        (indexed[(i, BASE)], indexed[(i, RAG)])
        for i in ids
        if (i, BASE) in indexed and (i, RAG) in indexed
    ]
    for a, b in pairs:
        if any(a[key] != b[key] for key in ("expected", "family", "split")):
            raise ValueError("Paired results disagree on reference, family or split")
        if a.get("comparison_settings") != b.get("comparison_settings"):
            raise ValueError("Paired experimental settings differ")
    successes = [
        (a, b)
        for a, b in pairs
        if model_success(a)
        and model_success(b)
        and model_signature(a) == model_signature(b)
        and a.get("comparison_settings")
    ]
    scopes = {}
    for split in ("all", "dev", "test"):
        selected = [(a, b) for a, b in pairs if split == "all" or a["split"] == split]
        selected_success = [(a, b) for a, b in successes if split == "all" or a["split"] == split]
        scopes[split] = {
            "all_attempts_including_fallback": compare_pairs(
                selected, reviews or {}, samples, seed
            ),
            "matched_model_successes": compare_pairs(
                selected_success, reviews or {}, samples, seed
            ),
        }
    rag_rows = [r for r in rows if r["mode"] == RAG]
    known_usage = [r for r in rag_rows if isinstance(r.get("retrieval_executed"), bool)]
    return {
        "status": "paired_results_available" if pairs else "no_paired_rag_results",
        "complete_pairs": len(pairs),
        "union_cases": len(ids),
        "missing_graph": [i for i in ids if (i, BASE) not in indexed],
        "missing_graph_retrieval": [i for i in ids if (i, RAG) not in indexed],
        "provider_failure_or_unverified_pairs": len(pairs) - len(successes),
        "fallback_pairs": sum(
            bool(a.get("fallback_reason") or b.get("fallback_reason")) for a, b in pairs
        ),
        "unverified_configuration_pairs": sum(not a.get("comparison_settings") for a, _ in pairs),
        "provider_or_model_mismatch_pairs": sum(
            model_success(a) and model_success(b) and model_signature(a) != model_signature(b)
            for a, b in pairs
        ),
        "retrieval_usage": {
            "cases": len(rag_rows),
            "recorded_usage_cases": len(known_usage),
            "executed_cases": sum(r["retrieval_executed"] for r in known_usage),
            "execution_rate_on_recorded_cases": statistics.mean(
                r["retrieval_executed"] for r in known_usage
            )
            if known_usage
            else None,
            "cases_with_documents": sum(bool(r.get("retrieved_document_ids")) for r in rag_rows),
        },
        "comparisons": scopes,
        "uncertainty": {
            "method": "paired family-cluster percentile bootstrap",
            "samples": samples,
            "seed": seed,
            "minimum_families": 2,
        },
        "caveats": [
            "Deltas are RAG minus graph; lower unsupported-answer rate, latency and cost are better.",
            "Intervals reflect this small family-grouped dataset, not broad generalization or guaranteed significance.",
            "All-attempt results include fallback; matched model successes can be selected by provider reliability.",
            "Human accuracy requires approved label and mode-blinded prediction reviews for both members of a pair.",
            "Reviewer fields are operator attestations, not authenticated proof of independent human review.",
            "Retrieval-use subsets are descriptive; they are not a randomized causal estimate of retrieval benefit.",
        ],
    }
