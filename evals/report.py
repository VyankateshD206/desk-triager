"""Derive matched and split-level comparisons without crediting offline fallback as LLM success."""

import argparse
import hashlib
import json
from pathlib import Path

from evals.benchmark import summarize


def analyze(report):
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
            "Agent-authored labels await independent human review",
            "Root-cause term matching is a regex proxy",
            "Matched successful subset may be selected by provider reliability",
            "No statistical significance or broad generalization claim",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raw = args.report.read_bytes()
    result = analyze(json.loads(raw))
    result["report_sha256"] = hashlib.sha256(raw).hexdigest()
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(f"Compared {len(result['matched_case_ids'])} matched successful cases")


if __name__ == "__main__":
    main()
