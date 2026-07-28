from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from halfreversal.broker import SubmittedOrder
from halfreversal.models import RankRow, TradingConfig, TradingMode
from halfreversal.service import TradingService


def fake_trade(
    order_id: int,
    *,
    status: str,
    filled: int,
    reference: str,
) -> SimpleNamespace:
    return SimpleNamespace(
        order=SimpleNamespace(orderId=order_id, orderRef=reference),
        orderStatus=SimpleNamespace(status=status, filled=filled),
    )


class LifecycleBroker:
    def __init__(self) -> None:
        self.connected = True
        self.entry_calls: list[tuple[str, int, str]] = []
        self.exit_calls: list[tuple[str, int, str]] = []

    async def place_moc(self, symbol: str, quantity: int, reference: str) -> SubmittedOrder:
        self.entry_calls.append((symbol, quantity, reference))
        trade = fake_trade(101, status="Filled", filled=quantity, reference=reference)
        return SubmittedOrder(101, "Filled", trade)  # type: ignore[arg-type]

    async def place_moo(
        self,
        symbol: str,
        quantity: int,
        reference: str,
    ) -> SubmittedOrder:
        self.exit_calls.append((symbol, quantity, reference))
        trade = fake_trade(202, status="Submitted", filled=0, reference=reference)
        return SubmittedOrder(202, "Submitted", trade)  # type: ignore[arg-type]

    async def validate_paper_order_path(self) -> dict:
        return {
            "symbol": "SPY",
            "order_type": "MOC",
            "quantity": 1,
            "status": "PreSubmitted",
            "warning": "",
            "transmitted": False,
        }

    def disconnect(self) -> None:
        self.connected = False


@pytest.mark.asyncio
async def test_filled_moc_automatically_queues_next_open_exit(tmp_path) -> None:
    service = TradingService(tmp_path, data_dir=tmp_path / "data")
    broker = LifecycleBroker()
    service.broker = broker  # type: ignore[assignment]
    service.state.config = TradingConfig(mode=TradingMode.PAPER, account="DUH450551")
    now = datetime.now(UTC)
    service.state.armed_until = now + timedelta(hours=1)
    service._next_session_window = lambda _now: (  # type: ignore[method-assign]
        now - timedelta(hours=6),
        now + timedelta(minutes=18),
    )
    selected = RankRow(
        rank=1,
        symbol="SPY",
        open_price=500,
        current_price=495,
        return_pct=-1,
        selected=True,
        target_quantity=1,
        target_value=495,
    )

    submitted = await service._execute_selected([selected])
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert submitted == 1
    assert broker.entry_calls[0][:2] == ("SPY", 1)
    assert broker.exit_calls == []
    assert service.state.pending_entries == {}
    assert service.state.pending_exit_intents["SPY"]["quantity"] == 1
    service.state.pending_exit_intents["SPY"]["submit_at"] = (
        now - timedelta(minutes=1)
    ).isoformat()

    await service._submit_due_exit_intents(now)

    assert broker.exit_calls[0][:2] == ("SPY", 1)
    assert broker.exit_calls[0][2].endswith("-EXIT")
    assert [(order.side, order.order_type) for order in service.state.orders] == [
        ("SELL", "MOO"),
        ("BUY", "MOC"),
    ]
    assert service.state.pending_exit_intents == {}
    assert service.state.pending_exit_order_ids == {202}
    await service.stop()


@pytest.mark.asyncio
async def test_cancelled_next_open_exit_remains_scheduled(tmp_path) -> None:
    service = TradingService(tmp_path, data_dir=tmp_path / "data")
    trade = fake_trade(
        202,
        status="Cancelled",
        filled=1,
        reference="HDR-2026-07-28-EXIT",
    )
    trade.order.totalQuantity = 3
    service.state.pending_exit_order_ids.add(202)

    await service._watch_exit_fill("SPY", trade)  # type: ignore[arg-type]

    assert service.state.pending_exit_order_ids == set()
    assert service.state.pending_exit_intents["SPY"]["quantity"] == 2
    assert service.state.pending_exit_intents["SPY"]["entry_reference"] == "HDR-2026-07-28"
    await service.stop()


@pytest.mark.asyncio
async def test_paper_order_path_reports_non_transmitting_validation(tmp_path) -> None:
    service = TradingService(tmp_path, data_dir=tmp_path / "data")
    broker = LifecycleBroker()
    service.broker = broker  # type: ignore[assignment]
    service.state.config = TradingConfig(mode=TradingMode.PAPER, account="DUH450551")

    result = await service.validate_paper_order_path()

    assert result["transmitted"] is False
    assert "no order was sent" in result["message"].lower()
    assert "Paper order path passed" in service.state.logs[0].message
    await service.stop()


@pytest.mark.asyncio
async def test_paper_execution_is_blocked_outside_preclose_window(tmp_path) -> None:
    service = TradingService(tmp_path, data_dir=tmp_path / "data")
    broker = LifecycleBroker()
    service.broker = broker  # type: ignore[assignment]
    service.state.config = TradingConfig(mode=TradingMode.PAPER, account="DUH450551")
    now = datetime.now(UTC)
    service.state.armed_until = now + timedelta(hours=1)
    service._next_session_window = lambda _now: (  # type: ignore[method-assign]
        now - timedelta(hours=1),
        now + timedelta(hours=3),
    )
    selected = RankRow(
        rank=1,
        symbol="SPY",
        open_price=500,
        current_price=495,
        return_pct=-1,
        selected=True,
        target_quantity=1,
        target_value=495,
    )

    with pytest.raises(RuntimeError, match="only near"):
        await service._execute_selected([selected])

    assert broker.entry_calls == []
    await service.stop()
