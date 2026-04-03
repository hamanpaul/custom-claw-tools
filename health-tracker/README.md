# health-tracker

`health-tracker` now includes a local GarminDB integration layer that can:

- run GarminDB sync without committing secrets into the repo
- ingest GarminDB SQLite outputs
- write canonical `raw/`, `daily/`, and refreshed `reports/` notes under `notes/claw/health`
- send a concise Telegram summary after report updates when runtime notification settings are configured

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

Do both in one step (this now also refreshes affected month / quarter / year reports):

```bash
cd /home/paul_chen/prj_pri/custom-claw-tools/health-tracker
./bin/health-tracker-garmin --runtime-config ~/.config/health-tracker/garmin-runtime.json sync-and-ingest
```

Refresh reports from existing canonical daily notes without running Garmin sync:

```bash
cd /home/paul_chen/prj_pri/custom-claw-tools/health-tracker
./bin/health-tracker-garmin --runtime-config ~/.config/health-tracker/garmin-runtime.json update-reports
```

## Current MVP mapping

The first implementation maps GarminDB into:

- sleep duration / bedtime / wake time / sleep score
- daily steps / distance（沿用 Garmin account measurement system）/ activity time / active calories
- activity sessions as daily training summaries
- raw Garmin import evidence into canonical `raw/YYYY/MM/DD/...`
- month / quarter / year reports rebuilt from canonical `daily/YYYY-MM-DD.md`

The first implementation does **not** yet promise stable support for Garmin high-level derived metrics such as readiness/recovery.

## Telegram report notifications

If `notifications.telegram` is configured in the repo-external runtime config,
`ingest-garmin`, `sync-and-ingest`, and `update-reports` will send a concise
Telegram summary **only when report files actually change**.

Runtime example:

```json
{
  "notifications": {
    "telegram": {
      "enabled": true,
      "chat_id": "telegram:<user-id>",
      "fallback_to_picoclaw_config": true,
      "bot_token_file": "~/.config/health-tracker/telegram-bot-token"
    }
  }
}
```

Notes:

- Telegram secrets stay outside the repo.
- If `bot_token_file` / `bot_token_env` is omitted, health-tracker will
  attempt to reuse a supported token field from `~/.picoclaw/config.json`.
- If `chat_id` is omitted, health-tracker will try to infer it from a single
  `channels.telegram.allow_from` entry in `~/.picoclaw/config.json`.
- Use `--no-notify` to suppress the Telegram message for a manual rerun.

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

If the pi3 runtime does not already have GarminDB installed, install it as the
`haman` user. On minimal Debian / Armbian images, `python3 -m pip` may be
missing, so bootstrap user-local pip first:

```bash
curl -fsSL https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip.py
python3 /tmp/get-pip.py --user --break-system-packages
python3 -m pip install --user --break-system-packages garmindb
rm -f /tmp/get-pip.py
```

If `garmindb_cli.py` is installed under `~/.local/bin`, point the runtime config
at the explicit executable path:

```json
{
  "garmindb_cli": "/home/haman/.local/bin/garmindb_cli.py"
}
```

Expected pi3 runtime layout:

- repo root: `/home/haman/custom-claw-tools/health-tracker`
- live wrapper: `/home/haman/.picoclaw/workspace/bin/health-tracker-garmin`
- runtime config: `/home/haman/.config/health-tracker/garmin-runtime.json`
- GarminDB config: `/home/haman/.GarminDb/GarminConnectConfig.json`
- canonical notes root: `/home/haman/.picoclaw/workspace/notes/claw/health`

Populate the repo-external Garmin config before the first live sync. The
GarminDB config must use `credentials.password_file`; do not put inline
passwords into `GarminConnectConfig.json`.

Once the repo-external Garmin config and password file exist, run:

```bash
/home/haman/.picoclaw/workspace/bin/health-tracker-garmin \
  --runtime-config /home/haman/.config/health-tracker/garmin-runtime.json \
  sync-and-ingest --latest
```
