from __future__ import annotations

import io
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from obs_auto_moc import cli


class CliNoiseToleranceTest(unittest.TestCase):
    def test_stats_ignores_trailing_period_token(self) -> None:
        payload = {
            "generated_at": "2026-03-28T00:00:00+00:00",
            "vault_path": "/tmp/vault",
            "artifacts_root": "/tmp/vault/claw/moc",
            "proposal_path": "/tmp/vault/claw/moc/proposals/2026-03-28-moc-proposal.md",
            "preview_path": "/tmp/vault/claw/moc/MOC.preview.md",
            "output_moc_path": "/tmp/vault/MOC.md",
            "notes_scanned": 3,
            "parse_errors": 0,
            "duplicate_frontmatter_notes": 0,
            "missing_schema_notes": 1,
            "orphan_notes": 1,
            "unresolved_links": 0,
            "ambiguous_links": 0,
            "applied": False,
        }
        with (
            patch("sys.argv", ["obs-auto-moc", "stats", "."]),
            patch("obs_auto_moc.cli.resolve_paths", return_value=SimpleNamespace(last_run_path=Path("/tmp/fake.json"))),
            patch("obs_auto_moc.cli.load_last_run", return_value=payload),
            patch("sys.stdout", new_callable=io.StringIO) as stdout,
        ):
            self.assertEqual(cli.main(), 0)
            self.assertIn("preview_path:", stdout.getvalue())


class CliPipelineCommandsTest(unittest.TestCase):
    def test_monitor_root_note_dispatches(self) -> None:
        payload = {
            "generated_at": "2026-03-31T00:00:00+00:00",
            "root_note_path": "/tmp/vault/root-note",
            "pipeline_root": "/tmp/vault/claw/moc/pipeline",
            "scanned_files": 1,
            "handed_off_files": 1,
            "unchanged_files": 0,
            "job_id": "root-note-20260331000000-deadbeef",
            "handoff_path": "/tmp/job.json",
            "ruleset_name": "ObsToolsVault",
            "ruleset_source": "ObsToolsVault/README.md",
        }
        with (
            patch("sys.argv", ["obs-auto-moc", "monitor-root-note", "--json"]),
            patch("obs_auto_moc.cli.monitor_root_note", return_value=SimpleNamespace(to_dict=lambda: payload)),
            patch("sys.stdout", new_callable=io.StringIO) as stdout,
        ):
            self.assertEqual(cli.main(), 0)
            self.assertIn('"job_id": "root-note-20260331000000-deadbeef"', stdout.getvalue())

    def test_apply_picoclaw_report_dispatches(self) -> None:
        payload = {
            "generated_at": "2026-03-31T00:10:00+00:00",
            "job_id": "root-note-20260331000000-deadbeef",
            "report_path": "/tmp/report.json",
            "archived_report_path": "/tmp/archive.json",
            "state_path": "/tmp/state.json",
            "processed_count": 1,
            "skipped_count": 0,
            "failed_count": 0,
            "touched_destination_vaults": ["TechVault"],
            "destination_mocs": {"TechVault": "/tmp/TechVault/MOC.md"},
        }
        with (
            patch("sys.argv", ["obs-auto-moc", "apply-picoclaw-report", "--report", "/tmp/report.json"]),
            patch("obs_auto_moc.cli.apply_picoclaw_report", return_value=SimpleNamespace(to_dict=lambda: payload)),
            patch("sys.stdout", new_callable=io.StringIO) as stdout,
        ):
            self.assertEqual(cli.main(), 0)
            self.assertIn("processed_count: 1", stdout.getvalue())

    def test_refresh_destination_mocs_dispatches(self) -> None:
        payload = {
            "generated_at": "2026-03-31T01:00:00+00:00",
            "vault_path": "/tmp/vault",
            "destination_mocs": {"WorkVault": "/tmp/vault/WorkVault/MOC.md"},
            "note_counts": {"WorkVault": 2},
        }
        with (
            patch("sys.argv", ["obs-auto-moc", "refresh-destination-mocs", "--destination-vault", "WorkVault"]),
            patch("obs_auto_moc.cli.refresh_destination_mocs", return_value=SimpleNamespace(to_dict=lambda: payload)),
            patch("sys.stdout", new_callable=io.StringIO) as stdout,
        ):
            self.assertEqual(cli.main(), 0)
            self.assertIn("destination_moc[WorkVault]", stdout.getvalue())

    def test_queue_picoclaw_report_dispatches(self) -> None:
        payload = {
            "generated_at": "2026-03-31T01:05:00+00:00",
            "job_id": "root-note-20260331010500-feedbead",
            "reported_by": "PicoClaw",
            "entry_count": 1,
            "report_inbox_root": "/tmp/vault/claw/moc/pipeline/picoclaw-report-inbox",
            "queued_report_path": "/tmp/vault/claw/moc/pipeline/picoclaw-report-inbox/root-note-20260331010500-feedbead.json",
            "run_pipeline": True,
            "pipeline_result": {
                "reports_applied": 1,
                "handoff_job_id": "root-note-20260331010600-facefeed",
            },
        }
        with (
            patch("sys.argv", ["obs-auto-moc", "queue-picoclaw-report", "--report", "/tmp/report.json", "--run-pipeline"]),
            patch("obs_auto_moc.cli.queue_picoclaw_report", return_value=SimpleNamespace(to_dict=lambda: payload)),
            patch("sys.stdout", new_callable=io.StringIO) as stdout,
        ):
            self.assertEqual(cli.main(), 0)
            self.assertIn("pipeline_reports_applied: 1", stdout.getvalue())

    def test_run_pipeline_once_dispatches(self) -> None:
        payload = {
            "generated_at": "2026-03-31T01:10:00+00:00",
            "root_note_path": "/tmp/vault/root-note",
            "report_inbox_root": "/tmp/vault/claw/moc/pipeline/picoclaw-report-inbox",
            "reports_discovered": 1,
            "reports_applied": 1,
            "archived_report_paths": ["/tmp/archive.json"],
            "handoff_job_id": "root-note-20260331011000-feedface",
            "handoff_path": "/tmp/handoff.json",
            "handed_off_files": 1,
            "unchanged_files": 0,
            "state_path": "/tmp/state.json",
        }
        with (
            patch("sys.argv", ["obs-auto-moc", "run-pipeline-once", "--json"]),
            patch("obs_auto_moc.cli.run_pipeline_once", return_value=SimpleNamespace(to_dict=lambda: payload)),
            patch("sys.stdout", new_callable=io.StringIO) as stdout,
        ):
            self.assertEqual(cli.main(), 0)
            self.assertIn('"reports_applied": 1', stdout.getvalue())

    def test_dispatch_picoclaw_handoff_dispatches(self) -> None:
        payload = {
            "generated_at": "2026-03-31T06:05:00+00:00",
            "job_id": "root-note-20260331060000-deadbeef",
            "handoff_path": "/tmp/handoff.json",
            "queued_report_path": "/tmp/report-inbox/root-note-20260331060000-deadbeef.json",
            "report_copy_path": "/tmp/pipeline/picoclaw-dispatch/root-note-20260331060000-deadbeef.report.json",
            "raw_output_log_path": "/tmp/pipeline/picoclaw-dispatch/root-note-20260331060000-deadbeef.agent.log",
            "entry_count": 1,
            "run_pipeline": True,
            "pipeline_result": {
                "reports_applied": 1,
                "handoff_job_id": "root-note-20260331061000-facefeed",
            },
        }
        with (
            patch("sys.argv", ["obs-auto-moc", "dispatch-picoclaw-handoff", "--handoff", "/tmp/handoff.json"]),
            patch("obs_auto_moc.cli.dispatch_handoff_to_picoclaw", return_value=SimpleNamespace(to_dict=lambda: payload)),
            patch("sys.stdout", new_callable=io.StringIO) as stdout,
        ):
            self.assertEqual(cli.main(), 0)
            self.assertIn("raw_output_log_path:", stdout.getvalue())

    def test_listen_dispatches(self) -> None:
        with (
            patch("sys.argv", ["obs-auto-moc", "listen", "--host", "127.0.0.1", "--port", "45460", "--run-pipeline"]),
            patch("obs_auto_moc.cli.serve_loopback") as serve_loopback,
        ):
            self.assertEqual(cli.main(), 0)
            serve_loopback.assert_called_once()


if __name__ == "__main__":
    unittest.main()
