from __future__ import annotations

import argparse
import json
from pathlib import Path

from .engine import (
    apply_picoclaw_report,
    build_workspace,
    dispatch_handoff_to_picoclaw,
    load_last_run,
    monitor_root_note,
    now_iso,
    queue_picoclaw_report,
    record_agent_references,
    refresh_destination_mocs,
    resolve_paths,
    run_pipeline_once,
)
from .dream import run_dream_mode
from .persona_goal import distill_persona_goals
from .retrieval import query_memory
from .session_insights import import_session_insights
from .server import serve_loopback
from .synthesis import synthesize_memory
from .wakeup import build_wake_up_bundle


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="obs-auto-moc")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build", help="scan notes and generate manifest, proposal, and preview")
    build.add_argument("--sync-root", type=Path, default=Path("~/.config/obsidian-headless/sync"))
    build.add_argument("--vault-path", type=Path)
    build.add_argument("--artifacts-root", type=Path)
    build.add_argument("--output-moc-path", type=Path)
    build.add_argument("--generated-at")
    build.add_argument("--apply", action="store_true")
    build.add_argument("--json", action="store_true", help="print machine-readable summary")

    stats = subparsers.add_parser("stats", help="show the last build summary")
    stats.add_argument("--sync-root", type=Path, default=Path("~/.config/obsidian-headless/sync"))
    stats.add_argument("--vault-path", type=Path)
    stats.add_argument("--artifacts-root", type=Path)
    stats.add_argument("--json", action="store_true", help="print machine-readable summary")

    monitor = subparsers.add_parser(
        "monitor-root-note",
        help="detect staged files under root-note and emit a PicoClaw handoff job",
    )
    monitor.add_argument("--sync-root", type=Path, default=Path("~/.config/obsidian-headless/sync"))
    monitor.add_argument("--vault-path", type=Path)
    monitor.add_argument("--artifacts-root", type=Path)
    monitor.add_argument("--root-note-path", type=Path)
    monitor.add_argument("--pipeline-root", type=Path)
    monitor.add_argument("--generated-at")
    monitor.add_argument("--json", action="store_true", help="print machine-readable summary")

    apply_report = subparsers.add_parser(
        "apply-picoclaw-report",
        help="apply a structured PicoClaw completion report and refresh destination MOCs",
    )
    apply_report.add_argument("--sync-root", type=Path, default=Path("~/.config/obsidian-headless/sync"))
    apply_report.add_argument("--vault-path", type=Path)
    apply_report.add_argument("--artifacts-root", type=Path)
    apply_report.add_argument("--root-note-path", type=Path)
    apply_report.add_argument("--pipeline-root", type=Path)
    apply_report.add_argument("--report", type=Path, required=True)
    apply_report.add_argument("--json", action="store_true", help="print machine-readable summary")

    queue_report = subparsers.add_parser(
        "queue-picoclaw-report",
        help="validate a PicoClaw completion report and queue it into the pipeline inbox",
    )
    queue_report.add_argument("--sync-root", type=Path, default=Path("~/.config/obsidian-headless/sync"))
    queue_report.add_argument("--vault-path", type=Path)
    queue_report.add_argument("--artifacts-root", type=Path)
    queue_report.add_argument("--root-note-path", type=Path)
    queue_report.add_argument("--pipeline-root", type=Path)
    queue_report.add_argument("--report", type=Path, required=True)
    queue_report.add_argument("--run-pipeline", action="store_true", help="apply the queued report immediately by running one pipeline tick")
    queue_report.add_argument("--json", action="store_true", help="print machine-readable summary")

    record_reference = subparsers.add_parser(
        "record-agent-reference",
        help="record an agent reference batch, reactivate Decayed notes, and rebuild related links",
    )
    record_reference.add_argument("--sync-root", type=Path, default=Path("~/.config/obsidian-headless/sync"))
    record_reference.add_argument("--vault-path", type=Path)
    record_reference.add_argument("--artifacts-root", type=Path)
    record_reference.add_argument("--note-path", action="append", dest="note_paths")
    record_reference.add_argument("--referenced-at")
    record_reference.add_argument("--json", action="store_true", help="print machine-readable summary")

    refresh = subparsers.add_parser(
        "refresh-destination-mocs",
        help="refresh script-maintained MOCs for TechVault, WorkVault, and PersonalVault",
    )
    refresh.add_argument("--sync-root", type=Path, default=Path("~/.config/obsidian-headless/sync"))
    refresh.add_argument("--vault-path", type=Path)
    refresh.add_argument("--artifacts-root", type=Path)
    refresh.add_argument("--destination-vault", action="append", dest="destination_vaults")
    refresh.add_argument("--generated-at")
    refresh.add_argument("--json", action="store_true", help="print machine-readable summary")

    run_pipeline = subparsers.add_parser(
        "run-pipeline-once",
        help="apply queued PicoClaw reports and then emit the next root-note handoff job",
    )
    run_pipeline.add_argument("--sync-root", type=Path, default=Path("~/.config/obsidian-headless/sync"))
    run_pipeline.add_argument("--vault-path", type=Path)
    run_pipeline.add_argument("--artifacts-root", type=Path)
    run_pipeline.add_argument("--root-note-path", type=Path)
    run_pipeline.add_argument("--pipeline-root", type=Path)
    run_pipeline.add_argument("--generated-at")
    run_pipeline.add_argument("--json", action="store_true", help="print machine-readable summary")

    dispatch = subparsers.add_parser(
        "dispatch-picoclaw-handoff",
        help="submit a generated handoff job to PicoClaw Stage 2 and optionally run the follow-up pipeline tick",
    )
    dispatch.add_argument("--sync-root", type=Path, default=Path("~/.config/obsidian-headless/sync"))
    dispatch.add_argument("--vault-path", type=Path)
    dispatch.add_argument("--artifacts-root", type=Path)
    dispatch.add_argument("--root-note-path", type=Path)
    dispatch.add_argument("--pipeline-root", type=Path)
    dispatch.add_argument("--handoff", type=Path, required=True)
    dispatch.add_argument("--no-run-pipeline", action="store_true", help="queue the structured report only, without immediately running the next pipeline tick")
    dispatch.add_argument("--json", action="store_true", help="print machine-readable summary")

    listen = subparsers.add_parser(
        "listen",
        help="start a loopback listener for health probes and queued PicoClaw report callbacks",
    )
    listen.add_argument("--sync-root", type=Path, default=Path("~/.config/obsidian-headless/sync"))
    listen.add_argument("--vault-path", type=Path)
    listen.add_argument("--artifacts-root", type=Path)
    listen.add_argument("--root-note-path", type=Path)
    listen.add_argument("--pipeline-root", type=Path)
    listen.add_argument("--host", default="127.0.0.1")
    listen.add_argument("--port", type=int, default=45460)
    listen.add_argument("--run-pipeline", action="store_true", help="apply queued report immediately after callback ingestion")

    query = subparsers.add_parser(
        "query-memory",
        help="query note memory using note content plus the secondary ledger",
    )
    query.add_argument("--sync-root", type=Path, default=Path("~/.config/obsidian-headless/sync"))
    query.add_argument("--vault-path", type=Path)
    query.add_argument("--artifacts-root", type=Path)
    query.add_argument("--query", required=True)
    query.add_argument("--limit", type=int, default=10)
    query.add_argument("--generated-at")
    query.add_argument("--json", action="store_true", help="print machine-readable summary")

    import_insights = subparsers.add_parser(
        "import-session-insights",
        help="import distilled session analytics artifacts into memory overlays",
    )
    import_insights.add_argument("--sync-root", type=Path, default=Path("~/.config/obsidian-headless/sync"))
    import_insights.add_argument("--vault-path", type=Path)
    import_insights.add_argument("--artifacts-root", type=Path)
    import_insights.add_argument("--insights", type=Path)
    import_insights.add_argument("--lesson", type=Path)
    import_insights.add_argument("--decision", type=Path)
    import_insights.add_argument("--skill-cards", type=Path)
    import_insights.add_argument("--skill-links", type=Path)
    import_insights.add_argument("--generated-at")
    import_insights.add_argument("--json", action="store_true", help="print machine-readable summary")

    wakeup = subparsers.add_parser(
        "wake-up",
        help="build a wake-up bundle from current memory health, hot notes, and open questions",
    )
    wakeup.add_argument("--sync-root", type=Path, default=Path("~/.config/obsidian-headless/sync"))
    wakeup.add_argument("--vault-path", type=Path)
    wakeup.add_argument("--artifacts-root", type=Path)
    wakeup.add_argument("--generated-at")
    wakeup.add_argument("--json", action="store_true", help="print machine-readable summary")

    dream = subparsers.add_parser(
        "dream",
        help="generate proposal-first dream-mode consolidation suggestions",
    )
    dream.add_argument("--sync-root", type=Path, default=Path("~/.config/obsidian-headless/sync"))
    dream.add_argument("--vault-path", type=Path)
    dream.add_argument("--artifacts-root", type=Path)
    dream.add_argument("--generated-at")
    dream.add_argument("--json", action="store_true", help="print machine-readable summary")

    persona = subparsers.add_parser(
        "distill-persona-goals",
        help="distill heuristics and goals from PersonalVault into an overlay, with optional canonical apply",
    )
    persona.add_argument("--sync-root", type=Path, default=Path("~/.config/obsidian-headless/sync"))
    persona.add_argument("--vault-path", type=Path)
    persona.add_argument("--artifacts-root", type=Path)
    persona.add_argument("--generated-at")
    persona.add_argument("--apply", action="store_true")
    persona.add_argument("--json", action="store_true", help="print machine-readable summary")

    synthesis = subparsers.add_parser(
        "synthesize-memory",
        help="assemble VERIFIED / SYNTHESIZED / OPEN QUESTION output from matched notes",
    )
    synthesis.add_argument("--sync-root", type=Path, default=Path("~/.config/obsidian-headless/sync"))
    synthesis.add_argument("--vault-path", type=Path)
    synthesis.add_argument("--artifacts-root", type=Path)
    synthesis.add_argument("--query", required=True)
    synthesis.add_argument("--limit", type=int, default=8)
    synthesis.add_argument("--generated-at")
    synthesis.add_argument("--write-artifact", action="store_true")
    synthesis.add_argument("--json", action="store_true", help="print machine-readable summary")

    return parser


def print_build_summary(result: dict[str, object]) -> None:
    print(f"generated_at: {result['generated_at']}")
    print(f"vault_path: {result['vault_path']}")
    print(f"artifacts_root: {result['artifacts_root']}")
    print(f"proposal_path: {result['proposal_path']}")
    print(f"preview_path: {result['preview_path']}")
    print(f"output_moc_path: {result['output_moc_path']}")
    print(f"notes_scanned: {result['notes_scanned']}")
    print(f"parse_errors: {result['parse_errors']}")
    print(f"duplicate_frontmatter_notes: {result['duplicate_frontmatter_notes']}")
    print(f"missing_schema_notes: {result['missing_schema_notes']}")
    print(f"orphan_notes: {result['orphan_notes']}")
    print(f"unresolved_links: {result['unresolved_links']}")
    print(f"ambiguous_links: {result['ambiguous_links']}")
    print(f"applied: {str(result['applied']).lower()}")


def print_monitor_summary(result: dict[str, object]) -> None:
    print(f"generated_at: {result['generated_at']}")
    print(f"root_note_path: {result['root_note_path']}")
    print(f"pipeline_root: {result['pipeline_root']}")
    print(f"scanned_files: {result['scanned_files']}")
    print(f"handed_off_files: {result['handed_off_files']}")
    print(f"unchanged_files: {result['unchanged_files']}")
    print(f"deferred_files: {result.get('deferred_files', 0)}")
    print(f"job_id: {result['job_id']}")
    print(f"handoff_path: {result['handoff_path']}")
    print(f"ruleset_name: {result['ruleset_name']}")
    print(f"ruleset_source: {result['ruleset_source']}")


def print_report_apply_summary(result: dict[str, object]) -> None:
    print(f"generated_at: {result['generated_at']}")
    print(f"job_id: {result['job_id']}")
    print(f"report_path: {result['report_path']}")
    print(f"archived_report_path: {result['archived_report_path']}")
    print(f"state_path: {result['state_path']}")
    print(f"processed_count: {result['processed_count']}")
    print(f"skipped_count: {result['skipped_count']}")
    print(f"failed_count: {result['failed_count']}")
    print(f"touched_destination_vaults: {', '.join(result['touched_destination_vaults'])}")
    print(f"referenced_note_count: {len(result.get('referenced_note_paths') or [])}")
    print(f"reactivated_note_count: {len(result.get('reactivated_note_paths') or [])}")
    print(f"relation_updated_note_count: {len(result.get('relation_updated_note_paths') or [])}")
    for name, path in (result.get("destination_mocs") or {}).items():
        print(f"destination_moc[{name}]: {path}")


def print_queue_report_summary(result: dict[str, object]) -> None:
    print(f"generated_at: {result['generated_at']}")
    print(f"job_id: {result['job_id']}")
    print(f"reported_by: {result['reported_by']}")
    print(f"entry_count: {result['entry_count']}")
    print(f"report_inbox_root: {result['report_inbox_root']}")
    print(f"queued_report_path: {result['queued_report_path']}")
    print(f"run_pipeline: {str(result['run_pipeline']).lower()}")
    if result.get("pipeline_result"):
        print(f"pipeline_reports_applied: {result['pipeline_result']['reports_applied']}")
        print(f"pipeline_handoff_job_id: {result['pipeline_result']['handoff_job_id']}")


def print_agent_reference_summary(result: dict[str, object]) -> None:
    print(f"referenced_at: {result['referenced_at']}")
    print(f"referenced_note_count: {len(result.get('referenced_note_paths') or [])}")
    print(f"reactivated_note_count: {len(result.get('reactivated_note_paths') or [])}")
    print(f"relation_updated_note_count: {len(result.get('relation_updated_note_paths') or [])}")
    print(f"touched_destination_vaults: {', '.join(result.get('touched_destination_vaults') or [])}")
    for name, path in (result.get("destination_mocs") or {}).items():
        print(f"destination_moc[{name}]: {path}")


def print_refresh_summary(result: dict[str, object]) -> None:
    print(f"generated_at: {result['generated_at']}")
    print(f"vault_path: {result['vault_path']}")
    for name, path in result["destination_mocs"].items():
        print(f"destination_moc[{name}]: {path}")
    for name, count in result["note_counts"].items():
        print(f"note_count[{name}]: {count}")


def print_pipeline_run_summary(result: dict[str, object]) -> None:
    print(f"generated_at: {result['generated_at']}")
    print(f"root_note_path: {result['root_note_path']}")
    print(f"report_inbox_root: {result['report_inbox_root']}")
    print(f"reports_discovered: {result['reports_discovered']}")
    print(f"reports_applied: {result['reports_applied']}")
    print(f"reports_failed: {result.get('reports_failed', 0)}")
    print(f"handoff_job_id: {result['handoff_job_id']}")
    print(f"handoff_path: {result['handoff_path']}")
    print(f"handed_off_files: {result['handed_off_files']}")
    print(f"unchanged_files: {result['unchanged_files']}")
    print(f"deferred_files: {result.get('deferred_files', 0)}")
    print(f"dispatch_enabled: {str(result.get('dispatch_enabled', False)).lower()}")
    print(f"dispatch_attempted: {result.get('dispatch_attempted', 0)}")
    print(f"dispatch_succeeded: {result.get('dispatch_succeeded', 0)}")
    print(f"dispatch_failed: {result.get('dispatch_failed', 0)}")
    print(f"state_path: {result['state_path']}")
    for index, path in enumerate(result.get("failed_report_paths") or [], start=1):
        print(f"failed_report_path[{index}]: {path}")
    for index, path in enumerate(result.get("dispatch_log_paths") or [], start=1):
        print(f"dispatch_log_path[{index}]: {path}")


def print_dispatch_summary(result: dict[str, object]) -> None:
    print(f"generated_at: {result['generated_at']}")
    print(f"job_id: {result['job_id']}")
    print(f"handoff_path: {result['handoff_path']}")
    print(f"queued_report_path: {result['queued_report_path']}")
    print(f"report_copy_path: {result['report_copy_path']}")
    print(f"raw_output_log_path: {result['raw_output_log_path']}")
    print(f"entry_count: {result['entry_count']}")
    print(f"run_pipeline: {str(result['run_pipeline']).lower()}")
    if result.get("pipeline_result"):
        print(f"pipeline_reports_applied: {result['pipeline_result']['reports_applied']}")
        print(f"pipeline_handoff_job_id: {result['pipeline_result']['handoff_job_id']}")


def print_memory_query_summary(result: dict[str, object]) -> None:
    print(f"generated_at: {result['generated_at']}")
    print(f"query: {result['query']}")
    print(f"result_count: {result['result_count']}")
    for index, row in enumerate(result.get("results") or [], start=1):
        print(f"result[{index}]: {row['note_path']} ({row['score']})")


def print_wakeup_summary(result: dict[str, object]) -> None:
    print(f"generated_at: {result['generated_at']}")
    print(f"output_path: {result['output_path']}")
    print(f"hot_note_count: {len(result.get('hot_note_paths') or [])}")
    print(f"stale_note_count: {len(result.get('stale_note_paths') or [])}")
    print(f"open_question_count: {len(result.get('open_questions') or [])}")
    print(f"contradiction_count: {result.get('contradiction_count', 0)}")
    print(f"operational_signal_count: {len(result.get('operational_signals') or [])}")
    print(f"session_friction_count: {len(result.get('session_friction_signals') or {})}")


def print_dream_summary(result: dict[str, object]) -> None:
    print(f"generated_at: {result['generated_at']}")
    print(f"proposal_path: {result['proposal_path']}")
    print(f"missing_contract_note_count: {len(result.get('missing_contract_note_paths') or [])}")
    print(f"duplicate_candidate_count: {len(result.get('duplicate_candidates') or [])}")
    print(f"contradiction_count: {result.get('contradiction_count', 0)}")
    print(f"session_patch_proposal_count: {len(result.get('session_patch_proposals') or [])}")
    print(f"accepted_rule_candidate_count: {len(result.get('accepted_rule_candidates') or [])}")


def print_persona_goal_summary(result: dict[str, object]) -> None:
    print(f"generated_at: {result['generated_at']}")
    print(f"overlay_path: {result['overlay_path']}")
    print(f"canonical_path: {result.get('canonical_path')}")
    print(f"heuristic_count: {len(result.get('heuristics') or [])}")
    print(f"goal_count: {len(result.get('goals') or [])}")
    print(f"source_note_count: {result.get('source_note_count', 0)}")
    print(f"session_heuristic_count: {len(result.get('session_heuristics') or [])}")
    print(f"applied: {str(result.get('applied', False)).lower()}")


def print_synthesis_summary(result: dict[str, object]) -> None:
    print(f"generated_at: {result['generated_at']}")
    print(f"query: {result['query']}")
    print(f"verified_count: {len(result.get('verified') or [])}")
    print(f"synthesized_count: {len(result.get('synthesized') or [])}")
    print(f"open_question_count: {len(result.get('open_questions') or [])}")
    print(f"artifact_path: {result.get('artifact_path')}")


def print_import_session_insights_summary(result: dict[str, object]) -> None:
    print(f"generated_at: {result['generated_at']}")
    print(f"dream_overlay_path: {result['dream_overlay_path']}")
    print(f"persona_overlay_path: {result['persona_overlay_path']}")
    print(f"method_graph_path: {result.get('method_graph_path')}")
    print(f"top_event_type_count: {len(result.get('top_event_types') or [])}")
    print(f"heuristic_candidate_count: {len(result.get('heuristic_candidates') or [])}")
    print(f"accepted_rule_candidate_count: {len(result.get('accepted_rule_candidates') or [])}")
    print(f"skill_card_count: {result.get('skill_card_count', 0)}")
    print(f"skill_link_count: {result.get('skill_link_count', 0)}")


def emit_payload(
    payload: dict[str, object],
    *,
    as_json: bool,
    printer,
) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        printer(payload)


def main() -> int:
    parser = build_parser()
    args, extras = parser.parse_known_args()
    extra_tokens = [token for token in extras if token.strip()]
    if extra_tokens:
        if not all(set(token) <= set(".。!！?？") for token in extra_tokens):
            parser.error(f"unrecognized arguments: {' '.join(extra_tokens)}")

    if args.command == "build":
        result = build_workspace(
            sync_root=args.sync_root.expanduser() if args.vault_path is None else None,
            vault_path=args.vault_path.expanduser() if args.vault_path else None,
            artifacts_root=args.artifacts_root.expanduser() if args.artifacts_root else None,
            output_moc_path=args.output_moc_path.expanduser() if args.output_moc_path else None,
            generated_at=args.generated_at,
            apply=args.apply,
        )
        emit_payload(result.to_dict(), as_json=args.json, printer=print_build_summary)
        return 0

    if args.command == "stats":
        paths = resolve_paths(
            sync_root=args.sync_root.expanduser() if args.vault_path is None else None,
            vault_path=args.vault_path.expanduser() if args.vault_path else None,
            artifacts_root=args.artifacts_root.expanduser() if args.artifacts_root else None,
        )
        payload = load_last_run(paths.last_run_path)
        emit_payload(payload, as_json=args.json, printer=print_build_summary)
        return 0

    if args.command == "monitor-root-note":
        result = monitor_root_note(
            sync_root=args.sync_root.expanduser() if args.vault_path is None else None,
            vault_path=args.vault_path.expanduser() if args.vault_path else None,
            artifacts_root=args.artifacts_root.expanduser() if args.artifacts_root else None,
            root_note_path=args.root_note_path.expanduser() if args.root_note_path else None,
            pipeline_root=args.pipeline_root.expanduser() if args.pipeline_root else None,
            generated_at=args.generated_at,
        )
        emit_payload(result.to_dict(), as_json=args.json, printer=print_monitor_summary)
        return 0

    if args.command == "apply-picoclaw-report":
        result = apply_picoclaw_report(
            report_path=args.report.expanduser(),
            sync_root=args.sync_root.expanduser() if args.vault_path is None else None,
            vault_path=args.vault_path.expanduser() if args.vault_path else None,
            artifacts_root=args.artifacts_root.expanduser() if args.artifacts_root else None,
            root_note_path=args.root_note_path.expanduser() if args.root_note_path else None,
            pipeline_root=args.pipeline_root.expanduser() if args.pipeline_root else None,
        )
        emit_payload(result.to_dict(), as_json=args.json, printer=print_report_apply_summary)
        return 0

    if args.command == "queue-picoclaw-report":
        result = queue_picoclaw_report(
            report_path=args.report.expanduser(),
            sync_root=args.sync_root.expanduser() if args.vault_path is None else None,
            vault_path=args.vault_path.expanduser() if args.vault_path else None,
            artifacts_root=args.artifacts_root.expanduser() if args.artifacts_root else None,
            root_note_path=args.root_note_path.expanduser() if args.root_note_path else None,
            pipeline_root=args.pipeline_root.expanduser() if args.pipeline_root else None,
            run_pipeline=args.run_pipeline,
        )
        emit_payload(result.to_dict(), as_json=args.json, printer=print_queue_report_summary)
        return 0

    if args.command == "record-agent-reference":
        result = record_agent_references(
            referenced_note_paths=args.note_paths or [],
            referenced_at=args.referenced_at,
            sync_root=args.sync_root.expanduser() if args.vault_path is None else None,
            vault_path=args.vault_path.expanduser() if args.vault_path else None,
            artifacts_root=args.artifacts_root.expanduser() if args.artifacts_root else None,
        )
        emit_payload(result.to_dict(), as_json=args.json, printer=print_agent_reference_summary)
        return 0

    if args.command == "refresh-destination-mocs":
        result = refresh_destination_mocs(
            sync_root=args.sync_root.expanduser() if args.vault_path is None else None,
            vault_path=args.vault_path.expanduser() if args.vault_path else None,
            artifacts_root=args.artifacts_root.expanduser() if args.artifacts_root else None,
            destination_vaults=args.destination_vaults,
            generated_at=args.generated_at,
        )
        emit_payload(result.to_dict(), as_json=args.json, printer=print_refresh_summary)
        return 0

    if args.command == "run-pipeline-once":
        result = run_pipeline_once(
            sync_root=args.sync_root.expanduser() if args.vault_path is None else None,
            vault_path=args.vault_path.expanduser() if args.vault_path else None,
            artifacts_root=args.artifacts_root.expanduser() if args.artifacts_root else None,
            root_note_path=args.root_note_path.expanduser() if args.root_note_path else None,
            pipeline_root=args.pipeline_root.expanduser() if args.pipeline_root else None,
            generated_at=args.generated_at,
        )
        emit_payload(result.to_dict(), as_json=args.json, printer=print_pipeline_run_summary)
        return 0

    if args.command == "dispatch-picoclaw-handoff":
        result = dispatch_handoff_to_picoclaw(
            handoff_path=args.handoff.expanduser(),
            sync_root=args.sync_root.expanduser() if args.vault_path is None else None,
            vault_path=args.vault_path.expanduser() if args.vault_path else None,
            artifacts_root=args.artifacts_root.expanduser() if args.artifacts_root else None,
            root_note_path=args.root_note_path.expanduser() if args.root_note_path else None,
            pipeline_root=args.pipeline_root.expanduser() if args.pipeline_root else None,
            run_pipeline=not args.no_run_pipeline,
        )
        emit_payload(result.to_dict(), as_json=args.json, printer=print_dispatch_summary)
        return 0

    if args.command == "listen":
        serve_loopback(
            sync_root=args.sync_root.expanduser() if args.vault_path is None else None,
            vault_path=args.vault_path.expanduser() if args.vault_path else None,
            artifacts_root=args.artifacts_root.expanduser() if args.artifacts_root else None,
            root_note_path=args.root_note_path.expanduser() if args.root_note_path else None,
            pipeline_root=args.pipeline_root.expanduser() if args.pipeline_root else None,
            host=args.host,
            port=args.port,
            run_pipeline=args.run_pipeline,
        )
        return 0

    if args.command == "query-memory":
        result = query_memory(
            query=args.query,
            sync_root=args.sync_root.expanduser() if args.vault_path is None else None,
            vault_path=args.vault_path.expanduser() if args.vault_path else None,
            artifacts_root=args.artifacts_root.expanduser() if args.artifacts_root else None,
            generated_at=args.generated_at or now_iso(),
            limit=args.limit,
        )
        emit_payload(result.to_dict(), as_json=args.json, printer=print_memory_query_summary)
        return 0

    if args.command == "import-session-insights":
        result = import_session_insights(
            sync_root=args.sync_root.expanduser() if args.vault_path is None else None,
            vault_path=args.vault_path.expanduser() if args.vault_path else None,
            artifacts_root=args.artifacts_root.expanduser() if args.artifacts_root else None,
            insights_path=args.insights.expanduser() if args.insights else None,
            lesson_path=args.lesson.expanduser() if args.lesson else None,
            decision_path=args.decision.expanduser() if args.decision else None,
            skill_cards_path=args.skill_cards.expanduser() if args.skill_cards else None,
            skill_links_path=args.skill_links.expanduser() if args.skill_links else None,
            generated_at=args.generated_at or now_iso(),
        )
        emit_payload(result.to_dict(), as_json=args.json, printer=print_import_session_insights_summary)
        return 0

    if args.command == "wake-up":
        result = build_wake_up_bundle(
            sync_root=args.sync_root.expanduser() if args.vault_path is None else None,
            vault_path=args.vault_path.expanduser() if args.vault_path else None,
            artifacts_root=args.artifacts_root.expanduser() if args.artifacts_root else None,
            generated_at=args.generated_at or now_iso(),
        )
        emit_payload(result.to_dict(), as_json=args.json, printer=print_wakeup_summary)
        return 0

    if args.command == "dream":
        result = run_dream_mode(
            sync_root=args.sync_root.expanduser() if args.vault_path is None else None,
            vault_path=args.vault_path.expanduser() if args.vault_path else None,
            artifacts_root=args.artifacts_root.expanduser() if args.artifacts_root else None,
            generated_at=args.generated_at or now_iso(),
        )
        emit_payload(result.to_dict(), as_json=args.json, printer=print_dream_summary)
        return 0

    if args.command == "distill-persona-goals":
        result = distill_persona_goals(
            sync_root=args.sync_root.expanduser() if args.vault_path is None else None,
            vault_path=args.vault_path.expanduser() if args.vault_path else None,
            artifacts_root=args.artifacts_root.expanduser() if args.artifacts_root else None,
            generated_at=args.generated_at or now_iso(),
            apply=args.apply,
        )
        emit_payload(result.to_dict(), as_json=args.json, printer=print_persona_goal_summary)
        return 0

    if args.command == "synthesize-memory":
        result = synthesize_memory(
            query=args.query,
            sync_root=args.sync_root.expanduser() if args.vault_path is None else None,
            vault_path=args.vault_path.expanduser() if args.vault_path else None,
            artifacts_root=args.artifacts_root.expanduser() if args.artifacts_root else None,
            generated_at=args.generated_at or now_iso(),
            limit=args.limit,
            write_artifact=args.write_artifact,
        )
        emit_payload(result.to_dict(), as_json=args.json, printer=print_synthesis_summary)
        return 0

    parser.error(f"unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
