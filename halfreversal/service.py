from __future__ import annotations

import asyncio
import os
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import pandas as pd
from ib_async import Trade

from .backtest import DatabentoBacktester
from .broker import IBKRBroker
from .models import (
    BacktestEstimate,
    BacktestRequest,
    BacktestResult,
    MidcapUniverse,
    OrderView,
    RuntimeSnapshot,
    TradingConfig,
    TradingMode,
)
from .state import RuntimeState
from .strategy import StrategyEngine

NEW_YORK = ZoneInfo("America/New_York")
STRATEGY_REFERENCE_PREFIX = "HDR-"
FINAL_ORDER_STATUSES = {"Filled", "Cancelled", "ApiCancelled", "Inactive"}


class TradingService:
    def __init__(self, project_root: Path, data_dir: Path | None = None) -> None:
        self.state = RuntimeState(data_dir or project_root / "data")
        self.broker = IBKRBroker(self.state.log)
        self.engine = StrategyEngine(self.broker)
        self.backtester = DatabentoBacktester(self.state.log)
        self.calendar = xcals.get_calendar("XNYS")
        self._scheduler_task: asyncio.Task[None] | None = None
        self._scan_lock = asyncio.Lock()
        self._backtest_lock = asyncio.Lock()
        self._watch_tasks: set[asyncio.Task[None]] = set()
        self._watched_order_ids: set[int] = set()
        self._auto_attempted_date: str | None = None
        self._stopping = False

    async def start(self) -> None:
        self.state.log("Dashboard started in safe mode. Connect to IBKR when ready.")
        self._stopping = False
        self._scheduler_task = asyncio.create_task(self._scheduler_loop())
        if os.getenv("IBKR_AUTO_CONNECT", "").lower() in {"1", "true", "yes"}:
            with suppress(Exception):
                await self.connect()

    async def stop(self) -> None:
        self._stopping = True
        if self._scheduler_task:
            self._scheduler_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._scheduler_task
        for task in tuple(self._watch_tasks):
            task.cancel()
        if self._watch_tasks:
            await asyncio.gather(*self._watch_tasks, return_exceptions=True)
        self._watch_tasks.clear()
        self._watched_order_ids.clear()
        self.broker.disconnect()
        self.state.save_runtime()

    async def connect(self) -> dict[str, str]:
        config = self.state.config
        self._validate_live_unlock(config)
        try:
            account = await self.broker.connect(config)
            self.state.connected = True
            self.state.connection_label = f"Connected · {self._masked_account(account)}"
            account_label = self._masked_account(account)
            self.state.log(
                f"Connected to {self._mode_label(config.mode)} account {account_label}",
                "SUCCESS",
            )
            await self.refresh_account()
            await self._restore_open_strategy_orders()
            return {"message": self.state.connection_label}
        except Exception as exc:
            self.state.connected = False
            self.state.connection_label = "Connection failed"
            self.state.log(str(exc), "ERROR")
            raise

    async def disconnect(self) -> dict[str, str]:
        for task in tuple(self._watch_tasks):
            task.cancel()
        if self._watch_tasks:
            await asyncio.gather(*self._watch_tasks, return_exceptions=True)
        self._watch_tasks.clear()
        self._watched_order_ids.clear()
        self.broker.disconnect()
        self.state.connected = False
        self.state.connection_label = "Disconnected"
        self.state.armed_until = None
        return {"message": "Disconnected from IBKR"}

    async def update_config(self, config: TradingConfig) -> TradingConfig:
        self._validate_live_unlock(config)
        connection_changed = any(
            getattr(config, field) != getattr(self.state.config, field)
            for field in ("host", "port", "client_id", "account", "mode")
        )
        if connection_changed and self.broker.connected:
            await self.disconnect()
        self.state.save_config(config)
        self.state.log("Settings saved")
        return config

    def arm(self, phrase: str) -> dict[str, Any]:
        config = self.state.config
        if not self.broker.connected:
            raise RuntimeError("Connect IBKR before arming execution")
        expected_phrase = "LIVE" if config.mode == TradingMode.LIVE else "PAPER"
        if config.mode == TradingMode.DRY_RUN:
            expected_phrase = "DRY RUN"
        if phrase.strip().upper() != expected_phrase:
            raise RuntimeError(f"Type {expected_phrase} to arm this session")
        self._validate_live_unlock(config)
        _, close_at = self._next_session_window(datetime.now(UTC))
        self.state.armed_until = close_at + timedelta(minutes=45)
        self.state.log(
            f"{self._mode_label(config.mode)} execution armed until "
            f"{self.state.armed_until.astimezone(NEW_YORK):%I:%M %p ET}",
            "WARNING" if config.mode == TradingMode.LIVE else "SUCCESS",
        )
        return {"armed_until": self.state.armed_until}

    def disarm(self) -> dict[str, str]:
        self.state.armed_until = None
        self.state.log("Order execution disarmed")
        return {"message": "Execution disarmed"}

    async def run_scan(self, execute: bool = False, scheduled: bool = False) -> dict[str, Any]:
        if self._scan_lock.locked():
            raise RuntimeError("A scan is already running")
        async with self._scan_lock:
            if not self.broker.connected:
                await self.connect()
            await self.refresh_account()
            action = "scheduled scan" if scheduled else "scan"
            self.state.log(f"Starting {action} across {len(self.state.config.universe)} symbols")
            result = await self.engine.scan(
                self.state.config,
                self.state.account.net_liquidation,
                self.state.account.available_funds,
            )
            self.state.rankings = result.rows
            self.state.last_scan_at = result.scanned_at
            self.state.log(
                f"Scan complete: {result.valid_quotes}/{result.universe_size} valid quotes; "
                f"{result.selected_count} stocks selected",
                "SUCCESS",
            )
            submitted = 0
            if execute:
                submitted = await self._execute_selected(result.rows)
            return {
                "scan": result.model_dump(mode="json"),
                "orders_submitted": submitted,
            }

    async def cancel_strategy_orders(self) -> dict[str, int]:
        if not self.broker.connected:
            raise RuntimeError("IBKR is not connected")
        count = await self.broker.cancel_strategy_orders(STRATEGY_REFERENCE_PREFIX)
        self.state.armed_until = None
        self.state.log(f"Cancellation requested for {count} open strategy order(s)", "WARNING")
        return {"cancelled": count}

    async def validate_paper_order_path(self) -> dict[str, Any]:
        if not self.broker.connected:
            raise RuntimeError("Connect IBKR before running the paper order test")
        if self.state.config.mode != TradingMode.PAPER:
            raise RuntimeError("The order-path test is available only in IBKR paper mode")
        result = await self.broker.validate_paper_order_path()
        self.state.log(
            "Paper order path passed: IBKR accepted a one-share SPY MOC what-if. "
            "No order was transmitted.",
            "SUCCESS",
        )
        return {
            **result,
            "message": "Paper order path passed. IBKR accepted the MOC what-if; no order was sent.",
        }

    async def estimate_backtest(self, request: BacktestRequest) -> BacktestEstimate:
        return await self.backtester.estimate(request, self.state.config)

    async def run_backtest(self, request: BacktestRequest) -> BacktestResult:
        if self._backtest_lock.locked():
            raise RuntimeError("A backtest is already running")
        async with self._backtest_lock:
            return await self.backtester.run(request, self.state.config)

    async def load_midcap_universe(self) -> MidcapUniverse:
        universe = await self.backtester.load_midcap_universe()
        self.state.log(
            f"Loaded {universe.symbol_count} mid-cap symbols from {universe.source}",
            "SUCCESS",
        )
        return universe

    async def refresh_account(self) -> None:
        self.state.connected = self.broker.connected
        if not self.broker.connected:
            self.state.connection_label = "Disconnected"
            return
        self.state.account = await self.broker.get_account_snapshot()

    def snapshot(self) -> RuntimeSnapshot:
        now = datetime.now(UTC)
        armed = self.state.armed_until is not None and self.state.armed_until > now
        if not armed:
            self.state.armed_until = None
        return RuntimeSnapshot(
            connected=self.broker.connected,
            connection_label=self.state.connection_label,
            mode=self.state.config.mode,
            armed=armed,
            armed_until=self.state.armed_until,
            auto_enabled=self.state.config.auto_enabled,
            next_run_at=self.state.next_run_at,
            market_status=self.state.market_status,
            last_scan_at=self.state.last_scan_at,
            last_execution_date=self.state.last_execution_date,
            account=self.state.account,
            rankings=self.state.rankings,
            orders=self.state.orders,
            logs=list(self.state.logs),
            config=self.state.config,
        )

    async def _execute_selected(self, rows: list[Any]) -> int:
        config = self.state.config
        now = datetime.now(UTC)
        if self.state.armed_until is None or self.state.armed_until <= now:
            raise RuntimeError("Execution is not armed")
        today = now.astimezone(NEW_YORK).date().isoformat()
        if self.state.last_execution_date == today:
            raise RuntimeError("Orders have already been submitted for this trading day")
        if self.state.pending_exit_order_ids or self.state.pending_exit_intents:
            raise RuntimeError("A previous strategy exit is still open; new entries are blocked")
        if config.mode != TradingMode.DRY_RUN:
            _, close_at = self._next_session_window(now)
            configured_run_at = close_at - timedelta(
                minutes=config.scan_minutes_before_close
            )
            earliest_execution = configured_run_at - timedelta(minutes=5)
            latest_execution = min(
                configured_run_at + timedelta(minutes=5),
                close_at - timedelta(minutes=15, seconds=45),
            )
            if not earliest_execution <= now <= latest_execution:
                raise RuntimeError(
                    "Order transmission is allowed only near the configured pre-close scan time "
                    f"({earliest_execution.astimezone(NEW_YORK):%I:%M:%S %p}–"
                    f"{latest_execution.astimezone(NEW_YORK):%I:%M:%S %p ET})"
                )

        selected = [row for row in rows if row.selected and row.target_quantity > 0]
        if not selected:
            raise RuntimeError("The scan has no executable selections")

        reference = f"{STRATEGY_REFERENCE_PREFIX}{today}"
        if config.mode == TradingMode.DRY_RUN:
            for row in selected:
                self.state.add_order(
                    OrderView(
                        symbol=row.symbol,
                        side="BUY",
                        order_type="MOC",
                        quantity=row.target_quantity,
                        status="Planned only",
                        reference=reference,
                    )
                )
            self.state.last_execution_date = today
            self.state.save_runtime()
            self.state.log(
                f"Dry run planned {len(selected)} MOC orders; nothing was transmitted",
                "SUCCESS",
            )
            return 0

        submitted_count = 0
        existing_positions = {
            position.symbol: position.quantity for position in self.state.account.positions
        }
        for row in selected:
            try:
                submitted = await self.broker.place_moc(
                    row.symbol,
                    row.target_quantity,
                    reference,
                )
                self.state.add_order(
                    OrderView(
                        order_id=submitted.order_id,
                        symbol=row.symbol,
                        side="BUY",
                        order_type="MOC",
                        quantity=row.target_quantity,
                        status=submitted.status,
                        reference=reference,
                    )
                )
                self.state.pending_entries[submitted.order_id] = {
                    "symbol": row.symbol,
                    "quantity": row.target_quantity,
                    "baseline_quantity": existing_positions.get(row.symbol, 0),
                    "reference": reference,
                }
                self.state.save_runtime()
                self._track_order_task(
                    submitted.order_id,
                    self._watch_entry_fill(row.symbol, submitted.trade, reference),
                )
                submitted_count += 1
            except Exception as exc:
                self.state.log(f"{row.symbol} MOC rejected before submission: {exc}", "ERROR")

        if submitted_count == 0:
            raise RuntimeError("IBKR did not accept any entry orders")
        self.state.last_execution_date = today
        self.state.save_runtime()
        self.state.log(f"Submitted {submitted_count} MOC buy orders", "SUCCESS")
        return submitted_count

    async def _watch_entry_fill(self, symbol: str, trade: Trade, reference: str) -> None:
        status = trade.orderStatus.status
        for _ in range(7_200):
            status = trade.orderStatus.status
            self.state.update_order_status(trade.order.orderId, status)
            if status in FINAL_ORDER_STATUSES:
                break
            await asyncio.sleep(1)
        filled = int(float(trade.orderStatus.filled or 0))
        if filled <= 0:
            self.state.pending_entries.pop(trade.order.orderId, None)
            self.state.save_runtime()
            self.state.log(f"{symbol} MOC finished as {status} with no fill", "WARNING")
            return
        try:
            self.state.pending_entries.pop(trade.order.orderId, None)
            self._schedule_exit_intent(symbol, filled, reference)
            self.state.save_runtime()
            submit_at = datetime.fromisoformat(
                str(self.state.pending_exit_intents[symbol]["submit_at"])
            )
            self.state.log(
                f"{symbol}: {filled} shares filled; next-open sell scheduled for "
                f"{submit_at.astimezone(NEW_YORK):%I:%M %p ET}",
                "SUCCESS",
            )
        except Exception as exc:
            self.state.log(
                f"URGENT: {symbol} filled {filled} shares but its exit could not be scheduled: "
                f"{exc}",
                "ERROR",
            )

    async def _watch_exit_fill(self, symbol: str, trade: Trade) -> None:
        status = trade.orderStatus.status
        for _ in range(86_400):
            status = trade.orderStatus.status
            self.state.update_order_status(trade.order.orderId, status)
            if status in FINAL_ORDER_STATUSES:
                break
            await asyncio.sleep(1)
        self.state.pending_exit_order_ids.discard(trade.order.orderId)
        filled = int(float(trade.orderStatus.filled or 0))
        total_quantity = int(float(trade.order.totalQuantity or 0))
        remaining = max(0, total_quantity - filled)
        if status != "Filled" and remaining:
            entry_reference = (trade.order.orderRef or "").removesuffix("-EXIT")
            self._schedule_exit_intent(symbol, remaining, entry_reference)
            scheduled = self.state.pending_exit_intents[symbol]
            original_submit_at = datetime.fromisoformat(str(scheduled["submit_at"]))
            original_open_at = original_submit_at + timedelta(minutes=90)
            now = datetime.now(UTC)
            if now >= original_open_at:
                original_session = self.calendar.date_to_session(
                    pd.Timestamp(original_open_at.astimezone(NEW_YORK).date()),
                    direction="next",
                )
                retry_session = self.calendar.next_session(original_session)
                retry_open_at = self.calendar.session_open(retry_session).to_pydatetime()
                scheduled["submit_at"] = (
                    retry_open_at.astimezone(UTC) - timedelta(minutes=90)
                ).isoformat()
        self.state.save_runtime()
        level = "SUCCESS" if status == "Filled" else "WARNING"
        suffix = ""
        if status != "Filled" and remaining:
            suffix = f"; {remaining} shares remain scheduled for exit"
        self.state.log(f"{symbol} next-open exit finished as {status}{suffix}", level)

    async def _restore_open_strategy_orders(self) -> None:
        open_trades = self.broker.ib.openTrades()
        open_order_ids = {trade.order.orderId for trade in open_trades}
        tracked_order_ids = set(self.state.pending_entries) | self.state.pending_exit_order_ids
        strategy_trades = [
            trade
            for trade in self.broker.ib.trades()
            if trade.order.orderId in tracked_order_ids
            or (
                trade.order.orderId in open_order_ids
                and (trade.order.orderRef or "").startswith(STRATEGY_REFERENCE_PREFIX)
            )
        ]
        recovered_order_ids: set[int] = set()
        active_exit_ids: set[int] = set()
        active_exit_symbols: set[str] = set()
        for trade in strategy_trades:
            reference = trade.order.orderRef or ""
            if not reference.startswith(STRATEGY_REFERENCE_PREFIX):
                continue
            order_type = "MOO" if trade.order.tif == "OPG" else "MOC"
            side = "SELL" if trade.order.action == "SELL" else "BUY"
            order_id = trade.order.orderId
            recovered_order_ids.add(order_id)
            if not any(order.order_id == order_id for order in self.state.orders):
                self.state.add_order(
                    OrderView(
                        order_id=order_id,
                        symbol=trade.contract.symbol,
                        side=side,
                        order_type=order_type,
                        quantity=int(float(trade.order.totalQuantity)),
                        status=trade.orderStatus.status,
                        reference=reference,
                    )
                )
            if order_type == "MOO":
                if trade.orderStatus.status not in FINAL_ORDER_STATUSES:
                    active_exit_ids.add(order_id)
                    active_exit_symbols.add(trade.contract.symbol)
                    self._track_order_task(
                        order_id,
                        self._watch_exit_fill(trade.contract.symbol, trade),
                    )
            else:
                self._track_order_task(
                    order_id,
                    self._watch_entry_fill(trade.contract.symbol, trade, reference),
                )
        self.state.pending_exit_order_ids = active_exit_ids
        for symbol in active_exit_symbols:
            self.state.pending_exit_intents.pop(symbol, None)
        await self._recover_unreported_entries(recovered_order_ids)
        self.state.save_runtime()

    async def _recover_unreported_entries(self, recovered_order_ids: set[int]) -> None:
        position_quantities = {
            position.symbol: position.quantity for position in self.state.account.positions
        }
        for order_id, entry in tuple(self.state.pending_entries.items()):
            if order_id in recovered_order_ids:
                continue
            symbol = str(entry["symbol"])
            baseline = float(entry.get("baseline_quantity", 0))
            acquired_quantity = max(0, int(position_quantities.get(symbol, 0) - baseline))
            if acquired_quantity == 0:
                self.state.log(
                    f"Recovered entry {order_id} for {symbol} with no remaining filled position",
                    "WARNING",
                )
                self.state.pending_entries.pop(order_id, None)
                continue
            try:
                entry_reference = str(entry["reference"])
                self._schedule_exit_intent(
                    symbol,
                    acquired_quantity,
                    entry_reference,
                )
                self.state.pending_entries.pop(order_id, None)
                self.state.log(
                    f"Recovered {symbol} after restart and scheduled a "
                    f"{acquired_quantity}-share next-open exit",
                    "WARNING",
                )
            except Exception as exc:
                self.state.log(
                    f"URGENT: restart recovery could not schedule the {symbol} exit: {exc}",
                    "ERROR",
                )

    async def _scheduler_loop(self) -> None:
        refresh_counter = 0
        while not self._stopping:
            try:
                now = datetime.now(UTC)
                session_open, session_close = self._next_session_window(now)
                run_at = session_close - timedelta(
                    minutes=self.state.config.scan_minutes_before_close
                )
                self.state.next_run_at = run_at
                if session_open <= now <= session_close:
                    self.state.market_status = "Open"
                elif now < session_open:
                    self.state.market_status = "Pre-market"
                else:
                    self.state.market_status = "Closed"

                session_date = session_close.astimezone(NEW_YORK).date().isoformat()
                should_run = (
                    self.state.config.auto_enabled
                    and run_at <= now <= session_close
                    and self.state.last_execution_date != session_date
                    and self._auto_attempted_date != session_date
                )
                if should_run:
                    self._auto_attempted_date = session_date
                    try:
                        await self.run_scan(execute=True, scheduled=True)
                    except Exception as exc:
                        self.state.log(f"Automatic run stopped: {exc}", "ERROR")

                refresh_counter += 1
                if refresh_counter >= 3 and self.broker.connected:
                    refresh_counter = 0
                    await self.refresh_account()
                if self.broker.connected:
                    await self._submit_due_exit_intents(now)
            except Exception as exc:
                self.state.log(f"Scheduler check failed: {exc}", "ERROR")
            await asyncio.sleep(5)

    def _next_session_window(self, now: datetime) -> tuple[datetime, datetime]:
        now_utc = now.astimezone(UTC)
        session = self.calendar.date_to_session(pd.Timestamp(now_utc.date()), direction="next")
        close_at = self.calendar.session_close(session).to_pydatetime().astimezone(UTC)
        if now_utc > close_at:
            session = self.calendar.next_session(session)
        open_at = self.calendar.session_open(session).to_pydatetime().astimezone(UTC)
        close_at = self.calendar.session_close(session).to_pydatetime().astimezone(UTC)
        return open_at, close_at

    def _next_open_submission_time(self, entry_reference: str) -> datetime:
        signal_date = entry_reference.removeprefix(STRATEGY_REFERENCE_PREFIX)[:10]
        entry_session = self.calendar.date_to_session(
            pd.Timestamp(signal_date),
            direction="next",
        )
        exit_session = self.calendar.next_session(entry_session)
        exit_open = self.calendar.session_open(exit_session).to_pydatetime()
        return exit_open.astimezone(UTC) - timedelta(minutes=90)

    def _schedule_exit_intent(
        self,
        symbol: str,
        quantity: int,
        entry_reference: str,
    ) -> None:
        self.state.pending_exit_intents[symbol] = {
            "symbol": symbol,
            "quantity": quantity,
            "entry_reference": entry_reference,
            "submit_at": self._next_open_submission_time(entry_reference).isoformat(),
            "last_attempt_at": None,
        }

    async def _submit_due_exit_intents(self, now: datetime | None = None) -> None:
        check_at = (now or datetime.now(UTC)).astimezone(UTC)
        for symbol, intent in tuple(self.state.pending_exit_intents.items()):
            submit_at = datetime.fromisoformat(str(intent["submit_at"])).astimezone(UTC)
            if check_at < submit_at:
                continue
            last_attempt_raw = intent.get("last_attempt_at")
            if last_attempt_raw:
                last_attempt = datetime.fromisoformat(str(last_attempt_raw)).astimezone(UTC)
                if check_at - last_attempt < timedelta(minutes=1):
                    continue
            intent["last_attempt_at"] = check_at.isoformat()
            self.state.save_runtime()
            quantity = int(intent["quantity"])
            reference = f"{intent['entry_reference']}-EXIT"
            try:
                submitted = await self.broker.place_moo(symbol, quantity, reference)
                self.state.pending_exit_order_ids.add(submitted.order_id)
                self.state.pending_exit_intents.pop(symbol, None)
                self.state.add_order(
                    OrderView(
                        order_id=submitted.order_id,
                        symbol=symbol,
                        side="SELL",
                        order_type="MOO",
                        quantity=quantity,
                        status=submitted.status,
                        reference=reference,
                    )
                )
                self.state.save_runtime()
                self.state.log(
                    f"{symbol}: {quantity}-share next-open sell submitted",
                    "SUCCESS",
                )
                self._track_order_task(
                    submitted.order_id,
                    self._watch_exit_fill(symbol, submitted.trade),
                )
            except Exception as exc:
                self.state.log(
                    f"URGENT: {symbol} next-open exit submission failed; retrying: {exc}",
                    "ERROR",
                )

    def _track_order_task(self, order_id: int, coroutine: Any) -> None:
        if order_id in self._watched_order_ids:
            coroutine.close()
            return
        task = asyncio.create_task(coroutine)
        self._watched_order_ids.add(order_id)
        self._watch_tasks.add(task)

        def cleanup(completed_task: asyncio.Task[None]) -> None:
            self._watch_tasks.discard(completed_task)
            self._watched_order_ids.discard(order_id)

        task.add_done_callback(cleanup)

    @staticmethod
    def _masked_account(account: str) -> str:
        return account if len(account) <= 4 else f"••••{account[-4:]}"

    @staticmethod
    def _mode_label(mode: TradingMode) -> str:
        return mode.value.replace("_", " ").title()

    @staticmethod
    def _validate_live_unlock(config: TradingConfig) -> None:
        if config.mode == TradingMode.LIVE and os.getenv("IBKR_LIVE_UNLOCK") != "YES_I_UNDERSTAND":
            raise RuntimeError(
                "Live mode is locked. Set IBKR_LIVE_UNLOCK=YES_I_UNDERSTAND "
                "before starting the app."
            )
