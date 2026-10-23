"""Native approval interrupts and a transactional SQL recovery outbox.

Graph checkpoints record workflow progress. SQL independently authorizes and deduplicates
execution, including replay after a crash between SQL commit and checkpoint persistence.
"""

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import TypedDict
from uuid import uuid4

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from sqlalchemy import or_, select, update

from .models import Audit, Balance, Incident, RecoveryJob, RecoveryProposal, SimulatorFault, now
from .security import action_policy, sanitize


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class ApprovalState(TypedDict, total=False):
    proposal_id: str
    payload: dict
    decision: dict
    result: dict


class Recovery:
    def __init__(self, desk):
        self.desk = desk
        self.db = desk.db
        self.path = desk.agent.checkpoint_path + ".approval.sqlite3"

    def graph(self, saver):
        def review(state):
            decision = interrupt(
                {"proposal_id": state["proposal_id"], "proposal": state["payload"]}
            )
            if decision["proposal_id"] != state["proposal_id"]:
                raise ValueError("Approval does not match interrupted proposal")
            return {"decision": decision}

        def record(state):
            return {"result": self.record_decision(state["decision"])}

        graph = StateGraph(ApprovalState)
        graph.add_node("human_review", review)
        graph.add_node("record_decision", record)
        graph.add_edge(START, "human_review")
        graph.add_edge("human_review", "record_decision")
        graph.add_edge("record_decision", END)
        return graph.compile(checkpointer=saver)

    @staticmethod
    def config(proposal_id):
        return {"configurable": {"thread_id": "approval:" + proposal_id}}

    def payload(self, session, incident):
        fault = session.get(SimulatorFault, incident.service)
        balance = (
            session.get(Balance, "desk-primary") if incident.action == "resync_ledger" else None
        )
        return {
            "incident_id": incident.id,
            "service": incident.service,
            "kind": incident.kind,
            "action": incident.action,
            "report_hash": digest(incident.report),
            "policy": action_policy(
                {"action": incident.action, "target": incident.service},
                incident_service=incident.service,
                incident_kind=incident.kind,
                simulator=self.desk.settings.simulator,
            ).model_dump(),
            "fault_generation": fault.generation if fault else None,
            "balance": {"local": str(balance.local_nav), "exchange": str(balance.exchange_nav)}
            if balance
            else None,
        }

    def prepare(self, incident_id):
        with self.desk.lock:
            return self._prepare(incident_id)

    def _prepare(self, incident_id):
        with self.desk.lock, self.db.Session.begin() as session:
            incident = session.get(Incident, incident_id)
            if not incident:
                raise KeyError(incident_id)
            payload = self.payload(session, incident)
            fingerprint = digest(payload)
            proposal = session.scalar(
                select(RecoveryProposal)
                .where(
                    RecoveryProposal.incident_id == incident_id,
                    RecoveryProposal.fingerprint == fingerprint,
                    RecoveryProposal.status.in_(["pending", "approved", "rejected"]),
                )
                .order_by(RecoveryProposal.created_at.desc())
                .limit(1)
            )
            if incident.status != "open":
                proposal = session.scalar(
                    select(RecoveryProposal)
                    .where(RecoveryProposal.incident_id == incident_id)
                    .order_by(RecoveryProposal.created_at.desc())
                    .limit(1)
                )
            if not proposal and incident.status == "open":
                session.execute(
                    update(RecoveryProposal)
                    .where(
                        RecoveryProposal.incident_id == incident_id,
                        RecoveryProposal.status == "pending",
                    )
                    .values(status="superseded")
                )
                proposal = RecoveryProposal(
                    id=str(uuid4()),
                    incident_id=incident_id,
                    fingerprint=fingerprint,
                    payload=payload,
                    created_at=now(),
                    status="pending",
                )
                session.add(proposal)
            if not proposal:
                return None
            result = {
                "id": proposal.id,
                "fingerprint": proposal.fingerprint,
                "status": proposal.status,
                "payload": proposal.payload,
            }
        # SQL creation and checkpoint creation are repairable, not one transaction.
        if result["status"] == "pending":
            with SqliteSaver.from_conn_string(self.path) as saver:
                graph = self.graph(saver)
                if not graph.get_state(self.config(result["id"])).values:
                    graph.invoke(
                        {"proposal_id": result["id"], "payload": result["payload"]},
                        self.config(result["id"]),
                    )
        return result

    @staticmethod
    def response(job):
        return {
            "status": job.status,
            "execution_id": job.id,
            "proposal_id": job.proposal_id,
            "decision": job.decision,
            "attempts": job.attempts,
            "result": job.result,
        }

    def decide(self, incident_id, action, actor, proposal_id, key, *, approved=True, reason=""):
        if not key or not 8 <= len(key) <= 80:
            raise ValueError("Idempotency key must contain 8..80 characters")
        decision = sanitize(
            {
                "incident_id": incident_id,
                "action": action,
                "actor": actor,
                "proposal_id": proposal_id,
                "approved": approved,
                "reason": reason,
            }
        )
        if not actor.strip() or len(actor) > 80 or len(reason) > 2000:
            raise ValueError("Invalid actor or reason")
        if not approved and not reason.strip():
            raise ValueError("Rejection requires a reason")
        decision["key_hash"] = digest(key)
        decision["request_hash"] = digest(decision)
        with self.desk.lock:
            with self.db.Session() as session:
                existing = session.scalar(
                    select(RecoveryJob).where(RecoveryJob.key_hash == decision["key_hash"])
                )
                if existing:
                    if existing.request_hash != decision["request_hash"]:
                        raise ValueError("Idempotency key reused with different request")
                    return self.response(existing)
                proposal = session.get(RecoveryProposal, proposal_id)
                if not proposal or proposal.incident_id != incident_id:
                    raise ValueError("Unknown proposal for this incident")
                if proposal.status != "pending":
                    raise ValueError("Proposal already decided or superseded")
                incident = session.get(Incident, incident_id)
                if not incident or incident.status != "open":
                    raise ValueError("Incident is no longer awaiting approval")
                if action != proposal.payload["action"]:
                    raise ValueError("Action does not match reviewed proposal")
                if digest(self.payload(session, incident)) != proposal.fingerprint:
                    raise ValueError("Proposal changed; review the latest version")
                if approved and proposal.payload["policy"]["disposition"] != "requires_approval":
                    raise ValueError("Policy blocks execution")
            with SqliteSaver.from_conn_string(self.path) as saver:
                graph = self.graph(saver)
                config = self.config(proposal_id)
                if not graph.get_state(config).values:
                    # Recover an interrupt whose SQL proposal survived a checkpoint outage.
                    with self.db.Session() as session:
                        payload = session.get(RecoveryProposal, proposal_id).payload
                    graph.invoke({"proposal_id": proposal_id, "payload": payload}, config)
                return graph.invoke(Command(resume=decision), config)["result"]

    def record_decision(self, decision):
        with self.db.Session.begin() as session:
            prior = session.scalar(
                select(RecoveryJob).where(RecoveryJob.key_hash == decision["key_hash"])
            )
            if prior:
                if prior.request_hash != decision["request_hash"]:
                    raise ValueError("Idempotency key reused with different request")
                return self.response(prior)
            proposal = session.get(RecoveryProposal, decision["proposal_id"])
            incident = session.get(Incident, decision["incident_id"])
            if not proposal or not incident or proposal.incident_id != incident.id:
                raise ValueError("Proposal scope mismatch")
            if proposal.status != "pending" or incident.status != "open":
                raise ValueError("Proposal is no longer pending")
            if decision["action"] != proposal.payload["action"]:
                raise ValueError("Action does not match reviewed proposal")
            if digest(self.payload(session, incident)) != proposal.fingerprint:
                raise ValueError("Proposal changed; review the latest version")
            if (
                decision["approved"]
                and proposal.payload["policy"]["disposition"] != "requires_approval"
            ):
                raise ValueError("Policy blocks execution")
            job = RecoveryJob(
                id=str(uuid4()),
                proposal_id=proposal.id,
                incident_id=incident.id,
                key_hash=decision["key_hash"],
                request_hash=decision["request_hash"],
                actor=decision["actor"],
                reason=decision["reason"],
                decision="approved" if decision["approved"] else "rejected",
                status="queued" if decision["approved"] else "rejected",
                created_at=now(),
                result={},
                attempts=0,
            )
            session.add(job)
            proposal.status = job.decision
            if decision["approved"]:
                incident.status, incident.updated_at = "queued", now()
            session.add(
                Audit(
                    at=now(),
                    incident_id=incident.id,
                    actor=job.actor,
                    action="approval_queued" if decision["approved"] else "rejected",
                    detail={
                        "proposal_id": proposal.id,
                        "execution_id": job.id,
                        "reason": job.reason,
                        "policy": proposal.payload["policy"],
                    },
                )
            )
            return self.response(job)

    def execute_next(self):
        current = now()
        token = str(uuid4())
        with self.desk.lock:
            with self.db.Session.begin() as session:
                candidate = session.scalar(
                    select(RecoveryJob.id)
                    .where(
                        or_(
                            RecoveryJob.status == "queued",
                            (RecoveryJob.status == "running") & (RecoveryJob.lease_until < current),
                        )
                    )
                    .order_by(RecoveryJob.created_at)
                    .limit(1)
                )
                if not candidate:
                    return None
                claimed = session.execute(
                    update(RecoveryJob)
                    .where(
                        RecoveryJob.id == candidate,
                        or_(
                            RecoveryJob.status == "queued",
                            (RecoveryJob.status == "running") & (RecoveryJob.lease_until < current),
                        ),
                    )
                    .values(
                        status="running",
                        lease_token=token,
                        lease_until=(
                            datetime.now(timezone.utc) + timedelta(seconds=30)
                        ).isoformat(),
                        attempts=RecoveryJob.attempts + 1,
                    )
                )
                if claimed.rowcount != 1:
                    return None
            try:
                with self.db.Session.begin() as session:
                    job = session.scalar(
                        select(RecoveryJob)
                        .where(
                            RecoveryJob.id == candidate,
                            RecoveryJob.status == "running",
                            RecoveryJob.lease_token == token,
                        )
                        .with_for_update()
                    )
                    if not job:
                        return None
                    incident = session.get(Incident, job.incident_id)
                    proposal = session.get(RecoveryProposal, job.proposal_id)
                    # SQL policy and preconditions rechecked at execution time, not model time.
                    if (
                        incident.status != "queued"
                        or digest(self.payload(session, incident)) != proposal.fingerprint
                    ):
                        raise ValueError("Execution preconditions changed")
                    if proposal.status != "approved" or job.decision != "approved":
                        raise ValueError("Execution lacks an approved decision")
                    before = {}
                    if incident.action == "resync_ledger":
                        balance = session.get(Balance, "desk-primary")
                        if not balance:
                            raise ValueError("Missing simulation balance")
                        before = {
                            "local_nav": str(balance.local_nav),
                            "exchange_nav": str(balance.exchange_nav),
                        }
                        balance.local_nav = balance.exchange_nav
                    fault = session.get(SimulatorFault, incident.service)
                    matching = {
                        "reconnect_feed": {"tick_gap", "silence"},
                        "enable_backoff": {"rate_limit"},
                        "resync_orders": {"latency"},
                        "resync_ledger": {"nav_mismatch"},
                    }
                    if fault and fault.kind in matching[incident.action]:
                        before["fault"] = fault.kind
                        session.delete(fault)
                    incident.status, incident.updated_at = "verifying", now()
                    job.status, job.lease_until = "succeeded", None
                    job.result = {"status": "verifying", "action": incident.action}
                    job.verification_deadline = (
                        datetime.now(timezone.utc)
                        + timedelta(seconds=self.desk.settings.verification_timeout_seconds)
                    ).isoformat()
                    session.add(
                        Audit(
                            at=now(),
                            incident_id=incident.id,
                            actor=job.actor,
                            action=incident.action,
                            detail={
                                "before": before,
                                "scope": "simulation",
                                "execution_id": job.id,
                                "policy": proposal.payload["policy"],
                                "awaiting": "fresh healthy telemetry",
                            },
                        )
                    )
            except Exception as exc:
                with self.db.Session.begin() as session:
                    job = session.get(RecoveryJob, candidate)
                    # Preconditions are terminal. Transient failures retry at most three times.
                    terminal = isinstance(exc, ValueError) or job.attempts >= 3
                    job.status, job.lease_until = ("failed" if terminal else "queued"), None
                    job.result = {"error": type(exc).__name__}
                    if terminal:
                        incident = session.get(Incident, job.incident_id)
                        incident.status, incident.updated_at = "failed", now()
                    session.add(
                        Audit(
                            at=now(),
                            incident_id=job.incident_id,
                            actor="recovery-worker",
                            action="execution_failed" if terminal else "execution_retry",
                            detail={"execution_id": job.id, "error": type(exc).__name__},
                        )
                    )
            self.desk.load_faults()
            with self.db.Session() as session:
                return self.response(session.get(RecoveryJob, candidate))
