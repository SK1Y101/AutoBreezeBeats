from __future__ import annotations
from logging import Logger, getLogger
from .common import BreezeBaseClass
from typing import Callable, Any
from fastapi import WebSocket
import json
import asyncio

Updates = dict[str, Any]


class Notifier(BreezeBaseClass):
    def __init__(self, parent_logger: None | Logger) -> None:
        super().__init__("websocket-notifier", parent_logger)

        self.callbacks: list[Callable[[], Updates]] = []
    
    def register_callback(self, callback: Callable[[], Updates]) -> None:
        self.info(f"Callback registered: {callback}")
        self.callbacks.append(callback)
    
    def get_updates(self) -> list[Updates]:
        updates = []
        for callback in self.callbacks:
            if update:=callback():
                updates.append(update)
        return updates
        

class WebSocketManager(BreezeBaseClass):
    def __init__(self, parent_logger: None | Logger) -> None:
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