"""Export rejected diagnoses as redacted, unlabeled candidates for human eval review."""

import argparse
import json
from pathlib import Path

from sqlalchemy import select

from triager.config import Settings
from triager.db import Database
from triager.models import Audit, RecoveryJob
from triager.security import sanitize


def export_candidates(db):
    rows = []
    with db.Session() as session:
        jobs = session.scalars(select(RecoveryJob).where(RecoveryJob.decision == "rejected"))
        for job in jobs:
            audit = session.scalar(
                select(Audit)
                .where(
                    Audit.incident_id == job.incident_id,
                    Audit.action == "diagnosed",
                    Audit.at <= job.created_at,
                )
                .order_by(Audit.at.desc())
            )
            if not audit:
                continue
            rows.append(
                sanitize(
                    {
                        "id": "feedback-" + job.id,
                        "origin": "operator_rejection",
                        "annotation_status": "pending_human_review",
                        "expected": None,
                        "reason": job.reason,
                        "candidate_diagnosis": audit.detail.get("diagnosis"),
                        "evidence": audit.detail.get("evidence_items", []),
                    }
                )
            )
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    db = Database(Settings().database_url)
    try:
        rows = export_candidates(db)
        args.output.write_text(json.dumps({"candidates": rows}, indent=2) + "\n")
        print(f"Exported {len(rows)} unlabeled candidates; review before eval or retrieval import")
    finally:
        db.engine.dispose()


if __name__ == "__main__":
    main()
