"""Bounded fault laboratory. All orders, balances, and deployments are simulated."""

import asyncio
import hmac
import json
import os
import sqlite3
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

Fault = Literal["healthy", "slow_query", "memory_pressure", "bad_deploy", "rate_limit"]
SERVICE = "execution-gateway"


def timestamp():
    return datetime.now(timezone.utc).isoformat()


class Lab:
    def __init__(self):
        self.fault = "healthy"
        self.memory = []
        self.metrics = {
            "fill_latency_ms": 85.0,
            "sql_duration_ms": 0.0,
            "memory_bytes": 0,
            "error_ratio": 0.0,
        }
        self.deployments = [
            {
                "id": "demo-v1",
                "version": "1.0",
                "at": timestamp(),
                "diff": "Initial simulated order routing; bounded retry pacing.",
            }
        ]
        self.delivery_errors = {}
        self.latest_event = None

    def inject(self, kind):
        previous = self.fault
        self.fault = kind
        if kind != "memory_pressure":
            self.memory.clear()
        if kind == "bad_deploy" or previous == "bad_deploy":
            self.deployments.append(
                {
                    "id": "demo-" + str(uuid4()),
                    "version": "1.1-bad" if kind == "bad_deploy" else "1.0",
                    "at": timestamp(),
                    "diff": (
                        "order-routing retry delay: 0ms -> 650ms"
                        if kind == "bad_deploy"
                        else "Revert order-routing retry delay: 650ms -> 0ms"
                    ),
                }
            )
            self.deployments = self.deployments[-10:]

    @staticmethod
    def sql_request(slow):
        start = time.perf_counter()
        with sqlite3.connect(":memory:") as db:
            # Controlled query latency, not a database resource exhaustion attack.
            db.create_function("demo_delay", 1, lambda seconds: time.sleep(seconds) or 1)
            db.execute("SELECT demo_delay(?)", (0.6 if slow else 0.0,)).fetchone()
        return (time.perf_counter() - start) * 1000

    async def sample(self):
        kind = self.fault
        sql_ms = await asyncio.to_thread(self.sql_request, kind == "slow_query")
        latency = 85 + sql_ms
        message, reject = "heartbeat healthy", "OK"
        if kind == "slow_query":
            message = "WARN order queue backlog; database SELECT demo_delay took over 600ms"
        elif kind == "memory_pressure":
            if len(self.memory) < 16:
                self.memory.append(bytearray(1024 * 1024))
            latency += 450
            message = (
                "WARN order queue backlog; retained buffers growing; bounded resource pressure"
            )
        elif kind == "bad_deploy":
            await asyncio.sleep(0.65)
            latency += 650
            message = (
                "WARN order queue backlog; routing retry delay regressed after deployment 1.1-bad"
            )
        elif kind == "rate_limit":
            reject = "429"
            message = "WARN simulated exchange HTTP 429; retry-after 5s"
        self.metrics = {
            "fill_latency_ms": latency,
            "sql_duration_ms": sql_ms,
            "memory_bytes": sum(len(chunk) for chunk in self.memory),
            "error_ratio": 1.0 if kind in {"bad_deploy", "rate_limit"} else 0.0,
        }
        event = {
            "event_id": str(uuid4()),
            "timestamp": timestamp(),
            "service": SERVICE,
            "fill_latency_ms": latency,
            "slippage_bps": 1.2,
            "heartbeat_jitter_ms": 12,
            "reject_code": reject,
            "log": message,
        }
        self.latest_event = event
        return event

    async def run(self):
        triager = os.getenv("TRIAGER_URL", "http://triager:8000")
        loki = os.getenv("LOKI_URL", "http://loki:3100")
        async with httpx.AsyncClient(timeout=3) as client:

            async def deliver(name, url, **kwargs):
                try:
                    response = await client.post(url, **kwargs)
                    response.raise_for_status()
                    self.delivery_errors.pop(name, None)
                except httpx.HTTPError as exc:
                    self.delivery_errors[name] = type(exc).__name__

            while True:
                event = await self.sample()
                events = [event] + [
                    {
                        **event,
                        "event_id": str(uuid4()),
                        "service": service,
                        "fill_latency_ms": 85,
                        "reject_code": "OK",
                        "log": "heartbeat healthy",
                    }
                    for service in ["market-feed", "portfolio-ledger"]
                ]
                line = json.dumps(
                    {
                        "message": event["log"],
                        "event_id": event["event_id"],
                        "deployment": self.deployments[-1]["version"],
                    }
                )
                print(line, flush=True)
                await asyncio.gather(
                    deliver(
                        "loki",
                        loki + "/loki/api/v1/push",
                        json={
                            "streams": [
                                {
                                    "stream": {"service": SERVICE, "app": "desk-demo"},
                                    "values": [[str(time.time_ns()), line]],
                                }
                            ]
                        },
                    ),
                    *[
                        deliver(
                            "telemetry:" + e["service"],
                            triager + "/api/telemetry",
                            json=e,
                            headers={"X-Desk-Token": os.getenv("DESK_TOKEN", "local-access-token")},
                        )
                        for e in events
                    ],
                )
                await asyncio.sleep(1)


def create_app(background=True):
    lab = Lab()

    @asynccontextmanager
    async def lifespan(app):
        task = asyncio.create_task(lab.run()) if background else None
        yield
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    app = FastAPI(title="Simulated execution service", lifespan=lifespan)
    app.state.lab = lab

    class Injection(BaseModel):
        kind: Fault

    def authorize(x_demo_token: str = Header(default="")):
        expected = os.getenv("DEMO_TOKEN", "local-demo-token")
        if not expected or not hmac.compare_digest(x_demo_token, expected):
            raise HTTPException(401, "Valid X-Demo-Token required")

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "scope": "simulation",
            "fault": lab.fault,
            "delivery_errors": lab.delivery_errors,
            "latest_event": lab.latest_event,
        }

    @app.post("/faults", dependencies=[Depends(authorize)])
    def inject(body: Injection):
        lab.inject(body.kind)
        return {"fault": lab.fault, "scope": "simulation"}

    @app.get("/metrics", response_class=PlainTextResponse)
    def metrics():
        return "".join(
            f'# TYPE demo_{name} gauge\ndemo_{name}{{service="{SERVICE}"}} {value}\n'
            for name, value in lab.metrics.items()
        )

    @app.get("/deployments")
    def deployments(service: str):
        return {"service": service, "deployments": lab.deployments if service == SERVICE else []}

    @app.get("/deployments/latest/diff")
    def diff(service: str):
        return {
            "service": service,
            "deployment": lab.deployments[-1] if service == SERVICE else None,
        }

    return app


app = create_app()
