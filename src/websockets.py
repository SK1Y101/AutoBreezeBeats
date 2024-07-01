from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import timedelta
from logging import Logger
from typing import Any, AsyncGenerator, Callable

from fastapi import WebSocket, WebSocketDisconnect

from .common import DEFAULT_INTERVAL, BreezeBaseClass

Updates = dict[str, Any]


class Notifier(BreezeBaseClass):
    def __init__(self, parent_logger: None | Logger = None) -> None:
        super().__init__("websocket-notifier", parent_logger)

        self.callbacks: list[Callable[[], Updates]] = []

    def register_callback(self, callback: Callable[[], Updates]) -> None:
        self.log(self.logger.info, f"Callback registered: {callback}")
        self.callbacks.append(callback)

    def get_updates(self) -> list[Updates]:
        self.log(self.logger.debug, "<< Fetching websocket updates >>")
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

    async def start(self, websocket_interval: timedelta = DEFAULT_INTERVAL) -> None:
        if self.update_task and not self.update_task.done():
            self.log(self.logger.warn, "Update task already active")
            return
        self.log(self.logger.info, "Started update task")
        self.update_task = asyncio.create_task(
            self.update_loop(websocket_interval.total_seconds()),
            name="Send websocket data",
        )

    async def update_loop(self, websocket_interval: float = 1) -> None:
        self.log(
            self.logger.info,
            f"Starting update loop with interval {websocket_interval}s",
        )
        while True:
            try:
                updates = self.notifier.get_updates()
                self.log(self.logger.debug, "Sending updates:", *updates)
                for update in updates:
                    await self.broadcast(update, self.logger.getChild("update_loop"))
                self.log(
                    self.logger.debug,
                    f"Updates complete, waiting {websocket_interval}s",
                )
                await asyncio.sleep(websocket_interval)
            except asyncio.CancelledError:
                self.log(self.logger.info, "Update loop cancelled")
                break
            except Exception as e:
                self.log(self.logger.error, f"Error during update: {e}")

    async def connect(self, websocket: WebSocket) -> None:
        self.log(self.logger.info, f"Client connecting {websocket}")
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        self.log(self.logger.info, f"Client disconnecting {websocket}")
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict, logger: Logger | None = None) -> None:
        for connection in self.active_connections:
            await connection.send_text(json.dumps(message))

    async def recieve_data(self, websocket: WebSocket) -> AsyncGenerator[Any, None]:
        async with self.keep_connected(websocket):
            while True:
                data = await websocket.receive_text()
                self.log(self.logger.info, f"Recieved data '{data}'")
                yield data
                await self.broadcast({"action": data})

    @asynccontextmanager
    async def keep_connected(self, websocket: WebSocket) -> AsyncGenerator[None, None]:
        await self.connect(websocket)
        try:
            yield
        except WebSocketDisconnect:
            self.disconnect(websocket)
