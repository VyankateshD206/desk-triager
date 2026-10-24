import asyncio

import httpx

from triager.app import create_app
from triager.config import Settings


def test_local_api_connects_without_token_and_keeps_request_validation(
    tmp_path, monkeypatch, capsys
):
    # Old deployment variables do not reintroduce a credential or token-file requirement.
    legacy_file = tmp_path / "unused-token"
    monkeypatch.setenv("DESK_TOKEN", "obsolete-test-token")
    monkeypatch.setenv("DESK_TOKEN_FILE", str(legacy_file))
    settings = Settings(
        database_url=f"sqlite:///{tmp_path}/desk.db",
        graph_checkpoint_path=str(tmp_path / "graph.db"),
        simulator=False,
        ai_provider="offline",
    )
    app = create_app(settings)

    async def check():
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                page = await client.get("/")
                assert page.status_code == 200
                assert page.headers["cache-control"] == "no-cache"
                for asset in ("app.js", "investigation.js", "style.css"):
                    response = await client.get("/static/" + asset + "?v=37a3611")
                    assert response.status_code == 200
                    assert response.headers["cache-control"] == "no-cache"
                assert 'id="token"' not in page.text
                assert (await client.get("/api/snapshot")).status_code == 200
                assert (await client.post("/api/telemetry", json={})).status_code == 422
                # Approval is still an explicit request with a bound proposal and retry key.
                assert (
                    await client.post("/api/incidents/missing/approve", json={"actor": "operator"})
                ).status_code == 422
                schema = (await client.get("/openapi.json")).json()
                for route in schema["paths"].values():
                    for operation in route.values():
                        assert all(
                            p["name"] != "x-desk-token" for p in operation.get("parameters", [])
                        )

    asyncio.run(check())
    assert not legacy_file.exists()
    assert "obsolete-test-token" not in capsys.readouterr().out
