import re
import tomllib
from pathlib import Path

from halfreversal.app import APP_VERSION as API_VERSION
from halfreversal.desktop import APP_VERSION as DESKTOP_VERSION
from halfreversal.hosted import APP_VERSION as HOSTED_VERSION
from halfreversal.version import APP_VERSION

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_all_runtime_surfaces_share_one_version() -> None:
    project = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text())
    windows_installer = (PROJECT_ROOT / "packaging" / "windows.iss").read_text()
    windows_version = re.search(r'#define MyAppVersion "([^"]+)"', windows_installer)

    assert project["project"]["version"] == APP_VERSION
    assert windows_version is not None
    assert windows_version.group(1) == APP_VERSION
    assert API_VERSION == APP_VERSION
    assert DESKTOP_VERSION == APP_VERSION
    assert HOSTED_VERSION == APP_VERSION
