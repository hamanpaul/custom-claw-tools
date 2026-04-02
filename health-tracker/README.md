# health-tracker

`health-tracker` now includes a local GarminDB integration layer that can:

- run GarminDB sync without committing secrets into the repo
- ingest GarminDB SQLite outputs
- write canonical `raw/` and `daily/` notes under `notes/claw/health`

## Project layout

- `SKILL.md`: PicoClaw skill rules
- `templates/`: canonical raw/daily/report templates
- `bin/health-tracker-garmin`: local CLI wrapper
- `health_tracker_garmin/`: Python implementation
- `tests/`: stdlib `unittest` coverage for the Garmin note-mapping flow
- `runtime.example.json`: repo-safe runtime config example

## Secret handling

Garmin secrets stay **outside the repo**:

- GarminDB config: `~/.GarminDb/GarminConnectConfig.json`
- password storage: `credentials.password_file`

`health-tracker` rejects inline `credentials.password` when loading Garmin sync runtime, so the Garmin login path stays repo-external by default.

## Runtime config

The default runtime config path is:

`~/.config/health-tracker/garmin-runtime.json`

Write an example file:

```bash
cd /home/paul_chen/prj_pri/custom-claw-tools/health-tracker
./bin/health-tracker-garmin init-runtime
```

The committed `runtime.example.json` is repo-safe and only contains paths/command names, not secrets.

## Commands

Preview the GarminDB sync command:

```bash
cd /home/paul_chen/prj_pri/custom-claw-tools/health-tracker
./bin/health-tracker-garmin --runtime-config ~/.config/health-tracker/garmin-runtime.json sync-garmin --dry-run
```

Run a latest GarminDB sync:

```bash
cd /home/paul_chen/prj_pri/custom-claw-tools/health-tracker
./bin/health-tracker-garmin --runtime-config ~/.config/health-tracker/garmin-runtime.json sync-garmin
```

Ingest the most recent GarminDB outputs into canonical notes:

```bash
cd /home/paul_chen/prj_pri/custom-claw-tools/health-tracker
./bin/health-tracker-garmin --runtime-config ~/.config/health-tracker/garmin-runtime.json ingest-garmin
```

Do both in one step:

```bash
cd /home/paul_chen/prj_pri/custom-claw-tools/health-tracker
./bin/health-tracker-garmin --runtime-config ~/.config/health-tracker/garmin-runtime.json sync-and-ingest
```

## Current MVP mapping

The first implementation maps GarminDB into:

- sleep duration / bedtime / wake time / sleep score
- daily steps / distance（沿用 Garmin account measurement system）/ activity time / active calories
- activity sessions as daily training summaries
- raw Garmin import evidence into canonical `raw/YYYY/MM/DD/...`

The first implementation does **not** yet promise stable support for Garmin high-level derived metrics such as readiness/recovery.

## Validation

Run unit tests:

```bash
cd /home/paul_chen/prj_pri/custom-claw-tools/health-tracker
python3 -m unittest discover -s tests
```

Run a syntax-only smoke check:

```bash
cd /home/paul_chen/prj_pri/custom-claw-tools/health-tracker
python3 -m py_compile health_tracker_garmin/*.py
```

## pi3 deployment

After local validation, deploy the wrapper to pi3 by symlinking:

```bash
ln -sf /home/haman/custom-claw-tools/health-tracker/bin/health-tracker-garmin \
  /home/haman/.picoclaw/workspace/bin/health-tracker-garmin
```

Expected pi3 runtime layout:

- repo root: `/home/haman/custom-claw-tools/health-tracker`
- live wrapper: `/home/haman/.picoclaw/workspace/bin/health-tracker-garmin`
- runtime config: `/home/haman/.config/health-tracker/garmin-runtime.json`
- GarminDB config: `/home/haman/.GarminDb/GarminConnectConfig.json`
- canonical notes root: `/home/haman/.picoclaw/workspace/notes/claw/health`
