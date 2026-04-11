from __future__ import annotations

import json
import tempfile
import unittest
from http.client import HTTPConnection
from pathlib import Path
from threading import Thread
from unittest.mock import patch

from obs_auto_moc.engine import (
    apply_picoclaw_report,
    build_picoclaw_dispatch_prompt,
    build_picoclaw_dispatch_session,
    build_workspace,
    dispatch_handoff_to_picoclaw,
    extract_json_block,
    monitor_root_note,
    parse_markdown_text,
    queue_picoclaw_report,
    record_agent_references,
    refresh_destination_mocs,
    run_pipeline_once,
)
from obs_auto_moc.server import serve_loopback


class ParseMarkdownTextTest(unittest.TestCase):
    def test_detects_duplicate_frontmatter_block(self) -> None:
        parsed = parse_markdown_text(
            "---\n"
            "title: Demo\n"
            "tags: [alpha]\n"
            "---\n"
            "---\n"
            "tags:\n"
            "  - beta\n"
            "---\n"
            "body\n"
        )
        self.assertTrue(parsed.has_frontmatter)
        self.assertTrue(parsed.duplicate_frontmatter)
        self.assertIsNone(parsed.parse_error)
        self.assertEqual(parsed.frontmatter["title"], "Demo")

    def test_reports_yaml_parse_error(self) -> None:
        parsed = parse_markdown_text("---\ntitle: [oops\n---\nbody\n")
        self.assertTrue(parsed.has_frontmatter)
        self.assertIsNotNone(parsed.parse_error)


class BuildPicoclawDispatchPromptTest(unittest.TestCase):
    def test_prompt_demands_real_json_block_not_placeholder(self) -> None:
        prompt = build_picoclaw_dispatch_prompt(
            handoff_payload={
                "job_id": "root-note-20260331060000-feedface",
                "entries": [],
            },
            callback_endpoint="http://127.0.0.1:43120/picoclaw/report",
        )

        self.assertIn("不要輸出 `{...json report...}`", prompt)
        self.assertIn('PICOCLAW_REPORT_BEGIN\n{"job_id":"<job_id>"', prompt)
        self.assertIn("每一個 entry 都必須在 report entries[] 中剛好出現一次", prompt)


class BuildPicoclawDispatchSessionTest(unittest.TestCase):
    def test_appends_job_id_by_default(self) -> None:
        self.assertEqual(
            build_picoclaw_dispatch_session("cron:obs-auto-moc", "root-note-20260331060000-feedface"),
            "cron:obs-auto-moc:root-note-20260331060000-feedface",
        )

    def test_supports_job_id_placeholder(self) -> None:
        self.assertEqual(
            build_picoclaw_dispatch_session("cron:obs-auto-moc:{job_id}", "root-note-20260331060000-feedface"),
            "cron:obs-auto-moc:root-note-20260331060000-feedface",
        )


class BuildWorkspaceTest(unittest.TestCase):
    def test_build_workspace_generates_manifest_preview_and_apply(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sync_root = root / "sync"
            config_dir = sync_root / "vault-id"
            vault_path = root / "notes"
            (vault_path / "TechVault").mkdir(parents=True)
            (vault_path / "WorkVault").mkdir(parents=True)
            (vault_path / "PersonalVault").mkdir(parents=True)
            (vault_path / ".obsidian").mkdir(parents=True)
            config_dir.mkdir(parents=True)
            (config_dir / "config.json").write_text(
                json.dumps({"vaultPath": str(vault_path)}),
                encoding="utf-8",
            )

            (vault_path / "TechVault" / "alpha.md").write_text(
                "---\n"
                "title: Alpha\n"
                "tags: [project, demo]\n"
                "updated_at: 2026-03-28\n"
                "status: active\n"
                "moc_targets: [workbench]\n"
                "---\n"
                "Links to [[beta]] and [[missing-note]].\n",
                encoding="utf-8",
            )
            (vault_path / "WorkVault" / "beta.md").write_text(
                "---\n"
                "title: Beta\n"
                "tags:\n"
                "  - work\n"
                "updated_at: 2026-03-27\n"
                "status: draft\n"
                "---\n"
                "Links back to [[Alpha]].\n",
                encoding="utf-8",
            )
            (vault_path / "PersonalVault" / "orphan.md").write_text(
                "---\n"
                "title: Orphan\n"
                "tags: [personal]\n"
                "---\n"
                "No links here.\n",
                encoding="utf-8",
            )
            (vault_path / "TechVault" / "decayed.md").write_text(
                "---\n"
                "title: Decayed\n"
                "tags: [tech, decayed]\n"
                "status: decayed\n"
                "decayed: true\n"
                "---\n"
                "Sleepy note.\n",
                encoding="utf-8",
            )
            (vault_path / "ObsToolsVault").mkdir(parents=True)
            (vault_path / "ObsToolsVault" / "rules.md").write_text(
                "---\n"
                "title: Rules\n"
                "tags: [rules]\n"
                "---\n"
                "Should stay outside build scope.\n",
                encoding="utf-8",
            )

            result = build_workspace(sync_root=sync_root, generated_at="2026-03-28T00:00:00+00:00", apply=True)

            manifest_path = vault_path / "claw" / "moc" / "index-manifest.jsonl"
            preview_path = vault_path / "claw" / "moc" / "MOC.preview.md"
            proposal_path = vault_path / "claw" / "moc" / "proposals" / "2026-03-28-moc-proposal.md"
            moc_path = vault_path / "MOC.md"
            last_run_path = vault_path / "claw" / "moc" / "last-run.json"

            self.assertEqual(result.notes_scanned, 3)
            self.assertTrue(manifest_path.exists())
            self.assertTrue(preview_path.exists())
            self.assertTrue(proposal_path.exists())
            self.assertTrue(moc_path.exists())
            self.assertTrue(last_run_path.exists())

            manifest_rows = [json.loads(line) for line in manifest_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(len(manifest_rows), 3)
            self.assertTrue(any(row["note_name"] == "alpha" for row in manifest_rows))
            self.assertFalse(any(row["note_name"] == "decayed" for row in manifest_rows))
            self.assertFalse(any(row["note_name"] == "rules" for row in manifest_rows))

            preview_text = preview_path.read_text(encoding="utf-8")
            proposal_text = proposal_path.read_text(encoding="utf-8")
            moc_text = moc_path.read_text(encoding="utf-8")

            self.assertIn("## TechVault", preview_text)
            self.assertIn("## Issues to review", proposal_text)
            self.assertIn("mode: apply", moc_text)


class RootNotePipelineTest(unittest.TestCase):
    def test_extract_json_block_parses_wrapped_report(self) -> None:
        payload = extract_json_block(
            "noise\nPICOCLAW_REPORT_BEGIN\n{\n  \"job_id\": \"demo\"\n}\nPICOCLAW_REPORT_END\n",
            start_marker="PICOCLAW_REPORT_BEGIN",
            end_marker="PICOCLAW_REPORT_END",
        )
        self.assertEqual(payload["job_id"], "demo")

    def test_monitor_root_note_emits_picoclaw_handoff_for_changed_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sync_root = root / "sync"
            config_dir = sync_root / "vault-id"
            vault_path = root / "notes"
            root_note_path = vault_path / "root-note"
            config_dir.mkdir(parents=True)
            root_note_path.mkdir(parents=True)
            (vault_path / "TechVault").mkdir(parents=True)
            (vault_path / "WorkVault").mkdir(parents=True)
            (vault_path / "PersonalVault").mkdir(parents=True)
            (config_dir / "config.json").write_text(
                json.dumps({"vaultPath": str(vault_path)}),
                encoding="utf-8",
            )
            (root_note_path / "entry.md").write_text(
                "---\n"
                "title: Inbox Entry\n"
                "tags: [inbox]\n"
                "---\n"
                "Pending organization.\n",
                encoding="utf-8",
            )

            result = monitor_root_note(sync_root=sync_root, generated_at="2026-03-31T00:00:00+00:00")

            self.assertTrue(result.root_note_exists)
            self.assertEqual(result.scanned_files, 1)
            self.assertEqual(result.handed_off_files, 1)
            self.assertIsNotNone(result.job_id)
            self.assertIsNotNone(result.handoff_path)

            handoff_payload = json.loads(result.handoff_path.read_text(encoding="utf-8"))
            self.assertEqual(handoff_payload["job_id"], result.job_id)
            self.assertEqual(handoff_payload["destination_vaults"], ["TechVault", "WorkVault", "PersonalVault"])
            self.assertEqual(handoff_payload["ruleset"]["source"], "ObsToolsVault/README.md")
            self.assertEqual(handoff_payload["callback_contract"]["endpoint"], "http://127.0.0.1:45460/picoclaw-report")
            self.assertEqual(handoff_payload["entries"][0]["source_path"], "root-note/entry.md")
            self.assertEqual(handoff_payload["vault_path"], str(vault_path))
            self.assertEqual(handoff_payload["destination_root_paths"]["TechVault"], str(vault_path / "TechVault"))

            second_result = monitor_root_note(sync_root=sync_root, generated_at="2026-03-31T00:05:00+00:00")
            self.assertEqual(second_result.handed_off_files, 0)
            self.assertEqual(second_result.unchanged_files, 1)

            third_result = monitor_root_note(sync_root=sync_root, generated_at="2026-03-31T02:05:00+00:00")
            self.assertEqual(third_result.handed_off_files, 1)
            self.assertEqual(third_result.unchanged_files, 0)

    def test_apply_picoclaw_report_refreshes_only_touched_destination_mocs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sync_root = root / "sync"
            config_dir = sync_root / "vault-id"
            vault_path = root / "notes"
            root_note_path = vault_path / "root-note"
            tech_path = vault_path / "TechVault"
            work_path = vault_path / "WorkVault"
            personal_path = vault_path / "PersonalVault"
            config_dir.mkdir(parents=True)
            root_note_path.mkdir(parents=True)
            tech_path.mkdir(parents=True)
            work_path.mkdir(parents=True)
            personal_path.mkdir(parents=True)
            (config_dir / "config.json").write_text(
                json.dumps({"vaultPath": str(vault_path)}),
                encoding="utf-8",
            )

            root_note_file = root_note_path / "entry.md"
            source_text = (
                "---\n"
                "title: Inbox Entry\n"
                "tags: [inbox]\n"
                "---\n"
                "Already reviewed.\n"
            )
            root_note_file.write_text(source_text, encoding="utf-8")
            monitor_result = monitor_root_note(sync_root=sync_root, generated_at="2026-03-31T00:00:00+00:00")

            (tech_path / "atomic-note.md").write_text(
                "---\n"
                "title: Atomic Note\n"
                "tags: [tech]\n"
                "atomized_from: entry\n"
                "---\n"
                "Linked from root-note.\n",
                encoding="utf-8",
            )

            report_path = root / "picoclaw-report.json"
            report_path.write_text(
                json.dumps(
                    {
                        "job_id": monitor_result.job_id,
                        "reported_by": "PicoClaw",
                        "completed_at": "2026-03-31T00:10:00+00:00",
                        "entries": [
                            {
                                "source_path": "root-note/entry.md",
                                "fingerprint": monitor_result.handoff_path
                                and json.loads(monitor_result.handoff_path.read_text(encoding="utf-8"))["entries"][0]["fingerprint"],
                                "status": "processed",
                                "outputs": [
                                    {
                                        "destination_vault": "TechVault",
                                        "note_path": "TechVault/atomic-note.md",
                                        "title": "Atomic Note",
                                        "tags": ["tech"],
                                    }
                                ],
                            }
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            result = apply_picoclaw_report(report_path=report_path, sync_root=sync_root)

            self.assertEqual(result.processed_count, 1)
            self.assertEqual(result.touched_destination_vaults, ["TechVault"])
            self.assertIn("TechVault", result.destination_mocs)
            self.assertNotIn("WorkVault", result.destination_mocs)

            tech_moc_text = (tech_path / "MOC.md").read_text(encoding="utf-8")
            self.assertIn("# TechVault MOC", tech_moc_text)
            self.assertIn("[[Atomic Note]]", tech_moc_text)

            state_payload = json.loads(result.state_path.read_text(encoding="utf-8"))
            self.assertEqual(state_payload["entries"]["root-note/entry.md"]["status"], "processed")

    def test_apply_picoclaw_report_rejects_source_path_outside_root_note(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sync_root = root / "sync"
            config_dir = sync_root / "vault-id"
            vault_path = root / "notes"
            config_dir.mkdir(parents=True)
            (vault_path / "root-note").mkdir(parents=True)
            (vault_path / "TechVault").mkdir(parents=True)
            (vault_path / "WorkVault").mkdir(parents=True)
            (vault_path / "PersonalVault").mkdir(parents=True)
            (config_dir / "config.json").write_text(
                json.dumps({"vaultPath": str(vault_path)}),
                encoding="utf-8",
            )

            report_path = root / "picoclaw-report.json"
            report_path.write_text(
                json.dumps(
                    {
                        "job_id": "root-note-20260331000000-deadbeef",
                        "reported_by": "PicoClaw",
                        "completed_at": "2026-03-31T00:10:00+00:00",
                        "entries": [
                            {
                                "source_path": "../outside.md",
                                "fingerprint": "abc",
                                "status": "skipped",
                                "outputs": [],
                            }
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(RuntimeError, "source_path must stay under root-note/"):
                apply_picoclaw_report(report_path=report_path, sync_root=sync_root)

    def test_apply_picoclaw_report_marks_missing_destination_note_failed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sync_root = root / "sync"
            config_dir = sync_root / "vault-id"
            vault_path = root / "notes"
            root_note_path = vault_path / "root-note"
            config_dir.mkdir(parents=True)
            root_note_path.mkdir(parents=True)
            (vault_path / "TechVault").mkdir(parents=True)
            (vault_path / "WorkVault").mkdir(parents=True)
            (vault_path / "PersonalVault").mkdir(parents=True)
            (config_dir / "config.json").write_text(
                json.dumps({"vaultPath": str(vault_path)}),
                encoding="utf-8",
            )
            (root_note_path / "entry.md").write_text(
                "---\n"
                "title: Inbox Entry\n"
                "tags: [inbox]\n"
                "---\n"
                "Already reviewed.\n",
                encoding="utf-8",
            )
            monitor_result = monitor_root_note(sync_root=sync_root, generated_at="2026-03-31T00:00:00+00:00")
            handoff_payload = json.loads(monitor_result.handoff_path.read_text(encoding="utf-8"))

            report_path = root / "picoclaw-report.json"
            report_path.write_text(
                json.dumps(
                    {
                        "job_id": monitor_result.job_id,
                        "reported_by": "PicoClaw",
                        "completed_at": "2026-03-31T00:10:00+00:00",
                        "entries": [
                            {
                                "source_path": "root-note/entry.md",
                                "fingerprint": handoff_payload["entries"][0]["fingerprint"],
                                "status": "processed",
                                "outputs": [
                                    {
                                        "destination_vault": "TechVault",
                                        "note_path": "TechVault/missing-note.md",
                                    }
                                ],
                            }
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            result = apply_picoclaw_report(report_path=report_path, sync_root=sync_root)

            self.assertEqual(result.processed_count, 0)
            self.assertEqual(result.failed_count, 1)
            self.assertTrue(result.archived_report_path.exists())
            state_payload = json.loads(result.state_path.read_text(encoding="utf-8"))
            self.assertEqual(state_payload["entries"]["root-note/entry.md"]["status"], "failed")
            self.assertIn("missing destination note", state_payload["entries"]["root-note/entry.md"]["last_error"])

    def test_apply_picoclaw_report_reactivates_decayed_references_and_rebuilds_related_links(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sync_root = root / "sync"
            config_dir = sync_root / "vault-id"
            vault_path = root / "notes"
            root_note_path = vault_path / "root-note"
            tech_path = vault_path / "TechVault"
            work_path = vault_path / "WorkVault"
            personal_path = vault_path / "PersonalVault"
            config_dir.mkdir(parents=True)
            root_note_path.mkdir(parents=True)
            tech_path.mkdir(parents=True)
            work_path.mkdir(parents=True)
            personal_path.mkdir(parents=True)
            (config_dir / "config.json").write_text(
                json.dumps({"vaultPath": str(vault_path)}),
                encoding="utf-8",
            )

            root_note_file = root_note_path / "entry.md"
            root_note_file.write_text(
                "---\n"
                "title: Inbox Entry\n"
                "tags: [inbox]\n"
                "---\n"
                "Already reviewed.\n",
                encoding="utf-8",
            )
            monitor_result = monitor_root_note(sync_root=sync_root, generated_at="2026-03-31T00:00:00+00:00")
            handoff_payload = json.loads(monitor_result.handoff_path.read_text(encoding="utf-8"))

            (tech_path / "atomic-note.md").write_text(
                "---\n"
                "title: Atomic Note\n"
                "tags: [tech]\n"
                "---\n"
                "Linked from root-note.\n",
                encoding="utf-8",
            )
            dormant_tech = tech_path / "dormant-a.md"
            dormant_tech.write_text(
                "---\n"
                "title: Dormant A\n"
                "tags: [tech, decayed]\n"
                "status: decayed\n"
                "decayed: true\n"
                "---\n"
                "sleep\n",
                encoding="utf-8",
            )
            dormant_work = work_path / "dormant-b.md"
            dormant_work.write_text(
                "---\n"
                "title: Dormant B\n"
                "tags: [work, decayed]\n"
                "status: decayed\n"
                "decayed: true\n"
                "---\n"
                "sleep\n",
                encoding="utf-8",
            )

            report_path = root / "picoclaw-report.json"
            report_path.write_text(
                json.dumps(
                    {
                        "job_id": monitor_result.job_id,
                        "reported_by": "PicoClaw",
                        "completed_at": "2026-03-31T00:10:00+00:00",
                        "referenced_note_paths": [
                            "TechVault/dormant-a.md",
                            "WorkVault/dormant-b.md",
                        ],
                        "entries": [
                            {
                                "source_path": "root-note/entry.md",
                                "fingerprint": handoff_payload["entries"][0]["fingerprint"],
                                "status": "processed",
                                "outputs": [
                                    {
                                        "destination_vault": "TechVault",
                                        "note_path": "TechVault/atomic-note.md",
                                    }
                                ],
                            }
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            result = apply_picoclaw_report(report_path=report_path, sync_root=sync_root)

            self.assertEqual(set(result.reactivated_note_paths), {"TechVault/dormant-a.md", "WorkVault/dormant-b.md"})
            self.assertEqual(
                set(result.relation_updated_note_paths),
                {"TechVault/dormant-a.md", "WorkVault/dormant-b.md"},
            )
            self.assertIn("TechVault", result.destination_mocs)
            self.assertIn("WorkVault", result.destination_mocs)

            dormant_tech_text = dormant_tech.read_text(encoding="utf-8")
            dormant_work_text = dormant_work.read_text(encoding="utf-8")
            self.assertIn("decayed: false", dormant_tech_text)
            self.assertIn("status: active", dormant_tech_text)
            self.assertIn("[[WorkVault/dormant-b]]", dormant_tech_text)
            self.assertIn("decayed: false", dormant_work_text)
            self.assertIn("status: active", dormant_work_text)
            self.assertIn("[[TechVault/dormant-a]]", dormant_work_text)
            self.assertEqual(parse_markdown_text(dormant_tech_text).frontmatter["last_resonated_at"], "2026-03-31T00:10:00+00:00")
            self.assertEqual(parse_markdown_text(dormant_work_text).frontmatter["last_resonated_at"], "2026-03-31T00:10:00+00:00")

    def test_refresh_destination_mocs_updates_requested_destination_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sync_root = root / "sync"
            config_dir = sync_root / "vault-id"
            vault_path = root / "notes"
            tech_path = vault_path / "TechVault"
            work_path = vault_path / "WorkVault"
            personal_path = vault_path / "PersonalVault"
            config_dir.mkdir(parents=True)
            tech_path.mkdir(parents=True)
            work_path.mkdir(parents=True)
            personal_path.mkdir(parents=True)
            (config_dir / "config.json").write_text(
                json.dumps({"vaultPath": str(vault_path)}),
                encoding="utf-8",
            )

            (tech_path / "alpha.md").write_text(
                "---\n"
                "title: Alpha\n"
                "tags: [tech]\n"
                "---\n"
                "tech body\n",
                encoding="utf-8",
            )
            (work_path / "beta.md").write_text(
                "---\n"
                "title: Beta\n"
                "tags: [work]\n"
                "---\n"
                "work body\n",
                encoding="utf-8",
            )

            result = refresh_destination_mocs(
                sync_root=sync_root,
                destination_vaults=["WorkVault"],
                generated_at="2026-03-31T01:00:00+00:00",
            )

            self.assertEqual(set(result.destination_mocs.keys()), {"WorkVault"})
            self.assertFalse((tech_path / "MOC.md").exists())
            self.assertTrue((work_path / "MOC.md").exists())
            work_moc_text = (work_path / "MOC.md").read_text(encoding="utf-8")
            self.assertIn("# WorkVault MOC", work_moc_text)
            self.assertIn("[[Beta]]", work_moc_text)

    def test_run_pipeline_once_applies_report_inbox_then_emits_next_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sync_root = root / "sync"
            config_dir = sync_root / "vault-id"
            vault_path = root / "notes"
            root_note_path = vault_path / "root-note"
            tech_path = vault_path / "TechVault"
            work_path = vault_path / "WorkVault"
            personal_path = vault_path / "PersonalVault"
            config_dir.mkdir(parents=True)
            root_note_path.mkdir(parents=True)
            tech_path.mkdir(parents=True)
            work_path.mkdir(parents=True)
            personal_path.mkdir(parents=True)
            (config_dir / "config.json").write_text(
                json.dumps({"vaultPath": str(vault_path)}),
                encoding="utf-8",
            )

            first_entry = root_note_path / "entry-one.md"
            first_entry.write_text(
                "---\n"
                "title: First Entry\n"
                "tags: [inbox]\n"
                "---\n"
                "ready one\n",
                encoding="utf-8",
            )
            first_monitor = monitor_root_note(sync_root=sync_root, generated_at="2026-03-31T00:00:00+00:00")
            first_handoff = json.loads(first_monitor.handoff_path.read_text(encoding="utf-8"))
            (tech_path / "atomic-note.md").write_text(
                "---\n"
                "title: Atomic Note\n"
                "tags: [tech]\n"
                "atomized_from: entry-one\n"
                "---\n"
                "tech body\n",
                encoding="utf-8",
            )

            second_entry = root_note_path / "entry-two.md"
            second_entry.write_text(
                "---\n"
                "title: Second Entry\n"
                "tags: [inbox]\n"
                "---\n"
                "ready two\n",
                encoding="utf-8",
            )

            pipeline_root = vault_path / "claw" / "moc" / "pipeline"
            report_inbox = pipeline_root / "picoclaw-report-inbox"
            report_inbox.mkdir(parents=True, exist_ok=True)
            (report_inbox / "done.json").write_text(
                json.dumps(
                    {
                        "job_id": first_monitor.job_id,
                        "reported_by": "PicoClaw",
                        "completed_at": "2026-03-31T00:10:00+00:00",
                        "entries": [
                            {
                                "source_path": "root-note/entry-one.md",
                                "fingerprint": first_handoff["entries"][0]["fingerprint"],
                                "status": "processed",
                                "outputs": [
                                    {
                                        "destination_vault": "TechVault",
                                        "note_path": "TechVault/atomic-note.md",
                                    }
                                ],
                            }
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            result = run_pipeline_once(sync_root=sync_root, generated_at="2026-03-31T00:20:00+00:00")

            self.assertEqual(result.reports_discovered, 1)
            self.assertEqual(result.reports_applied, 1)
            self.assertEqual(result.handed_off_files, 1)
            self.assertTrue((tech_path / "MOC.md").exists())
            self.assertFalse((report_inbox / "done.json").exists())
            handoff_payload = json.loads(Path(result.handoff_path).read_text(encoding="utf-8"))
            self.assertEqual(handoff_payload["entries"][0]["source_path"], "root-note/entry-two.md")

    def test_run_pipeline_once_quarantines_invalid_report_and_retries_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sync_root = root / "sync"
            config_dir = sync_root / "vault-id"
            vault_path = root / "notes"
            root_note_path = vault_path / "root-note"
            config_dir.mkdir(parents=True)
            root_note_path.mkdir(parents=True)
            (vault_path / "TechVault").mkdir(parents=True)
            (vault_path / "WorkVault").mkdir(parents=True)
            (vault_path / "PersonalVault").mkdir(parents=True)
            (config_dir / "config.json").write_text(json.dumps({"vaultPath": str(vault_path)}), encoding="utf-8")
            (root_note_path / "entry.md").write_text("---\ntitle: Inbox\n---\nbody\n", encoding="utf-8")

            first_monitor = monitor_root_note(sync_root=sync_root, generated_at="2026-03-31T00:00:00+00:00")
            pipeline_root = vault_path / "claw" / "moc" / "pipeline"
            report_inbox = pipeline_root / "picoclaw-report-inbox"
            report_inbox.mkdir(parents=True, exist_ok=True)
            bad_report_path = report_inbox / f"{first_monitor.job_id}.json"
            bad_report_path.write_text("{not valid json\n", encoding="utf-8")

            result = run_pipeline_once(sync_root=sync_root, generated_at="2026-03-31T00:20:00+00:00")

            self.assertEqual(result.reports_discovered, 1)
            self.assertEqual(result.reports_applied, 0)
            self.assertEqual(result.reports_failed, 1)
            self.assertFalse(bad_report_path.exists())
            self.assertEqual(len(result.failed_report_paths), 1)
            self.assertTrue(Path(result.failed_report_paths[0]).exists())
            self.assertEqual(result.handed_off_files, 1)
            self.assertIsNotNone(result.handoff_path)
            self.assertTrue(Path(result.handoff_path).exists())

            state_payload = json.loads(result.state_path.read_text(encoding="utf-8"))
            self.assertEqual(state_payload["entries"]["root-note/entry.md"]["status"], "handed_off_to_picoclaw")
            self.assertNotEqual(state_payload["entries"]["root-note/entry.md"]["last_job_id"], first_monitor.job_id)

    def test_dispatch_handoff_to_picoclaw_runs_agent_and_queues_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sync_root = root / "sync"
            config_dir = sync_root / "vault-id"
            vault_path = root / "notes"
            root_note_path = vault_path / "root-note"
            tech_path = vault_path / "TechVault"
            config_dir.mkdir(parents=True)
            root_note_path.mkdir(parents=True)
            tech_path.mkdir(parents=True)
            (vault_path / "WorkVault").mkdir(parents=True)
            (vault_path / "PersonalVault").mkdir(parents=True)
            (config_dir / "config.json").write_text(json.dumps({"vaultPath": str(vault_path)}), encoding="utf-8")
            (root_note_path / "entry.md").write_text("---\ntitle: Inbox\n tags: [inbox]\n---\nbody\n".replace(" \n", "\n"), encoding="utf-8")
            handoff = monitor_root_note(sync_root=sync_root, generated_at="2026-03-31T06:00:00+00:00")
            handoff_payload = json.loads(handoff.handoff_path.read_text(encoding="utf-8"))
            (tech_path / "atomic.md").write_text("---\ntitle: Atomic\n tags: [tech]\n---\nbody\n".replace(" \n", "\n"), encoding="utf-8")

            report_payload = {
                "job_id": handoff.job_id,
                "reported_by": "PicoClaw",
                "completed_at": "2026-03-31T06:05:00+00:00",
                "entries": [
                    {
                        "source_path": "root-note/entry.md",
                        "fingerprint": handoff_payload["entries"][0]["fingerprint"],
                        "status": "processed",
                        "outputs": [
                            {
                                "destination_vault": "TechVault",
                                "note_path": "TechVault/atomic.md",
                            }
                        ],
                    }
                ],
            }
            agent_output = (
                "PICOCLAW_REPORT_BEGIN\n"
                + json.dumps(report_payload, ensure_ascii=False, indent=2)
                + "\nPICOCLAW_REPORT_END\n"
            )

            with patch("obs_auto_moc.engine.subprocess.run") as run:
                run.return_value = type(
                    "CompletedProcess",
                    (),
                    {
                        "returncode": 0,
                        "stdout": agent_output,
                        "stderr": "",
                    },
                )()
                result = dispatch_handoff_to_picoclaw(
                    handoff_path=handoff.handoff_path,
                    sync_root=sync_root,
                    run_pipeline=True,
                )

            command = run.call_args[0][0]
            session_value = command[command.index("--session") + 1]
            self.assertEqual(result.job_id, handoff.job_id)
            self.assertEqual(session_value, f"cron:obs-auto-moc:{handoff.job_id}")
            self.assertTrue(result.raw_output_log_path.exists())
            self.assertTrue(result.report_copy_path.exists())
            self.assertFalse(result.queued_report_path.exists())
            self.assertIsNotNone(result.pipeline_result)
            self.assertEqual(result.pipeline_result["reports_applied"], 1)
            self.assertTrue((tech_path / "MOC.md").exists())

    def test_dispatch_handoff_to_picoclaw_pads_missing_entries_as_failed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sync_root = root / "sync"
            config_dir = sync_root / "vault-id"
            vault_path = root / "notes"
            root_note_path = vault_path / "root-note"
            tech_path = vault_path / "TechVault"
            config_dir.mkdir(parents=True)
            root_note_path.mkdir(parents=True)
            tech_path.mkdir(parents=True)
            (vault_path / "WorkVault").mkdir(parents=True)
            (vault_path / "PersonalVault").mkdir(parents=True)
            (config_dir / "config.json").write_text(json.dumps({"vaultPath": str(vault_path)}), encoding="utf-8")
            (root_note_path / "entry-a.md").write_text("---\ntitle: A\n---\nbody\n", encoding="utf-8")
            (root_note_path / "entry-b.md").write_text("---\ntitle: B\n---\nbody\n", encoding="utf-8")
            handoff = monitor_root_note(sync_root=sync_root, generated_at="2026-03-31T06:00:00+00:00")
            handoff_payload = json.loads(handoff.handoff_path.read_text(encoding="utf-8"))
            (tech_path / "atomic.md").write_text("---\ntitle: Atomic\n---\nbody\n", encoding="utf-8")

            report_payload = {
                "job_id": handoff.job_id,
                "reported_by": "PicoClaw",
                "completed_at": "2026-03-31T06:05:00+00:00",
                "entries": [
                    {
                        "source_path": handoff_payload["entries"][0]["source_path"],
                        "fingerprint": handoff_payload["entries"][0]["fingerprint"],
                        "status": "processed",
                        "outputs": [
                            {
                                "destination_vault": "TechVault",
                                "note_path": "TechVault/atomic.md",
                            }
                        ],
                    }
                ],
            }
            agent_output = (
                "PICOCLAW_REPORT_BEGIN\n"
                + json.dumps(report_payload, ensure_ascii=False, indent=2)
                + "\nPICOCLAW_REPORT_END\n"
            )

            with patch("obs_auto_moc.engine.subprocess.run") as run:
                run.return_value = type(
                    "CompletedProcess",
                    (),
                    {
                        "returncode": 0,
                        "stdout": agent_output,
                        "stderr": "",
                    },
                )()
                result = dispatch_handoff_to_picoclaw(
                    handoff_path=handoff.handoff_path,
                    sync_root=sync_root,
                    run_pipeline=False,
                )

            queued_report = json.loads(result.queued_report_path.read_text(encoding="utf-8"))
            self.assertEqual(len(queued_report["entries"]), 2)
            missing_entry = next(entry for entry in queued_report["entries"] if entry["source_path"] == "root-note/entry-b.md")
            self.assertEqual(missing_entry["status"], "failed")
            self.assertIn("missing from PicoClaw report", missing_entry["warnings"][0])

    def test_dispatch_handoff_to_picoclaw_uses_local_fallback_for_stale_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sync_root = root / "sync"
            config_dir = sync_root / "vault-id"
            vault_path = root / "notes"
            root_note_path = vault_path / "root-note"
            tech_path = vault_path / "TechVault"
            config_dir.mkdir(parents=True)
            root_note_path.mkdir(parents=True)
            tech_path.mkdir(parents=True)
            (vault_path / "WorkVault").mkdir(parents=True)
            (vault_path / "PersonalVault").mkdir(parents=True)
            (config_dir / "config.json").write_text(json.dumps({"vaultPath": str(vault_path)}), encoding="utf-8")
            (root_note_path / "entry-a.md").write_text("---\ntitle: A\n---\nbody a\n", encoding="utf-8")
            (root_note_path / "entry-b.md").write_text("---\ntitle: B\n---\nbody b\n", encoding="utf-8")
            handoff = monitor_root_note(sync_root=sync_root, generated_at="2026-03-31T06:00:00+00:00")

            stale_report_payload = {
                "job_id": "root-note-20260331055555-deadbeef",
                "reported_by": "PicoClaw",
                "completed_at": "2026-03-31T06:05:00+00:00",
                "entries": [
                    {
                        "source_path": "root-note/entry-a.md",
                        "fingerprint": "deadbeef",
                        "status": "processed",
                        "outputs": [
                            {
                                "destination_vault": "TechVault",
                                "note_path": "TechVault/entry-a.md",
                            }
                        ],
                    }
                ],
            }
            agent_output = (
                "PICOCLAW_REPORT_BEGIN\n"
                + json.dumps(stale_report_payload, ensure_ascii=False, indent=2)
                + "\nPICOCLAW_REPORT_END\n"
            )

            with patch("obs_auto_moc.engine.subprocess.run") as run:
                run.return_value = type(
                    "CompletedProcess",
                    (),
                    {
                        "returncode": 0,
                        "stdout": agent_output,
                        "stderr": "",
                    },
                )()
                result = dispatch_handoff_to_picoclaw(
                    handoff_path=handoff.handoff_path,
                    sync_root=sync_root,
                    run_pipeline=False,
                )

            queued_report = json.loads(result.queued_report_path.read_text(encoding="utf-8"))
            self.assertEqual(queued_report["job_id"], handoff.job_id)
            self.assertEqual(queued_report["reported_by"], "obs-auto-moc-fallback")
            self.assertEqual(len(queued_report["entries"]), 2)
            self.assertTrue((tech_path / "entry-a.md").exists())
            self.assertTrue((tech_path / "entry-b.md").exists())

    def test_dispatch_handoff_to_picoclaw_surfaces_invalid_report_log_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sync_root = root / "sync"
            config_dir = sync_root / "vault-id"
            vault_path = root / "notes"
            root_note_path = vault_path / "root-note"
            config_dir.mkdir(parents=True)
            root_note_path.mkdir(parents=True)
            (vault_path / "TechVault").mkdir(parents=True)
            (vault_path / "WorkVault").mkdir(parents=True)
            (vault_path / "PersonalVault").mkdir(parents=True)
            (config_dir / "config.json").write_text(json.dumps({"vaultPath": str(vault_path)}), encoding="utf-8")
            (root_note_path / "entry.md").write_text("---\ntitle: Inbox\n---\nbody\n", encoding="utf-8")
            handoff = monitor_root_note(sync_root=sync_root, generated_at="2026-03-31T06:00:00+00:00")

            with patch("obs_auto_moc.engine.subprocess.run") as run:
                run.return_value = type(
                    "CompletedProcess",
                    (),
                    {
                        "returncode": 0,
                        "stdout": "not a valid PicoClaw report\n",
                        "stderr": "",
                    },
                )()
                with self.assertRaisesRegex(RuntimeError, rf"see .*{handoff.job_id}\.agent\.log"):
                    dispatch_handoff_to_picoclaw(
                        handoff_path=handoff.handoff_path,
                        sync_root=sync_root,
                        run_pipeline=True,
                    )

            dispatch_log_path = vault_path / "claw" / "moc" / "pipeline" / "picoclaw-dispatch" / f"{handoff.job_id}.agent.log"
            self.assertTrue(dispatch_log_path.exists())

    def test_run_pipeline_once_auto_dispatches_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sync_root = root / "sync"
            config_dir = sync_root / "vault-id"
            vault_path = root / "notes"
            root_note_path = vault_path / "root-note"
            config_dir.mkdir(parents=True)
            root_note_path.mkdir(parents=True)
            (vault_path / "TechVault").mkdir(parents=True)
            (vault_path / "WorkVault").mkdir(parents=True)
            (vault_path / "PersonalVault").mkdir(parents=True)
            (config_dir / "config.json").write_text(json.dumps({"vaultPath": str(vault_path)}), encoding="utf-8")
            (root_note_path / "entry.md").write_text("---\ntitle: Inbox\n tags: [inbox]\n---\nbody\n".replace(" \n", "\n"), encoding="utf-8")

            with (
                patch("obs_auto_moc.engine.env_flag", return_value=True),
                patch("obs_auto_moc.engine.dispatch_handoff_to_picoclaw") as dispatch,
            ):
                dispatch.return_value = type(
                    "DispatchResult",
                    (),
                    {
                        "job_id": "root-note-20260331062000-feedface",
                        "raw_output_log_path": Path("/tmp/dispatch.log"),
                        "pipeline_result": {
                            "reports_discovered": 1,
                            "reports_applied": 1,
                            "archived_report_paths": ["/tmp/archive.json"],
                            "handoff_job_id": "root-note-20260331062100-facefeed",
                            "handoff_path": "/tmp/next-handoff.json",
                            "handed_off_files": 0,
                            "unchanged_files": 1,
                        },
                    },
                )()
                result = run_pipeline_once(sync_root=sync_root, generated_at="2026-03-31T06:20:00+00:00")

            self.assertTrue(result.dispatch_enabled)
            self.assertEqual(result.dispatch_attempted, 1)
            self.assertEqual(result.dispatch_succeeded, 1)
            self.assertEqual(result.dispatch_failed, 0)
            self.assertEqual(result.dispatched_job_ids, ["root-note-20260331062000-feedface"])
            self.assertEqual(result.reports_applied, 1)

    def test_run_pipeline_once_marks_auto_dispatch_failure_retryable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sync_root = root / "sync"
            config_dir = sync_root / "vault-id"
            vault_path = root / "notes"
            root_note_path = vault_path / "root-note"
            config_dir.mkdir(parents=True)
            root_note_path.mkdir(parents=True)
            (vault_path / "TechVault").mkdir(parents=True)
            (vault_path / "WorkVault").mkdir(parents=True)
            (vault_path / "PersonalVault").mkdir(parents=True)
            (config_dir / "config.json").write_text(json.dumps({"vaultPath": str(vault_path)}), encoding="utf-8")
            (root_note_path / "entry.md").write_text("---\ntitle: Inbox\n---\nbody\n", encoding="utf-8")

            with (
                patch("obs_auto_moc.engine.env_flag", return_value=True),
                patch("obs_auto_moc.engine.dispatch_handoff_to_picoclaw", side_effect=RuntimeError("bad dispatch")),
            ):
                result = run_pipeline_once(sync_root=sync_root, generated_at="2026-03-31T06:20:00+00:00")

            self.assertTrue(result.dispatch_enabled)
            self.assertEqual(result.dispatch_attempted, 1)
            self.assertEqual(result.dispatch_succeeded, 0)
            self.assertEqual(result.dispatch_failed, 1)

            state_payload = json.loads(result.state_path.read_text(encoding="utf-8"))
            self.assertEqual(state_payload["entries"]["root-note/entry.md"]["status"], "failed")
            self.assertEqual(state_payload["entries"]["root-note/entry.md"]["last_job_id"], result.handoff_job_id)
            self.assertIn("bad dispatch", state_payload["entries"]["root-note/entry.md"]["last_error"])

    def test_queue_picoclaw_report_writes_validated_report_into_inbox(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sync_root = root / "sync"
            config_dir = sync_root / "vault-id"
            vault_path = root / "notes"
            root_note_path = vault_path / "root-note"
            tech_path = vault_path / "TechVault"
            config_dir.mkdir(parents=True)
            root_note_path.mkdir(parents=True)
            tech_path.mkdir(parents=True)
            (vault_path / "WorkVault").mkdir(parents=True)
            (vault_path / "PersonalVault").mkdir(parents=True)
            (config_dir / "config.json").write_text(json.dumps({"vaultPath": str(vault_path)}), encoding="utf-8")
            (root_note_path / "entry.md").write_text("---\ntitle: Inbox\n tags: [inbox]\n---\nbody\n".replace(" \n", "\n"), encoding="utf-8")
            handoff = monitor_root_note(sync_root=sync_root, generated_at="2026-03-31T05:20:00+00:00")
            handoff_payload = json.loads(handoff.handoff_path.read_text(encoding="utf-8"))
            (tech_path / "atomic.md").write_text("---\ntitle: Atomic\n tags: [tech]\n---\nbody\n".replace(" \n", "\n"), encoding="utf-8")

            result = queue_picoclaw_report(
                report_payload={
                    "job_id": handoff.job_id,
                    "reported_by": "PicoClaw",
                    "completed_at": "2026-03-31T05:25:00+00:00",
                    "entries": [
                        {
                            "source_path": "root-note/entry.md",
                            "fingerprint": handoff_payload["entries"][0]["fingerprint"],
                            "status": "processed",
                            "outputs": [
                                {
                                    "destination_vault": "TechVault",
                                    "note_path": "TechVault/atomic.md",
                                }
                            ],
                        }
                    ],
                },
                sync_root=sync_root,
            )

            self.assertTrue(result.queued_report_path.exists())
            queued_payload = json.loads(result.queued_report_path.read_text(encoding="utf-8"))
            self.assertEqual(queued_payload["job_id"], handoff.job_id)
            self.assertEqual(result.entry_count, 1)
            self.assertIsNone(result.pipeline_result)

    def test_loopback_listener_accepts_picoclaw_report_callback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sync_root = root / "sync"
            config_dir = sync_root / "vault-id"
            vault_path = root / "notes"
            root_note_path = vault_path / "root-note"
            tech_path = vault_path / "TechVault"
            config_dir.mkdir(parents=True)
            root_note_path.mkdir(parents=True)
            tech_path.mkdir(parents=True)
            (vault_path / "WorkVault").mkdir(parents=True)
            (vault_path / "PersonalVault").mkdir(parents=True)
            (config_dir / "config.json").write_text(json.dumps({"vaultPath": str(vault_path)}), encoding="utf-8")
            (root_note_path / "entry.md").write_text("---\ntitle: Inbox\n tags: [inbox]\n---\nbody\n".replace(" \n", "\n"), encoding="utf-8")
            handoff = monitor_root_note(sync_root=sync_root, generated_at="2026-03-31T05:30:00+00:00")
            handoff_payload = json.loads(handoff.handoff_path.read_text(encoding="utf-8"))
            (tech_path / "atomic.md").write_text("---\ntitle: Atomic\n tags: [tech]\n---\nbody\n".replace(" \n", "\n"), encoding="utf-8")
            (root_note_path / "entry-two.md").write_text("---\ntitle: Next\n tags: [inbox]\n---\nnext\n".replace(" \n", "\n"), encoding="utf-8")

            server = Thread(
                target=serve_loopback,
                kwargs={
                    "sync_root": sync_root,
                    "host": "127.0.0.1",
                    "port": 45491,
                    "run_pipeline": True,
                },
                daemon=True,
            )
            server.start()
            for _ in range(50):
                try:
                    conn = HTTPConnection("127.0.0.1", 45491, timeout=1)
                    conn.request("GET", "/health")
                    health = conn.getresponse()
                    if health.status == 200:
                        break
                except OSError:
                    continue
            else:
                self.fail("loopback listener did not become ready")
            self.assertEqual(health.status, 200)
            health_payload = json.loads(health.read().decode("utf-8"))
            self.assertEqual(health_payload["callback_endpoint"], "/picoclaw-report")

            conn.request(
                "POST",
                "/picoclaw-report",
                body=json.dumps(
                    {
                        "job_id": handoff.job_id,
                        "reported_by": "PicoClaw",
                        "completed_at": "2026-03-31T05:35:00+00:00",
                        "entries": [
                            {
                                "source_path": "root-note/entry.md",
                                "fingerprint": handoff_payload["entries"][0]["fingerprint"],
                                "status": "processed",
                                "outputs": [
                                    {
                                        "destination_vault": "TechVault",
                                        "note_path": "TechVault/atomic.md",
                                    }
                                ],
                            }
                        ],
                    }
                ),
                headers={"Content-Type": "application/json"},
            )
            response = conn.getresponse()
            self.assertEqual(response.status, 200)
            payload = json.loads(response.read().decode("utf-8"))
            self.assertTrue(payload["run_pipeline"])
            self.assertEqual(payload["pipeline_result"]["reports_applied"], 1)
            next_handoff = json.loads(Path(payload["pipeline_result"]["handoff_path"]).read_text(encoding="utf-8"))
            self.assertEqual(next_handoff["entries"][0]["source_path"], "root-note/entry-two.md")
            self.assertTrue((tech_path / "MOC.md").exists())

    def test_loopback_listener_accepts_agent_reference_callback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sync_root = root / "sync"
            config_dir = sync_root / "vault-id"
            vault_path = root / "notes"
            tech_path = vault_path / "TechVault"
            config_dir.mkdir(parents=True)
            tech_path.mkdir(parents=True)
            (vault_path / "root-note").mkdir(parents=True)
            (vault_path / "WorkVault").mkdir(parents=True)
            (vault_path / "PersonalVault").mkdir(parents=True)
            (config_dir / "config.json").write_text(json.dumps({"vaultPath": str(vault_path)}), encoding="utf-8")
            dormant_path = tech_path / "dormant.md"
            dormant_path.write_text(
                "---\n"
                "title: Dormant\n"
                "tags: [tech, decayed]\n"
                "status: decayed\n"
                "decayed: true\n"
                "---\n"
                "sleep\n",
                encoding="utf-8",
            )

            server = Thread(
                target=serve_loopback,
                kwargs={
                    "sync_root": sync_root,
                    "host": "127.0.0.1",
                    "port": 45492,
                    "run_pipeline": False,
                },
                daemon=True,
            )
            server.start()
            for _ in range(50):
                try:
                    conn = HTTPConnection("127.0.0.1", 45492, timeout=1)
                    conn.request("GET", "/health")
                    health = conn.getresponse()
                    if health.status == 200:
                        break
                except OSError:
                    continue
            else:
                self.fail("loopback listener did not become ready")

            health_payload = json.loads(health.read().decode("utf-8"))
            self.assertEqual(health_payload["agent_reference_endpoint"], "/agent-reference")

            conn.request(
                "POST",
                "/agent-reference",
                body=json.dumps(
                    {
                        "referenced_at": "2026-03-31T05:40:00+00:00",
                        "referenced_note_paths": ["TechVault/dormant.md"],
                    }
                ),
                headers={"Content-Type": "application/json"},
            )
            response = conn.getresponse()
            self.assertEqual(response.status, 200)
            payload = json.loads(response.read().decode("utf-8"))
            self.assertEqual(payload["reactivated_note_paths"], ["TechVault/dormant.md"])
            self.assertIn("TechVault", payload["destination_mocs"])

            updated_text = dormant_path.read_text(encoding="utf-8")
            self.assertIn("decayed: false", updated_text)
            self.assertEqual(parse_markdown_text(updated_text).frontmatter["last_resonated_at"], "2026-03-31T05:40:00+00:00")


if __name__ == "__main__":
    unittest.main()
