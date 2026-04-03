# Famiclean Implementation Plan

## Phase 1: Orangepi3 / Picoclaw Skill

### Milestone 1: Protocol-capable CLI

- Build a single entrypoint at `scripts/famiclean.py`
- Hide UDP details inside `scripts/tools/`
- Support discovery, total gas read, temperature read, and temperature set
- Keep one UDP socket alive across discovery and usage requests

### Milestone 2: Notification and threshold workflow

- Load runtime config from local `config/.env` copied from `config/.env.example`
- Store notification progress in `data/famiclean-state.json`
- Implement fixed 20-M3 threshold logic on display values
- Implement bootstrap-without-retroactive-alert behavior
- Support Telegram and Email

### Milestone 3: Skill packaging

- Write `SKILL.md` for operational guidance
- Add protocol and deployment references
- Keep the skill self-contained enough to move onto Orangepi3 later

## Phase 2: Google Home Research

### Track A: Direct Google route

- Validate `WATERHEATER` + `TemperatureControl` as the semantic model
- Confirm whether Google Home can carry cumulative gas usage in a native way
- If needed, split responsibility:
  - Google Home for water temperature control
  - self-hosted dashboard / skill for gas usage

### Track B: Smart Life / Tuya route

- Evaluate whether Famiclean can realistically be adapted into the Tuya ecosystem
- Compare the integration cost with the direct Google route
- Treat Tuya as a backup route, not the default

## Exit Criteria

- Phase 1 is done when the CLI can discover, read gas, read temperature, set temperature, and perform the daily threshold workflow with persisted state.
- Phase 2 is done when there is a clear go / no-go decision for:
  - direct Google Smart Home integration
  - Tuya / Smart Life bridge integration
