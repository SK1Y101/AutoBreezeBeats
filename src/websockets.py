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
        self.logger.info(f"Callback registered: {callback}")
        self.callbacks.append(callback)

    def get_updates(self) -> list[Updates]:
        self.logger.debug("Fetching websocket updates")
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

        self.update_task: None | asyncio.Task = None

    async def start(self, interval: float = 0.1) -> None:
        if self.update_task and not self.update_task.done():
            self.logger.warn("Update task already active")
            return
        self.logger.info("Started update task")
        self.update_task = asyncio.create_task(
            self.update_loop(interval), name="Send websocket data"
        )

    async def update_loop(self, interval: float = 0.1) -> None:
        self.update_interval = interval
        self.logger.info(f"Starting update loop with interval {interval}s")
        try:
            while True:
                updates = self.notifier.get_updates()
                self.logger.debug(f"Sending updates: {updates}")
                for update in updates:
                    await self.broadcast(update, self.logger.getChild("update_loop"))
                self.logger.debug(f"Updates complete, waiting {interval}s")
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            self.logger.info("Update loop cancelled")
        except Exception as e:
            self.logger.error(f"Error during update: {e}")

    async def connect(self, websocket: WebSocket) -> None:
        self.logger.info(f"Client connecting {websocket}")
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        self.logger.info(f"Client disconnecting {websocket}")
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict, logger: Logger | None = None) -> None:
        (logger or self.logger).debug(f"Sending broadcast: {message}")
        for connection in self.active_connections:
            await connection.send_text(json.dumps(message))

    async def recieve_data(self, websocket: WebSocket) -> AsyncGenerator[Any, None]:
        async with self.keep_connected(websocket):
            while True:
                data = await websocket.receive_text()
                self.logger.info(f"Recieved data '{data}'")
                yield data
                await self.broadcast({"action": data})

    @asynccontextmanager
    async def keep_connected(self, websocket: WebSocket) -> AsyncGenerator[None, None]:
        await self.connect(websocket)
        try:
            yield
        except WebSocketDisconnect:
            self.disconnect(websocket)
