import logging
import random
import threading
import time
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import func, select

from .agent import TriageAgent
from .db import Database
from .detector import RUNBOOKS, Detector
from .models import SERVICES, Audit, Balance, Event, Incident, ServiceWatermark, Telemetry, now

log = logging.getLogger(__name__)


def record(row):
    return {c.name: getattr(row, c.name) for c in row.__table__.columns}


class Desk:
    """One process owns simulation, ingestion and recovery; DB is the source of truth."""

    def __init__(self, settings):
        settings.validate()
        self.settings = settings
        self.db = Database(settings.database_url)
        self.db.initialize(seed=settings.simulator)
        self.detector = Detector()
        self.agent = TriageAgent(self.db, settings)
        self.lock = threading.RLock()
        self.faults = {}
        self.rng = random.Random(24)
        self.last_seen = {s: time.monotonic() for s in SERVICES}
        self.accepted_at = {}
        with self.db.Session() as db:
            for watermark in db.scalars(select(ServiceWatermark)):
                self.accepted_at[watermark.service] = datetime.fromisoformat(
                    watermark.event_timestamp
                )
        self.last_ingest = None
        self.errors = {}

    def open_incident(self, db, service, kind, evidence):
        incident = db.scalar(
            select(Incident).where(
                Incident.service == service, Incident.kind == kind, Incident.status != "resolved"
            )
        )
        if incident:
            incident.occurrences += 1
            incident.updated_at = now()
            incident.evidence = evidence
            return
        diagnosis, action = RUNBOOKS[kind]
        incident = Incident(
            id=str(uuid4()),
            service=service,
            kind=kind,
            status="open",
            opened_at=now(),
            updated_at=now(),
            evidence=evidence,
            diagnosis=diagnosis,
            action=action,
        )
        db.add(incident)
        db.flush()
        db.add(
            Audit(
                at=now(),
                incident_id=incident.id,
                actor="detector",
                action="opened",
                detail=evidence,
            )
        )

    def ingest(self, event):
        with self.lock:
            with self.db.Session.begin() as db:
                if db.get(Event, event.event_id):
                    return {"duplicate": True}
                # Late events remain in the durable log, but cannot overwrite current service state.
                watermark = self.accepted_at.get(event.service)
                stale = (
                    datetime.now(timezone.utc) - event.timestamp
                ).total_seconds() > self.settings.tick_gap_seconds
                late = stale or (watermark is not None and event.timestamp <= watermark)
                mismatch = any(
                    abs(Decimal(b["difference"])) > Decimal("0.01") for b in self.db.reconcile(db)
                )
                score, kinds = self.detector.detect(event, mismatch)
                payload = event.model_dump(mode="json")
                db.add(
                    Event(
                        id=event.event_id,
                        service=event.service,
                        received_at=now(),
                        payload=payload,
                        score=score,
                    )
                )
                if not late:
                    watermark_row = db.get(ServiceWatermark, event.service)
                    if watermark_row:
                        watermark_row.event_timestamp = event.timestamp.isoformat()
                    else:
                        db.add(
                            ServiceWatermark(
                                service=event.service, event_timestamp=event.timestamp.isoformat()
                            )
                        )
                    for kind in kinds:
                        self.open_incident(
                            db,
                            event.service,
                            kind,
                            {"event_id": event.event_id, "score": score, "telemetry": payload},
                        )
                    pending = db.scalars(
                        select(Incident).where(
                            Incident.service == event.service, Incident.status == "verifying"
                        )
                    ).all()
                    for incident in pending:
                        if (
                            incident.kind not in kinds
                            and score >= 0
                            and event.timestamp > datetime.fromisoformat(incident.updated_at)
                        ):
                            incident.status, incident.updated_at = "resolved", now()
                            db.add(
                                Audit(
                                    at=now(),
                                    incident_id=incident.id,
                                    actor="verifier",
                                    action="resolved",
                                    detail={"healthy_event": event.event_id, "score": score},
                                )
                            )
            if not late:
                self.accepted_at[event.service] = event.timestamp
                self.last_seen[event.service] = time.monotonic()
            self.last_ingest = now()
            return {"duplicate": False, "late": late, "score": score, "anomalies": kinds}

    def watchdog(self):
        with self.lock, self.db.Session.begin() as db:
            for service, seen in self.last_seen.items():
                gap = time.monotonic() - seen
                if gap > self.settings.tick_gap_seconds:
                    self.open_incident(
                        db,
                        service,
                        "tick_gap",
                        {"silence_seconds": round(gap, 2), "source": "receipt-time watchdog"},
                    )

    def inject(self, kind, service):
        if not self.settings.simulator:
            raise ValueError("Fault injection requires SIMULATOR_ENABLED=true")
        if kind not in {
            "tick_gap",
            "rate_limit",
            "nav_mismatch",
            "latency",
            "ml_degradation",
            "silence",
        }:
            raise ValueError("Unknown fault")
        if kind == "nav_mismatch" and service != "portfolio-ledger":
            raise ValueError("NAV mismatch belongs to portfolio-ledger")
        with self.lock:
            self.faults[service] = kind
            if kind == "nav_mismatch":
                with self.db.Session.begin() as db:
                    balance = db.get(Balance, "desk-primary")
                    balance.exchange_nav = balance.local_nav - Decimal("1250.00")

    def generate(self):
        events = []
        with self.lock:
            for service in SERVICES:
                kind = self.faults.get(service)
                if kind == "silence":
                    continue
                data = dict(
                    service=service,
                    fill_latency_ms=max(1, self.rng.gauss(85, 8)),
                    slippage_bps=max(0, self.rng.gauss(1.2, 0.2)),
                    heartbeat_jitter_ms=max(0, self.rng.gauss(12, 2)),
                )
                if kind == "tick_gap":
                    data.update(
                        tick_age_ms=12000,
                        heartbeat_jitter_ms=300,
                        log="WARN websocket stale; tick age 12000ms",
                    )
                elif kind == "rate_limit":
                    data.update(
                        reject_code="429", log="WARN simulated exchange HTTP 429; retry-after 5s"
                    )
                elif kind == "nav_mismatch":
                    data.update(log="WARN local ledger differs from exchange snapshot by USD 1250")
                elif kind == "latency":
                    data.update(
                        fill_latency_ms=650,
                        log="WARN simulated order queue backlog; fill latency rising",
                    )
                elif kind == "ml_degradation":
                    data.update(
                        slippage_bps=6.5,
                        heartbeat_jitter_ms=45,
                        log="WARN slippage and heartbeat jitter drifting",
                    )
                events.append(Telemetry(**data))
        return events

    def proposal(self, incident_id):
        with self.db.Session() as db:
            row = db.get(Incident, incident_id)
            if not row:
                raise KeyError(incident_id)
            result = record(row)
        result["script"] = (
            "# Fixed recovery client; the server checks the incident's allowlisted action.\n"
            "import os, httpx\n"
            f"response = httpx.post('http://127.0.0.1:8000/api/incidents/{incident_id}/approve',\n"
            "    headers={'X-Desk-Token': os.environ['DESK_TOKEN']},\n"
            f"    json={{'action': '{result['action']}', 'actor': 'trader'}})\n"
            "response.raise_for_status()\nprint(response.json())\n"
        )
        result["scope"] = (
            "simulated exchange only"
            if self.settings.simulator
            else "recovery disabled: no real exchange adapter"
        )
        return result

    def approve(self, incident_id, action, actor):
        if not self.settings.simulator:
            raise ValueError(
                "No live exchange adapter is installed; recovery is restricted to simulation"
            )
        with self.lock, self.db.Session.begin() as db:
            row = db.get(Incident, incident_id)
            if not row:
                raise KeyError(incident_id)
            if row.status != "open":
                raise ValueError("Incident was already approved or resolved")
            if action != row.action or action == "inspect_only":
                raise ValueError("Action is not an executable allowlisted proposal")
            if action == "resync_ledger":
                balance = db.get(Balance, "desk-primary")
                before = {
                    "local_nav": str(balance.local_nav),
                    "exchange_nav": str(balance.exchange_nav),
                }
                balance.local_nav = balance.exchange_nav
            else:
                before = {"fault": self.faults.get(row.service)}
            # Only clear the fault that this action addresses, preserving unrelated injected failures.
            matching = {
                "reconnect_feed": {"tick_gap", "silence"},
                "enable_backoff": {"rate_limit"},
                "resync_ledger": {"nav_mismatch"},
                "resync_orders": {"latency"},
            }
            if self.faults.get(row.service) in matching[action]:
                self.faults.pop(row.service, None)
            row.status, row.updated_at = "verifying", now()
            db.add(
                Audit(
                    at=now(),
                    incident_id=incident_id,
                    actor=actor,
                    action=action,
                    detail={
                        "before": before,
                        "scope": "simulation",
                        "awaiting": "fresh healthy telemetry",
                    },
                )
            )
            return {"status": "verifying", "action": action}

    def triage(self, incident_id):
        proposal = self.proposal(incident_id)
        result = self.agent.diagnose(
            {k: proposal[k] for k in ("id", "service", "kind", "diagnosis", "action", "evidence")}
        )
        with self.lock, self.db.Session.begin() as db:
            incident = db.get(Incident, incident_id)
            label = result["provider"].capitalize() + " diagnosis"
            if result.get("fallback_http_status"):
                label += f" (Gemini HTTP {result['fallback_http_status']})"
            incident.report = label + "\n\n" + result["report"]
            db.add(
                Audit(
                    at=now(),
                    incident_id=incident_id,
                    actor="triage-agent",
                    action="diagnosed",
                    detail={
                        "provider": result["provider"],
                        "run_id": result["run_id"],
                        "workflow": result["workflow"],
                        "diagnosis": result["diagnosis"],
                        "tools": result["tool_trace"],
                        "fallback_reason": result.get("fallback_reason"),
                        "fallback_http_status": result.get("fallback_http_status"),
                    },
                )
            )
        return result

    def triage_next(self):
        with self.db.Session() as db:
            pending = db.scalar(
                select(Incident)
                .where(Incident.status == "open", Incident.report == "")
                .order_by(Incident.opened_at)
                .limit(1)
            )
            incident_id = pending.id if pending else None
        if incident_id:
            self.triage(incident_id)

    def snapshot(self):
        # Read-only console queries must not block the ingestion lock across cloud round trips.
        with self.db.Session() as db:
            events = db.scalars(select(Event).order_by(Event.received_at.desc()).limit(180)).all()
            incidents = db.scalars(
                select(Incident)
                .order_by((Incident.status == "resolved").asc(), Incident.opened_at.desc())
                .limit(100)
            ).all()
            audit = db.scalars(select(Audit).order_by(Audit.id.desc()).limit(60)).all()
            grouped = dict(
                db.execute(
                    select(Incident.service, func.count())
                    .where(Incident.status != "resolved")
                    .group_by(Incident.service)
                ).all()
            )
            return {
                "mode": "simulated desk" if self.settings.simulator else "external telemetry",
                "ai_provider": self.settings.ai_provider,
                "database": self.db.engine.dialect.name,
                "tick_gap_seconds": self.settings.tick_gap_seconds,
                "errors": self.errors.copy(),
                "last_ingest": self.last_ingest,
                "open_incident_count": sum(grouped.values()),
                "open_incidents_by_service": {
                    service: grouped.get(service, 0) for service in SERVICES
                },
                "event_count": db.scalar(select(func.count()).select_from(Event)),
                "events": [
                    dict(e.payload, score=float(e.score), received_at=e.received_at)
                    for e in reversed(events)
                ],
                "incidents": [record(i) for i in incidents],
                "audit": [record(a) for a in audit],
                "balances": self.db.reconcile(db),
                "faults": self.faults.copy(),
                "service_age_seconds": {
                    s: round(time.monotonic() - t, 1) for s, t in self.last_seen.items()
                },
            }
