from __future__ import annotations

import asyncio
import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ib_async import IB, Order, Stock, Trade

from .models import AccountSnapshot, PositionView, Quote, TradingConfig


@dataclass(slots=True)
class SubmittedOrder:
    order_id: int
    status: str
    trade: Trade


class IBKRBroker:
    def __init__(self, log: Callable[[str, str], None]) -> None:
        self.ib = IB()
        self.log = log
        self._account = ""
        self.ib.disconnectedEvent += self._on_disconnected

    @property
    def connected(self) -> bool:
        return self.ib.isConnected()

    @property
    def account(self) -> str:
        return self._account

    async def connect(self, config: TradingConfig) -> str:
        if self.connected:
            return self._account
        self.log(f"Connecting to IBKR at {config.host}:{config.port}...", "INFO")
        await self.ib.connectAsync(
            config.host,
            config.port,
            clientId=config.client_id,
            account=config.account,
            timeout=8,
            readonly=False,
        )
        accounts = self.ib.managedAccounts()
        if config.account and config.account not in accounts:
            self.ib.disconnect()
            raise RuntimeError(f"Account {config.account} is not available to this IBKR login")
        self._account = config.account or (accounts[0] if accounts else "")
        if not self._account:
            self.ib.disconnect()
            raise RuntimeError("IBKR connected but did not return an account")
        if config.mode.value == "paper" and not self._account.upper().startswith("DU"):
            self.ib.disconnect()
            raise RuntimeError(
                "Paper mode requires an IBKR paper account (normally beginning with DU)"
            )
        if config.mode.value == "live" and self._account.upper().startswith("DU"):
            self.ib.disconnect()
            raise RuntimeError("Live mode cannot run against an IBKR paper account")
        delayed_requested = (
            config.mode.value == "dry_run" and config.allow_delayed_data_in_dry_run
        ) or (config.mode.value == "paper" and config.allow_delayed_data_in_paper)
        market_data_type = 3 if delayed_requested else 1
        self.ib.reqMarketDataType(market_data_type)
        return self._account

    def disconnect(self) -> None:
        if self.connected:
            self.ib.disconnect()

    async def get_account_snapshot(self) -> AccountSnapshot:
        if not self.connected:
            return AccountSnapshot()
        values = self.ib.accountValues(self._account)
        value_map: dict[str, float] = {}
        for item in values:
            if item.tag in {"NetLiquidation", "AvailableFunds"} and item.currency in {
                "BASE",
                "USD",
            }:
                try:
                    value_map[item.tag] = float(item.value)
                except ValueError:
                    continue

        positions = []
        for position in self.ib.positions(self._account):
            if position.contract.secType != "STK" or not position.position:
                continue
            positions.append(
                PositionView(
                    symbol=position.contract.symbol,
                    quantity=float(position.position),
                    average_cost=float(position.avgCost),
                )
            )
        return AccountSnapshot(
            account=self._account,
            net_liquidation=value_map.get("NetLiquidation", 0),
            available_funds=value_map.get("AvailableFunds", 0),
            positions=positions,
        )

    async def get_quotes(self, symbols: list[str], batch_size: int) -> list[Quote]:
        if not self.connected:
            raise RuntimeError("IBKR is not connected")
        results: list[Quote] = []
        for offset in range(0, len(symbols), batch_size):
            batch = symbols[offset : offset + batch_size]
            contracts = [Stock(symbol, "SMART", "USD") for symbol in batch]
            qualified = await self.ib.qualifyContractsAsync(*contracts)
            qualified_by_symbol = {contract.symbol: contract for contract in qualified}
            missing = [symbol for symbol in batch if symbol not in qualified_by_symbol]
            results.extend(Quote(symbol=symbol, error="Contract not found") for symbol in missing)
            if not qualified:
                continue
            tickers = await self.ib.reqTickersAsync(*qualified)
            ticker_by_symbol = {ticker.contract.symbol: ticker for ticker in tickers}
            for symbol in batch:
                if symbol not in qualified_by_symbol:
                    continue
                ticker = ticker_by_symbol.get(symbol)
                if ticker is None:
                    results.append(Quote(symbol=symbol, error="No quote returned"))
                    continue
                open_price = self._finite_price(getattr(ticker, "open", None))
                current_price = self._finite_price(ticker.marketPrice())
                if current_price is None:
                    current_price = self._finite_price(getattr(ticker, "last", None))
                error = None
                if open_price is None:
                    error = "Opening price unavailable"
                elif current_price is None:
                    error = "Current price unavailable"
                results.append(
                    Quote(
                        symbol=symbol,
                        open_price=open_price,
                        current_price=current_price,
                        error=error,
                    )
                )
            if offset + batch_size < len(symbols):
                await asyncio.sleep(0.25)
        return results

    async def place_moc(self, symbol: str, quantity: int, reference: str) -> SubmittedOrder:
        contract = await self._qualified_stock(symbol)
        order = Order(
            action="BUY",
            orderType="MOC",
            totalQuantity=quantity,
            tif="DAY",
            orderRef=reference,
        )
        trade = self.ib.placeOrder(contract, order)
        await asyncio.sleep(0.2)
        return SubmittedOrder(trade.order.orderId, trade.orderStatus.status, trade)

    async def place_moo(self, symbol: str, quantity: int, reference: str) -> SubmittedOrder:
        contract = await self._qualified_stock(symbol)
        order = Order(
            action="SELL",
            orderType="MKT",
            totalQuantity=quantity,
            tif="OPG",
            orderRef=reference,
        )
        trade = self.ib.placeOrder(contract, order)
        await asyncio.sleep(0.2)
        return SubmittedOrder(trade.order.orderId, trade.orderStatus.status, trade)

    async def cancel_strategy_orders(self, reference_prefix: str) -> int:
        cancelled = 0
        for trade in self.ib.openTrades():
            reference = trade.order.orderRef or ""
            if reference.startswith(reference_prefix) and not reference.endswith("-EXIT"):
                self.ib.cancelOrder(trade.order)
                cancelled += 1
        await asyncio.sleep(0.25)
        return cancelled

    async def _qualified_stock(self, symbol: str) -> Stock:
        contracts = await self.ib.qualifyContractsAsync(Stock(symbol, "SMART", "USD"))
        if not contracts:
            raise RuntimeError(f"IBKR could not qualify {symbol}")
        return contracts[0]

    def _on_disconnected(self) -> None:
        self.log("IBKR connection closed", "WARNING")

    @staticmethod
    def _finite_price(value: Any) -> float | None:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if number > 0 and math.isfinite(number) else None
