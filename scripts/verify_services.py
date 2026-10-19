"""Exercise configured Neon persistence and Gemini diagnosis through the running app.

Creates one simulated rate-limit incident, approves its recovery, and retains the
resolved incident and audit trail. Does not print credentials or provider responses.
"""

import sys
import time
from urllib.parse import urlsplit

import httpx
from sqlalchemy import select, text

from triager.config import Settings
from triager.db import Database
from triager.models import Audit, Incident


class VerificationError(RuntimeError):
    """Safe, locally authored verification failure message."""


def verify(base_url="http://127.0.0.1:8000"):
    if urlsplit(base_url).hostname not in {"127.0.0.1", "localhost"}:
        raise VerificationError("Verification targets the local application only")
    settings = Settings()
    database = Database(settings.database_url)
    try:
        if database.engine.dialect.name != "postgresql":
            raise VerificationError("Configure Neon DATABASE_URL before live verification")
        with database.engine.connect() as db:
            db.execute(text("SELECT 1"))
            encrypted = bool(db.connection.driver_connection.pgconn.ssl_in_use)
        if not encrypted:
            raise VerificationError("Database connection must use TLS")
        print("PASS Neon PostgreSQL: SELECT 1; TLS=true", flush=True)
        with httpx.Client(
            base_url=base_url, headers={"X-Desk-Token": settings.token}, timeout=30
        ) as client:

            def request(method, path, **kwargs):
                response = client.request(method, path, **kwargs)
                response.raise_for_status()
                return response.json()

            snapshot = request("GET", "/api/snapshot")
            if snapshot["database"] != "postgresql" or snapshot["mode"] != "simulated desk":
                raise VerificationError(
                    "Start the application against Neon with simulation enabled"
                )
            request(
                "POST", "/api/faults", json={"kind": "rate_limit", "service": "execution-gateway"}
            )
            deadline = time.monotonic() + 75
            incident = diagnosis = None
            while time.monotonic() < deadline:
                snapshot = request("GET", "/api/snapshot")
                incident = next(
                    (
                        i
                        for i in snapshot["incidents"]
                        if i["service"] == "execution-gateway"
                        and i["kind"] == "rate_limit"
                        and i["status"] == "open"
                    ),
                    None,
                )
                if incident:
                    diagnosis = next(
                        (
                            a["detail"]
                            for a in snapshot["audit"]
                            if a["incident_id"] == incident["id"] and a["action"] == "diagnosed"
                        ),
                        None,
                    )
                    if diagnosis:
                        break
                time.sleep(1)
            if not incident or not diagnosis:
                raise VerificationError("Timed out waiting for incident diagnosis")
            print("PASS Incident detection: persisted rate-limit incident", flush=True)
            gemini_ok = diagnosis["provider"] == "gemini"
            if gemini_ok:
                print("PASS Gemini: live REST diagnosis persisted", flush=True)
            else:
                print(
                    f"FAIL Gemini: offline fallback ({diagnosis.get('fallback_reason')}; HTTP {diagnosis.get('fallback_http_status')})",
                    flush=True,
                )
            proposal = request("GET", "/api/incidents/" + incident["id"])
            result = request(
                "POST",
                f"/api/incidents/{incident['id']}/approve",
                json={"action": proposal["action"], "actor": "service-verification"},
            )
            if result["status"] != "verifying":
                raise VerificationError("Approval did not enter verification")
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                current = request("GET", "/api/incidents/" + incident["id"])
                if current["status"] == "resolved":
                    break
                time.sleep(0.5)
            else:
                raise VerificationError("Recovery was not verified")
            print("PASS Recovery: open -> verifying -> resolved", flush=True)
            with database.Session() as db:
                stored = db.get(Incident, incident["id"])
                audit = list(db.scalars(select(Audit).where(Audit.incident_id == incident["id"])))
                if stored.status != "resolved" or not {
                    "opened",
                    "diagnosed",
                    "enable_backoff",
                    "resolved",
                }.issubset({a.action for a in audit}):
                    raise VerificationError("Persisted incident or audit verification failed")
            print(
                "PASS Neon persistence: independent SQL read confirms resolved incident + approval audit",
                flush=True,
            )
            return 0 if gemini_ok else 1
    finally:
        database.engine.dispose()


if __name__ == "__main__":
    try:
        sys.exit(verify(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"))
    except Exception as exc:
        if isinstance(exc, VerificationError):
            print(f"Service verification failed: {exc}", flush=True)
        elif isinstance(exc, httpx.HTTPStatusError):
            print(
                f"Service verification failed: application HTTP {exc.response.status_code}",
                flush=True,
            )
        else:
            print(
                f"Service verification failed ({type(exc).__name__}); credentials and provider responses withheld",
                flush=True,
            )
        sys.exit(1)
