from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .engine import atomic_write, normalize_list, normalize_scalar, resolve_paths, unique_preserving_order
from .memory_ledger import resolve_memory_ledger_paths

RULE_TEMPLATES = {
    "turn_aborted": "收到可直接執行的明確需求時，優先實作並回報驗證結果，避免先輸出冗長規劃。",
    "context_compacted": "跨檔案或長流程任務先摘要既有結論，再進入下一步，降低上下文流失風險。",
    "agent_reasoning": "保持輸出可驗證且精簡，只保留會影響決策的證據與結論。",
    "task_complete": "任務完成後同步更新對應規範，避免同類型問題重複發生。",
}


@dataclass
class ImportSessionInsightsResult:
    generated_at: str
    health_paths: dict[str, str]
    dream_overlay_path: str
    persona_overlay_path: str
    method_graph_path: str | None
    top_event_types: list[str]
    heuristic_candidates: list[str]
    accepted_rule_candidates: list[str]
    imported_inputs: dict[str, str]
    skill_card_count: int
    skill_link_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "health_paths": self.health_paths,
            "dream_overlay_path": self.dream_overlay_path,
            "persona_overlay_path": self.persona_overlay_path,
            "method_graph_path": self.method_graph_path,
            "top_event_types": self.top_event_types,
            "heuristic_candidates": self.heuristic_candidates,
            "accepted_rule_candidates": self.accepted_rule_candidates,
            "imported_inputs": self.imported_inputs,
            "skill_card_count": self.skill_card_count,
            "skill_link_count": self.skill_link_count,
        }


def _timestamp_slug(generated_at: str) -> str:
    return generated_at[:19].replace(":", "").replace("-", "")


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"session insights payload must be a JSON object: {path}")
    return payload


def _write_json_versions(root: Path, stem: str, generated_at: str, payload: dict[str, Any]) -> dict[str, str]:
    slug = _timestamp_slug(generated_at)
    timestamped = root / f"{stem}-{slug}.json"
    latest = root / f"{stem}-latest.json"
    content = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    atomic_write(timestamped, content)
    atomic_write(latest, content)
    return {
        "timestamped": str(timestamped),
        "latest": str(latest),
    }


def _write_markdown_versions(root: Path, stem: str, generated_at: str, body: str) -> dict[str, str]:
    slug = _timestamp_slug(generated_at)
    timestamped = root / f"{stem}-{slug}.md"
    latest = root / f"{stem}.md"
    content = body.rstrip() + "\n"
    atomic_write(timestamped, content)
    atomic_write(latest, content)
    return {
        "timestamped": str(timestamped),
        "latest": str(latest),
    }


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_insights_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    if payload is None:
        return {
            "generated_at": None,
            "sessions_root": None,
            "session_count": 0,
            "scoring_formula": None,
            "half_life_days": None,
            "short_window_days": None,
            "long_window_days": None,
            "rows": [],
        }
    scoring = payload.get("scoring")
    source = scoring if isinstance(scoring, dict) else payload
    rows: list[dict[str, Any]] = []
    for item in source.get("rows") or []:
        if not isinstance(item, dict):
            continue
        event_type = normalize_scalar(item.get("event_type"))
        if not event_type:
            continue
        rows.append(
            {
                "event_type": event_type,
                "raw_count": _to_int(item.get("raw_count"), 0),
                "short_weighted": round(_to_float(item.get("short_weighted"), 0.0), 4),
                "long_weighted": round(_to_float(item.get("long_weighted"), 0.0), 4),
                "severity": round(_to_float(item.get("severity"), 0.0), 4),
                "score": round(_to_float(item.get("score"), 0.0), 4),
            }
        )
    return {
        "generated_at": normalize_scalar(payload.get("generated_at")),
        "sessions_root": normalize_scalar(payload.get("sessions_root")),
        "session_count": _to_int(payload.get("session_count"), 0),
        "scoring_formula": normalize_scalar(source.get("scoring_formula")),
        "half_life_days": source.get("half_life_days"),
        "short_window_days": source.get("short_window_days"),
        "long_window_days": source.get("long_window_days"),
        "rows": rows,
    }


def _normalize_lesson_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    if payload is None:
        return {
            "generated_at": None,
            "session_path": None,
            "event_counts": {},
            "response_item_counts": {},
            "friction_signals": {},
            "patch_proposal": [],
        }
    report = payload.get("report")
    source = report if isinstance(report, dict) else payload
    event_counts = source.get("event_counts") if isinstance(source.get("event_counts"), dict) else {}
    response_item_counts = (
        source.get("response_item_counts") if isinstance(source.get("response_item_counts"), dict) else {}
    )
    friction_signals = source.get("friction_signals") if isinstance(source.get("friction_signals"), dict) else {}
    return {
        "generated_at": normalize_scalar(payload.get("generated_at")),
        "session_path": normalize_scalar(payload.get("session_path")),
        "event_counts": {str(key): _to_int(value, 0) for key, value in event_counts.items()},
        "response_item_counts": {str(key): _to_int(value, 0) for key, value in response_item_counts.items()},
        "friction_signals": {str(key): _to_int(value, 0) for key, value in friction_signals.items()},
        "patch_proposal": normalize_list(source.get("patch_proposal")),
    }


def _normalize_decision_list(payload: Any) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    if not isinstance(payload, list):
        return rows
    for item in payload:
        if not isinstance(item, dict):
            continue
        event_type = normalize_scalar(item.get("event_type"))
        action = normalize_scalar(item.get("action"))
        decision = normalize_scalar(item.get("decision"))
        reason = normalize_scalar(item.get("reason")) or normalize_scalar(item.get("decision_reason")) or ""
        if not event_type:
            continue
        rows.append(
            {
                "event_type": event_type,
                "action": action or "",
                "decision": decision or "",
                "reason": reason,
            }
        )
    return rows


def _normalize_proposal_list(payload: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not isinstance(payload, list):
        return rows
    for item in payload:
        if not isinstance(item, dict):
            continue
        event_type = normalize_scalar(item.get("event_type"))
        if not event_type:
            continue
        rows.append(
            {
                "event_type": event_type,
                "action": normalize_scalar(item.get("action")) or "",
                "score": round(_to_float(item.get("score"), 0.0), 4),
                "decision_reason": normalize_scalar(item.get("decision_reason")) or normalize_scalar(item.get("reason")) or "",
            }
        )
    return rows


def _normalize_decision_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    if payload is None:
        return {
            "accepted_proposals": [],
            "rejected_proposals": [],
            "decisions": [],
        }
    source = payload.get("decision") if isinstance(payload.get("decision"), dict) else payload
    return {
        "accepted_proposals": _normalize_proposal_list(source.get("accepted_proposals")),
        "rejected_proposals": _normalize_proposal_list(source.get("rejected_proposals")),
        "decisions": _normalize_decision_list(source.get("decisions")),
    }


def _normalize_card_list(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        items = payload.get("skill_cards") or payload.get("cards") or payload.get("rows") or []
    else:
        items = []
    rows: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        label = normalize_scalar(item.get("title")) or normalize_scalar(item.get("topic_id")) or normalize_scalar(item.get("skill_id"))
        if not label:
            continue
        rows.append(
            {
                "label": label,
                "skill_id": normalize_scalar(item.get("skill_id")) or "",
                "topic_id": normalize_scalar(item.get("topic_id")) or "",
                "confidence": round(_to_float(item.get("confidence"), 0.0), 4),
                "evidence_count": _to_int(item.get("evidence_count"), 0),
                "signals": normalize_list(item.get("signals")),
                "related_paths": normalize_list(item.get("related_paths")),
                "sample_commands": normalize_list(item.get("sample_commands")),
            }
        )
    return rows


def _normalize_link_list(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        items = payload.get("skill_links") or payload.get("links") or payload.get("rows") or []
    else:
        items = []
    rows: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        source = normalize_scalar(item.get("source")) or normalize_scalar(item.get("from_skill")) or normalize_scalar(item.get("from"))
        target = normalize_scalar(item.get("target")) or normalize_scalar(item.get("to_skill")) or normalize_scalar(item.get("to"))
        if not source or not target:
            continue
        rows.append(
            {
                "source": source,
                "target": target,
                "relation": normalize_scalar(item.get("relation")) or normalize_scalar(item.get("relation_type")) or "related",
                "confidence": round(_to_float(item.get("confidence"), 0.0), 4),
            }
        )
    return rows


def _decision_rule_sentence(event_type: str, reason: str) -> str:
    base = RULE_TEMPLATES.get(
        event_type,
        f"針對 `{event_type}` 類事件，採最小可驗證修改並同步更新規範。",
    )
    if reason and reason != "no reason provided":
        return f"{base} 依據：{reason}。"
    return base


def _accepted_rule_candidates(decision_payload: dict[str, Any]) -> list[str]:
    rows: list[str] = []
    for item in decision_payload.get("accepted_proposals") or []:
        event_type = normalize_scalar(item.get("event_type"))
        if not event_type:
            continue
        rows.append(_decision_rule_sentence(event_type, normalize_scalar(item.get("decision_reason")) or ""))
    return unique_preserving_order(rows)


def _heuristic_candidates(lesson_payload: dict[str, Any], decision_payload: dict[str, Any]) -> list[str]:
    return unique_preserving_order(
        normalize_list(lesson_payload.get("patch_proposal")) + _accepted_rule_candidates(decision_payload)
    )


def _render_dream_overlay(
    *,
    generated_at: str,
    insights_payload: dict[str, Any],
    lesson_payload: dict[str, Any],
    accepted_rule_candidates: list[str],
) -> str:
    lines = [
        f"# Session Lessons ({generated_at})",
        "",
        "## Patch proposals",
    ]
    for item in normalize_list(lesson_payload.get("patch_proposal")) or ["No patch proposals surfaced yet."]:
        lines.append(item if item.startswith("- ") else f"- {item}")
    lines.extend(["", "## Accepted working-rule candidates"])
    for item in accepted_rule_candidates or ["No accepted working-rule candidates yet."]:
        lines.append(item if item.startswith("- ") else f"- {item}")
    lines.extend(["", "## Top operational signals"])
    for row in (insights_payload.get("rows") or [])[:8]:
        lines.append(
            f"- {row['event_type']} :: score={row['score']} raw_count={row['raw_count']} severity={row['severity']}"
        )
    if not insights_payload.get("rows"):
        lines.append("- None surfaced yet.")
    return "\n".join(lines)


def _render_persona_overlay(generated_at: str, heuristic_candidates: list[str]) -> str:
    lines = [
        f"# Session-Derived Heuristics ({generated_at})",
        "",
        "## Heuristic candidates",
    ]
    for item in heuristic_candidates or ["No session-derived heuristics surfaced yet."]:
        lines.append(item if item.startswith("- ") else f"- {item}")
    return "\n".join(lines)


def _render_method_graph(generated_at: str, skill_cards: list[dict[str, Any]], skill_links: list[dict[str, Any]]) -> str:
    lines = [
        f"# Skill Method Graph ({generated_at})",
        "",
        "## Skill cards",
    ]
    for row in skill_cards or []:
        suffix = f" confidence={row['confidence']}" if row.get("confidence") else ""
        evidence = f" evidence_count={row['evidence_count']}" if row.get("evidence_count") else ""
        lines.append(f"- {row['label']}{suffix}{evidence}")
    if not skill_cards:
        lines.append("- None imported.")
    lines.extend(["", "## Skill links"])
    for row in skill_links or []:
        suffix = f" confidence={row['confidence']}" if row.get("confidence") else ""
        lines.append(f"- {row['source']} -> {row['target']} ({row['relation']}){suffix}")
    if not skill_links:
        lines.append("- None imported.")
    return "\n".join(lines)


def load_imported_session_insights(artifacts_root: Path) -> dict[str, Any]:
    memory_paths = resolve_memory_ledger_paths(artifacts_root)
    insights_payload = _normalize_insights_payload(_read_json(memory_paths.health_root / "session-insights-latest.json"))
    lesson_payload = _normalize_lesson_payload(_read_json(memory_paths.health_root / "session-lessons-latest.json"))
    decision_payload = _normalize_decision_payload(_read_json(memory_paths.health_root / "session-decisions-latest.json"))
    skill_cards = _read_json(memory_paths.health_root / "skill-cards-latest.json") or {"rows": []}
    skill_links = _read_json(memory_paths.health_root / "skill-links-latest.json") or {"rows": []}
    normalized_skill_cards = _normalize_card_list(skill_cards)
    normalized_skill_links = _normalize_link_list(skill_links)
    accepted_rule_candidates = _accepted_rule_candidates(decision_payload)
    heuristic_candidates = _heuristic_candidates(lesson_payload, decision_payload)
    return {
        "insights": insights_payload,
        "lesson": lesson_payload,
        "decision": decision_payload,
        "skill_cards": normalized_skill_cards,
        "skill_links": normalized_skill_links,
        "accepted_rule_candidates": accepted_rule_candidates,
        "heuristic_candidates": heuristic_candidates,
        "top_event_types": [row["event_type"] for row in (insights_payload.get("rows") or [])[:8]],
        "friction_signals": lesson_payload.get("friction_signals") or {},
        "patch_proposals": normalize_list(lesson_payload.get("patch_proposal")),
    }


def import_session_insights(
    *,
    generated_at: str,
    sync_root: Path | None = None,
    vault_path: Path | None = None,
    artifacts_root: Path | None = None,
    insights_path: Path | None = None,
    lesson_path: Path | None = None,
    decision_path: Path | None = None,
    skill_cards_path: Path | None = None,
    skill_links_path: Path | None = None,
) -> ImportSessionInsightsResult:
    input_paths = {
        "insights": insights_path,
        "lesson": lesson_path,
        "decision": decision_path,
        "skill_cards": skill_cards_path,
        "skill_links": skill_links_path,
    }
    if not any(path is not None for path in input_paths.values()):
        raise RuntimeError("import-session-insights requires at least one input artifact")

    paths = resolve_paths(sync_root=sync_root, vault_path=vault_path, artifacts_root=artifacts_root, generated_at=generated_at)
    memory_paths = resolve_memory_ledger_paths(paths.artifacts_root)
    for directory in (memory_paths.health_root, memory_paths.dream_root, memory_paths.persona_root, memory_paths.synthesis_root):
        directory.mkdir(parents=True, exist_ok=True)

    raw_insights = _read_json(insights_path) if insights_path else None
    raw_lesson = _read_json(lesson_path) if lesson_path else None
    raw_decision = _read_json(decision_path) if decision_path else None
    raw_skill_cards = _read_json(skill_cards_path) if skill_cards_path else None
    raw_skill_links = _read_json(skill_links_path) if skill_links_path else None

    insights_payload = _normalize_insights_payload(raw_insights)
    lesson_payload = _normalize_lesson_payload(raw_lesson)
    decision_payload = _normalize_decision_payload(raw_decision)
    skill_cards = _normalize_card_list(raw_skill_cards)
    skill_links = _normalize_link_list(raw_skill_links)

    health_paths: dict[str, str] = {}
    health_paths.update(
        {
            "session_insights_latest": _write_json_versions(memory_paths.health_root, "session-insights", generated_at, insights_payload)["latest"],
            "session_lessons_latest": _write_json_versions(memory_paths.health_root, "session-lessons", generated_at, lesson_payload)["latest"],
            "session_decisions_latest": _write_json_versions(memory_paths.health_root, "session-decisions", generated_at, decision_payload)["latest"],
        }
    )
    if raw_skill_cards is not None:
        health_paths["skill_cards_latest"] = _write_json_versions(
            memory_paths.health_root, "skill-cards", generated_at, {"rows": skill_cards}
        )["latest"]
    if raw_skill_links is not None:
        health_paths["skill_links_latest"] = _write_json_versions(
            memory_paths.health_root, "skill-links", generated_at, {"rows": skill_links}
        )["latest"]

    accepted_rule_candidates = _accepted_rule_candidates(decision_payload)
    heuristic_candidates = _heuristic_candidates(lesson_payload, decision_payload)

    dream_paths = _write_markdown_versions(
        memory_paths.dream_root,
        "session-lessons",
        generated_at,
        _render_dream_overlay(
            generated_at=generated_at,
            insights_payload=insights_payload,
            lesson_payload=lesson_payload,
            accepted_rule_candidates=accepted_rule_candidates,
        ),
    )
    persona_paths = _write_markdown_versions(
        memory_paths.persona_root,
        "session-derived-heuristics",
        generated_at,
        _render_persona_overlay(generated_at, heuristic_candidates),
    )

    method_graph_path: str | None = None
    if skill_cards or skill_links:
        method_graph_path = _write_markdown_versions(
            memory_paths.synthesis_root,
            "skill-method-graph",
            generated_at,
            _render_method_graph(generated_at, skill_cards, skill_links),
        )["latest"]

    return ImportSessionInsightsResult(
        generated_at=generated_at,
        health_paths=health_paths,
        dream_overlay_path=dream_paths["latest"],
        persona_overlay_path=persona_paths["latest"],
        method_graph_path=method_graph_path,
        top_event_types=[row["event_type"] for row in (insights_payload.get("rows") or [])[:8]],
        heuristic_candidates=heuristic_candidates,
        accepted_rule_candidates=accepted_rule_candidates,
        imported_inputs={name: str(path) for name, path in input_paths.items() if path is not None},
        skill_card_count=len(skill_cards),
        skill_link_count=len(skill_links),
    )
