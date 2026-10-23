"""Run a deliberately simple rules baseline: python -m evals.run."""

import argparse
import json
import time
from pathlib import Path

from triager.baseline import rules_baseline
from triager.contracts import Diagnosis, IncidentInput, unsupported_citations


def evaluate(cases, predictor=rules_baseline):
    if not cases or len({case["id"] for case in cases}) != len(cases):
        raise ValueError("Cases must be nonempty and have unique IDs")
    rows = []
    for case in cases:
        incident = IncidentInput.model_validate(case["input"])
        if any(item.service != incident.service for item in incident.evidence):
            raise ValueError("Evidence outside incident service")
        start = time.perf_counter()
        report = Diagnosis.model_validate(predictor(incident))
        latency = (time.perf_counter() - start) * 1000
        refs = {ref for hypothesis in report.hypotheses for ref in hypothesis.evidence_ids}
        rows.append(
            {
                "id": case["id"],
                "expected": case["expected"],
                "prediction": report.model_dump(mode="json"),
                "latency_ms": latency,
                "citation_count": len(refs),
                "invalid_citations": len(unsupported_citations(report, incident.evidence)),
            }
        )
    labels = sorted(
        {row["expected"]["category"] for row in rows}
        | {row["prediction"]["category"] for row in rows}
    )
    f1 = []
    for label in labels:
        tp = sum(r["expected"]["category"] == label == r["prediction"]["category"] for r in rows)
        fp = sum(r["expected"]["category"] != label == r["prediction"]["category"] for r in rows)
        fn = sum(r["expected"]["category"] == label != r["prediction"]["category"] for r in rows)
        f1.append(2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0)
    citations = sum(r["citation_count"] for r in rows)
    return {
        "benchmark_version": "seed-1",
        "case_count": len(rows),
        "category_macro_f1": sum(f1) / len(f1),
        "severity_accuracy": sum(
            r["expected"]["severity"] == r["prediction"]["severity"] for r in rows
        )
        / len(rows),
        "abstention_accuracy": sum(
            r["expected"]["abstained"] == r["prediction"]["abstained"] for r in rows
        )
        / len(rows),
        "answer_coverage": sum(not r["prediction"]["abstained"] for r in rows) / len(rows),
        "citation_validity": (
            1 - sum(r["invalid_citations"] for r in rows) / citations if citations else None
        ),
        "rows": rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=Path(__file__).parent / "cases/seed.json")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = evaluate(json.loads(args.cases.read_text()))
    result["predictor"] = "rules-baseline-v1"
    output = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.write_text(output)
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}, indent=2))


if __name__ == "__main__":
    main()
