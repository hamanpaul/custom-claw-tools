from __future__ import annotations

from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from zoneinfo import ZoneInfo
import json
import math


def now_iso(timezone_name: str) -> str:
    try:
        return datetime.now(ZoneInfo(timezone_name)).isoformat(timespec="seconds")
    except Exception:
        return datetime.now().astimezone().isoformat(timespec="seconds")


def load_state(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(path: Path, state: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def threshold_floor(total_m3: float, step_m3: int) -> int:
    if step_m3 <= 0:
        raise ValueError("step_m3 must be positive")
    return int(math.floor(total_m3 / step_m3) * step_m3)


def thresholds_crossed(last_notified_threshold_m3: int | None, total_m3: float, step_m3: int) -> list[int]:
    current_threshold = threshold_floor(total_m3, step_m3)
    if last_notified_threshold_m3 is None or current_threshold <= last_notified_threshold_m3:
        return []
    return list(range(last_notified_threshold_m3 + step_m3, current_threshold + step_m3, step_m3))


def remaining_to_next_threshold(total_m3: float, step_m3: int) -> float:
    if step_m3 <= 0:
        raise ValueError("step_m3 must be positive")

    step = Decimal(str(step_m3))
    total = Decimal(str(total_m3))
    remaining = step - (total % step)
    return float(remaining.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
