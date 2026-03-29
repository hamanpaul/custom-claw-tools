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


if __name__ == "__main__":
    unittest.main()
