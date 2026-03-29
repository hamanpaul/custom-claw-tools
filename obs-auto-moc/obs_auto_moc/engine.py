from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

import yaml

FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
WIKILINK_RE = re.compile(r"!?\[\[([^\]]+)\]\]")
REQUIRED_FIELDS = ("tags",)
SUGGESTED_FIELDS = ("updated_at", "status", "moc_targets")
UNTAGGED_LABEL = "_untagged"


@dataclass
class ParsedMarkdown:
    frontmatter: dict[str, Any]
    body: str
    has_frontmatter: bool
    parse_error: str | None
    duplicate_frontmatter: bool


@dataclass
class IndexedNote:
    relative_path: str
    top_level: str
    note_name: str
    title: str
    tags: list[str]
    aliases: list[str]
    moc_targets: list[str]
    status: str | None
    updated_at: str | None
    atomized_from: str | None
    has_frontmatter: bool
    parse_error: str | None
    duplicate_frontmatter: bool
    missing_required_fields: list[str]
    missing_suggested_fields: list[str]
    outbound_links: list[str]
    resolved_outbound: list[str] = field(default_factory=list)
    unresolved_links: list[str] = field(default_factory=list)
    ambiguous_links: list[str] = field(default_factory=list)
    inbound_count: int = 0
    hub_score: int = 0
    is_orphan: bool = False

    def display_groups(self) -> list[str]:
        groups = self.moc_targets or self.tags
        if not groups:
            return [UNTAGGED_LABEL]
        return unique_preserving_order(groups)

    def wikilink_label(self) -> str:
        return self.title if self.title and self.title != self.note_name else self.note_name

    def manifest_row(self) -> dict[str, Any]:
        row = asdict(self)
        row["display_groups"] = self.display_groups()
        return row


@dataclass
class BuildPaths:
    vault_path: Path
    artifacts_root: Path
    proposal_path: Path
    preview_path: Path
    manifest_path: Path
    last_run_path: Path
    output_moc_path: Path
    sync_config_path: Path | None


@dataclass
class BuildResult:
    generated_at: str
    paths: BuildPaths
    notes_scanned: int
    parse_errors: int
    duplicate_frontmatter_notes: int
    missing_schema_notes: int
    orphan_notes: int
    unresolved_links: int
    ambiguous_links: int
    hub_candidates: list[str]
    applied: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "vault_path": str(self.paths.vault_path),
            "artifacts_root": str(self.paths.artifacts_root),
            "proposal_path": str(self.paths.proposal_path),
            "preview_path": str(self.paths.preview_path),
            "manifest_path": str(self.paths.manifest_path),
            "last_run_path": str(self.paths.last_run_path),
            "output_moc_path": str(self.paths.output_moc_path),
            "sync_config_path": str(self.paths.sync_config_path) if self.paths.sync_config_path else None,
            "notes_scanned": self.notes_scanned,
            "parse_errors": self.parse_errors,
            "duplicate_frontmatter_notes": self.duplicate_frontmatter_notes,
            "missing_schema_notes": self.missing_schema_notes,
            "orphan_notes": self.orphan_notes,
            "unresolved_links": self.unresolved_links,
            "ambiguous_links": self.ambiguous_links,
            "hub_candidates": self.hub_candidates,
            "applied": self.applied,
        }


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def unique_preserving_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = value.strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        result.append(cleaned)
    return result


def normalize_scalar(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    return str(value)


def normalize_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned:
            return []
        if cleaned.startswith("[") and cleaned.endswith("]"):
            try:
                parsed = yaml.safe_load(cleaned)
            except yaml.YAMLError:
                return [cleaned]
            if isinstance(parsed, list):
                return unique_preserving_order([normalize_scalar(item) or "" for item in parsed])
        return [cleaned]
    if isinstance(value, list):
        return unique_preserving_order([normalize_scalar(item) or "" for item in value])
    return [normalize_scalar(value) or ""]


def safe_heading(label: str) -> str:
    stripped = label.strip()
    while stripped.startswith("#"):
        stripped = stripped[1:].strip()
    return stripped or UNTAGGED_LABEL


def parse_markdown_text(text: str) -> ParsedMarkdown:
    match = FRONTMATTER_RE.match(text)
    if not match:
        return ParsedMarkdown(frontmatter={}, body=text, has_frontmatter=False, parse_error=None, duplicate_frontmatter=False)

    raw = match.group(1)
    body = text[match.end() :]
    duplicate_frontmatter = body.startswith("---\n") or body.startswith("---\r\n")
    try:
        parsed = yaml.safe_load(raw) or {}
    except yaml.YAMLError as exc:
        return ParsedMarkdown(
            frontmatter={},
            body=body,
            has_frontmatter=True,
            parse_error=f"yaml_parse_error:{exc.__class__.__name__}",
            duplicate_frontmatter=duplicate_frontmatter,
        )

    if not isinstance(parsed, dict):
        return ParsedMarkdown(
            frontmatter={},
            body=body,
            has_frontmatter=True,
            parse_error="frontmatter_not_mapping",
            duplicate_frontmatter=duplicate_frontmatter,
        )

    return ParsedMarkdown(
        frontmatter=parsed,
        body=body,
        has_frontmatter=True,
        parse_error=None,
        duplicate_frontmatter=duplicate_frontmatter,
    )


def extract_wikilinks(text: str) -> list[str]:
    links: list[str] = []
    for raw_target in WIKILINK_RE.findall(text):
        target = raw_target.split("|", 1)[0].split("#", 1)[0].strip()
        if not target:
            continue
        leaf = Path(target).name.strip()
        if leaf:
            links.append(leaf)
    return unique_preserving_order(links)


def normalize_link_key(value: str) -> str:
    return value.strip().casefold()


def resolve_sync_config(sync_root: Path) -> tuple[Path, Path]:
    files = sorted(sync_root.expanduser().glob("*/config.json"))
    if len(files) != 1:
        raise RuntimeError(f"expected exactly one sync config under {sync_root}, found {len(files)}")
    config_path = files[0]
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid sync config JSON: {config_path}: {exc}") from exc
    vault_path = normalize_scalar(data.get("vaultPath"))
    if not vault_path:
        raise RuntimeError(f"missing vaultPath in sync config: {config_path}")
    return config_path, Path(vault_path).expanduser()


def resolve_paths(
    *,
    sync_root: Path | None = None,
    vault_path: Path | None = None,
    artifacts_root: Path | None = None,
    output_moc_path: Path | None = None,
    proposal_name: str | None = None,
    generated_at: str | None = None,
) -> BuildPaths:
    config_path: Path | None = None
    if vault_path is None:
        if sync_root is None:
            sync_root = Path("~/.config/obsidian-headless/sync")
        config_path, vault_path = resolve_sync_config(sync_root)
    else:
        vault_path = vault_path.expanduser()

    assert vault_path is not None
    if artifacts_root is None:
        artifacts_root = vault_path / "claw" / "moc"
    if output_moc_path is None:
        output_moc_path = vault_path / "MOC.md"

    stamp = (generated_at or now_iso())[:10]
    proposal_file = proposal_name or f"{stamp}-moc-proposal.md"
    return BuildPaths(
        vault_path=vault_path,
        artifacts_root=artifacts_root,
        proposal_path=artifacts_root / "proposals" / proposal_file,
        preview_path=artifacts_root / "MOC.preview.md",
        manifest_path=artifacts_root / "index-manifest.jsonl",
        last_run_path=artifacts_root / "last-run.json",
        output_moc_path=output_moc_path,
        sync_config_path=config_path,
    )


def should_skip(path: Path, vault_path: Path, artifacts_root: Path, output_moc_path: Path) -> bool:
    relative = path.relative_to(vault_path)
    if path == output_moc_path:
        return True
    if any(part == ".obsidian" for part in relative.parts):
        return True
    if artifacts_root == path or artifacts_root in path.parents:
        return True
    return False


def scan_notes(vault_path: Path, artifacts_root: Path, output_moc_path: Path) -> list[IndexedNote]:
    notes: list[IndexedNote] = []
    for path in sorted(vault_path.rglob("*.md")):
        if should_skip(path, vault_path, artifacts_root, output_moc_path):
            continue

        text = path.read_text(encoding="utf-8", errors="replace")
        parsed = parse_markdown_text(text)
        frontmatter = parsed.frontmatter
        relative_path = str(path.relative_to(vault_path))
        top_level = path.relative_to(vault_path).parts[0] if len(path.relative_to(vault_path).parts) > 1 else "_root"
        note_name = path.stem
        title = normalize_scalar(frontmatter.get("title")) or note_name
        tags = normalize_list(frontmatter.get("tags"))
        aliases = normalize_list(frontmatter.get("aliases"))
        moc_targets = normalize_list(frontmatter.get("moc_targets") or frontmatter.get("moc-targets"))
        status = normalize_scalar(frontmatter.get("status"))
        updated_at = normalize_scalar(frontmatter.get("updated_at") or frontmatter.get("updated"))
        atomized_from = normalize_scalar(frontmatter.get("atomized_from"))
        missing_required_fields = [field for field in REQUIRED_FIELDS if field not in frontmatter]
        missing_suggested_fields = [field for field in SUGGESTED_FIELDS if field not in frontmatter]
        notes.append(
            IndexedNote(
                relative_path=relative_path,
                top_level=top_level,
                note_name=note_name,
                title=title,
                tags=tags,
                aliases=aliases,
                moc_targets=moc_targets,
                status=status,
                updated_at=updated_at,
                atomized_from=atomized_from,
                has_frontmatter=parsed.has_frontmatter,
                parse_error=parsed.parse_error,
                duplicate_frontmatter=parsed.duplicate_frontmatter,
                missing_required_fields=missing_required_fields,
                missing_suggested_fields=missing_suggested_fields,
                outbound_links=extract_wikilinks(parsed.body),
            )
        )

    resolve_links(notes)
    return notes


def resolve_links(notes: list[IndexedNote]) -> None:
    stem_index: dict[str, list[IndexedNote]] = defaultdict(list)
    for note in notes:
        stem_index[normalize_link_key(note.note_name)].append(note)
        for alias in note.aliases:
            stem_index[normalize_link_key(alias)].append(note)

    for note in notes:
        resolved_targets: list[str] = []
        unresolved: list[str] = []
        ambiguous: list[str] = []
        for target in note.outbound_links:
            candidates = unique_note_candidates(stem_index.get(normalize_link_key(target), []))
            if not candidates:
                unresolved.append(target)
                continue
            if len(candidates) > 1:
                ambiguous.append(target)
                continue
            resolved = candidates[0]
            resolved.inbound_count += 1
            resolved_targets.append(resolved.relative_path)

        note.resolved_outbound = unique_preserving_order(resolved_targets)
        note.unresolved_links = unique_preserving_order(unresolved)
        note.ambiguous_links = unique_preserving_order(ambiguous)
        note.hub_score = note.inbound_count * 2 + len(note.resolved_outbound) + len(note.display_groups())
        note.is_orphan = note.inbound_count == 0 and len(note.resolved_outbound) == 0


def unique_note_candidates(candidates: list[IndexedNote]) -> list[IndexedNote]:
    unique: dict[str, IndexedNote] = {}
    for candidate in candidates:
        unique[candidate.relative_path] = candidate
    return list(unique.values())


def render_preview(notes: list[IndexedNote], generated_at: str) -> str:
    by_section: dict[str, dict[str, list[IndexedNote]]] = defaultdict(lambda: defaultdict(list))
    section_counts: dict[str, set[str]] = defaultdict(set)

    for note in notes:
        section_counts[note.top_level].add(note.relative_path)
        for group in note.display_groups():
            by_section[note.top_level][safe_heading(group)].append(note)

    lines = [
        "---",
        'title: "Map of Content"',
        f"generated: {generated_at}",
        "generator: obs-auto-moc",
        "mode: preview",
        "---",
        "",
        "# Map of Content",
        "",
        "> 此文件由 `obs-auto-moc` 自動產生。請優先 review proposal，只有明確 apply 才會覆寫 live MOC。",
        "",
    ]

    for section in sorted(by_section.keys(), key=lambda item: (item == "_root", item.lower())):
        section_label = "root" if section == "_root" else section
        lines.append(f"## {section_label} ({len(section_counts[section])})")
        lines.append("")
        groups = by_section[section]
        for group_name, grouped_notes in sorted(groups.items(), key=lambda item: (-len(item[1]), item[0].lower())):
            lines.append(f"### {group_name} ({len(grouped_notes)})")
            lines.append("")
            for note in sorted(grouped_notes, key=lambda item: item.note_name.lower()):
                suffix = f" (atomized_from: [[{note.atomized_from}]])" if note.atomized_from else ""
                lines.append(f"- [[{note.wikilink_label()}]]{suffix}")
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def render_proposal(notes: list[IndexedNote], result: BuildResult) -> str:
    missing_required = [note for note in notes if note.missing_required_fields]
    suggested_field_counts: dict[str, int] = {field: 0 for field in SUGGESTED_FIELDS}
    for note in notes:
        for field in note.missing_suggested_fields:
            suggested_field_counts[field] += 1
    parse_errors = [note for note in notes if note.parse_error]
    duplicate_frontmatter = [note for note in notes if note.duplicate_frontmatter]
    orphans = sorted([note for note in notes if note.is_orphan], key=lambda item: item.relative_path.lower())
    hubs = sorted(notes, key=lambda item: (-item.hub_score, item.relative_path.lower()))[:20]
    unresolved = [note for note in notes if note.unresolved_links or note.ambiguous_links]
    top_levels = defaultdict(int)
    for note in notes:
        top_levels[note.top_level] += 1

    lines = [
        f"# Obsidian MOC Proposal ({result.generated_at})",
        "",
        "## Summary",
        "",
        f"- vault path: `{result.paths.vault_path}`",
        f"- artifacts root: `{result.paths.artifacts_root}`",
        f"- preview path: `{result.paths.preview_path}`",
        f"- live MOC path: `{result.paths.output_moc_path}`",
        f"- notes scanned: `{result.notes_scanned}`",
        f"- parse errors: `{result.parse_errors}`",
        f"- duplicate frontmatter notes: `{result.duplicate_frontmatter_notes}`",
        f"- missing schema notes: `{result.missing_schema_notes}`",
        f"- orphan notes: `{result.orphan_notes}`",
        f"- unresolved links: `{result.unresolved_links}`",
        f"- ambiguous links: `{result.ambiguous_links}`",
        f"- apply mode: `{str(result.applied).lower()}`",
        "",
        "## Top-level note counts",
        "",
    ]

    for section, count in sorted(top_levels.items(), key=lambda item: (-item[1], item[0].lower())):
        label = "root" if section == "_root" else section
        lines.append(f"- `{label}`: {count}")

    lines.extend(["", "## Issues to review", ""])

    if parse_errors:
        lines.append("### Frontmatter parse errors")
        lines.append("")
        for note in parse_errors[:30]:
            lines.append(f"- `{note.relative_path}`: `{note.parse_error}`")
        lines.append("")

    if duplicate_frontmatter:
        lines.append("### Duplicate frontmatter blocks")
        lines.append("")
        for note in duplicate_frontmatter[:30]:
            lines.append(f"- `{note.relative_path}`")
        lines.append("")

    if missing_required:
        lines.append("### Missing required fields")
        lines.append("")
        for note in missing_required[:30]:
            lines.append(f"- `{note.relative_path}`: {', '.join(note.missing_required_fields)}")
        lines.append("")

    lines.append("### Suggested field coverage gaps")
    lines.append("")
    for field, count in suggested_field_counts.items():
        lines.append(f"- `{field}` missing in {count} notes")
    lines.append("")

    if orphans:
        lines.append("### Orphan notes")
        lines.append("")
        for note in orphans[:30]:
            lines.append(f"- `{note.relative_path}`")
        lines.append("")

    if unresolved:
        lines.append("### Link resolution warnings")
        lines.append("")
        for note in unresolved[:30]:
            parts: list[str] = []
            if note.unresolved_links:
                parts.append(f"unresolved={note.unresolved_links}")
            if note.ambiguous_links:
                parts.append(f"ambiguous={note.ambiguous_links}")
            lines.append(f"- `{note.relative_path}`: {'; '.join(parts)}")
        lines.append("")

    lines.extend(["## Hub candidates", ""])
    for note in hubs[:20]:
        lines.append(
            f"- `{note.relative_path}`: score={note.hub_score}, inbound={note.inbound_count}, outbound={len(note.resolved_outbound)}, groups={note.display_groups()}"
        )

    lines.extend(
        [
            "",
            "## Suggested workflow",
            "",
            "1. Read this proposal and `MOC.preview.md` first.",
            "2. Fix malformed frontmatter or unresolved links if they matter to the current review.",
            "3. Only run `build --apply` when you explicitly want to update the live `notes/MOC.md`.",
            "",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(content)
        temp_path = Path(handle.name)
    temp_path.replace(path)


def write_manifest(path: Path, notes: list[IndexedNote]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [json.dumps(note.manifest_row(), ensure_ascii=False, sort_keys=True) for note in notes]
    atomic_write(path, "\n".join(rows) + ("\n" if rows else ""))


def build_workspace(
    *,
    sync_root: Path | None = None,
    vault_path: Path | None = None,
    artifacts_root: Path | None = None,
    output_moc_path: Path | None = None,
    generated_at: str | None = None,
    apply: bool = False,
) -> BuildResult:
    generated = generated_at or now_iso()
    paths = resolve_paths(
        sync_root=sync_root,
        vault_path=vault_path,
        artifacts_root=artifacts_root,
        output_moc_path=output_moc_path,
        generated_at=generated,
    )

    notes = scan_notes(paths.vault_path, paths.artifacts_root, paths.output_moc_path)
    preview = render_preview(notes, generated)
    hub_candidates = [note.relative_path for note in sorted(notes, key=lambda item: (-item.hub_score, item.relative_path.lower()))[:10]]

    result = BuildResult(
        generated_at=generated,
        paths=paths,
        notes_scanned=len(notes),
        parse_errors=sum(1 for note in notes if note.parse_error),
        duplicate_frontmatter_notes=sum(1 for note in notes if note.duplicate_frontmatter),
        missing_schema_notes=sum(1 for note in notes if note.missing_required_fields),
        orphan_notes=sum(1 for note in notes if note.is_orphan),
        unresolved_links=sum(len(note.unresolved_links) for note in notes),
        ambiguous_links=sum(len(note.ambiguous_links) for note in notes),
        hub_candidates=hub_candidates,
        applied=apply,
    )
    proposal = render_proposal(notes, result)

    write_manifest(paths.manifest_path, notes)
    atomic_write(paths.preview_path, preview)
    atomic_write(paths.proposal_path, proposal)
    if apply:
        atomic_write(paths.output_moc_path, preview.replace("mode: preview", "mode: apply", 1))
    atomic_write(paths.last_run_path, json.dumps(result.to_dict(), ensure_ascii=False, indent=2) + "\n")
    return result


def load_last_run(last_run_path: Path) -> dict[str, Any]:
    return json.loads(last_run_path.read_text(encoding="utf-8"))
