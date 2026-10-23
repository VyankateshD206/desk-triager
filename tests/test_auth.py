import asyncio
import os

import httpx
import pytest

from triager.app import create_app
from triager.auth import local_token
from triager.config import Settings
from triager.security import redact_text


def test_private_token_is_random_and_reused(tmp_path):
    path = tmp_path / "token"
    token, created = local_token(path)
    assert created and len(token) == 43
    assert local_token(path) == (token, False)
    assert local_token(tmp_path / "other")[0] != token
    if os.name == "posix":
        assert path.stat().st_mode & 0o777 == 0o600


def test_unsafe_or_invalid_token_file_is_rejected(tmp_path):
    path = tmp_path / "token"
    path.write_text("bad")
    path.chmod(0o600)
    with pytest.raises(ValueError, match="Invalid"):
        local_token(path)
    path.chmod(0o644)
    if os.name == "posix":
        with pytest.raises(ValueError, match="private"):
            local_token(path)
    link = tmp_path / "link"
    link.symlink_to(path)
    with pytest.raises((OSError, ValueError)):
        local_token(link)


def test_bootstrap_auth_rejects_old_default_and_redacts_new_token(tmp_path, capsys):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path}/desk.db",
        token=None,
        token_file=str(tmp_path / "token"),
        simulator=False,
        ai_provider="offline",
    )
    app = create_app(settings)

    async def check():
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                assert (
                    await client.get(
                        "/api/snapshot", headers={"X-Desk-Token": "local-access-token"}
                    )
                ).status_code == 401
                assert (
                    await client.get("/api/snapshot", headers={"X-Desk-Token": settings.token})
                ).status_code == 200
                assert redact_text("token " + settings.token) == "token [REDACTED]"

    asyncio.run(check())
    assert settings.token in capsys.readouterr().out


def test_explicit_token_does_not_create_bootstrap_file(tmp_path, capsys):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path}/explicit.db",
        simulator=False,
        ai_provider="offline",
        token="explicit-test-token",
        token_file=str(tmp_path / "unused"),
    )
    app = create_app(settings)

    async def check():
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                assert (
                    await client.get(
                        "/api/snapshot", headers={"X-Desk-Token": "explicit-test-token"}
                    )
                ).status_code == 200

    asyncio.run(check())
    assert not (tmp_path / "unused").exists()
    assert "explicit-test-token" not in capsys.readouterr().out
