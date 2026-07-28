from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .models import (
    BacktestEstimate,
    BacktestRequest,
    BacktestResult,
    MidcapUniverse,
    RuntimeSnapshot,
    TradingConfig,
)
from .service import TradingService

RESOURCE_ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
ENV_FILE = Path(os.getenv("HALFREVERSAL_ENV_FILE", RESOURCE_ROOT / ".env"))
DATA_DIR = Path(os.getenv("HALFREVERSAL_DATA_DIR", RESOURCE_ROOT / "data"))
load_dotenv(ENV_FILE)
service = TradingService(RESOURCE_ROOT, data_dir=DATA_DIR)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await service.start()
    yield
    await service.stop()


APP_VERSION = "1.2.4"
app = FastAPI(title="Half-Day Reversal Control", version=APP_VERSION, lifespan=lifespan)


class ArmRequest(BaseModel):
    phrase: str


@app.get("/api/connector")
async def connector_identity() -> dict[str, str]:
    return {
        "product": "half-day-reversal",
        "version": APP_VERSION,
    }


@app.get("/api/status", response_model=RuntimeSnapshot)
async def get_status() -> RuntimeSnapshot:
    return service.snapshot()


@app.post("/api/connect")
async def connect() -> dict[str, str]:
    return await _handle(service.connect())


@app.post("/api/disconnect")
async def disconnect() -> dict[str, str]:
    return await _handle(service.disconnect())


@app.put("/api/config", response_model=TradingConfig)
async def update_config(config: TradingConfig) -> TradingConfig:
    return await _handle(service.update_config(config))


@app.post("/api/arm")
async def arm(request: ArmRequest) -> dict:
    try:
        return service.arm(request.phrase)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/disarm")
async def disarm() -> dict[str, str]:
    return service.disarm()


@app.post("/api/scan")
async def run_scan(execute: bool = Query(default=False)) -> dict:
    return await _handle(service.run_scan(execute=execute))


@app.post("/api/cancel")
async def cancel_orders() -> dict[str, int]:
    return await _handle(service.cancel_strategy_orders())


@app.post("/api/paper-order-test")
async def paper_order_test() -> dict:
    return await _handle(service.validate_paper_order_path())


@app.post("/api/backtest/estimate", response_model=BacktestEstimate)
async def estimate_backtest(request: BacktestRequest) -> BacktestEstimate:
    return await _handle(service.estimate_backtest(request))


@app.post("/api/backtest/run", response_model=BacktestResult)
async def run_backtest(request: BacktestRequest) -> BacktestResult:
    return await _handle(service.run_backtest(request))


@app.get("/api/backtest/universe/midcap", response_model=MidcapUniverse)
async def load_midcap_universe() -> MidcapUniverse:
    return await _handle(service.load_midcap_universe())


@app.get("/api/logs/download")
async def download_logs() -> FileResponse:
    return FileResponse(service.state.log_path, filename="half-day-reversal.log")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(
        RESOURCE_ROOT / "static" / "index.html",
        headers={"Cache-Control": "no-store, max-age=0"},
    )


app.mount("/static", StaticFiles(directory=RESOURCE_ROOT / "static"), name="static")


async def _handle(awaitable):
    try:
        return await awaitable
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
