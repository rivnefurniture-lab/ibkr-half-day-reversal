from __future__ import annotations

import pytest

from halfreversal.models import Quote, TradingConfig
from halfreversal.strategy import StrategyEngine


class FakeBroker:
    def __init__(self, quotes: list[Quote]) -> None:
        self.quotes = quotes

    async def get_quotes(self, symbols: list[str], batch_size: int) -> list[Quote]:
        assert symbols
        assert batch_size >= 10
        return self.quotes


def make_quotes(count: int) -> list[Quote]:
    return [
        Quote(symbol=f"STOCK{index}", open_price=100, current_price=80 + index)
        for index in range(count)
    ]


@pytest.mark.asyncio
async def test_scan_selects_bottom_decile_and_caps_position_size() -> None:
    config = TradingConfig(
        universe=[f"STOCK{index}" for index in range(20)],
        bottom_fraction=0.10,
        capital_fraction=0.90,
        max_position_fraction=0.10,
        max_positions=25,
    )
    engine = StrategyEngine(FakeBroker(make_quotes(20)))  # type: ignore[arg-type]

    result = await engine.scan(
        config,
        net_liquidation=100_000,
        available_funds=100_000,
    )

    selected = [row for row in result.rows if row.selected]
    assert result.selected_count == 2
    assert [row.symbol for row in selected] == ["STOCK0", "STOCK1"]
    assert all(row.target_value <= 10_000 for row in selected)
    assert result.coverage == 1


@pytest.mark.asyncio
async def test_scan_stops_when_data_coverage_is_too_low() -> None:
    symbols = [f"STOCK{index}" for index in range(20)]
    quotes = make_quotes(10) + [
        Quote(symbol=symbol, error="No data") for symbol in symbols[10:]
    ]
    config = TradingConfig(universe=symbols, min_data_coverage=0.75)
    engine = StrategyEngine(FakeBroker(quotes))  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="usable live data"):
        await engine.scan(
            config,
            net_liquidation=100_000,
            available_funds=100_000,
        )


@pytest.mark.asyncio
async def test_scan_limits_total_allocation_to_available_funds() -> None:
    config = TradingConfig(
        universe=[f"STOCK{index}" for index in range(20)],
        bottom_fraction=0.10,
        capital_fraction=0.90,
        max_position_fraction=0.25,
    )
    engine = StrategyEngine(FakeBroker(make_quotes(20)))  # type: ignore[arg-type]

    result = await engine.scan(
        config,
        net_liquidation=100_000,
        available_funds=10_000,
    )

    selected_value = sum(row.target_value for row in result.rows if row.selected)
    assert selected_value <= 9_000


def test_universe_is_normalized_and_deduplicated() -> None:
    config = TradingConfig(universe=[" aapl ", "AAPL", "brk.b"] + [f"S{i}" for i in range(9)])

    assert config.universe[:2] == ["AAPL", "BRK B"]
    assert config.universe.count("AAPL") == 1
