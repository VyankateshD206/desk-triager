"""Offline label review and mode-blinded diagnosis review; never calls a provider."""

import argparse
import copy
import hashlib
import json
import random
from datetime import datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, StrictBool, StrictStr, model_validator

from triager.contracts import Category
from triager.security import sanitize

CORPUS = Path(__file__).parent / "cases/incidents.json"


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class ReviewModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Labels(ReviewModel):
    severity: Literal["critical", "high", "medium", "low", "unknown"]
    category: Category
    abstained: StrictBool
    root_cause_terms: list[list[StrictStr]]

    @model_validator(mode="after")
    def valid_terms(self):
        if any(
            not group or any(not term.strip() for term in group) for group in self.root_cause_terms
        ):
            raise ValueError("Root-cause term groups must not be empty")
        return self


class ReviewIdentity(ReviewModel):
    status: Literal["pending", "approved"] = "pending"
    reviewer: StrictStr = ""
    reviewed_at: datetime | None = None
    notes: StrictStr = ""

    @model_validator(mode="after")
    def completed_identity(self):
        if self.status == "approved" and (
            not self.reviewer.strip()
            or not self.notes.strip()
            or self.reviewed_at is None
            or self.reviewed_at.tzinfo is None
        ):
            raise ValueError("Approved reviews require reviewer, timezone-aware date and notes")
        return self


class LabelReview(ReviewIdentity):
    labels: Labels
    root_cause_reference: StrictStr = ""

    @model_validator(mode="after")
    def completed_reference(self):
        if self.status == "approved" and not self.root_cause_reference.strip():
            raise ValueError("Approved labels need a root-cause reference or explicit uncertainty")
        return self


class DiagnosisReview(ReviewIdentity):
    root_cause_correct: StrictBool | None = None
    evidence_grounded: StrictBool | None = None
    appropriate_abstention: StrictBool | None = None

    @model_validator(mode="after")
    def completed_scores(self):
        if self.status == "approved" and any(
            value is None
            for value in (
                self.root_cause_correct,
                self.evidence_grounded,
                self.appropriate_abstention,
            )
        ):
            raise ValueError("Approved diagnosis reviews require all three judgments")
        return self


def label_packet(corpus):
    return {
        "schema": "desk-label-review-1",
        "corpus_sha256": fingerprint(corpus),
        "instructions": [
            "Review labels before seeing predictions. Do not infer causes absent from evidence.",
            "Correct category/severity/abstention and write a reference explaining supported causes or uncertainty.",
            "Only a human reviewer should mark approved; reviewer identity is attribution, not authentication.",
        ],
        "cases": [
            {
                "case_id": case["id"],
                "case_sha256": fingerprint(case),
                "case": sanitize(copy.deepcopy(case)),
                "review": LabelReview(labels=sanitize(case["expected"])).model_dump(mode="json"),
            }
            for case in corpus["cases"]
        ],
    }


def apply_label_reviews(corpus, packet):
    if packet.get("schema") != "desk-label-review-1" or packet.get("corpus_sha256") != fingerprint(
        corpus
    ):
        raise ValueError("Label packet does not match the original corpus")
    entries = packet["cases"]
    lookup = {entry["case_id"]: entry for entry in entries}
    if len(lookup) != len(entries) or set(lookup) != {c["id"] for c in corpus["cases"]}:
        raise ValueError("Missing, duplicate or unknown review case IDs")
    reviewed = copy.deepcopy(corpus)
    for case in reviewed["cases"]:
        entry = lookup[case["id"]]
        if entry["case_sha256"] != fingerprint(case) or entry["case"] != sanitize(case):
            raise ValueError("Reviewed case content changed; regenerate the packet")
        review = LabelReview.model_validate(entry["review"])
        if review.status == "approved":
            case["expected"] = review.labels.model_dump(mode="json")
            case["annotation_status"] = "human_reviewed_attestation"
            case["label_review"] = review.model_dump(mode="json")
    return reviewed


def blind_content(row):
    reference = row.get("label_review") or {}
    return sanitize(
        {
            "prediction": row["prediction"],
            "evidence": row.get("evidence", []),
            "reference": {
                "labels": row["expected"],
                "root_cause_reference": reference.get("root_cause_reference"),
                "label_reviewed": reference.get("status") == "approved",
            },
        }
    )


def blind_packet(report, seed=None):
    rows = list(report["rows"])
    if any((r.get("label_review") or {}).get("status") != "approved" for r in rows):
        raise ValueError("Complete label review before exporting blind diagnosis reviews")
    if len({(r["id"], r["mode"]) for r in rows}) != len(rows):
        raise ValueError("Duplicate case/mode results")
    rng = random.SystemRandom() if seed is None else random.Random(seed)
    rng.shuffle(rows)
    packet = {
        "schema": "desk-diagnosis-review-1",
        "report_sha256": fingerprint(report),
        "instructions": [
            "Judge recorded evidence support, causal correctness and whether answering/abstaining was appropriate.",
            "Mode/provider labels are hidden; evidence contents may still reveal retrieval. Do not open the separate key.",
            "Unreviewed reference labels are provisional. Do not treat term matching as root-cause truth.",
        ],
        "samples": [],
    }
    key = {"schema": "desk-review-key-1", "report_sha256": fingerprint(report), "samples": {}}
    for row in rows:
        sample_id = uuid4().hex
        content = blind_content(row)
        packet["samples"].append(
            {"sample_id": sample_id, **content, "review": DiagnosisReview().model_dump(mode="json")}
        )
        key["samples"][sample_id] = {
            "case_id": row["id"],
            "mode": row["mode"],
            "row_sha256": fingerprint(row),
            "content_sha256": fingerprint(content),
        }
    return packet, key


def load_diagnosis_reviews(report, packet, key):
    digest = fingerprint(report)
    if (
        packet.get("schema") != "desk-diagnosis-review-1"
        or key.get("schema") != "desk-review-key-1"
    ):
        raise ValueError("Unknown review packet/key schema")
    if packet.get("report_sha256") != digest or key.get("report_sha256") != digest:
        raise ValueError("Diagnosis reviews are bound to a different report")
    rows = {(r["id"], r["mode"]): r for r in report["rows"]}
    samples = packet["samples"]
    if len({s["sample_id"] for s in samples}) != len(samples) or {
        s["sample_id"] for s in samples
    } != set(key["samples"]):
        raise ValueError("Missing, duplicate or unknown review samples")
    if len(rows) != len(report["rows"]) or len(rows) != len(samples):
        raise ValueError("Review/result coverage mismatch")
    results, seen = {}, set()
    for sample in samples:
        binding = key["samples"][sample["sample_id"]]
        pair = (binding["case_id"], binding["mode"])
        if pair not in rows or pair in seen:
            raise ValueError("Review key has missing or duplicate results")
        seen.add(pair)
        row = rows[pair]
        content = {k: v for k, v in sample.items() if k not in {"sample_id", "review"}}
        if (
            binding["row_sha256"] != fingerprint(row)
            or binding["content_sha256"] != fingerprint(content)
            or content != blind_content(row)
        ):
            raise ValueError("Review prediction/evidence/reference was edited")
        review = DiagnosisReview.model_validate(sample["review"])
        if review.status == "approved":
            results[pair] = review.model_dump(mode="json")
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    labels = sub.add_parser("labels")
    labels.add_argument("--corpus", type=Path, default=CORPUS)
    labels.add_argument("--output", type=Path, required=True)
    blind = sub.add_parser("diagnoses")
    blind.add_argument("report", type=Path)
    blind.add_argument("--output", type=Path, required=True)
    blind.add_argument("--key", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "labels":
        if args.output.resolve() == args.corpus.resolve():
            parser.error("Review output must not overwrite the corpus")
        output = label_packet(json.loads(args.corpus.read_text()))
    else:
        if args.report.resolve() in {args.output.resolve(), args.key.resolve()}:
            parser.error("Review output must not overwrite the prediction report")
        if args.output.resolve() == args.key.resolve():
            parser.error("Keep the blind review packet and key in separate files")
        output, key = blind_packet(json.loads(args.report.read_text()))
        args.key.write_text(json.dumps(key, indent=2) + "\n")
        args.key.chmod(0o600)
    args.output.write_text(json.dumps(output, indent=2) + "\n")
    print("Wrote pending reviews; no human judgments or provider calls were generated")


if __name__ == "__main__":
    main()
