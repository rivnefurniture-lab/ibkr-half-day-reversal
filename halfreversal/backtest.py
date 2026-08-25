from __future__ import annotations

import asyncio
import csv
import io
import math
import os
import re
import ssl
import urllib.request
from collections.abc import Callable
from datetime import date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

import certifi
import databento as db
import pandas as pd

from .models import (
    BacktestEstimate,
    BacktestRequest,
    BacktestResult,
    BacktestTrade,
    MidcapUniverse,
    TradingConfig,
)

DATASET = "DBEQ.BASIC"
SCHEMA = "ohlcv-1m"
NEW_YORK = ZoneInfo("America/New_York")
ISHARES_IJH_HOLDINGS_URL = (
    "https://www.ishares.com/us/products/239763/"
    "ishares-core-s-p-mid-cap-etf/latest-holdings.csv"
)
ISHARES_IJR_HOLDINGS_URL = (
    "https://www.ishares.com/us/products/239774/"
    "ishares-core-sp-smallcap-etf/latest-holdings.csv"
)
# Keyed by the value the dashboard sends; both files share the same layout.
INDEX_SOURCES = {
    "midcap400": (ISHARES_IJH_HOLDINGS_URL, "iShares IJH (tracks S&P MidCap 400)"),
    "smallcap600": (ISHARES_IJR_HOLDINGS_URL, "iShares IJR (tracks S&P SmallCap 600)"),
}
ISHARES_SYMBOL_ALIASES = {"MOGA": "MOG A"}
DATABENTO_SYMBOL_ALIASES = {"MOGA": "MOG.A", "MOG A": "MOG.A"}


class DatabentoBacktester:
    def __init__(self, log: Callable[[str, str], None]) -> None:
        self.log = log

    async def estimate(
        self,
        request: BacktestRequest,
        config: TradingConfig,
    ) -> BacktestEstimate:
        symbols = _databento_symbols(request.universe or config.universe)
        return await asyncio.to_thread(self._estimate_sync, request, symbols)

    async def run(
        self,
        request: BacktestRequest,
        config: TradingConfig,
    ) -> BacktestResult:
        symbols = _databento_symbols(request.universe or config.universe)
        estimate = await asyncio.to_thread(self._estimate_sync, request, symbols)
        if estimate.estimated_cost_usd > request.max_cost_usd:
            raise RuntimeError(
                f"Databento estimates ${estimate.estimated_cost_usd:.4f}, above the "
                f"${request.max_cost_usd:.2f} safety limit. Increase the limit only after review."
            )
        self.log(
            f"Downloading Databento history for {len(symbols)} symbols "
            f"({request.start_date} to {request.end_date}); estimated cost "
            f"${estimate.estimated_cost_usd:.4f}",
            "INFO",
        )
        frame = await asyncio.to_thread(self._download_sync, request, symbols)
        result = calculate_backtest(frame, request, estimate)
        self.log(
            f"Backtest complete: {result.trade_count} trades, "
            f"{result.total_return_pct:+.2f}% total return",
            "SUCCESS",
        )
        return result

    async def load_midcap_universe(self, index: str = "smallcap600") -> MidcapUniverse:
        return await asyncio.to_thread(self._load_midcap_universe_sync, index)

    @staticmethod
    def _client() -> db.Historical:
        key = os.getenv("DATABENTO_API_KEY", "").strip()
        if not key:
            raise RuntimeError("DATABENTO_API_KEY is not configured")
        return db.Historical(key)

    def _estimate_sync(
        self,
        request: BacktestRequest,
        symbols: list[str],
    ) -> BacktestEstimate:
        try:
            cost = self._client().metadata.get_cost(
                dataset=DATASET,
                symbols=symbols,
                schema=SCHEMA,
                stype_in="raw_symbol",
                start=request.start_date.isoformat(),
                end=request.end_date.isoformat(),
            )
        except Exception as exc:
            raise RuntimeError(f"Databento cost estimate failed: {exc}") from exc
        return BacktestEstimate(
            dataset=DATASET,
            schema_name=SCHEMA,
            start_date=request.start_date,
            end_date=request.end_date,
            symbol_count=len(symbols),
            estimated_cost_usd=float(cost),
        )

    def _download_sync(self, request: BacktestRequest, symbols: list[str]) -> pd.DataFrame:
        try:
            store = self._client().timeseries.get_range(
                dataset=DATASET,
                symbols=symbols,
                schema=SCHEMA,
                stype_in="raw_symbol",
                start=request.start_date.isoformat(),
                end=request.end_date.isoformat(),
            )
            return store.to_df()
        except Exception as exc:
            raise RuntimeError(f"Databento historical download failed: {exc}") from exc

    @staticmethod
    def _load_midcap_universe_sync(index: str = "smallcap600") -> MidcapUniverse:
        try:
            url, source = INDEX_SOURCES[index]
        except KeyError as exc:
            raise ValueError(f"Unsupported index universe: {index}") from exc
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "Half-Day-Reversal/0.1"},
        )
        # The packaged Mac app ships no system CA bundle, so the default context
        # fails with CERTIFICATE_VERIFY_FAILED. certifi is what the rest of the
        # app already uses for exactly this reason.
        context = ssl.create_default_context(cafile=certifi.where())
        try:
            with urllib.request.urlopen(request, timeout=25, context=context) as response:
                text = response.read().decode("utf-8-sig")
        except Exception as exc:
            raise RuntimeError(f"Could not load the current holdings: {exc}") from exc
        universe = parse_ishares_midcap_holdings(text)
        return universe.model_copy(update={"source": source})


def parse_ishares_midcap_holdings(text: str) -> MidcapUniverse:
    lines = text.splitlines()
    header_index = next(
        (
            index
            for index, line in enumerate(lines)
            if line.lstrip('"').startswith("Ticker")
        ),
        None,
    )
    if header_index is None:
        raise RuntimeError("The iShares holdings file did not contain a ticker table")
    symbols = []
    for row in csv.DictReader(io.StringIO("\n".join(lines[header_index:]))):
        ticker = (row.get("Ticker") or "").strip().upper()
        ticker = ISHARES_SYMBOL_ALIASES.get(ticker, ticker)
        asset_class = (row.get("Asset Class") or "").strip()
        if asset_class == "Equity" and re.fullmatch(
            r"[A-Z][A-Z0-9-]*(?: [A-Z])?",
            ticker,
        ):
            symbols.append(ticker)
    symbols = list(dict.fromkeys(symbols))
    if len(symbols) < 350:
        raise RuntimeError(
            f"The iShares holdings file returned only {len(symbols)} usable equity symbols"
        )
    date_match = re.search(r'Fund Holdings as of,"([A-Za-z]+ \d{1,2}, \d{4})"', text)
    as_of = (
        datetime.strptime(date_match.group(1), "%b %d, %Y").date()
        if date_match
        else None
    )
    return MidcapUniverse(
        source="iShares IJH (tracks S&P MidCap 400)",
        as_of=as_of,
        symbol_count=len(symbols),
        symbols=symbols,
    )


def calculate_backtest(
    frame: pd.DataFrame,
    request: BacktestRequest,
    estimate: BacktestEstimate,
    initial_equity: float = 100_000,
) -> BacktestResult:
    required = {"symbol", "open", "close"}
    missing = required.difference(frame.columns)
    if missing:
        raise RuntimeError(f"Historical data is missing columns: {', '.join(sorted(missing))}")
    if frame.empty:
        raise RuntimeError("Databento returned no historical bars for this request")

    bars = frame.reset_index()
    timestamp_column = "ts_event" if "ts_event" in bars.columns else bars.columns[0]
    bars[timestamp_column] = pd.to_datetime(bars[timestamp_column], utc=True)
    bars["local_time"] = bars[timestamp_column].dt.tz_convert(NEW_YORK)
    bars["session_date"] = bars["local_time"].dt.date
    bars = bars[
        (bars["local_time"].dt.time >= time(9, 30))
        & (bars["local_time"].dt.time < time(16, 1))
    ].sort_values(["session_date", "symbol", "local_time"])

    daily: dict[date, dict[str, dict[str, float]]] = {}
    for (session_date, symbol), group in bars.groupby(["session_date", "symbol"], sort=True):
        valid = group.dropna(subset=["open", "close"])
        if valid.empty:
            continue
        last_timestamp = valid["local_time"].iloc[-1]
        signal_cutoff = (
            last_timestamp
            + pd.Timedelta(minutes=1)
            - pd.Timedelta(minutes=request.scan_minutes_before_close)
        )
        signal_bars = valid[valid["local_time"] <= signal_cutoff]
        if signal_bars.empty:
            continue
        open_price = _positive_float(valid["open"].iloc[0])
        signal_price = _positive_float(signal_bars["close"].iloc[-1])
        entry_price = _positive_float(valid["close"].iloc[-1])
        if open_price is None or signal_price is None or entry_price is None:
            continue
        daily.setdefault(session_date, {})[str(symbol)] = {
            "open": open_price,
            "signal": signal_price,
            "entry": entry_price,
        }

    session_dates = sorted(daily)
    trades: list[BacktestTrade] = []
    daily_returns: list[float] = []
    skipped = 0
    equity = initial_equity
    peak = equity
    max_drawdown = 0.0

    for index, signal_date in enumerate(session_dates[:-1]):
        exit_date = session_dates[index + 1]
        candidates = []
        for symbol, prices in daily[signal_date].items():
            exit_prices = daily[exit_date].get(symbol)
            if not exit_prices or prices["signal"] < request.min_price:
                continue
            signal_return = prices["signal"] / prices["open"] - 1
            candidates.append((signal_return, symbol, prices, exit_prices["open"]))
        coverage = len(candidates) / estimate.symbol_count
        if not candidates or coverage < request.min_data_coverage:
            skipped += 1
            continue
        candidates.sort(key=lambda item: (item[0], item[1]))
        selected_count = min(
            request.max_positions,
            max(1, math.ceil(len(candidates) * request.bottom_fraction)),
        )
        selected = candidates[:selected_count]
        session_trade_returns = []
        for signal_return, symbol, prices, exit_price in selected:
            trade_return = (
                exit_price / prices["entry"]
                - 1
                - 2 * request.transaction_cost_bps / 10_000
            )
            session_trade_returns.append(trade_return)
            trades.append(
                BacktestTrade(
                    signal_date=signal_date,
                    exit_date=exit_date,
                    symbol=symbol,
                    signal_return_pct=signal_return * 100,
                    entry_price=prices["entry"],
                    exit_price=exit_price,
                    return_pct=trade_return * 100,
                )
            )
        portfolio_return = (
            sum(session_trade_returns) / len(session_trade_returns) * request.capital_fraction
        )
        daily_returns.append(portfolio_return)
        equity *= 1 + portfolio_return
        peak = max(peak, equity)
        max_drawdown = min(max_drawdown, equity / peak - 1)

    if not trades:
        raise RuntimeError(
            "No testable trades remained after data coverage and price filters. "
            "Try a wider date range or a more complete universe."
        )
    elapsed_years = max((estimate.end_date - estimate.start_date).days / 365.25, 1 / 365.25)
    annualized = (equity / initial_equity) ** (1 / elapsed_years) - 1
    trade_returns = [trade.return_pct for trade in trades]
    return BacktestResult(
        estimate=estimate,
        sessions=len(session_dates),
        sessions_traded=len(daily_returns),
        trade_count=len(trades),
        total_return_pct=(equity / initial_equity - 1) * 100,
        annualized_return_pct=annualized * 100,
        max_drawdown_pct=max_drawdown * 100,
        win_rate_pct=sum(value > 0 for value in trade_returns) / len(trade_returns) * 100,
        average_trade_pct=sum(trade_returns) / len(trade_returns),
        ending_equity=equity,
        skipped_sessions=skipped,
        trades=trades[-250:],
    )


def _positive_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 and math.isfinite(number) else None


def _databento_symbols(symbols: list[str]) -> list[str]:
    return [DATABENTO_SYMBOL_ALIASES.get(symbol, symbol) for symbol in symbols]
