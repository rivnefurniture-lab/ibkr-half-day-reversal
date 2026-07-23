from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from halfreversal.backtest import calculate_backtest, parse_ishares_midcap_holdings
from halfreversal.models import BacktestEstimate, BacktestRequest


def test_calculate_backtest_ranks_losers_and_exits_next_open() -> None:
    symbols = [f"S{index}" for index in range(10)]
    rows = []
    timestamps = []
    for day, next_day in [("2026-07-20", False), ("2026-07-21", True)]:
        for index, symbol in enumerate(symbols):
            open_price = 100.0 if not next_day else 96.0 + index
            for clock, close_price in [
                ("09:30", open_price),
                ("15:42", 80.0 + index if not next_day else open_price),
                ("15:59", 90.0 + index if not next_day else open_price),
            ]:
                timestamps.append(pd.Timestamp(f"{day} {clock}", tz="America/New_York"))
                rows.append(
                    {
                        "symbol": symbol,
                        "open": open_price,
                        "high": close_price,
                        "low": close_price,
                        "close": close_price,
                    }
                )
    frame = pd.DataFrame(rows, index=pd.DatetimeIndex(timestamps, name="ts_event"))
    request = BacktestRequest(
        start_date=date(2026, 7, 20),
        end_date=date(2026, 7, 22),
        universe=symbols,
        bottom_fraction=0.10,
        capital_fraction=0.90,
        min_data_coverage=1,
        transaction_cost_bps=0,
    )
    estimate = BacktestEstimate(
        dataset="DBEQ.BASIC",
        schema_name="ohlcv-1m",
        start_date=date(2026, 7, 20),
        end_date=date(2026, 7, 22),
        symbol_count=10,
        estimated_cost_usd=0,
    )

    result = calculate_backtest(frame, request, estimate)

    assert result.trade_count == 1
    assert result.trades[0].symbol == "S0"
    assert result.trades[0].entry_price == 90
    assert result.trades[0].exit_price == 96
    assert result.total_return_pct == pytest.approx(6)


def test_backtest_request_rejects_reversed_dates() -> None:
    from pydantic import ValidationError

    try:
        BacktestRequest(start_date=date(2026, 7, 22), end_date=date(2026, 7, 20))
    except ValidationError as exc:
        assert "End date must be after" in str(exc)
    else:
        raise AssertionError("Expected invalid date range to fail")


def test_parse_ishares_midcap_holdings_filters_non_equities() -> None:
    equities = "\n".join(
        f'"S{index}","Stock {index}","EQUITY","Industrials","Equity"'
        for index in range(350)
    )
    text = (
        'iShares Core S&P Mid-Cap ETF Fund Holdings as of,"Jul 20, 2026"\n'
        '"Ticker","Name","Type","Sector","Asset Class"\n'
        f"{equities}\n"
        '"USD","USD CASH","CASH","Cash","Cash"\n'
    )

    universe = parse_ishares_midcap_holdings(text)

    assert universe.as_of == date(2026, 7, 20)
    assert universe.symbol_count == 350
    assert "USD" not in universe.symbols
