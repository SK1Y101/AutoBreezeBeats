from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from logging import Logger, getLogger
from math import ceil
from time import sleep
from typing import Any, Generator

from fastapi import HTTPException
from pydantic import BaseModel

from .common import check_output, load_data, BreezeBaseClass, run, save_data


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
    def __init__(self, parent_logger: None | Logger) -> None:
        super().__init__("devices", parent_logger)
        self.filename = "connected_devices.json"

        self.devices: list[Device] = []
        self.load_devices()
        self.sync_devices()

        self.scanning_thread: None | threading.Thread = None
        self.keep_scanning = False
        self.scan_timeout: int = 5

    @property
    def clients(self) -> list[str]:
        return [device.address for device in self.devices if device.connected]

    @property
    def list_devices(self) -> list[dict[str, Any]]:
        return [device.to_dict for device in self.devices]

    def start_scanning(self, timeout: int = 5) -> None:
        self.scan_timeout = timeout
        if self.scanning_thread and self.scanning_thread.is_alive():
            self.warn("Scanning thread already active")
            return
        self.keep_scanning = True
        self.scanning_thread = threading.Thread(target=self._scan_devices, daemon=True)
        self.scanning_thread.start()

    def stop_scanning(self) -> None:
        self.keep_scanning = False
        if self.scanning_thread and self.scanning_thread.is_alive():
            self.info("Waiting for scanning thread shutdown")
            self.scanning_thread.join()

    def _scan_devices(self) -> None:
        try:
            self.info("Discovering bluetooth devices")
            while self.keep_scanning:
                run(["bluetoothctl", "--timeout", str(self.scan_timeout), "scan", "on"])
                self.devices = self._found_devices()
                # scan until the next 10 seconds have elapsed
                sleep(10 * ceil(self.scan_timeout / 10))
        except KeyboardInterrupt:
            self.info("Forcibly stopping device scanning")
        except Exception as e:
            self.error(f"Error during device scan: {e}")

    def _device_connected(self, address: str) -> bool:
        with self.handle_error():
            output = check_output(["bluetoothctl", "info", address])
            return "Connected: yes" in output
        return False

    def _found_devices(self) -> list[Device]:
        with self.handle_error():
            devices: list[Device] = []
            found = check_output(["bluetoothctl", "devices"])
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
        return []

    def _device_(self, address: str) -> Device:
        for device in self.devices:
            if device.address == noramlise_address(address):
                return device
        raise Exception(f"Could not find device {address}")

    def connect_device(self, address: str) -> bool:
        self.info(f"Request connect {address}")
        with self.handle_error(f"Failed to connect to device {address}"):
            run(["bluetoothctl", "connect", address])
            self._device_(address).connected = True
            self.save_devices()
            return True
        return False

    def disconnect_device(self, address: str) -> bool:
        self.info(f"Request disconnect {address}")
        with self.handle_error(f"Failed to disconnect from {address}"):
            run(["bluetoothctl", "disconnect", address])
            self._device_(address).connected = True
            self.save_devices()
            return True
        return False

    @property
    def _sinks_(self) -> Generator[Sink, None, None]:
        with self.handle_error("Could not find pactl sinks"):
            output = check_output(["pactl", "list", "short", "sinks"])
            for line in output.splitlines():
                idx, name, _, _, active = line.split("\t")
                sink = Sink(
                    id=int(idx),
                    name=name,
                    active=active.lower() != "suspended",
                )
                self.info(f"Found sink {sink}")
                yield sink

    def _sink_info_(self, address: str) -> Sink | None:
        for sink in self._sinks_:
            if address.lower().replace(":", "_") in sink.name.lower():
                return sink
        self.debug(f"Sink with address '{address}' not found.")
        return None

    def set_sink(self, address: str) -> bool:
        self.info(f"Request to set sink to {address}")
        with self.handle_error(f"Could not set {address} as sink."):
            device = self._device_(address=address)
            if not device.connected:
                self.info(f"device {device} not connected")
                self.connect_device(address)
            if sink := self._sink_info_(device.address):
                self.info(f"Found sink {sink} for device {device}")
                run(["pactl", "set-default-sink", str(sink.id)])
                device.primary = True
                return True
            else:
                self.warn(f"Could not find sink for {device}")
        return False

    def unset_sinks(self) -> bool:
        with self.handle_error("Could not unset"):
            for device in self.devices:
                device.primary = False
            for sink in self._sinks_:
                self.info(f"Suspending sink {sink}")
                run(["pactl", "suspend-sink", str(sink.id), "1"])
                sink.active = False
            return True
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
        self.info("Saving device data")

        data = {}
        data["devices"] = {device.address: device.name for device in self.devices}

        save_data(self.filename, data)
        self.info("Saving complete")

    def load_devices(self) -> None:
        self.info("Loading device data")

        if data := load_data(self.filename):
            devices = data["devices"]

            self.devices = [
                Device(address=noramlise_address(address), name=name, connected=False)
                for address, name in devices.items()
                if noramlise_address(address) != noramlise_address(name)
            ]
            self.info("Loading complete")
