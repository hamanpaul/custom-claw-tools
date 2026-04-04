from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import re


class RuntimeConfigError(RuntimeError):
    """Raised when fami-ghome configuration is invalid."""


@dataclass(frozen=True)
class DeviceOverrides:
    device_ip: str | None = None
    device_mac: str | None = None
    broadcast_ip: str | None = None
    port: int | None = None
    timeout_seconds: float | None = None


@dataclass(frozen=True)
class AppConfig:
    project_root: Path
    env_file: Path
    state_dir: Path
    log_dir: Path
    famiclean_home: Path
    famiclean_wrapper: Path
    famiclean_env_file: Path | None
    host: str
    port: int
    public_base_url: str
    timezone: str
    log_level: str
    min_temp_celsius: int
    max_temp_celsius: int
    google_cloud_project_id: str
    google_home_project_id: str
    google_home_fulfillment_url: str
    google_home_local_app_id: str
    agent_user_id: str
    account_linking_client_id: str
    account_linking_client_secret: str
    account_linking_allowed_redirect_uris: tuple[str, ...]
    auth_admin_username: str
    auth_admin_password_hash: str
    session_secret: str
    token_encryption_key: str
    authorization_code_ttl_seconds: int
    access_token_ttl_seconds: int
    refresh_token_ttl_days: int
    local_home_enabled: bool
    local_home_device_id: str
    local_home_scan_port: int
    local_home_listen_host: str
    local_home_listen_port: int
    google_service_account_file: Path | None
    internal_api_enabled: bool
    internal_api_token: str
    device_overrides: DeviceOverrides


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


def _split_values(value: str | None) -> tuple[str, ...]:
    if value is None or value.strip() == "":
        return ()
    parts = [item.strip() for item in re.split(r"[\s,]+", value.strip())]
    return tuple(item for item in parts if item)


def _resolve_path(root: Path, raw_value: str | None, default_value: str | None = None) -> Path | None:
    chosen = raw_value if raw_value not in {None, ""} else default_value
    if chosen in {None, ""}:
        return None
    path = Path(str(chosen)).expanduser()
    if not path.is_absolute():
        path = root / path
    return path.resolve()


def find_project_root(script_path: Path, explicit_root: str | None = None) -> Path:
    candidates: list[Path] = []
    if explicit_root:
        candidates.append(Path(explicit_root).expanduser())

    env_root = os.environ.get("FAMI_GHOME_HOME")
    if env_root:
        candidates.append(Path(env_root).expanduser())

    candidates.append(Path.cwd())
    candidates.extend(script_path.resolve().parents)

    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if (resolved / "config").is_dir() and (resolved / "docs").is_dir():
            return resolved
    return script_path.resolve().parents[1]


def load_config(script_path: Path, *, env_file: str | None = None, explicit_root: str | None = None) -> AppConfig:
    project_root = find_project_root(script_path, explicit_root=explicit_root)
    env_path = Path(env_file).expanduser().resolve() if env_file else project_root / "config" / ".env"
    values = _read_env_file(env_path)

    state_dir = _resolve_path(project_root, values.get("STATE_DIR"), "data")
    log_dir = _resolve_path(project_root, values.get("LOG_DIR"), "logs")
    if state_dir is None or log_dir is None:
        raise RuntimeConfigError("STATE_DIR and LOG_DIR must resolve to usable paths")

    famiclean_home = _resolve_path(project_root, values.get("FAMICLEAN_HOME"), "../famiclean-skill")
    if famiclean_home is None:
        raise RuntimeConfigError("FAMICLEAN_HOME must resolve to a usable path")
    famiclean_wrapper = _resolve_path(
        project_root,
        values.get("FAMICLEAN_WRAPPER"),
        str(Path("../famiclean-skill/skills/fami-claw-skill/fami-claw")),
    )
    if famiclean_wrapper is None:
        raise RuntimeConfigError("FAMICLEAN_WRAPPER must resolve to a usable path")
    famiclean_env_file = _resolve_path(project_root, values.get("FAMICLEAN_ENV_FILE"))

    google_service_account_file = _resolve_path(project_root, values.get("GOOGLE_SERVICE_ACCOUNT_FILE"))

    overrides = DeviceOverrides(
        device_ip=values.get("DEVICE_IP") or None,
        device_mac=values.get("DEVICE_MAC") or None,
        broadcast_ip=values.get("BROADCAST_IP") or None,
        port=_as_int(values.get("FAMICLEAN_PORT"), 0) or None,
        timeout_seconds=_as_float(values.get("FAMICLEAN_TIMEOUT_SECONDS"), 0.0) or None,
    )

    return AppConfig(
        project_root=project_root,
        env_file=env_path,
        state_dir=state_dir,
        log_dir=log_dir,
        famiclean_home=famiclean_home,
        famiclean_wrapper=famiclean_wrapper,
        famiclean_env_file=famiclean_env_file,
        host=values.get("FAMI_GHOME_HOST", "0.0.0.0"),
        port=_as_int(values.get("FAMI_GHOME_PORT"), 8787),
        public_base_url=values.get("PUBLIC_BASE_URL", "").strip(),
        timezone=values.get("TIMEZONE", "Asia/Taipei"),
        log_level=values.get("LOG_LEVEL", "INFO"),
        min_temp_celsius=_as_int(values.get("MIN_TEMP_CELSIUS"), 35),
        max_temp_celsius=_as_int(values.get("MAX_TEMP_CELSIUS"), 50),
        google_cloud_project_id=values.get("GOOGLE_CLOUD_PROJECT_ID", "").strip(),
        google_home_project_id=values.get("GOOGLE_HOME_PROJECT_ID", "").strip(),
        google_home_fulfillment_url=values.get("GOOGLE_HOME_FULFILLMENT_URL", "").strip(),
        google_home_local_app_id=values.get("GOOGLE_HOME_LOCAL_APP_ID", "").strip(),
        agent_user_id=values.get("AGENT_USER_ID", "fami-ghome-single-home").strip() or "fami-ghome-single-home",
        account_linking_client_id=values.get("ACCOUNT_LINKING_CLIENT_ID", "").strip(),
        account_linking_client_secret=values.get("ACCOUNT_LINKING_CLIENT_SECRET", "").strip(),
        account_linking_allowed_redirect_uris=_split_values(values.get("ACCOUNT_LINKING_ALLOWED_REDIRECT_URIS")),
        auth_admin_username=values.get("AUTH_ADMIN_USERNAME", "").strip(),
        auth_admin_password_hash=values.get("AUTH_ADMIN_PASSWORD_HASH", "").strip(),
        session_secret=values.get("SESSION_SECRET", "").strip(),
        token_encryption_key=values.get("TOKEN_ENCRYPTION_KEY", "").strip(),
        authorization_code_ttl_seconds=_as_int(values.get("AUTHORIZATION_CODE_TTL_SECONDS"), 300),
        access_token_ttl_seconds=_as_int(values.get("ACCESS_TOKEN_TTL_SECONDS"), 3600),
        refresh_token_ttl_days=_as_int(values.get("REFRESH_TOKEN_TTL_DAYS"), 180),
        local_home_enabled=_as_bool(values.get("LOCAL_HOME_ENABLED"), False),
        local_home_device_id=values.get("LOCAL_HOME_DEVICE_ID", "famiclean-water-heater-1").strip() or "famiclean-water-heater-1",
        local_home_scan_port=_as_int(values.get("LOCAL_HOME_SCAN_PORT"), 3311),
        local_home_listen_host=values.get("LOCAL_HOME_LISTEN_HOST", "0.0.0.0").strip() or "0.0.0.0",
        local_home_listen_port=_as_int(values.get("LOCAL_HOME_LISTEN_PORT"), 3322),
        google_service_account_file=google_service_account_file,
        internal_api_enabled=_as_bool(values.get("INTERNAL_API_ENABLED"), True),
        internal_api_token=values.get("INTERNAL_API_TOKEN", "").strip(),
        device_overrides=overrides,
    )


def ensure_runtime_dirs(config: AppConfig) -> None:
    config.state_dir.mkdir(parents=True, exist_ok=True)
    config.log_dir.mkdir(parents=True, exist_ok=True)
