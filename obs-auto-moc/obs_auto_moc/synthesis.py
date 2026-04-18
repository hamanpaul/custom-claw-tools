from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .engine import resolve_paths
from .memory_ledger import load_memory_snapshot, resolve_memory_ledger_paths
from .retrieval import query_memory


@dataclass
class SynthesisResult:
    generated_at: str
    query: str
    verified: list[dict[str, Any]]
    synthesized: list[str]
    open_questions: list[str]
    artifact_path: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "query": self.query,
            "verified": self.verified,
            "synthesized": self.synthesized,
            "open_questions": self.open_questions,
            "artifact_path": self.artifact_path,
        }


def synthesize_memory(
    *,
    query: str,
    sync_root: Path | None = None,
    vault_path: Path | None = None,
    artifacts_root: Path | None = None,
    generated_at: str,
    limit: int = 8,
    write_artifact: bool = False,
) -> SynthesisResult:
    paths = resolve_paths(sync_root=sync_root, vault_path=vault_path, artifacts_root=artifacts_root, generated_at=generated_at)
    query_result = query_memory(
        query=query,
        vault_path=paths.vault_path,
        artifacts_root=paths.artifacts_root,
        generated_at=generated_at,
        limit=limit,
    )
    ledger = load_memory_snapshot(paths.artifacts_root)
    note_paths = {row["note_path"] for row in query_result.results}

    entity_counter: Counter[str] = Counter()
    tag_counter: Counter[str] = Counter()
    for row in query_result.results:
        entity_counter.update(row.get("entities") or [])
        tag_counter.update(row.get("tags") or [])

    synthesized: list[str] = []
    for entity, count in entity_counter.most_common():
        if count >= 2:
            synthesized.append(f"Entity `{entity}` spans {count} matched notes.")
        if len(synthesized) >= 4:
            break
    for tag, count in tag_counter.most_common():
        if count >= 2 and len(synthesized) < 6:
            synthesized.append(f"Tag `{tag}` recurs across {count} matched notes.")

    open_questions: list[str] = []
    for row in ledger["contradictions"]:
        row_note_paths = set(row.get("note_paths") or [])
        if row_note_paths & note_paths:
            signal = row.get("signal")
            if signal and signal not in open_questions:
                open_questions.append(signal)
    for row in ledger["note_facts"]:
        if row.get("note_path") not in note_paths:
            continue
        for question in row.get("open_questions") or []:
            if question not in open_questions:
                open_questions.append(question)
    if not open_questions and len(query_result.results) >= 2:
        open_questions.append(
            f"What is the strongest causal link between {query_result.results[0]['note_path']} and {query_result.results[1]['note_path']}?"
        )

    artifact_path: str | None = None
    if write_artifact:
        memory_paths = resolve_memory_ledger_paths(paths.artifacts_root)
        memory_paths.synthesis_root.mkdir(parents=True, exist_ok=True)
        artifact = memory_paths.synthesis_root / f"{generated_at[:19].replace(':', '').replace('-', '')}-synthesis.md"
        lines = [
            f"# Memory Synthesis ({generated_at})",
            "",
            f"Query: {query}",
            "",
            "## VERIFIED",
        ]
        for row in query_result.results:
            lines.append(f"- {row['note_path']} :: {row['snippet']}")
        lines.extend(["", "## SYNTHESIZED"])
        for item in synthesized or ["- Not enough overlap yet."]:
            lines.append(item if item.startswith("- ") else f"- {item}")
        lines.extend(["", "## OPEN QUESTION"])
        for item in open_questions:
            lines.append(item if item.startswith("- ") else f"- {item}")
        artifact.write_text("\n".join(lines), encoding="utf-8")
        artifact_path = str(artifact)

    return SynthesisResult(
        generated_at=generated_at,
        query=query,
        verified=query_result.results,
        synthesized=synthesized,
        open_questions=open_questions,
        artifact_path=artifact_path,
    )
