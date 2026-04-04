from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock
from typing import Any, Callable
import json
import os

from .security import expires_in, expires_in_days, new_opaque_token, parse_utc, token_digest, utc_iso, utcnow


DEFAULT_STATE = {
    "sessions": {},
    "authorization_codes": {},
    "access_tokens": {},
    "refresh_tokens": {},
}


class AuthStateStore:
    def __init__(self, *, path: Path, session_secret: str, token_secret: str):
        self.path = path
        self.session_secret = session_secret
        self.token_secret = token_secret
        self._lock = Lock()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return json.loads(json.dumps(DEFAULT_STATE))
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        for key, default in DEFAULT_STATE.items():
            payload.setdefault(key, default.copy())
        return payload

    def _save(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=self.path.parent) as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            temp_name = handle.name
        os.replace(temp_name, self.path)

    def _purge_expired(self, payload: dict[str, Any]) -> None:
        now = utcnow()
        for bucket_name in ("sessions", "authorization_codes", "access_tokens", "refresh_tokens"):
            bucket = payload.get(bucket_name, {})
            expired = [
                key
                for key, record in bucket.items()
                if parse_utc(record["expires_at"]) <= now
            ]
            for key in expired:
                bucket.pop(key, None)

    def _mutate(self, callback: Callable[[dict[str, Any]], Any]) -> Any:
        with self._lock:
            payload = self._load()
            self._purge_expired(payload)
            result = callback(payload)
            self._save(payload)
            return result

    def create_session(self, username: str, *, ttl_seconds: int = 24 * 3600) -> str:
        token = new_opaque_token()
        digest = token_digest(self.session_secret, token)

        def callback(payload: dict[str, Any]) -> str:
            payload["sessions"][digest] = {
                "username": username,
                "created_at": utc_iso(),
                "expires_at": expires_in(ttl_seconds),
            }
            return token

        return self._mutate(callback)

    def get_session(self, token: str) -> dict[str, Any] | None:
        digest = token_digest(self.session_secret, token)

        def callback(payload: dict[str, Any]) -> dict[str, Any] | None:
            return payload["sessions"].get(digest)

        return self._mutate(callback)

    def create_authorization_code(
        self,
        *,
        client_id: str,
        redirect_uri: str,
        agent_user_id: str,
        username: str,
        ttl_seconds: int,
    ) -> str:
        token = new_opaque_token()
        digest = token_digest(self.token_secret, token)

        def callback(payload: dict[str, Any]) -> str:
            payload["authorization_codes"][digest] = {
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "agent_user_id": agent_user_id,
                "username": username,
                "created_at": utc_iso(),
                "expires_at": expires_in(ttl_seconds),
            }
            return token

        return self._mutate(callback)

    def consume_authorization_code(self, code: str, *, client_id: str, redirect_uri: str) -> dict[str, Any] | None:
        digest = token_digest(self.token_secret, code)

        def callback(payload: dict[str, Any]) -> dict[str, Any] | None:
            record = payload["authorization_codes"].pop(digest, None)
            if record is None:
                return None
            if record["client_id"] != client_id or record["redirect_uri"] != redirect_uri:
                return None
            return record

        return self._mutate(callback)

    def create_access_token(self, *, client_id: str, agent_user_id: str, ttl_seconds: int) -> str:
        token = new_opaque_token()
        digest = token_digest(self.token_secret, token)

        def callback(payload: dict[str, Any]) -> str:
            payload["access_tokens"][digest] = {
                "client_id": client_id,
                "agent_user_id": agent_user_id,
                "created_at": utc_iso(),
                "expires_at": expires_in(ttl_seconds),
            }
            return token

        return self._mutate(callback)

    def create_refresh_token(self, *, client_id: str, agent_user_id: str, ttl_days: int) -> str:
        token = new_opaque_token()
        digest = token_digest(self.token_secret, token)

        def callback(payload: dict[str, Any]) -> str:
            payload["refresh_tokens"][digest] = {
                "client_id": client_id,
                "agent_user_id": agent_user_id,
                "created_at": utc_iso(),
                "expires_at": expires_in_days(ttl_days),
            }
            return token

        return self._mutate(callback)

    def get_access_token(self, token: str) -> dict[str, Any] | None:
        digest = token_digest(self.token_secret, token)

        def callback(payload: dict[str, Any]) -> dict[str, Any] | None:
            return payload["access_tokens"].get(digest)

        return self._mutate(callback)

    def get_refresh_token(self, token: str) -> dict[str, Any] | None:
        digest = token_digest(self.token_secret, token)

        def callback(payload: dict[str, Any]) -> dict[str, Any] | None:
            return payload["refresh_tokens"].get(digest)

        return self._mutate(callback)

    def revoke_agent_user(self, agent_user_id: str) -> None:
        def callback(payload: dict[str, Any]) -> None:
            for bucket_name in ("access_tokens", "refresh_tokens", "authorization_codes"):
                bucket = payload[bucket_name]
                doomed = [key for key, record in bucket.items() if record.get("agent_user_id") == agent_user_id]
                for key in doomed:
                    bucket.pop(key, None)

        self._mutate(callback)

    def snapshot(self) -> dict[str, Any]:
        def callback(payload: dict[str, Any]) -> dict[str, Any]:
            return {
                "sessions": len(payload["sessions"]),
                "authorization_codes": len(payload["authorization_codes"]),
                "access_tokens": len(payload["access_tokens"]),
                "refresh_tokens": len(payload["refresh_tokens"]),
            }

        return self._mutate(callback)
