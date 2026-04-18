from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .engine import atomic_write, parse_markdown_text, render_markdown, resolve_paths
from .memory_ledger import resolve_memory_ledger_paths
from .session_insights import load_imported_session_insights

HEURISTIC_MARKERS = ("prefer", "avoid", "must", "should", "先", "不要", "避免", "優先", "原則", "建議")
GOAL_MARKERS = ("goal", "priority", "objective", "目標", "想要", "希望", "規劃", "方向", "優先")


@dataclass
class PersonaGoalResult:
    generated_at: str
    overlay_path: Path
    canonical_path: str | None
    heuristics: list[str]
    session_heuristics: list[str]
    goals: list[str]
    source_note_count: int
    applied: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "overlay_path": str(self.overlay_path),
            "canonical_path": self.canonical_path,
            "heuristics": self.heuristics,
            "session_heuristics": self.session_heuristics,
            "goals": self.goals,
            "source_note_count": self.source_note_count,
            "applied": self.applied,
        }


def _collect_signals(note_file: Path) -> tuple[list[str], list[str]]:
    text = note_file.read_text(encoding="utf-8", errors="replace")
    parsed = parse_markdown_text(text)
    body = parsed.body if parsed.has_frontmatter else text
    heuristics: list[str] = []
    goals: list[str] = []
    for raw_line in body.splitlines():
        line = raw_line.strip().lstrip("-").strip()
        if not line:
            continue
        lower = line.casefold()
        if len(line) <= 180 and any(marker in lower for marker in HEURISTIC_MARKERS):
            heuristics.append(line)
        if len(line) <= 180 and any(marker in lower for marker in GOAL_MARKERS):
            goals.append(line)
    return heuristics, goals


def distill_persona_goals(
    *,
    sync_root: Path | None = None,
    vault_path: Path | None = None,
    artifacts_root: Path | None = None,
    generated_at: str,
    apply: bool = False,
) -> PersonaGoalResult:
    paths = resolve_paths(sync_root=sync_root, vault_path=vault_path, artifacts_root=artifacts_root, generated_at=generated_at)
    personal_root = paths.vault_path / "PersonalVault"
    memory_paths = resolve_memory_ledger_paths(paths.artifacts_root)
    memory_paths.persona_root.mkdir(parents=True, exist_ok=True)

    heuristic_counter: Counter[str] = Counter()
    goal_counter: Counter[str] = Counter()
    source_note_count = 0
    for note_file in sorted(personal_root.rglob("*.md")):
        if not note_file.is_file():
            continue
        source_note_count += 1
        heuristics, goals = _collect_signals(note_file)
        heuristic_counter.update(heuristics)
        goal_counter.update(goals)

    imported = load_imported_session_insights(paths.artifacts_root)
    session_heuristics = imported["heuristic_candidates"][:8]
    top_personal_heuristics = [item for item, _count in heuristic_counter.most_common(8)]
    top_heuristics = top_personal_heuristics + [item for item in session_heuristics if item not in top_personal_heuristics]
    top_goals = [item for item, _count in goal_counter.most_common(8)]
    overlay_path = memory_paths.persona_root / "persona-goal-model.md"
    lines = [
        f"# Persona Goal Model ({generated_at})",
        "",
        "## Distilled heuristics from PersonalVault",
    ]
    for item in top_personal_heuristics or ["No clear PersonalVault heuristics surfaced yet."]:
        lines.append(item if item.startswith("- ") else f"- {item}")
    lines.extend(["", "## Session-derived heuristic overlays"])
    for item in session_heuristics or ["No session-derived heuristics surfaced yet."]:
        lines.append(item if item.startswith("- ") else f"- {item}")
    lines.extend(["", "## Combined heuristics"])
    for item in top_heuristics or ["No clear heuristics surfaced yet."]:
        lines.append(item if item.startswith("- ") else f"- {item}")
    lines.extend(["", "## Goals hierarchy"])
    for item in top_goals or ["No clear goals surfaced yet."]:
        lines.append(item if item.startswith("- ") else f"- {item}")
    lines.extend(
        [
            "",
            "## Source scope",
            f"- PersonalVault notes scanned: {source_note_count}",
            f"- Session-derived heuristics imported: {len(session_heuristics)}",
            "",
        ]
    )
    overlay_path.write_text("\n".join(lines), encoding="utf-8")

    canonical_path: str | None = None
    if apply:
        canonical_file = personal_root / "Persona Goal Model.md"
        canonical_frontmatter = {
            "title": "Persona Goal Model",
            "type": "persona-goal-model",
            "generated_from": "obs-auto-moc",
            "updated_at": generated_at,
        }
        atomic_write(canonical_file, render_markdown(canonical_frontmatter, "\n".join(lines[2:])))
        canonical_path = str(canonical_file)

    return PersonaGoalResult(
        generated_at=generated_at,
        overlay_path=overlay_path,
        canonical_path=canonical_path,
        heuristics=top_heuristics,
        session_heuristics=session_heuristics,
        goals=top_goals,
        source_note_count=source_note_count,
        applied=apply,
    )
