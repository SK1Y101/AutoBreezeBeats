from __future__ import annotations

from dataclasses import dataclass
from subprocess import CalledProcessError
from typing import Optional

from bleak import BleakClient, BleakScanner

from common import load_data, run, save_data


@dataclass
class Device:
    address: str
    name: Optional[str] = "Unknown device"
    connected: bool = False

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

    async def scan_devices(self) -> list[Device]:
        devices = await BleakScanner.discover()
        return [Device(name=device.name, address=device.address) for device in devices]

    def _find_device_(self, address: str) -> Device:
        device = next(
            (device for device in self.devices if device.address == address), None
        )
        if not device:
            device = Device(address=address)
            self.devices.append(device)
        return device

    async def connect_deice(self, address: str) -> None:
        device = self._find_device_(address=address)

        await device.connect()
        self.clients[address] = device

        self.set_audio_sinks()
        self.save_devices()

    async def disconnect_device(self, address: str) -> None:
        device = self.clients.pop(address, None)
        if device:
            await device.client.disconnect()

        self.set_audio_sinks()
        self.save_devices()

    def set_audio_sinks(self) -> None:
        for device in self.clients.values():
            try:
                sink_name = f"bluez_sink.{device.sink_address}.a2dp_sink"
                run(["pactl", "set-default-sink", sink_name])
                # run(["pactl", "move-sink-input", "0", sink_name])
                device.connected = True
            except CalledProcessError as e:
                print(f"Failed to set audio sink to {device.address}: {e}")

    def save_devices(self) -> None:
        device_dict = {device.name: device.address for device in self.devices}
        save_data(self.filename, device_dict)

    def load_devices(self) -> None:
        device_dict = load_data(self.filename)
        self.devices = [
            Device(name=name, address=address) for name, address in device_dict.items()
        ]


device_manager = DeviceManager()
