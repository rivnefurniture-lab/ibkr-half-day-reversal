from __future__ import annotations

import math
from datetime import datetime

from .broker import IBKRBroker
from .models import RankRow, ScanResult, TradingConfig


class StrategyEngine:
    def __init__(self, broker: IBKRBroker) -> None:
        self.broker = broker

    async def scan(
        self,
        config: TradingConfig,
        net_liquidation: float,
        available_funds: float,
    ) -> ScanResult:
        quotes = await self.broker.get_quotes(config.universe, config.quote_batch_size)
        valid = [
            quote
            for quote in quotes
            if quote.error is None
            and quote.open_price is not None
            and quote.current_price is not None
            and quote.current_price >= config.min_price
        ]
        coverage = len(valid) / len(config.universe)
        if coverage < config.min_data_coverage:
            raise RuntimeError(
                f"Only {coverage:.0%} of the universe has usable live data; "
                f"minimum is {config.min_data_coverage:.0%}"
            )
        if net_liquidation <= 0:
            raise RuntimeError("IBKR did not return a positive net liquidation value")
        if available_funds <= 0:
            raise RuntimeError("IBKR did not return positive available funds")

        ranked_quotes = sorted(
            valid,
            key=lambda quote: quote.current_price / quote.open_price - 1,  # type: ignore[operator]
        )
        desired_count = max(1, math.floor(len(ranked_quotes) * config.bottom_fraction))
        selected_count = min(desired_count, config.max_positions)
        deployable_capital = min(
            net_liquidation * config.capital_fraction,
            available_funds * 0.90,
        )
        allocation_per_name = min(
            deployable_capital / selected_count,
            net_liquidation * config.max_position_fraction,
        )

        rows = []
        for index, quote in enumerate(ranked_quotes, start=1):
            selected = index <= selected_count
            current_price = quote.current_price or 0
            target_quantity = math.floor(allocation_per_name / current_price) if selected else 0
            rows.append(
                RankRow(
                    rank=index,
                    symbol=quote.symbol,
                    open_price=quote.open_price or 0,
                    current_price=current_price,
                    return_pct=(current_price / (quote.open_price or 1) - 1) * 100,
                    selected=selected and target_quantity > 0,
                    target_quantity=target_quantity,
                    target_value=target_quantity * current_price,
                )
            )

        actual_selected_count = sum(row.selected for row in rows)
        if actual_selected_count == 0:
            raise RuntimeError("No selected stock can be purchased with the current allocation")
        return ScanResult(
            scanned_at=datetime.now(),
            universe_size=len(config.universe),
            valid_quotes=len(valid),
            coverage=coverage,
            selected_count=actual_selected_count,
            rows=rows,
        )
