from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .engine import (
    atomic_write,
    normalize_list,
    normalize_related_links,
    normalize_scalar,
    note_reference_link,
    parse_markdown_text,
    render_markdown,
    unique_preserving_order,
)

REQUIRED_MEMORY_SECTIONS = (
    "Compiled Truth",
    "Timeline",
    "Sources",
    "Related",
)

SECTION_PLACEHOLDERS = {
    "Compiled Truth": "- Pending curation.\n",
    "Timeline": "- Pending event extraction.\n",
    "Sources": "- Pending source trace.\n",
    "Related": "- Pending related note mapping.\n",
}


@dataclass
class NoteContractStatus:
    note_path: str
    destination_vault: str
    source_refs: list[str]
    sections_present: list[str]
    sections_added: list[str]
    entities: list[str]
    goals: list[str]
    heuristics: list[str]
    related_note_paths: list[str]
    updated: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "note_path": self.note_path,
            "destination_vault": self.destination_vault,
            "source_refs": self.source_refs,
            "sections_present": self.sections_present,
            "sections_added": self.sections_added,
            "entities": self.entities,
            "goals": self.goals,
            "heuristics": self.heuristics,
            "related_note_paths": self.related_note_paths,
            "updated": self.updated,
        }


def _has_heading(body: str, heading: str) -> bool:
    pattern = re.compile(rf"(?mi)^\s{{0,3}}##+\s+{re.escape(heading)}\s*$")
    return bool(pattern.search(body))


def _append_missing_sections(body: str, headings: list[str]) -> tuple[str, list[str]]:
    if not headings:
        return body, []
    normalized = body.rstrip()
    chunks = [normalized] if normalized else []
    added: list[str] = []
    for heading in headings:
        chunks.append(f"## {heading}\n\n{SECTION_PLACEHOLDERS[heading].rstrip()}")
        added.append(heading)
    return "\n\n".join(chunks).rstrip() + "\n", added


def inspect_memory_note(note_path: str, text: str) -> dict[str, Any]:
    parsed = parse_markdown_text(text)
    body = parsed.body if parsed.has_frontmatter else text
    sections_present = [heading for heading in REQUIRED_MEMORY_SECTIONS if _has_heading(body, heading)]
    return {
        "note_path": note_path,
        "frontmatter": parsed.frontmatter,
        "body": body,
        "has_frontmatter": parsed.has_frontmatter,
        "sections_present": sections_present,
        "missing_sections": [heading for heading in REQUIRED_MEMORY_SECTIONS if heading not in sections_present],
    }


def ensure_memory_note_contract(
    *,
    note_file: Path,
    note_path: str,
    destination_vault: str,
    source_refs: list[str],
    compiled_at: str,
    event_time: str | None = None,
    entities: list[str] | None = None,
    related_note_paths: list[str] | None = None,
    goals: list[str] | None = None,
    heuristics: list[str] | None = None,
) -> NoteContractStatus:
    text = note_file.read_text(encoding="utf-8", errors="replace")
    inspection = inspect_memory_note(note_path, text)
    frontmatter = dict(inspection["frontmatter"])
    body = inspection["body"]

    changed = False

    existing_type = normalize_scalar(frontmatter.get("type"))
    if existing_type is None:
        frontmatter["type"] = "memory-note"
        changed = True

    if normalize_scalar(frontmatter.get("vault")) != destination_vault:
        frontmatter["vault"] = destination_vault
        changed = True

    normalized_source_refs = unique_preserving_order(normalize_list(frontmatter.get("source_refs")) + source_refs)
    if normalize_list(frontmatter.get("source_refs")) != normalized_source_refs:
        frontmatter["source_refs"] = normalized_source_refs
        changed = True

    if normalize_scalar(frontmatter.get("last_compiled_at")) != compiled_at:
        frontmatter["last_compiled_at"] = compiled_at
        changed = True

    if event_time and normalize_scalar(frontmatter.get("last_event_at")) != event_time:
        frontmatter["last_event_at"] = event_time
        changed = True

    normalized_entities = unique_preserving_order(normalize_list(frontmatter.get("entities")) + (entities or []))
    if normalize_list(frontmatter.get("entities")) != normalized_entities and normalized_entities:
        frontmatter["entities"] = normalized_entities
        changed = True

    normalized_goals = unique_preserving_order(normalize_list(frontmatter.get("goals")) + (goals or []))
    if normalize_list(frontmatter.get("goals")) != normalized_goals and normalized_goals:
        frontmatter["goals"] = normalized_goals
        changed = True

    normalized_heuristics = unique_preserving_order(normalize_list(frontmatter.get("heuristics")) + (heuristics or []))
    if normalize_list(frontmatter.get("heuristics")) != normalized_heuristics and normalized_heuristics:
        frontmatter["heuristics"] = normalized_heuristics
        changed = True

    existing_related = normalize_related_links(frontmatter.get("related"))
    merged_related = unique_preserving_order(
        existing_related + [note_reference_link(path) for path in related_note_paths or [] if path != note_path]
    )
    if existing_related != merged_related and merged_related:
        frontmatter["related"] = merged_related
        changed = True

    updated_body, sections_added = _append_missing_sections(body, inspection["missing_sections"])
    if sections_added:
        body = updated_body
        changed = True

    rendered = render_markdown(frontmatter, body)
    if changed and rendered != text:
        atomic_write(note_file, rendered)

    return NoteContractStatus(
        note_path=note_path,
        destination_vault=destination_vault,
        source_refs=normalized_source_refs,
        sections_present=inspection["sections_present"] + sections_added,
        sections_added=sections_added,
        entities=normalized_entities,
        goals=normalized_goals,
        heuristics=normalized_heuristics,
        related_note_paths=[path for path in related_note_paths or [] if path != note_path],
        updated=changed and rendered != text,
    )
