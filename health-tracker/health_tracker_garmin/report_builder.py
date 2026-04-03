"""Build canonical health reports from daily notes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import calendar
from pathlib import Path
import re

from .config import RuntimeConfig
from .note_writer import (
    _format_duration,
    _format_number,
    _load_template,
    _render_template,
    _replace_section,
    _split_section,
)

REPORT_RANK = {"monthly": 0, "quarterly": 1, "yearly": 2}
PERIOD_LABEL = {"monthly": "月報", "quarterly": "季報", "yearly": "年報"}
COMPLETENESS_SCORE = {"高": 1.0, "中": 0.6, "低": 0.3}
NUMBER_PATTERN = re.compile(r"-?\d+(?:,\d{3})*(?:\.\d+)?")


@dataclass(frozen=True)
class DailyMetrics:
    """Structured metrics parsed from one canonical daily note."""

    day: date
    steps: float | None
    sleep_minutes: int | None
    calories_intake: float | None
    protein_g: float | None
    weight_kg: float | None
    body_fat_percent: float | None
    completeness_label: str | None
    activity_summary: str | None
    sleep_summary: str | None
    training_focus: str | None
    missing_inputs: tuple[str, ...]
    low_confidence_items: tuple[str, ...]

    @property
    def has_training(self) -> bool:
        if self.training_focus is None:
            return False
        text = self.training_focus.strip()
        return bool(text) and not text.startswith("本日沒有")


@dataclass(frozen=True)
class PeriodWindow:
    """One concrete report file to update."""

    report_type: str
    label: str
    start: date
    end: date
    path: Path


@dataclass(frozen=True)
class PeriodStats:
    """Aggregated metrics for one report window."""

    label: str
    report_type: str
    days_with_notes: int
    completeness_label: str
    avg_steps: float | None
    steps_days: int
    avg_sleep_minutes: float | None
    sleep_days: int
    training_days: int
    avg_calories: float | None
    calories_days: int
    avg_protein: float | None
    protein_days: int
    first_weight: float | None
    latest_weight: float | None
    weight_days: int
    first_body_fat: float | None
    latest_body_fat: float | None
    body_fat_days: int
    activity_summaries: tuple[str, ...]
    sleep_summaries: tuple[str, ...]
    training_summaries: tuple[str, ...]
    missing_inputs: tuple[str, ...]
    low_confidence_items: tuple[str, ...]


@dataclass(frozen=True)
class ReportUpdate:
    """A report file that changed during this run."""

    report_type: str
    label: str
    path: Path
    summary_line: str


@dataclass(frozen=True)
class ReportBuildResult:
    """Summary of report updates for a set of target days."""

    target_days: tuple[date, ...]
    updates: tuple[ReportUpdate, ...]

    @property
    def notification_message(self) -> str | None:
        if not self.updates:
            return None
        lines = [
            f"health-tracker 已更新 {len(self.updates)} 份報表（影響 {len(self.target_days)} 天日誌）",
            *[f"- {update.summary_line}" for update in self.updates],
        ]
        return "\n".join(lines)


def build_reports(
    runtime: RuntimeConfig,
    *,
    target_days: list[date],
    dry_run: bool = False,
) -> ReportBuildResult:
    """Update monthly, quarterly, and yearly reports affected by target days."""

    normalized_days = tuple(sorted(set(target_days)))
    updates: list[ReportUpdate] = []
    for window in _iter_report_windows(runtime, normalized_days):
        update = _update_report_window(runtime, window, dry_run=dry_run)
        if update is not None:
            updates.append(update)
    return ReportBuildResult(target_days=normalized_days, updates=tuple(updates))


def _iter_report_windows(runtime: RuntimeConfig, target_days: tuple[date, ...]) -> list[PeriodWindow]:
    windows: dict[tuple[str, str], PeriodWindow] = {}
    for target_day in target_days:
        month_window = _monthly_window(runtime, target_day.year, target_day.month)
        quarter_window = _quarterly_window(runtime, target_day.year, _quarter_for_month(target_day.month))
        year_window = _yearly_window(runtime, target_day.year)
        for window in (month_window, quarter_window, year_window):
            windows[(window.report_type, window.label)] = window
    return sorted(
        windows.values(),
        key=lambda item: (REPORT_RANK[item.report_type], item.start, item.label),
    )


def _quarter_for_month(month: int) -> int:
    return ((month - 1) // 3) + 1


def _monthly_window(runtime: RuntimeConfig, year: int, month: int) -> PeriodWindow:
    last_day = calendar.monthrange(year, month)[1]
    return PeriodWindow(
        report_type="monthly",
        label=f"{year:04d}-{month:02d}",
        start=date(year, month, 1),
        end=date(year, month, last_day),
        path=runtime.reports_root / "monthly" / f"{year:04d}-{month:02d}.md",
    )


def _quarterly_window(runtime: RuntimeConfig, year: int, quarter: int) -> PeriodWindow:
    start_month = ((quarter - 1) * 3) + 1
    end_month = start_month + 2
    last_day = calendar.monthrange(year, end_month)[1]
    return PeriodWindow(
        report_type="quarterly",
        label=f"{year:04d}-Q{quarter}",
        start=date(year, start_month, 1),
        end=date(year, end_month, last_day),
        path=runtime.reports_root / "quarterly" / f"{year:04d}-Q{quarter}.md",
    )


def _yearly_window(runtime: RuntimeConfig, year: int) -> PeriodWindow:
    return PeriodWindow(
        report_type="yearly",
        label=f"{year:04d}",
        start=date(year, 1, 1),
        end=date(year, 12, 31),
        path=runtime.reports_root / "yearly" / f"{year:04d}.md",
    )


def _previous_window(runtime: RuntimeConfig, window: PeriodWindow) -> PeriodWindow:
    if window.report_type == "monthly":
        if window.start.month == 1:
            return _monthly_window(runtime, window.start.year - 1, 12)
        return _monthly_window(runtime, window.start.year, window.start.month - 1)
    if window.report_type == "quarterly":
        current_quarter = _quarter_for_month(window.start.month)
        if current_quarter == 1:
            return _quarterly_window(runtime, window.start.year - 1, 4)
        return _quarterly_window(runtime, window.start.year, current_quarter - 1)
    return _yearly_window(runtime, window.start.year - 1)


def _update_report_window(
    runtime: RuntimeConfig,
    window: PeriodWindow,
    *,
    dry_run: bool,
) -> ReportUpdate | None:
    records = _load_daily_metrics(runtime, window.start, window.end)
    if not records:
        return None

    previous_window = _previous_window(runtime, window)
    previous_records = _load_daily_metrics(runtime, previous_window.start, previous_window.end)
    current = _build_period_stats(window, records)
    previous = _build_period_stats(previous_window, previous_records) if previous_records else None

    if window.report_type == "monthly":
        updated_markdown = _render_monthly_report(runtime, window, current, previous)
    elif window.report_type == "quarterly":
        monthly_breakdown = _quarter_monthly_stats(runtime, window)
        previous_breakdown = _quarter_monthly_stats(runtime, previous_window)
        updated_markdown = _render_quarterly_report(
            runtime,
            window,
            current,
            previous,
            monthly_breakdown,
            previous_breakdown,
        )
    else:
        monthly_breakdown = _year_monthly_stats(runtime, window.start.year)
        previous_breakdown = _year_monthly_stats(runtime, previous_window.start.year)
        updated_markdown = _render_yearly_report(
            runtime,
            window,
            current,
            previous,
            monthly_breakdown,
            previous_breakdown,
        )

    existing_markdown = window.path.read_text(encoding="utf-8") if window.path.exists() else ""
    if existing_markdown == updated_markdown:
        return None
    if not dry_run:
        window.path.parent.mkdir(parents=True, exist_ok=True)
        window.path.write_text(updated_markdown, encoding="utf-8")

    return ReportUpdate(
        report_type=window.report_type,
        label=window.label,
        path=window.path,
        summary_line=_build_summary_line(window, current),
    )


def _load_daily_metrics(runtime: RuntimeConfig, start: date, end: date) -> list[DailyMetrics]:
    records: list[DailyMetrics] = []
    if not runtime.daily_root.exists():
        return records
    for path in sorted(runtime.daily_root.glob("*.md")):
        try:
            target_day = date.fromisoformat(path.stem)
        except ValueError:
            continue
        if start <= target_day <= end:
            records.append(_parse_daily_metrics(path, target_day))
    return records


def _section_mapping(markdown: str, heading: str) -> dict[str, str]:
    _, body, _ = _split_section(markdown, heading)
    values: dict[str, str] = {}
    for line in body:
        stripped = line.strip()
        if not stripped.startswith("- "):
            continue
        payload = stripped[2:]
        if "：" in payload:
            label, value = payload.split("：", 1)
        elif ":" in payload:
            label, value = payload.split(":", 1)
        else:
            continue
        values[label.strip()] = value.strip()
    return values


def _section_last_value(markdown: str, heading: str, label: str) -> str | None:
    _, body, _ = _split_section(markdown, heading)
    found: str | None = None
    for line in body:
        stripped = line.strip()
        if not stripped.startswith("- "):
            continue
        payload = stripped[2:]
        if "：" in payload:
            parsed_label, value = payload.split("：", 1)
        elif ":" in payload:
            parsed_label, value = payload.split(":", 1)
        else:
            continue
        if parsed_label.strip() == label:
            found = value.strip()
    return found


def _split_value_list(value: str | None) -> tuple[str, ...]:
    if value is None:
        return ()
    normalized = value.replace("；", ",").replace("、", ",").replace(";", ",")
    items = [item.strip() for item in normalized.split(",") if item.strip()]
    if not items and value.strip():
        return (value.strip(),)
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return tuple(ordered)


def _first_number(value: str | None) -> float | None:
    if value is None:
        return None
    match = NUMBER_PATTERN.search(value.replace("%", ""))
    if match is None:
        return None
    return float(match.group(0).replace(",", ""))


def _parse_minutes(value: str | None) -> int | None:
    if value is None:
        return None
    hours_match = re.search(r"(\d+)\s*小時", value)
    minutes_match = re.search(r"(\d+)\s*分", value)
    if hours_match is None and minutes_match is None:
        return None
    total = 0
    if hours_match is not None:
        total += int(hours_match.group(1)) * 60
    if minutes_match is not None:
        total += int(minutes_match.group(1))
    return total


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _parse_daily_metrics(path: Path, target_day: date) -> DailyMetrics:
    markdown = path.read_text(encoding="utf-8")
    overview = _section_mapping(markdown, "## 今日總覽")
    activity = _section_mapping(markdown, "## 活動")
    sleep = _section_mapping(markdown, "## 睡眠")
    diet = _section_mapping(markdown, "## 飲食紀錄")
    energy = _section_mapping(markdown, "## 熱量與營養預算")
    labs = _section_mapping(markdown, "## 檢驗與身體組成")
    quality = _section_mapping(markdown, "## 資料品質")

    calories_value = diet.get("今日總攝取熱量") or energy.get("已攝取熱量")
    protein_value = diet.get("今日總蛋白質") or energy.get("蛋白質已達成")

    return DailyMetrics(
        day=target_day,
        steps=_first_number(activity.get("步數")),
        sleep_minutes=_parse_minutes(sleep.get("睡眠時數")),
        calories_intake=_first_number(calories_value),
        protein_g=_first_number(protein_value),
        weight_kg=_first_number(labs.get("體重")),
        body_fat_percent=_first_number(labs.get("體脂")),
        completeness_label=_clean_text(overview.get("資料完整度")),
        activity_summary=_clean_text(activity.get("活動摘要")),
        sleep_summary=_clean_text(sleep.get("睡眠摘要")),
        training_focus=_clean_text(_section_last_value(markdown, "## 訓練", "今日訓練重點")),
        missing_inputs=_split_value_list(quality.get("缺失資料")),
        low_confidence_items=_split_value_list(quality.get("低信心項目")),
    )


def _average(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _dedupe_text(values: list[str]) -> tuple[str, ...]:
    ordered: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value and value not in seen:
            seen.add(value)
            ordered.append(value)
    return tuple(ordered)


def _coverage_label(available: int, total: int) -> str:
    if total <= 0 or available <= 0:
        return "低"
    ratio = available / total
    if ratio >= 0.75:
        return "高"
    if ratio >= 0.4:
        return "中"
    return "低"


def _overall_completeness(records: list[DailyMetrics]) -> str:
    if not records:
        return "低"
    scores = [COMPLETENESS_SCORE[record.completeness_label] for record in records if record.completeness_label in COMPLETENESS_SCORE]
    if scores:
        ratio = sum(scores) / len(scores)
    else:
        metric_coverages = []
        total = len(records)
        metric_coverages.append(sum(1 for record in records if record.steps is not None) / total)
        metric_coverages.append(sum(1 for record in records if record.sleep_minutes is not None) / total)
        metric_coverages.append(sum(1 for record in records if record.calories_intake is not None) / total)
        metric_coverages.append(sum(1 for record in records if record.weight_kg is not None) / total)
        ratio = sum(metric_coverages) / len(metric_coverages)
    if ratio >= 0.75:
        return "高"
    if ratio >= 0.45:
        return "中"
    return "低"


def _build_period_stats(window: PeriodWindow, records: list[DailyMetrics]) -> PeriodStats:
    ordered = sorted(records, key=lambda item: item.day)
    step_values = [record.steps for record in ordered if record.steps is not None]
    sleep_values = [float(record.sleep_minutes) for record in ordered if record.sleep_minutes is not None]
    calories_values = [record.calories_intake for record in ordered if record.calories_intake is not None]
    protein_values = [record.protein_g for record in ordered if record.protein_g is not None]
    weight_records = [record for record in ordered if record.weight_kg is not None]
    body_fat_records = [record for record in ordered if record.body_fat_percent is not None]
    return PeriodStats(
        label=window.label,
        report_type=window.report_type,
        days_with_notes=len(ordered),
        completeness_label=_overall_completeness(ordered),
        avg_steps=_average([value for value in step_values if value is not None]),
        steps_days=len(step_values),
        avg_sleep_minutes=_average(sleep_values),
        sleep_days=len(sleep_values),
        training_days=sum(1 for record in ordered if record.has_training),
        avg_calories=_average([value for value in calories_values if value is not None]),
        calories_days=len(calories_values),
        avg_protein=_average([value for value in protein_values if value is not None]),
        protein_days=len(protein_values),
        first_weight=weight_records[0].weight_kg if weight_records else None,
        latest_weight=weight_records[-1].weight_kg if weight_records else None,
        weight_days=len(weight_records),
        first_body_fat=body_fat_records[0].body_fat_percent if body_fat_records else None,
        latest_body_fat=body_fat_records[-1].body_fat_percent if body_fat_records else None,
        body_fat_days=len(body_fat_records),
        activity_summaries=_dedupe_text(
            [record.activity_summary for record in ordered if record.activity_summary]
        ),
        sleep_summaries=_dedupe_text([record.sleep_summary for record in ordered if record.sleep_summary]),
        training_summaries=_dedupe_text(
            [record.training_focus for record in ordered if record.training_focus]
        ),
        missing_inputs=_dedupe_text(
            [item for record in ordered for item in record.missing_inputs]
        ),
        low_confidence_items=_dedupe_text(
            [item for record in ordered for item in record.low_confidence_items]
        ),
    )


def _quarter_monthly_stats(runtime: RuntimeConfig, window: PeriodWindow) -> list[PeriodStats]:
    stats: list[PeriodStats] = []
    for offset in range(3):
        month = window.start.month + offset
        year = window.start.year
        month_window = _monthly_window(runtime, year, month)
        stats.append(
            _build_period_stats(
                month_window,
                _load_daily_metrics(runtime, month_window.start, month_window.end),
            )
        )
    return stats


def _year_monthly_stats(runtime: RuntimeConfig, year: int) -> list[PeriodStats]:
    stats: list[PeriodStats] = []
    for month in range(1, 13):
        window = _monthly_window(runtime, year, month)
        stats.append(_build_period_stats(window, _load_daily_metrics(runtime, window.start, window.end)))
    return stats


def _render_monthly_report(
    runtime: RuntimeConfig,
    window: PeriodWindow,
    current: PeriodStats,
    previous: PeriodStats | None,
) -> str:
    markdown = _base_report_markdown(runtime, window, "reports/monthly-report-template.md")
    markdown = _replace_section(markdown, "## 本月摘要", _monthly_summary_lines(current, previous))
    markdown = _replace_section(markdown, "## 核心指標", _monthly_table_lines(current, previous))
    markdown = _replace_section(markdown, "## 活動與睡眠", _monthly_activity_lines(current, previous))
    markdown = _replace_section(markdown, "## 飲食與營養", _monthly_nutrition_lines(current, previous))
    markdown = _replace_section(markdown, "## 訓練", _monthly_training_lines(current, previous))
    markdown = _replace_section(markdown, "## 身體組成與檢驗", _monthly_body_lines(current, previous))
    markdown = _replace_section(markdown, "## 缺資料與低信心項目", _quality_lines(current))
    markdown = _replace_section(markdown, "## 下月追蹤重點", _monthly_follow_up_lines(current))
    return markdown


def _render_quarterly_report(
    runtime: RuntimeConfig,
    window: PeriodWindow,
    current: PeriodStats,
    previous: PeriodStats | None,
    monthly_breakdown: list[PeriodStats],
    previous_breakdown: list[PeriodStats],
) -> str:
    markdown = _base_report_markdown(runtime, window, "reports/quarterly-report-template.md")
    markdown = _replace_section(markdown, "## 本季摘要", _quarterly_summary_lines(current, previous))
    markdown = _replace_section(
        markdown,
        "## 月度趨勢表",
        _quarterly_table_lines(monthly_breakdown),
    )
    markdown = _replace_section(
        markdown,
        "## 活動與睡眠趨勢",
        _quarterly_activity_lines(current, previous, monthly_breakdown),
    )
    markdown = _replace_section(
        markdown,
        "## 訓練一致性",
        _quarterly_training_lines(current, previous, monthly_breakdown),
    )
    markdown = _replace_section(
        markdown,
        "## 飲食與營養模式",
        _quarterly_nutrition_lines(current, previous, monthly_breakdown),
    )
    markdown = _replace_section(
        markdown,
        "## 身體組成與檢驗",
        _quarterly_body_lines(current, previous, monthly_breakdown, previous_breakdown),
    )
    markdown = _replace_section(markdown, "## 缺資料與低信心項目", _quality_lines(current))
    markdown = _replace_section(markdown, "## 下季追蹤重點", _quarterly_follow_up_lines(current))
    return markdown


def _render_yearly_report(
    runtime: RuntimeConfig,
    window: PeriodWindow,
    current: PeriodStats,
    previous: PeriodStats | None,
    monthly_breakdown: list[PeriodStats],
    previous_breakdown: list[PeriodStats],
) -> str:
    markdown = _base_report_markdown(runtime, window, "reports/yearly-report-template.md")
    markdown = _replace_section(markdown, "## 年度總覽", _yearly_summary_lines(current, previous))
    markdown = _replace_section(markdown, "## 年度核心指標", _yearly_table_lines(current, previous))
    markdown = _replace_section(
        markdown,
        "## 活動與睡眠模式",
        _yearly_activity_lines(current, previous, monthly_breakdown),
    )
    markdown = _replace_section(
        markdown,
        "## 訓練與恢復",
        _yearly_training_lines(current, previous, monthly_breakdown),
    )
    markdown = _replace_section(
        markdown,
        "## 飲食與營養",
        _yearly_nutrition_lines(current, previous, monthly_breakdown),
    )
    markdown = _replace_section(
        markdown,
        "## 身體組成與檢驗",
        _yearly_body_lines(current, previous, monthly_breakdown, previous_breakdown),
    )
    markdown = _replace_section(
        markdown,
        "## 年度亮點與風險",
        _yearly_highlights_lines(current, previous),
    )
    markdown = _replace_section(markdown, "## 明年追蹤重點", _yearly_follow_up_lines(current))
    return markdown


def _base_report_markdown(runtime: RuntimeConfig, window: PeriodWindow, template_path: str) -> str:
    if window.path.exists():
        return window.path.read_text(encoding="utf-8")

    template = _load_template(runtime, template_path)
    replacements = {"year": f"{window.start.year:04d}"}
    if window.report_type == "monthly":
        replacements["month"] = f"{window.start.month:02d}"
    elif window.report_type == "quarterly":
        replacements["quarter"] = str(_quarter_for_month(window.start.month))
    return _render_template(template, replacements)


def _format_int(value: float | None, suffix: str = "") -> str:
    if value is None:
        return "資料不足"
    return f"{int(round(value)):,}{suffix}"


def _format_decimal(value: float | None, suffix: str = "") -> str:
    if value is None:
        return "資料不足"
    return f"{value:.1f}{suffix}"


def _format_sleep(value: float | None) -> str:
    if value is None:
        return "資料不足"
    return _format_duration(timedelta(minutes=int(round(value))))


def _format_frequency(days: int, total: int) -> str:
    if total <= 0:
        return "資料不足"
    return f"{days} 天 / {total} 天"


def _format_weight(value: float | None) -> str:
    if value is None:
        return "資料不足"
    return f"{value:.1f} kg"


def _format_body_fat(value: float | None) -> str:
    if value is None:
        return "資料不足"
    return f"{value:.1f}%"


def _format_change(current: float | None, previous: float | None, suffix: str = "") -> str:
    if current is None or previous is None:
        return "—"
    delta = current - previous
    sign = "+" if delta > 0 else ""
    if suffix == "%":
        return f"{sign}{delta:.1f}%"
    if suffix:
        if suffix == " 分":
            return f"{sign}{int(round(delta))}{suffix}"
        return f"{sign}{delta:.1f}{suffix}"
    return f"{sign}{delta:.1f}"


def _format_metric_change(current: float | None, previous: float | None, kind: str) -> str:
    if kind == "days":
        if current is None or previous is None:
            return "—"
        delta = int(round(current - previous))
        sign = "+" if delta > 0 else ""
        return f"{sign}{delta} 天"
    if kind == "sleep":
        return _format_change(current, previous, " 分")
    if kind == "steps":
        if current is None or previous is None:
            return "—"
        delta = int(round(current - previous))
        sign = "+" if delta > 0 else ""
        return f"{sign}{delta:,}"
    if kind == "calories":
        return _format_change(current, previous, " kcal")
    if kind == "protein":
        return _format_change(current, previous, " g")
    if kind == "weight":
        return _format_change(current, previous, " kg")
    if kind == "body_fat":
        return _format_change(current, previous, "%")
    return "—"


def _compare_sentence(
    metric_name: str,
    current_value: float | None,
    previous_value: float | None,
    *,
    formatter,
    positive_is_good: bool | None,
    kind: str,
) -> str:
    if current_value is None:
        return f"{metric_name}資料不足，暫時只能保守觀察。"
    if previous_value is None:
        return f"{metric_name}目前為 {formatter(current_value)}，前期資料不足，先作為 baseline。"

    delta_text = _format_metric_change(current_value, previous_value, kind)
    if delta_text == "—":
        return f"{metric_name}目前為 {formatter(current_value)}。"

    direction = "持平"
    raw_delta = current_value - previous_value
    if abs(raw_delta) > 0.0001:
        direction = "上升" if raw_delta > 0 else "下降"

    if positive_is_good is True:
        assessment = "偏向改善" if raw_delta > 0 else "較前期回落"
    elif positive_is_good is False:
        assessment = "較前期降低" if raw_delta < 0 else "較前期偏高"
    else:
        assessment = "相較前期有變化"

    if direction == "持平":
        assessment = "大致持平"

    return f"{metric_name}{direction}至 {formatter(current_value)}（{delta_text}），{assessment}。"


def _coverage_summary(current: PeriodStats, field: str, days: int) -> str:
    return _coverage_label(days, current.days_with_notes)


def _month_focus_line(current: PeriodStats) -> str:
    bits = [f"納入 {current.days_with_notes} 天 daily"]
    if current.avg_steps is not None:
        bits.append(f"平均步數 {_format_int(current.avg_steps)}")
    if current.avg_sleep_minutes is not None:
        bits.append(f"平均睡眠 {_format_sleep(current.avg_sleep_minutes)}")
    bits.append(f"訓練 {_format_frequency(current.training_days, current.days_with_notes)}")
    return "；".join(bits)


def _monthly_summary_lines(current: PeriodStats, previous: PeriodStats | None) -> list[str]:
    comparison = _compare_sentence(
        "步數",
        current.avg_steps,
        previous.avg_steps if previous else None,
        formatter=lambda value: _format_int(value, " 步"),
        positive_is_good=True,
        kind="steps",
    )
    return [
        f"- 期間：{current.label}",
        f"- 本月重點：{_month_focus_line(current)}",
        f"- 整體評語：{comparison}",
        f"- 資料完整度：{current.completeness_label}",
    ]


def _monthly_table_lines(current: PeriodStats, previous: PeriodStats | None) -> list[str]:
    previous_steps = previous.avg_steps if previous else None
    previous_sleep = previous.avg_sleep_minutes if previous else None
    previous_calories = previous.avg_calories if previous else None
    previous_protein = previous.avg_protein if previous else None
    previous_weight = previous.latest_weight if previous else None
    previous_body_fat = previous.latest_body_fat if previous else None
    previous_training = float(previous.training_days) if previous else None

    return [
        "| 指標 | 本月 | 上月 | 變化 | 信心 |",
        "| --- | --- | --- | --- | --- |",
        f"| 平均步數 | {_format_int(current.avg_steps)} | {_format_int(previous_steps)} | {_format_metric_change(current.avg_steps, previous_steps, 'steps')} | {_coverage_summary(current, 'steps', current.steps_days)} |",
        f"| 平均睡眠時數 | {_format_sleep(current.avg_sleep_minutes)} | {_format_sleep(previous_sleep)} | {_format_metric_change(current.avg_sleep_minutes, previous_sleep, 'sleep')} | {_coverage_summary(current, 'sleep', current.sleep_days)} |",
        f"| 訓練頻率 | {_format_frequency(current.training_days, current.days_with_notes)} | {_format_frequency(previous.training_days, previous.days_with_notes) if previous else '資料不足'} | {_format_metric_change(float(current.training_days), previous_training, 'days')} | {_coverage_summary(current, 'training', current.days_with_notes)} |",
        f"| 平均熱量攝取 | {_format_int(current.avg_calories, ' kcal')} | {_format_int(previous_calories, ' kcal')} | {_format_metric_change(current.avg_calories, previous_calories, 'calories')} | {_coverage_summary(current, 'calories', current.calories_days)} |",
        f"| 平均蛋白質攝取 | {_format_decimal(current.avg_protein, ' g')} | {_format_decimal(previous_protein, ' g')} | {_format_metric_change(current.avg_protein, previous_protein, 'protein')} | {_coverage_summary(current, 'protein', current.protein_days)} |",
        f"| 體重變化 | {_format_weight(current.latest_weight)} | {_format_weight(previous_weight)} | {_format_metric_change(current.latest_weight, previous_weight, 'weight')} | {_coverage_summary(current, 'weight', current.weight_days)} |",
        f"| 體脂變化 | {_format_body_fat(current.latest_body_fat)} | {_format_body_fat(previous_body_fat)} | {_format_metric_change(current.latest_body_fat, previous_body_fat, 'body_fat')} | {_coverage_summary(current, 'bodyfat', current.body_fat_days)} |",
    ]


def _monthly_activity_lines(current: PeriodStats, previous: PeriodStats | None) -> list[str]:
    highlight = current.activity_summaries[0] if current.activity_summaries else "目前主要依每日步數與活動摘要判讀活動量。"
    risk = (
        "平均睡眠低於 6 小時，需留意恢復。"
        if current.avg_sleep_minutes is not None and current.avg_sleep_minutes < 360
        else "暫未看到明顯活動 / 睡眠風險，但仍需持續補齊資料。"
    )
    return [
        f"- 活動趨勢：{_compare_sentence('平均步數', current.avg_steps, previous.avg_steps if previous else None, formatter=lambda value: _format_int(value, ' 步'), positive_is_good=True, kind='steps')}",
        f"- 睡眠趨勢：{_compare_sentence('平均睡眠', current.avg_sleep_minutes, previous.avg_sleep_minutes if previous else None, formatter=_format_sleep, positive_is_good=True, kind='sleep')}",
        f"- 本月亮點：{highlight}",
        f"- 本月風險：{risk}",
    ]


def _monthly_nutrition_lines(current: PeriodStats, previous: PeriodStats | None) -> list[str]:
    calorie_text = _compare_sentence(
        "平均熱量攝取",
        current.avg_calories,
        previous.avg_calories if previous else None,
        formatter=lambda value: _format_int(value, " kcal"),
        positive_is_good=None,
        kind="calories",
    )
    protein_text = _compare_sentence(
        "平均蛋白質",
        current.avg_protein,
        previous.avg_protein if previous else None,
        formatter=lambda value: _format_decimal(value, " g"),
        positive_is_good=True,
        kind="protein",
    )
    micronutrients = (
        "目前 daily 尚未形成足夠穩定的微量營養欄位，只能保守標註。"
        if current.avg_protein is None and current.avg_calories is None
        else "可先用熱量 / 蛋白質作為主軸，微量營養仍需更多原始紀錄。"
    )
    gaps = _format_missing_items(current)
    return [
        f"- 熱量收支摘要：{calorie_text}",
        f"- 蛋白質達成情況：{protein_text}",
        f"- 微量營養觀察：{micronutrients}",
        f"- 主要缺口：{gaps}",
    ]


def _monthly_training_lines(current: PeriodStats, previous: PeriodStats | None) -> list[str]:
    summary = current.training_summaries[0] if current.training_summaries else "本月沒有穩定可比較的訓練摘要。"
    recovery = (
        "仍以睡眠與活動量代理恢復狀態；Garmin 匯入未提供穩定 recovery/readiness 指標。"
    )
    return [
        f"- 訓練一致性：本月有 {current.training_days} 天留下訓練重點，覆蓋 {_format_frequency(current.training_days, current.days_with_notes)}。",
        f"- 主要訓練項目：{summary}",
        f"- 恢復與疲勞觀察：{recovery}",
    ]


def _monthly_body_lines(current: PeriodStats, previous: PeriodStats | None) -> list[str]:
    weight_trend = _compare_sentence(
        "體重",
        current.latest_weight,
        previous.latest_weight if previous else None,
        formatter=_format_weight,
        positive_is_good=None,
        kind="weight",
    )
    body_fat_trend = _compare_sentence(
        "體脂",
        current.latest_body_fat,
        previous.latest_body_fat if previous else None,
        formatter=_format_body_fat,
        positive_is_good=False,
        kind="body_fat",
    )
    return [
        f"- 體重 / 體脂趨勢：{weight_trend} {body_fat_trend}",
        "- 檢驗重點：本月報表目前未看到穩定可比較的檢驗數值。",
        "- 待追蹤數值：若有體重、體脂或檢驗更新，建議持續補進 daily。",
    ]


def _format_missing_items(current: PeriodStats) -> str:
    items = list(current.missing_inputs)
    if current.calories_days == 0:
        items.append("飲食熱量")
    if current.protein_days == 0:
        items.append("蛋白質")
    if current.weight_days == 0:
        items.append("體重")
    if current.body_fat_days == 0:
        items.append("體脂")
    deduped = _dedupe_text(items)
    return "、".join(deduped) if deduped else "目前沒有明顯缺口。"


def _quality_lines(current: PeriodStats) -> list[str]:
    missing = _format_missing_items(current)
    low_confidence = (
        "、".join(current.low_confidence_items)
        if current.low_confidence_items
        else "目前沒有額外標記的低信心項目。"
    )
    suggestion = "優先補齊飲食 / 身體組成欄位，並維持 daily 記錄密度。"
    return [
        f"- 缺資料：{missing}",
        f"- 低信心估值：{low_confidence}",
        f"- 建議補資料項目：{suggestion}",
    ]


def _monthly_follow_up_lines(current: PeriodStats) -> list[str]:
    if current.avg_sleep_minutes is not None and current.avg_sleep_minutes < 420:
        return ["- 優先把平均睡眠拉回 7 小時附近，觀察恢復是否更穩定。"]
    if current.training_days == 0:
        return ["- 下月至少建立固定訓練紀錄，讓訓練趨勢可被比較。"]
    if current.calories_days == 0 or current.protein_days == 0:
        return ["- 補齊飲食熱量與蛋白質欄位，讓月報能加入營養趨勢。"]
    return ["- 延續目前記錄節奏，持續觀察步數、睡眠與訓練是否穩定。"]


def _trend_label(values: list[float | None]) -> str:
    available = [value for value in values if value is not None]
    if len(available) < 2:
        return "資料不足"
    if available[-1] > available[0]:
        return "上升"
    if available[-1] < available[0]:
        return "下降"
    return "持平"


def _quarterly_summary_lines(current: PeriodStats, previous: PeriodStats | None) -> list[str]:
    compare = _compare_sentence(
        "平均步數",
        current.avg_steps,
        previous.avg_steps if previous else None,
        formatter=lambda value: _format_int(value, " 步"),
        positive_is_good=True,
        kind="steps",
    )
    return [
        f"- 期間：{current.label}",
        f"- 本季重點：納入 {current.days_with_notes} 天 daily；平均步數 {_format_int(current.avg_steps)}；平均睡眠 {_format_sleep(current.avg_sleep_minutes)}。",
        f"- 整體評語：{compare}",
        f"- 資料完整度：{current.completeness_label}",
    ]


def _quarterly_table_lines(monthly_breakdown: list[PeriodStats]) -> list[str]:
    rows = [
        ("平均步數", [_format_int(item.avg_steps) for item in monthly_breakdown], _trend_label([item.avg_steps for item in monthly_breakdown])),
        ("平均睡眠時數", [_format_sleep(item.avg_sleep_minutes) for item in monthly_breakdown], _trend_label([item.avg_sleep_minutes for item in monthly_breakdown])),
        ("訓練頻率", [_format_frequency(item.training_days, item.days_with_notes) for item in monthly_breakdown], _trend_label([float(item.training_days) if item.days_with_notes else None for item in monthly_breakdown])),
        ("平均熱量攝取", [_format_int(item.avg_calories, " kcal") for item in monthly_breakdown], _trend_label([item.avg_calories for item in monthly_breakdown])),
        ("平均蛋白質攝取", [_format_decimal(item.avg_protein, " g") for item in monthly_breakdown], _trend_label([item.avg_protein for item in monthly_breakdown])),
        ("體重", [_format_weight(item.latest_weight) for item in monthly_breakdown], _trend_label([item.latest_weight for item in monthly_breakdown])),
        ("體脂", [_format_body_fat(item.latest_body_fat) for item in monthly_breakdown], _trend_label([item.latest_body_fat for item in monthly_breakdown])),
    ]
    lines = [
        "| 指標 | 第 1 月 | 第 2 月 | 第 3 月 | 趨勢 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for label, values, trend in rows:
        lines.append(f"| {label} | {values[0]} | {values[1]} | {values[2]} | {trend} |")
    return lines


def _quarterly_activity_lines(
    current: PeriodStats,
    previous: PeriodStats | None,
    monthly_breakdown: list[PeriodStats],
) -> list[str]:
    return [
        f"- 活動量變化：本季月度步數趨勢為 {_trend_label([item.avg_steps for item in monthly_breakdown])}；{_compare_sentence('季平均步數', current.avg_steps, previous.avg_steps if previous else None, formatter=lambda value: _format_int(value, ' 步'), positive_is_good=True, kind='steps')}",
        f"- 睡眠穩定度：本季月度睡眠趨勢為 {_trend_label([item.avg_sleep_minutes for item in monthly_breakdown])}；平均睡眠 {_format_sleep(current.avg_sleep_minutes)}。",
        "- 恢復觀察：目前仍以睡眠與活動量代理恢復狀態，Garmin 匯入沒有穩定的 readiness 指標。",
    ]


def _quarterly_training_lines(
    current: PeriodStats,
    previous: PeriodStats | None,
    monthly_breakdown: list[PeriodStats],
) -> list[str]:
    return [
        f"- 訓練頻率：本季共 {current.training_days} 天有訓練重點，月度趨勢 {_trend_label([float(item.training_days) if item.days_with_notes else None for item in monthly_breakdown])}。",
        f"- 訓練量模式：{current.training_summaries[0] if current.training_summaries else '目前訓練摘要仍偏少。'}",
        f"- 進步 / 停滯觀察：{_compare_sentence('訓練日數', float(current.training_days), float(previous.training_days) if previous else None, formatter=lambda value: f'{int(round(value))} 天', positive_is_good=True, kind='steps')}",
    ]


def _quarterly_nutrition_lines(
    current: PeriodStats,
    previous: PeriodStats | None,
    monthly_breakdown: list[PeriodStats],
) -> list[str]:
    return [
        f"- 熱量收支：{_compare_sentence('平均熱量', current.avg_calories, previous.avg_calories if previous else None, formatter=lambda value: _format_int(value, ' kcal'), positive_is_good=None, kind='calories')}",
        f"- 蛋白質與纖維：{_compare_sentence('平均蛋白質', current.avg_protein, previous.avg_protein if previous else None, formatter=lambda value: _format_decimal(value, ' g'), positive_is_good=True, kind='protein')}",
        "- 微量營養趨勢：目前仍需更多 daily 來源，才能穩定比較微量營養模式。",
        f"- 主要風險：{_format_missing_items(current)}",
    ]


def _quarterly_body_lines(
    current: PeriodStats,
    previous: PeriodStats | None,
    monthly_breakdown: list[PeriodStats],
    previous_breakdown: list[PeriodStats],
) -> list[str]:
    return [
        f"- 身體組成趨勢：體重 {_format_weight(current.latest_weight)}，體脂 {_format_body_fat(current.latest_body_fat)}；季內趨勢為 {_trend_label([item.latest_weight for item in monthly_breakdown])}。",
        "- 檢驗變化：本季尚未整理出足夠穩定的檢驗比較資料。",
        "- 需要持續追蹤的指標：若後續有體重、體脂或檢驗更新，請持續補進 daily。",
    ]


def _quarterly_follow_up_lines(current: PeriodStats) -> list[str]:
    if current.completeness_label == "低":
        return ["- 下季先提升 daily 覆蓋率，讓趨勢比較不被稀疏資料扭曲。"]
    if current.training_days == 0:
        return ["- 下季建立固定訓練紀錄，讓訓練一致性可以被量化。"]
    return ["- 下季持續補齊飲食與身體組成欄位，讓季報更完整。"]


def _yearly_summary_lines(current: PeriodStats, previous: PeriodStats | None) -> list[str]:
    return [
        f"- 年度：{current.label}",
        f"- 年度重點：今年共納入 {current.days_with_notes} 天 daily；平均步數 {_format_int(current.avg_steps)}；平均睡眠 {_format_sleep(current.avg_sleep_minutes)}。",
        f"- 整體評語：{_compare_sentence('年度步數', current.avg_steps, previous.avg_steps if previous else None, formatter=lambda value: _format_int(value, ' 步'), positive_is_good=True, kind='steps')}",
        f"- 資料完整度：{current.completeness_label}",
    ]


def _yearly_table_lines(current: PeriodStats, previous: PeriodStats | None) -> list[str]:
    return [
        "| 指標 | 年平均 / 年末 | 去年 | 變化 | 信心 |",
        "| --- | --- | --- | --- | --- |",
        f"| 平均步數 | {_format_int(current.avg_steps)} | {_format_int(previous.avg_steps if previous else None)} | {_format_metric_change(current.avg_steps, previous.avg_steps if previous else None, 'steps')} | {_coverage_summary(current, 'steps', current.steps_days)} |",
        f"| 平均睡眠時數 | {_format_sleep(current.avg_sleep_minutes)} | {_format_sleep(previous.avg_sleep_minutes if previous else None)} | {_format_metric_change(current.avg_sleep_minutes, previous.avg_sleep_minutes if previous else None, 'sleep')} | {_coverage_summary(current, 'sleep', current.sleep_days)} |",
        f"| 訓練頻率 | {_format_frequency(current.training_days, current.days_with_notes)} | {_format_frequency(previous.training_days, previous.days_with_notes) if previous else '資料不足'} | {_format_metric_change(float(current.training_days), float(previous.training_days) if previous else None, 'days')} | {_coverage_summary(current, 'training', current.days_with_notes)} |",
        f"| 平均熱量攝取 | {_format_int(current.avg_calories, ' kcal')} | {_format_int(previous.avg_calories if previous else None, ' kcal')} | {_format_metric_change(current.avg_calories, previous.avg_calories if previous else None, 'calories')} | {_coverage_summary(current, 'calories', current.calories_days)} |",
        f"| 平均蛋白質攝取 | {_format_decimal(current.avg_protein, ' g')} | {_format_decimal(previous.avg_protein if previous else None, ' g')} | {_format_metric_change(current.avg_protein, previous.avg_protein if previous else None, 'protein')} | {_coverage_summary(current, 'protein', current.protein_days)} |",
        f"| 體重 | {_format_weight(current.latest_weight)} | {_format_weight(previous.latest_weight if previous else None)} | {_format_metric_change(current.latest_weight, previous.latest_weight if previous else None, 'weight')} | {_coverage_summary(current, 'weight', current.weight_days)} |",
        f"| 體脂 | {_format_body_fat(current.latest_body_fat)} | {_format_body_fat(previous.latest_body_fat if previous else None)} | {_format_metric_change(current.latest_body_fat, previous.latest_body_fat if previous else None, 'body_fat')} | {_coverage_summary(current, 'bodyfat', current.body_fat_days)} |",
    ]


def _yearly_activity_lines(
    current: PeriodStats,
    previous: PeriodStats | None,
    monthly_breakdown: list[PeriodStats],
) -> list[str]:
    active_months = sum(1 for item in monthly_breakdown if item.days_with_notes)
    return [
        f"- 活動模式：今年共有 {active_months} 個月份有 daily 資料，活動量月度趨勢為 {_trend_label([item.avg_steps for item in monthly_breakdown])}。",
        f"- 睡眠模式：平均睡眠 {_format_sleep(current.avg_sleep_minutes)}；月度睡眠趨勢 {_trend_label([item.avg_sleep_minutes for item in monthly_breakdown])}。",
        f"- 年度穩定度：資料完整度 {current.completeness_label}，解讀時仍需搭配缺資料欄位。",
    ]


def _yearly_training_lines(
    current: PeriodStats,
    previous: PeriodStats | None,
    monthly_breakdown: list[PeriodStats],
) -> list[str]:
    return [
        f"- 訓練量模式：全年 {current.training_days} 天有訓練重點，月度趨勢 {_trend_label([float(item.training_days) if item.days_with_notes else None for item in monthly_breakdown])}。",
        f"- 一致性觀察：{_compare_sentence('年度訓練日數', float(current.training_days), float(previous.training_days) if previous else None, formatter=lambda value: f'{int(round(value))} 天', positive_is_good=True, kind='steps')}",
        "- 恢復與疲勞重點：目前仍以睡眠與活動量代理恢復狀態，Garmin 匯入沒有穩定 recovery/readiness 指標。",
    ]


def _yearly_nutrition_lines(
    current: PeriodStats,
    previous: PeriodStats | None,
    monthly_breakdown: list[PeriodStats],
) -> list[str]:
    return [
        f"- 熱量收支總結：{_compare_sentence('年度平均熱量', current.avg_calories, previous.avg_calories if previous else None, formatter=lambda value: _format_int(value, ' kcal'), positive_is_good=None, kind='calories')}",
        f"- 蛋白質與纖維總結：{_compare_sentence('年度平均蛋白質', current.avg_protein, previous.avg_protein if previous else None, formatter=lambda value: _format_decimal(value, ' g'), positive_is_good=True, kind='protein')}",
        "- 微量營養觀察：目前仍需更多 daily 來源，才能穩定產出年度微量營養比較。",
        f"- 年度主要缺口：{_format_missing_items(current)}",
    ]


def _yearly_body_lines(
    current: PeriodStats,
    previous: PeriodStats | None,
    monthly_breakdown: list[PeriodStats],
    previous_breakdown: list[PeriodStats],
) -> list[str]:
    return [
        f"- 身體組成年度變化：體重 {_compare_sentence('年度體重', current.latest_weight, previous.latest_weight if previous else None, formatter=_format_weight, positive_is_good=None, kind='weight')}",
        "- 檢驗指標年度變化：目前未累積足夠穩定的年度檢驗比較資料。",
        "- 需持續追蹤項目：若有體重、體脂或 lab 更新，請持續補入 daily。",
    ]


def _yearly_highlights_lines(current: PeriodStats, previous: PeriodStats | None) -> list[str]:
    highlight = (
        "步數與睡眠已有基本年度 baseline。"
        if current.avg_steps is not None or current.avg_sleep_minutes is not None
        else "今年主要在建立 baseline。"
    )
    risk = (
        "飲食與身體組成資料仍偏少，年度解讀要保守。"
        if current.calories_days == 0 or current.weight_days == 0
        else "目前沒有額外高風險訊號，但仍需持續補齊資料。"
    )
    return [
        f"- 亮點：{highlight}",
        f"- 風險：{risk}",
        "- 待改善面向：持續補齊飲食、身體組成與 lab 欄位，讓年報更完整。",
    ]


def _yearly_follow_up_lines(current: PeriodStats) -> list[str]:
    if current.completeness_label == "低":
        return ["- 明年先提升 daily 覆蓋率，減少 sparse data 對年度判讀的限制。"]
    return ["- 明年持續穩定記錄步數、睡眠、訓練與飲食，讓年度趨勢更可比較。"]


def _build_summary_line(window: PeriodWindow, current: PeriodStats) -> str:
    return (
        f"{PERIOD_LABEL[window.report_type]} {window.label}："
        f"平均步數 {_format_int(current.avg_steps)}；"
        f"平均睡眠 {_format_sleep(current.avg_sleep_minutes)}；"
        f"訓練 {_format_frequency(current.training_days, current.days_with_notes)}；"
        f"資料完整度 {current.completeness_label}"
    )
