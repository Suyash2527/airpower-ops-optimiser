"""WebSocket hub (API_SPEC "WebSocket /ws"). Server -> client messages are JSON
`{type, ts, data}`; a client chooses a scenario with `{type: "subscribe", scenario_id}` and then
receives that scenario's messages. Request handlers run in worker threads, so `publish` is
thread-safe: it hands the message to the event loop captured at start-up."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import WebSocket

from app.core.clock import utcnow

MESSAGE_TYPES = (
    "state.updated", "event.created", "plan.created", "plan.approved", "proposal.created",
    "proposal.updated", "alert.created", "fusion.conflict",
)


class Hub:
    def __init__(self) -> None:
        self._subs: dict[WebSocket, str | None] = {}
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self) -> None:
        self._loop = asyncio.get_running_loop()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._subs[ws] = None

    def disconnect(self, ws: WebSocket) -> None:
        self._subs.pop(ws, None)

    def subscribe(self, ws: WebSocket, scenario_id: str) -> None:
        self._subs[ws] = scenario_id

    @property
    def n_clients(self) -> int:
        return len(self._subs)

    def publish(self, scenario_id: str, type_: str, data: dict[str, Any]) -> None:
        """Queue a message for every client subscribed to `scenario_id` (no-op without a loop)."""
        if type_ not in MESSAGE_TYPES:
            raise ValueError(f"unknown message type {type_!r}")
        if self._loop is None or self._loop.is_closed():
            return
        message = {"type": type_, "ts": utcnow().isoformat(), "data": data}
        asyncio.run_coroutine_threadsafe(self._send(scenario_id, message), self._loop)

    async def _send(self, scenario_id: str, message: dict[str, Any]) -> None:
        for ws, sid in list(self._subs.items()):
            if sid != scenario_id:
                continue
            try:
                await ws.send_json(message)
            except Exception:  # a dead socket must not stop the others
                self._subs.pop(ws, None)
