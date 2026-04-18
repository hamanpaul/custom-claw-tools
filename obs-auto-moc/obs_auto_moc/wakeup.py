from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .engine import resolve_paths, scan_notes
from .memory_ledger import load_memory_snapshot, resolve_memory_ledger_paths
from .session_insights import load_imported_session_insights


@dataclass
class WakeUpBundleResult:
    generated_at: str
    output_path: Path
    hot_note_paths: list[str]
    stale_note_paths: list[str]
    open_questions: list[str]
    contradiction_count: int
    operational_signals: list[str]
    session_friction_signals: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "output_path": str(self.output_path),
            "hot_note_paths": self.hot_note_paths,
            "stale_note_paths": self.stale_note_paths,
            "open_questions": self.open_questions,
            "contradiction_count": self.contradiction_count,
            "operational_signals": self.operational_signals,
            "session_friction_signals": self.session_friction_signals,
        }


def build_wake_up_bundle(
    *,
    sync_root: Path | None = None,
    vault_path: Path | None = None,
    artifacts_root: Path | None = None,
    generated_at: str,
) -> WakeUpBundleResult:
    paths = resolve_paths(sync_root=sync_root, vault_path=vault_path, artifacts_root=artifacts_root, generated_at=generated_at)
    notes = scan_notes(paths.vault_path, paths.artifacts_root, paths.output_moc_path)
    ledger = load_memory_snapshot(paths.artifacts_root)
    imported = load_imported_session_insights(paths.artifacts_root)
    memory_paths = resolve_memory_ledger_paths(paths.artifacts_root)
    memory_paths.wakeup_root.mkdir(parents=True, exist_ok=True)

    hot_notes = sorted(
        notes,
        key=lambda note: (note.last_resonated_at or "", note.hub_score, note.inbound_count, note.relative_path),
        reverse=True,
    )[:8]
    stale_notes = sorted(
        [note for note in notes if not note.last_resonated_at],
        key=lambda note: (note.updated_at or "", note.relative_path),
    )[:8]
    open_questions: list[str] = []
    for row in ledger["note_facts"]:
        for question in row.get("open_questions") or []:
            if question not in open_questions:
                open_questions.append(question)
            if len(open_questions) >= 8:
                break
        if len(open_questions) >= 8:
            break

    contradiction_count = len(ledger["contradictions"])
    operational_signals = [
        f"{row['event_type']} :: score={row['score']} raw_count={row['raw_count']}"
        for row in (imported["insights"].get("rows") or [])[:5]
    ]
    session_friction_signals = dict(imported.get("friction_signals") or {})
    output_path = memory_paths.wakeup_root / f"{generated_at[:19].replace(':', '').replace('-', '')}-wake-up.md"
    lines = [
        f"# Memory Wake-Up Bundle ({generated_at})",
        "",
        "## Hot notes",
    ]
    for note in hot_notes:
        lines.append(f"- {note.relative_path} :: {note.title}")
    lines.extend(["", "## Stale notes"])
    for note in stale_notes:
        lines.append(f"- {note.relative_path} :: {note.title}")
    lines.extend(["", "## Open questions"])
    for question in open_questions or ["- None surfaced yet."]:
        lines.append(question if question.startswith("- ") else f"- {question}")
    lines.extend(["", "## Operational signals"])
    for item in operational_signals or ["- None surfaced yet."]:
        lines.append(item if item.startswith("- ") else f"- {item}")
    lines.extend(["", "## Session frictions"])
    if session_friction_signals:
        for key, value in sorted(session_friction_signals.items()):
            lines.append(f"- {key}: {value}")
    else:
        lines.append("- None surfaced yet.")
    lines.extend(
        [
            "",
            "## Contradictions",
            f"- contradiction_count: {contradiction_count}",
            "",
        ]
    )
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return WakeUpBundleResult(
        generated_at=generated_at,
        output_path=output_path,
        hot_note_paths=[note.relative_path for note in hot_notes],
        stale_note_paths=[note.relative_path for note in stale_notes],
        open_questions=open_questions,
        contradiction_count=contradiction_count,
        operational_signals=operational_signals,
        session_friction_signals=session_friction_signals,
    )
