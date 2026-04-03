from __future__ import annotations

from email.message import EmailMessage
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import smtplib

from .famiclean_env import FamicleanSettings


def _split_recipients(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def send_telegram(settings: FamicleanSettings, message: str) -> str:
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        raise ValueError("Telegram configuration is incomplete")

    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    body = urlencode({"chat_id": settings.telegram_chat_id, "text": message}).encode("utf-8")
    request = Request(url, data=body, method="POST")
    with urlopen(request, timeout=10) as response:
        payload = response.read().decode("utf-8", errors="replace")
    return payload


def send_email(settings: FamicleanSettings, subject: str, message: str) -> str:
    recipients = _split_recipients(settings.email_to)
    if not settings.email_smtp_host or not settings.email_from or not recipients:
        raise ValueError("Email configuration is incomplete")

    mail = EmailMessage()
    mail["Subject"] = subject
    mail["From"] = settings.email_from
    mail["To"] = ", ".join(recipients)
    mail.set_content(message)

    with smtplib.SMTP(settings.email_smtp_host, settings.email_smtp_port, timeout=10) as smtp:
        if settings.email_use_tls:
            smtp.starttls()
        if settings.email_smtp_username:
            smtp.login(settings.email_smtp_username, settings.email_smtp_password or "")
        smtp.send_message(mail)

    return "sent"


def dispatch_notifications(settings: FamicleanSettings, subject: str, message: str) -> dict[str, object]:
    configured_channels: list[str] = []
    sent_channels: list[str] = []
    failed_channels: list[dict[str, str]] = []

    if settings.telegram_bot_token and settings.telegram_chat_id:
        configured_channels.append("telegram")
        try:
            send_telegram(settings, message)
            sent_channels.append("telegram")
        except Exception as exc:
            failed_channels.append({"channel": "telegram", "error": str(exc)})

    if settings.email_smtp_host and settings.email_from and _split_recipients(settings.email_to):
        configured_channels.append("email")
        try:
            send_email(settings, subject, message)
            sent_channels.append("email")
        except Exception as exc:
            failed_channels.append({"channel": "email", "error": str(exc)})

    return {
        "configured_channels": configured_channels,
        "sent_channels": sent_channels,
        "failed_channels": failed_channels,
        "success": bool(configured_channels) and not failed_channels and len(sent_channels) == len(configured_channels),
    }
