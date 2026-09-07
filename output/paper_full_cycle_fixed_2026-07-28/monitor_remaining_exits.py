from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from halfreversal.service import FINAL_ORDER_STATUSES, NEW_YORK, TradingService

PROJECT_ROOT = Path("/Users/andriiliudvichuk/Projects/ibkr-half-day-reversal")
DATA_DIR = PROJECT_ROOT / "output/paper_full_cycle_fixed_2026-07-28"
EVIDENCE_PATH = DATA_DIR / "evidence.json"
EXPECTED_ACCOUNT = "DUR357918"
EXIT_REFERENCE = "HDR-2026-07-28-EXIT"
REMAINING_SYMBOLS = frozenset(
    {"AAON", "ATI", "DAR", "DY", "FLR", "MP", "MUR", "RH", "SPXC"}
)
DEADLINE = datetime(2026, 8, 6, 18, 0, tzinfo=UTC)


def emit(event: str, **payload: Any) -> None:
    print(
        json.dumps(
            {
                "event": event,
                "time_utc": datetime.now(UTC).isoformat(),
                **payload,
            },
            sort_keys=True,
        ),
        flush=True,
    )


def write_evidence(payload: dict[str, Any]) -> None:
    temporary_path = EVIDENCE_PATH.with_suffix(".json.tmp")
    temporary_path.write_text(json.dumps(payload, indent=2, sort_keys=True))
    temporary_path.replace(EVIDENCE_PATH)


def reschedule_expired_intents(service: TradingService, now: datetime) -> datetime:
    session = service.calendar.date_to_session(
        pd.Timestamp(now.astimezone(NEW_YORK).date()),
        direction="next",
    )
    session_open = service.calendar.session_open(session).to_pydatetime().astimezone(UTC)
    if now >= session_open:
        session = service.calendar.next_session(session)
        session_open = service.calendar.session_open(session).to_pydatetime().astimezone(UTC)
    submit_at = session_open - timedelta(minutes=90)

    changed = False
    for symbol, intent in service.state.pending_exit_intents.items():
        if symbol not in REMAINING_SYMBOLS:
            raise RuntimeError(f"Unexpected pending exit intent: {symbol}")
        current_submit_at = datetime.fromisoformat(str(intent["submit_at"])).astimezone(UTC)
        if current_submit_at <= now:
            intent["submit_at"] = submit_at.isoformat()
            intent["last_attempt_at"] = None
            changed = True
    if changed:
        service.state.save_runtime()
    return submit_at


async def main() -> None:
    service = TradingService(PROJECT_ROOT, data_dir=DATA_DIR)
    now = datetime.now(UTC)
    submit_at = reschedule_expired_intents(service, now)
    emit(
        "recovery_scheduled",
        symbols=sorted(service.state.pending_exit_intents),
        submit_at_utc=submit_at.isoformat(),
        submit_at_et=submit_at.astimezone(NEW_YORK).isoformat(),
    )

    exit_history: dict[int, dict[str, Any]] = {}
    last_summary: tuple[Any, ...] | None = None
    await service.start()
    try:
        while datetime.now(UTC) < DEADLINE:
            if not service.broker.connected:
                try:
                    await service.connect()
                    if service.broker.account != EXPECTED_ACCOUNT:
                        raise RuntimeError(
                            f"Connected to {service.broker.account}, expected {EXPECTED_ACCOUNT}"
                        )
                    emit("connected", account=service.broker.account)
                except Exception as exc:
                    emit("connection_failed", error=str(exc))
                    await asyncio.sleep(15)
                    continue

            await service.refresh_account()
            strategy_positions = {
                position.symbol: int(position.quantity)
                for position in service.state.account.positions
                if position.symbol in REMAINING_SYMBOLS and position.quantity
            }

            for trade in service.broker.ib.trades():
                if (
                    (trade.order.orderRef or "") != EXIT_REFERENCE
                    or trade.contract.symbol not in REMAINING_SYMBOLS
                ):
                    continue
                order_id = int(trade.order.orderId)
                exit_history[order_id] = {
                    "order_id": order_id,
                    "symbol": trade.contract.symbol,
                    "quantity": int(float(trade.order.totalQuantity)),
                    "status": trade.orderStatus.status,
                    "filled": int(float(trade.orderStatus.filled or 0)),
                    "remaining": int(float(trade.orderStatus.remaining or 0)),
                    "average_fill_price": float(trade.orderStatus.avgFillPrice or 0),
                    "order_type": trade.order.orderType,
                    "tif": trade.order.tif,
                    "reference": trade.order.orderRef,
                }

            open_exit_orders = [
                trade
                for trade in service.broker.ib.openTrades()
                if (trade.order.orderRef or "") == EXIT_REFERENCE
            ]
            final_exit_count = sum(
                exit_order["status"] in FINAL_ORDER_STATUSES
                for exit_order in exit_history.values()
            )
            summary = (
                len(strategy_positions),
                len(service.state.pending_exit_intents),
                len(service.state.pending_exit_order_ids),
                len(open_exit_orders),
                len(exit_history),
                final_exit_count,
            )
            if summary != last_summary:
                emit(
                    "state",
                    account=service.broker.account,
                    strategy_positions=strategy_positions,
                    exit_intents_count=len(service.state.pending_exit_intents),
                    pending_exit_ids_count=len(service.state.pending_exit_order_ids),
                    open_exit_orders_count=len(open_exit_orders),
                    observed_recovery_orders_count=len(exit_history),
                    final_recovery_orders_count=final_exit_count,
                )
                last_summary = summary

            recovered_symbols = {
                exit_order["symbol"]
                for exit_order in exit_history.values()
                if exit_order["status"] == "Filled"
                and exit_order["filled"] == exit_order["quantity"]
            }
            cycle_complete = (
                not strategy_positions
                and not service.state.pending_exit_intents
                and not service.state.pending_exit_order_ids
                and not open_exit_orders
                and recovered_symbols == REMAINING_SYMBOLS
            )
            if cycle_complete:
                evidence = {
                    "result": "complete",
                    "verified_at_utc": datetime.now(UTC).isoformat(),
                    "account": service.broker.account,
                    "paper_account": service.broker.account.startswith("DU"),
                    "entry_universe_count": 400,
                    "entry_selected_count": 40,
                    "initial_exit_filled_count": 31,
                    "recovery_exit_filled_count": len(recovered_symbols),
                    "total_exit_filled_count": 31 + len(recovered_symbols),
                    "recovery_exit_orders": sorted(
                        exit_history.values(),
                        key=lambda exit_order: exit_order["symbol"],
                    ),
                    "remaining_strategy_positions": strategy_positions,
                    "remaining_exit_intents": len(service.state.pending_exit_intents),
                    "remaining_open_strategy_orders": len(open_exit_orders),
                }
                write_evidence(evidence)
                emit("cycle_complete", evidence_path=str(EVIDENCE_PATH))
                return

            await asyncio.sleep(15)

        evidence = {
            "result": "deadline_reached",
            "verified_at_utc": datetime.now(UTC).isoformat(),
            "account": service.broker.account,
            "remaining_strategy_positions": {
                position.symbol: int(position.quantity)
                for position in service.state.account.positions
                if position.symbol in REMAINING_SYMBOLS and position.quantity
            },
            "remaining_exit_intents": len(service.state.pending_exit_intents),
            "remaining_pending_exit_ids": len(service.state.pending_exit_order_ids),
            "observed_recovery_orders": sorted(
                exit_history.values(),
                key=lambda exit_order: exit_order["symbol"],
            ),
        }
        write_evidence(evidence)
        emit("deadline_reached", evidence_path=str(EVIDENCE_PATH))
        raise RuntimeError("Paper cycle did not become flat before the monitoring deadline")
    finally:
        await service.stop()


if __name__ == "__main__":
    asyncio.run(main())
