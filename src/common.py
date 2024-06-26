import os
from logging import Logger, getLogger
from subprocess import DEVNULL, PIPE, CalledProcessError, Popen
from typing import Any

import yaml


class BreezeBaseClass:
    def __init__(self, name: str, parent_logger: Logger | None = None) -> None:
        self.name = name
        self.logger = (
            parent_logger.getChild(self.name) if parent_logger else getLogger(self.name)
        )

    @property
    def logger(self) -> Logger:
        return getattr(self, "_logger", None) or getLogger(self.__class__.__name__)

    @logger.setter
    def logger(self, logger: Logger) -> None:
        self._logger = logger

    def run(self, cmd: list[str], capture: bool = False) -> str:
        return run(cmd, capture=capture, logger=self.logger.getChild("subprocess"))


def run(
    cmd: list[str],
    capture: bool = False,
    logger: Logger = getLogger("subprocess"),
) -> str:
    try:
        process = Popen(
            cmd, stdout=PIPE if capture else DEVNULL, stderr=PIPE, text=True
        )
        stdout, stderr = process.communicate()
        if stdout:
            logger.debug(stdout)
        if stderr:
            logger.error(stderr)
        if process.returncode != 0:
            raise CalledProcessError(
                process.returncode, cmd, output=stdout, stderr=stderr
            )
    except CalledProcessError as e:
        logger.error(f"Command '{' '.join(e.cmd)}' failed: {e.returncode}")
        logger.error(e.output)
        logger.error(e.stderr)
    except FileNotFoundError as e:
        logger.error(f"Not found: {e}")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
    else:
        return stdout if capture else ""

    raise


def save_data(filename: str, data: dict[str, Any]) -> None:
    with open(filename, "w") as f:
        yaml.safe_dump(data, f)


def load_data(filename: str) -> dict[str, Any]:
    if os.path.exists(filename):
        with open(filename, "r") as f:
            return yaml.safe_load(f)
    else:
        print(f"Could not load data from nonexistent file '{filename}'")
    return {}
