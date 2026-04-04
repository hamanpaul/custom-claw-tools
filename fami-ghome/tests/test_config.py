from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fami_ghome.config import load_config


class ConfigLoadTest(unittest.TestCase):
    def test_load_config_supports_device_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "config").mkdir()
            (root / "docs").mkdir()
            (root / "config" / ".env").write_text(
                "\n".join(
                    [
                        "FAMICLEAN_HOME=../famiclean-skill",
                        "FAMICLEAN_WRAPPER=../famiclean-skill/skills/fami-claw-skill/fami-claw",
                        "STATE_DIR=data",
                        "LOG_DIR=logs",
                        "DEVICE_IP=192.168.1.50",
                        "DEVICE_MAC=AABBCCDDEEFF",
                        "BROADCAST_IP=192.168.1.255",
                        "FAMICLEAN_PORT=9999",
                        "FAMICLEAN_TIMEOUT_SECONDS=1.5",
                        "ACCOUNT_LINKING_ALLOWED_REDIRECT_URIS=https://redirect.example/callback",
                        "SESSION_SECRET=session-secret-session-secret-123456",
                        "TOKEN_ENCRYPTION_KEY=token-secret-token-secret-123456",
                        "AUTH_ADMIN_USERNAME=admin",
                        "AUTH_ADMIN_PASSWORD_HASH=scrypt$16384$8$1$c2FsdA$ZGlnaWVzdA",
                        "ACCOUNT_LINKING_CLIENT_ID=client-id",
                        "ACCOUNT_LINKING_CLIENT_SECRET=client-secret",
                    ]
                ),
                encoding="utf-8",
            )
            script_path = root / "fami_ghome" / "cli.py"
            script_path.parent.mkdir()
            script_path.write_text("", encoding="utf-8")

            config = load_config(script_path, explicit_root=str(root))

            self.assertEqual(config.device_overrides.device_ip, "192.168.1.50")
            self.assertEqual(config.device_overrides.device_mac, "AABBCCDDEEFF")
            self.assertEqual(config.device_overrides.broadcast_ip, "192.168.1.255")
            self.assertEqual(config.device_overrides.port, 9999)
            self.assertEqual(config.device_overrides.timeout_seconds, 1.5)
            self.assertEqual(config.account_linking_allowed_redirect_uris, ("https://redirect.example/callback",))


if __name__ == "__main__":
    unittest.main()
