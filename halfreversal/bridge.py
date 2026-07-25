from __future__ import annotations

import asyncio
import base64
import json
import os
import ssl
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import certifi
import httpx
from dotenv import load_dotenv
from websockets.asyncio.client import connect

PROJECT_ROOT = Path(__file__).resolve().parent.parent

load_dotenv(Path(os.getenv("HALFREVERSAL_ENV_FILE", PROJECT_ROOT / ".env")))
StatusCallback = Callable[[str, bool], None]


def websocket_url(hosted_url: str) -> str:
    parts = urlsplit(hosted_url.rstrip("/"))
    scheme = "wss" if parts.scheme == "https" else "ws"
    return urlunsplit((scheme, parts.netloc, "/bridge/ws", "", ""))


def websocket_ssl_context(address: str) -> ssl.SSLContext | None:
    if not address.startswith("wss://"):
        return None
    return ssl.create_default_context(cafile=certifi.where())


async def run_connector(status_callback: StatusCallback | None = None) -> None:
    hosted_url = os.getenv("HOSTED_DASHBOARD_URL", "").strip()
    token = os.getenv("BRIDGE_TOKEN", "").strip()
    local_url = os.getenv("LOCAL_DASHBOARD_URL", "http://127.0.0.1:8765").rstrip("/")
    if not hosted_url:
        raise RuntimeError("HOSTED_DASHBOARD_URL is missing from .env")
    if len(token) < 32:
        raise RuntimeError("BRIDGE_TOKEN must contain at least 32 characters")

    address = websocket_url(hosted_url)
    ssl_context = websocket_ssl_context(address)
    retry_seconds = 1
    while True:
        try:
            async with connect(
                address,
                additional_headers={"Authorization": f"Bearer {token}"},
                ssl=ssl_context,
                open_timeout=15,
                ping_interval=20,
                ping_timeout=20,
                max_size=20 * 1024 * 1024,
            ) as websocket:
                message = "Hosted dashboard connector is online."
                print(message)
                if status_callback:
                    status_callback(message, True)
                retry_seconds = 1
                send_lock = asyncio.Lock()
                async with httpx.AsyncClient(timeout=360) as client:
                    tasks: set[asyncio.Task[None]] = set()
                    async for raw_message in websocket:
                        message = json.loads(raw_message)
                        task = asyncio.create_task(
                            _handle_request(
                                websocket,
                                send_lock,
                                client,
                                local_url,
                                message,
                            )
                        )
                        tasks.add(task)
                        task.add_done_callback(tasks.discard)
                    if tasks:
                        await asyncio.gather(*tasks, return_exceptions=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            detail = type(exc).__name__
            if "CERTIFICATE_VERIFY_FAILED" in str(exc):
                detail = "secure connection failed - install the latest connector"
            message = f"Connector offline ({detail}). Retrying in {retry_seconds}s."
            print(f"{message} ({exc})")
            if status_callback:
                status_callback(message, False)
            await asyncio.sleep(retry_seconds)
            retry_seconds = min(retry_seconds * 2, 15)


async def _handle_request(
    websocket: Any,
    send_lock: asyncio.Lock,
    client: httpx.AsyncClient,
    local_url: str,
    message: dict[str, Any],
) -> None:
    request_id = str(message.get("id", ""))
    path = str(message.get("path", "/api/status"))
    query = str(message.get("query", ""))
    url = f"{local_url}{path}"
    if query:
        url = f"{url}?{query}"
    headers = {}
    content_type = str(message.get("content_type", ""))
    if content_type:
        headers["content-type"] = content_type
    try:
        response = await client.request(
            str(message.get("method", "GET")),
            url,
            headers=headers,
            content=base64.b64decode(message.get("body", "")),
        )
        result = {
            "id": request_id,
            "status": response.status_code,
            "headers": {
                key: value
                for key, value in response.headers.items()
                if key.lower() in {"content-type", "content-disposition"}
            },
            "body": base64.b64encode(response.content).decode(),
        }
    except Exception as exc:
        result = {
            "id": request_id,
            "status": 502,
            "headers": {"content-type": "application/json"},
            "body": base64.b64encode(
                json.dumps({"detail": f"Local dashboard unavailable: {exc}"}).encode()
            ).decode(),
        }
    async with send_lock:
        await websocket.send(json.dumps(result))


def main() -> None:
    try:
        asyncio.run(run_connector())
    except KeyboardInterrupt:
        pass
    finally:
        with suppress(Exception):
            print("Hosted dashboard connector stopped.")


if __name__ == "__main__":
    main()
