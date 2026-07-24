from __future__ import annotations

import json
import logging
import os
import threading
from collections import deque
from datetime import datetime
from pathlib import Path

from .models import (
    AccountSnapshot,
    LogView,
    OrderView,
    RankRow,
    TradingConfig,
)


class RuntimeState:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.config_path = data_dir / "config.json"
        self.runtime_path = data_dir / "runtime.json"
        self.log_path = data_dir / "strategy.log"
        self._lock = threading.RLock()

        self.config = self._load_config()
        self.connected = False
        self.connection_label = "Disconnected"
        self.armed_until: datetime | None = None
        self.next_run_at: datetime | None = None
        self.market_status = "Unknown"
        self.last_scan_at: datetime | None = None
        self.last_execution_date: str | None = None
        self.account = AccountSnapshot()
        self.rankings: list[RankRow] = []
        self.orders: list[OrderView] = []
        self.logs: deque[LogView] = deque(maxlen=300)
        self.pending_entries: dict[int, dict[str, object]] = {}
        self.pending_exit_order_ids: set[int] = set()
        self._load_runtime()
        self._configure_file_logger()

    def _load_config(self) -> TradingConfig:
        if not self.config_path.exists():
            config = TradingConfig()
            self._atomic_json_write(self.config_path, config.model_dump(mode="json"))
            return config
        try:
            return TradingConfig.model_validate_json(self.config_path.read_text())
        except (OSError, ValueError):
            return TradingConfig()

    def save_config(self, config: TradingConfig) -> None:
        with self._lock:
            self._atomic_json_write(self.config_path, config.model_dump(mode="json"))
            self.config = config

    def _load_runtime(self) -> None:
        if not self.runtime_path.exists():
            return
        try:
            payload = json.loads(self.runtime_path.read_text())
            self.last_execution_date = payload.get("last_execution_date")
            self.pending_entries = {
                int(order_id): entry
                for order_id, entry in payload.get("pending_entries", {}).items()
            }
            self.pending_exit_order_ids = set(payload.get("pending_exit_order_ids", []))
        except (OSError, ValueError, TypeError):
            pass

    def save_runtime(self) -> None:
        with self._lock:
            self._atomic_json_write(
                self.runtime_path,
                {
                    "last_execution_date": self.last_execution_date,
                    "pending_entries": self.pending_entries,
                    "pending_exit_order_ids": sorted(self.pending_exit_order_ids),
                },
            )

    def log(self, message: str, level: str = "INFO") -> None:
        safe_level = level if level in {"INFO", "WARNING", "ERROR", "SUCCESS"} else "INFO"
        entry = LogView(level=safe_level, message=message)  # type: ignore[arg-type]
        with self._lock:
            self.logs.appendleft(entry)
        logger = logging.getLogger("halfday")
        log_method = logger.error if safe_level == "ERROR" else (
            logger.warning if safe_level == "WARNING" else logger.info
        )
        log_method(message)

    def add_order(self, order: OrderView) -> None:
        with self._lock:
            self.orders.insert(0, order)
            del self.orders[100:]

    def update_order_status(self, order_id: int, status: str) -> None:
        with self._lock:
            for order in self.orders:
                if order.order_id == order_id:
                    order.status = status
                    return

    def _configure_file_logger(self) -> None:
        logger = logging.getLogger("halfday")
        logger.setLevel(logging.INFO)
        if any(isinstance(handler, logging.FileHandler) for handler in logger.handlers):
            return
        handler = logging.FileHandler(self.log_path)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)

    @staticmethod
    def _atomic_json_write(path: Path, payload: object) -> None:
        temporary_path = path.with_suffix(f"{path.suffix}.tmp")
        try:
            temporary_path.write_text(json.dumps(payload, indent=2, sort_keys=True))
            os.replace(temporary_path, path)
        except Exception:
            temporary_path.unlink(missing_ok=True)
            raise
