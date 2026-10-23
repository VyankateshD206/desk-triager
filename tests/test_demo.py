import asyncio

import pytest
from fastapi.testclient import TestClient

from demo.app import Lab, create_app


def test_fault_control_requires_auth_and_records_deployments(monkeypatch):
    monkeypatch.setenv("DEMO_TOKEN", "test-token")
    app = create_app(background=False)
    with TestClient(app) as client:
        assert client.post("/faults", json={"kind": "bad_deploy"}).status_code == 401
        headers = {"X-Demo-Token": "test-token"}
        assert (
            client.post("/faults", headers=headers, json={"kind": "bad_deploy"}).status_code == 200
        )
        diff = client.get(
            "/deployments/latest/diff", params={"service": "execution-gateway"}
        ).json()
        assert diff["deployment"]["version"] == "1.1-bad"
        assert client.post("/faults", headers=headers, json={"kind": "healthy"}).status_code == 200
        history = client.get("/deployments", params={"service": "execution-gateway"}).json()
        assert len(history["deployments"]) == 3
        assert "Revert" in history["deployments"][-1]["diff"]
        assert (
            client.get("/deployments", params={"service": "market-feed"}).json()["deployments"]
            == []
        )
        assert (
            client.post("/faults", headers=headers, json={"kind": "run_shell"}).status_code == 422
        )
        assert 'demo_sql_duration_ms{service="execution-gateway"}' in client.get("/metrics").text


@pytest.mark.parametrize("kind", ["slow_query", "memory_pressure", "bad_deploy", "rate_limit"])
def test_faults_produce_distinct_evidence_and_recover(kind):
    lab = Lab()
    lab.inject(kind)
    sample = asyncio.run(lab.sample())
    if kind == "rate_limit":
        assert sample["reject_code"] == "429"
    else:
        assert sample["fill_latency_ms"] > 350
    if kind == "slow_query":
        assert lab.metrics["sql_duration_ms"] >= 600
    if kind == "memory_pressure":
        assert lab.metrics["memory_bytes"] == 1024 * 1024
    if kind == "bad_deploy":
        assert "deployment" in sample["log"]
    lab.inject("healthy")
    healthy = asyncio.run(lab.sample())
    assert healthy["reject_code"] == "OK"
    assert healthy["fill_latency_ms"] < 350
    assert lab.metrics["memory_bytes"] == 0


def test_memory_pressure_is_bounded():
    async def exercise():
        lab = Lab()
        lab.inject("memory_pressure")
        for _ in range(18):
            await lab.sample()
        assert lab.metrics["memory_bytes"] == 16 * 1024 * 1024

    asyncio.run(exercise())
