from __future__ import annotations

import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

from fami_ghome.adapter import FamicleanAdapter
from fami_ghome.app import FamiGhomeApp
from fami_ghome.config import AppConfig, DeviceOverrides, ensure_runtime_dirs
from fami_ghome.security import make_password_hash
from fami_ghome.server import create_server
from fami_ghome.store import AuthStateStore


class FakeAdapter(FamicleanAdapter):
    def __init__(self, config: AppConfig):
        super().__init__(config)
        self.last_set_temp: int | None = None

    def read_temp(self) -> dict[str, object]:
        return {
            "device": {"ip": "192.168.1.50", "mac": "AABBCCDDEEFF"},
            "settemp": 42,
        }

    def read_gas(self) -> dict[str, object]:
        return {
            "device": {"ip": "192.168.1.50", "mac": "AABBCCDDEEFF"},
            "gas_total_m3": 12.34,
            "remaining_to_next_threshold_m3": 7.66,
        }

    def set_temp(self, target_celsius: int) -> dict[str, object]:
        self.last_set_temp = target_celsius
        return {
            "device": {"ip": "192.168.1.50", "mac": "AABBCCDDEEFF"},
            "previous_temp": 42,
            "confirmed_temp": target_celsius,
        }

    def read_snapshot(self):  # noqa: D401
        class Snapshot:
            def to_dict(self_nonlocal) -> dict[str, object]:
                return {
                    "device": {"ip": "192.168.1.50", "mac": "AABBCCDDEEFF"},
                    "gas": self.read_gas(),
                    "temp": self.read_temp(),
                    "checked_at": "2026-04-04T00:00:00+00:00",
                }

        return Snapshot()


class HttpIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        ensure_runtime_dirs(
            AppConfig(
                project_root=root,
                env_file=root / "config/.env",
                state_dir=root / "data",
                log_dir=root / "logs",
                famiclean_home=root / "../famiclean-skill",
                famiclean_wrapper=root / "../famiclean-skill/skills/fami-claw-skill/fami-claw",
                famiclean_env_file=None,
                host="127.0.0.1",
                port=0,
                public_base_url="http://127.0.0.1",
                timezone="Asia/Taipei",
                log_level="INFO",
                min_temp_celsius=35,
                max_temp_celsius=50,
                google_cloud_project_id="project-id",
                google_home_project_id="home-project-id",
                google_home_fulfillment_url="https://example.com/fulfillment",
                google_home_local_app_id="",
                agent_user_id="single-home",
                account_linking_client_id="client-id",
                account_linking_client_secret="client-secret",
                account_linking_allowed_redirect_uris=("https://redirect.example/callback",),
                auth_admin_username="admin",
                auth_admin_password_hash=make_password_hash("admin-password"),
                session_secret="session-secret-session-secret-123456",
                token_encryption_key="token-secret-token-secret-123456",
                authorization_code_ttl_seconds=300,
                access_token_ttl_seconds=3600,
                refresh_token_ttl_days=180,
                local_home_enabled=False,
                local_home_device_id="famiclean-water-heater-1",
                local_home_scan_port=3311,
                local_home_listen_host="0.0.0.0",
                local_home_listen_port=3322,
                google_service_account_file=None,
                internal_api_enabled=True,
                internal_api_token="internal-secret",
                device_overrides=DeviceOverrides(),
            )
        )
        self.config = AppConfig(
            project_root=root,
            env_file=root / "config/.env",
            state_dir=root / "data",
            log_dir=root / "logs",
            famiclean_home=root / "../famiclean-skill",
            famiclean_wrapper=root / "../famiclean-skill/skills/fami-claw-skill/fami-claw",
            famiclean_env_file=None,
            host="127.0.0.1",
            port=0,
            public_base_url="http://127.0.0.1",
            timezone="Asia/Taipei",
            log_level="INFO",
            min_temp_celsius=35,
            max_temp_celsius=50,
            google_cloud_project_id="project-id",
            google_home_project_id="home-project-id",
            google_home_fulfillment_url="https://example.com/fulfillment",
            google_home_local_app_id="",
            agent_user_id="single-home",
            account_linking_client_id="client-id",
            account_linking_client_secret="client-secret",
            account_linking_allowed_redirect_uris=("https://redirect.example/callback",),
            auth_admin_username="admin",
            auth_admin_password_hash=make_password_hash("admin-password"),
            session_secret="session-secret-session-secret-123456",
            token_encryption_key="token-secret-token-secret-123456",
            authorization_code_ttl_seconds=300,
            access_token_ttl_seconds=3600,
            refresh_token_ttl_days=180,
            local_home_enabled=False,
            local_home_device_id="famiclean-water-heater-1",
            local_home_scan_port=3311,
            local_home_listen_host="0.0.0.0",
            local_home_listen_port=3322,
            google_service_account_file=None,
            internal_api_enabled=True,
            internal_api_token="internal-secret",
            device_overrides=DeviceOverrides(),
        )
        self.adapter = FakeAdapter(self.config)
        self.store = AuthStateStore(
            path=self.config.state_dir / "oauth-state.json",
            session_secret=self.config.session_secret,
            token_secret=self.config.token_encryption_key,
        )
        self.app = FamiGhomeApp(self.config, adapter=self.adapter, store=self.store)
        self.app.validate_runtime()
        self.server = create_server(self.app, host="127.0.0.1", port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temp_dir.cleanup()

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        final_headers = dict(headers or {})
        payload = body.encode("utf-8") if body is not None else None
        if payload is not None:
            final_headers.setdefault("content-length", str(len(payload)))
        conn.request(method, path, body=payload, headers=final_headers)
        response = conn.getresponse()
        response_headers = {key.lower(): value for key, value in response.getheaders()}
        data = response.read()
        conn.close()
        return response.status, response_headers, data

    def test_authorization_token_query_execute_and_internal_state(self) -> None:
        query = urlencode(
            {
                "response_type": "code",
                "client_id": "client-id",
                "redirect_uri": "https://redirect.example/callback",
                "state": "opaque-state",
            }
        )
        status, _headers, body = self._request("GET", f"/oauth/authorize?{query}")
        self.assertEqual(status, 200)
        self.assertIn("Sign in and continue", body.decode("utf-8"))

        status, headers, _body = self._request(
            "POST",
            "/oauth/authorize",
            body=urlencode(
                {
                    "response_type": "code",
                    "client_id": "client-id",
                    "redirect_uri": "https://redirect.example/callback",
                    "state": "opaque-state",
                    "username": "admin",
                    "password": "admin-password",
                }
            ),
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
        self.assertEqual(status, 302)
        parsed_redirect = urlparse(headers["location"])
        redirect_params = parse_qs(parsed_redirect.query)
        code = redirect_params["code"][0]
        self.assertEqual(redirect_params["state"][0], "opaque-state")

        status, _headers, body = self._request(
            "POST",
            "/oauth/token",
            body=urlencode(
                {
                    "grant_type": "authorization_code",
                    "client_id": "client-id",
                    "client_secret": "client-secret",
                    "code": code,
                    "redirect_uri": "https://redirect.example/callback",
                }
            ),
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
        self.assertEqual(status, 200)
        token_payload = json.loads(body.decode("utf-8"))
        access_token = token_payload["access_token"]

        status, _headers, body = self._request(
            "POST",
            "/fulfillment",
            body=json.dumps(
                {
                    "requestId": "sync-1",
                    "inputs": [{"intent": "action.devices.SYNC"}],
                }
            ),
            headers={
                "content-type": "application/json",
                "authorization": f"Bearer {access_token}",
            },
        )
        self.assertEqual(status, 200)
        sync_payload = json.loads(body.decode("utf-8"))
        self.assertEqual(sync_payload["payload"]["devices"][0]["id"], "famiclean-water-heater-1")

        status, _headers, body = self._request(
            "POST",
            "/fulfillment",
            body=json.dumps(
                {
                    "requestId": "query-1",
                    "inputs": [
                        {
                            "intent": "action.devices.QUERY",
                            "payload": {"devices": [{"id": "famiclean-water-heater-1"}]},
                        }
                    ],
                }
            ),
            headers={
                "content-type": "application/json",
                "authorization": f"Bearer {access_token}",
            },
        )
        self.assertEqual(status, 200)
        query_payload = json.loads(body.decode("utf-8"))
        self.assertEqual(
            query_payload["payload"]["devices"]["famiclean-water-heater-1"]["temperatureSetpointCelsius"],
            42,
        )

        status, _headers, body = self._request(
            "POST",
            "/fulfillment",
            body=json.dumps(
                {
                    "requestId": "execute-1",
                    "inputs": [
                        {
                            "intent": "action.devices.EXECUTE",
                            "payload": {
                                "commands": [
                                    {
                                        "devices": [{"id": "famiclean-water-heater-1"}],
                                        "execution": [
                                            {
                                                "command": "action.devices.commands.SetTemperature",
                                                "params": {"temperature": 45},
                                            }
                                        ],
                                    }
                                ]
                            },
                        }
                    ],
                }
            ),
            headers={
                "content-type": "application/json",
                "authorization": f"Bearer {access_token}",
            },
        )
        self.assertEqual(status, 200)
        execute_payload = json.loads(body.decode("utf-8"))
        self.assertEqual(execute_payload["payload"]["commands"][0]["status"], "SUCCESS")
        self.assertEqual(self.adapter.last_set_temp, 45)

        status, _headers, body = self._request(
            "GET",
            "/internal/state",
            headers={"x-internal-api-token": "internal-secret"},
        )
        self.assertEqual(status, 200)
        internal_payload = json.loads(body.decode("utf-8"))
        self.assertEqual(internal_payload["temp"]["settemp"], 42)
        self.assertEqual(internal_payload["gas"]["gas_total_m3"], 12.34)

    def test_execute_rejects_out_of_range_temperature(self) -> None:
        access_token = self.store.create_access_token(
            client_id="client-id",
            agent_user_id="single-home",
            ttl_seconds=3600,
        )
        status, _headers, body = self._request(
            "POST",
            "/fulfillment",
            body=json.dumps(
                {
                    "requestId": "execute-2",
                    "inputs": [
                        {
                            "intent": "action.devices.EXECUTE",
                            "payload": {
                                "commands": [
                                    {
                                        "devices": [{"id": "famiclean-water-heater-1"}],
                                        "execution": [
                                            {
                                                "command": "action.devices.commands.SetTemperature",
                                                "params": {"temperature": 80},
                                            }
                                        ],
                                    }
                                ]
                            },
                        }
                    ],
                }
            ),
            headers={
                "content-type": "application/json",
                "authorization": f"Bearer {access_token}",
            },
        )
        self.assertEqual(status, 200)
        payload = json.loads(body.decode("utf-8"))
        self.assertEqual(payload["payload"]["commands"][0]["errorCode"], "valueOutOfRange")


if __name__ == "__main__":
    unittest.main()
