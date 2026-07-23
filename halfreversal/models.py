from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

DEFAULT_UNIVERSE = [
    "AAPL",
    "ABBV",
    "ABT",
    "ADBE",
    "AMD",
    "AMGN",
    "AMZN",
    "AVGO",
    "AXP",
    "BA",
    "BAC",
    "BKNG",
    "BLK",
    "CAT",
    "CMCSA",
    "COF",
    "COP",
    "COST",
    "CRM",
    "CSCO",
    "CVX",
    "DE",
    "DIS",
    "GE",
    "GILD",
    "GOOG",
    "GOOGL",
    "GS",
    "HD",
    "HON",
    "IBM",
    "INTC",
    "INTU",
    "ISRG",
    "JNJ",
    "JPM",
    "KO",
    "LIN",
    "LLY",
    "LOW",
    "MA",
    "MCD",
    "MDLZ",
    "META",
    "MMM",
    "MRK",
    "MS",
    "MSFT",
    "MU",
    "NFLX",
    "NKE",
    "NOW",
    "NVDA",
    "ORCL",
    "PEP",
    "PFE",
    "PG",
    "PM",
    "QCOM",
    "RTX",
    "SBUX",
    "SCHW",
    "SPGI",
    "T",
    "TGT",
    "TMO",
    "TMUS",
    "TSLA",
    "TXN",
    "UBER",
    "UNH",
    "UPS",
    "V",
    "VZ",
    "WFC",
    "WMT",
    "XOM",
]


class TradingMode(StrEnum):
    DRY_RUN = "dry_run"
    PAPER = "paper"
    LIVE = "live"


class TradingConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = Field(default=7497, ge=1, le=65535)
    client_id: int = Field(default=17, ge=0, le=9999)
    account: str = ""
    mode: TradingMode = TradingMode.DRY_RUN
    auto_enabled: bool = False
    scan_minutes_before_close: int = Field(default=18, ge=16, le=120)
    bottom_fraction: float = Field(default=0.10, gt=0, le=0.5)
    capital_fraction: float = Field(default=0.01, gt=0, le=0.95)
    max_position_fraction: float = Field(default=0.01, gt=0, le=0.25)
    max_positions: int = Field(default=1, ge=1, le=100)
    min_price: float = Field(default=5.0, ge=1)
    min_data_coverage: float = Field(default=0.75, ge=0.5, le=1)
    quote_batch_size: int = Field(default=80, ge=10, le=100)
    allow_delayed_data_in_dry_run: bool = True
    allow_delayed_data_in_paper: bool = True
    universe: list[str] = Field(default_factory=lambda: DEFAULT_UNIVERSE.copy())

    @field_validator("universe")
    @classmethod
    def normalize_universe(cls, value: list[str]) -> list[str]:
        normalized = []
        seen = set()
        for raw_symbol in value:
            symbol = raw_symbol.strip().upper().replace(".", " ")
            if symbol and symbol not in seen:
                seen.add(symbol)
                normalized.append(symbol)
        if len(normalized) < 10:
            raise ValueError("The universe must contain at least 10 unique symbols")
        return normalized

    @model_validator(mode="after")
    def validate_position_budget(self) -> TradingConfig:
        if self.max_position_fraction > self.capital_fraction:
            raise ValueError("Maximum position size cannot exceed the total capital allocation")
        return self


class Quote(BaseModel):
    symbol: str
    open_price: float | None = None
    current_price: float | None = None
    error: str | None = None


class RankRow(BaseModel):
    rank: int
    symbol: str
    open_price: float
    current_price: float
    return_pct: float
    selected: bool = False
    target_quantity: int = 0
    target_value: float = 0


class OrderView(BaseModel):
    order_id: int | None = None
    symbol: str
    side: Literal["BUY", "SELL"]
    order_type: Literal["MOC", "MOO"]
    quantity: int
    status: str
    reference: str
    created_at: datetime = Field(default_factory=datetime.now)


class PositionView(BaseModel):
    symbol: str
    quantity: float
    average_cost: float
    market_value: float | None = None


class AccountSnapshot(BaseModel):
    account: str = ""
    net_liquidation: float = 0
    available_funds: float = 0
    positions: list[PositionView] = Field(default_factory=list)


class LogView(BaseModel):
    timestamp: datetime = Field(default_factory=datetime.now)
    level: Literal["INFO", "WARNING", "ERROR", "SUCCESS"] = "INFO"
    message: str


class ScanResult(BaseModel):
    scanned_at: datetime
    universe_size: int
    valid_quotes: int
    coverage: float
    selected_count: int
    rows: list[RankRow]


class RuntimeSnapshot(BaseModel):
    connected: bool
    connection_label: str
    mode: TradingMode
    armed: bool
    armed_until: datetime | None
    auto_enabled: bool
    next_run_at: datetime | None
    market_status: str
    last_scan_at: datetime | None
    last_execution_date: str | None
    account: AccountSnapshot
    rankings: list[RankRow]
    orders: list[OrderView]
    logs: list[LogView]
    config: TradingConfig


class BacktestRequest(BaseModel):
    start_date: date
    end_date: date
    universe: list[str] | None = None
    max_cost_usd: float = Field(default=1.0, ge=0, le=100)
    transaction_cost_bps: float = Field(default=5.0, ge=0, le=100)
    scan_minutes_before_close: int = Field(default=18, ge=16, le=120)
    bottom_fraction: float = Field(default=0.10, gt=0, le=0.5)
    capital_fraction: float = Field(default=1.0, gt=0, le=1)
    max_positions: int = Field(default=500, ge=1, le=500)
    min_price: float = Field(default=5.0, ge=1)
    min_data_coverage: float = Field(default=0.75, ge=0.5, le=1)

    @field_validator("universe")
    @classmethod
    def normalize_backtest_universe(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return TradingConfig.normalize_universe(value)

    @model_validator(mode="after")
    def validate_dates(self) -> BacktestRequest:
        if self.end_date <= self.start_date:
            raise ValueError("End date must be after the start date")
        if (self.end_date - self.start_date).days > 366:
            raise ValueError("A single backtest is limited to 366 calendar days")
        return self


class BacktestEstimate(BaseModel):
    dataset: str
    schema_name: str
    start_date: date
    end_date: date
    symbol_count: int
    estimated_cost_usd: float


class BacktestTrade(BaseModel):
    signal_date: date
    exit_date: date
    symbol: str
    signal_return_pct: float
    entry_price: float
    exit_price: float
    return_pct: float


class BacktestResult(BaseModel):
    estimate: BacktestEstimate
    sessions: int
    sessions_traded: int
    trade_count: int
    total_return_pct: float
    annualized_return_pct: float
    max_drawdown_pct: float
    win_rate_pct: float
    average_trade_pct: float
    ending_equity: float
    skipped_sessions: int
    trades: list[BacktestTrade]


class MidcapUniverse(BaseModel):
    source: str
    as_of: date | None
    symbol_count: int
    symbols: list[str]
