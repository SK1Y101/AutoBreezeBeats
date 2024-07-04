import os
from concurrent.futures import TimeoutError
from datetime import UTC, datetime, timedelta
from logging import Logger, getLogger
from multiprocessing import Process, Queue
from subprocess import DEVNULL, PIPE, CalledProcessError, Popen
from typing import Any, Callable, Iterable

import yaml
from retry import retry

DEFAULT_INTERVAL = timedelta(seconds=1)


def current_time() -> datetime:
    return datetime.now(UTC)


class TimeoutException(Exception):
    pass


class ConfigurationManager:
    config_path = "config.yaml"
    _config_: dict[str, dict[str, Any]] = {}

    def __init__(self, name: str) -> None:
        self.name = name
        self._load_configuration_()

    @property
    def name(self) -> str:
        if self._name_:
            return self._name_
        return self.__class__.__name__.lower().replace("manager", "")

    @name.setter
    def name(self, value: str) -> None:
        self._name_ = value

    def _load_configuration_(self) -> None:
        self._config_ = load_data(self.config_path, True)

    def _save_configuration_(self) -> None:
        save_data(self.config_path, self._config_)

    # the whole configuration
    def _get_configuration_section_(self, section: str) -> dict[str, Any]:
        return self._config_.get(section, {})

    def _set_configuration_section_(
        self, section: str, value: dict[str, Any] = {}
    ) -> None:
        self._config_[section] = value
        self._save_configuration_()

    # configuration from a section
    def _get_configuration_value_(self, section: str, key: str, default=None) -> Any:
        return self._get_configuration_section_(section).get(key, default)

    def _set_configuration_value_(self, section: str, key: str, value: Any) -> None:
        conf = self._get_configuration_section_(section)
        conf[key] = value
        self._set_configuration_section_(section, conf)

    # configuration for my class
    def _get_config_(self) -> dict[str, Any]:
        return self._get_configuration_section_(self.name)

    def _get_config_value_(self, key: str, default: Any) -> Any:
        return self._get_configuration_value_(self.name, key, default)

    def _set_config_(self, value: dict[str, Any] = {}) -> None:
        return self._set_configuration_section_(self.name, value)

    def _set_config_value_(self, key: str, value: Any) -> None:
        return self._set_configuration_value_(self.name, key, value)

    # easy to access
    def read_config(self, key: str, default=None) -> Any:
        return self._get_config_value_(key, default)

    def write_config(self, key: str, value=Any) -> None:
        return self._set_config_value_(key, value)

    @property
    def my_config(self) -> dict[str, Any]:
        return self._get_config_()

    @property
    def config(self) -> dict[str, dict[str, Any]]:
        if not self._config_:
            self._load_configuration_()
        return self._config_


class BreezeBaseClass(ConfigurationManager):

    def __init__(self, name: str, parent_logger: Logger | None = None) -> None:
        super().__init__(name)
        self.logger = (
            parent_logger.getChild(self.name) if parent_logger else getLogger(self.name)
        )

    def _target(self, func: Callable, queue: Queue, *args: Any, **kwargs) -> None:
        try:
            result = func(*args, **kwargs)
            queue.put(result)
        except Exception as e:
            queue.put(e)

    def run_with_timeout(
        self,
        func: Callable,
        *args: Any,
        timeout: float = 10,
        **kwargs,
    ) -> Any | None:
        queue = Queue()
        process = Process(target=self._target, args=(func, queue, *args), kwargs=kwargs)
        process.start()
        process.join(timeout)

        if process.is_alive():
            process.terminate()
            process.join()
            msg = f"Timeout: {func.__name__} timed out after {timeout} seconds"
            self.logger.error(msg)
            raise TimeoutException(msg)

        if not queue.empty():
            result = queue.get_nowait()
            if isinstance(result, Exception):
                self.logger.error(f"Error: {func.__name__} raised an exception: {e}")
                raise result
            return result

        return None

    @retry(tries=3, delay=1, exceptions=(TimeoutException,))
    def retry_with_timeout(
        self,
        func: Callable,
        *args: Any,
        timeout: float = 10,
        **kwargs,
    ) -> Any | None:
        try:
            return self.run_with_timeout(func, *args, timeout=timeout, **kwargs)
        except Exception as e:
            self.logger.warning(e)
            return None

    @property
    def logger(self) -> Logger:
        return getattr(self, "_logger", None) or getLogger(self.__class__.__name__)

    @logger.setter
    def logger(self, logger: Logger) -> None:
        self._logger = logger

    def log(self, log_type: Callable[[Any], None], *msgs) -> None:
        log(log_type, *msgs)

    def log_changed(
        self,
        log_type: Callable[[Any], None],
        value_type: str,
        new_values: Iterable[Any],
        old_values: Iterable[Any],
        log_new: bool = True,
        log_old: bool = True,
        new_message: str = "new",
        old_message: str = "old",
        expand: bool = True,
    ) -> None:
        """Log the difference bewteen two values."""

        def a_without_b(a: Iterable[Any], b: Iterable[Any]) -> Iterable[Any]:
            if isinstance(a, dict):
                return {k: v for k, v in a.items() if k not in b}
            return [v for v in a if v not in b]

        if new_values != old_values:
            if log_new and (new := a_without_b(new_values, old_values)):
                value_name = str(value_type) + ("s" if len(list(new)) > 1 else "")
                self.log(
                    log_type,
                    f"{new_message.strip()} {value_name.strip()}".capitalize(),
                    *new if expand else new,
                )
            if log_old and (old := a_without_b(old_values, new_values)):
                value_name = str(value_type) + ("s" if len(list(old)) > 1 else "")
                self.log(
                    log_type,
                    f"{old_message.strip()} {value_name.strip()}".capitalize(),
                    *old if expand else old,
                )

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
        out = (
            "\n".join(_out)
            .replace("\n", f"\n{pipes} ")
            .replace(f"{pipes} {entry}", entry)
            .splitlines()
        )
        if len(out) > 1:
            out[-1] = f"{final}{out[-1][1:]}"
        for line in out:
            log_type(line)
    except Exception as e:
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
