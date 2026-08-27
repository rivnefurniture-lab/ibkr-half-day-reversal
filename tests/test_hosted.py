from __future__ import annotations

from datetime import date

import httpx
import pytest

from halfreversal import hosted
from halfreversal.hosted import app
from halfreversal.models import MidcapUniverse
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
    assert f'/static/styles.css?v={APP_VERSION}.2' in response.text
    assert f'/static/app.js?v={APP_VERSION}.2' in response.text
    assert "Mac blocked the app?" in response.text
    assert "Open Mac Privacy &amp; Security" in response.text
    assert "installs itself into Applications" in response.text
    assert 'id="loadSettingsMidcaps"' in response.text
    assert "Use current S&amp;P 600 for live scans" in response.text
    assert "Keep your existing connector" in response.text
    assert "Use 1.00 for 100% or 0.10 for 10%." in response.text


@pytest.mark.asyncio
async def test_hosted_universe_load_does_not_require_connector(monkeypatch) -> None:
    monkeypatch.setenv("BRIDGE_TOKEN", "a" * 40)

    async def fake_load(index: str) -> MidcapUniverse:
        assert index == "smallcap600"
        return MidcapUniverse(
            source="test S&P 600",
            as_of=date(2026, 8, 21),
            symbol_count=2,
            symbols=["AA", "BB"],
        )

    monkeypatch.setattr(hosted, "load_index_universe", fake_load)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/host/universe?index=smallcap600",
            headers={"Authorization": f"Bearer {'a' * 40}"},
        )

    assert response.status_code == 200
    assert response.json()["symbols"] == ["AA", "BB"]
