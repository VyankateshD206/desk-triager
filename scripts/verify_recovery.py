"""Exercise the approval outbox on an isolated PostgreSQL schema in demo CI."""

import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from sqlalchemy import func, select, text

from triager.config import Settings
from triager.db import Database
from triager.models import RecoveryJob, Telemetry
from triager.runtime import Desk


def main():
    url = os.environ["DATABASE_URL"]
    admin = Database(url)
    schema = "recovery_test_" + uuid4().hex
    desks = []
    try:
        with admin.engine.begin() as connection:
            connection.execute(text("CREATE SCHEMA " + schema))
        scoped = url + ("&" if "?" in url else "?") + "options=-csearch_path%3D" + schema
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(
                database_url=scoped,
                simulator=True,
                ai_provider="offline",
                graph_checkpoint_path=directory + "/graph.sqlite3",
            )
            desk = Desk(settings)
            desks.append(desk)
            desk.inject("nav_mismatch", "portfolio-ledger")
            for sample in desk.generate():
                desk.ingest(sample)
            incident = next(i for i in desk.snapshot()["incidents"] if i["kind"] == "nav_mismatch")
            item = desk.proposal(incident["id"])
            key = str(uuid4())
            job = desk.approve(
                item["id"], item["action"], "ci-operator", item["approval"]["id"], key
            )
            restarted = Desk(settings)
            desks.append(restarted)
            assert (
                restarted.approve(
                    item["id"], item["action"], "ci-operator", item["approval"]["id"], key
                )["execution_id"]
                == job["execution_id"]
            )
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda d: d.recovery.execute_next(), desks))
            assert sum(r is not None for r in results) == 1
            assert all(row["difference"] == "0.00" for row in restarted.db.reconcile())
            for _ in range(settings.verification_samples):
                restarted.ingest(
                    Telemetry(
                        service="portfolio-ledger",
                        fill_latency_ms=85,
                        slippage_bps=1.2,
                        heartbeat_jitter_ms=12,
                    )
                )
            assert restarted.proposal(item["id"])["status"] == "resolved"
            with restarted.db.Session() as session:
                assert session.scalar(select(func.count()).select_from(RecoveryJob)) == 1
            print(
                "PASS PostgreSQL: interrupt resume, idempotency, atomic worker claim, ledger, verification."
            )
    finally:
        for desk in desks:
            desk.db.engine.dispose()
        with admin.engine.begin() as connection:
            connection.execute(text("DROP SCHEMA IF EXISTS " + schema + " CASCADE"))
        admin.engine.dispose()


if __name__ == "__main__":
    main()
