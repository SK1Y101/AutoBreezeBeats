from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from logging import Logger
from typing import Any, Generator

from fastapi import HTTPException
from pydantic import BaseModel

from .common import BreezeBaseClass, load_data, save_data
from .websockets import Notifier, Updates


class ConnectError(HTTPException):
    def __init__(self, address: str) -> None:
        super().__init__(status_code=500, detail=f"Failed to connect to {address}")


class DisconnectError(HTTPException):
    def __init__(self, address: str) -> None:
        super().__init__(status_code=500, detail=f"Failed to disconnect from {address}")


class SinkError(HTTPException):
    def __init__(self, address: str | None) -> None:
        super().__init__(
            status_code=500, detail=f"Failed to set sink to {address or "default"}"
        )


class DeviceAction(BaseModel):
    address: str


class SinkAction(BaseModel):
    address: str | None = None


def noramlise_address(address: str) -> str:
    return re.sub(r"[\-\_\.]", ":", address.lower())


@dataclass
class Sink:
    id: int = -1
    name: str = "Uninitialised Sink"
    active: bool = False


@dataclass
class Device:
    address: str
    name: str = "Unknown device"
    connected: bool = False
    primary: bool = False

    @property
    def to_dict(self) -> dict[str, str | bool]:
        return {
            "name": self.name,
            "address": noramlise_address(self.address),
            "connected": self.connected,
            "primary": self.primary,
        }

    @property
    def sink_address(self) -> str:
        return noramlise_address(self.address).replace(":", "_")


class DeviceManager(BreezeBaseClass):
    def __init__(self, parent_logger: None | Logger, notifier: Notifier) -> None:
        super().__init__("devices", parent_logger)
        self.filename = "connected_devices.json"

        self.devices: list[Device] = []
        self.load_devices()
        self.sync_devices()

        self.scanning_task: None | asyncio.Task = None

        notifier.register_callback(self.get_current_devices)

    async def start(self, interval: int = 1) -> None:
        if self.scanning_task and not self.scanning_task.done():
            self.logger.warn("Scanning task already active")
            return
        self.logger.info("Started scanning task")
        self.update_task = asyncio.create_task(self.scan_loop(interval), name="Scan for devices")

    async def scan_loop(self, interval: int = 1) -> None:
        self.logger.info(f"Starting scan loop with interval {interval}s")
        try:
            while True:
                self.run(["bluetoothctl", "--timeout", str(interval), "scan", "on"])
                self.devices = self._found_devices()
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            self.logger.info("Scan loop cancelled")
        except Exception as e:
            self.logger.error(f"Error during scan: {e}")

    def _device_connected(self, address: str) -> bool:
        try:
            output = self.run(["bluetoothctl", "info", address], capture=True)
            return "Connected: yes" in output
        except Exception:
            return False

    def _found_devices(self) -> list[Device]:
        try:
            devices: list[Device] = []
            found = self.run(["bluetoothctl", "devices"], capture=True)
            for line in found.splitlines():
                if line.startswith("Device "):
                    parts = line.split()
                    address = noramlise_address(parts[1])
                    name = " ".join(parts[2:])
                    if noramlise_address(name) == address:
                        continue
                    connected = self._device_connected(address)
                    device = Device(address=address, name=name, connected=connected)
                    device.primary = (
                        sink.active
                        if (sink := self._sink_info_(device.address))
                        else False
                    )
                    devices.append(device)
            return devices
        except Exception:
            return []

    def get_current_devices(self) -> Updates:
        devices = self.list_devices
        self.logger.getChild("device_update").debug(devices)
        return {"devices": devices}

    @property
    def clients(self) -> list[str]:
        return [device.address for device in self.devices if device.connected]

    @property
    def list_devices(self) -> list[dict[str, Any]]:
        return [device.to_dict for device in self.devices]

    def _device_(self, address: str) -> Device:
        for device in self.devices:
            if device.address == noramlise_address(address):
                return device
        raise Exception(f"Could not find device {address}")

    def connect_device(self, address: str) -> bool:
        self.logger.info(f"Request connect {address}")
        try:
            self.run(["bluetoothctl", "connect", address])
            self._device_(address).connected = True
            self.save_devices()
            return True
        except Exception:
            return False

    def disconnect_device(self, address: str) -> bool:
        self.logger.info(f"Request disconnect {address}")
        try:
            self.run(["bluetoothctl", "disconnect", address])
            self._device_(address).connected = True
            self.save_devices()
            return True
        except Exception:
            return False

    @property
    def _sinks_(self) -> Generator[Sink, None, None]:
        output = self.run(["pactl", "list", "short", "sinks"], capture=True)
        for line in output.splitlines():
            idx, name, _, _, active = line.split("\t")
            sink = Sink(
                id=int(idx),
                name=name,
                active=active.lower() != "suspended",
            )
            self.logger.debug(f"Found sink {sink}")
            yield sink

    def _sink_info_(self, address: str) -> Sink | None:
        for sink in self._sinks_:
            if address.lower().replace(":", "_") in sink.name.lower():
                return sink
        self.logger.warn(f"Sink with address '{address}' not found.")
        return None

    def set_sink(self, address: str) -> bool:
        self.logger.info(f"Request to set sink to {address}")
        try:
            device = self._device_(address=address)
            if not device.connected:
                self.logger.info(f"device {device} not connected")
                self.connect_device(address)
            if sink := self._sink_info_(device.address):
                self.logger.info(f"Found sink {sink} for device {device}")
                self.run(["pactl", "set-default-sink", str(sink.id)])
                device.primary = True
                return True
            else:
                self.logger.warn(f"Could not find sink for {device}")
        except Exception:
            self.logger.error(f"Could not set sink to {address}")
        return False

    def unset_sinks(self) -> bool:
        try:
            for device in self.devices:
                device.primary = False
            for sink in self._sinks_:
                self.logger.info(f"Suspending sink {sink}")
                self.run(["pactl", "suspend-sink", str(sink.id), "1"])
                sink.active = False
            return True
        except Exception:
            return False

    def sync_devices(self) -> None:
        clients = self.clients
        for device in self.devices:
            if device.address in clients:
                device.connected = True

            if device.connected:
                self.connect_device(device.address)
            else:
                self.disconnect_device(device.address)

    def save_devices(self) -> None:
        self.logger.info("Saving device data")

        data = {}
        data["devices"] = {device.address: device.name for device in self.devices}

        save_data(self.filename, data)
        self.logger.info("Saving complete")

    def load_devices(self) -> None:
        self.logger.info("Loading device data")

        if data := load_data(self.filename):
            devices = data["devices"]

            self.devices = [
                Device(address=noramlise_address(address), name=name, connected=False)
                for address, name in devices.items()
                if noramlise_address(address) != noramlise_address(name)
            ]
            self.logger.info("Loading complete")
