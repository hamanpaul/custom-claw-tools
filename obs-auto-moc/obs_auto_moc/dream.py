from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .engine import index_note_file, iter_allowed_note_files, resolve_paths
from .memory_ledger import load_memory_snapshot, resolve_memory_ledger_paths
from .note_contract import inspect_memory_note
from .session_insights import load_imported_session_insights


@dataclass
class DreamModeResult:
    generated_at: str
    proposal_path: Path
    missing_contract_note_paths: list[str]
    duplicate_candidates: list[list[str]]
    contradiction_count: int
    session_patch_proposals: list[str]
    accepted_rule_candidates: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "proposal_path": str(self.proposal_path),
            "missing_contract_note_paths": self.missing_contract_note_paths,
            "duplicate_candidates": self.duplicate_candidates,
            "contradiction_count": self.contradiction_count,
            "session_patch_proposals": self.session_patch_proposals,
            "accepted_rule_candidates": self.accepted_rule_candidates,
        }


def run_dream_mode(
    *,
    sync_root: Path | None = None,
    vault_path: Path | None = None,
    artifacts_root: Path | None = None,
    generated_at: str,
) -> DreamModeResult:
    paths = resolve_paths(sync_root=sync_root, vault_path=vault_path, artifacts_root=artifacts_root, generated_at=generated_at)
    ledger = load_memory_snapshot(paths.artifacts_root)
    imported = load_imported_session_insights(paths.artifacts_root)
    memory_paths = resolve_memory_ledger_paths(paths.artifacts_root)
    memory_paths.dream_root.mkdir(parents=True, exist_ok=True)

    missing_contract_note_paths: list[str] = []
    titles: dict[str, list[str]] = defaultdict(list)
    for note_file in iter_allowed_note_files(paths.vault_path):
        note = index_note_file(note_file, relative_to=paths.vault_path)
        titles[note.title.casefold()].append(note.relative_path)
        inspection = inspect_memory_note(note.relative_path, note_file.read_text(encoding="utf-8", errors="replace"))
        if note.top_level != "root-note" and inspection["missing_sections"]:
            missing_contract_note_paths.append(note.relative_path)

    duplicate_candidates = [sorted(paths_group) for paths_group in titles.values() if len(paths_group) > 1][:8]
    contradiction_count = len(ledger["contradictions"])
    session_patch_proposals = imported.get("patch_proposals") or []
    accepted_rule_candidates = imported.get("accepted_rule_candidates") or []
    proposal_path = memory_paths.dream_root / f"{generated_at[:19].replace(':', '').replace('-', '')}-dream.md"
    lines = [
        f"# Dream Mode Proposal ({generated_at})",
        "",
        "## Missing memory contract sections",
    ]
    for note_path in missing_contract_note_paths[:12]:
        lines.append(f"- {note_path}")
    if not missing_contract_note_paths:
        lines.append("- None.")
    lines.extend(["", "## Duplicate merge suggestions"])
    for group in duplicate_candidates:
        lines.append(f"- {' | '.join(group)}")
    if not duplicate_candidates:
        lines.append("- None.")
    lines.extend(["", "## Session lesson proposals"])
    for item in session_patch_proposals or ["No session lesson proposals surfaced yet."]:
        lines.append(item if item.startswith("- ") else f"- {item}")
    lines.extend(["", "## Accepted working-rule candidates"])
    for item in accepted_rule_candidates or ["No accepted working-rule candidates yet."]:
        lines.append(item if item.startswith("- ") else f"- {item}")
    lines.extend(
        [
            "",
            "## Contradiction review",
            f"- contradiction_count: {contradiction_count}",
            "",
        ]
    )
    proposal_path.write_text("\n".join(lines), encoding="utf-8")
    return DreamModeResult(
        generated_at=generated_at,
        proposal_path=proposal_path,
        missing_contract_note_paths=missing_contract_note_paths,
        duplicate_candidates=duplicate_candidates,
        contradiction_count=contradiction_count,
        session_patch_proposals=session_patch_proposals,
        accepted_rule_candidates=accepted_rule_candidates,
    )
