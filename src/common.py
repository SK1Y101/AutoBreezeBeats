import os
from datetime import timedelta
from logging import Logger, getLogger
from subprocess import DEVNULL, PIPE, CalledProcessError, Popen
from typing import Any, Callable

import yaml

DEFAULT_INTERVAL = timedelta(seconds=1)


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

    def log(self, log_type: Callable[[Any], None], *msgs) -> None:
        log(log_type, *msgs)

    def run(self, cmd: list[str], capture: bool = False, quiet: bool = False) -> str:
        return run(
            cmd, capture=capture, logger=self.logger.getChild("subprocess"), quiet=quiet
        )


def log(log_type: Callable[[Any], None], *msgs) -> None:
    """Nicely show multi-line messages."""

    entry = "┝"
    pipes = "|"
    final = "┕"

    try:
        _out: list[str] = []
        for msg in msgs:
            this_msg = str(msg)
            if isinstance(msg, dict):
                this_msg = yaml.dump(msg).strip("\n")
            elif isinstance(msg, list):
                this_msg = ", ".join(str(item) for item in msg)
            if len(_out):
                this_msg = f"{entry} {this_msg}"
            _out.append(this_msg)
        out = "\n".join(_out)
        out = out.replace("\n", f"\n{pipes} ").replace(f"{pipes} {entry}", entry)
        if out.count("\n") > 0:
            # format the end nicely
            a, b = out.rsplit("\n", 1)
            out = f"{a}\n{final}{b[1:]}"
        log_type(out)
    except Exception as e:
        print(msgs)
        getLogger("logging").error(f"Problem creating multi-line log: {e}")


def run(
    cmd: list[str],
    capture: bool = False,
    logger: Logger = getLogger("subprocess"),
    quiet: bool = False,
) -> str:
    """Handle executing commands."""
    try:
        process = Popen(
            cmd, stdout=PIPE if capture else DEVNULL, stderr=PIPE, text=True
        )
        stdout, stderr = process.communicate()
        if stdout and not quiet:
            log(logger.debug, stdout)
        if stderr:
            log(logger.error, stderr)
        if process.returncode != 0:
            raise CalledProcessError(
                process.returncode, cmd, output=stdout, stderr=stderr
            )
    except CalledProcessError as e:
        log(logger.error, f"Command '{' '.join(e.cmd)}' failed: {e.returncode}")
        log(logger.error, e.output)
        log(logger.error, e.stderr)
    except FileNotFoundError as e:
        log(logger.error, f"Not found: {e}")
    except Exception as e:
        log(logger.error, f"Unexpected error: {e}")
    else:
        return stdout if capture else ""

    raise


def save_data(filename: str, data: dict[str, Any]) -> None:
    with open(filename, "w") as f:
        yaml.safe_dump(data, f)


def load_data(filename: str, quiet: bool = False) -> Any:
    if os.path.exists(filename):
        with open(filename, "r") as f:
            return yaml.safe_load(f)
    elif not quiet:
        print(f"Could not load data from nonexistent file '{filename}'")
    return {}
