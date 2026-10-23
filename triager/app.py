import asyncio
import hmac
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from . import __version__
from .auth import local_token
from .config import Settings
from .limits import RateLimits
from .models import SERVICES, Telemetry
from .runtime import Desk
from .security import register_secret
from .telemetry import configure_tracing
from .workers import recover_pending, simulate, supervise, triage_pending, watch

STATIC = Path(__file__).parent / "static"


class Injection(BaseModel):
    kind: str
    service: str


class Approval(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: str = Field(min_length=1, max_length=80)
    actor: str = Field(min_length=1, max_length=80)
    proposal_id: str = Field(min_length=1, max_length=80)
    reason: str = Field(default="", max_length=2000)


class Rejection(Approval):
    reason: str = Field(min_length=1, max_length=2000)


def create_app(settings=None):
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app):
        if settings.token is None:
            settings.token, created = local_token(settings.token_file)
            register_secret(settings.token)
            if created:
                print("Local desk access token: " + settings.token, flush=True)
            else:
                print("Using the private token in " + settings.token_file, flush=True)
        tracer_provider = configure_tracing()
        desk = await asyncio.to_thread(Desk, settings)
        app.state.desk = desk
        tasks = [asyncio.create_task(supervise(desk, "watchdog", lambda: watch(desk)))]
        tasks.append(asyncio.create_task(supervise(desk, "triage", lambda: triage_pending(desk))))
        tasks.append(
            asyncio.create_task(supervise(desk, "recovery", lambda: recover_pending(desk)))
        )
        if settings.simulator:

            async def publish(event):
                await asyncio.to_thread(desk.ingest, event)
                desk.errors.pop("simulator", None)

            tasks.append(
                asyncio.create_task(supervise(desk, "simulator", lambda: simulate(desk, publish)))
            )
        yield
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        desk.db.engine.dispose()
        if tracer_provider:
            await asyncio.to_thread(tracer_provider.shutdown)

    app = FastAPI(title="Desk | Execution Anomaly Triager", version=__version__, lifespan=lifespan)
    limits = RateLimits()
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    def authorize(request: Request, x_desk_token: str = Header(default="")):
        limits.check(request.client.host if request.client else "local", request.url.path)
        if not settings.token or not hmac.compare_digest(x_desk_token, settings.token):
            raise HTTPException(401, "Valid X-Desk-Token required")

    @app.get("/")
    def home():
        return FileResponse(STATIC / "index.html")

    @app.get("/health")
    def health():
        desk = app.state.desk
        try:
            with desk.db.Session() as db:
                from sqlalchemy import text

                db.execute(text("SELECT 1"))
        except Exception:
            raise HTTPException(503, "Database unavailable") from None
        if desk.errors:
            raise HTTPException(503, {"workers": desk.errors})
        return {"status": "ok", "mode": "simulation" if settings.simulator else "external"}

    @app.get("/api/snapshot", dependencies=[Depends(authorize)])
    def snapshot():
        return app.state.desk.snapshot()

    @app.post("/api/telemetry", dependencies=[Depends(authorize)])
    def telemetry(event: Telemetry):
        return app.state.desk.ingest(event)

    @app.post("/api/faults", dependencies=[Depends(authorize)])
    def inject(body: Injection):
        if body.service not in SERVICES:
            raise HTTPException(422, "Unknown service")
        try:
            app.state.desk.inject(body.kind, body.service)
            return {"injected": body.kind, "service": body.service}
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None

    @app.get("/api/incidents/{incident_id}", dependencies=[Depends(authorize)])
    def proposal(incident_id: str):
        try:
            return app.state.desk.proposal(incident_id)
        except KeyError:
            raise HTTPException(404, "Incident not found") from None

    @app.post("/api/incidents/{incident_id}/triage", dependencies=[Depends(authorize)])
    def triage(incident_id: str):
        try:
            return app.state.desk.triage(incident_id)
        except KeyError:
            raise HTTPException(404, "Incident not found") from None

    @app.post("/api/incidents/{incident_id}/approve", dependencies=[Depends(authorize)])
    def approve(
        incident_id: str,
        body: Approval,
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=80),
    ):
        try:
            return app.state.desk.approve(
                incident_id, body.action, body.actor, body.proposal_id, idempotency_key, body.reason
            )
        except KeyError:
            raise HTTPException(404, "Incident not found") from None
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None

    @app.post("/api/incidents/{incident_id}/reject", dependencies=[Depends(authorize)])
    def reject(
        incident_id: str,
        body: Rejection,
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=80),
    ):
        try:
            return app.state.desk.reject(
                incident_id, body.action, body.actor, body.proposal_id, idempotency_key, body.reason
            )
        except KeyError:
            raise HTTPException(404, "Incident not found") from None
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None

    return app


app = create_app()
