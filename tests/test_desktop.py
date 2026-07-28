from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

import halfreversal.desktop as desktop
from halfreversal.desktop import (
    APP_VERSION,
    DEFAULT_HOSTED_URL,
    DesktopSettings,
    LocalServiceProbe,
    apply_settings,
    dashboard_url,
    load_settings,
    probe_local_service,
    runtime_action,
    save_settings,
    user_data_dir,
    validate_settings,
)

TOKEN = "a" * 64
DATABENTO_KEY = "test-databento-" + "b" * 20


def test_user_data_dir_uses_native_locations(tmp_path: Path) -> None:
    assert user_data_dir("darwin", tmp_path) == (
        tmp_path / "Library" / "Application Support" / "Half-Day Reversal"
    )
    assert user_data_dir("win32", tmp_path, {"APPDATA": "C:/Users/Scott/AppData/Roaming"}) == (
        Path("C:/Users/Scott/AppData/Roaming") / "Half-Day Reversal"
    )


def test_settings_round_trip_with_private_permissions(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    settings = DesktopSettings(
        bridge_token=TOKEN,
        databento_api_key=DATABENTO_KEY,
    )

    save_settings(path, settings)

    assert load_settings(path) == settings
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_settings_validation_rejects_incomplete_keys() -> None:
    with pytest.raises(ValueError, match="at least 32"):
        validate_settings(DesktopSettings(bridge_token="short", databento_api_key=DATABENTO_KEY))


def test_apply_settings_uses_per_user_strategy_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "HOSTED_DASHBOARD_URL",
        "BRIDGE_TOKEN",
        "DATABENTO_API_KEY",
        "HALFREVERSAL_DATA_DIR",
        "IBKR_AUTO_CONNECT",
        "IBKR_LIVE_UNLOCK",
    ):
        monkeypatch.delenv(name, raising=False)
    settings = DesktopSettings(bridge_token=TOKEN, databento_api_key=DATABENTO_KEY)

    apply_settings(settings, tmp_path)

    assert os.environ["HOSTED_DASHBOARD_URL"] == DEFAULT_HOSTED_URL
    assert os.environ["BRIDGE_TOKEN"] == TOKEN
    assert os.environ["DATABENTO_API_KEY"] == DATABENTO_KEY
    assert os.environ["HALFREVERSAL_DATA_DIR"] == str(tmp_path / "strategy")
    assert os.environ["IBKR_AUTO_CONNECT"] == "false"
    assert "IBKR_LIVE_UNLOCK" not in os.environ


def test_dashboard_url_pairs_browser_without_server_query_parameter() -> None:
    settings = DesktopSettings(bridge_token=TOKEN, databento_api_key=DATABENTO_KEY)

    url = dashboard_url(settings)

    assert url.startswith(f"{DEFAULT_HOSTED_URL}/#access=")
    assert "?" not in url


def test_probe_recognizes_current_connector(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        desktop,
        "_read_local_json",
        lambda url: (
            {"product": "half-day-reversal", "version": APP_VERSION}
            if url == desktop.LOCAL_IDENTITY_URL
            else None
        ),
    )

    assert probe_local_service() == LocalServiceProbe(
        running=True,
        is_half_day=True,
        version=APP_VERSION,
    )


def test_probe_recognizes_legacy_connector(monkeypatch: pytest.MonkeyPatch) -> None:
    legacy_status = {
        "connected": False,
        "mode": "dry_run",
        "armed": False,
        "config": {},
        "rankings": [],
        "orders": [],
    }
    monkeypatch.setattr(
        desktop,
        "_read_local_json",
        lambda url: legacy_status if url == desktop.LOCAL_STATUS_URL else None,
    )

    assert probe_local_service() == LocalServiceProbe(
        running=True,
        is_half_day=True,
        version="legacy",
    )


def test_runtime_recovers_offline_legacy_connector() -> None:
    legacy = LocalServiceProbe(running=True, is_half_day=True, version="legacy")

    assert runtime_action(legacy, worker_connected=False) == "recover"
    assert runtime_action(legacy, worker_connected=True) == "existing"


def test_runtime_does_not_duplicate_current_bridge_or_unrelated_service() -> None:
    current = LocalServiceProbe(running=True, is_half_day=True, version=APP_VERSION)
    unrelated = LocalServiceProbe(running=True, is_half_day=False)

    assert runtime_action(current, worker_connected=False) == "existing"
    assert runtime_action(unrelated, worker_connected=False) == "blocked"
    assert runtime_action(LocalServiceProbe(False, False), False) == "start"
