import json
import os
import subprocess
import sys
from contextlib import contextmanager
from logging import Logger, getLogger
from typing import Any


class loggable:
    @property
    def logger(self) -> Logger:
        return getattr(self, "_logger", None) or getLogger(self.__class__.__name__)

    @logger.setter
    def logger(self, logger: Logger) -> None:
        self._logger = logger

    @contextmanager
    def handle_error(self, error_msg: str | None = None):
        try:
            yield
        except subprocess.CalledProcessError as e:
            if error_msg:
                self.logger.error(f"{error_msg}: {e}")
            else:
                self.logger.error(f"Failed to execute command: {e}")
        except Exception as e:
            self.logger.error(f"Unexpected error: {e}")
        finally:
            pass


def run(cmd: list[str]) -> None:
    process = subprocess.Popen(cmd, stdout=sys.stdout, stderr=sys.stderr)
    process.communicate()
    if process.returncode != 0:
        raise subprocess.CalledProcessError(process.returncode, cmd)


def stdout(cmd: list[str]) -> str:
    result = subprocess.run(
        cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    return result.stdout


def check_output(cmd: list[str]) -> str:
    return stdout(cmd)


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
