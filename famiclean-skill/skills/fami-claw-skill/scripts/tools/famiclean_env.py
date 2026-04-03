from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import os


@dataclass(frozen=True)
class FamicleanSettings:
    home_dir: Path
    env_file: Path
    state_file: Path
    device_ip: str | None = None
    device_mac: str | None = None
    broadcast_ip: str = "255.255.255.255"
    port: int = 9999
    timeout_seconds: float = 1.5
    gas_divisor: float = 9100.0
    threshold_step_m3: int = 20
    daily_check_hour: int = 8
    timezone: str = "Asia/Taipei"
    max_temp_celsius: int = 50
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    email_smtp_host: str | None = None
    email_smtp_port: int = 587
    email_smtp_username: str | None = None
    email_smtp_password: str | None = None
    email_use_tls: bool = True
    email_from: str | None = None
    email_to: str | None = None


def _strip_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _read_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = _strip_quotes(value)
    return values


def _as_bool(value: str | None, default: bool) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _as_int(value: str | None, default: int) -> int:
    if value is None or value == "":
        return default
    return int(value)


def _as_float(value: str | None, default: float) -> float:
    if value is None or value == "":
        return default
    return float(value)


def _first_existing(candidates: list[Path]) -> Path | None:
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if (resolved / "config").exists():
            return resolved
    return None


def find_home_dir(script_path: Path, explicit_home: str | None = None) -> Path:
    candidates: list[Path] = []

    if explicit_home:
        candidates.append(Path(explicit_home))

    env_home = os.environ.get("FAMICLEAN_HOME")
    if env_home:
        candidates.append(Path(env_home))

    candidates.append(Path.cwd())
    candidates.extend(script_path.resolve().parents)

    discovered = _first_existing(candidates)
    if discovered is not None:
        return discovered

    return Path.cwd().resolve()


def load_settings(script_path: Path, env_file: str | None = None, explicit_home: str | None = None) -> FamicleanSettings:
    home_dir = find_home_dir(script_path, explicit_home=explicit_home)
    env_path = Path(env_file).resolve() if env_file else home_dir / "config" / ".env"
    values = _read_env_file(env_path)

    state_rel = values.get("STATE_FILE", "data/famiclean-state.json")
    state_path = Path(state_rel)
    if not state_path.is_absolute():
        state_path = home_dir / state_path

    return FamicleanSettings(
        home_dir=home_dir,
        env_file=env_path,
        state_file=state_path,
        device_ip=values.get("DEVICE_IP") or None,
        device_mac=values.get("DEVICE_MAC") or None,
        broadcast_ip=values.get("BROADCAST_IP", "255.255.255.255"),
        port=_as_int(values.get("FAMICLEAN_PORT"), 9999),
        timeout_seconds=_as_float(values.get("FAMICLEAN_TIMEOUT_SECONDS"), 1.5),
        gas_divisor=_as_float(values.get("GAS_DIVISOR"), 9100.0),
        threshold_step_m3=_as_int(values.get("THRESHOLD_STEP_M3"), 20),
        daily_check_hour=_as_int(values.get("DAILY_CHECK_HOUR"), 8),
        timezone=values.get("TIMEZONE", "Asia/Taipei"),
        max_temp_celsius=_as_int(values.get("MAX_TEMP_CELSIUS"), 50),
        telegram_bot_token=values.get("TELEGRAM_BOT_TOKEN") or None,
        telegram_chat_id=values.get("TELEGRAM_CHAT_ID") or None,
        email_smtp_host=values.get("EMAIL_SMTP_HOST") or None,
        email_smtp_port=_as_int(values.get("EMAIL_SMTP_PORT"), 587),
        email_smtp_username=values.get("EMAIL_SMTP_USERNAME") or None,
        email_smtp_password=values.get("EMAIL_SMTP_PASSWORD") or None,
        email_use_tls=_as_bool(values.get("EMAIL_USE_TLS"), True),
        email_from=values.get("EMAIL_FROM") or None,
        email_to=values.get("EMAIL_TO") or None,
    )


def apply_overrides(settings: FamicleanSettings, **overrides: object) -> FamicleanSettings:
    clean_overrides = {key: value for key, value in overrides.items() if value is not None}
    if not clean_overrides:
        return settings
    return replace(settings, **clean_overrides)
