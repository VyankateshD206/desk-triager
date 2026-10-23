from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver
from sqlalchemy import func, select

from triager.config import Settings
from triager.models import Incident, RecoveryJob, Telemetry
from triager.runtime import Desk


@pytest.fixture
def desk(tmp_path):
    desk = Desk(
        Settings(
            database_url=f"sqlite:///{tmp_path}/test.db",
            ai_provider="offline",
            simulator=True,
            tick_gap_seconds=8,
            verification_samples=2,
        )
    )
    desk.inject("rate_limit", "execution-gateway")
    for event in desk.generate():
        desk.ingest(event)
    yield desk
    desk.db.engine.dispose()


def proposal(desk):
    incident = next(i for i in desk.snapshot()["incidents"] if i["kind"] == "rate_limit")
    return desk.proposal(incident["id"])


def approve(desk, item, key):
    return desk.approve(item["id"], item["action"], "operator", item["approval"]["id"], key)


def healthy(desk):
    desk.ingest(
        Telemetry(
            service="execution-gateway",
            fill_latency_ms=85,
            slippage_bps=1.2,
            heartbeat_jitter_ms=12,
        )
    )


def test_interrupt_survives_restart_and_deduplicates_approval(desk):
    item = proposal(desk)
    with SqliteSaver.from_conn_string(desk.recovery.path) as saver:
        state = desk.recovery.graph(saver).get_state(desk.recovery.config(item["approval"]["id"]))
        assert state.next == ("human_review",)
        assert state.tasks[0].interrupts[0].value["proposal_id"] == item["approval"]["id"]
    restarted = Desk(desk.settings)
    key = str(uuid4())
    first = approve(restarted, item, key)
    assert first["status"] == "queued"
    assert approve(restarted, item, key) == first
    assert restarted.faults["execution-gateway"] == "rate_limit"
    restarted.recovery.execute_next()
    assert "execution-gateway" not in restarted.faults
    assert approve(restarted, item, key)["execution_id"] == first["execution_id"]
    with restarted.db.Session() as session:
        assert session.scalar(select(func.count()).select_from(RecoveryJob)) == 1
    assert restarted.recovery.execute_next() is None
    healthy(restarted)
    assert restarted.proposal(item["id"])["status"] == "verifying"
    healthy(restarted)
    assert restarted.proposal(item["id"])["status"] == "resolved"
    restarted.db.engine.dispose()


def test_concurrent_identical_approvals_share_one_job(desk):
    item, key = proposal(desk), str(uuid4())
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: approve(desk, item, key), range(4)))
    assert len({r["execution_id"] for r in results}) == 1


def test_idempotency_key_cannot_change_actor_or_proposal(desk):
    item, key = proposal(desk), str(uuid4())
    approve(desk, item, key)
    with pytest.raises(ValueError, match="different request"):
        desk.approve(item["id"], item["action"], "other", item["approval"]["id"], key)
    with pytest.raises(ValueError):
        approve(desk, item, str(uuid4()))


def test_stale_report_or_new_fault_requires_new_review(desk):
    item = proposal(desk)
    with desk.db.Session.begin() as session:
        session.get(Incident, item["id"]).report = "A revised diagnosis"
    with pytest.raises(ValueError, match="changed"):
        approve(desk, item, str(uuid4()))
    revised = desk.proposal(item["id"])
    assert revised["approval"]["id"] != item["approval"]["id"]
    desk.inject("rate_limit", "execution-gateway")
    with pytest.raises(ValueError, match="changed"):
        approve(desk, revised, str(uuid4()))


def test_execution_rechecks_preconditions(desk):
    item = proposal(desk)
    approve(desk, item, str(uuid4()))
    desk.inject("latency", "execution-gateway")
    result = desk.recovery.execute_next()
    assert result["status"] == "failed"
    assert desk.faults["execution-gateway"] == "latency"
    assert desk.proposal(item["id"])["status"] == "failed"


def test_rejection_is_durable_and_idempotent(desk):
    item, key = proposal(desk), str(uuid4())

    def reject():
        return desk.reject(
            item["id"],
            item["action"],
            "operator",
            item["approval"]["id"],
            key,
            "Need a second source",
        )

    assert reject()["status"] == "rejected"
    assert reject()["status"] == "rejected"
    assert desk.recovery.execute_next() is None
    assert desk.proposal(item["id"])["approval"]["status"] == "rejected"
    with pytest.raises(ValueError):
        approve(desk, item, str(uuid4()))


def test_expired_worker_lease_is_reclaimed(desk):
    item = proposal(desk)
    result = approve(desk, item, str(uuid4()))
    with desk.db.Session.begin() as session:
        job = session.get(RecoveryJob, result["execution_id"])
        job.status, job.lease_until = (
            "running",
            (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
        )
        job.attempts = 1
    result = desk.recovery.execute_next()
    assert result["status"] == "succeeded"
    assert result["attempts"] == 2


def test_verification_deadline_escalates_silence(desk):
    item = proposal(desk)
    result = approve(desk, item, str(uuid4()))
    desk.recovery.execute_next()
    with desk.db.Session.begin() as session:
        session.get(RecoveryJob, result["execution_id"]).verification_deadline = (
            datetime.now(timezone.utc) - timedelta(seconds=1)
        ).isoformat()
    desk.watchdog()
    assert desk.proposal(item["id"])["status"] == "failed"


def test_sql_commit_replay_cannot_create_second_outbox_record(desk):
    item, key = proposal(desk), str(uuid4())
    result = approve(desk, item, key)
    with SqliteSaver.from_conn_string(desk.recovery.path) as saver:
        state = desk.recovery.graph(saver).get_state(desk.recovery.config(item["approval"]["id"]))
    replay = desk.recovery.record_decision(state.values["decision"])
    assert replay["execution_id"] == result["execution_id"]
