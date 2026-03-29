from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from obs_auto_moc.engine import build_workspace, parse_markdown_text


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

            preview_text = preview_path.read_text(encoding="utf-8")
            proposal_text = proposal_path.read_text(encoding="utf-8")
            moc_text = moc_path.read_text(encoding="utf-8")

            self.assertIn("## TechVault", preview_text)
            self.assertIn("## Issues to review", proposal_text)
            self.assertIn("mode: apply", moc_text)


if __name__ == "__main__":
    unittest.main()
