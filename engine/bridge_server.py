"""The team hub's HTTP transport (#79): `bridge-engine --serve`.

An optional `[server]` extra (FastAPI, uvicorn), imported only by `main.py`
when `--serve` is given, excluded from `bridge-engine.spec`, and never
imported by `bridge_service.py` (a test pins that), so the desktop sidecar
carries no server and no network path (DECISIONS 2026-09-11, 2026-10-15).

The envelope is the stdio one: `POST /rpc` with `{id, method, params,
session}` returns exactly what `BridgeEngine.handle_request` returns over
stdio, so `bridgeClient.ts` can swap `invoke("engine_call")` for `fetch`
without the protocol changing. `session` keeps two clients on two projects
apart (`BridgeEngine._activate_session`).

Requests are serialised by one lock. The engine's per-session state is
swapped per request and its dispatcher assumes one request at a time, as
the stdio loop does; job threads still run in parallel. Join codes, device
tokens and `authorize()` per hub user are #80; until then the server binds
to 127.0.0.1 by default, and `--host` is the administrator's explicit
choice to listen on the LAN.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from bridge_service import BridgeEngine
from greek_room_engine.protocol import EngineRequest, EngineResponse
from tc_ai_bridge.secret_store import AppSettings


def create_app(engine: BridgeEngine) -> FastAPI:
    app = FastAPI(title="Bridge hub", docs_url=None, redoc_url=None, openapi_url=None)
    lock = threading.Lock()

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"status": "ok"}

    @app.post("/rpc")
    async def rpc(request: Request) -> JSONResponse:
        try:
            body = await request.json()
            engine_request = EngineRequest.from_dict(body)
        except Exception as exc:  # noqa: BLE001 -- a bad body is the client's error
            return JSONResponse(EngineResponse.fail("__unknown__", "bad_request", str(exc)).to_dict())
        with lock:
            try:
                response = engine.handle_request(engine_request)
            except Exception as exc:  # noqa: BLE001 -- same defence as the stdio loop
                response = EngineResponse.fail(engine_request.id, "internal_error", str(exc))
        return JSONResponse(response.to_dict())

    return app


def build_engine(data_dir: str | Path = "") -> BridgeEngine:
    """An engine whose settings, workspace and managed projects live under
    `data_dir` (the hub's own folder), or the desktop default when empty."""
    if data_dir:
        root = Path(data_dir).resolve()
        root.mkdir(parents=True, exist_ok=True)
        return BridgeEngine(settings=AppSettings(path=root / "settings.json"))
    return BridgeEngine()


def serve(data_dir: str = "", host: str = "127.0.0.1", port: int = 8765) -> None:
    import uvicorn

    uvicorn.run(create_app(build_engine(data_dir)), host=host, port=int(port), log_level="warning")
