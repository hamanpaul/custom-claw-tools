from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlencode
import html

from .adapter import (
    FamicleanAdapter,
    FamicleanAdapterError,
    FamicleanCommandError,
    FamicleanInvalidResponseError,
    FamicleanUnavailableError,
)
from .config import AppConfig, RuntimeConfigError
from .security import PasswordHashError, verify_password
from .store import AuthStateStore


SYNC_INTENT = "action.devices.SYNC"
QUERY_INTENT = "action.devices.QUERY"
EXECUTE_INTENT = "action.devices.EXECUTE"
DISCONNECT_INTENT = "action.devices.DISCONNECT"
SET_TEMPERATURE = "action.devices.commands.SetTemperature"
ON_OFF = "action.devices.commands.OnOff"


@dataclass(frozen=True)
class OAuthAuthorizeRequest:
    client_id: str
    redirect_uri: str
    state: str | None
    response_type: str


class FamiGhomeApp:
    def __init__(self, config: AppConfig, *, adapter: FamicleanAdapter, store: AuthStateStore):
        self.config = config
        self.adapter = adapter
        self.store = store

    def validate_runtime(self) -> None:
        missing: list[str] = []
        required_fields = {
            "ACCOUNT_LINKING_CLIENT_ID": self.config.account_linking_client_id,
            "ACCOUNT_LINKING_CLIENT_SECRET": self.config.account_linking_client_secret,
            "ACCOUNT_LINKING_ALLOWED_REDIRECT_URIS": ",".join(self.config.account_linking_allowed_redirect_uris),
            "AUTH_ADMIN_USERNAME": self.config.auth_admin_username,
            "AUTH_ADMIN_PASSWORD_HASH": self.config.auth_admin_password_hash,
            "SESSION_SECRET": self.config.session_secret,
            "TOKEN_ENCRYPTION_KEY": self.config.token_encryption_key,
        }
        if self.config.internal_api_enabled and not self.config.internal_api_token:
            missing.append("INTERNAL_API_TOKEN")
        missing.extend(name for name, value in required_fields.items() if not value)
        if missing:
            raise RuntimeConfigError(f"missing required config values: {', '.join(sorted(set(missing)))}")

    def authorize_request(self, params: dict[str, str]) -> OAuthAuthorizeRequest:
        response_type = params.get("response_type", "").strip()
        client_id = params.get("client_id", "").strip()
        redirect_uri = params.get("redirect_uri", "").strip()
        state = params.get("state", "").strip() or None
        if response_type != "code":
            raise RuntimeConfigError("oauth authorize only supports response_type=code")
        if client_id != self.config.account_linking_client_id:
            raise RuntimeConfigError("unknown client_id")
        if redirect_uri not in self.config.account_linking_allowed_redirect_uris:
            raise RuntimeConfigError("redirect_uri is not allowlisted")
        return OAuthAuthorizeRequest(
            client_id=client_id,
            redirect_uri=redirect_uri,
            state=state,
            response_type=response_type,
        )

    def login_admin(self, username: str, password: str) -> str:
        if username != self.config.auth_admin_username:
            raise RuntimeConfigError("invalid username or password")
        try:
            ok = verify_password(password, self.config.auth_admin_password_hash)
        except PasswordHashError as exc:
            raise RuntimeConfigError(str(exc)) from exc
        if not ok:
            raise RuntimeConfigError("invalid username or password")
        return self.store.create_session(username=username)

    def get_session(self, session_token: str | None) -> dict[str, object] | None:
        if not session_token:
            return None
        return self.store.get_session(session_token)

    def build_redirect_url(self, request: OAuthAuthorizeRequest, username: str) -> str:
        code = self.store.create_authorization_code(
            client_id=request.client_id,
            redirect_uri=request.redirect_uri,
            agent_user_id=self.config.agent_user_id,
            username=username,
            ttl_seconds=self.config.authorization_code_ttl_seconds,
        )
        payload = {"code": code}
        if request.state:
            payload["state"] = request.state
        return f"{request.redirect_uri}?{urlencode(payload)}"

    def exchange_authorization_code(self, *, client_id: str, client_secret: str, code: str, redirect_uri: str) -> dict[str, object]:
        self._validate_client_credentials(client_id=client_id, client_secret=client_secret)
        record = self.store.consume_authorization_code(code, client_id=client_id, redirect_uri=redirect_uri)
        if record is None:
            raise RuntimeConfigError("invalid authorization code")
        access_token = self.store.create_access_token(
            client_id=client_id,
            agent_user_id=str(record["agent_user_id"]),
            ttl_seconds=self.config.access_token_ttl_seconds,
        )
        refresh_token = self.store.create_refresh_token(
            client_id=client_id,
            agent_user_id=str(record["agent_user_id"]),
            ttl_days=self.config.refresh_token_ttl_days,
        )
        return {
            "token_type": "Bearer",
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_in": self.config.access_token_ttl_seconds,
        }

    def exchange_refresh_token(self, *, client_id: str, client_secret: str, refresh_token: str) -> dict[str, object]:
        self._validate_client_credentials(client_id=client_id, client_secret=client_secret)
        record = self.store.get_refresh_token(refresh_token)
        if record is None or record["client_id"] != client_id:
            raise RuntimeConfigError("invalid refresh token")
        access_token = self.store.create_access_token(
            client_id=client_id,
            agent_user_id=str(record["agent_user_id"]),
            ttl_seconds=self.config.access_token_ttl_seconds,
        )
        return {
            "token_type": "Bearer",
            "access_token": access_token,
            "expires_in": self.config.access_token_ttl_seconds,
        }

    def validate_access_token(self, access_token: str | None) -> dict[str, object]:
        if not access_token:
            raise RuntimeConfigError("missing bearer token")
        record = self.store.get_access_token(access_token)
        if record is None:
            raise RuntimeConfigError("invalid access token")
        return record

    def disconnect(self, agent_user_id: str) -> None:
        self.store.revoke_agent_user(agent_user_id)

    def read_snapshot(self) -> dict[str, object]:
        snapshot = self.adapter.read_snapshot()
        return {
            **snapshot.to_dict(),
            "google_state": self.google_query_state(device_id=self.config.local_home_device_id),
            "store_counts": self.store.snapshot(),
        }

    def google_sync_payload(self) -> dict[str, object]:
        device: dict[str, object] = {
            "id": self.config.local_home_device_id,
            "type": "action.devices.types.WATERHEATER",
            "traits": ["action.devices.traits.TemperatureControl"],
            "name": {
                "name": "Famiclean Water Heater",
                "nicknames": ["Famiclean 熱水器", "熱水器"],
            },
            "willReportState": False,
            "attributes": {
                "temperatureRange": {
                    "minThresholdCelsius": self.config.min_temp_celsius,
                    "maxThresholdCelsius": self.config.max_temp_celsius,
                },
                "temperatureStepCelsius": 1,
                "temperatureUnitForUX": "C",
                "commandOnlyTemperatureControl": False,
                "queryOnlyTemperatureControl": False,
            },
            "deviceInfo": {
                "manufacturer": "Famiclean",
                "model": "LAN Water Heater",
                "swVersion": "1",
            },
        }
        return {
            "agentUserId": self.config.agent_user_id,
            "devices": [device],
        }

    def google_query_state(self, *, device_id: str) -> dict[str, object]:
        if device_id != self.config.local_home_device_id:
            return {
                "status": "ERROR",
                "online": False,
                "errorCode": "deviceNotFound",
            }
        try:
            temp = self.adapter.read_temp()
        except FamicleanUnavailableError:
            return {"status": "ERROR", "online": False, "errorCode": "deviceOffline"}
        except FamicleanAdapterError:
            return {"status": "ERROR", "online": False, "errorCode": "hardError"}

        return {
            "status": "SUCCESS",
            "online": True,
            "temperatureSetpointCelsius": int(temp["settemp"]),
        }

    def google_execute(self, payload: dict[str, object]) -> dict[str, object]:
        commands_out: list[dict[str, object]] = []
        for command in payload.get("commands", []):
            devices = command.get("devices") or []
            executions = command.get("execution") or []
            ids = [str(device.get("id", "")) for device in devices if device.get("id")]
            if not ids:
                commands_out.append({"ids": [], "status": "ERROR", "errorCode": "deviceNotFound"})
                continue

            for execution in executions:
                google_command = str(execution.get("command", ""))
                params = execution.get("params") or {}
                if google_command == SET_TEMPERATURE:
                    target = int(float(params.get("temperature", 0)))
                    if target < self.config.min_temp_celsius or target > self.config.max_temp_celsius:
                        commands_out.append({"ids": ids, "status": "ERROR", "errorCode": "valueOutOfRange"})
                        continue
                    try:
                        result = self.adapter.set_temp(target)
                    except FamicleanUnavailableError:
                        commands_out.append({"ids": ids, "status": "ERROR", "errorCode": "deviceOffline"})
                        continue
                    except FamicleanCommandError as exc:
                        error_code = "valueOutOfRange" if "exceeds max" in str(exc) else "hardError"
                        commands_out.append({"ids": ids, "status": "ERROR", "errorCode": error_code})
                        continue
                    except FamicleanInvalidResponseError:
                        commands_out.append({"ids": ids, "status": "ERROR", "errorCode": "hardError"})
                        continue
                    commands_out.append(
                        {
                            "ids": ids,
                            "status": "SUCCESS",
                            "states": {
                                "online": True,
                                "temperatureSetpointCelsius": int(result["confirmed_temp"]),
                            },
                        }
                    )
                    continue

                if google_command == ON_OFF:
                    commands_out.append({"ids": ids, "status": "ERROR", "errorCode": "functionNotSupported"})
                    continue

                commands_out.append({"ids": ids, "status": "ERROR", "errorCode": "functionNotSupported"})
        return {"commands": commands_out}

    def handle_fulfillment(self, payload: dict[str, object], *, access_token: str | None) -> dict[str, object]:
        self.validate_access_token(access_token)
        request_id = payload.get("requestId") or ""
        inputs = payload.get("inputs") or []
        if not inputs:
            raise RuntimeConfigError("fulfillment payload has no inputs")
        intent = str(inputs[0].get("intent", ""))

        if intent == SYNC_INTENT:
            return {"requestId": request_id, "payload": self.google_sync_payload()}

        if intent == QUERY_INTENT:
            devices = inputs[0].get("payload", {}).get("devices", [])
            result = {
                str(device.get("id", "")): self.google_query_state(device_id=str(device.get("id", "")))
                for device in devices
            }
            return {"requestId": request_id, "payload": {"devices": result}}

        if intent == EXECUTE_INTENT:
            execute_payload = inputs[0].get("payload") or {}
            return {"requestId": request_id, "payload": self.google_execute(execute_payload)}

        if intent == DISCONNECT_INTENT:
            self.disconnect(self.config.agent_user_id)
            return {"requestId": request_id, "payload": {}}

        raise RuntimeConfigError(f"unsupported smart home intent: {intent}")

    def render_authorize_html(
        self,
        request: OAuthAuthorizeRequest,
        *,
        error: str | None = None,
    ) -> str:
        error_markup = ""
        if error:
            error_markup = (
                '<p style="padding: 0.75rem; background: #fee2e2; color: #991b1b; border-radius: 0.5rem;">'
                f"{html.escape(error)}</p>"
            )
        hidden_inputs = "\n".join(
            [
                f'<input type="hidden" name="response_type" value="{html.escape(request.response_type)}">',
                f'<input type="hidden" name="client_id" value="{html.escape(request.client_id)}">',
                f'<input type="hidden" name="redirect_uri" value="{html.escape(request.redirect_uri)}">',
                f'<input type="hidden" name="state" value="{html.escape(request.state or "")}">',
            ]
        )
        return f"""<!doctype html>
<html lang="zh-Hant">
  <head>
    <meta charset="utf-8">
    <title>fami-ghome account linking</title>
  </head>
  <body style="font-family: sans-serif; max-width: 32rem; margin: 3rem auto; padding: 0 1rem;">
    <h1>fami-ghome account linking</h1>
    <p>使用本地管理帳號登入，讓 Google Home 取得 `Famiclean Water Heater` 的控制權。</p>
    {error_markup}
    <form method="post" action="/oauth/authorize" style="display: grid; gap: 0.75rem;">
      {hidden_inputs}
      <label>Username <input type="text" name="username" autocomplete="username" required></label>
      <label>Password <input type="password" name="password" autocomplete="current-password" required></label>
      <button type="submit">Sign in and continue</button>
    </form>
  </body>
</html>
"""

    def _validate_client_credentials(self, *, client_id: str, client_secret: str) -> None:
        if client_id != self.config.account_linking_client_id:
            raise RuntimeConfigError("invalid client_id")
        if client_secret != self.config.account_linking_client_secret:
            raise RuntimeConfigError("invalid client_secret")
