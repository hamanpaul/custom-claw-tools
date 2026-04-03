# Famiclean Engineering TODO

## Immediate follow-up

- Run the new CLI against the real heater after moving the skill to Orangepi3
- Replace placeholder `.env` values with real Telegram and SMTP credentials
- Decide whether `EMAIL_TO` should support one or multiple recipients in production

## Protocol hardening

- Verify whether all devices always return `request_usage ` to the discovery source port
- Verify whether any models require extra fields in the `settemp` control payload
- Capture more than one device generation to confirm field stability

## Operational hardening

- Add log rotation or a bounded log strategy for scheduled runs
- Decide whether failed notifications should retry immediately or only at next schedule
- Decide whether a manual `--force-notify` run should advance state in production

## Future product choices

- If Google Home cannot present gas totals natively, design a NAS-hosted dashboard or API for that metric
- If Matter route becomes attractive later, re-check Google Home's currently supported Matter device types
- If Tuya route is pursued, define the Famiclean-to-Tuya adapter boundary before writing cloud code
