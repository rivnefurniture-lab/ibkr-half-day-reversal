from __future__ import annotations

import httpx
import pytest

from halfreversal.hosted import app
from halfreversal.version import APP_VERSION


@pytest.mark.asyncio
async def test_hosted_health_and_auth(monkeypatch) -> None:
    monkeypatch.setenv("BRIDGE_TOKEN", "a" * 40)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/health")).json()["ok"] is True
        assert (await client.get("/host/config")).json()["hosted"] is True
        assert (await client.get("/api/status")).status_code == 401
        response = await client.get(
            "/api/status",
            headers={"Authorization": f"Bearer {'a' * 40}"},
        )

    assert response.status_code == 503
    assert "connector is offline" in response.json()["detail"]


@pytest.mark.asyncio
async def test_hosted_dashboard_disables_stale_asset_caching() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store, max-age=0"
    assert f'/static/styles.css?v={APP_VERSION}' in response.text
    assert f'/static/app.js?v={APP_VERSION}' in response.text
    assert "Mac blocked the app?" in response.text
    assert "Open Mac Privacy &amp; Security" in response.text
    assert "installs itself into Applications" in response.text
    assert 'id="loadSettingsMidcaps"' in response.text
