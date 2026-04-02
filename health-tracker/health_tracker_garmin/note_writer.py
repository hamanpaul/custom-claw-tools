"""Write GarminDB snapshots into canonical health-tracker notes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import json
from pathlib import Path

from .config import RuntimeConfig
from .garmin_reader import ActivitySnapshot, DailyGarminSnapshot


WEEKDAYS_ZH = ["週一", "週二", "週三", "週四", "週五", "週六", "週日"]


@dataclass(frozen=True)
class WriteResult:
    """Paths written for one Garmin snapshot."""

    daily_path: Path
    raw_path: Path


def _render_template(template_text: str, replacements: dict[str, str]) -> str:
    rendered = template_text
    for key, value in replacements.items():
        rendered = rendered.replace("{{" + key + "}}", value)
    return rendered


def _format_number(value: float | int | None, suffix: str = "") -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        text = f"{value:.2f}".rstrip("0").rstrip(".")
    else:
        text = str(value)
    return f"{text}{suffix}"


def _format_distance(value: float | int | None) -> str:
    if value is None:
        return ""
    return f"{_format_number(value)}（依 Garmin 單位）"


def _format_duration(duration: timedelta | None) -> str:
    if duration is None:
        return ""
    total_minutes = int(duration.total_seconds() // 60)
    hours, minutes = divmod(total_minutes, 60)
    if hours and minutes:
        return f"{hours} 小時 {minutes} 分"
    if hours:
        return f"{hours} 小時"
    return f"{minutes} 分"


def _format_time_of_day(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.strftime("%H:%M")


def _captured_at_slug(captured_at: datetime) -> str:
    return captured_at.strftime("%Y%m%dT%H%M%S%z")


def _load_template(runtime: RuntimeConfig, relative_path: str) -> str:
    live_candidate = runtime.templates_root / relative_path
    if live_candidate.exists():
        return live_candidate.read_text(encoding="utf-8")
    repo_candidate = runtime.repo_templates_root / relative_path
    return repo_candidate.read_text(encoding="utf-8")


def _replace_section(markdown: str, heading: str, body_lines: list[str]) -> str:
    lines = markdown.splitlines()
    section_start = None
    for index, line in enumerate(lines):
        if line.strip() == heading:
            section_start = index
            break

    replacement = [heading, ""] + body_lines + [""]
    if section_start is None:
        if lines and lines[-1] != "":
            lines.append("")
        lines.extend(replacement)
        return "\n".join(lines).rstrip() + "\n"

    section_end = len(lines)
    for index in range(section_start + 1, len(lines)):
        if lines[index].startswith("## "):
            section_end = index
            break

    new_lines = lines[:section_start] + replacement + lines[section_end:]
    return "\n".join(new_lines).rstrip() + "\n"


def _split_section(markdown: str, heading: str) -> tuple[list[str], list[str], list[str]]:
    lines = markdown.splitlines()
    section_start = None
    for index, line in enumerate(lines):
        if line.strip() == heading:
            section_start = index
            break

    if section_start is None:
        return lines, [], []

    section_end = len(lines)
    for index in range(section_start + 1, len(lines)):
        if lines[index].startswith("## "):
            section_end = index
            break

    return lines[: section_start + 1], lines[section_start + 1 : section_end], lines[section_end:]


def _extract_section_bullets(markdown: str, heading: str) -> list[str]:
    lines = markdown.splitlines()
    section_start = None
    for index, line in enumerate(lines):
        if line.strip() == heading:
            section_start = index
            break
    if section_start is None:
        return []

    collected: list[str] = []
    for index in range(section_start + 1, len(lines)):
        line = lines[index]
        if line.startswith("## "):
            break
        stripped = line.strip()
        if stripped.startswith("- "):
            value = stripped[2:].strip()
            if value:
                collected.append(value)
    return collected


def _managed_markers(block_key: str) -> tuple[str, str]:
    return (
        f"<!-- health-tracker-garmin:{block_key}:start -->",
        f"<!-- health-tracker-garmin:{block_key}:end -->",
    )


def _replace_managed_block(body_lines: list[str], block_key: str, block_lines: list[str]) -> list[str]:
    start_marker, end_marker = _managed_markers(block_key)
    start_index = next((index for index, line in enumerate(body_lines) if line.strip() == start_marker), None)
    end_index = next((index for index, line in enumerate(body_lines) if line.strip() == end_marker), None)
    managed_block = ["", start_marker, *block_lines, end_marker, ""]
    if start_index is not None and end_index is not None and start_index < end_index:
        return body_lines[:start_index] + managed_block + body_lines[end_index + 1 :]
    return body_lines + managed_block


def _training_section_is_placeholder(body_lines: list[str]) -> bool:
    placeholder_headings = {"### 訓練項目 1", "### 訓練摘要"}
    for line in body_lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped in placeholder_headings:
            continue
        if stripped.startswith("- "):
            if "：" not in stripped:
                return False
            _, value = stripped[2:].split("：", 1)
            if value.strip():
                return False
            continue
        return False
    return True


def _upsert_training_section(markdown: str, block_lines: list[str]) -> str:
    prefix, body, suffix = _split_section(markdown, "## 訓練")
    if not prefix:
        return markdown

    if _training_section_is_placeholder(body):
        new_body = ["", *_replace_managed_block([], "training", block_lines)]
    else:
        new_body = _replace_managed_block(body, "training", block_lines)
    rebuilt = prefix + new_body + suffix
    return "\n".join(rebuilt).rstrip() + "\n"


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered


def _format_activity_name(activity: ActivitySnapshot) -> str:
    if activity.name:
        return activity.name
    if activity.sport and activity.sub_sport and activity.sub_sport != activity.sport:
        return f"{activity.sport} / {activity.sub_sport}"
    return activity.sport or activity.sub_sport or activity.activity_id


class GarminNoteWriter:
    """Canonical note writer for GarminDB snapshots."""

    def __init__(self, runtime: RuntimeConfig):
        self.runtime = runtime

    def _ensure_daily_file(self, target_day: date, *, dry_run: bool) -> Path:
        daily_path = self.runtime.daily_root / f"{target_day.isoformat()}.md"
        if daily_path.exists() or dry_run:
            return daily_path

        daily_path.parent.mkdir(parents=True, exist_ok=True)
        template_text = _load_template(self.runtime, "daily-log-template.md")
        daily_path.write_text(
            _render_template(
                template_text,
                {
                    "date": target_day.isoformat(),
                    "weekday": WEEKDAYS_ZH[target_day.weekday()],
                },
            ),
            encoding="utf-8",
        )
        return daily_path

    def _build_raw_markdown(self, snapshot: DailyGarminSnapshot, captured_at: datetime) -> str:
        summary = snapshot.summary
        sleep = snapshot.sleep
        structured_fields = [
            f"- day: {snapshot.day.isoformat()}",
            f"- steps: {summary.steps if summary and summary.steps is not None else ''}",
            f"- distance: {summary.distance if summary and summary.distance is not None else ''}",
            f"- calories_active: {summary.calories_active if summary and summary.calories_active is not None else ''}",
            f"- sleep_duration: {_format_duration(sleep.duration) if sleep else ''}",
            f"- sleep_score: {sleep.score if sleep and sleep.score is not None else ''}",
            f"- activity_count: {len(snapshot.activities)}",
        ]
        if snapshot.activities:
            structured_fields.append(
                "- activity_ids: " + ", ".join(activity.activity_id for activity in snapshot.activities)
            )

        raw_payload = json.dumps(snapshot.to_dict(), ensure_ascii=False, indent=2)
        return "\n".join(
            [
                f"# 健康原始紀錄｜{captured_at.isoformat()}",
                "",
                "## 基本資訊",
                "",
                f"- 在地日期：{snapshot.day.isoformat()}",
                "- 資料類型：garmin-day",
                "- 來源類型：import",
                f"- 來源參考：{'; '.join(snapshot.source_refs)}",
                "- 信心：high",
                "- 處理狀態：已整理",
                "",
                "## 原始內容",
                "",
                "```json",
                raw_payload,
                "```",
                "",
                "## 結構化欄位",
                "",
                *structured_fields,
                "",
                "## 補充註記",
                "",
                "- Garmin secrets 仍留在 repo 外的 GarminDB runtime。",
                "",
            ]
        )

    def _write_raw_record(self, snapshot: DailyGarminSnapshot, captured_at: datetime, *, dry_run: bool) -> Path:
        slug = _captured_at_slug(captured_at)
        raw_dir = (
            self.runtime.raw_root
            / f"{snapshot.day.year:04d}"
            / f"{snapshot.day.month:02d}"
            / f"{snapshot.day.day:02d}"
        )
        raw_path = raw_dir / f"{slug}-garmin-day-import.md"
        if not dry_run:
            raw_dir.mkdir(parents=True, exist_ok=True)
            raw_path.write_text(self._build_raw_markdown(snapshot, captured_at), encoding="utf-8")
        return raw_path

    def _overview_lines(self, snapshot: DailyGarminSnapshot) -> list[str]:
        summary_parts: list[str] = []
        if snapshot.sleep and snapshot.sleep.duration:
            summary_parts.append(f"睡眠 {_format_duration(snapshot.sleep.duration)}")
        if snapshot.summary and snapshot.summary.steps is not None:
            summary_parts.append(f"步數 {_format_number(snapshot.summary.steps)}")
        if snapshot.activities:
            summary_parts.append(f"活動 {len(snapshot.activities)} 筆")

        categories = sum(
            [
                1 if snapshot.sleep else 0,
                1 if snapshot.summary else 0,
                1 if snapshot.activities else 0,
            ]
        )
        completeness = "高" if categories >= 3 else "中" if categories == 2 else "低"
        status = "Garmin 睡眠與活動資料已同步" if categories >= 2 else "Garmin 單一來源資料已同步"
        return [
            f"- 日期：{snapshot.day.isoformat()}",
            f"- 星期：{WEEKDAYS_ZH[snapshot.day.weekday()]}",
            f"- 主要狀態：{status}",
            f"- 今日摘要：{'; '.join(summary_parts) if summary_parts else 'Garmin 本日沒有可落地的摘要欄位'}",
            f"- 資料完整度：{completeness}",
        ]

    def _activity_lines(self, snapshot: DailyGarminSnapshot) -> list[str]:
        summary = snapshot.summary
        steps = _format_number(summary.steps) if summary else ""
        distance = _format_distance(summary.distance) if summary else ""
        moderate = _format_duration(summary.moderate_activity) if summary else ""
        vigorous = _format_duration(summary.vigorous_activity) if summary else ""
        active_bits = [bit for bit in [moderate, vigorous] if bit]
        active_text = " / ".join(
            [f"中強度 {moderate}" if moderate else "", f"高強度 {vigorous}" if vigorous else ""]
        ).strip(" /")
        if active_bits and active_text:
            total_minutes = timedelta()
            if summary and summary.moderate_activity:
                total_minutes += summary.moderate_activity
            if summary and summary.vigorous_activity:
                total_minutes += summary.vigorous_activity
            activity_time = f"{_format_duration(total_minutes)}（{active_text}）"
        else:
            activity_time = ""

        if snapshot.activities:
            names = ", ".join(_format_activity_name(activity) for activity in snapshot.activities[:3])
            if len(snapshot.activities) > 3:
                names += " 等"
            activity_summary = f"Garmin 來源共 {len(snapshot.activities)} 筆活動（{names}）"
        else:
            activity_summary = summary.description if summary and summary.description else "本日沒有 Garmin 活動 session"

        return [
            f"- 步數：{steps}",
            f"- 距離：{distance}",
            f"- 活動時間：{activity_time}",
            f"- 運動消耗：{_format_number(summary.calories_active, ' kcal') if summary and summary.calories_active is not None else ''}",
            f"- 活動摘要：{activity_summary}",
        ]

    def _sleep_lines(self, snapshot: DailyGarminSnapshot) -> list[str]:
        if not snapshot.sleep:
            return [
                "- 睡眠時數：",
                "- 入睡時間：",
                "- 起床時間：",
                "- 夜間醒來次數：",
                "- 睡眠品質 / 分數：",
                "- 睡眠摘要：Garmin 本日沒有 sleep row",
            ]

        score_parts = []
        if snapshot.sleep.score is not None:
            score_parts.append(str(snapshot.sleep.score))
        if snapshot.sleep.qualifier:
            score_parts.append(snapshot.sleep.qualifier)

        summary_bits = []
        if snapshot.sleep.avg_stress is not None:
            summary_bits.append(f"平均壓力 {_format_number(snapshot.sleep.avg_stress)}")
        if not summary_bits:
            summary_bits.append("Garmin 未提供穩定可用的醒來次數")

        return [
            f"- 睡眠時數：{_format_duration(snapshot.sleep.duration)}",
            f"- 入睡時間：{_format_time_of_day(snapshot.sleep.start)}",
            f"- 起床時間：{_format_time_of_day(snapshot.sleep.end)}",
            "- 夜間醒來次數：未提供",
            f"- 睡眠品質 / 分數：{' / '.join(score_parts)}",
            f"- 睡眠摘要：{'; '.join(summary_bits)}",
        ]

    def _training_lines(self, snapshot: DailyGarminSnapshot) -> list[str]:
        if not snapshot.activities:
            return [
                "### 訓練摘要",
                "",
                "- 今日訓練重點：本日沒有 Garmin 活動 session",
                "- 恢復觀察：Garmin 匯入未提供可穩定落地的 recovery/readiness 指標",
            ]

        lines: list[str] = []
        total_distance = 0.0
        for index, activity in enumerate(snapshot.activities, start=1):
            if activity.distance:
                total_distance += activity.distance
            summary_bits = [
                bit
                for bit in [
                    _format_duration(activity.elapsed_time),
                    _format_distance(activity.distance) if activity.distance is not None else "",
                    f"平均心率 {_format_number(activity.avg_hr, ' bpm')}" if activity.avg_hr is not None else "",
                    f"訓練效果 {_format_number(activity.training_effect)}" if activity.training_effect is not None else "",
                    f"訓練負荷 {_format_number(activity.training_load)}" if activity.training_load is not None else "",
                ]
                if bit
            ]
            lines.extend(
                [
                    f"### 訓練項目 {index}",
                    "",
                    f"- 動作名稱：{_format_activity_name(activity)}",
                    "- 組數：不適用（Garmin 活動）",
                    "- 次數：不適用（Garmin 活動）",
                    "- 重量：不適用（Garmin 活動）",
                    f"- 總訓練量：{'; '.join(summary_bits)}",
                    "- 信心：high",
                    "",
                ]
            )

        lines.extend(
            [
                "### Garmin 匯入訓練摘要",
                "",
                f"- 今日訓練重點：Garmin 共 {len(snapshot.activities)} 筆活動，總距離 {_format_distance(total_distance)}",
                "- 恢復觀察：Garmin 匯入未提供可穩定落地的 recovery/readiness 指標",
            ]
        )
        return lines

    def _raw_index_lines(self, existing_markdown: str, raw_relative_path: Path) -> list[str]:
        existing_entries = _extract_section_bullets(existing_markdown, "## 原始紀錄索引")
        merged = _dedupe(existing_entries + [raw_relative_path.as_posix()])
        return [f"- {entry}" for entry in merged]

    def write_snapshot(
        self,
        snapshot: DailyGarminSnapshot,
        *,
        captured_at: datetime,
        dry_run: bool = False,
    ) -> WriteResult:
        """Write raw + daily notes for one Garmin snapshot."""

        daily_path = self._ensure_daily_file(snapshot.day, dry_run=dry_run)
        raw_path = self._write_raw_record(snapshot, captured_at, dry_run=dry_run)
        raw_relative_path = raw_path.relative_to(self.runtime.notes_root)

        if dry_run:
            return WriteResult(daily_path=daily_path, raw_path=raw_path)

        existing_markdown = daily_path.read_text(encoding="utf-8")
        updated = existing_markdown
        updated = _replace_section(updated, "## 今日總覽", self._overview_lines(snapshot))
        updated = _replace_section(updated, "## 活動", self._activity_lines(snapshot))
        updated = _replace_section(updated, "## 睡眠", self._sleep_lines(snapshot))
        updated = _upsert_training_section(updated, self._training_lines(snapshot))
        updated = _replace_section(updated, "## 原始紀錄索引", self._raw_index_lines(existing_markdown, raw_relative_path))
        daily_path.write_text(updated, encoding="utf-8")
        return WriteResult(daily_path=daily_path, raw_path=raw_path)
