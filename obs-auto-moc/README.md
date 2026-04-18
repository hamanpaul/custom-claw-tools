# obs-auto-moc

`obs-auto-moc` is a review-first Obsidian MOC compiler and memory-overlay manager for the live PicoClaw vault on pi3.

It does **not** rewrite `notes/MOC.md` by default. A normal run only:

- resolves the live vault path from `~/.config/obsidian-headless/sync/*/config.json`
- scans Markdown notes and frontmatter
- builds a JSONL inventory manifest
- renders a proposal report
- renders a `MOC.preview.md`

Only `build --apply` writes the live `MOC.md`.

Current guardrails:

- `obs-auto-moc` only processes `root-note`, `TechVault`, `WorkVault`, and `PersonalVault`
- notes marked `Decayed` are metadata-only, not moved to another folder
- agent search / read / quote references can reactivate a Decayed note and recompute `last_resonated_at`

## Project layout

- `SKILL.md`: versioned PicoClaw skill copy
- `bin/obs-auto-moc`: local CLI wrapper
- `obs_auto_moc/`: Python implementation
- `tests/`: unit tests

## Runtime assumptions

- Python 3.10+
- `PyYAML` available on the host

The current local and pi3 environments already provide `yaml`.

## Default live paths

- project root: `/home/haman/custom-claw-tools/obs-auto-moc`
- live skill path: `/home/haman/.picoclaw/workspace/skills/obs-auto-moc/SKILL.md`
- live wrapper path: `/home/haman/.picoclaw/workspace/bin/obs-auto-moc`
- artifacts root: `/home/haman/.picoclaw/workspace/notes/claw/moc`
- live preview path: `/home/haman/.picoclaw/workspace/notes/claw/moc/MOC.preview.md`
- live proposal root: `/home/haman/.picoclaw/workspace/notes/claw/moc/proposals`
- live manifest path: `/home/haman/.picoclaw/workspace/notes/claw/moc/index-manifest.jsonl`
- live MOC path: `/home/haman/.picoclaw/workspace/notes/MOC.md`

## Commands

Preview-only build:

```bash
cd /home/paul_chen/prj_pri/custom-claw-tools/obs-auto-moc
./bin/obs-auto-moc build
```

Show last-run stats:

```bash
cd /home/paul_chen/prj_pri/custom-claw-tools/obs-auto-moc
./bin/obs-auto-moc stats
```

Apply the rendered preview to the live MOC:

```bash
cd /home/paul_chen/prj_pri/custom-claw-tools/obs-auto-moc
./bin/obs-auto-moc build --apply
```

Emit a PicoClaw handoff job for changed files in `root-note`:

```bash
cd /home/paul_chen/prj_pri/custom-claw-tools/obs-auto-moc
./bin/obs-auto-moc monitor-root-note --json
```

Apply a structured PicoClaw completion report and refresh destination MOCs:

```bash
cd /home/paul_chen/prj_pri/custom-claw-tools/obs-auto-moc
./bin/obs-auto-moc apply-picoclaw-report --report /path/to/report.json
```

Validate and queue a PicoClaw completion report into the live report inbox:

```bash
cd /home/paul_chen/prj_pri/custom-claw-tools/obs-auto-moc
./bin/obs-auto-moc queue-picoclaw-report --report /path/to/report.json --run-pipeline --json
```

Refresh destination MOCs directly:

```bash
cd /home/paul_chen/prj_pri/custom-claw-tools/obs-auto-moc
./bin/obs-auto-moc refresh-destination-mocs --destination-vault TechVault
```

Run one full script-side pipeline tick:

```bash
cd /home/paul_chen/prj_pri/custom-claw-tools/obs-auto-moc
./bin/obs-auto-moc run-pipeline-once --json
```

Start the local loopback callback listener:

```bash
cd /home/paul_chen/prj_pri/custom-claw-tools/obs-auto-moc
./bin/obs-auto-moc listen --host 127.0.0.1 --port 45460 --run-pipeline
```

Record an agent reference batch, reactivate Decayed notes, and rebuild related links:

```bash
cd /home/paul_chen/prj_pri/custom-claw-tools/obs-auto-moc
./bin/obs-auto-moc record-agent-reference \
  --note-path TechVault/example.md \
  --note-path WorkVault/another-note.md \
  --json
```

Query memory from notes plus the secondary ledger:

```bash
cd /home/paul_chen/prj_pri/custom-claw-tools/obs-auto-moc
./bin/obs-auto-moc query-memory --query "memory substrate"
```

Build a wake-up bundle:

```bash
cd /home/paul_chen/prj_pri/custom-claw-tools/obs-auto-moc
./bin/obs-auto-moc wake-up
```

Generate dream-mode consolidation proposals:

```bash
cd /home/paul_chen/prj_pri/custom-claw-tools/obs-auto-moc
./bin/obs-auto-moc dream
```

Distill persona and goals from `PersonalVault`:

```bash
cd /home/paul_chen/prj_pri/custom-claw-tools/obs-auto-moc
./bin/obs-auto-moc distill-persona-goals --apply
```

Import distilled session analytics into memory overlays:

```bash
cd /home/paul_chen/prj_pri/custom-claw-tools/obs-auto-moc
./bin/obs-auto-moc import-session-insights \
  --insights /path/to/insights.json \
  --lesson /path/to/lesson.json \
  --decision /path/to/decision.json
```

Synthesize cross-note evidence for an open question:

```bash
cd /home/paul_chen/prj_pri/custom-claw-tools/obs-auto-moc
./bin/obs-auto-moc synthesize-memory --query "deterministic memory" --write-artifact
```

## Artifacts

A normal `build` writes:

- `index-manifest.jsonl`
- `last-run.json`
- `MOC.preview.md`
- `proposals/<date>-moc-proposal.md`

The proposal focuses on:

- scan counts
- malformed or incomplete frontmatter
- orphan notes
- hub candidates
- unresolved links
- next-step guidance

The `root-note` pipeline also maintains a secondary memory ledger under `claw/moc/memory/`:

- `entities.jsonl`
- `relations.jsonl`
- `events.jsonl`
- `citations.jsonl`
- `note-facts.jsonl`
- `contradictions.jsonl`
- `wake-up/`
- `dream/`
- `persona/`
- `synthesis/`
- `health/ledger-summary.json`

Session-derived overlays now land under the same managed memory root:

- `health/session-insights-latest.json`
- `health/session-lessons-latest.json`
- `health/session-decisions-latest.json`
- optional `health/skill-cards-latest.json`
- optional `health/skill-links-latest.json`
- `dream/session-lessons.md`
- `persona/session-derived-heuristics.md`
- optional `synthesis/skill-method-graph.md`

## Validation

Run unit tests:

```bash
cd /home/paul_chen/prj_pri/custom-claw-tools/obs-auto-moc
python3 -m py_compile obs_auto_moc/*.py tests/*.py
python3 -m unittest discover -s tests
```

Run a local smoke build against a real vault path:

```bash
cd /home/paul_chen/prj_pri/custom-claw-tools/obs-auto-moc
./bin/obs-auto-moc build
./bin/obs-auto-moc stats
```

## Design notes

- The scanner prefers frontmatter-driven grouping over folder-driven grouping.
- It still records top-level vault sections so the generated preview stays familiar.
- Malformed notes are reported instead of silently fixed.
- `build` is safe by default; `--apply` is explicit.

## Planned continuous pipeline

This section is a roadmap only. It does **not** describe the current implementation yet.

The intended direction is to evolve `obs-auto-moc` from a single `build` command into one continuous pipeline:

1. monitor `root-note` as the intake/staging area for files you have already read and want organized
2. hand off `root-note` processing to the live OpenClaw Stage 2 agent, where the agent follows `ObsToolsVault` rules to:
   - atomize notes
   - establish file relationships
   - determine and update tags/metadata
   - route results toward `TechVault`, `WorkVault`, or `PersonalVault`
3. let script logic maintain the MOC relations for `TechVault`, `WorkVault`, and `PersonalVault`

Important boundary notes for the planned design:

- `1 -> 2 -> 3` is intended to be one continuous flow, not three separate manual steps
- the scope is intentionally limited to `root-note -> TechVault / WorkVault / PersonalVault`
- Stage 2 runs in live OpenClaw on pi3 via `/usr/local/bin/openclaw agent --session-id ...`
- `picoclaw-ops-companion` is **not** the planned Stage 2 runtime for this flow
- Stage 1 monitoring and Stage 3 MOC maintenance should remain deterministic script/service logic
- the current handoff contract points PicoClaw at the canonical pi3 notes entry `ObsToolsVault/README.md`, with deeper migration guidance living under `ObsToolsVault/specs/`


## Current root-note pipeline scaffold

The repository now includes a live script-side pipeline for `root-note -> PicoClaw -> TechVault / WorkVault / PersonalVault`.

What exists now:

- `monitor-root-note` detects changed Markdown files under `root-note/` and writes a structured Stage 2 handoff artifact
- if the pending `root-note` batch is too large, `monitor-root-note` only hands off the bounded front slice for the current tick and leaves the remainder retryable for the next tick
- `apply-picoclaw-report` validates a structured PicoClaw completion report, updates root-note pipeline state, and refreshes destination MOCs
- processed destination notes now get a lightweight memory-note contract (`type`, `vault`, `source_refs`, `last_compiled_at`, plus `Compiled Truth` / `Timeline` / `Sources` / `Related` sections when missing)
- when a report entry lands as `processed` or `skipped`, the original `root-note/` source note is archived under `pipeline/root-note-archive/<status>/<job_id>/...` so the intake area actually drains
- `queue-picoclaw-report` validates a PicoClaw completion report and drops it into the pipeline report inbox, optionally running the next pipeline tick immediately
- `record-agent-reference` records an explicit agent reference batch, reactivates Decayed notes, updates `last_resonated_at`, and rebuilds `related` links for the touched note set
- `refresh-destination-mocs` rebuilds script-maintained `MOC.md` files inside `TechVault`, `WorkVault`, and `PersonalVault`
- `dispatch-picoclaw-handoff` submits a generated handoff job to the live OpenClaw Stage 2 runtime, captures the structured JSON report, and feeds it back into the pipeline
- `run-pipeline-once` applies queued PicoClaw completion reports from the report inbox, emits the next handoff job from `root-note`, and when auto-dispatch is enabled, immediately submits that handoff to PicoClaw
- `query-memory` searches both canonical notes and the secondary ledger so agents can wake up by claims, entities, heuristics, goals, and source refs instead of raw grep only
- `import-session-insights` ingests distilled `insights` / `lesson` / `decision` artifacts into `memory/health`, `memory/dream`, and `memory/persona`, with optional `skill-card` / `skill-link` overlays
- `wake-up` writes a wake-up bundle with hot notes, stale notes, open questions, contradiction counts, and imported operational signals when present
- `dream` writes proposal-first consolidation suggestions plus imported session lesson / working-rule candidates instead of directly rewriting canonical notes
- `distill-persona-goals` extracts reusable heuristics and goals from `PersonalVault`, merges imported session-derived heuristics into the overlay, and only writes back to `PersonalVault/Persona Goal Model.md` when `--apply` is explicit
- `synthesize-memory` assembles `VERIFIED` / `SYNTHESIZED` / `OPEN QUESTION` outputs from matched notes and ledger evidence
- if a queued PicoClaw completion report is malformed or cannot be applied, `run-pipeline-once` quarantines it under `pipeline/picoclaw-report-failures/` and lets the affected `root-note` entries become retryable on the next tick
- if the live OpenClaw Stage 2 auto-dispatch returns a non-zero exit or an unusable report block, `run-pipeline-once` marks the affected `root-note` entries as retryable instead of wedging the whole pipeline on a stale in-flight handoff state
- if the live OpenClaw Stage 2 runtime returns only a partial report, missing handoff entries are padded as `failed` results so they re-enter retry flow instead of lingering as stale in-flight state
- if the live OpenClaw Stage 2 runtime returns a stale/wrong-job report or claims `processed` outputs that do not exist, `dispatch-picoclaw-handoff` falls back locally by copying the source root-note into the selected destination vault(s) and queueing a valid report for the pipeline
- the handoff artifact now advertises `ObsToolsVault/README.md` as the Stage 2 ruleset source for PicoClaw
- the handoff artifact also includes `vault_path` and per-destination root paths so PicoClaw can write destination notes before reporting completion
- `listen` exposes a loopback-only callback listener on `127.0.0.1` for `GET /health`, `POST /picoclaw-report`, and `POST /agent-reference`
- the handoff callback contract now includes the default loopback callback endpoint `http://127.0.0.1:45460/picoclaw-report`
- PicoClaw completion reports may include `referenced_note_paths`, and the listener also accepts direct `agent-reference` callbacks for non-pipeline agent activity

What is live now:

- `obs-auto-moc-listener.service` keeps the loopback callback listener up on `127.0.0.1:45460`
- `obs-auto-moc-pipeline.path` proactively triggers a pipeline run when `root-note/` or the report inbox changes
- `obs-auto-moc-pipeline.timer` periodically runs `bin/obs-auto-moc-runner`
- `bin/obs-auto-moc-runner` defaults `OBS_AUTO_MOC_AUTO_DISPATCH=1` and dispatches new handoff jobs to the live OpenClaw Stage 2 runtime
- the live dispatch path uses `/usr/local/bin/openclaw agent --session-id cron:obs-auto-moc:<job_id>` so each handoff gets an isolated Stage 2 session instead of reusing stale conversation history

## pi3 loopback callback and runner deployment

The repo now includes a first deployment scaffold for pi3:

- `bin/obs-auto-moc-listen`
- `bin/obs-auto-moc-runner`
- `systemd/obs-auto-moc-listener.service`
- `systemd/obs-auto-moc-pipeline.path`
- `systemd/obs-auto-moc-pipeline.service`
- `systemd/obs-auto-moc-pipeline.timer`

Suggested deployment flow:

```bash
cd /home/haman/custom-claw-tools/obs-auto-moc
chmod +x bin/obs-auto-moc-listen bin/obs-auto-moc-runner
cp systemd/obs-auto-moc-listener.service ~/.config/systemd/user/
cp systemd/obs-auto-moc-pipeline.path ~/.config/systemd/user/
cp systemd/obs-auto-moc-pipeline.service ~/.config/systemd/user/
cp systemd/obs-auto-moc-pipeline.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now obs-auto-moc-listener.service
systemctl --user enable --now obs-auto-moc-pipeline.path
systemctl --user enable --now obs-auto-moc-pipeline.timer
```

Quick checks:

```bash
systemctl --user status obs-auto-moc-listener.service
systemctl --user status obs-auto-moc-pipeline.path
systemctl --user status obs-auto-moc-pipeline.timer
curl http://127.0.0.1:45460/health
```

For safe smoke tests on pi3, the wrappers also honor optional environment overrides:

- `OBS_AUTO_MOC_SYNC_ROOT`
- `OBS_AUTO_MOC_VAULT_PATH`
- `OBS_AUTO_MOC_ARTIFACTS_ROOT`
- `OBS_AUTO_MOC_ROOT_NOTE_PATH`
- `OBS_AUTO_MOC_PIPELINE_ROOT`
- `OBS_AUTO_MOC_RUN_PIPELINE`
- `OBS_AUTO_MOC_AUTO_DISPATCH`
- `OBS_AUTO_MOC_STAGE2_BIN`
- `OBS_AUTO_MOC_STAGE2_SESSION`
- `OBS_AUTO_MOC_STAGE2_TIMEOUT_S`
- `OBS_AUTO_MOC_STAGE2_MAX_ENTRIES`
- `OBS_AUTO_MOC_STAGE2_MAX_SOURCE_BYTES`
- `OBS_AUTO_MOC_RUN_WAKEUP`
- `OBS_AUTO_MOC_RUN_DREAM`
- `OBS_AUTO_MOC_STAGE2_SESSION` acts as the session prefix/namespace; the dispatcher appends `:<job_id>` automatically, or you can include a literal `{job_id}` placeholder in the value for custom formatting
- `OBS_AUTO_MOC_STALE_HANDOFF_SECONDS`

If `OBS_AUTO_MOC_RUN_WAKEUP=1` and/or `OBS_AUTO_MOC_RUN_DREAM=1`, `bin/obs-auto-moc-runner` will run those proposal/bundle jobs after the normal pipeline tick.

That lets you point the listener/timer at a temporary vault before switching to the live notes tree.

Example callback POST from a local PicoClaw relay:

```bash
curl -X POST http://127.0.0.1:45460/picoclaw-report \
  -H 'content-type: application/json' \
  --data @report.json
```

Example direct agent-reference callback:

```bash
curl -X POST http://127.0.0.1:45460/agent-reference \
  -H 'content-type: application/json' \
  --data '{"referenced_at":"2026-04-10T00:00:00+00:00","referenced_note_paths":["TechVault/example.md","WorkVault/another-note.md"]}'
```
