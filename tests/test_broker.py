from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from ib_async import Order, Stock

from halfreversal.broker import IBKRBroker
from halfreversal.models import TradingConfig, TradingMode


class FakeEvent:
    def __init__(self) -> None:
        self.handlers: list = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def __isub__(self, handler):
        self.handlers.remove(handler)
        return self

    def emit(self, *args) -> None:
        for handler in tuple(self.handlers):
            handler(*args)


class FakeIB:
    def __init__(
        self,
        accounts: list[str] | None = None,
        *,
        connected: bool = True,
    ) -> None:
        self.accounts = accounts or ["DUH450551"]
        self.connected = connected
        self.disconnected = False
        self.market_data_types: list[int] = []
        self.placed: list[tuple[Stock, Order]] = []
        self.cancelled: list[Order] = []
        self.open_trades: list[SimpleNamespace] = []
        self.errorEvent = FakeEvent()
        self.what_if_error: tuple[int, str] | None = None

    def isConnected(self) -> bool:
        return self.connected

    async def connectAsync(self, *_args, **_kwargs) -> None:
        self.connected = True

    def managedAccounts(self) -> list[str]:
        return self.accounts

    def disconnect(self) -> None:
        self.connected = False
        self.disconnected = True

    def reqMarketDataType(self, market_data_type: int) -> None:
        self.market_data_types.append(market_data_type)

    async def qualifyContractsAsync(self, *contracts: Stock) -> list[Stock]:
        return list(contracts)

    def placeOrder(self, contract: Stock, order: Order) -> SimpleNamespace:
        order.orderId = 100 + len(self.placed)
        self.placed.append((contract, order))
        return SimpleNamespace(
            contract=contract,
            order=order,
            orderStatus=SimpleNamespace(status="PreSubmitted", filled=0),
        )

    async def whatIfOrderAsync(self, contract: Stock, order: Order) -> SimpleNamespace:
        self.placed.append((contract, order))
        if self.what_if_error:
            code, message = self.what_if_error
            asyncio.get_running_loop().call_later(
                0.01,
                self.errorEvent.emit,
                7,
                code,
                message,
                contract,
            )
        return SimpleNamespace(status="PreSubmitted", warningText="")

    def openTrades(self) -> list[SimpleNamespace]:
        return self.open_trades

    def cancelOrder(self, order: Order) -> None:
        self.cancelled.append(order)


def broker_with(fake_ib: FakeIB) -> IBKRBroker:
    broker = IBKRBroker(lambda _message, _level: None)
    broker.ib = fake_ib  # type: ignore[assignment]
    return broker


@pytest.mark.asyncio
async def test_paper_connect_rejects_live_account() -> None:
    fake_ib = FakeIB(["U1234567"], connected=False)
    broker = broker_with(fake_ib)
    config = TradingConfig(mode=TradingMode.PAPER, account="U1234567")

    with pytest.raises(RuntimeError, match="paper account"):
        await broker.connect(config)

    assert fake_ib.disconnected is True


@pytest.mark.asyncio
async def test_live_connect_rejects_paper_account() -> None:
    fake_ib = FakeIB(["DUH450551"], connected=False)
    broker = broker_with(fake_ib)
    config = TradingConfig(mode=TradingMode.LIVE, account="DUH450551")

    with pytest.raises(RuntimeError, match="cannot run against"):
        await broker.connect(config)

    assert fake_ib.disconnected is True


@pytest.mark.asyncio
async def test_broker_builds_expected_moc_and_moo_orders() -> None:
    fake_ib = FakeIB()
    broker = broker_with(fake_ib)

    entry = await broker.place_moc("SPY", 1, "HDR-TEST")
    exit_order = await broker.place_moo("SPY", 1, "HDR-TEST-EXIT")

    assert entry.order_id == 100
    assert exit_order.order_id == 101
    _, moc = fake_ib.placed[0]
    assert (moc.action, moc.orderType, moc.totalQuantity, moc.tif, moc.orderRef) == (
        "BUY",
        "MOC",
        1,
        "DAY",
        "HDR-TEST",
    )
    _, moo = fake_ib.placed[1]
    assert (moo.action, moo.orderType, moo.totalQuantity, moo.tif, moo.orderRef) == (
        "SELL",
        "MKT",
        1,
        "OPG",
        "HDR-TEST-EXIT",
    )


@pytest.mark.asyncio
async def test_paper_order_test_uses_what_if_without_transmitting() -> None:
    fake_ib = FakeIB()
    broker = broker_with(fake_ib)

    result = await broker.validate_paper_order_path()

    assert result["transmitted"] is False
    _, order = fake_ib.placed[0]
    assert (order.action, order.orderType, order.totalQuantity, order.orderRef) == (
        "BUY",
        "MOC",
        1,
        "HDR-SELFTEST",
    )


@pytest.mark.asyncio
async def test_paper_order_test_surfaces_ibkr_rejection_event() -> None:
    fake_ib = FakeIB()
    fake_ib.what_if_error = (201, "Insufficient settled cash")
    broker = broker_with(fake_ib)

    with pytest.raises(RuntimeError, match=r"rejected.*201.*Insufficient settled cash"):
        await broker.validate_paper_order_path()

    assert fake_ib.errorEvent.handlers == []


@pytest.mark.asyncio
async def test_cancellation_protects_exit_and_unrelated_orders() -> None:
    fake_ib = FakeIB()
    broker = broker_with(fake_ib)
    entry = Order(orderId=1, orderRef="HDR-TEST")
    exit_order = Order(orderId=2, orderRef="HDR-TEST-EXIT")
    unrelated = Order(orderId=3, orderRef="OTHER")
    fake_ib.open_trades = [
        SimpleNamespace(order=entry),
        SimpleNamespace(order=exit_order),
        SimpleNamespace(order=unrelated),
    ]

    cancelled = await broker.cancel_strategy_orders("HDR-")

    assert cancelled == 1
    assert fake_ib.cancelled == [entry]
