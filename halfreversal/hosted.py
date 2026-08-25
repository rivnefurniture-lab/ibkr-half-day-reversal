from __future__ import annotations

import asyncio
import base64
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .backtest import load_index_universe
from .models import MidcapUniverse
from .version import APP_VERSION

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RESPONSE_TIMEOUT_SECONDS = 360


@dataclass
class WorkerConnection:
    websocket: WebSocket
    pending: dict[str, asyncio.Future[dict[str, Any]]] = field(default_factory=dict)
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


app = FastAPI(title="Half-Day Reversal Hosted Relay", version=APP_VERSION)
worker: WorkerConnection | None = None
worker_guard = asyncio.Lock()


def configured_token() -> str:
    token = os.getenv("BRIDGE_TOKEN", "").strip()
    if len(token) < 32:
        raise RuntimeError("BRIDGE_TOKEN must contain at least 32 characters")
    return token


def token_matches(candidate: str) -> bool:
    try:
        expected = configured_token()
    except RuntimeError:
        return False
    return secrets.compare_digest(candidate, expected)


@app.get("/health")
async def health() -> dict[str, bool]:
    return {"ok": True, "worker_connected": worker is not None}


@app.get("/host/config")
async def host_config() -> dict[str, bool]:
    return {"hosted": True, "worker_connected": worker is not None}


@app.get("/host/universe", response_model=MidcapUniverse)
async def host_universe(request: Request, index: str = "smallcap600") -> MidcapUniverse:
    """Load public index holdings without requiring a connector upgrade."""
    _require_browser_token(request)
    try:
        return await load_index_universe(index)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.websocket("/bridge/ws")
async def bridge_socket(websocket: WebSocket) -> None:
    authorization = websocket.headers.get("authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token_matches(token):
        await websocket.close(code=1008, reason="Invalid bridge token")
        return
    await websocket.accept()
    connection = WorkerConnection(websocket=websocket)
    global worker
    async with worker_guard:
        previous = worker
        worker = connection
    if previous is not None:
        await previous.websocket.close(code=1012, reason="Replaced by a new connector")
    try:
        while True:
            message = await websocket.receive_json()
            request_id = str(message.get("id", ""))
            future = connection.pending.pop(request_id, None)
            if future is not None and not future.done():
                future.set_result(message)
    except WebSocketDisconnect:
        pass
    finally:
        async with worker_guard:
            if worker is connection:
                worker = None
        for future in connection.pending.values():
            if not future.done():
                future.set_exception(RuntimeError("The local TWS connector disconnected"))


@app.api_route(
    "/api/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
)
async def proxy_api(path: str, request: Request) -> Response:
    _require_browser_token(request)
    connection = worker
    if connection is None:
        raise HTTPException(
            status_code=503,
            detail="Scott's local TWS connector is offline. Start it beside TWS and retry.",
        )
    request_id = uuid4().hex
    future = asyncio.get_running_loop().create_future()
    connection.pending[request_id] = future
    body = await request.body()
    payload = {
        "id": request_id,
        "method": request.method,
        "path": f"/api/{path}",
        "query": request.url.query,
        "content_type": request.headers.get("content-type", ""),
        "body": base64.b64encode(body).decode(),
    }
    try:
        async with connection.send_lock:
            await connection.websocket.send_json(payload)
        result = await asyncio.wait_for(future, timeout=RESPONSE_TIMEOUT_SECONDS)
    except TimeoutError as exc:
        connection.pending.pop(request_id, None)
        raise HTTPException(status_code=504, detail="The local connector timed out") from exc
    except Exception as exc:
        connection.pending.pop(request_id, None)
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    response_body = base64.b64decode(result.get("body", ""))
    headers = {
        key: value
        for key, value in result.get("headers", {}).items()
        if key.lower() in {"content-type", "content-disposition"}
    }
    return Response(
        content=response_body,
        status_code=int(result.get("status", 500)),
        headers=headers,
    )


def _require_browser_token(request: Request) -> None:
    authorization = request.headers.get("authorization", "")
    scheme, _, candidate = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token_matches(candidate):
        raise HTTPException(status_code=401, detail="Enter the hosted dashboard access key")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(
        PROJECT_ROOT / "static" / "index.html",
        headers={"Cache-Control": "no-store, max-age=0"},
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


app.mount("/static", StaticFiles(directory=PROJECT_ROOT / "static"), name="static")
