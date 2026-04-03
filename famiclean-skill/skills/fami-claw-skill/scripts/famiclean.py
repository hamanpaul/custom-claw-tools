#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import json
import sys


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from tools.famiclean_client import FamicleanError, FamicleanSession
from tools.famiclean_env import apply_overrides, load_settings
from tools.famiclean_notify import dispatch_notifications
from tools.famiclean_state import load_state, now_iso, save_state, threshold_floor, thresholds_crossed


def json_print(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def text_print_discover(result: list[dict[str, object]]) -> None:
    for item in result:
        print(f"{item['ip']}  mac={item['mac']}  control={item.get('control')}")


def text_print_total_gas(result: dict[str, object]) -> None:
    print(f"總瓦斯用量: {result['gas_total_m3']:.2f} M3")
    print(f"Raw heatvalue_total(累積): {result['raw_heatvalue_total']}")
    print(f"Raw heatvalue_count(即時): {result['raw_heatvalue_count']}")
    print(f"Raw effective heatvalue_total: {result['raw_effective_heatvalue_total']}")
    print(f"本次瓦斯用量: {result['gas_count_m3']:.2f} M3")
    print(f"下個門檻: {result['next_threshold_m3']} M3")
    print(f"剩餘瓦斯量: {result['remaining_to_next_threshold_m3']:.2f} M3")
    print(f"設備: {result['device']['ip']} / {result['device']['mac']}")


def text_print_temp(result: dict[str, object]) -> None:
    print(f"目前設定溫度: {result['settemp']}°C")
    print(f"設備: {result['device']['ip']} / {result['device']['mac']}")


def text_print_set_temp(result: dict[str, object]) -> None:
    print(f"設定完成: {result['previous_temp']}°C -> {result['confirmed_temp']}°C")
    print(f"設備: {result['device']['ip']} / {result['device']['mac']}")


def build_threshold_message(result: dict[str, object]) -> tuple[str, str]:
    crossed = result.get("crossed_thresholds_m3", [])
    crossed_text = ", ".join(f"{item} M3" for item in crossed) if crossed else "無"
    subject = "Famiclean 瓦斯用量通知"
    message = "\n".join(
        [
            "瓦斯用量已達臨界值",
            f"目前總瓦斯用量: {result['gas_total_m3']:.2f} M3",
            f"目前整數門檻: {result['current_threshold_m3']} M3",
            f"本次跨越門檻: {crossed_text}",
            f"設備: {result['device']['ip']} / {result['device']['mac']}",
            f"檢查時間: {result['checked_at']}",
        ]
    )
    return subject, message


def run_check_threshold(settings, *, device_ip: str | None, device_mac: str | None, send_notifications: bool, force_notify: bool) -> dict[str, object]:
    with FamicleanSession(settings) as session:
        reading = session.get_total_gas(device_ip=device_ip, device_mac=device_mac)

    state = load_state(settings.state_file)
    checked_at = now_iso(settings.timezone)
    current_threshold = threshold_floor(reading["gas_total_m3"], settings.threshold_step_m3)
    last_notified = state.get("last_notified_threshold_m3")
    last_notified = int(last_notified) if last_notified is not None else None

    result = {
        **reading,
        "checked_at": checked_at,
        "threshold_step_m3": settings.threshold_step_m3,
        "current_threshold_m3": current_threshold,
        "last_notified_threshold_m3": last_notified,
        "crossed_thresholds_m3": [],
        "notification": {
            "attempted": False,
            "success": False,
            "reason": None,
            "details": None,
        },
        "state_file": str(settings.state_file),
    }

    state["last_checked_at"] = checked_at
    state["last_seen_total_m3"] = reading["gas_total_m3"]
    state["last_seen_raw_heatvalue_total"] = reading["raw_heatvalue_total"]

    if force_notify:
        result["crossed_thresholds_m3"] = [current_threshold] if current_threshold > 0 else []
    elif last_notified is None:
        state["bootstrapped_at"] = checked_at
        state["last_notified_threshold_m3"] = current_threshold
        save_state(settings.state_file, state)
        result["last_notified_threshold_m3"] = current_threshold
        result["notification"]["reason"] = "bootstrapped_without_alert"
        return result
    else:
        result["crossed_thresholds_m3"] = thresholds_crossed(last_notified, reading["gas_total_m3"], settings.threshold_step_m3)

    if not result["crossed_thresholds_m3"]:
        save_state(settings.state_file, state)
        result["notification"]["reason"] = "no_new_threshold"
        return result

    if not send_notifications:
        result["notification"]["reason"] = "notification_suppressed"
        save_state(settings.state_file, state)
        return result

    subject, message = build_threshold_message(result)
    details = dispatch_notifications(settings, subject, message)
    result["notification"]["attempted"] = True
    result["notification"]["details"] = details
    result["notification"]["success"] = bool(details["success"])

    if details["success"]:
        highest_threshold = result["crossed_thresholds_m3"][-1]
        state["last_notified_threshold_m3"] = highest_threshold
        state["last_notified_at"] = checked_at
        state["last_notification_subject"] = subject
        save_state(settings.state_file, state)
        result["last_notified_threshold_m3"] = highest_threshold
        result["notification"]["reason"] = "sent"
    else:
        result["notification"]["reason"] = "notification_failed"
        save_state(settings.state_file, state)

    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Famiclean Orangepi3 / Picoclaw CLI")
    parser.add_argument("--home", help="Override FAMICLEAN_HOME")
    parser.add_argument("--env-file", help="Path to config/.env")
    parser.add_argument("--device-ip", help="Override device IP")
    parser.add_argument("--device-mac", help="Override device MAC")
    parser.add_argument("--broadcast-ip", help="Override broadcast IP")
    parser.add_argument("--port", type=int, help="Override UDP port")
    parser.add_argument("--timeout", type=float, help="Override request timeout in seconds")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("discover", help="Discover Famiclean devices")
    subparsers.add_parser("get-total-gas", help="Read total gas usage")
    subparsers.add_parser("get-temp", help="Read current target temperature")

    set_temp = subparsers.add_parser("set-temp", help="Set target temperature")
    set_temp.add_argument("temperature", type=int)

    check_threshold = subparsers.add_parser("check-threshold", help="Run the 08:00 threshold workflow")
    check_threshold.add_argument("--no-notify", action="store_true", help="Do not send Telegram or Email")
    check_threshold.add_argument("--force-notify", action="store_true", help="Send a notification even without a newly crossed threshold")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    settings = load_settings(Path(__file__), env_file=args.env_file, explicit_home=args.home)
    settings = apply_overrides(
        settings,
        device_ip=args.device_ip,
        device_mac=args.device_mac,
        broadcast_ip=args.broadcast_ip,
        port=args.port,
        timeout_seconds=args.timeout,
    )

    try:
        if args.command == "discover":
            with FamicleanSession(settings) as session:
                records = session.discover(target_ip=args.device_ip, target_mac=args.device_mac)
            payload = [
                {
                    "ip": record.ip,
                    "port": record.port,
                    "mac": record.mac,
                    "control": record.control,
                    "payload": record.payload,
                }
                for record in records
            ]
            if args.json:
                json_print({"devices": payload})
            else:
                text_print_discover(payload)
            return 0

        if args.command == "get-total-gas":
            with FamicleanSession(settings) as session:
                result = session.get_total_gas(device_ip=settings.device_ip, device_mac=settings.device_mac)
            if args.json:
                json_print(result)
            else:
                text_print_total_gas(result)
            return 0

        if args.command == "get-temp":
            with FamicleanSession(settings) as session:
                result = session.get_temp(device_ip=settings.device_ip, device_mac=settings.device_mac)
            if args.json:
                json_print(result)
            else:
                text_print_temp(result)
            return 0

        if args.command == "set-temp":
            with FamicleanSession(settings) as session:
                result = session.set_temp(args.temperature, device_ip=settings.device_ip, device_mac=settings.device_mac)
            if args.json:
                json_print(result)
            else:
                text_print_set_temp(result)
            return 0

        if args.command == "check-threshold":
            result = run_check_threshold(
                settings,
                device_ip=settings.device_ip,
                device_mac=settings.device_mac,
                send_notifications=not args.no_notify,
                force_notify=args.force_notify,
            )
            if args.json:
                json_print(result)
            else:
                text_print_total_gas(result)
                print(f"目前門檻: {result['current_threshold_m3']} M3")
                print(f"通知狀態: {result['notification']['reason']}")
            return 0

        parser.error("unknown command")
        return 2
    except FamicleanError as exc:
        if args.json:
            json_print({"error": str(exc)})
        else:
            print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
