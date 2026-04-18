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

from tools.famiclean_env import FamicleanSettings, load_settings
from tools.famiclean_notify import dispatch_notifications


class _FakeResponse:
    def __init__(self, payload: str = ""):
        self._payload = payload

    def read(self) -> bytes:
        return self._payload.encode("utf-8")

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class LoadSettingsTests(unittest.TestCase):
    def test_load_settings_reads_line_fields(self) -> None:
        with TemporaryDirectory() as temp_dir:
            home_dir = Path(temp_dir)
            config_dir = home_dir / "config"
            config_dir.mkdir()
            env_path = config_dir / ".env"
            env_path.write_text(
                "\n".join(
                    [
                        "LINE_CHANNEL_ACCESS_TOKEN=line-token",
                        "LINE_TARGET_USER_IDS=U123,U456",
                        "LINE_BOT_USER_ID=Ubottest",
                        "LINE_BOT_BASIC_ID=@botid",
                        "WARNING_REMAINING_M3=1.5",
                    ]
                ),
                encoding="utf-8",
            )

            settings = load_settings(Path(__file__), env_file=str(env_path), explicit_home=str(home_dir))

            self.assertEqual(settings.line_channel_access_token, "line-token")
            self.assertEqual(settings.line_target_user_ids, ("U123", "U456"))
            self.assertEqual(settings.line_bot_user_id, "Ubottest")
            self.assertEqual(settings.line_bot_basic_id, "@botid")
            self.assertEqual(settings.warning_remaining_m3, 1.5)


class DispatchNotificationsTests(unittest.TestCase):
    def test_dispatch_notifications_sends_line_push_to_every_target_user(self) -> None:
        settings = FamicleanSettings(
            home_dir=Path("/tmp/famiclean"),
            env_file=Path("/tmp/famiclean/config/.env"),
            state_file=Path("/tmp/famiclean/data/famiclean-state.json"),
            line_channel_access_token="line-token",
            line_target_user_ids=("U111", "U222"),
        )

        requests: list[dict[str, object]] = []

        def fake_urlopen(request, timeout=10):
            headers = {key.lower(): value for key, value in request.header_items()}
            requests.append(
                {
                    "url": request.full_url,
                    "body": json.loads(request.data.decode("utf-8")),
                    "headers": headers,
                    "timeout": timeout,
                }
            )
            return _FakeResponse('{"sentMessages":[{"id":"1"}]}')

        with mock.patch("tools.famiclean_notify.urlopen", side_effect=fake_urlopen):
            details = dispatch_notifications(settings, "subject ignored by LINE", "LINE push test")

        self.assertEqual(details["configured_channels"], ["line"])
        self.assertEqual(details["sent_channels"], ["line"])
        self.assertEqual(details["failed_channels"], [])
        self.assertTrue(details["success"])
        self.assertEqual(len(requests), 2)
        self.assertEqual([request["body"]["to"] for request in requests], ["U111", "U222"])
        self.assertTrue(all(request["url"] == "https://api.line.me/v2/bot/message/push" for request in requests))
        self.assertTrue(all(request["headers"]["authorization"] == "Bearer line-token" for request in requests))
        self.assertTrue(all(request["headers"]["content-type"] == "application/json; charset=utf-8" for request in requests))
        self.assertTrue(all(request["body"]["messages"] == [{"type": "text", "text": "LINE push test"}] for request in requests))


if __name__ == "__main__":
    unittest.main()
