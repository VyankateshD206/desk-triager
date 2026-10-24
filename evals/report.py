"""Derive matched and split-level comparisons without crediting offline fallback as LLM success."""

import argparse
import hashlib
import json
from pathlib import Path

from evals.benchmark import summarize
from evals.paired import analyze_paired


def analyze(report, reviews=None, bootstrap_samples=1000):
    modes = list(report["summaries"])
    rows = report["rows"]
    usable_ids = {
        mode: {r["id"] for r in rows if r["mode"] == mode and not r["fallback_reason"]}
        for mode in modes
    }
    matched = set.intersection(*usable_ids.values()) if usable_ids else set()
    groups = {
        "all_attempts_including_fallback": rows,
        "successful_provider_responses": [r for r in rows if not r["fallback_reason"]],
        "matched_successful_cases": [r for r in rows if r["id"] in matched],
        "dev_attempts": [r for r in rows if r["split"] == "dev"],
        "test_attempts": [r for r in rows if r["split"] == "test"],
    }
    return {
        "matched_case_ids": sorted(matched),
        "paired_rag": analyze_paired(report, reviews, samples=bootstrap_samples),
        "human_validated_labels": report["human_validated_labels"],
        "comparisons": {
            name: {
                mode: summarize([r for r in group if r["mode"] == mode])
                for mode in modes
                if any(r["mode"] == mode for r in group)
            }
            for name, group in groups.items()
        },
        "caveats": [
            "Unreviewed labels remain provisional; completed reviewer fields are operator attestations, not authenticated independence",
            "Root-cause term matching is a regex proxy",
            "Matched successful subset may be selected by provider reliability",
            "Legacy successful-provider groups filter fallback only; paired matched-model groups additionally require recorded matching model/configuration metadata",
            "No statistical significance or broad generalization claim",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reviews", type=Path, help="Completed mode-blinded diagnosis packet")
    parser.add_argument("--review-key", type=Path, help="Separate packet-to-result binding key")
    parser.add_argument("--bootstrap-samples", type=int, default=1000)
    args = parser.parse_args()
    if bool(args.reviews) != bool(args.review_key):
        parser.error("Supply both --reviews and --review-key")
    if not 1 <= args.bootstrap_samples <= 10000:
        parser.error("Bootstrap samples must be 1..10000")
    raw = args.report.read_bytes()
    report = json.loads(raw)
    reviews = None
    if args.reviews:
        from evals.review_packets import load_diagnosis_reviews

        reviews = load_diagnosis_reviews(
            report, json.loads(args.reviews.read_text()), json.loads(args.review_key.read_text())
        )
    result = analyze(report, reviews, args.bootstrap_samples)
    result["report_sha256"] = hashlib.sha256(raw).hexdigest()
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    pairs = result["paired_rag"]
    print(
        f"Compared {pairs['complete_pairs']} graph/RAG pairs; "
        f"{pairs['comparisons']['all']['matched_model_successes']['cases']} matching-model pairs; "
        f"{result['human_validated_labels']} label review attestations"
    )


if __name__ == "__main__":
    main()
