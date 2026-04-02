"""Wrapper for driving GarminDB sync from health-tracker."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

from .config import RuntimeConfig, RuntimeConfigError


class GarminSyncError(Exception):
    """Raised when GarminDB sync cannot be started or fails."""


def _resolve_garmindb_cli(command: str) -> str:
    if "/" in command:
        candidate = Path(command).expanduser().resolve()
        if not candidate.exists():
            raise GarminSyncError(f"Configured GarminDB CLI does not exist: {candidate}")
        return str(candidate)

    resolved = shutil.which(command)
    if not resolved:
        raise GarminSyncError(
            f"Cannot find `{command}` in PATH. Install GarminDB first, for example with `pip install garmindb`."
        )
    return resolved


def build_sync_command(
    runtime: RuntimeConfig,
    *,
    latest: bool = True,
    resolve_executable: bool = True,
) -> list[str]:
    """Build the GarminDB CLI command."""

    config_dir = runtime.garmin.config_dir if runtime.garmin is not None else runtime.garmin_config_path.parent
    command = [
        _resolve_garmindb_cli(runtime.garmindb_cli) if resolve_executable else runtime.garmindb_cli,
        "--config",
        str(config_dir),
        "--all",
        "--download",
        "--import",
        "--analyze",
    ]
    if latest:
        command.append("--latest")
    return command


def run_sync(runtime: RuntimeConfig, *, latest: bool = True, dry_run: bool = False) -> list[str]:
    """Run GarminDB sync and return the exact command used."""

    command = build_sync_command(runtime, latest=latest, resolve_executable=not dry_run)
    if dry_run:
        return command

    completed = subprocess.run(command, check=False)
    if completed.returncode != 0:
        raise GarminSyncError(f"GarminDB sync failed with exit code {completed.returncode}.")
    return command
