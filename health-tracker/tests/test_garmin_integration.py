from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from health_tracker_garmin.cli import main
from health_tracker_garmin.config import RuntimeConfigError, load_runtime_config


def _write_sqlite(path: Path, statements: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        for statement in statements:
            connection.execute(statement)
        connection.commit()


class GarminIntegrationTest(unittest.TestCase):
    def test_load_runtime_config_rejects_inline_password(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            garmin_config = temp_root / "GarminConnectConfig.json"
            garmin_config.write_text(
                json.dumps(
                    {
                        "credentials": {
                            "user": "runner@example.com",
                            "password": "secret-inline-password",
                            "password_file": None,
                        },
                        "directories": {
                            "relative_to_home": False,
                            "base_dir": str(temp_root / "HealthData"),
                        },
                    }
                ),
                encoding="utf-8",
            )
            runtime_config = temp_root / "garmin-runtime.json"
            runtime_config.write_text(
                json.dumps(
                    {
                        "garmin_config_path": str(garmin_config),
                        "notes_root": str(temp_root / "notes" / "claw" / "health"),
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaises(RuntimeConfigError):
                load_runtime_config(runtime_config)

    def test_load_runtime_config_rejects_missing_password_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            missing_password_file = temp_root / "secrets" / "missing.password"
            garmin_config = temp_root / "GarminConnectConfig.json"
            garmin_config.write_text(
                json.dumps(
                    {
                        "credentials": {
                            "user": "runner@example.com",
                            "password": "",
                            "password_file": str(missing_password_file),
                        },
                        "directories": {
                            "relative_to_home": False,
                            "base_dir": str(temp_root / "HealthData"),
                        },
                    }
                ),
                encoding="utf-8",
            )
            runtime_config = temp_root / "garmin-runtime.json"
            runtime_config.write_text(
                json.dumps(
                    {
                        "garmin_config_path": str(garmin_config),
                        "notes_root": str(temp_root / "notes" / "claw" / "health"),
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaises(RuntimeConfigError):
                load_runtime_config(runtime_config)

    def test_ingest_garmin_updates_daily_without_overwriting_manual_sections(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            notes_root = temp_root / "notes" / "claw" / "health"
            daily_root = notes_root / "daily"
            daily_root.mkdir(parents=True, exist_ok=True)

            password_file = temp_root / "secrets" / "garmin.password"
            password_file.parent.mkdir(parents=True, exist_ok=True)
            password_file.write_text("not-a-real-password\n", encoding="utf-8")

            garmin_config = temp_root / "GarminConnectConfig.json"
            garmin_config.write_text(
                json.dumps(
                    {
                        "credentials": {
                            "user": "runner@example.com",
                            "password": "",
                            "password_file": str(password_file),
                        },
                        "directories": {
                            "relative_to_home": False,
                            "base_dir": str(temp_root / "HealthData"),
                        },
                    }
                ),
                encoding="utf-8",
            )

            runtime_config = temp_root / "garmin-runtime.json"
            runtime_config.write_text(
                json.dumps(
                    {
                        "garmin_config_path": str(garmin_config),
                        "notes_root": str(notes_root),
                        "templates_root": str(temp_root / "missing-live-templates"),
                        "lookback_days": 1,
                    }
                ),
                encoding="utf-8",
            )

            garmin_db = temp_root / "HealthData" / "DBs" / "garmin.db"
            activities_db = temp_root / "HealthData" / "DBs" / "garmin_activities.db"
            _write_sqlite(
                garmin_db,
                [
                    """
                    CREATE TABLE sleep (
                      day TEXT PRIMARY KEY,
                      start TEXT,
                      "end" TEXT,
                      total_sleep TEXT,
                      score INTEGER,
                      qualifier TEXT,
                      avg_stress REAL
                    )
                    """,
                    """
                    INSERT INTO sleep(day, start, "end", total_sleep, score, qualifier, avg_stress)
                    VALUES ('2026-04-01 00:00:00', '2026-04-01 23:10:00', '2026-04-02 06:28:00', '07:18:00.000000', 82, 'good', 18.0)
                    """,
                    """
                    CREATE TABLE daily_summary (
                      day TEXT PRIMARY KEY,
                      steps INTEGER,
                      distance REAL,
                      moderate_activity_time TEXT,
                      vigorous_activity_time TEXT,
                      calories_active INTEGER,
                      description TEXT
                    )
                    """,
                    """
                    INSERT INTO daily_summary(day, steps, distance, moderate_activity_time, vigorous_activity_time, calories_active, description)
                    VALUES ('2026-04-01 00:00:00', 10234, 8.75, '00:42:00.000000', '00:13:00.000000', 520, '日常活動與跑步')
                    """,
                ],
            )
            _write_sqlite(
                activities_db,
                [
                    """
                    CREATE TABLE activities (
                      activity_id TEXT PRIMARY KEY,
                      name TEXT,
                      sport TEXT,
                      sub_sport TEXT,
                      start_time TEXT,
                      stop_time TEXT,
                      elapsed_time TEXT,
                      distance REAL,
                      calories INTEGER,
                      avg_hr INTEGER,
                      max_hr INTEGER,
                      avg_cadence INTEGER,
                      max_cadence INTEGER,
                      training_load REAL,
                      training_effect REAL,
                      anaerobic_training_effect REAL
                    )
                    """,
                    """
                    INSERT INTO activities(
                      activity_id, name, sport, sub_sport, start_time, stop_time, elapsed_time,
                      distance, calories, avg_hr, max_hr, avg_cadence, max_cadence, training_load, training_effect, anaerobic_training_effect
                    ) VALUES (
                      'run-001', '晨跑', 'running', 'road_running', '2026-04-01 06:30:00', '2026-04-01 07:15:00', '00:45:00.000000',
                      8.75, 520, 148, 173, 164, 182, 187.5, 3.4, 1.2
                    )
                    """,
                ],
            )

            repo_template = (
                Path(__file__).resolve().parent.parent / "templates" / "daily-log-template.md"
            ).read_text(encoding="utf-8")
            daily_path = daily_root / "2026-04-01.md"
            daily_path.write_text(
                repo_template.replace("{{date}}", "2026-04-01")
                .replace("{{weekday}}", "週三")
                .replace("- 餐點名稱：", "- 餐點名稱：保留的手動早餐", 1)
                .replace("- 今日訓練重點：", "- 今日訓練重點：保留的手動重量訓練", 1),
                encoding="utf-8",
            )

            exit_code = main(
                [
                    "--runtime-config",
                    str(runtime_config),
                    "ingest-garmin",
                    "--date",
                    "2026-04-01",
                    "--lookback-days",
                    "1",
                    "--captured-at",
                    "2026-04-02T06:00:00+08:00",
                ]
            )

            self.assertEqual(exit_code, 0)
            updated_daily = daily_path.read_text(encoding="utf-8")
            self.assertIn("- 餐點名稱：保留的手動早餐", updated_daily)
            self.assertIn("- 今日訓練重點：保留的手動重量訓練", updated_daily)
            self.assertIn("- 步數：10234", updated_daily)
            self.assertIn("- 睡眠時數：7 小時 18 分", updated_daily)
            self.assertIn("- 今日訓練重點：Garmin 共 1 筆活動，總距離 8.75（依 Garmin 單位）", updated_daily)
            self.assertIn("raw/2026/04/01/20260402T060000+0800-garmin-day-import.md", updated_daily)

            raw_path = notes_root / "raw" / "2026" / "04" / "01" / "20260402T060000+0800-garmin-day-import.md"
            self.assertTrue(raw_path.exists())
            raw_text = raw_path.read_text(encoding="utf-8")
            self.assertIn('"activity_id": "run-001"', raw_text)
            self.assertIn('"steps": 10234', raw_text)
            self.assertIn('"distance": 8.75', raw_text)

            monthly_report = notes_root / "reports" / "monthly" / "2026-04.md"
            quarterly_report = notes_root / "reports" / "quarterly" / "2026-Q2.md"
            yearly_report = notes_root / "reports" / "yearly" / "2026.md"
            self.assertTrue(monthly_report.exists())
            self.assertTrue(quarterly_report.exists())
            self.assertTrue(yearly_report.exists())
            self.assertIn("平均步數", monthly_report.read_text(encoding="utf-8"))
            self.assertIn("2026-04", monthly_report.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
