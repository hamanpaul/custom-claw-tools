from __future__ import annotations

import argparse
import json
from pathlib import Path

from .engine import build_workspace, load_last_run, resolve_paths


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
        payload = result.to_dict()
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print_build_summary(payload)
        return 0

    if args.command == "stats":
        paths = resolve_paths(
            sync_root=args.sync_root.expanduser() if args.vault_path is None else None,
            vault_path=args.vault_path.expanduser() if args.vault_path else None,
            artifacts_root=args.artifacts_root.expanduser() if args.artifacts_root else None,
        )
        payload = load_last_run(paths.last_run_path)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print_build_summary(payload)
        return 0

    parser.error(f"unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
