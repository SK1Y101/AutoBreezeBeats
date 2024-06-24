from __future__ import annotations

import asyncio
from dataclasses import dataclass
from subprocess import CalledProcessError
from typing import Any

from bleak import BleakClient, BleakScanner
from fastapi import HTTPException
from pydantic import BaseModel

from .common import load_data, run, save_data


class ConnectError(HTTPException):
    def __init__(self, address: str) -> None:
        super().__init__(status_code=500, detail=f"Failed to connect to {address}")


class DisconnectError(HTTPException):
    def __init__(self, address: str) -> None:
        super().__init__(status_code=500, detail=f"Failed to disconnect from {address}")


class DeviceAction(BaseModel):
    address: str


@dataclass
class Device:
    address: str
    name: str = "Unknown device"
    connected: bool = False

    @property
    def to_dict(self) -> dict[str, str | bool]:
        return {
            "name": self.name,
            "address": self.address.lower(),
            "connected": self.connected,
        }

    @property
    def sink_address(self) -> str:
        return self.address.replace(":", "_")

    @property
    def client(self) -> BleakClient:
        return BleakClient(self.address)

    async def connect(self) -> None:
        await self.client.connect()
        self.connected = True

    async def disconnect(self) -> None:
        await self.client.disconnect()
        self.connected = False


class DeviceManager:
    def __init__(self) -> None:
        self.devices: list[Device] = []
        self.clients: dict[str, Device] = {}
        self.filename = "connected_devices.json"
        self.load_devices()

    async def scan_devices(self) -> None:
        devices = await BleakScanner.discover()
        self.devices = [
            Device(name=device.name or "Unknown device", address=device.address)
            for device in devices
        ]

    @property
    def list_devices(self) -> list[dict[str, Any]]:
        return [device.to_dict for device in self.devices]

    def _find_device_(self, address: str) -> Device:
        device = next(
            (device for device in self.devices if device.address == address), None
        )
        if not device:
            device = Device(address=address)
            self.devices.append(device)
        return device

    async def connect_device(self, address: str) -> bool:
        device = self._find_device_(address=address)

        await device.connect()
        self.clients[address] = device

        self.set_audio_sinks()
        self.save_devices()
        return device.connected is True

    async def disconnect_device(self, address: str) -> bool:
        device = self.clients.pop(address, None)
        if device:
            await device.client.disconnect()
        else:
            return False

        self.set_audio_sinks()
        self.save_devices()
        return device.connected is False

    def set_audio_sinks(self) -> None:
        for device in self.clients.values():
            try:
                sink_name = f"bluez_sink.{device.sink_address}.a2dp_sink"
                run(["pactl", "set-default-sink", sink_name])
                # run(["pactl", "move-sink-input", "0", sink_name])
                device.connected = True
            except CalledProcessError as e:
                print(f"Failed to set audio sink to {device.address}: {e}")

    async def sync_devices(self) -> None:
        """Ensure the connected devices match what we think is connected."""
        for device in self.devices:
            if device.address in self.clients.keys():
                device.connected = True
            if device.connected:
                await device.connect()
                self.clients[device.address] = device
            else:
                await device.disconnect()
                self.clients.pop(device.address, None)

    def save_devices(self) -> None:
        device_dict = {device.name: device.address for device in self.devices}
        save_data(self.filename, device_dict)

    def load_devices(self) -> None:
        device_dict = load_data(self.filename)
        self.devices = [
            Device(name=name, address=address) for name, address in device_dict.items()
        ]

    async def periodic_scan(self, interval: int = 30) -> None:
        while True:
            await self.scan_devices()
            await self.sync_devices()
            await asyncio.sleep(interval)


device_manager = DeviceManager()


async def start_periodic_scan() -> None:
    await device_manager.periodic_scan()


loop = asyncio.get_event_loop()
loop.create_task(start_periodic_scan())
