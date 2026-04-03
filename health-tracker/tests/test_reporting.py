from __future__ import annotations

from datetime import date
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from health_tracker_garmin.cli import main


def _daily_template() -> str:
    return (
        Path(__file__).resolve().parent.parent / "templates" / "daily-log-template.md"
    ).read_text(encoding="utf-8")


def _write_daily_note(
    path: Path,
    *,
    target_day: date,
    weekday: str,
    replacements: dict[str, str],
) -> None:
    text = _daily_template().replace("{{date}}", target_day.isoformat()).replace("{{weekday}}", weekday)
    for source, replacement in replacements.items():
        text = text.replace(source, replacement, 1)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class _FakeResponse:
    def __init__(self, payload: dict[str, object]):
        self._payload = payload

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


class ReportGenerationTest(unittest.TestCase):
    def test_update_reports_sends_telegram_summary_with_explicit_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            notes_root = temp_root / "notes" / "claw" / "health"
            daily_root = notes_root / "daily"
            token_file = temp_root / "telegram.token"
            token_file.write_text("TESTTOKEN\n", encoding="utf-8")

            _write_daily_note(
                daily_root / "2026-04-01.md",
                target_day=date(2026, 4, 1),
                weekday="週三",
                replacements={
                    "- 資料完整度：高 / 中 / 低": "- 資料完整度：高",
                    "- 步數：": "- 步數：10000",
                    "- 睡眠時數：": "- 睡眠時數：7 小時",
                    "- 活動摘要：": "- 活動摘要：晨跑 5K",
                    "- 今日訓練重點：": "- 今日訓練重點：上肢訓練",
                    "- 今日總攝取熱量：": "- 今日總攝取熱量：2100 kcal",
                    "- 今日總蛋白質：": "- 今日總蛋白質：130 g",
                    "- 體重：": "- 體重：70.4 kg",
                    "- 體脂：": "- 體脂：18.1%",
                },
            )
            _write_daily_note(
                daily_root / "2026-04-02.md",
                target_day=date(2026, 4, 2),
                weekday="週四",
                replacements={
                    "- 資料完整度：高 / 中 / 低": "- 資料完整度：高",
                    "- 步數：": "- 步數：12000",
                    "- 睡眠時數：": "- 睡眠時數：7 小時 30 分",
                    "- 活動摘要：": "- 活動摘要：快走與通勤",
                    "- 今日訓練重點：": "- 今日訓練重點：下肢訓練",
                    "- 今日總攝取熱量：": "- 今日總攝取熱量：2200 kcal",
                    "- 今日總蛋白質：": "- 今日總蛋白質：140 g",
                    "- 體重：": "- 體重：70.0 kg",
                    "- 體脂：": "- 體脂：17.8%",
                },
            )

            runtime_config = temp_root / "garmin-runtime.json"
            runtime_config.write_text(
                json.dumps(
                    {
                        "garmin_config_path": str(temp_root / "missing-garmin.json"),
                        "notes_root": str(notes_root),
                        "templates_root": str(temp_root / "missing-live-templates"),
                        "lookback_days": 2,
                        "notifications": {
                            "telegram": {
                                "enabled": True,
                                "chat_id": "telegram:123456",
                                "bot_token_file": str(token_file),
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            sent_requests = []

            def fake_urlopen(request, timeout):
                self.assertEqual(timeout, 20)
                sent_requests.append(request)
                return _FakeResponse({"ok": True, "result": {"message_id": 1}})

            with patch("health_tracker_garmin.notifications.urlopen", side_effect=fake_urlopen):
                exit_code = main(
                    [
                        "--runtime-config",
                        str(runtime_config),
                        "update-reports",
                        "--date",
                        "2026-04-02",
                        "--lookback-days",
                        "2",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(len(sent_requests), 1)
            payload = json.loads(sent_requests[0].data.decode("utf-8"))
            self.assertEqual(payload["chat_id"], "123456")
            self.assertIn("月報 2026-04", payload["text"])
            self.assertIn("季報 2026-Q2", payload["text"])
            self.assertIn("年報 2026", payload["text"])

            monthly_report = notes_root / "reports" / "monthly" / "2026-04.md"
            self.assertTrue(monthly_report.exists())
            monthly_text = monthly_report.read_text(encoding="utf-8")
            self.assertIn("11,000", monthly_text)
            self.assertIn("7 小時 15 分", monthly_text)
            self.assertIn("17.8%", monthly_text)

    def test_update_reports_can_fallback_to_picoclaw_allowlist_chat_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            notes_root = temp_root / "notes" / "claw" / "health"
            daily_root = notes_root / "daily"
            picoclaw_config = temp_root / "picoclaw-config.json"
            picoclaw_config.write_text(
                json.dumps(
                    {
                        "channels": {
                            "telegram": {
                                "enabled": True,
                                "token": "PICOCLAWTOKEN",
                                "allow_from": ["telegram:999888777"],
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            _write_daily_note(
                daily_root / "2026-04-03.md",
                target_day=date(2026, 4, 3),
                weekday="週五",
                replacements={
                    "- 資料完整度：高 / 中 / 低": "- 資料完整度：中",
                    "- 步數：": "- 步數：8000",
                    "- 睡眠時數：": "- 睡眠時數：6 小時 40 分",
                    "- 活動摘要：": "- 活動摘要：通勤與散步",
                    "- 今日訓練重點：": "- 今日訓練重點：本日沒有 Garmin 活動 session",
                },
            )

            runtime_config = temp_root / "garmin-runtime.json"
            runtime_config.write_text(
                json.dumps(
                    {
                        "garmin_config_path": str(temp_root / "missing-garmin.json"),
                        "notes_root": str(notes_root),
                        "templates_root": str(temp_root / "missing-live-templates"),
                        "lookback_days": 1,
                        "notifications": {
                            "telegram": {
                                "enabled": True,
                                "picoclaw_config_path": str(picoclaw_config),
                                "fallback_to_picoclaw_config": True,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            sent_requests = []

            def fake_urlopen(request, timeout):
                sent_requests.append(request)
                return _FakeResponse({"ok": True, "result": {"message_id": 1}})

            with patch("health_tracker_garmin.notifications.urlopen", side_effect=fake_urlopen):
                exit_code = main(
                    [
                        "--runtime-config",
                        str(runtime_config),
                        "update-reports",
                        "--date",
                        "2026-04-03",
                        "--lookback-days",
                        "1",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(len(sent_requests), 1)
            payload = json.loads(sent_requests[0].data.decode("utf-8"))
            self.assertEqual(payload["chat_id"], "999888777")

    def test_update_reports_can_fallback_to_numeric_picoclaw_allowlist_chat_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            notes_root = temp_root / "notes" / "claw" / "health"
            daily_root = notes_root / "daily"
            picoclaw_config = temp_root / "picoclaw-config.json"
            picoclaw_config.write_text(
                json.dumps(
                    {
                        "channels": {
                            "telegram": {
                                "enabled": True,
                                "token": "PICOCLAWTOKEN",
                                "allow_from": [8313353234],
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            _write_daily_note(
                daily_root / "2026-04-03.md",
                target_day=date(2026, 4, 3),
                weekday="週五",
                replacements={
                    "- 資料完整度：高 / 中 / 低": "- 資料完整度：中",
                    "- 步數：": "- 步數：8000",
                    "- 睡眠時數：": "- 睡眠時數：6 小時 40 分",
                    "- 活動摘要：": "- 活動摘要：通勤與散步",
                    "- 今日訓練重點：": "- 今日訓練重點：本日沒有 Garmin 活動 session",
                },
            )

            runtime_config = temp_root / "garmin-runtime.json"
            runtime_config.write_text(
                json.dumps(
                    {
                        "garmin_config_path": str(temp_root / "missing-garmin.json"),
                        "notes_root": str(notes_root),
                        "templates_root": str(temp_root / "missing-live-templates"),
                        "lookback_days": 1,
                        "notifications": {
                            "telegram": {
                                "enabled": True,
                                "picoclaw_config_path": str(picoclaw_config),
                                "fallback_to_picoclaw_config": True,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            sent_requests = []

            def fake_urlopen(request, timeout):
                sent_requests.append(request)
                return _FakeResponse({"ok": True, "result": {"message_id": 1}})

            with patch("health_tracker_garmin.notifications.urlopen", side_effect=fake_urlopen):
                exit_code = main(
                    [
                        "--runtime-config",
                        str(runtime_config),
                        "update-reports",
                        "--date",
                        "2026-04-03",
                        "--lookback-days",
                        "1",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(len(sent_requests), 1)
            payload = json.loads(sent_requests[0].data.decode("utf-8"))
            self.assertEqual(payload["chat_id"], "8313353234")


if __name__ == "__main__":
    unittest.main()
