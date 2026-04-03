# Deployment Notes

## Layout

- Skill directory:
  `skills/fami-claw-skill`
- Skill-local wrapper:
  `skills/fami-claw-skill/fami-claw`
- Config template:
  `config/.env.example`
- Local runtime config:
  `config/.env`
- Runtime state:
  `data/famiclean-state.json`

## PicoClaw live install

Install the skill metadata and wrapper into the PicoClaw workspace, and keep a shell-friendly symlink in `workspace/bin`.

```bash
install -d ~/.picoclaw/workspace/skills/fami-claw-skill ~/.picoclaw/workspace/bin
install -m 755 skills/fami-claw-skill/fami-claw ~/.picoclaw/workspace/skills/fami-claw-skill/fami-claw
install -m 644 skills/fami-claw-skill/SKILL.md ~/.picoclaw/workspace/skills/fami-claw-skill/SKILL.md
ln -sfn ~/.picoclaw/workspace/skills/fami-claw-skill/fami-claw ~/.picoclaw/workspace/bin/fami-claw
```

The wrapper defaults to `--json` and accepts PicoClaw-friendly aliases such as `read-temp`, `read-gas`, and `set-temperature`.

## Required configuration

Start from the committed template, then fill the local runtime file:

```bash
cp config/.env.example config/.env
```

Populate `config/.env` with at least:

- `DEVICE_IP`
- `DEVICE_MAC`
- `BROADCAST_IP`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `EMAIL_SMTP_HOST`
- `EMAIL_FROM`
- `EMAIL_TO`

## Interactive commands

```bash
./skills/fami-claw-skill/fami-claw read-gas
./skills/fami-claw-skill/fami-claw read-temp
./skills/fami-claw-skill/fami-claw set-temp 42

python skills/fami-claw-skill/scripts/famiclean.py get-total-gas
python skills/fami-claw-skill/scripts/famiclean.py get-temp
python skills/fami-claw-skill/scripts/famiclean.py set-temp 42
```

## Daily 08:00 check

Use cron on Orangepi3 to invoke the bundled checker once per day.

Example:

```cron
0 8 * * * cd /opt/faminclean-ghome && skills/fami-claw-skill/fami-claw check-threshold >> /var/log/famiclean-check.log 2>&1
```

## Operational assumptions

- The first successful `check-threshold` run bootstraps the state file without sending a historical alert.
- If the total jumps across multiple 20-M3 boundaries between runs, the checker sends one alert containing every crossed threshold and advances the state to the highest confirmed threshold only after notification succeeds.
- If notification fails, the state is left behind on purpose so the alert can be retried.
