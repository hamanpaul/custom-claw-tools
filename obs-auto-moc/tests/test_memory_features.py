from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from obs_auto_moc.dream import run_dream_mode
from obs_auto_moc.engine import apply_picoclaw_report, monitor_root_note, parse_markdown_text
from obs_auto_moc.persona_goal import distill_persona_goals
from obs_auto_moc.retrieval import query_memory
from obs_auto_moc.session_insights import import_session_insights
from obs_auto_moc.synthesis import synthesize_memory
from obs_auto_moc.wakeup import build_wake_up_bundle


class MemoryFeatureIntegrationTest(unittest.TestCase):
    def _build_vault(self) -> tuple[Path, Path, Path]:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        root = Path(temp_dir.name)
        sync_root = root / "sync"
        config_dir = sync_root / "vault-id"
        vault_path = root / "notes"
        config_dir.mkdir(parents=True)
        (vault_path / "root-note").mkdir(parents=True)
        (vault_path / "TechVault").mkdir(parents=True)
        (vault_path / "WorkVault").mkdir(parents=True)
        (vault_path / "PersonalVault").mkdir(parents=True)
        (config_dir / "config.json").write_text(json.dumps({"vaultPath": str(vault_path)}), encoding="utf-8")
        return root, sync_root, vault_path

    def test_monitor_root_note_includes_memory_contract(self) -> None:
        _root, sync_root, vault_path = self._build_vault()
        (vault_path / "root-note" / "entry.md").write_text(
            "---\n"
            "title: Inbox Entry\n"
            "tags: [inbox]\n"
            "---\n"
            "Pending organization.\n",
            encoding="utf-8",
        )

        result = monitor_root_note(sync_root=sync_root, generated_at="2026-04-17T10:00:00+00:00")
        payload = json.loads(result.handoff_path.read_text(encoding="utf-8"))
        self.assertEqual(
            payload["entries"][0]["memory_contract"]["required_sections"],
            ["Compiled Truth", "Timeline", "Sources", "Related"],
        )

    def test_apply_report_populates_note_contract_and_memory_ledger(self) -> None:
        root, sync_root, vault_path = self._build_vault()
        (vault_path / "root-note" / "entry.md").write_text(
            "---\n"
            "title: Inbox Entry\n"
            "tags: [inbox]\n"
            "---\n"
            "A demo source note.\n",
            encoding="utf-8",
        )
        monitor_result = monitor_root_note(sync_root=sync_root, generated_at="2026-04-17T10:00:00+00:00")
        handoff_payload = json.loads(monitor_result.handoff_path.read_text(encoding="utf-8"))
        fingerprint = handoff_payload["entries"][0]["fingerprint"]

        destination_note = vault_path / "TechVault" / "atomic-note.md"
        destination_note.write_text(
            "---\n"
            "title: Atomic Note\n"
            "tags: [tech]\n"
            "---\n"
            "This note mentions memory retrieval.\n",
            encoding="utf-8",
        )
        (vault_path / "PersonalVault" / "working-style.md").write_text(
            "---\n"
            "title: Working Style\n"
            "tags: [persona]\n"
            "---\n"
            "- Prefer deterministic pipelines.\n"
            "- 目標：把 Obsidian 變成可追溯 memory substrate。\n",
            encoding="utf-8",
        )

        report_path = root / "picoclaw-report.json"
        report_path.write_text(
            json.dumps(
                {
                    "job_id": monitor_result.job_id,
                    "reported_by": "PicoClaw",
                    "completed_at": "2026-04-17T10:10:00+00:00",
                    "entries": [
                        {
                            "source_path": "root-note/entry.md",
                            "fingerprint": fingerprint,
                            "status": "processed",
                            "entities": ["Obsidian", "Memory"],
                            "claims": ["Obsidian can act as a memory substrate."],
                            "decisions": ["Keep canonical truth in vault notes."],
                            "open_questions": ["How should dream mode write back proposals?"],
                            "event_time": "2026-04-17T10:05:00+00:00",
                            "citations": [
                                {
                                    "source_path": "root-note/entry.md",
                                    "quote": "A demo source note.",
                                    "locator": "body",
                                }
                            ],
                            "contradiction_signals": ["Need proposal-first writeback safeguards."],
                            "related_note_paths": ["PersonalVault/working-style.md"],
                            "goals": ["Turn notes into durable agent memory."],
                            "heuristics": ["Prefer deterministic orchestration."],
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
        self.assertEqual(len(result.note_contract_updates), 1)
        self.assertIsNotNone(result.memory_ledger_summary)

        parsed_destination = parse_markdown_text(destination_note.read_text(encoding="utf-8"))
        self.assertEqual(parsed_destination.frontmatter["type"], "memory-note")
        self.assertEqual(parsed_destination.frontmatter["vault"], "TechVault")
        self.assertIn("root-note/entry.md", parsed_destination.frontmatter["source_refs"])
        self.assertIn("## Compiled Truth", parsed_destination.body)
        self.assertIn("## Sources", parsed_destination.body)

        note_facts_path = vault_path / "claw" / "moc" / "memory" / "note-facts.jsonl"
        ledger_rows = [json.loads(line) for line in note_facts_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual(ledger_rows[0]["note_path"], "TechVault/atomic-note.md")
        self.assertIn("Obsidian can act as a memory substrate.", ledger_rows[0]["claims"])

        query_result = query_memory(
            query="memory substrate",
            sync_root=sync_root,
            generated_at="2026-04-17T10:11:00+00:00",
        )
        self.assertEqual(query_result.results[0]["note_path"], "TechVault/atomic-note.md")

        insights_path = root / "insights.json"
        lesson_path = root / "lesson.json"
        decision_path = root / "decision.json"
        skill_cards_path = root / "skill-cards.json"
        skill_links_path = root / "skill-links.json"
        insights_path.write_text(
            json.dumps(
                {
                    "generated_at": "2026-04-17T10:11:30+00:00",
                    "session_count": 3,
                    "scoring": {
                        "rows": [
                            {
                                "event_type": "turn_aborted",
                                "raw_count": 4,
                                "short_weighted": 3.2,
                                "long_weighted": 3.4,
                                "severity": 1.0,
                                "score": 0.97,
                            },
                            {
                                "event_type": "context_compacted",
                                "raw_count": 2,
                                "short_weighted": 1.4,
                                "long_weighted": 1.9,
                                "severity": 0.6,
                                "score": 0.73,
                            },
                        ]
                    },
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        lesson_path.write_text(
            json.dumps(
                {
                    "generated_at": "2026-04-17T10:11:45+00:00",
                    "session_path": "/tmp/demo.jsonl",
                    "report": {
                        "event_counts": {"turn_aborted": 4},
                        "response_item_counts": {"message": 2},
                        "friction_signals": {"turn_aborted": 4, "context_compacted": 1},
                        "patch_proposal": [
                            "縮短回覆前置規劃，明確指令優先直接執行。",
                            "減少冗長輸出，將長流程拆成可檢核小步驟。",
                        ],
                    },
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        decision_path.write_text(
            json.dumps(
                {
                    "accepted_proposals": [
                        {
                            "event_type": "turn_aborted",
                            "action": "add",
                            "score": 0.97,
                            "decision_reason": "raw_count 與 friction 都偏高",
                        }
                    ],
                    "rejected_proposals": [],
                    "decisions": [
                        {
                            "event_type": "turn_aborted",
                            "action": "add",
                            "decision": "accept",
                            "reason": "raw_count 與 friction 都偏高",
                        }
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        skill_cards_path.write_text(
            json.dumps(
                {
                    "rows": [
                        {
                            "skill_id": "obs-auto-moc",
                            "topic_id": "turn_aborted",
                            "title": "Turn Aborted Remediation",
                            "confidence": 0.97,
                            "evidence_count": 4,
                        }
                    ]
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        skill_links_path.write_text(
            json.dumps(
                {
                    "rows": [
                        {
                            "source": "obs-auto-moc",
                            "target": "problemmap",
                            "relation": "relates_to",
                            "confidence": 0.61,
                        }
                    ]
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        import_result = import_session_insights(
            sync_root=sync_root,
            generated_at="2026-04-17T10:11:59+00:00",
            insights_path=insights_path,
            lesson_path=lesson_path,
            decision_path=decision_path,
            skill_cards_path=skill_cards_path,
            skill_links_path=skill_links_path,
        )
        self.assertTrue(Path(import_result.dream_overlay_path).exists())
        self.assertTrue(Path(import_result.persona_overlay_path).exists())
        self.assertIsNotNone(import_result.method_graph_path)
        self.assertTrue(Path(import_result.method_graph_path or "").exists())
        self.assertIn("turn_aborted", import_result.top_event_types)

        wake_result = build_wake_up_bundle(sync_root=sync_root, generated_at="2026-04-17T10:12:00+00:00")
        self.assertTrue(wake_result.output_path.exists())
        self.assertTrue(any("turn_aborted" in row for row in wake_result.operational_signals))
        self.assertEqual(wake_result.session_friction_signals["turn_aborted"], 4)

        dream_result = run_dream_mode(sync_root=sync_root, generated_at="2026-04-17T10:13:00+00:00")
        self.assertTrue(dream_result.proposal_path.exists())
        self.assertIn("縮短回覆前置規劃，明確指令優先直接執行。", dream_result.session_patch_proposals)
        self.assertGreaterEqual(len(dream_result.accepted_rule_candidates), 1)

        synthesis_result = synthesize_memory(
            query="deterministic memory",
            sync_root=sync_root,
            generated_at="2026-04-17T10:14:00+00:00",
            write_artifact=True,
        )
        self.assertTrue(synthesis_result.verified)
        self.assertIsNotNone(synthesis_result.artifact_path)
        self.assertTrue(Path(synthesis_result.artifact_path).exists())

    def test_distill_persona_goals_can_apply_to_personal_vault(self) -> None:
        _root, sync_root, vault_path = self._build_vault()
        (vault_path / "PersonalVault" / "journal.md").write_text(
            "---\n"
            "title: Journal\n"
            "tags: [persona]\n"
            "---\n"
            "- Prefer proof before assumptions.\n"
            "- Avoid silent fallback.\n"
            "- 目標：建立長期記憶系統。\n"
            "- 目標：讓 agent 能用 wake-up 回憶上下文。\n",
            encoding="utf-8",
        )

        result = distill_persona_goals(
            sync_root=sync_root,
            generated_at="2026-04-17T11:00:00+00:00",
            apply=True,
        )

        self.assertTrue(Path(result.overlay_path).exists())
        self.assertTrue(result.applied)
        self.assertIsNotNone(result.canonical_path)
        self.assertTrue(Path(result.canonical_path).exists())
        self.assertGreaterEqual(len(result.heuristics), 1)
        self.assertGreaterEqual(len(result.goals), 1)

    def test_distill_persona_goals_merges_session_heuristics(self) -> None:
        root, sync_root, vault_path = self._build_vault()
        (vault_path / "PersonalVault" / "journal.md").write_text(
            "---\n"
            "title: Journal\n"
            "tags: [persona]\n"
            "---\n"
            "- Prefer proof before assumptions.\n"
            "- 目標：建立長期記憶系統。\n",
            encoding="utf-8",
        )
        lesson_path = root / "lesson.json"
        decision_path = root / "decision.json"
        lesson_path.write_text(
            json.dumps(
                {
                    "report": {
                        "friction_signals": {"turn_aborted": 1},
                        "patch_proposal": ["縮短回覆前置規劃，明確指令優先直接執行。"],
                    }
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        decision_path.write_text(
            json.dumps(
                {
                    "accepted_proposals": [
                        {
                            "event_type": "turn_aborted",
                            "action": "add",
                            "decision_reason": "需要更直接的執行節奏",
                        }
                    ]
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        import_session_insights(
            sync_root=sync_root,
            generated_at="2026-04-17T11:01:00+00:00",
            lesson_path=lesson_path,
            decision_path=decision_path,
        )

        result = distill_persona_goals(
            sync_root=sync_root,
            generated_at="2026-04-17T11:02:00+00:00",
            apply=False,
        )

        self.assertGreaterEqual(len(result.session_heuristics), 1)
        overlay_text = Path(result.overlay_path).read_text(encoding="utf-8")
        self.assertIn("## Session-derived heuristic overlays", overlay_text)
        self.assertIn("縮短回覆前置規劃，明確指令優先直接執行。", overlay_text)


if __name__ == "__main__":
    unittest.main()
