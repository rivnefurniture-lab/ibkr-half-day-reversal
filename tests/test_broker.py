from __future__ import annotations

from types import SimpleNamespace

import pytest
from ib_async import Order, Stock

from halfreversal.broker import IBKRBroker
from halfreversal.models import TradingConfig, TradingMode


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
