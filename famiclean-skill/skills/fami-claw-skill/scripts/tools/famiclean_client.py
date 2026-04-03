from __future__ import annotations

import ast
import json
import socket
import time
from dataclasses import dataclass

from .famiclean_env import FamicleanSettings
from .famiclean_state import remaining_to_next_threshold, threshold_floor


class FamicleanError(Exception):
    """Base error for Famiclean skill helpers."""


class FamicleanTimeout(FamicleanError):
    """Raised when the device does not answer in time."""


class FamicleanProtocolError(FamicleanError):
    """Raised when a response cannot be parsed or validated."""


class FamicleanValidationError(FamicleanError):
    """Raised when a local validation rule is violated."""


@dataclass
class DeviceRecord:
    ip: str
    port: int
    mac: str
    control: str | None
    payload: dict[str, object]


def normalize_mac(value: str | None) -> str | None:
    if value is None:
        return None
    clean = "".join(ch for ch in str(value).upper() if ch.isalnum())
    return clean or None


def compute_display_m3(raw_value: object, divisor: float) -> float:
    return round(float(raw_value) / divisor, 2)


def parse_payload(text: str) -> dict[str, object]:
    text = text.strip()
    if not text:
        raise FamicleanProtocolError("empty payload")

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        try:
            payload = ast.literal_eval(text)
        except (SyntaxError, ValueError) as exc:
            raise FamicleanProtocolError(f"unable to parse payload: {text}") from exc

    if not isinstance(payload, dict):
        raise FamicleanProtocolError(f"unexpected payload type: {type(payload)!r}")

    return payload


class FamicleanSession:
    def __init__(self, settings: FamicleanSettings):
        self.settings = settings
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.sock.bind(("", 0))
        self.sock.settimeout(0.2)

    @property
    def local_port(self) -> int:
        return int(self.sock.getsockname()[1])

    def close(self) -> None:
        self.sock.close()

    def __enter__(self) -> "FamicleanSession":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def _send(self, host: str, payload: str) -> None:
        self.sock.sendto(payload.encode("utf-8"), (host, self.settings.port))

    def _receive_dict(self, *, required_key: str | None, timeout: float, matcher=None) -> tuple[dict[str, object], tuple[str, int]]:
        deadline = time.monotonic() + timeout
        last_error: Exception | None = None

        while time.monotonic() < deadline:
            try:
                data, addr = self.sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError as exc:
                last_error = exc
                continue

            try:
                payload = parse_payload(data.decode("utf-8", errors="replace"))
            except Exception as exc:
                last_error = exc
                continue

            if required_key and required_key not in payload:
                continue
            if matcher and not matcher(payload, addr):
                continue

            return payload, (addr[0], addr[1])

        if last_error:
            raise FamicleanTimeout(str(last_error))
        raise FamicleanTimeout(f"no response containing {required_key or 'a valid payload'}")

    def discover(self, *, target_ip: str | None = None, target_mac: str | None = None, broadcast_ip: str | None = None, timeout: float | None = None) -> list[DeviceRecord]:
        wanted_mac = normalize_mac(target_mac)
        host = target_ip or broadcast_ip or self.settings.broadcast_ip
        timeout = timeout or self.settings.timeout_seconds
        self._send(host, "request_mac ")

        deadline = time.monotonic() + timeout
        devices: dict[tuple[str, str], DeviceRecord] = {}

        while time.monotonic() < deadline:
            try:
                data, addr = self.sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                continue

            try:
                payload = parse_payload(data.decode("utf-8", errors="replace"))
            except Exception:
                continue

            mac = normalize_mac(str(payload.get("mac", "")))
            if not mac or "control" not in payload:
                continue
            if wanted_mac and mac != wanted_mac:
                continue

            record = DeviceRecord(
                ip=addr[0],
                port=addr[1],
                mac=mac,
                control=str(payload.get("control")) if payload.get("control") is not None else None,
                payload=payload,
            )
            devices[(record.ip, record.mac)] = record
            if target_ip or wanted_mac:
                break

        if not devices:
            raise FamicleanTimeout("discover did not find any device")

        return list(devices.values())

    def resolve_device(self, *, device_ip: str | None = None, device_mac: str | None = None) -> DeviceRecord:
        device_ip = device_ip or self.settings.device_ip
        device_mac = normalize_mac(device_mac or self.settings.device_mac)

        if device_ip:
            device = self.discover(target_ip=device_ip, target_mac=device_mac)[0]
            if device_mac and device.mac != device_mac:
                raise FamicleanProtocolError(f"device at {device_ip} returned MAC {device.mac}, expected {device_mac}")
            return device

        devices = self.discover(target_mac=device_mac)
        if device_mac:
            return devices[0]
        return devices[0]

    def _request_usage(self, device: DeviceRecord) -> dict[str, object]:
        self._send(device.ip, "request_usage ")
        payload, _addr = self._receive_dict(
            required_key="heatvalue_total",
            timeout=self.settings.timeout_seconds,
            matcher=lambda _payload, addr: addr[0] == device.ip,
        )
        return payload

    def _request_status(self, device: DeviceRecord) -> dict[str, object]:
        self._send(device.ip, "request_data ")
        payload, _addr = self._receive_dict(
            required_key="settemp",
            timeout=self.settings.timeout_seconds,
            matcher=lambda _payload, addr: addr[0] == device.ip,
        )
        return payload

    def get_total_gas(self, *, device_ip: str | None = None, device_mac: str | None = None) -> dict[str, object]:
        device = self.resolve_device(device_ip=device_ip, device_mac=device_mac)
        usage = self._request_usage(device)
        status = self._request_status(device)
        raw_heatvalue_total = float(usage["heatvalue_total"])
        raw_heatvalue_count = float(status.get("heatvalue_count", 0.0))
        raw_effective_heatvalue_total = raw_heatvalue_total + raw_heatvalue_count
        gas_total_m3 = compute_display_m3(raw_effective_heatvalue_total, self.settings.gas_divisor)
        threshold_step_m3 = int(self.settings.threshold_step_m3)
        return {
            "device": {
                "ip": device.ip,
                "port": device.port,
                "mac": device.mac,
                "control": device.control,
            },
            "raw_usage": usage,
            "raw_status": status,
            "raw_heatvalue_total": raw_heatvalue_total,
            "raw_heatvalue_count": raw_heatvalue_count,
            "raw_effective_heatvalue_total": raw_effective_heatvalue_total,
            "gas_total_m3": gas_total_m3,
            "gas_count_m3": compute_display_m3(raw_heatvalue_count, self.settings.gas_divisor),
            "threshold_step_m3": threshold_step_m3,
            "current_threshold_m3": threshold_floor(gas_total_m3, threshold_step_m3),
            "next_threshold_m3": threshold_floor(gas_total_m3, threshold_step_m3) + threshold_step_m3,
            "remaining_to_next_threshold_m3": remaining_to_next_threshold(gas_total_m3, threshold_step_m3),
            "raw_waterflow_total": float(usage.get("waterflow_total", 0.0)),
            "raw_waterflow_count": float(usage.get("waterflow_count", 0.0)),
            "session_port": self.local_port,
        }

    def get_temp(self, *, device_ip: str | None = None, device_mac: str | None = None) -> dict[str, object]:
        device = self.resolve_device(device_ip=device_ip, device_mac=device_mac)
        status = self._request_status(device)
        return {
            "device": {
                "ip": device.ip,
                "port": device.port,
                "mac": device.mac,
                "control": device.control,
            },
            "status": status,
            "settemp": int(float(status["settemp"])),
            "session_port": self.local_port,
        }

    def build_set_temp_payload(self, *, target_celsius: int, device: DeviceRecord, status: dict[str, object]) -> str:
        power = str(status.get("power", "on")).lower()
        lock = int(status.get("lock", 0))
        return (
            f"control_type:waterheatersettemp:{target_celsius}"
            f"power:{power}"
            f"mac:{device.mac}"
            "min_flow:0"
            "wifi_reset:0"
            f"lock:{lock}"
            "bath_qty:0"
            "bath_qty_timer:0"
            "fcm_token:"
            "platform:android"
            "pro_mode:0 "
        )

    def set_temp(self, target_celsius: int, *, device_ip: str | None = None, device_mac: str | None = None) -> dict[str, object]:
        if target_celsius > self.settings.max_temp_celsius:
            raise FamicleanValidationError(f"target temperature {target_celsius} exceeds max {self.settings.max_temp_celsius}")

        device = self.resolve_device(device_ip=device_ip, device_mac=device_mac)
        before_status = self._request_status(device)
        before_temp = int(float(before_status["settemp"]))
        control_payload = self.build_set_temp_payload(target_celsius=target_celsius, device=device, status=before_status)
        self._send(device.ip, control_payload)
        time.sleep(0.25)
        after_status = self._request_status(device)
        after_temp = int(float(after_status["settemp"]))
        if after_temp != target_celsius:
            raise FamicleanProtocolError(f"temperature verification failed: requested {target_celsius}, device reported {after_temp}")

        return {
            "device": {
                "ip": device.ip,
                "port": device.port,
                "mac": device.mac,
                "control": device.control,
            },
            "requested_temp": target_celsius,
            "previous_temp": before_temp,
            "confirmed_temp": after_temp,
            "changed": before_temp != after_temp,
            "control_payload": control_payload,
            "before_status": before_status,
            "after_status": after_status,
            "session_port": self.local_port,
        }
