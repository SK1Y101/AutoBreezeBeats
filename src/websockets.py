from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from logging import Logger
from typing import Any, AsyncGenerator, Callable

from fastapi import WebSocket, WebSocketDisconnect

from .common import BreezeBaseClass

Updates = dict[str, Any]


class Notifier(BreezeBaseClass):
    def __init__(self, parent_logger: None | Logger = None) -> None:
        super().__init__("websocket-notifier", parent_logger)

        self.callbacks: list[Callable[[], Updates]] = []

    def register_callback(self, callback: Callable[[], Updates]) -> None:
        self.info(f"Callback registered: {callback}")
        self.callbacks.append(callback)

    def get_updates(self) -> list[Updates]:
        updates = []
        for callback in self.callbacks:
            if update := callback():
                updates.append(update)
        return updates


class WebSocketManager(BreezeBaseClass):
    def __init__(self, parent_logger: None | Logger = None) -> None:
        super().__init__("websocket", parent_logger)

        self.notifier = Notifier()
        self.active_connections: list[WebSocket] = []
        self.interval = 1

    async def connect(self, websocket: WebSocket) -> None:
        self.info(f"Client connecting {websocket}")
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        self.info(f"Client disconnecting {websocket}")
        self.active_connections.remove(websocket)

    async def broadcast(self, message: dict) -> None:
        self.info(f"Sending broadcast: {message}")
        for connection in self.active_connections:
            await connection.send_text(json.dumps(message))

    async def periodic_update(self) -> None:
        while True:
            updates = self.notifier.get_updates()
            for update in updates:
                await self.broadcast(update)
            await asyncio.sleep(self.interval)

    async def recieve_data(self, websocket: WebSocket) -> AsyncGenerator[Any, None]:
        async with self.keep_connected(websocket):
            while True:
                data = await websocket.receive_text()
                self.debug(f"Recieved {data}")
                yield data
                await self.broadcast({"action": data})

    @asynccontextmanager
    async def keep_connected(self, websocket: WebSocket) -> AsyncGenerator[None, None]:
        loop = asyncio.get_event_loop()
        loop.create_task(self.connect(websocket))
        try:
            yield
        except WebSocketDisconnect:
            self.disconnect(websocket)
