from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from .engine import normalize_list, normalize_scalar, parse_markdown_text, unique_preserving_order


@dataclass
class MemoryLedgerPaths:
    root: Path
    entities_path: Path
    relations_path: Path
    events_path: Path
    citations_path: Path
    note_facts_path: Path
    contradictions_path: Path
    health_root: Path
    wakeup_root: Path
    dream_root: Path
    persona_root: Path
    synthesis_root: Path
    health_summary_path: Path


def resolve_memory_ledger_paths(artifacts_root: Path) -> MemoryLedgerPaths:
    root = artifacts_root / "memory"
    return MemoryLedgerPaths(
        root=root,
        entities_path=root / "entities.jsonl",
        relations_path=root / "relations.jsonl",
        events_path=root / "events.jsonl",
        citations_path=root / "citations.jsonl",
        note_facts_path=root / "note-facts.jsonl",
        contradictions_path=root / "contradictions.jsonl",
        health_root=root / "health",
        wakeup_root=root / "wake-up",
        dream_root=root / "dream",
        persona_root=root / "persona",
        synthesis_root=root / "synthesis",
        health_summary_path=root / "health" / "ledger-summary.json",
    )


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _stable_hash(payload: str) -> str:
    return sha256(payload.encode("utf-8")).hexdigest()[:16]


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rows.append(json.loads(line))
    return rows


def upsert_jsonl(path: Path, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    existing = {row["record_key"]: row for row in read_jsonl(path) if isinstance(row, dict) and row.get("record_key")}
    for row in rows:
        record_key = normalize_scalar(row.get("record_key"))
        if not record_key:
            raise RuntimeError(f"memory ledger row missing record_key for {path}")
        existing[record_key] = row
    _ensure_parent(path)
    ordered_rows = sorted(existing.values(), key=lambda row: str(row["record_key"]))
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in ordered_rows) + "\n",
        encoding="utf-8",
    )
    return len(rows)


def load_memory_snapshot(artifacts_root: Path) -> dict[str, Any]:
    paths = resolve_memory_ledger_paths(artifacts_root)
    return {
        "paths": {
            "root": str(paths.root),
            "entities": str(paths.entities_path),
            "relations": str(paths.relations_path),
            "events": str(paths.events_path),
            "citations": str(paths.citations_path),
            "note_facts": str(paths.note_facts_path),
            "contradictions": str(paths.contradictions_path),
            "health_summary": str(paths.health_summary_path),
        },
        "entities": read_jsonl(paths.entities_path),
        "relations": read_jsonl(paths.relations_path),
        "events": read_jsonl(paths.events_path),
        "citations": read_jsonl(paths.citations_path),
        "note_facts": read_jsonl(paths.note_facts_path),
        "contradictions": read_jsonl(paths.contradictions_path),
    }


def _note_keywords(text: str) -> list[str]:
    parsed = parse_markdown_text(text)
    body = parsed.body if parsed.has_frontmatter else text
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    return lines[:8]


def update_memory_ledger(
    *,
    artifacts_root: Path,
    report: dict[str, Any],
    applied_entries: list[dict[str, Any]],
    note_contracts: list[dict[str, Any]],
) -> dict[str, Any]:
    paths = resolve_memory_ledger_paths(artifacts_root)
    for directory in (
        paths.root,
        paths.health_root,
        paths.wakeup_root,
        paths.dream_root,
        paths.persona_root,
        paths.synthesis_root,
    ):
        directory.mkdir(parents=True, exist_ok=True)

    contracts_by_note = {contract["note_path"]: contract for contract in note_contracts}

    entity_rows: list[dict[str, Any]] = []
    relation_rows: list[dict[str, Any]] = []
    event_rows: list[dict[str, Any]] = []
    citation_rows: list[dict[str, Any]] = []
    fact_rows: list[dict[str, Any]] = []
    contradiction_rows: list[dict[str, Any]] = []

    for entry in applied_entries:
        output_note_paths = [output["note_path"] for output in entry.get("outputs") or []]
        output_vaults = unique_preserving_order([output["destination_vault"] for output in entry.get("outputs") or []])
        event_time = normalize_scalar(entry.get("event_time")) or report["completed_at"]
        event_key = f"{report['job_id']}::{entry['source_path']}"
        event_rows.append(
            {
                "record_key": event_key,
                "job_id": report["job_id"],
                "reported_by": report["reported_by"],
                "source_path": entry["source_path"],
                "status": entry["status"],
                "event_time": event_time,
                "completed_at": report["completed_at"],
                "output_note_paths": output_note_paths,
                "output_vaults": output_vaults,
                "warnings": entry.get("warnings") or [],
            }
        )

        raw_entities = unique_preserving_order(
            normalize_list(entry.get("entities"))
            + [contract_entity for note_path in output_note_paths for contract_entity in contracts_by_note.get(note_path, {}).get("entities", [])]
        )
        for entity in raw_entities:
            entity_rows.append(
                {
                    "record_key": f"{event_key}::entity::{entity.casefold()}",
                    "entity": entity,
                    "job_id": report["job_id"],
                    "source_path": entry["source_path"],
                    "event_time": event_time,
                    "note_paths": output_note_paths,
                }
            )

        for note_path in output_note_paths:
            relation_rows.append(
                {
                    "record_key": f"{entry['source_path']}::atomized_to::{note_path}",
                    "from": entry["source_path"],
                    "to": note_path,
                    "relation_type": "atomized_to",
                    "job_id": report["job_id"],
                    "event_time": event_time,
                }
            )

        for related_note_path in normalize_list(entry.get("related_note_paths")):
            for note_path in output_note_paths or [entry["source_path"]]:
                relation_rows.append(
                    {
                        "record_key": f"{note_path}::related_to::{related_note_path}",
                        "from": note_path,
                        "to": related_note_path,
                        "relation_type": "related_to",
                        "job_id": report["job_id"],
                        "event_time": event_time,
                    }
                )

        for index, citation in enumerate(entry.get("citations") or [], start=1):
            if not isinstance(citation, dict):
                continue
            source_path = normalize_scalar(citation.get("source_path")) or entry["source_path"]
            quote = normalize_scalar(citation.get("quote"))
            locator = normalize_scalar(citation.get("locator"))
            citation_rows.append(
                {
                    "record_key": f"{event_key}::citation::{index}::{_stable_hash((quote or '') + '|' + (locator or ''))}",
                    "job_id": report["job_id"],
                    "source_path": source_path,
                    "note_paths": output_note_paths,
                    "quote": quote,
                    "locator": locator,
                    "kind": normalize_scalar(citation.get("kind")) or "quote",
                    "event_time": event_time,
                }
            )

        for index, contradiction in enumerate(entry.get("contradiction_signals") or [], start=1):
            contradiction_text = normalize_scalar(contradiction)
            if not contradiction_text:
                continue
            contradiction_rows.append(
                {
                    "record_key": f"{event_key}::contradiction::{index}",
                    "job_id": report["job_id"],
                    "source_path": entry["source_path"],
                    "note_paths": output_note_paths,
                    "signal": contradiction_text,
                    "event_time": event_time,
                }
            )

        for note_path in output_note_paths:
            contract = contracts_by_note.get(note_path, {})
            note_file = Path(contract.get("note_file")) if contract.get("note_file") else None
            note_keywords = _note_keywords(note_file.read_text(encoding="utf-8", errors="replace")) if note_file and note_file.exists() else []
            fact_rows.append(
                {
                    "record_key": note_path,
                    "note_path": note_path,
                    "source_path": entry["source_path"],
                    "job_id": report["job_id"],
                    "status": entry["status"],
                    "event_time": event_time,
                    "claims": normalize_list(entry.get("claims")),
                    "decisions": normalize_list(entry.get("decisions")),
                    "open_questions": normalize_list(entry.get("open_questions")),
                    "entities": unique_preserving_order(raw_entities + normalize_list(contract.get("entities"))),
                    "goals": normalize_list(contract.get("goals")),
                    "heuristics": normalize_list(contract.get("heuristics")),
                    "source_refs": normalize_list(contract.get("source_refs")),
                    "related_note_paths": normalize_list(contract.get("related_note_paths")),
                    "keywords": note_keywords,
                    "warnings": entry.get("warnings") or [],
                    "sections_present": normalize_list(contract.get("sections_present")),
                }
            )

            for entity in unique_preserving_order(normalize_list(contract.get("entities"))):
                relation_rows.append(
                    {
                        "record_key": f"{note_path}::mentions_entity::{entity.casefold()}",
                        "from": note_path,
                        "to": entity,
                        "relation_type": "mentions_entity",
                        "job_id": report["job_id"],
                        "event_time": event_time,
                    }
                )

    inserted = {
        "entities": upsert_jsonl(paths.entities_path, entity_rows),
        "relations": upsert_jsonl(paths.relations_path, relation_rows),
        "events": upsert_jsonl(paths.events_path, event_rows),
        "citations": upsert_jsonl(paths.citations_path, citation_rows),
        "note_facts": upsert_jsonl(paths.note_facts_path, fact_rows),
        "contradictions": upsert_jsonl(paths.contradictions_path, contradiction_rows),
    }

    summary = {
        "generated_at": report["completed_at"],
        "job_id": report["job_id"],
        "root": str(paths.root),
        "inserted": inserted,
        "totals": {
            "entities": len(read_jsonl(paths.entities_path)),
            "relations": len(read_jsonl(paths.relations_path)),
            "events": len(read_jsonl(paths.events_path)),
            "citations": len(read_jsonl(paths.citations_path)),
            "note_facts": len(read_jsonl(paths.note_facts_path)),
            "contradictions": len(read_jsonl(paths.contradictions_path)),
        },
        "paths": {
            "entities": str(paths.entities_path),
            "relations": str(paths.relations_path),
            "events": str(paths.events_path),
            "citations": str(paths.citations_path),
            "note_facts": str(paths.note_facts_path),
            "contradictions": str(paths.contradictions_path),
            "health_summary": str(paths.health_summary_path),
        },
    }
    _ensure_parent(paths.health_summary_path)
    paths.health_summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary
