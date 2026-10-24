import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError

from triager.app import create_app
from triager.config import Settings
from triager.models import Balance, Telemetry
from triager.runtime import Desk


@pytest.fixture
def desk(tmp_path):
    desk = Desk(
        Settings(
            database_url=f"sqlite:///{tmp_path}/test.db",
            simulator=True,
            ai_provider="offline",
            tick_gap_seconds=8,
            verification_samples=1,
        )
    )
    yield desk
    desk.db.engine.dispose()


def approve(desk, incident_id, action, actor):
    proposal = desk.proposal(incident_id)
    result = desk.approve(incident_id, action, actor, proposal["approval"]["id"], str(uuid4()))
    desk.recovery.execute_next()
    if result["status"] == "queued":
        return {"status": "verifying", "action": action}
    return result


def event(**kwargs):
    return Telemetry(
        **dict(
            {
                "service": "execution-gateway",
                "fill_latency_ms": 85,
                "slippage_bps": 1.2,
                "heartbeat_jitter_ms": 12,
            },
            **kwargs,
        )
    )


def test_duplicate_delivery_is_idempotent(desk):
    e = event(reject_code="429")
    assert desk.ingest(e)["anomalies"] == ["rate_limit"]
    assert desk.ingest(e) == {"duplicate": True}
    snapshot = desk.snapshot()
    assert snapshot["event_count"] == 1
    assert len(snapshot["incidents"]) == 1
    assert snapshot["incidents"][0]["occurrences"] == 1


@pytest.mark.parametrize(
    "kind,service,action",
    [
        ("tick_gap", "market-feed", "reconnect_feed"),
        ("rate_limit", "execution-gateway", "enable_backoff"),
        ("latency", "execution-gateway", "resync_orders"),
        ("nav_mismatch", "portfolio-ledger", "resync_ledger"),
    ],
)
def test_fault_approval_requires_fresh_healthy_verification(desk, kind, service, action):
    desk.inject(kind, service)
    for e in desk.generate():
        desk.ingest(e)
    incident = next(i for i in desk.snapshot()["incidents"] if i["kind"] == kind)
    with pytest.raises(ValueError):
        approve(desk, incident["id"], "arbitrary_python", "trader")
    assert approve(desk, incident["id"], action, "trader")["status"] == "verifying"
    assert desk.proposal(incident["id"])["status"] == "verifying"
    with pytest.raises(ValueError):
        approve(desk, incident["id"], action, "trader")
    desk.ingest(event(service=service))
    assert desk.proposal(incident["id"])["status"] == "resolved"
    audit = desk.snapshot()["audit"]
    assert {a["action"] for a in audit} >= {"opened", action, "resolved"}
    if kind == "nav_mismatch":
        assert desk.db.reconcile()[0]["difference"] == "0.00"


def test_watchdog_detects_absence_without_new_messages(desk):
    desk.last_seen["market-feed"] -= 20
    desk.watchdog()
    incident = desk.snapshot()["incidents"][0]
    assert incident["kind"] == "tick_gap"
    assert incident["service"] == "market-feed"
    assert incident["evidence"]["source"] == "receipt-time watchdog"


def test_late_event_cannot_close_incident(desk):
    desk.ingest(event(reject_code="429"))
    incident = desk.snapshot()["incidents"][0]
    approve(desk, incident["id"], "enable_backoff", "trader")
    result = desk.ingest(event(timestamp=datetime.now(timezone.utc) - timedelta(seconds=20)))
    assert result["late"]
    assert desk.proposal(incident["id"])["status"] == "verifying"


def test_model_detects_subthreshold_drift(desk):
    result = desk.ingest(event(slippage_bps=6.5, heartbeat_jitter_ms=45))
    assert result["score"] < 0
    assert result["anomalies"] == ["ml_degradation"]
    incident = desk.snapshot()["incidents"][0]
    with pytest.raises(ValueError):
        approve(desk, incident["id"], "inspect_only", "trader")


def test_nonhealthy_event_cannot_verify(desk):
    desk.ingest(event(reject_code="429"))
    incident = desk.snapshot()["incidents"][0]
    approve(desk, incident["id"], "enable_backoff", "trader")
    desk.ingest(event(reject_code="429"))
    assert desk.proposal(incident["id"])["status"] == "verifying"


def test_nav_uses_decimal_tolerance(desk):
    with desk.db.Session.begin() as db:
        db.get(Balance, "desk-primary").exchange_nav -= Decimal("0.01")
    assert "nav_mismatch" not in desk.ingest(event(service="portfolio-ledger"))["anomalies"]
    with desk.db.Session.begin() as db:
        db.get(Balance, "desk-primary").exchange_nav -= Decimal("0.02")
    assert "nav_mismatch" in desk.ingest(event(service="portfolio-ledger"))["anomalies"]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"fill_latency_ms": float("nan")},
        {"fill_latency_ms": -1},
        {"timestamp": datetime.now()},
        {"timestamp": datetime.now(timezone.utc) - timedelta(days=1)},
    ],
)
def test_reject_invalid_telemetry(kwargs):
    with pytest.raises(ValidationError):
        event(**kwargs)


def test_restart_preserves_incidents_and_event_dedup(desk):
    e = event(reject_code="429")
    desk.ingest(e)
    restarted = Desk(desk.settings)
    assert restarted.ingest(e)["duplicate"]
    assert restarted.snapshot()["incidents"][0]["status"] == "open"
    restarted.db.engine.dispose()


def test_api_access_and_validation(tmp_path):
    app = create_app(
        Settings(
            database_url=f"sqlite:///{tmp_path}/api.db",
            simulator=False,
            ai_provider="offline",
        )
    )

    async def check():
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client,
        ):
            assert (await client.get("/")).status_code == 200
            headers = {}
            assert (await client.get("/api/snapshot", headers=headers)).status_code == 200
            assert (
                await client.post("/api/telemetry", headers=headers, json={"service": "x"})
            ).status_code == 422
            assert (
                await client.post(
                    "/api/faults",
                    headers=headers,
                    json={"kind": "latency", "service": "execution-gateway"},
                )
            ).status_code == 409
            assert (await client.get("/api/incidents/missing", headers=headers)).status_code == 404
            assert (
                await client.post(
                    "/api/incidents/missing/approve",
                    headers=headers,
                    json={
                        "action": "resync_orders",
                        "actor": "operator",
                        "requires_approval": False,
                    },
                )
            ).status_code == 422
            assert (
                await client.post(
                    "/api/telemetry", headers=headers, json=event().model_dump(mode="json")
                )
            ).status_code == 200

    asyncio.run(check())


def test_gemini_missing_key_falls_back(desk, monkeypatch):
    desk.ingest(event(reject_code="429"))
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    desk.settings.ai_provider = "gemini"
    result = desk.agent.diagnose(desk.snapshot()["incidents"][0])
    assert result["provider"] == "offline"
    assert "fallback_reason" in result


def test_gemini_rest_tool_loop_and_unknown_tool_rejected(desk, monkeypatch):
    desk.ingest(event(reject_code="429"))
    desk.settings.ai_provider = "gemini"
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    requests = []
    real_client = httpx.Client

    def handler(request):
        import json

        body = json.loads(request.content)
        requests.append(body)
        assert request.headers["x-goog-api-key"] == "test-key"
        if len(requests) == 1:
            parts = [
                {"functionCall": {"name": "reconcile_balances", "args": {}}},
                {"functionCall": {"name": "run_shell", "args": {"cmd": "bad"}}},
            ]
        else:
            assert body["contents"][-1]["parts"][1]["functionResponse"]["response"]["error"]
            evidence = json.loads(body["contents"][0]["parts"][0]["text"])["untrusted_evidence"]
            parts = [
                {
                    "text": json.dumps(
                        {
                            "severity": "medium",
                            "category": "rate_limit",
                            "confidence": 0.8,
                            "hypotheses": [
                                {
                                    "cause": "Exchange throttling",
                                    "evidence_ids": [evidence[0]["evidence_id"]],
                                    "supporting_quotes": [
                                        {
                                            "evidence_id": evidence[0]["evidence_id"],
                                            "quote": evidence[0]["content"][:40],
                                        }
                                    ],
                                }
                            ],
                        }
                    )
                }
            ]
        return httpx.Response(
            200, json={"candidates": [{"content": {"role": "model", "parts": parts}}]}
        )

    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: real_client(transport=httpx.MockTransport(handler))
    )
    result = desk.agent.diagnose(desk.snapshot()["incidents"][0])
    assert result["provider"] == "gemini"
    assert result["tool_trace"] == ["inspect_service_logs", "reconcile_balances"]
    assert len(requests) == 2


def test_historical_replay_is_archived_without_refreshing_health(desk):
    old = event().model_dump(mode="json")
    old["timestamp"] = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    replay = Telemetry.model_validate(old, context={"allow_historical": True})
    seen = desk.last_seen["execution-gateway"]
    result = desk.ingest(replay)
    assert result["late"]
    assert desk.last_seen["execution-gateway"] == seen
    assert desk.snapshot()["event_count"] == 1


def test_automatic_triage_persists_report_once(desk):
    desk.ingest(event(reject_code="429"))
    desk.triage_next()
    desk.triage_next()
    snapshot = desk.snapshot()
    assert snapshot["incidents"][0]["report"]
    assert sum(a["action"] == "diagnosed" for a in snapshot["audit"]) == 1


def test_preapproval_healthy_sample_cannot_verify(desk):
    desk.ingest(event(reject_code="429"))
    healthy_but_queued = event()
    incident = desk.snapshot()["incidents"][0]
    approve(desk, incident["id"], "enable_backoff", "trader")
    desk.ingest(healthy_but_queued)
    assert desk.proposal(incident["id"])["status"] == "verifying"


def test_service_watermark_survives_restart_and_replay(desk):
    desk.ingest(event())
    watermark = desk.accepted_at["execution-gateway"]
    replay = event(timestamp=watermark - timedelta(seconds=4))
    desk.ingest(replay)
    restarted = Desk(desk.settings)
    assert restarted.accepted_at["execution-gateway"] == watermark
    restarted.db.engine.dispose()


@pytest.mark.parametrize("unresolved", [1, 102])
def test_unresolved_totals_and_queue_priority_beyond_visible_history(desk, unresolved):
    from triager.models import Incident

    with desk.db.Session.begin() as db:
        for index in range(102):
            db.add(
                Incident(
                    id=f"history-{index}",
                    service="execution-gateway",
                    kind="latency",
                    status="open" if index < unresolved else "resolved",
                    opened_at=f"2026-01-01T00:{index // 60:02}:{index % 60:02}+00:00",
                    updated_at="2026-01-01T00:00:00+00:00",
                    evidence={},
                    diagnosis="Historical incident",
                    action="resync_orders",
                )
            )
    snapshot = desk.snapshot()
    assert len(snapshot["incidents"]) == 100
    assert sum(i["status"] == "open" for i in snapshot["incidents"]) == min(unresolved, 100)
    assert snapshot["open_incident_count"] == unresolved
    assert snapshot["open_incidents_by_service"]["execution-gateway"] == unresolved


def test_legacy_account_is_renamed_without_changing_balances(desk):
    with desk.db.Session.begin() as db:
        balance = db.get(Balance, "desk-primary")
        balance.account = "demo-desk"
        balance.local_nav = Decimal("999000.00")
        balance.exchange_nav = Decimal("998750.00")
    desk.db.initialize(seed=True)
    with desk.db.Session() as db:
        assert db.get(Balance, "demo-desk") is None
        balance = db.get(Balance, "desk-primary")
        assert balance.local_nav == Decimal("999000.00")
        assert balance.exchange_nav == Decimal("998750.00")


def test_policy_rechecks_persisted_action_against_incident_kind(desk):
    from triager.models import Incident

    desk.ingest(event(reject_code="429"))
    incident = desk.snapshot()["incidents"][0]
    with desk.db.Session.begin() as session:
        session.get(Incident, incident["id"]).action = "resync_ledger"
    assert desk.proposal(incident["id"])["policy"]["disposition"] == "blocked"
    with pytest.raises(ValueError):
        approve(desk, incident["id"], "resync_ledger", "operator")
    assert desk.proposal(incident["id"])["status"] == "open"


def test_review_exposes_persisted_grounding_and_usage(desk):
    desk.ingest(event(reject_code="429", log="WARN HTTP 429; retry-after 5s"))
    incident_id = desk.snapshot()["incidents"][0]["id"]
    assert desk.proposal(incident_id)["investigation"] is None
    desk.triage(incident_id)
    review = desk.proposal(incident_id)["investigation"]
    assert review["provider"] == "offline"
    assert review["evidence_items"][0]["evidence_id"]
    assert review["node_trace"][-1]["node"] == "final_report"
    assert review["estimated_cost_usd"] == 0


def test_snapshot_has_latest_analysis_and_review_has_timeline(desk):
    desk.ingest(event(reject_code="429", log="WARN HTTP 429; retry-after 5s"))
    id = desk.snapshot()["incidents"][0]["id"]
    desk.triage(id)
    item = desk.snapshot()["incidents"][0]
    assert item["analysis_source"] == "offline"
    assert item["severity"] == "medium"
    assert item["abstained"] is False
    assert item["summary"]
    review = desk.proposal(id)
    assert [a["action"] for a in review["timeline"]] == ["opened", "diagnosed"]
    assert review["investigation"]["budget"]["tools"] == desk.settings.agent_max_tools


@pytest.mark.parametrize("value,provider", [(1250, "gemini"), (1251, "offline")])
def test_nav_numeric_diagnosis_never_approves_or_recovers(desk, value, provider):
    import json

    from sqlalchemy import func, select

    from triager.models import Audit, RecoveryJob, RecoveryProposal

    desk.inject("nav_mismatch", "portfolio-ledger")
    for sample in desk.generate():
        desk.ingest(sample)
    incident = next(i for i in desk.snapshot()["incidents"] if i["kind"] == "nav_mismatch")
    desk.settings.ai_provider = "gemini"
    desk.settings.critic_enabled = False

    def model(state):
        item = next(e for e in state["evidence_items"] if e["source"] == "ledger:snapshot")
        return {
            "role": "model",
            "parts": [
                {
                    "text": json.dumps(
                        {
                            "severity": "high",
                            "category": "nav_mismatch",
                            "confidence": 0.8,
                            "hypotheses": [
                                {
                                    "cause": "Recorded NAV discrepancy needs human investigation",
                                    "evidence_ids": [item["evidence_id"]],
                                    "numeric_claims": [
                                        {
                                            "evidence_id": item["evidence_id"],
                                            "pointer": "/0/difference",
                                            "value": value,
                                        }
                                    ],
                                }
                            ],
                        }
                    )
                }
            ],
        }

    desk.agent.model_turn = model
    result = desk.triage(incident["id"])
    assert result["provider"] == provider
    assert ("fallback_reason" in result) == (provider == "offline")
    with desk.db.Session() as db:
        assert db.scalar(select(func.count()).select_from(RecoveryJob)) == 0
        assert set(db.scalars(select(RecoveryProposal.status))) <= {"pending", "superseded"}
        assert "approval_queued" not in set(db.scalars(select(Audit.action)))
    assert desk.db.reconcile()[0]["difference"] == "1250.00"
    assert (
        next(i for i in desk.snapshot()["incidents"] if i["id"] == incident["id"])["status"]
        == "open"
    )
