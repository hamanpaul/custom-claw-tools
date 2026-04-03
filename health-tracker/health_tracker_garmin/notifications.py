"""Notification helpers for health-tracker report updates."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import RuntimeConfig, TelegramNotificationConfig


class NotificationError(Exception):
    """Raised when report notification cannot be delivered."""


@dataclass(frozen=True)
class ResolvedTelegramTarget:
    """Resolved Telegram delivery settings."""

    api_base_url: str
    bot_token: str
    chat_id: str


def notify_report_update(runtime: RuntimeConfig, message: str) -> bool:
    """Send a report update notification when Telegram delivery is configured."""

    telegram = runtime.notifications.telegram
    if telegram is None or not telegram.enabled:
        return False

    resolved = _resolve_telegram_target(telegram)
    _send_telegram_message(resolved, message)
    return True


def _read_json_file(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise NotificationError(f"{label} does not exist: {path}") from exc
    except json.JSONDecodeError as exc:
        raise NotificationError(f"{label} is not valid JSON: {path}: {exc}") from exc

    if not isinstance(value, dict):
        raise NotificationError(f"{label} must be a JSON object: {path}")
    return value


def _normalize_chat_id(raw_value: str | None) -> str | None:
    if raw_value is None:
        return None
    value = raw_value.strip()
    if not value:
        return None
    if value.startswith("telegram:"):
        value = value.split(":", 1)[1].strip()
    if "|" in value:
        value = value.split("|", 1)[0].strip()
    return value or None


def _normalize_allow_from(entries: list[Any]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        if isinstance(entry, int):
            chat_id = str(entry)
        elif isinstance(entry, str):
            chat_id = _normalize_chat_id(entry)
        else:
            continue
        if chat_id and chat_id not in seen:
            seen.add(chat_id)
            normalized.append(chat_id)
    return normalized


def _load_picoclaw_telegram_config(path: Path) -> dict[str, Any]:
    payload = _read_json_file(path, "PicoClaw config")
    channels = payload.get("channels")
    if not isinstance(channels, dict):
        return {}
    telegram = channels.get("telegram")
    if not isinstance(telegram, dict):
        return {}
    return telegram


def _resolve_bot_token(config: TelegramNotificationConfig, picoclaw_config: dict[str, Any]) -> str | None:
    if config.bot_token_file is not None:
        try:
            token = config.bot_token_file.read_text(encoding="utf-8").strip()
        except FileNotFoundError as exc:
            raise NotificationError(
                "notifications.telegram.bot_token_file does not exist: "
                f"{config.bot_token_file}"
            ) from exc
        if not token:
            raise NotificationError(
                "notifications.telegram.bot_token_file is empty: "
                f"{config.bot_token_file}"
            )
        return token

    if config.bot_token_env is not None:
        token = os.environ.get(config.bot_token_env, "").strip()
        if not token:
            raise NotificationError(
                "notifications.telegram.bot_token_env is set but the environment variable "
                f"{config.bot_token_env} is empty."
            )
        return token

    if config.fallback_to_picoclaw_config:
        for key in ("bot_token", "token"):
            value = picoclaw_config.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

    return None


def _resolve_chat_id(config: TelegramNotificationConfig, picoclaw_config: dict[str, Any]) -> str | None:
    explicit = _normalize_chat_id(config.chat_id)
    if explicit:
        return explicit

    if config.fallback_to_picoclaw_config:
        for key in ("chat_id", "default_chat_id", "notify_chat_id"):
            value = picoclaw_config.get(key)
            if isinstance(value, str):
                normalized = _normalize_chat_id(value)
                if normalized:
                    return normalized
            elif isinstance(value, int):
                return str(value)

        allow_from = picoclaw_config.get("allow_from")
        if isinstance(allow_from, list):
            candidates = _normalize_allow_from(allow_from)
            if len(candidates) == 1:
                return candidates[0]

    return None


def _resolve_telegram_target(config: TelegramNotificationConfig) -> ResolvedTelegramTarget:
    picoclaw_config: dict[str, Any] = {}
    if config.fallback_to_picoclaw_config and config.picoclaw_config_path.exists():
        picoclaw_config = _load_picoclaw_telegram_config(config.picoclaw_config_path)

    bot_token = _resolve_bot_token(config, picoclaw_config)
    if bot_token is None:
        raise NotificationError(
            "Telegram notification is enabled but no bot token was found. Configure "
            "notifications.telegram.bot_token_file, notifications.telegram.bot_token_env, "
            "or a supported token field in ~/.picoclaw/config.json."
        )

    chat_id = _resolve_chat_id(config, picoclaw_config)
    if chat_id is None:
        raise NotificationError(
            "Telegram notification is enabled but no chat_id could be resolved. Configure "
            "notifications.telegram.chat_id or ensure ~/.picoclaw/config.json has a single "
            "allow_from target for the Telegram channel."
        )

    return ResolvedTelegramTarget(
        api_base_url=config.api_base_url,
        bot_token=bot_token,
        chat_id=chat_id,
    )


def _send_telegram_message(target: ResolvedTelegramTarget, message: str) -> None:
    trimmed = message.strip()
    if not trimmed:
        raise NotificationError("Refusing to send an empty Telegram message.")

    if len(trimmed) > 4000:
        trimmed = trimmed[:3999].rstrip() + "…"

    request = Request(
        url=f"{target.api_base_url}/bot{target.bot_token}/sendMessage",
        data=json.dumps(
            {
                "chat_id": target.chat_id,
                "text": trimmed,
                "disable_web_page_preview": True,
            }
        ).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise NotificationError(f"Telegram sendMessage failed with HTTP {exc.code}.") from exc
    except URLError as exc:
        raise NotificationError(f"Telegram sendMessage failed: {exc.reason}") from exc

    if not isinstance(payload, dict) or payload.get("ok") is not True:
        raise NotificationError(f"Telegram sendMessage rejected the request: {payload}")
