import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

project_root = Path(SPECPATH).parent
datas = [(str(project_root / "static"), "static")]
datas += collect_data_files("exchange_calendars")
datas += collect_data_files("databento")
hiddenimports = (
    collect_submodules("halfreversal")
    + collect_submodules("databento")
    + collect_submodules("ib_async")
)

a = Analysis(
    [str(project_root / "halfreversal" / "desktop.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "ruff"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Half-Day Reversal Connector",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
)
bundle = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    name="Half-Day Reversal Connector",
)

if sys.platform == "darwin":
    app = BUNDLE(
        bundle,
        name="Half-Day Reversal Connector.app",
        bundle_identifier="com.halfday.reversal.connector",
        info_plist={
            "CFBundleDisplayName": "Half-Day Reversal Connector",
            "CFBundleShortVersionString": "1.2.4",
            "NSHighResolutionCapable": True,
        },
    )
