"""Runtime configuration for the health-tracker Garmin integration."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


class RuntimeConfigError(Exception):
    """Raised when runtime configuration is missing or invalid."""


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RUNTIME_CONFIG_PATH = Path.home() / ".config" / "health-tracker" / "garmin-runtime.json"
DEFAULT_GARMIN_CONFIG_PATH = Path.home() / ".GarminDb" / "GarminConnectConfig.json"
DEFAULT_NOTES_ROOT = Path.home() / ".picoclaw" / "workspace" / "notes" / "claw" / "health"
DEFAULT_TEMPLATES_ROOT = DEFAULT_NOTES_ROOT / "templates"
DEFAULT_LOOKBACK_DAYS = 3


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeConfigError(f"Missing required JSON file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeConfigError(f"Invalid JSON in {path}: {exc}") from exc


def _resolve_path(raw_value: str | None, base_dir: Path, default: Path) -> Path:
    value = Path(raw_value).expanduser() if raw_value else default.expanduser()
    if value.is_absolute():
        return value
    return (base_dir / value).resolve()


def _resolve_command(raw_value: str | None) -> str:
    return raw_value or "garmindb_cli.py"


@dataclass(frozen=True)
class GarminDbLayout:
    """Resolved GarminDB runtime layout."""

    config_path: Path
    config_dir: Path
    base_dir: Path
    db_dir: Path
    password_file: Path


@dataclass(frozen=True)
class RuntimeConfig:
    """Resolved runtime configuration."""

    runtime_config_path: Path
    garmin_config_path: Path
    garmin: GarminDbLayout | None
    garmindb_cli: str
    notes_root: Path
    templates_root: Path
    repo_templates_root: Path
    lookback_days: int

    @property
    def raw_root(self) -> Path:
        return self.notes_root / "raw"

    @property
    def daily_root(self) -> Path:
        return self.notes_root / "daily"


def build_runtime_example() -> dict[str, Any]:
    """Return a repo-safe example runtime config."""

    return {
        "garmin_config_path": str(DEFAULT_GARMIN_CONFIG_PATH),
        "garmindb_cli": "garmindb_cli.py",
        "notes_root": str(DEFAULT_NOTES_ROOT),
        "templates_root": str(DEFAULT_TEMPLATES_ROOT),
        "lookback_days": DEFAULT_LOOKBACK_DAYS,
    }


def write_runtime_example(output_path: Path, *, overwrite: bool = False) -> Path:
    """Write a repo-safe example runtime config."""

    output_path = output_path.expanduser()
    if output_path.exists() and not overwrite:
        raise RuntimeConfigError(f"Refusing to overwrite existing runtime config: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(build_runtime_example(), ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return output_path


def _load_garmin_layout(config_path: Path, *, require_password_file: bool) -> GarminDbLayout:
    config_path = config_path.expanduser().resolve()
    payload = _read_json(config_path)
    directories = payload.get("directories", {})
    credentials = payload.get("credentials", {})

    base_dir_value = directories.get("base_dir", "HealthData")
    if directories.get("relative_to_home", True):
        base_dir = Path.home() / base_dir_value
    else:
        base_candidate = Path(base_dir_value).expanduser()
        base_dir = base_candidate if base_candidate.is_absolute() else (config_path.parent / base_candidate).resolve()

    password_file_value = credentials.get("password_file")
    if require_password_file:
        if credentials.get("password"):
            raise RuntimeConfigError(
                "health-tracker Garmin integration requires GarminConnectConfig.json to use "
                "`credentials.password_file`, not inline `credentials.password`."
            )
        if not password_file_value:
            raise RuntimeConfigError(
                "GarminConnectConfig.json is missing `credentials.password_file`. "
                "Keep Garmin secrets outside the repo and point GarminDB to a password file."
            )

    password_file = _resolve_path(password_file_value, config_path.parent, config_path.parent / "missing-password-file")
    if require_password_file and not password_file.is_file():
        raise RuntimeConfigError(
            "Password file configured in GarminConnectConfig.json does not exist or is not a file: "
            f"{password_file}"
        )
    return GarminDbLayout(
        config_path=config_path,
        config_dir=config_path.parent,
        base_dir=base_dir,
        db_dir=base_dir / "DBs",
        password_file=password_file,
    )


def load_runtime_config(
    runtime_config_path: Path | None = None,
    *,
    require_garmin: bool = True,
    require_password_file: bool = True,
) -> RuntimeConfig:
    """Load runtime config, allowing repo-safe defaults when the file is absent."""

    runtime_path = runtime_config_path.expanduser().resolve() if runtime_config_path else DEFAULT_RUNTIME_CONFIG_PATH
    payload: dict[str, Any] = {}
    if runtime_path.exists():
        payload = _read_json(runtime_path)

    base_dir = runtime_path.parent
    notes_root = _resolve_path(payload.get("notes_root"), base_dir, DEFAULT_NOTES_ROOT)
    templates_root = _resolve_path(payload.get("templates_root"), base_dir, DEFAULT_TEMPLATES_ROOT)
    lookback_days = int(payload.get("lookback_days", DEFAULT_LOOKBACK_DAYS))
    if lookback_days < 1:
        raise RuntimeConfigError("lookback_days must be at least 1.")

    garmin_config_path = _resolve_path(payload.get("garmin_config_path"), base_dir, DEFAULT_GARMIN_CONFIG_PATH)
    garmin_layout: GarminDbLayout | None = None
    if require_garmin or garmin_config_path.exists():
        garmin_layout = _load_garmin_layout(
            garmin_config_path,
            require_password_file=require_password_file,
        )

    return RuntimeConfig(
        runtime_config_path=runtime_path,
        garmin_config_path=garmin_config_path,
        garmin=garmin_layout,
        garmindb_cli=_resolve_command(payload.get("garmindb_cli")),
        notes_root=notes_root,
        templates_root=templates_root,
        repo_templates_root=PROJECT_ROOT / "templates",
        lookback_days=lookback_days,
    )
