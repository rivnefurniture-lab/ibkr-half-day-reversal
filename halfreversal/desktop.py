from __future__ import annotations

import asyncio
import json
import logging
import os
import platform
import plistlib
import queue
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from dataclasses import asdict, dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path
from tkinter import BooleanVar, StringVar, Tk, messagebox, ttk
from urllib.parse import quote

import certifi

from .version import APP_VERSION

DEFAULT_HOSTED_URL = "https://half-day-reversal-production.up.railway.app"
APP_FOLDER = "Half-Day Reversal"
LOCAL_BASE_URL = "http://127.0.0.1:8765"
LOCAL_IDENTITY_URL = f"{LOCAL_BASE_URL}/api/connector"
LOCAL_STATUS_URL = f"{LOCAL_BASE_URL}/api/status"
PRODUCT_ID = "half-day-reversal"


@dataclass(frozen=True)
class DesktopSettings:
    hosted_url: str = DEFAULT_HOSTED_URL
    bridge_token: str = ""
    databento_api_key: str = ""
    start_with_computer: bool = True
    allow_live_trading: bool = False


@dataclass(frozen=True)
class LocalServiceProbe:
    running: bool
    is_half_day: bool
    version: str | None = None


def user_data_dir(
    platform: str | None = None,
    home: Path | None = None,
    environ: dict[str, str] | None = None,
) -> Path:
    platform = platform or sys.platform
    home = home or Path.home()
    environ = environ or dict(os.environ)
    if platform == "darwin":
        return home / "Library" / "Application Support" / APP_FOLDER
    if platform.startswith("win"):
        return Path(environ.get("APPDATA", home / "AppData" / "Roaming")) / APP_FOLDER
    return Path(environ.get("XDG_CONFIG_HOME", home / ".config")) / "half-day-reversal"


def validate_settings(settings: DesktopSettings) -> None:
    if not settings.hosted_url.startswith("https://"):
        raise ValueError("The hosted dashboard URL must start with https://")
    if len(settings.bridge_token.strip()) < 32:
        raise ValueError("The dashboard access key must contain at least 32 characters")
    if len(settings.databento_api_key.strip()) < 20:
        raise ValueError("Enter the Databento API key")


def load_settings(path: Path) -> DesktopSettings | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        settings = DesktopSettings(
            hosted_url=str(payload.get("hosted_url", DEFAULT_HOSTED_URL)).strip(),
            bridge_token=str(payload.get("bridge_token", "")).strip(),
            databento_api_key=str(payload.get("databento_api_key", "")).strip(),
            start_with_computer=bool(payload.get("start_with_computer", True)),
            allow_live_trading=bool(payload.get("allow_live_trading", False)),
        )
        validate_settings(settings)
        return settings
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None


def save_settings(path: Path, settings: DesktopSettings) -> None:
    validate_settings(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(asdict(settings), indent=2), encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def apply_settings(settings: DesktopSettings, data_dir: Path) -> None:
    os.environ["HOSTED_DASHBOARD_URL"] = settings.hosted_url
    os.environ["BRIDGE_TOKEN"] = settings.bridge_token
    os.environ["DATABENTO_API_KEY"] = settings.databento_api_key
    os.environ["HALFREVERSAL_DATA_DIR"] = str(data_dir / "strategy")
    os.environ["IBKR_AUTO_CONNECT"] = "false"
    if settings.allow_live_trading:
        os.environ["IBKR_LIVE_UNLOCK"] = "YES_I_UNDERSTAND"
    else:
        os.environ.pop("IBKR_LIVE_UNLOCK", None)


def dashboard_url(settings: DesktopSettings) -> str:
    base = settings.hosted_url.rstrip("/")
    return f"{base}/#access={quote(settings.bridge_token, safe='')}"


def launch_command(background: bool = False) -> list[str]:
    if getattr(sys, "frozen", False):
        command = [sys.executable]
    else:
        command = [sys.executable, "-m", "halfreversal.desktop"]
    if background:
        command.append("--background")
    return command


def configure_startup(enabled: bool, data_dir: Path) -> None:
    if sys.platform == "darwin":
        path = Path.home() / "Library" / "LaunchAgents" / "com.halfday.reversal.plist"
        if not enabled:
            path.unlink(missing_ok=True)
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "Label": "com.halfday.reversal",
            "ProgramArguments": launch_command(background=True),
            "RunAtLoad": True,
            "KeepAlive": False,
            "StandardOutPath": str(data_dir / "connector.log"),
            "StandardErrorPath": str(data_dir / "connector-error.log"),
        }
        with path.open("wb") as handle:
            plistlib.dump(payload, handle)
        return
    if sys.platform.startswith("win"):
        startup = (
            Path(os.environ["APPDATA"])
            / "Microsoft"
            / "Windows"
            / "Start Menu"
            / "Programs"
            / "Startup"
            / "HalfDayReversal.cmd"
        )
        if not enabled:
            startup.unlink(missing_ok=True)
            return
        startup.parent.mkdir(parents=True, exist_ok=True)
        startup.write_text(
            f'@start "" {subprocess.list2cmdline(launch_command(background=True))}\n',
            encoding="utf-8",
        )
        return
    startup = Path.home() / ".config" / "autostart" / "half-day-reversal.desktop"
    if not enabled:
        startup.unlink(missing_ok=True)
        return
    startup.parent.mkdir(parents=True, exist_ok=True)
    command = subprocess.list2cmdline(launch_command(background=True))
    startup.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Half-Day Reversal Connector\n"
        f"Exec={command}\n"
        "Terminal=false\n",
        encoding="utf-8",
    )


def _read_local_json(url: str) -> dict | None:
    try:
        with urllib.request.urlopen(url, timeout=1) as response:
            payload = json.loads(response.read())
        return payload if isinstance(payload, dict) else None
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return None


def probe_local_service() -> LocalServiceProbe:
    identity = _read_local_json(LOCAL_IDENTITY_URL)
    if identity is not None:
        return LocalServiceProbe(
            running=True,
            is_half_day=identity.get("product") == PRODUCT_ID,
            version=str(identity.get("version", "")) or None,
        )

    status = _read_local_json(LOCAL_STATUS_URL)
    if status is None:
        return LocalServiceProbe(running=False, is_half_day=False)
    expected = {"connected", "mode", "armed", "config", "rankings", "orders"}
    return LocalServiceProbe(
        running=True,
        is_half_day=expected.issubset(status),
        version="legacy" if expected.issubset(status) else None,
    )


def local_service_running() -> bool:
    probe = probe_local_service()
    return probe.running and probe.is_half_day


def runtime_action(probe: LocalServiceProbe, worker_connected: bool) -> str:
    if probe.running and not probe.is_half_day:
        return "blocked"
    if probe.is_half_day and probe.version in {APP_VERSION, None}:
        return "existing"
    if probe.is_half_day:
        return "existing" if worker_connected else "recover"
    return "start"


def hosted_worker_connected(settings: DesktopSettings) -> bool:
    request = urllib.request.Request(
        f"{settings.hosted_url.rstrip('/')}/health",
        headers={"User-Agent": f"Half-Day-Reversal-Connector/{APP_VERSION}"},
    )
    context = ssl.create_default_context(cafile=certifi.where())
    try:
        with urllib.request.urlopen(request, timeout=4, context=context) as response:
            payload = json.loads(response.read())
        return bool(payload.get("worker_connected")) if isinstance(payload, dict) else False
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return False


def connector_logger(data_dir: Path) -> logging.Logger:
    data_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(f"halfreversal.desktop.{id(data_dir)}")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        handler = RotatingFileHandler(
            data_dir / "connector.log",
            maxBytes=2 * 1024 * 1024,
            backupCount=2,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
    return logger


class DesktopApp:
    def __init__(self, background: bool = False) -> None:
        self.data_dir = user_data_dir()
        self.settings_path = self.data_dir / "settings.json"
        self.settings = load_settings(self.settings_path)
        self.background = background
        self.events: queue.Queue[tuple[str, bool]] = queue.Queue()
        self.server = None
        self.bridge_thread: threading.Thread | None = None
        self.server_thread: threading.Thread | None = None
        self.monitor_thread: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.restart_after_save = False
        self.logger = connector_logger(self.data_dir)
        self.logger.info(
            "Connector v%s starting; platform=%s architecture=%s frozen=%s background=%s",
            APP_VERSION,
            platform.system(),
            platform.machine(),
            getattr(sys, "frozen", False),
            background,
        )

        self.root = Tk()
        self.root.title("Half-Day Reversal Connector")
        self.root.geometry("620x470")
        self.root.minsize(560, 430)
        self.root.configure(background="#0b0f12")
        self.root.protocol("WM_DELETE_WINDOW", self.root.iconify)
        self._configure_styles()
        self.root.after(200, self._poll_events)

        if self.settings is None:
            self.background = False
            self._show_setup()
        else:
            self._show_running()
            self._start_runtime(open_browser=not background)
            if background:
                self.root.withdraw()

    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(".", background="#0b0f12", foreground="#f4f7f8")
        style.configure("TFrame", background="#0b0f12")
        style.configure("Card.TFrame", background="#151b20")
        style.configure("TLabel", background="#0b0f12", foreground="#f4f7f8")
        style.configure(
            "Title.TLabel",
            background="#0b0f12",
            foreground="#f4f7f8",
            font=("Arial", 24, "bold"),
        )
        style.configure(
            "Muted.TLabel",
            background="#0b0f12",
            foreground="#99a4b2",
            font=("Arial", 11),
        )
        style.configure(
            "Status.TLabel",
            background="#151b20",
            foreground="#bdff37",
            font=("Arial", 14, "bold"),
        )
        style.configure("TCheckbutton", background="#0b0f12", foreground="#f4f7f8")
        style.configure(
            "Accent.TButton",
            background="#bdff37",
            foreground="#071006",
            font=("Arial", 12, "bold"),
            padding=(18, 12),
        )
        style.map("Accent.TButton", background=[("active", "#d0ff70")])
        style.configure("TButton", padding=(12, 9), font=("Arial", 11))
        style.configure("TEntry", fieldbackground="#0f1417", foreground="#f4f7f8", padding=8)

    def _clear(self) -> None:
        for child in self.root.winfo_children():
            child.destroy()

    def _show_setup(self) -> None:
        self._clear()
        frame = ttk.Frame(self.root, padding=32)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="One-time setup", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            frame,
            text="Enter these once. The connector stores them securely on this computer.",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(4, 22))

        current = self.settings or DesktopSettings()
        self.url_var = StringVar(value=current.hosted_url)
        self.token_var = StringVar(value=current.bridge_token)
        self.databento_var = StringVar(value=current.databento_api_key)
        self.startup_var = BooleanVar(value=current.start_with_computer)
        self.live_var = BooleanVar(value=current.allow_live_trading)

        self._field(frame, "Hosted dashboard", self.url_var)
        self._field(frame, "Dashboard access key", self.token_var, secret=True)
        self._field(frame, "Databento API key", self.databento_var, secret=True)
        ttk.Checkbutton(
            frame,
            text="Start the connector automatically with this computer",
            variable=self.startup_var,
        ).pack(anchor="w", pady=(8, 8))
        ttk.Checkbutton(
            frame,
            text="Unlock IBKR live mode on this computer (leave off during paper testing)",
            variable=self.live_var,
        ).pack(anchor="w", pady=(0, 18))
        ttk.Button(
            frame,
            text="Save and open dashboard",
            style="Accent.TButton",
            command=self._save_setup,
        ).pack(anchor="e")

    @staticmethod
    def _field(parent: ttk.Frame, label: str, variable: StringVar, secret: bool = False) -> None:
        ttk.Label(parent, text=label).pack(anchor="w", pady=(0, 5))
        ttk.Entry(parent, textvariable=variable, show="•" if secret else "").pack(
            fill="x", pady=(0, 14)
        )

    def _save_setup(self) -> None:
        settings = DesktopSettings(
            hosted_url=self.url_var.get().strip(),
            bridge_token=self.token_var.get().strip(),
            databento_api_key=self.databento_var.get().strip(),
            start_with_computer=self.startup_var.get(),
            allow_live_trading=self.live_var.get(),
        )
        try:
            save_settings(self.settings_path, settings)
            configure_startup(settings.start_with_computer, self.data_dir)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Could not save setup", str(exc), parent=self.root)
            return
        self.settings = settings
        if self.restart_after_save:
            messagebox.showinfo(
                "Setup saved",
                "Open the connector again to use the new keys.",
                parent=self.root,
            )
            self._quit()
            return
        self._show_running()
        self._start_runtime(open_browser=True)

    def _show_running(self) -> None:
        self._clear()
        frame = ttk.Frame(self.root, padding=32)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Half-Day Reversal", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            frame,
            text="Keep TWS open. Everything else happens in the hosted dashboard.",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(4, 24))

        card = ttk.Frame(frame, style="Card.TFrame", padding=26)
        card.pack(fill="x", pady=(0, 20))
        ttk.Label(card, text="CONNECTOR STATUS", style="Status.TLabel").pack(anchor="w")
        self.status_var = StringVar(value="Starting local service…")
        ttk.Label(
            card,
            textvariable=self.status_var,
            style="Status.TLabel",
            wraplength=500,
        ).pack(
            anchor="w", fill="x", pady=(10, 0)
        )

        actions = ttk.Frame(frame)
        actions.pack(fill="x")
        ttk.Button(
            actions,
            text="Open dashboard",
            style="Accent.TButton",
            command=self._open_dashboard,
        ).pack(side="left")
        ttk.Button(actions, text="Change keys", command=self._change_keys).pack(
            side="left", padx=10
        )
        ttk.Button(actions, text="Open diagnostics", command=self._open_diagnostics).pack(
            side="left"
        )
        ttk.Button(actions, text="Quit connector", command=self._quit).pack(side="right")
        ttk.Label(
            frame,
            text=(
                "Safe state: the app starts disconnected and disarmed. "
                "IBKR credentials remain inside TWS."
            ),
            style="Muted.TLabel",
            wraplength=530,
        ).pack(anchor="w", pady=(28, 0))
        ttk.Label(
            frame,
            text=f"Connector version {APP_VERSION}",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(12, 0))

    def _start_runtime(self, open_browser: bool) -> None:
        if self.settings is None:
            return
        apply_settings(self.settings, self.data_dir)
        probe = probe_local_service()
        self.logger.info(
            "Local probe: running=%s half_day=%s version=%s",
            probe.running,
            probe.is_half_day,
            probe.version or "unknown",
        )
        needs_worker_probe = probe.is_half_day and probe.version not in {APP_VERSION, None}
        worker_connected = (
            hosted_worker_connected(self.settings) if needs_worker_probe else False
        )
        action = runtime_action(probe, worker_connected)
        self.logger.info("Runtime action=%s worker_connected=%s", action, worker_connected)
        if action == "blocked":
            message = (
                "Port 8765 is used by another app. Quit that app, then reopen this connector."
            )
            self.logger.error(message)
            self.events.put((message, False))
        elif action == "existing":
            message = "Connector is already running and will keep retrying automatically."
            self.logger.info(message)
            self.events.put((message, worker_connected))
        elif action == "recover":
            message = "Repairing the previous connector and reconnecting securely…"
            self.logger.warning(
                "Recovering local connector version=%s", probe.version or "unknown"
            )
            self.events.put((message, False))
            self._start_bridge()
            self.monitor_thread = threading.Thread(
                target=self._monitor_legacy_service,
                daemon=True,
                name="local-service-monitor",
            )
            self.monitor_thread.start()
        else:
            self._start_server()
            self._start_bridge()
        if open_browser:
            self.root.after(1400, self._open_dashboard)

    def _start_server(self) -> None:
        if self.server_thread is not None and self.server_thread.is_alive():
            return
        self.server_thread = threading.Thread(
            target=self._run_server,
            daemon=True,
            name="local-service",
        )
        self.server_thread.start()

    def _start_bridge(self) -> None:
        if self.bridge_thread is not None and self.bridge_thread.is_alive():
            return
        self.bridge_thread = threading.Thread(
            target=self._run_bridge,
            daemon=True,
            name="hosted-bridge",
        )
        self.bridge_thread.start()

    def _monitor_legacy_service(self) -> None:
        while not self.stop_event.wait(2):
            if not local_service_running():
                self.logger.warning("Previous local service stopped; starting v%s", APP_VERSION)
                self._start_server()
                return

    def _run_server(self) -> None:
        self.logger.info("Starting local strategy service on 127.0.0.1:8765")
        try:
            import uvicorn

            from halfreversal.app import app

            config = uvicorn.Config(
                app,
                host="127.0.0.1",
                port=8765,
                log_level="warning",
                access_log=False,
            )
            self.server = uvicorn.Server(config)
            asyncio.run(self.server.serve())
        except Exception as exc:
            self.logger.exception("Local service failed")
            self.events.put((f"Local service failed: {type(exc).__name__}", False))

    def _run_bridge(self) -> None:
        self.logger.info("Starting secure hosted bridge")
        for _ in range(80):
            if local_service_running():
                break
            time.sleep(0.1)
        else:
            self.logger.error("Local service did not start within 8 seconds")
            self.events.put(("Local service did not start.", False))
            return
        try:
            from halfreversal.bridge import run_connector

            asyncio.run(run_connector(self._bridge_status))
        except Exception as exc:
            self.logger.exception("Hosted bridge stopped")
            self.events.put((f"Connector stopped: {type(exc).__name__}", False))

    def _bridge_status(self, message: str, online: bool) -> None:
        self.logger.info("Bridge online=%s status=%s", online, message)
        self.events.put((message, online))

    def _open_diagnostics(self) -> None:
        path = self.data_dir / "connector.log"
        path.touch(exist_ok=True)
        try:
            if sys.platform == "darwin":
                subprocess.Popen(["open", "-R", str(path)])
            elif sys.platform.startswith("win"):
                os.startfile(path.parent)  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["xdg-open", str(path.parent)])
        except OSError as exc:
            messagebox.showerror(
                "Could not open diagnostics",
                f"Log file: {path}\n\n{exc}",
                parent=self.root,
            )

    def _poll_events(self) -> None:
        try:
            while True:
                message, online = self.events.get_nowait()
                if hasattr(self, "status_var"):
                    self.status_var.set(message)
                if online and self.background:
                    self.root.withdraw()
        except queue.Empty:
            pass
        self.root.after(200, self._poll_events)

    def _open_dashboard(self) -> None:
        if self.settings:
            webbrowser.open(dashboard_url(self.settings))

    def _change_keys(self) -> None:
        if messagebox.askyesno(
            "Change connector setup",
            "The connector will close after saving. Open it again to use the new settings.",
            parent=self.root,
        ):
            self.restart_after_save = True
            self._show_setup()

    def _quit(self) -> None:
        self.stop_event.set()
        self.logger.info("Connector v%s quitting", APP_VERSION)
        if self.server is not None:
            self.server.should_exit = True
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    DesktopApp(background="--background" in sys.argv).run()


if __name__ == "__main__":
    main()
