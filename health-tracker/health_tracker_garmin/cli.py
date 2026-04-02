"""CLI for health-tracker GarminDB integration."""

from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
from pathlib import Path
import shlex
import sys

from .config import (
    DEFAULT_RUNTIME_CONFIG_PATH,
    RuntimeConfigError,
    load_runtime_config,
    write_runtime_example,
)
from .garmin_reader import DailyGarminSnapshot, read_daily_snapshot
from .garmin_sync import GarminSyncError, run_sync
from .note_writer import GarminNoteWriter


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def _parse_captured_at(value: str | None) -> datetime:
    if value:
        return datetime.fromisoformat(value)
    return datetime.now().astimezone()


def _target_days(end_day: date | None, lookback_days: int) -> list[date]:
    final_day = end_day or date.today()
    return [final_day - timedelta(days=offset) for offset in reversed(range(lookback_days))]


def _print_snapshot_results(results: list[tuple[DailyGarminSnapshot, Path, Path]]) -> None:
    for snapshot, daily_path, raw_path in results:
        print(
            f"{snapshot.day.isoformat()}: daily -> {daily_path} ; raw -> {raw_path}",
            file=sys.stdout,
        )


def cmd_init_runtime(args: argparse.Namespace) -> int:
    output_path = args.path or DEFAULT_RUNTIME_CONFIG_PATH
    written = write_runtime_example(output_path, overwrite=args.force)
    print(
        f"Wrote example runtime config to {written}\n"
        "Secrets stay in repo-external ~/.GarminDb/GarminConnectConfig.json using credentials.password_file.",
        file=sys.stdout,
    )
    return 0


def cmd_sync_garmin(args: argparse.Namespace) -> int:
    runtime = load_runtime_config(
        args.runtime_config,
        require_garmin=not args.dry_run,
        require_password_file=not args.dry_run,
    )
    command = run_sync(runtime, latest=not args.full, dry_run=args.dry_run)
    if args.dry_run:
        print("Dry run:", shlex.join(command), file=sys.stdout)
    else:
        print(f"Completed GarminDB sync via: {shlex.join(command)}", file=sys.stdout)
    return 0


def _ingest(runtime_config_path: Path | None, args: argparse.Namespace) -> int:
    runtime = load_runtime_config(
        runtime_config_path,
        require_garmin=not args.dry_run,
        require_password_file=not args.dry_run,
    )
    captured_at = _parse_captured_at(args.captured_at)
    writer = GarminNoteWriter(runtime)
    results: list[tuple[DailyGarminSnapshot, Path, Path]] = []
    for target_day in _target_days(args.date, args.lookback_days or runtime.lookback_days):
        snapshot = read_daily_snapshot(runtime, target_day)
        if snapshot is None:
            print(f"{target_day.isoformat()}: no Garmin data found in DB outputs", file=sys.stdout)
            continue
        write_result = writer.write_snapshot(snapshot, captured_at=captured_at, dry_run=args.dry_run)
        results.append((snapshot, write_result.daily_path, write_result.raw_path))
    if results:
        _print_snapshot_results(results)
    return 0


def cmd_ingest_garmin(args: argparse.Namespace) -> int:
    return _ingest(args.runtime_config, args)


def cmd_sync_and_ingest(args: argparse.Namespace) -> int:
    runtime = load_runtime_config(
        args.runtime_config,
        require_garmin=not args.dry_run,
        require_password_file=not args.dry_run,
    )
    command = run_sync(runtime, latest=not args.full, dry_run=args.dry_run)
    if args.dry_run:
        print("Dry run sync:", shlex.join(command), file=sys.stdout)
    args.lookback_days = args.lookback_days or runtime.lookback_days
    return _ingest(args.runtime_config, args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="GarminDB integration for health-tracker.")
    parser.add_argument(
        "--runtime-config",
        type=Path,
        default=None,
        help=f"Path to runtime config JSON (default: {DEFAULT_RUNTIME_CONFIG_PATH})",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init-runtime", help="Write a repo-safe example runtime config.")
    init_parser.add_argument("--path", type=Path, default=DEFAULT_RUNTIME_CONFIG_PATH)
    init_parser.add_argument("--force", action="store_true", help="Overwrite an existing runtime config.")
    init_parser.set_defaults(func=cmd_init_runtime)

    sync_parser = subparsers.add_parser("sync-garmin", help="Run GarminDB latest/full sync.")
    sync_parser.add_argument("--full", action="store_true", help="Run a full sync instead of --latest.")
    sync_parser.add_argument("--dry-run", action="store_true", help="Print the GarminDB command without executing it.")
    sync_parser.set_defaults(func=cmd_sync_garmin)

    ingest_parser = subparsers.add_parser("ingest-garmin", help="Map GarminDB outputs into canonical health notes.")
    ingest_parser.add_argument("--date", type=_parse_date, default=None, help="End date to ingest, YYYY-MM-DD (default: today).")
    ingest_parser.add_argument("--lookback-days", type=int, default=None, help="How many days ending at --date to ingest.")
    ingest_parser.add_argument("--captured-at", type=str, default=None, help="Fixed ISO 8601 timestamp for deterministic raw filenames.")
    ingest_parser.add_argument("--dry-run", action="store_true", help="Compute paths without writing files.")
    ingest_parser.set_defaults(func=cmd_ingest_garmin)

    sync_ingest_parser = subparsers.add_parser("sync-and-ingest", help="Run GarminDB sync, then ingest notes.")
    sync_ingest_parser.add_argument("--full", action="store_true", help="Run a full sync instead of --latest.")
    sync_ingest_parser.add_argument("--date", type=_parse_date, default=None, help="End date to ingest, YYYY-MM-DD (default: today).")
    sync_ingest_parser.add_argument("--lookback-days", type=int, default=None, help="How many days ending at --date to ingest.")
    sync_ingest_parser.add_argument("--captured-at", type=str, default=None, help="Fixed ISO 8601 timestamp for deterministic raw filenames.")
    sync_ingest_parser.add_argument("--dry-run", action="store_true", help="Print sync command and computed note paths without writing.")
    sync_ingest_parser.set_defaults(func=cmd_sync_and_ingest)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (GarminSyncError, RuntimeConfigError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
