from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import json
import sys
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "skills" / "fami-claw-skill" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from famiclean import build_threshold_message, run_check_threshold
from tools.famiclean_env import FamicleanSettings


class BuildThresholdMessageTests(unittest.TestCase):
    def test_build_threshold_message_uses_notification_for_regular_cross(self) -> None:
        subject, message, classification = build_threshold_message(
            {
                "gas_total_m3": 81.51,
                "current_threshold_m3": 80,
                "crossed_thresholds_m3": [80],
                "remaining_to_next_threshold_m3": 18.49,
                "device": {"ip": "192.0.2.10", "mac": "AA:BB:CC:DD:EE:FF"},
                "checked_at": "2026-04-18T08:00:00+08:00",
            },
            warning_remaining_m3=3.0,
        )

        self.assertEqual(subject, "Famiclean 瓦斯用量通知")
        self.assertEqual(classification["level"], "notification")
        self.assertEqual(classification["reason"], "threshold_crossed")
        self.assertIn("通知：瓦斯用量已跨越例行門檻", message)
        self.assertIn("距離下一個門檻: 18.49 M3", message)

    def test_build_threshold_message_uses_warning_when_close_to_next_threshold(self) -> None:
        subject, message, classification = build_threshold_message(
            {
                "gas_total_m3": 99.20,
                "current_threshold_m3": 80,
                "crossed_thresholds_m3": [80],
                "remaining_to_next_threshold_m3": 0.8,
                "device": {"ip": "192.0.2.10", "mac": "AA:BB:CC:DD:EE:FF"},
                "checked_at": "2026-04-18T08:00:00+08:00",
            },
            warning_remaining_m3=3.0,
        )

        self.assertEqual(subject, "Famiclean 瓦斯用量警告")
        self.assertEqual(classification["level"], "warning")
        self.assertEqual(classification["reason"], "approaching_next_threshold")
        self.assertIn("警告：瓦斯用量已接近下一個門檻", message)
        self.assertIn("原因: 距離下一個門檻僅剩 0.80 M3", message)


class RunCheckThresholdTests(unittest.TestCase):
    def test_run_check_threshold_records_warning_subject(self) -> None:
        with TemporaryDirectory() as temp_dir:
            state_file = Path(temp_dir) / "famiclean-state.json"
            state_file.write_text(
                json.dumps({"last_notified_threshold_m3": 60}, ensure_ascii=False),
                encoding="utf-8",
            )

            settings = FamicleanSettings(
                home_dir=Path(temp_dir),
                env_file=Path(temp_dir) / ".env",
                state_file=state_file,
                warning_remaining_m3=3.0,
            )

            reading = {
                "gas_total_m3": 99.20,
                "raw_heatvalue_total": 900000,
                "raw_heatvalue_count": 1000,
                "raw_effective_heatvalue_total": 901000,
                "gas_count_m3": 0.11,
                "threshold_step_m3": 20,
                "current_threshold_m3": 80,
                "next_threshold_m3": 100,
                "remaining_to_next_threshold_m3": 0.8,
                "device": {"ip": "192.0.2.10", "mac": "AA:BB:CC:DD:EE:FF"},
            }

            class FakeSession:
                def __init__(self, *_args, **_kwargs) -> None:
                    pass

                def __enter__(self) -> "FakeSession":
                    return self

                def __exit__(self, exc_type, exc, tb) -> bool:
                    return False

                def get_total_gas(self, *, device_ip=None, device_mac=None):
                    return reading

            with (
                mock.patch("famiclean.FamicleanSession", FakeSession),
                mock.patch(
                    "famiclean.dispatch_notifications",
                    return_value={
                        "configured_channels": ["telegram"],
                        "sent_channels": ["telegram"],
                        "failed_channels": [],
                        "success": True,
                    },
                ) as dispatch_mock,
            ):
                result = run_check_threshold(
                    settings,
                    device_ip=None,
                    device_mac=None,
                    send_notifications=True,
                    force_notify=False,
                )

            dispatch_mock.assert_called_once()
            sent_subject = dispatch_mock.call_args.args[1]
            sent_message = dispatch_mock.call_args.args[2]
            self.assertEqual(sent_subject, "Famiclean 瓦斯用量警告")
            self.assertIn("警告：瓦斯用量已接近下一個門檻", sent_message)
            self.assertEqual(result["notification"]["level"], "warning")
            self.assertEqual(result["notification"]["classification_reason"], "approaching_next_threshold")

            saved_state = json.loads(state_file.read_text(encoding="utf-8"))
            self.assertEqual(saved_state["last_notification_subject"], "Famiclean 瓦斯用量警告")


if __name__ == "__main__":
    unittest.main()
