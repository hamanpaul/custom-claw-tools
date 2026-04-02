"""Read daily GarminDB snapshots from SQLite outputs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
import sqlite3

from .config import RuntimeConfig, RuntimeConfigError


GARMIN_DB_NAME = "garmin.db"
GARMIN_ACTIVITIES_DB_NAME = "garmin_activities.db"


class GarminReaderError(Exception):
    """Raised when GarminDB outputs cannot be read."""


def _parse_datetime(value: object | None) -> datetime | None:
    if value in (None, ""):
        return None
    return datetime.fromisoformat(str(value))


def _parse_duration(value: object | None) -> timedelta | None:
    if value in (None, ""):
        return None
    text = str(value)
    for fmt in ("%H:%M:%S.%f", "%H:%M:%S"):
        try:
            parsed = datetime.strptime(text, fmt)
            return timedelta(
                hours=parsed.hour,
                minutes=parsed.minute,
                seconds=parsed.second,
                microseconds=parsed.microsecond,
            )
        except ValueError:
            continue
    raise GarminReaderError(f"Unsupported GarminDB time value: {text}")


@dataclass(frozen=True)
class SleepSnapshot:
    start: datetime | None
    end: datetime | None
    duration: timedelta | None
    score: int | None
    qualifier: str | None
    avg_stress: float | None

    def to_dict(self) -> dict[str, object]:
        return {
            "start": self.start.isoformat(sep=" ") if self.start else None,
            "end": self.end.isoformat(sep=" ") if self.end else None,
            "duration": str(self.duration) if self.duration else None,
            "score": self.score,
            "qualifier": self.qualifier,
            "avg_stress": self.avg_stress,
        }


@dataclass(frozen=True)
class DailySummarySnapshot:
    steps: int | None
    distance: float | None
    moderate_activity: timedelta | None
    vigorous_activity: timedelta | None
    calories_active: int | None
    description: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "steps": self.steps,
            "distance": self.distance,
            "moderate_activity": str(self.moderate_activity) if self.moderate_activity else None,
            "vigorous_activity": str(self.vigorous_activity) if self.vigorous_activity else None,
            "calories_active": self.calories_active,
            "description": self.description,
        }


@dataclass(frozen=True)
class ActivitySnapshot:
    activity_id: str
    name: str | None
    sport: str | None
    sub_sport: str | None
    start_time: datetime | None
    stop_time: datetime | None
    elapsed_time: timedelta | None
    distance: float | None
    calories: int | None
    avg_hr: int | None
    max_hr: int | None
    avg_cadence: int | None
    max_cadence: int | None
    training_load: float | None
    training_effect: float | None
    anaerobic_training_effect: float | None

    def to_dict(self) -> dict[str, object]:
        return {
            "activity_id": self.activity_id,
            "name": self.name,
            "sport": self.sport,
            "sub_sport": self.sub_sport,
            "start_time": self.start_time.isoformat(sep=" ") if self.start_time else None,
            "stop_time": self.stop_time.isoformat(sep=" ") if self.stop_time else None,
            "elapsed_time": str(self.elapsed_time) if self.elapsed_time else None,
            "distance": self.distance,
            "calories": self.calories,
            "avg_hr": self.avg_hr,
            "max_hr": self.max_hr,
            "avg_cadence": self.avg_cadence,
            "max_cadence": self.max_cadence,
            "training_load": self.training_load,
            "training_effect": self.training_effect,
            "anaerobic_training_effect": self.anaerobic_training_effect,
        }


@dataclass(frozen=True)
class DailyGarminSnapshot:
    day: date
    sleep: SleepSnapshot | None
    summary: DailySummarySnapshot | None
    activities: list[ActivitySnapshot]
    source_refs: list[str]

    def to_dict(self) -> dict[str, object]:
        return {
            "day": self.day.isoformat(),
            "sleep": self.sleep.to_dict() if self.sleep else None,
            "summary": self.summary.to_dict() if self.summary else None,
            "activities": [activity.to_dict() for activity in self.activities],
            "source_refs": self.source_refs,
        }


def _connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def _table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _read_sleep(garmin_db_path: Path, day_text: str) -> SleepSnapshot | None:
    if not garmin_db_path.exists():
        return None
    with _connect(garmin_db_path) as connection:
        if not _table_exists(connection, "sleep"):
            return None
        row = connection.execute(
            """
            SELECT start, "end", total_sleep, score, qualifier, avg_stress
            FROM sleep
            WHERE date(day) = ?
            ORDER BY day
            LIMIT 1
            """,
            (day_text,),
        ).fetchone()
        if row is None:
            return None
        return SleepSnapshot(
            start=_parse_datetime(row["start"]),
            end=_parse_datetime(row["end"]),
            duration=_parse_duration(row["total_sleep"]),
            score=row["score"],
            qualifier=row["qualifier"],
            avg_stress=row["avg_stress"],
        )


def _read_summary(garmin_db_path: Path, day_text: str) -> DailySummarySnapshot | None:
    if not garmin_db_path.exists():
        return None
    with _connect(garmin_db_path) as connection:
        if not _table_exists(connection, "daily_summary"):
            return None
        row = connection.execute(
            """
            SELECT steps, distance, moderate_activity_time, vigorous_activity_time, calories_active, description
            FROM daily_summary
            WHERE date(day) = ?
            ORDER BY day
            LIMIT 1
            """,
            (day_text,),
        ).fetchone()
        if row is None:
            return None
        return DailySummarySnapshot(
            steps=row["steps"],
            distance=row["distance"],
            moderate_activity=_parse_duration(row["moderate_activity_time"]),
            vigorous_activity=_parse_duration(row["vigorous_activity_time"]),
            calories_active=row["calories_active"],
            description=row["description"],
        )


def _read_activities(activities_db_path: Path, day_text: str) -> list[ActivitySnapshot]:
    if not activities_db_path.exists():
        return []
    with _connect(activities_db_path) as connection:
        if not _table_exists(connection, "activities"):
            return []
        rows = connection.execute(
            """
            SELECT activity_id, name, sport, sub_sport, start_time, stop_time, elapsed_time,
                   distance, calories, avg_hr, max_hr, avg_cadence, max_cadence,
                   training_load, training_effect, anaerobic_training_effect
            FROM activities
            WHERE date(start_time) = ?
            ORDER BY start_time
            """,
            (day_text,),
        ).fetchall()
        return [
            ActivitySnapshot(
                activity_id=row["activity_id"],
                name=row["name"],
                sport=row["sport"],
                sub_sport=row["sub_sport"],
                start_time=_parse_datetime(row["start_time"]),
                stop_time=_parse_datetime(row["stop_time"]),
                elapsed_time=_parse_duration(row["elapsed_time"]),
                distance=row["distance"],
                calories=row["calories"],
                avg_hr=row["avg_hr"],
                max_hr=row["max_hr"],
                avg_cadence=row["avg_cadence"],
                max_cadence=row["max_cadence"],
                training_load=row["training_load"],
                training_effect=row["training_effect"],
                anaerobic_training_effect=row["anaerobic_training_effect"],
            )
            for row in rows
        ]


def read_daily_snapshot(runtime: RuntimeConfig, target_day: date) -> DailyGarminSnapshot | None:
    """Read one Garmin day from the GarminDB outputs."""

    if runtime.garmin is None:
        raise RuntimeConfigError("Garmin layout is not configured; cannot ingest GarminDB outputs.")

    day_text = target_day.isoformat()
    garmin_db_path = runtime.garmin.db_dir / GARMIN_DB_NAME
    activities_db_path = runtime.garmin.db_dir / GARMIN_ACTIVITIES_DB_NAME

    sleep = _read_sleep(garmin_db_path, day_text)
    summary = _read_summary(garmin_db_path, day_text)
    activities = _read_activities(activities_db_path, day_text)

    if sleep is None and summary is None and not activities:
        return None

    source_refs = [str(garmin_db_path)]
    if activities:
        source_refs.append(str(activities_db_path))

    return DailyGarminSnapshot(
        day=target_day,
        sleep=sleep,
        summary=summary,
        activities=activities,
        source_refs=source_refs,
    )
