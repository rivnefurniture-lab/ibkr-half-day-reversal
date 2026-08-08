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
    install_and_relaunch_macos,
    install_macos_app,
    load_settings,
    macos_app_bundle,
    macos_app_needs_install,
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


def test_macos_bundle_and_install_location_detection() -> None:
    translocated = Path(
        "/private/var/folders/demo/AppTranslocation/ABC/d/"
        "Half-Day Reversal Connector.app/Contents/MacOS/Half-Day Reversal Connector"
    )
    installed = Path(
        "/Applications/Half-Day Reversal Connector.app/Contents/MacOS/"
        "Half-Day Reversal Connector"
    )

    assert macos_app_bundle(translocated) == Path(
        "/private/var/folders/demo/AppTranslocation/ABC/d/Half-Day Reversal Connector.app"
    )
    translocated_bundle = macos_app_bundle(translocated)
    installed_bundle = macos_app_bundle(installed)
    assert translocated_bundle is not None
    assert installed_bundle is not None
    assert macos_app_needs_install(translocated_bundle)
    assert not macos_app_needs_install(installed_bundle)


def test_install_macos_app_copies_bundle_with_ditto(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "download" / "Half-Day Reversal Connector.app"
    applications = tmp_path / "Applications"
    calls: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: object) -> None:
        calls.append(command)

    monkeypatch.setattr(desktop.subprocess, "run", fake_run)

    target = install_macos_app(source, applications)

    assert target == applications / "Half-Day Reversal Connector.app"
    assert calls == [
        [
            "/usr/bin/ditto",
            "--rsrc",
            "--extattr",
            str(source),
            str(target),
        ]
    ]


def test_dmg_launch_installs_and_relaunches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = Path(
        "/Volumes/Half-Day Reversal/Half-Day Reversal Connector.app/Contents/MacOS/"
        "Half-Day Reversal Connector"
    )
    installed = tmp_path / "Applications" / "Half-Day Reversal Connector.app"
    install_calls: list[tuple[Path, Path]] = []
    launch_calls: list[list[str]] = []

    monkeypatch.setattr(desktop.sys, "platform", "darwin")
    monkeypatch.setattr(desktop.sys, "frozen", True, raising=False)
    monkeypatch.setattr(desktop.sys, "executable", str(source))
    monkeypatch.setattr(desktop.Path, "home", lambda: tmp_path)

    def fake_install(bundle: Path, applications_dir: Path) -> Path:
        install_calls.append((bundle, applications_dir))
        return installed

    def fake_popen(command: list[str], **kwargs: object) -> object:
        launch_calls.append(command)
        return object()

    monkeypatch.setattr(desktop, "install_macos_app", fake_install)
    monkeypatch.setattr(desktop.subprocess, "Popen", fake_popen)

    assert install_and_relaunch_macos(desktop.logging.getLogger("test"))
    assert install_calls == [(macos_app_bundle(source), Path("/Applications"))]
    assert launch_calls == [["/usr/bin/open", "-n", str(installed)]]


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
