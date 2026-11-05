from __future__ import annotations

import asyncio
import uuid
from typing import Self

import aiohttp


class TransportError(RuntimeError):
    pass


def authorization(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"} if token else {}


class WebSocketTransport:
    def __init__(self, session: aiohttp.ClientSession, config: dict):
        self.session = session
        self.config = config
        self.socket: aiohttp.ClientWebSocketResponse | None = None
        self.reader: asyncio.Task | None = None
        self.pending: dict[str, asyncio.Future] = {}
        self.events: asyncio.Queue = asyncio.Queue()

    async def __aenter__(self) -> Self:
        self.socket = await self.session.ws_connect(
            self.config["ws_url"],
            headers=authorization(self.config["ws_token"]),
            heartbeat=30,
        )
        self.reader = asyncio.create_task(self._read())
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        await self.socket.close()
        await self.reader

    @property
    def connected(self) -> bool:
        return self.socket is not None and not self.socket.closed

    async def _read(self) -> None:
        try:
            async for message in self.socket:
                if message.type != aiohttp.WSMsgType.TEXT:
                    if message.type == aiohttp.WSMsgType.ERROR:
                        raise self.socket.exception() or TransportError(
                            "WebSocket 错误"
                        )
                    continue
                try:
                    payload = message.json()
                except ValueError:
                    continue
                if not isinstance(payload, dict):
                    continue
                echo = payload.get("echo")
                future = self.pending.get(str(echo)) if echo is not None else None
                if future is not None and not future.done():
                    future.set_result(payload)
                elif payload.get("post_type"):
                    await self.events.put(payload)
        finally:
            for future in self.pending.values():
                if not future.done():
                    future.set_exception(TransportError("WebSocket 已断开"))
            await self.events.put(None)

    async def action(self, name: str, params: dict) -> object:
        if not self.connected:
            raise TransportError("WebSocket 未连接")
        echo = uuid.uuid4().hex
        future = asyncio.get_running_loop().create_future()
        self.pending[echo] = future
        try:
            await self.socket.send_json(
                {"action": name, "params": params, "echo": echo}
            )
            payload = await asyncio.wait_for(future, 30)
        finally:
            self.pending.pop(echo, None)
        if payload.get("status") != "ok" or payload.get("retcode") != 0:
            raise TransportError(
                f"{name} 失败: {payload.get('wording') or payload.get('retcode')}"
            )
        return payload.get("data")
