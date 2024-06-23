import json
import os
import subprocess
from typing import Any


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True)


def save_data(filename: str, data: dict[str, Any]) -> None:
    with open(filename, "w") as f:
        json.dump(data, f)


def load_data(filename: str) -> dict[str, Any]:
    if os.path.exists(filename):
        with open(filename, "r") as f:
            return json.load(f)
    else:
        print(f"Could not load data from nonexistent file '{filename}'")
    return {}
