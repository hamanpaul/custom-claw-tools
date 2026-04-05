from __future__ import annotations

import json
import os
import re
import subprocess
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

import yaml

FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
WIKILINK_RE = re.compile(r"!?\[\[([^\]]+)\]\]")
REQUIRED_FIELDS = ("tags",)
SUGGESTED_FIELDS = ("updated_at", "status", "moc_targets")
UNTAGGED_LABEL = "_untagged"
ROOT_NOTE_DIRNAME = "root-note"
DESTINATION_VAULTS = ("TechVault", "WorkVault", "PersonalVault")
PIPELINE_RULESET_NAME = "ObsToolsVault"
PIPELINE_RULESET_SOURCE = "ObsToolsVault/README.md"
REPORT_STATUSES = ("processed", "skipped", "failed")
PIPELINE_CALLBACK_HOST = "127.0.0.1"
PIPELINE_CALLBACK_PORT = 45460
PIPELINE_CALLBACK_PATH = "/picoclaw-report"
PICOCLAW_AUTO_DISPATCH_ENV = "OBS_AUTO_MOC_AUTO_DISPATCH"
PICOCLAW_BIN_ENV = "OBS_AUTO_MOC_PICOCLAW_BIN"
PICOCLAW_SESSION_ENV = "OBS_AUTO_MOC_PICOCLAW_SESSION"
PICOCLAW_TIMEOUT_ENV = "OBS_AUTO_MOC_PICOCLAW_TIMEOUT_S"
PICOCLAW_STALE_HANDOFF_ENV = "OBS_AUTO_MOC_STALE_HANDOFF_SECONDS"
PICOCLAW_DEFAULT_BIN = "/usr/bin/picoclaw"
PICOCLAW_DEFAULT_SESSION = "cron:obs-auto-moc"
PICOCLAW_DEFAULT_TIMEOUT_S = 20 * 60
PICOCLAW_DEFAULT_STALE_HANDOFF_S = 60 * 60
PICOCLAW_REPORT_BEGIN = "PICOCLAW_REPORT_BEGIN"
PICOCLAW_REPORT_END = "PICOCLAW_REPORT_END"
WORK_VAULT_HINTS = (
    "work",
    "meeting",
    "client",
    "customer",
    "company",
    "business",
    "career",
    "project",
    "proposal",
    "sales",
    "marketing",
    "startup",
    "工作",
    "會議",
    "客戶",
    "公司",
    "商務",
    "專案",
    "創業",
)
PERSONAL_VAULT_HINTS = (
    "personal",
    "family",
    "home",
    "health",
    "sleep",
    "diet",
    "fitness",
    "travel",
    "journal",
    "diary",
    "private",
    "finance",
    "生活",
    "家庭",
    "健康",
    "睡眠",
    "飲食",
    "旅遊",
    "日記",
    "私人",
    "理財",
)


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
class RootNotePaths:
    root_note_path: Path
    pipeline_root: Path
    state_path: Path
    handoff_root: Path
    report_inbox_root: Path
    completions_root: Path
    failed_report_root: Path
    status_path: Path


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


@dataclass
class RootNoteMonitorResult:
    generated_at: str
    paths: RootNotePaths
    root_note_exists: bool
    scanned_files: int
    handed_off_files: int
    unchanged_files: int
    job_id: str | None
    handoff_path: Path | None
    ruleset_name: str = PIPELINE_RULESET_NAME
    ruleset_source: str = PIPELINE_RULESET_SOURCE

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "root_note_path": str(self.paths.root_note_path),
            "pipeline_root": str(self.paths.pipeline_root),
            "state_path": str(self.paths.state_path),
            "handoff_root": str(self.paths.handoff_root),
            "status_path": str(self.paths.status_path),
            "root_note_exists": self.root_note_exists,
            "scanned_files": self.scanned_files,
            "handed_off_files": self.handed_off_files,
            "unchanged_files": self.unchanged_files,
            "job_id": self.job_id,
            "handoff_path": str(self.handoff_path) if self.handoff_path else None,
            "ruleset_name": self.ruleset_name,
            "ruleset_source": self.ruleset_source,
        }


@dataclass
class DestinationMocRefreshResult:
    generated_at: str
    vault_path: Path
    destination_mocs: dict[str, str]
    note_counts: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "vault_path": str(self.vault_path),
            "destination_mocs": self.destination_mocs,
            "note_counts": self.note_counts,
        }


@dataclass
class PicoclawReportApplyResult:
    generated_at: str
    job_id: str
    report_path: Path
    archived_report_path: Path
    state_path: Path
    processed_count: int
    skipped_count: int
    failed_count: int
    touched_destination_vaults: list[str]
    destination_mocs: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "job_id": self.job_id,
            "report_path": str(self.report_path),
            "archived_report_path": str(self.archived_report_path),
            "state_path": str(self.state_path),
            "processed_count": self.processed_count,
            "skipped_count": self.skipped_count,
            "failed_count": self.failed_count,
            "touched_destination_vaults": self.touched_destination_vaults,
            "destination_mocs": self.destination_mocs,
        }


@dataclass
class PipelineRunResult:
    generated_at: str
    root_note_path: Path
    report_inbox_root: Path
    reports_discovered: int
    reports_applied: int
    reports_failed: int
    archived_report_paths: list[str]
    failed_report_paths: list[str]
    handoff_job_id: str | None
    handoff_path: str | None
    handed_off_files: int
    unchanged_files: int
    state_path: Path
    dispatch_enabled: bool = False
    dispatch_attempted: int = 0
    dispatch_succeeded: int = 0
    dispatch_failed: int = 0
    dispatched_job_ids: list[str] = field(default_factory=list)
    dispatch_log_paths: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "root_note_path": str(self.root_note_path),
            "report_inbox_root": str(self.report_inbox_root),
            "reports_discovered": self.reports_discovered,
            "reports_applied": self.reports_applied,
            "reports_failed": self.reports_failed,
            "archived_report_paths": self.archived_report_paths,
            "failed_report_paths": self.failed_report_paths,
            "handoff_job_id": self.handoff_job_id,
            "handoff_path": self.handoff_path,
            "handed_off_files": self.handed_off_files,
            "unchanged_files": self.unchanged_files,
            "state_path": str(self.state_path),
            "dispatch_enabled": self.dispatch_enabled,
            "dispatch_attempted": self.dispatch_attempted,
            "dispatch_succeeded": self.dispatch_succeeded,
            "dispatch_failed": self.dispatch_failed,
            "dispatched_job_ids": self.dispatched_job_ids,
            "dispatch_log_paths": self.dispatch_log_paths,
        }


@dataclass
class PicoclawReportQueueResult:
    generated_at: str
    job_id: str
    reported_by: str
    entry_count: int
    report_inbox_root: Path
    queued_report_path: Path
    pipeline_result: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "job_id": self.job_id,
            "reported_by": self.reported_by,
            "entry_count": self.entry_count,
            "report_inbox_root": str(self.report_inbox_root),
            "queued_report_path": str(self.queued_report_path),
            "run_pipeline": self.pipeline_result is not None,
            "pipeline_result": self.pipeline_result,
        }


@dataclass
class PicoclawDispatchResult:
    generated_at: str
    job_id: str
    handoff_path: Path
    queued_report_path: Path
    report_copy_path: Path
    raw_output_log_path: Path
    entry_count: int
    pipeline_result: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "job_id": self.job_id,
            "handoff_path": str(self.handoff_path),
            "queued_report_path": str(self.queued_report_path),
            "report_copy_path": str(self.report_copy_path),
            "raw_output_log_path": str(self.raw_output_log_path),
            "entry_count": self.entry_count,
            "run_pipeline": self.pipeline_result is not None,
            "pipeline_result": self.pipeline_result,
        }


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


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


def fingerprint_text(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


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


def resolve_root_note_paths(
    paths: BuildPaths,
    *,
    root_note_path: Path | None = None,
    pipeline_root: Path | None = None,
) -> RootNotePaths:
    resolved_root_note_path = root_note_path.expanduser() if root_note_path else paths.vault_path / ROOT_NOTE_DIRNAME
    resolved_pipeline_root = pipeline_root.expanduser() if pipeline_root else paths.artifacts_root / "pipeline"
    return RootNotePaths(
        root_note_path=resolved_root_note_path,
        pipeline_root=resolved_pipeline_root,
        state_path=resolved_pipeline_root / "root-note-state.json",
        handoff_root=resolved_pipeline_root / "picoclaw-handoff",
        report_inbox_root=resolved_pipeline_root / "picoclaw-report-inbox",
        completions_root=resolved_pipeline_root / "picoclaw-completions",
        failed_report_root=resolved_pipeline_root / "picoclaw-report-failures",
        status_path=resolved_pipeline_root / "last-pipeline-run.json",
    )


def load_json_file(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def should_skip(path: Path, vault_path: Path, artifacts_root: Path, output_moc_path: Path) -> bool:
    relative = path.relative_to(vault_path)
    if path == output_moc_path:
        return True
    if any(part == ".obsidian" for part in relative.parts):
        return True
    if artifacts_root == path or artifacts_root in path.parents:
        return True
    return False


def should_skip_destination_note(path: Path, destination_root: Path, output_moc_path: Path) -> bool:
    relative = path.relative_to(destination_root)
    if path == output_moc_path:
        return True
    if any(part == ".obsidian" for part in relative.parts):
        return True
    return False


def index_note_file(path: Path, *, relative_to: Path, relative_prefix: str | None = None) -> IndexedNote:
    text = path.read_text(encoding="utf-8", errors="replace")
    parsed = parse_markdown_text(text)
    frontmatter = parsed.frontmatter
    relative_path = path.relative_to(relative_to).as_posix()
    if relative_prefix:
        relative_path = f"{relative_prefix}/{relative_path}"
    relative_parts = path.relative_to(relative_to).parts
    top_level = relative_parts[0] if len(relative_parts) > 1 else "_root"
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
    return IndexedNote(
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


def scan_notes(vault_path: Path, artifacts_root: Path, output_moc_path: Path) -> list[IndexedNote]:
    notes: list[IndexedNote] = []
    for path in sorted(vault_path.rglob("*.md")):
        if should_skip(path, vault_path, artifacts_root, output_moc_path):
            continue
        notes.append(index_note_file(path, relative_to=vault_path))

    resolve_links(notes)
    return notes


def scan_destination_notes(vault_path: Path, destination_vault: str) -> list[IndexedNote]:
    validate_destination_vault(destination_vault)
    destination_root = vault_path / destination_vault
    output_moc_path = destination_root / "MOC.md"
    if not destination_root.exists():
        return []

    notes: list[IndexedNote] = []
    for path in sorted(destination_root.rglob("*.md")):
        if should_skip_destination_note(path, destination_root, output_moc_path):
            continue
        notes.append(index_note_file(path, relative_to=destination_root, relative_prefix=destination_vault))

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


def render_destination_moc(destination_vault: str, notes: list[IndexedNote], generated_at: str) -> str:
    by_section: dict[str, dict[str, list[IndexedNote]]] = defaultdict(lambda: defaultdict(list))
    section_counts: dict[str, set[str]] = defaultdict(set)

    for note in notes:
        section_counts[note.top_level].add(note.relative_path)
        for group in note.display_groups():
            by_section[note.top_level][safe_heading(group)].append(note)

    lines = [
        "---",
        f'title: "{destination_vault} MOC"',
        f"generated: {generated_at}",
        "generator: obs-auto-moc",
        "mode: destination-moc",
        f"destination_vault: {destination_vault}",
        "---",
        "",
        f"# {destination_vault} MOC",
        "",
        "> 此文件由 `obs-auto-moc` 的 root-note pipeline 自動維護。",
        "",
    ]

    if not notes:
        lines.append("_No indexed notes yet._")
        lines.append("")
        return "\n".join(lines).rstrip() + "\n"

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


def write_json_file(path: Path, payload: Any) -> None:
    atomic_write(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def env_flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().casefold() in {"1", "true", "yes", "on"}


def stale_handoff_seconds() -> int:
    value = os.environ.get(PICOCLAW_STALE_HANDOFF_ENV)
    if value is None or not value.strip():
        return PICOCLAW_DEFAULT_STALE_HANDOFF_S
    return int(value)


def extract_json_block(text: str, *, start_marker: str, end_marker: str) -> dict[str, Any]:
    start = text.find(start_marker)
    if start < 0:
        raise RuntimeError(f"missing {start_marker} in PicoClaw output")
    start = text.find("\n", start)
    if start < 0:
        raise RuntimeError(f"missing newline after {start_marker} in PicoClaw output")
    start += 1
    end = text.find(end_marker, start)
    if end < 0:
        raise RuntimeError(f"missing {end_marker} in PicoClaw output")
    block = text[start:end].strip()
    if not block:
        raise RuntimeError("empty PicoClaw JSON report block")
    try:
        payload = json.loads(block)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid PicoClaw JSON report block: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("PicoClaw report block must decode to a JSON object")
    return payload


def build_picoclaw_dispatch_prompt(*, handoff_payload: dict[str, Any], callback_endpoint: str) -> str:
    handoff_json = json.dumps(handoff_payload, ensure_ascii=False, indent=2)
    return (
        "你是 obs-auto-moc Stage 2 agent，負責把 root-note intake 內容依 ObsToolsVault 規則原子化、建立關聯、判斷 tags，"
        "並導向 TechVault / WorkVault / PersonalVault。\n\n"
        "嚴格要求：\n"
        "1. 先閱讀 ruleset.source 指向的規則入口，必要時再補讀同 vault 下的 ObsToolsVault/specs。\n"
        "2. 對每個 processed entry，你必須先在 vault 內實際建立或更新 destination note，再回報結構化結果。\n"
        "3. 只能輸出一個 JSON report block，前後標記必須完全如下，且中間必須是真正可被 json.loads() 解析的 JSON object，"
        "不要輸出 `{...json report...}`、Python dict、code fence 或其他 placeholder：\n"
        f"{PICOCLAW_REPORT_BEGIN}\n"
        '{"job_id":"<job_id>","reported_by":"PicoClaw","completed_at":"<ISO-8601>","entries":[{"source_path":"<root-note path>",'
        '"fingerprint":"<sha256>","status":"processed","outputs":[{"destination_vault":"TechVault","note_path":"TechVault/example.md"}]}]}\n'
        f"{PICOCLAW_REPORT_END}\n"
        "4. 除了該 block 之外，不要輸出其他文字。\n"
        "5. JSON report 必須符合 callback_contract：\n"
        "   - job_id\n"
        "   - reported_by = PicoClaw\n"
        "   - completed_at\n"
        "   - entries[] with source_path, fingerprint, status, outputs\n"
        "6. handoff payload 裡的每一個 entry 都必須在 report entries[] 中剛好出現一次；不能只回部分 entries。\n"
        "7. status 只能是 processed / skipped / failed。\n"
        "8. 只有在 destination note 已經真的存在於 vault 時，才能回 processed；做不到就回 failed 或 skipped。\n"
        "9. processed entries 的 outputs[] 必須列出 destination_vault 與 note_path；note_path 要指向實際已存在的目的筆記。\n"
        "10. 若 entry 不適合導入三個 destination vault，請回 skipped 並把 outputs 留空。\n"
        "11. 你不需要自己 call HTTP callback；只要輸出結構化 JSON report block，由外層 bridge 送到 loopback callback。\n\n"
        f"loopback callback endpoint: {callback_endpoint}\n\n"
        "handoff payload:\n"
        f"{handoff_json}\n"
    )


def build_picoclaw_dispatch_session(base_session: str, job_id: str) -> str:
    if "{job_id}" in base_session:
        return base_session.replace("{job_id}", job_id)
    return f"{base_session}:{job_id}"


def fallback_destination_vaults(entry: dict[str, Any]) -> list[str]:
    explicit_targets = [target for target in normalize_list(entry.get("moc_targets")) if target in DESTINATION_VAULTS]
    if explicit_targets:
        return unique_preserving_order(explicit_targets)

    haystacks = [
        normalize_scalar(entry.get("title")) or "",
        normalize_scalar(entry.get("note_name")) or "",
        normalize_scalar(entry.get("status")) or "",
        normalize_scalar(entry.get("source_path")) or "",
        " ".join(normalize_list(entry.get("tags"))),
        " ".join(normalize_list(entry.get("aliases"))),
        normalize_scalar(entry.get("source_text")) or "",
    ]
    search_text = " ".join(haystacks).casefold()
    if any(keyword in search_text for keyword in PERSONAL_VAULT_HINTS):
        return ["PersonalVault"]
    if any(keyword in search_text for keyword in WORK_VAULT_HINTS):
        return ["WorkVault"]
    return ["TechVault"]


def load_handoff_entry_source_text(entry: dict[str, Any], *, vault_path: Path) -> str:
    source_text = normalize_scalar(entry.get("source_text"))
    if source_text is not None:
        return source_text
    source_path = normalize_scalar(entry.get("source_path"))
    if not source_path:
        raise RuntimeError("handoff entry is missing source_path")
    source_file = (vault_path / source_path).expanduser()
    return source_file.read_text(encoding="utf-8")


def should_use_local_fallback_report(
    report_payload: dict[str, Any],
    *,
    handoff_payload: dict[str, Any],
    vault_path: Path,
) -> str | None:
    job_id = normalize_scalar(handoff_payload.get("job_id"))
    if report_payload.get("job_id") != job_id:
        return f"report job_id {report_payload.get('job_id')!r} did not match handoff job_id {job_id!r}"

    expected_entries = handoff_payload.get("entries")
    if isinstance(expected_entries, list):
        expected_pairs = {
            (normalize_scalar(entry.get("source_path")), normalize_scalar(entry.get("fingerprint")))
            for entry in expected_entries
            if isinstance(entry, dict)
        }
        actual_pairs = {(entry["source_path"], entry["fingerprint"]) for entry in report_payload["entries"]}
        if actual_pairs != expected_pairs:
            return "report entries did not match handoff entries"

    for entry in report_payload["entries"]:
        if entry["status"] != "processed":
            continue
        for output in entry["outputs"]:
            destination_note = resolve_destination_note_file(
                vault_path,
                output["destination_vault"],
                output["note_path"],
            )
            if not destination_note.exists():
                return f"processed report referenced missing destination note: {output['note_path']}"
    return None


def build_local_fallback_report(
    handoff_payload: dict[str, Any],
    *,
    vault_path: Path,
    fallback_reason: str,
) -> dict[str, Any]:
    job_id = normalize_scalar(handoff_payload.get("job_id"))
    if not job_id:
        raise RuntimeError("handoff payload must include job_id for local fallback")
    raw_entries = handoff_payload.get("entries")
    if not isinstance(raw_entries, list) or not raw_entries:
        raise RuntimeError("handoff payload must include non-empty entries for local fallback")

    completed_at = now_iso()
    report_entries: list[dict[str, Any]] = []
    for index, raw_entry in enumerate(raw_entries, start=1):
        if not isinstance(raw_entry, dict):
            raise RuntimeError(f"invalid handoff entry #{index} for local fallback")
        source_path = normalize_scalar(raw_entry.get("source_path"))
        fingerprint = normalize_scalar(raw_entry.get("fingerprint"))
        if not source_path or not fingerprint:
            raise RuntimeError(f"handoff entry #{index} is missing source_path or fingerprint for local fallback")

        source_text = load_handoff_entry_source_text(raw_entry, vault_path=vault_path)
        outputs: list[dict[str, Any]] = []
        for destination_vault in fallback_destination_vaults(raw_entry):
            note_path = f"{destination_vault}/{Path(source_path).name}"
            destination_note = resolve_destination_note_file(vault_path, destination_vault, note_path)
            if not destination_note.exists():
                atomic_write(destination_note, source_text)
            outputs.append(
                {
                    "destination_vault": destination_vault,
                    "note_path": note_path,
                    "title": normalize_scalar(raw_entry.get("title")),
                    "tags": normalize_list(raw_entry.get("tags")),
                    "warnings": [],
                }
            )

        report_entries.append(
            {
                "source_path": source_path,
                "fingerprint": fingerprint,
                "status": "processed",
                "warnings": [f"local fallback applied: {fallback_reason}"],
                "outputs": outputs,
            }
        )

    return {
        "job_id": job_id,
        "completed_at": completed_at,
        "reported_by": "obs-auto-moc-fallback",
        "entries": report_entries,
    }


def load_state_entries(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    payload = load_json_file(path)
    if not isinstance(payload, dict):
        raise RuntimeError(f"invalid root-note state payload: {path}")
    raw_entries = payload.get("entries", {})
    if not isinstance(raw_entries, dict):
        raise RuntimeError(f"invalid root-note state entries: {path}")
    entries: dict[str, dict[str, Any]] = {}
    for source_path, raw_entry in raw_entries.items():
        if not isinstance(source_path, str) or not isinstance(raw_entry, dict):
            raise RuntimeError(f"invalid root-note state entry: {path}: {source_path!r}")
        entries[source_path] = raw_entry
    return entries


def mark_job_entries_failed_for_retry(
    state_path: Path,
    *,
    job_id: str,
    updated_at: str,
    error: str,
    report_path: Path,
    report_entries: list[dict[str, Any]] | None = None,
) -> None:
    state_entries = load_state_entries(state_path)
    targets = (
        {
            (entry["source_path"], entry["fingerprint"])
            for entry in report_entries
            if isinstance(entry, dict) and entry.get("source_path") and entry.get("fingerprint")
        }
        if report_entries is not None
        else None
    )

    changed = False
    for source_path, state_entry in state_entries.items():
        if normalize_scalar(state_entry.get("last_job_id")) != job_id:
            continue
        fingerprint = normalize_scalar(state_entry.get("fingerprint"))
        if not fingerprint:
            continue
        if targets is not None and (source_path, fingerprint) not in targets:
            continue
        state_entries[source_path] = {
            "fingerprint": fingerprint,
            "status": "failed",
            "destinations": [],
            "last_job_id": job_id,
            "updated_at": updated_at,
            "last_report_path": str(report_path),
            "last_error": error,
        }
        changed = True

    if changed:
        write_json_file(state_path, {"entries": state_entries})


def list_report_inbox_files(path: Path) -> list[Path]:
    if not path.exists():
        return []
    return sorted(candidate for candidate in path.glob("*.json") if candidate.is_file())


def build_root_note_job_id(generated_at: str, source_paths: list[str]) -> str:
    stamp = re.sub(r"\D", "", generated_at)[:14]
    digest = sha256("\n".join(source_paths).encode("utf-8")).hexdigest()[:8]
    return f"root-note-{stamp}-{digest}"


def build_root_note_handoff_entry(path: Path, vault_path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    parsed = parse_markdown_text(text)
    frontmatter = parsed.frontmatter
    relative_path = path.relative_to(vault_path).as_posix()
    note_name = path.stem
    title = normalize_scalar(frontmatter.get("title")) or note_name
    return {
        "source_path": relative_path,
        "fingerprint": fingerprint_text(text),
        "title": title,
        "note_name": note_name,
        "tags": normalize_list(frontmatter.get("tags")),
        "aliases": normalize_list(frontmatter.get("aliases")),
        "moc_targets": normalize_list(frontmatter.get("moc_targets") or frontmatter.get("moc-targets")),
        "status": normalize_scalar(frontmatter.get("status")),
        "updated_at": normalize_scalar(frontmatter.get("updated_at") or frontmatter.get("updated")),
        "atomized_from": normalize_scalar(frontmatter.get("atomized_from")),
        "parse_error": parsed.parse_error,
        "duplicate_frontmatter": parsed.duplicate_frontmatter,
        "has_frontmatter": parsed.has_frontmatter,
        "outbound_links": extract_wikilinks(parsed.body),
        "source_text": text,
    }


def should_skip_root_note_entry(
    state_entry: dict[str, Any] | None,
    *,
    fingerprint: str,
    generated_at: str,
    pending_report_job_ids: set[str],
) -> bool:
    if state_entry is None or state_entry.get("fingerprint") != fingerprint:
        return False

    status = normalize_scalar(state_entry.get("status"))
    if status in {"processed", "skipped"}:
        return True
    if status != "handed_off_to_picoclaw":
        return False

    last_job_id = normalize_scalar(state_entry.get("last_job_id"))
    if last_job_id and last_job_id in pending_report_job_ids:
        return True

    updated_at = parse_iso_datetime(normalize_scalar(state_entry.get("updated_at")))
    generated_dt = parse_iso_datetime(generated_at)
    if updated_at is None or generated_dt is None:
        return False
    return (generated_dt - updated_at).total_seconds() < stale_handoff_seconds()


def resolve_ruleset_source_paths(vault_path: Path) -> dict[str, str]:
    relative_path = PIPELINE_RULESET_SOURCE
    candidates = [
        (vault_path / relative_path).expanduser(),
        Path("~/.picoclaw/workspace/notes").expanduser() / relative_path,
    ]
    absolute_path = next((str(candidate) for candidate in candidates if candidate.exists()), None)
    payload: dict[str, str] = {
        "name": PIPELINE_RULESET_NAME,
        "source": relative_path,
    }
    if absolute_path:
        payload["absolute_source_path"] = absolute_path
    return payload


def monitor_root_note(
    *,
    sync_root: Path | None = None,
    vault_path: Path | None = None,
    artifacts_root: Path | None = None,
    root_note_path: Path | None = None,
    pipeline_root: Path | None = None,
    generated_at: str | None = None,
) -> RootNoteMonitorResult:
    generated = generated_at or now_iso()
    paths = resolve_paths(sync_root=sync_root, vault_path=vault_path, artifacts_root=artifacts_root, generated_at=generated)
    root_paths = resolve_root_note_paths(paths, root_note_path=root_note_path, pipeline_root=pipeline_root)
    state_entries = load_state_entries(root_paths.state_path)
    pending_report_job_ids = {report_file.stem for report_file in list_report_inbox_files(root_paths.report_inbox_root)}

    scanned_files = 0
    unchanged_files = 0
    handoff_entries: list[dict[str, Any]] = []
    if root_paths.root_note_path.exists():
        for path in sorted(root_paths.root_note_path.rglob("*.md")):
            scanned_files += 1
            entry = build_root_note_handoff_entry(path, paths.vault_path)
            state_entry = state_entries.get(entry["source_path"])
            if should_skip_root_note_entry(
                state_entry,
                fingerprint=entry["fingerprint"],
                generated_at=generated,
                pending_report_job_ids=pending_report_job_ids,
            ):
                unchanged_files += 1
                continue
            handoff_entries.append(entry)

    handoff_path: Path | None = None
    job_id: str | None = None
    if handoff_entries:
        job_id = build_root_note_job_id(generated, [entry["source_path"] for entry in handoff_entries])
        handoff_path = root_paths.handoff_root / f"{job_id}.json"
        handoff_payload = {
            "job_id": job_id,
            "generated_at": generated,
            "vault_path": str(paths.vault_path),
            "root_note_path": str(root_paths.root_note_path),
            "ruleset": resolve_ruleset_source_paths(paths.vault_path),
            "destination_vaults": list(DESTINATION_VAULTS),
            "destination_root_paths": {
                destination_vault: str(paths.vault_path / destination_vault)
                for destination_vault in DESTINATION_VAULTS
            },
            "entries": handoff_entries,
            "callback_contract": {
                "reported_by": "PicoClaw",
                "allowed_statuses": list(REPORT_STATUSES),
                "required_entry_fields": [
                    "source_path",
                    "fingerprint",
                    "status",
                ],
                "processed_output_fields": [
                    "destination_vault",
                    "note_path",
                ],
                "endpoint": f"http://{PIPELINE_CALLBACK_HOST}:{PIPELINE_CALLBACK_PORT}{PIPELINE_CALLBACK_PATH}",
                "note": "Processed entries should point to destination note files that PicoClaw already created or updated, then POST the structured report JSON to the loopback callback endpoint.",
            },
        }
        write_json_file(handoff_path, handoff_payload)
        for entry in handoff_entries:
            state_entries[entry["source_path"]] = {
                "fingerprint": entry["fingerprint"],
                "status": "handed_off_to_picoclaw",
                "last_job_id": job_id,
                "updated_at": generated,
            }
        write_json_file(root_paths.state_path, {"entries": state_entries})

    result = RootNoteMonitorResult(
        generated_at=generated,
        paths=root_paths,
        root_note_exists=root_paths.root_note_path.exists(),
        scanned_files=scanned_files,
        handed_off_files=len(handoff_entries),
        unchanged_files=unchanged_files,
        job_id=job_id,
        handoff_path=handoff_path,
    )
    write_json_file(root_paths.status_path, result.to_dict())
    return result


def validate_destination_vault(destination_vault: str) -> None:
    if destination_vault not in DESTINATION_VAULTS:
        raise RuntimeError(
            f"destination vault must be one of {', '.join(DESTINATION_VAULTS)}, got {destination_vault}"
        )


def validate_root_note_source_path(source_path: str) -> None:
    source = Path(source_path)
    if source.is_absolute() or ".." in source.parts or not source.parts or source.parts[0] != ROOT_NOTE_DIRNAME:
        raise RuntimeError(f"source_path must stay under {ROOT_NOTE_DIRNAME}/: {source_path}")


def validate_destination_note_path(destination_vault: str, note_path: str) -> None:
    note = Path(note_path)
    if note.is_absolute() or ".." in note.parts or not note.parts:
        raise RuntimeError(f"note_path must be a relative path inside {destination_vault}: {note_path}")
    if note.parts[0] != destination_vault:
        raise RuntimeError(f"note_path must start with {destination_vault}/")


def resolve_destination_note_file(vault_path: Path, destination_vault: str, note_path: str) -> Path:
    validate_destination_note_path(destination_vault, note_path)
    resolved = (vault_path / note_path).resolve()
    destination_root = (vault_path / destination_vault).resolve()
    if destination_root not in resolved.parents and resolved != destination_root:
        raise RuntimeError(f"note_path escapes destination vault {destination_vault}: {note_path}")
    return resolved


def normalize_picoclaw_report_payload(
    payload: Any,
    *,
    source_label: str,
    expected_entries: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise RuntimeError(f"invalid PicoClaw report payload: {source_label}")

    job_id = normalize_scalar(payload.get("job_id"))
    if not job_id:
        raise RuntimeError(f"missing job_id in PicoClaw report: {source_label}")

    completed_at = normalize_scalar(payload.get("completed_at")) or now_iso()
    reported_by = normalize_scalar(payload.get("reported_by")) or "PicoClaw"
    raw_entries = payload.get("entries")
    if not isinstance(raw_entries, list) or not raw_entries:
        raise RuntimeError(f"PicoClaw report must contain a non-empty entries list: {source_label}")

    normalized_entries: list[dict[str, Any]] = []
    for index, raw_entry in enumerate(raw_entries, start=1):
        if not isinstance(raw_entry, dict):
            raise RuntimeError(f"invalid PicoClaw report entry #{index}: {source_label}")
        source_path = normalize_scalar(raw_entry.get("source_path"))
        fingerprint = normalize_scalar(raw_entry.get("fingerprint"))
        status = normalize_scalar(raw_entry.get("status"))
        if not source_path or not fingerprint or not status:
            raise RuntimeError(f"report entry #{index} is missing source_path, fingerprint, or status: {source_label}")
        validate_root_note_source_path(source_path)
        if status not in REPORT_STATUSES:
            raise RuntimeError(
                f"report entry #{index} has invalid status {status!r}; expected one of {', '.join(REPORT_STATUSES)}"
            )

        raw_outputs = raw_entry.get("outputs") or []
        if not isinstance(raw_outputs, list):
            raise RuntimeError(f"report entry #{index} outputs must be a list: {source_label}")
        outputs: list[dict[str, Any]] = []
        for output_index, raw_output in enumerate(raw_outputs, start=1):
            if not isinstance(raw_output, dict):
                raise RuntimeError(f"report entry #{index} output #{output_index} is invalid: {source_label}")
            destination_vault = normalize_scalar(raw_output.get("destination_vault"))
            note_path = normalize_scalar(raw_output.get("note_path"))
            if not destination_vault or not note_path:
                raise RuntimeError(
                    f"report entry #{index} output #{output_index} must include destination_vault and note_path"
                )
            validate_destination_vault(destination_vault)
            validate_destination_note_path(destination_vault, note_path)
            outputs.append(
                {
                    "destination_vault": destination_vault,
                    "note_path": note_path,
                    "title": normalize_scalar(raw_output.get("title")),
                    "tags": normalize_list(raw_output.get("tags")),
                    "warnings": normalize_list(raw_output.get("warnings")),
                }
            )

        if status == "processed" and not outputs:
            raise RuntimeError(f"report entry #{index} must include outputs when status=processed")

        normalized_entries.append(
            {
                "source_path": source_path,
                "fingerprint": fingerprint,
                "status": status,
                "warnings": normalize_list(raw_entry.get("warnings")),
                "outputs": outputs,
            }
        )

    if expected_entries is not None:
        expected_pairs: list[tuple[str, str]] = []
        for index, raw_entry in enumerate(expected_entries, start=1):
            if not isinstance(raw_entry, dict):
                raise RuntimeError(f"invalid PicoClaw handoff entry #{index}: {source_label}")
            source_path = normalize_scalar(raw_entry.get("source_path"))
            fingerprint = normalize_scalar(raw_entry.get("fingerprint"))
            if not source_path or not fingerprint:
                raise RuntimeError(f"handoff entry #{index} is missing source_path or fingerprint: {source_label}")
            validate_root_note_source_path(source_path)
            expected_pairs.append((source_path, fingerprint))

        present_pairs = {(entry["source_path"], entry["fingerprint"]) for entry in normalized_entries}
        for source_path, fingerprint in expected_pairs:
            if (source_path, fingerprint) in present_pairs:
                continue
            normalized_entries.append(
                {
                    "source_path": source_path,
                    "fingerprint": fingerprint,
                    "status": "failed",
                    "warnings": [f"missing from PicoClaw report: {source_label}"],
                    "outputs": [],
                }
            )

    return {
        "job_id": job_id,
        "completed_at": completed_at,
        "reported_by": reported_by,
        "entries": normalized_entries,
    }


def load_picoclaw_report(report_path: Path) -> dict[str, Any]:
    return normalize_picoclaw_report_payload(load_json_file(report_path), source_label=str(report_path))


def queue_picoclaw_report(
    *,
    report_path: Path | None = None,
    report_payload: dict[str, Any] | None = None,
    sync_root: Path | None = None,
    vault_path: Path | None = None,
    artifacts_root: Path | None = None,
    root_note_path: Path | None = None,
    pipeline_root: Path | None = None,
    run_pipeline: bool = False,
) -> PicoclawReportQueueResult:
    if (report_path is None) == (report_payload is None):
        raise RuntimeError("exactly one of report_path or report_payload must be provided")

    report = (
        load_picoclaw_report(report_path.expanduser())
        if report_path is not None
        else normalize_picoclaw_report_payload(report_payload, source_label="inline PicoClaw report payload")
    )
    paths = resolve_paths(sync_root=sync_root, vault_path=vault_path, artifacts_root=artifacts_root, generated_at=report["completed_at"])
    root_paths = resolve_root_note_paths(paths, root_note_path=root_note_path, pipeline_root=pipeline_root)
    queued_report_path = root_paths.report_inbox_root / f"{report['job_id']}.json"
    write_json_file(queued_report_path, report)

    pipeline_result: dict[str, Any] | None = None
    if run_pipeline:
        original_dispatch = os.environ.get(PICOCLAW_AUTO_DISPATCH_ENV)
        os.environ[PICOCLAW_AUTO_DISPATCH_ENV] = "0"
        try:
            pipeline_result = run_pipeline_once(
                vault_path=paths.vault_path,
                artifacts_root=paths.artifacts_root,
                root_note_path=root_paths.root_note_path,
                pipeline_root=root_paths.pipeline_root,
                generated_at=report["completed_at"],
            ).to_dict()
        finally:
            if original_dispatch is None:
                os.environ.pop(PICOCLAW_AUTO_DISPATCH_ENV, None)
            else:
                os.environ[PICOCLAW_AUTO_DISPATCH_ENV] = original_dispatch

    return PicoclawReportQueueResult(
        generated_at=report["completed_at"],
        job_id=report["job_id"],
        reported_by=report["reported_by"],
        entry_count=len(report["entries"]),
        report_inbox_root=root_paths.report_inbox_root,
        queued_report_path=queued_report_path,
        pipeline_result=pipeline_result,
    )


def dispatch_handoff_to_picoclaw(
    *,
    handoff_path: Path,
    sync_root: Path | None = None,
    vault_path: Path | None = None,
    artifacts_root: Path | None = None,
    root_note_path: Path | None = None,
    pipeline_root: Path | None = None,
    run_pipeline: bool = True,
    picoclaw_bin: str | None = None,
    picoclaw_session: str | None = None,
    timeout_s: int | None = None,
) -> PicoclawDispatchResult:
    handoff_path = handoff_path.expanduser()
    handoff_payload = load_json_file(handoff_path)
    if not isinstance(handoff_payload, dict):
        raise RuntimeError(f"invalid handoff payload: {handoff_path}")
    job_id = normalize_scalar(handoff_payload.get("job_id"))
    callback_contract = handoff_payload.get("callback_contract")
    callback_endpoint = None
    if isinstance(callback_contract, dict):
        callback_endpoint = normalize_scalar(callback_contract.get("endpoint"))
    if not job_id or not callback_endpoint:
        raise RuntimeError(f"handoff payload must include job_id and callback_contract.endpoint: {handoff_path}")

    generated_at = normalize_scalar(handoff_payload.get("generated_at")) or now_iso()
    paths = resolve_paths(sync_root=sync_root, vault_path=vault_path, artifacts_root=artifacts_root, generated_at=generated_at)
    root_paths = resolve_root_note_paths(paths, root_note_path=root_note_path, pipeline_root=pipeline_root)
    dispatch_root = root_paths.pipeline_root / "picoclaw-dispatch"
    dispatch_root.mkdir(parents=True, exist_ok=True)
    raw_output_log_path = dispatch_root / f"{job_id}.agent.log"
    report_copy_path = dispatch_root / f"{job_id}.report.json"

    prompt = build_picoclaw_dispatch_prompt(handoff_payload=handoff_payload, callback_endpoint=callback_endpoint)
    command = [
        picoclaw_bin or os.environ.get(PICOCLAW_BIN_ENV, PICOCLAW_DEFAULT_BIN),
        "agent",
        "--session",
        build_picoclaw_dispatch_session(
            picoclaw_session or os.environ.get(PICOCLAW_SESSION_ENV, PICOCLAW_DEFAULT_SESSION),
            job_id,
        ),
        "--message",
        prompt,
    ]
    timeout_value = timeout_s
    if timeout_value is None:
        timeout_text = os.environ.get(PICOCLAW_TIMEOUT_ENV)
        timeout_value = int(timeout_text) if timeout_text else PICOCLAW_DEFAULT_TIMEOUT_S

    proc = subprocess.run(
        command,
        text=True,
        capture_output=True,
        timeout=timeout_value,
        check=False,
    )
    combined_output = (proc.stdout or "") + (proc.stderr or "")
    atomic_write(raw_output_log_path, combined_output)
    if proc.returncode != 0:
        raise RuntimeError(
            f"PicoClaw agent dispatch failed for {job_id} with exit code {proc.returncode}; see {raw_output_log_path}"
        )

    try:
        report_payload = normalize_picoclaw_report_payload(
            extract_json_block(
                combined_output,
                start_marker=PICOCLAW_REPORT_BEGIN,
                end_marker=PICOCLAW_REPORT_END,
            ),
            source_label=f"PicoClaw dispatch output for {job_id}",
            expected_entries=handoff_payload.get("entries") if isinstance(handoff_payload.get("entries"), list) else None,
        )
        fallback_reason = should_use_local_fallback_report(
            report_payload,
            handoff_payload=handoff_payload,
            vault_path=paths.vault_path,
        )
        if fallback_reason is not None:
            report_payload = build_local_fallback_report(
                handoff_payload,
                vault_path=paths.vault_path,
                fallback_reason=fallback_reason,
            )
    except Exception as exc:
        raise RuntimeError(
            f"PicoClaw agent returned unusable report for {job_id}; see {raw_output_log_path}: {exc}"
        ) from exc
    write_json_file(report_copy_path, report_payload)
    queue_result = queue_picoclaw_report(
        report_payload=report_payload,
        vault_path=paths.vault_path,
        artifacts_root=paths.artifacts_root,
        root_note_path=root_paths.root_note_path,
        pipeline_root=root_paths.pipeline_root,
        run_pipeline=run_pipeline,
    )
    return PicoclawDispatchResult(
        generated_at=queue_result.generated_at,
        job_id=job_id,
        handoff_path=handoff_path,
        queued_report_path=queue_result.queued_report_path,
        report_copy_path=report_copy_path,
        raw_output_log_path=raw_output_log_path,
        entry_count=queue_result.entry_count,
        pipeline_result=queue_result.pipeline_result,
    )


def refresh_destination_mocs(
    *,
    sync_root: Path | None = None,
    vault_path: Path | None = None,
    artifacts_root: Path | None = None,
    destination_vaults: list[str] | None = None,
    generated_at: str | None = None,
) -> DestinationMocRefreshResult:
    generated = generated_at or now_iso()
    paths = resolve_paths(sync_root=sync_root, vault_path=vault_path, artifacts_root=artifacts_root, generated_at=generated)
    requested_vaults = destination_vaults or list(DESTINATION_VAULTS)
    unique_vaults = unique_preserving_order(requested_vaults)
    for destination_vault in unique_vaults:
        validate_destination_vault(destination_vault)

    destination_mocs: dict[str, str] = {}
    note_counts: dict[str, int] = {}
    for destination_vault in unique_vaults:
        notes = scan_destination_notes(paths.vault_path, destination_vault)
        output_path = paths.vault_path / destination_vault / "MOC.md"
        atomic_write(output_path, render_destination_moc(destination_vault, notes, generated))
        destination_mocs[destination_vault] = str(output_path)
        note_counts[destination_vault] = len(notes)

    return DestinationMocRefreshResult(
        generated_at=generated,
        vault_path=paths.vault_path,
        destination_mocs=destination_mocs,
        note_counts=note_counts,
    )


def apply_picoclaw_report(
    *,
    report_path: Path,
    sync_root: Path | None = None,
    vault_path: Path | None = None,
    artifacts_root: Path | None = None,
    root_note_path: Path | None = None,
    pipeline_root: Path | None = None,
) -> PicoclawReportApplyResult:
    report = load_picoclaw_report(report_path.expanduser())
    paths = resolve_paths(sync_root=sync_root, vault_path=vault_path, artifacts_root=artifacts_root, generated_at=report["completed_at"])
    root_paths = resolve_root_note_paths(paths, root_note_path=root_note_path, pipeline_root=pipeline_root)
    archived_report_path = root_paths.completions_root / f"{report['job_id']}.json"

    state_entries = load_state_entries(root_paths.state_path)
    processed_count = 0
    skipped_count = 0
    failed_count = 0
    touched_destination_vaults: list[str] = []
    for entry in report["entries"]:
        entry_error: str | None = None
        state_entry = state_entries.get(entry["source_path"])
        if state_entry is not None and state_entry.get("fingerprint") != entry["fingerprint"]:
            entry_error = (
                f"fingerprint mismatch for {entry['source_path']}: "
                f"state has {state_entry.get('fingerprint')}, report has {entry['fingerprint']}"
            )

        destinations: list[str] = []
        for output in entry["outputs"]:
            try:
                destination_note = resolve_destination_note_file(
                    paths.vault_path,
                    output["destination_vault"],
                    output["note_path"],
                )
            except RuntimeError as exc:
                entry_error = str(exc)
                break
            if not destination_note.exists():
                entry_error = f"PicoClaw report references missing destination note: {output['note_path']}"
                break
            destinations.append(output["destination_vault"])

        if entry_error is not None:
            state_entries[entry["source_path"]] = {
                "fingerprint": entry["fingerprint"],
                "status": "failed",
                "destinations": [],
                "last_job_id": report["job_id"],
                "updated_at": report["completed_at"],
                "last_report_path": str(archived_report_path),
                "last_error": entry_error,
            }
            failed_count += 1
            continue

        destinations = unique_preserving_order(destinations)
        touched_destination_vaults.extend(destinations)
        state_entries[entry["source_path"]] = {
            "fingerprint": entry["fingerprint"],
            "status": entry["status"],
            "destinations": destinations,
            "last_job_id": report["job_id"],
            "updated_at": report["completed_at"],
            "last_report_path": str(archived_report_path),
        }
        if entry["status"] == "failed" and entry.get("warnings"):
            state_entries[entry["source_path"]]["last_error"] = "; ".join(normalize_list(entry["warnings"]))
        if entry["status"] == "processed":
            processed_count += 1
        elif entry["status"] == "skipped":
            skipped_count += 1
        else:
            failed_count += 1

    write_json_file(archived_report_path, report)
    write_json_file(root_paths.state_path, {"entries": state_entries})
    unique_destinations = unique_preserving_order(touched_destination_vaults)
    destination_result = (
        refresh_destination_mocs(
            vault_path=paths.vault_path,
            artifacts_root=paths.artifacts_root,
            destination_vaults=unique_destinations,
            generated_at=report["completed_at"],
        )
        if unique_destinations
        else DestinationMocRefreshResult(
            generated_at=report["completed_at"],
            vault_path=paths.vault_path,
            destination_mocs={},
            note_counts={},
        )
    )
    result = PicoclawReportApplyResult(
        generated_at=report["completed_at"],
        job_id=report["job_id"],
        report_path=report_path.expanduser(),
        archived_report_path=archived_report_path,
        state_path=root_paths.state_path,
        processed_count=processed_count,
        skipped_count=skipped_count,
        failed_count=failed_count,
        touched_destination_vaults=unique_destinations,
        destination_mocs=destination_result.destination_mocs,
    )
    write_json_file(root_paths.status_path, result.to_dict())
    return result


def run_pipeline_once(
    *,
    sync_root: Path | None = None,
    vault_path: Path | None = None,
    artifacts_root: Path | None = None,
    root_note_path: Path | None = None,
    pipeline_root: Path | None = None,
    generated_at: str | None = None,
) -> PipelineRunResult:
    generated = generated_at or now_iso()
    paths = resolve_paths(sync_root=sync_root, vault_path=vault_path, artifacts_root=artifacts_root, generated_at=generated)
    root_paths = resolve_root_note_paths(paths, root_note_path=root_note_path, pipeline_root=pipeline_root)
    auto_dispatch = env_flag(PICOCLAW_AUTO_DISPATCH_ENV, default=False)

    reports_discovered = 0
    reports_applied = 0
    reports_failed = 0
    archived_report_paths: list[str] = []
    failed_report_paths: list[str] = []
    for report_file in list_report_inbox_files(root_paths.report_inbox_root):
        reports_discovered += 1
        try:
            apply_result = apply_picoclaw_report(
                report_path=report_file,
                vault_path=paths.vault_path,
                artifacts_root=paths.artifacts_root,
                root_note_path=root_paths.root_note_path,
                pipeline_root=root_paths.pipeline_root,
            )
        except Exception as exc:
            reports_failed += 1
            failed_report_path = root_paths.failed_report_root / report_file.name
            failed_report_path.parent.mkdir(parents=True, exist_ok=True)
            report_file.replace(failed_report_path)
            failed_report_paths.append(str(failed_report_path))

            job_id = report_file.stem
            updated_at = generated
            report_entries: list[dict[str, Any]] | None = None
            try:
                report = load_picoclaw_report(failed_report_path)
            except Exception:
                report = None
            if report is not None:
                job_id = report["job_id"]
                updated_at = report["completed_at"]
                report_entries = report["entries"]

            mark_job_entries_failed_for_retry(
                root_paths.state_path,
                job_id=job_id,
                updated_at=updated_at,
                error=str(exc),
                report_path=failed_report_path,
                report_entries=report_entries,
            )
            continue

        archived_report_paths.append(str(apply_result.archived_report_path))
        reports_applied += 1
        report_file.unlink()

    monitor_result = monitor_root_note(
        vault_path=paths.vault_path,
        artifacts_root=paths.artifacts_root,
        root_note_path=root_paths.root_note_path,
        pipeline_root=root_paths.pipeline_root,
        generated_at=generated,
    )
    dispatch_attempted = 0
    dispatch_succeeded = 0
    dispatch_failed = 0
    dispatched_job_ids: list[str] = []
    dispatch_log_paths: list[str] = []
    handoff_path = monitor_result.handoff_path
    handoff_job_id = monitor_result.job_id
    handed_off_files = monitor_result.handed_off_files
    unchanged_files = monitor_result.unchanged_files

    if auto_dispatch and monitor_result.handoff_path is not None and monitor_result.job_id is not None:
        dispatch_attempted = 1
        try:
            dispatch_result = dispatch_handoff_to_picoclaw(
                handoff_path=monitor_result.handoff_path,
                vault_path=paths.vault_path,
                artifacts_root=paths.artifacts_root,
                root_note_path=root_paths.root_note_path,
                pipeline_root=root_paths.pipeline_root,
                run_pipeline=True,
            )
        except Exception as exc:
            dispatch_failed = 1
            dispatch_log_path = root_paths.pipeline_root / "picoclaw-dispatch" / f"{monitor_result.job_id}.agent.log"
            if dispatch_log_path.exists():
                dispatch_log_paths.append(str(dispatch_log_path))
            mark_job_entries_failed_for_retry(
                root_paths.state_path,
                job_id=monitor_result.job_id,
                updated_at=generated,
                error=str(exc),
                report_path=dispatch_log_path if dispatch_log_path.exists() else monitor_result.handoff_path,
            )
        else:
            dispatch_succeeded = 1
            dispatched_job_ids.append(dispatch_result.job_id)
            dispatch_log_paths.append(str(dispatch_result.raw_output_log_path))
            if dispatch_result.pipeline_result is not None:
                reports_discovered += int(dispatch_result.pipeline_result.get("reports_discovered") or 0)
                reports_applied += int(dispatch_result.pipeline_result.get("reports_applied") or 0)
                reports_failed += int(dispatch_result.pipeline_result.get("reports_failed") or 0)
                archived_report_paths.extend(dispatch_result.pipeline_result.get("archived_report_paths") or [])
                failed_report_paths.extend(dispatch_result.pipeline_result.get("failed_report_paths") or [])
                handoff_job_id = dispatch_result.pipeline_result.get("handoff_job_id")
                handoff_path = dispatch_result.pipeline_result.get("handoff_path")
                handed_off_files = int(dispatch_result.pipeline_result.get("handed_off_files") or 0)
                unchanged_files = int(dispatch_result.pipeline_result.get("unchanged_files") or 0)

    result = PipelineRunResult(
        generated_at=generated,
        root_note_path=root_paths.root_note_path,
        report_inbox_root=root_paths.report_inbox_root,
        reports_discovered=reports_discovered,
        reports_applied=reports_applied,
        reports_failed=reports_failed,
        archived_report_paths=archived_report_paths,
        failed_report_paths=failed_report_paths,
        handoff_job_id=handoff_job_id,
        handoff_path=str(handoff_path) if isinstance(handoff_path, Path) else handoff_path,
        handed_off_files=handed_off_files,
        unchanged_files=unchanged_files,
        state_path=root_paths.state_path,
        dispatch_enabled=auto_dispatch,
        dispatch_attempted=dispatch_attempted,
        dispatch_succeeded=dispatch_succeeded,
        dispatch_failed=dispatch_failed,
        dispatched_job_ids=dispatched_job_ids,
        dispatch_log_paths=dispatch_log_paths,
    )
    write_json_file(root_paths.status_path, result.to_dict())
    return result


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
    write_json_file(paths.last_run_path, result.to_dict())
    return result


def load_last_run(last_run_path: Path) -> dict[str, Any]:
    return json.loads(last_run_path.read_text(encoding="utf-8"))
