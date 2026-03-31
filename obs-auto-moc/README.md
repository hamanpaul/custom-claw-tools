# obs-auto-moc

`obs-auto-moc` is a review-first Obsidian MOC compiler for the live PicoClaw vault on pi3.

It does **not** rewrite `notes/MOC.md` by default. A normal run only:

- resolves the live vault path from `~/.config/obsidian-headless/sync/*/config.json`
- scans Markdown notes and frontmatter
- builds a JSONL inventory manifest
- renders a proposal report
- renders a `MOC.preview.md`

Only `build --apply` writes the live `MOC.md`.

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

## Validation

Run unit tests:

```bash
cd /home/paul_chen/prj_pri/custom-claw-tools/obs-auto-moc
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
2. hand off `root-note` processing to `PicoClaw`, where the agent follows `ObsToolsVault` rules to:
   - atomize notes
   - establish file relationships
   - determine and update tags/metadata
   - route results toward `TechVault`, `WorkVault`, or `PersonalVault`
3. let script logic maintain the MOC relations for `TechVault`, `WorkVault`, and `PersonalVault`

Important boundary notes for the planned design:

- `1 -> 2 -> 3` is intended to be one continuous flow, not three separate manual steps
- the scope is intentionally limited to `root-note -> TechVault / WorkVault / PersonalVault`
- Stage 2 runs in live `PicoClaw` on pi3 via `/usr/bin/picoclaw agent`
- `picoclaw-ops-companion` is **not** the planned Stage 2 runtime for this flow
- Stage 1 monitoring and Stage 3 MOC maintenance should remain deterministic script/service logic
- the current handoff contract points PicoClaw at the canonical pi3 notes entry `ObsToolsVault/README.md`, with deeper migration guidance living under `ObsToolsVault/specs/`


## Current root-note pipeline scaffold

The repository now includes a live script-side pipeline for `root-note -> PicoClaw -> TechVault / WorkVault / PersonalVault`.

What exists now:

- `monitor-root-note` detects changed Markdown files under `root-note/` and writes a structured PicoClaw handoff artifact
- `apply-picoclaw-report` validates a structured PicoClaw completion report, updates root-note pipeline state, and refreshes destination MOCs
- `queue-picoclaw-report` validates a PicoClaw completion report and drops it into the pipeline report inbox, optionally running the next pipeline tick immediately
- `refresh-destination-mocs` rebuilds script-maintained `MOC.md` files inside `TechVault`, `WorkVault`, and `PersonalVault`
- `dispatch-picoclaw-handoff` submits a generated handoff job to live PicoClaw, captures the structured JSON report, and feeds it back into the pipeline
- `run-pipeline-once` applies queued PicoClaw completion reports from the report inbox, emits the next handoff job from `root-note`, and when auto-dispatch is enabled, immediately submits that handoff to PicoClaw
- the handoff artifact now advertises `ObsToolsVault/README.md` as the Stage 2 ruleset source for PicoClaw
- the handoff artifact also includes `vault_path` and per-destination root paths so PicoClaw can write destination notes before reporting completion
- `listen` exposes a loopback-only callback listener on `127.0.0.1` for `GET /health` and `POST /picoclaw-report`
- the handoff callback contract now includes the default loopback callback endpoint `http://127.0.0.1:45460/picoclaw-report`

What is live now:

- `obs-auto-moc-listener.service` keeps the loopback callback listener up on `127.0.0.1:45460`
- `obs-auto-moc-pipeline.timer` periodically runs `bin/obs-auto-moc-runner`
- `bin/obs-auto-moc-runner` defaults `OBS_AUTO_MOC_AUTO_DISPATCH=1` and dispatches new handoff jobs to `PicoClaw`
- the live dispatch path uses `/usr/bin/picoclaw agent --session cron:obs-auto-moc`

## pi3 loopback callback and runner deployment

The repo now includes a first deployment scaffold for pi3:

- `bin/obs-auto-moc-listen`
- `bin/obs-auto-moc-runner`
- `systemd/obs-auto-moc-listener.service`
- `systemd/obs-auto-moc-pipeline.service`
- `systemd/obs-auto-moc-pipeline.timer`

Suggested deployment flow:

```bash
cd /home/haman/custom-claw-tools/obs-auto-moc
chmod +x bin/obs-auto-moc-listen bin/obs-auto-moc-runner
cp systemd/obs-auto-moc-listener.service ~/.config/systemd/user/
cp systemd/obs-auto-moc-pipeline.service ~/.config/systemd/user/
cp systemd/obs-auto-moc-pipeline.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now obs-auto-moc-listener.service
systemctl --user enable --now obs-auto-moc-pipeline.timer
```

Quick checks:

```bash
systemctl --user status obs-auto-moc-listener.service
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
- `OBS_AUTO_MOC_PICOCLAW_SESSION`

That lets you point the listener/timer at a temporary vault before switching to the live notes tree.

Example callback POST from a local PicoClaw relay:

```bash
curl -X POST http://127.0.0.1:45460/picoclaw-report \
  -H 'content-type: application/json' \
  --data @report.json
```
