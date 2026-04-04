from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import json
import subprocess

from .config import AppConfig


class FamicleanAdapterError(RuntimeError):
    """Base error for famiclean wrapper interactions."""


class FamicleanUnavailableError(FamicleanAdapterError):
    """Raised when the wrapper cannot reach the device or is not executable."""


class FamicleanCommandError(FamicleanAdapterError):
    """Raised when the wrapper reports a command error."""


class FamicleanInvalidResponseError(FamicleanAdapterError):
    """Raised when wrapper output cannot be parsed."""


@dataclass(frozen=True)
class SnapshotResult:
    device: dict[str, object]
    gas: dict[str, object]
    temp: dict[str, object]
    checked_at: str

    def to_dict(self) -> dict[str, object]:
        return {
            "device": self.device,
            "gas": self.gas,
            "temp": self.temp,
            "checked_at": self.checked_at,
        }


class FamicleanAdapter:
    def __init__(self, config: AppConfig):
        self.config = config

    def _base_command(self) -> list[str]:
        wrapper = self.config.famiclean_wrapper
        if not wrapper.is_file():
            raise FamicleanUnavailableError(f"famiclean wrapper not found: {wrapper}")
        if not wrapper.exists():
            raise FamicleanUnavailableError(f"famiclean wrapper does not exist: {wrapper}")

        command = [str(wrapper), "--home", str(self.config.famiclean_home)]
        if self.config.famiclean_env_file is not None:
            command.extend(["--env-file", str(self.config.famiclean_env_file)])

        overrides = self.config.device_overrides
        if overrides.device_ip:
            command.extend(["--device-ip", overrides.device_ip])
        if overrides.device_mac:
            command.extend(["--device-mac", overrides.device_mac])
        if overrides.broadcast_ip:
            command.extend(["--broadcast-ip", overrides.broadcast_ip])
        if overrides.port is not None:
            command.extend(["--port", str(overrides.port)])
        if overrides.timeout_seconds is not None:
            command.extend(["--timeout", str(overrides.timeout_seconds)])
        return command

    def _process_timeout(self) -> float:
        device_timeout = self.config.device_overrides.timeout_seconds or 1.5
        return max(10.0, device_timeout * 4)

    def _invoke(self, *args: str) -> dict[str, object]:
        command = [*self._base_command(), *args]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=self._process_timeout(),
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise FamicleanUnavailableError(f"famiclean wrapper timed out: {' '.join(command)}") from exc
        except OSError as exc:
            raise FamicleanUnavailableError(f"unable to execute famiclean wrapper: {exc}") from exc

        stdout = (completed.stdout or "").strip()
        stderr = (completed.stderr or "").strip()
        payload: dict[str, object] | None = None
        if stdout:
            try:
                decoded = json.loads(stdout)
            except json.JSONDecodeError as exc:
                raise FamicleanInvalidResponseError(
                    f"famiclean wrapper returned invalid JSON for {' '.join(args)}: {stdout}"
                ) from exc
            if not isinstance(decoded, dict):
                raise FamicleanInvalidResponseError(
                    f"famiclean wrapper returned a non-object payload for {' '.join(args)}"
                )
            payload = decoded

        if completed.returncode != 0:
            message = None
            if payload is not None and isinstance(payload.get("error"), str):
                message = str(payload["error"])
            elif stderr:
                message = stderr
            elif stdout:
                message = stdout
            else:
                message = f"famiclean wrapper exited with code {completed.returncode}"
            raise FamicleanCommandError(message)

        if payload is None:
            raise FamicleanInvalidResponseError(f"famiclean wrapper produced no JSON output for {' '.join(args)}")
        return payload

    def read_temp(self) -> dict[str, object]:
        return self._invoke("read-temp")

    def read_gas(self) -> dict[str, object]:
        return self._invoke("read-gas")

    def set_temp(self, target_celsius: int) -> dict[str, object]:
        return self._invoke("set-temp", str(target_celsius))

    def read_snapshot(self) -> SnapshotResult:
        gas = self.read_gas()
        temp = self.read_temp()
        try:
            checked_at = datetime.now(ZoneInfo(self.config.timezone)).isoformat(timespec="seconds")
        except Exception:
            checked_at = datetime.now().astimezone().isoformat(timespec="seconds")
        return SnapshotResult(
            device=dict(temp.get("device") or gas.get("device") or {}),
            gas=gas,
            temp=temp,
            checked_at=checked_at,
        )
