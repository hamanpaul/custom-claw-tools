# Famiclean Tasks

- [x] Capture and decode the real-device Famiclean UDP protocol
- [x] Confirm the raw-to-display gas conversion rule (`heatvalue_total / 9100`)
- [x] Scaffold a reusable Orangepi3 / Picoclaw skill
- [x] Implement CLI commands for discover / get-total-gas / get-temp / set-temp
- [x] Implement a persisted daily threshold-check workflow
- [x] Add Telegram and Email notification hooks
- [x] Write deployment and protocol reference notes
- [x] Write the project specification and implementation plan
- [ ] Validate the CLI against the real heater on Orangepi3
- [ ] Fill real Telegram configuration in local `config/.env` copied from `config/.env.example`
- [ ] Fill real SMTP / Email configuration in local `config/.env` copied from `config/.env.example`
- [ ] Install the daily 08:00 schedule on Orangepi3
- [ ] Run end-to-end production validation with a real 20-M3 threshold crossing
- [ ] Decide whether Google Home should expose only water temperature or also a gas-usage companion surface
- [ ] Choose the second-phase integration route: direct Google vs Tuya bridge
