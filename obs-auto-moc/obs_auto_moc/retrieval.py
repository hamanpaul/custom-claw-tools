from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .engine import (
    index_note_file,
    iter_allowed_note_files,
    now_iso,
    parse_markdown_text,
    parse_iso_datetime,
    resolve_paths,
)
from .memory_ledger import load_memory_snapshot, resolve_memory_ledger_paths


@dataclass
class MemoryQueryResult:
    generated_at: str
    query: str
    result_count: int
    memory_root: Path
    results: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "query": self.query,
            "result_count": self.result_count,
            "memory_root": str(self.memory_root),
            "results": self.results,
        }


def _tokenize(query: str) -> list[str]:
    tokens = [token.strip().casefold() for token in re.findall(r"[\w\u4e00-\u9fff-]+", query, flags=re.UNICODE)]
    return [token for token in tokens if token]


def _load_note_rows(vault_path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for note_file in iter_allowed_note_files(vault_path):
        note = index_note_file(note_file, relative_to=vault_path)
        text = note_file.read_text(encoding="utf-8", errors="replace")
        parsed = parse_markdown_text(text)
        body = parsed.body if parsed.has_frontmatter else text
        rows.append(
            {
                "note": note,
                "body": body,
                "text": text,
            }
        )
    return rows


def query_memory(
    *,
    query: str,
    sync_root: Path | None = None,
    vault_path: Path | None = None,
    artifacts_root: Path | None = None,
    generated_at: str | None = None,
    limit: int = 10,
) -> MemoryQueryResult:
    if not query.strip():
        raise RuntimeError("query must not be empty")

    effective_at = generated_at or now_iso()
    paths = resolve_paths(sync_root=sync_root, vault_path=vault_path, artifacts_root=artifacts_root, generated_at=effective_at)
    ledger = load_memory_snapshot(paths.artifacts_root)
    note_facts_by_path = {row["note_path"]: row for row in ledger["note_facts"] if isinstance(row, dict) and row.get("note_path")}
    tokens = _tokenize(query)
    lower_query = query.casefold()
    matches: list[dict[str, Any]] = []

    for row in _load_note_rows(paths.vault_path):
        note = row["note"]
        body = row["body"]
        text = row["text"]
        fact = note_facts_by_path.get(note.relative_path, {})
        matched_fields: set[str] = set()
        score = 0

        title = note.title.casefold()
        note_name = note.note_name.casefold()
        tags = [tag.casefold() for tag in note.tags]
        aliases = [alias.casefold() for alias in note.aliases]
        body_lower = body.casefold()
        related = [item.casefold() for item in note.related]
        entities = [item.casefold() for item in fact.get("entities") or []]
        claims = [item.casefold() for item in (fact.get("claims") or [])]
        decisions = [item.casefold() for item in (fact.get("decisions") or [])]
        goals = [item.casefold() for item in (fact.get("goals") or [])]
        heuristics = [item.casefold() for item in (fact.get("heuristics") or [])]

        if lower_query in title or lower_query in note_name:
            score += 20
            matched_fields.add("title")
        if lower_query in body_lower:
            score += 10
            matched_fields.add("body")
        if any(lower_query in value for value in tags + aliases):
            score += 8
            matched_fields.add("tags")
        if any(lower_query in value for value in entities + claims + decisions + goals + heuristics):
            score += 12
            matched_fields.add("ledger")
        if any(lower_query in value for value in related):
            score += 4
            matched_fields.add("related")

        for token in tokens:
            if token in title or token in note_name:
                score += 6
                matched_fields.add("title")
            if any(token in value for value in tags + aliases):
                score += 5
                matched_fields.add("tags")
            if any(token in value for value in entities):
                score += 5
                matched_fields.add("entities")
            if any(token in value for value in claims + decisions + goals + heuristics):
                score += 4
                matched_fields.add("ledger")
            if token in body_lower:
                score += 2
                matched_fields.add("body")
            if any(token in value for value in related):
                score += 1
                matched_fields.add("related")

        if score <= 0:
            continue

        snippet = next((line.strip() for line in body.splitlines() if line.strip() and any(token in line.casefold() for token in tokens)), "")
        if not snippet:
            snippet = next((line.strip() for line in body.splitlines() if line.strip()), "")

        recency = parse_iso_datetime(note.last_resonated_at) or parse_iso_datetime(note.updated_at)
        matches.append(
            {
                "note_path": note.relative_path,
                "title": note.title,
                "vault": note.top_level,
                "score": score + (1 if recency else 0),
                "matched_fields": sorted(matched_fields),
                "snippet": snippet[:240],
                "entities": fact.get("entities") or [],
                "source_refs": fact.get("source_refs") or [],
                "related_note_paths": fact.get("related_note_paths") or note.related,
                "updated_at": note.updated_at,
                "last_resonated_at": note.last_resonated_at,
                "tags": note.tags,
            }
        )

    matches.sort(key=lambda row: (-row["score"], row["note_path"]))
    limited = matches[: max(1, limit)]
    memory_paths = resolve_memory_ledger_paths(paths.artifacts_root)
    return MemoryQueryResult(
        generated_at=effective_at,
        query=query,
        result_count=len(limited),
        memory_root=memory_paths.root,
        results=limited,
    )
