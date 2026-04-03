---
name: fami-claw-skill
description: 處理 Famiclean 熱水器、瓦斯、水溫與剩餘瓦斯量相關請求，包含 discovery、總瓦斯用量查詢、目前設定溫度查詢、溫度設定與每日門檻通知。當使用者提到熱水器、瓦斯、水溫或剩餘瓦斯量時，優先使用這個 skill。
---

# Fami Claw Skill

## Overview

Use this skill to control a single Famiclean water heater over LAN from Orangepi3 or Picoclaw-style hosts.
The bundled scripts cover device discovery, total gas queries, temperature reads, temperature changes, and the 08:00 daily threshold check with Telegram and Email notifications.
For PicoClaw-triggered runs, prefer the skill-local `./fami-claw` wrapper so the agent can use stable command names and JSON output.

## Routing hints

- Prefer this skill when the user mentions **熱水器**, **瓦斯**, **水溫**, or **剩餘瓦斯量** in the context of the Famiclean device.
- Treat **剩餘瓦斯量** as **the remaining amount to the next 20-M3 threshold**, computed from the latest `gas_total_m3` as `20 - (gas_total_m3 % 20)`.
- When answering a 剩餘瓦斯量 request, report both the current total gas usage and the computed remaining amount.

## Quick Start

1. Read `references/protocol.md` if you need the packet shapes or protocol quirks.
2. Read `references/deployment.md` if you need local `.env` setup, cron, or deployment guidance.
3. Run the skill-local wrapper or the underlying CLI entrypoint:

```bash
./fami-claw discover
./fami-claw read-gas
./fami-claw read-temp
./fami-claw set-temp 42
./fami-claw check-threshold

python scripts/famiclean.py discover
python scripts/famiclean.py get-total-gas
python scripts/famiclean.py get-temp
python scripts/famiclean.py set-temp 42
python scripts/famiclean.py check-threshold
```

## PicoClaw execution contract

- PicoClaw live triggers should execute `~/.picoclaw/workspace/skills/fami-claw-skill/fami-claw`.
- Keep `~/.picoclaw/workspace/bin/fami-claw` as a symlink or copy of the same wrapper when you want a shell-friendly path.
- The wrapper defaults to `--json` output and translates PicoClaw-friendly aliases:
  - `read-temp` -> `get-temp`
  - `water-temp` -> `get-temp`
  - `read-gas` -> `get-total-gas`
  - `remaining-gas` -> `get-total-gas`
  - `set-temperature` -> `set-temp`
- When changing temperature, always follow with a read (`read-temp` / `get-temp`) and report the confirmed value.
- When the user asks for 剩餘瓦斯量, run `read-gas` / `get-total-gas` and answer with `remaining_to_next_threshold_m3`.

## Core Workflow

### 1. Discover or resolve the device

- Prefer configured `DEVICE_IP` / `DEVICE_MAC` from your local `config/.env` copied from `config/.env.example`.
- Use `discover` when IP or MAC is missing or needs verification.
- Keep one UDP socket alive across discovery and follow-up requests because `request_usage ` may reply to the source port used by the earlier `request_mac ` discovery packet.

### 2. Query gas usage or temperature

- Use `get-total-gas` or `read-gas` to read the app-aligned total gas display value in `M3`.
- Use the same gas-reading command for **剩餘瓦斯量**; the result includes `remaining_to_next_threshold_m3`.
- Use `get-temp` or `read-temp` to read the current `settemp`.
- Idle 時 gas display value is `round(heatvalue_total / 9100, 2)`.
- Active heating 時 gas display value is aligned to the phone app by using `request_usage.heatvalue_total + request_data.heatvalue_count` before dividing by `9100`.
- The remaining amount to the next threshold is computed with the current 20-M3 rule: `20 - (gas_total_m3 % 20)`.

### 3. Change temperature safely

- Use `set-temp <N>` or `set-temperature <N>` to request a new target temperature.
- Reject values above `50°C`.
- Confirm changes by polling `request_data ` after sending the control payload.

### 4. Run the daily threshold workflow

- Use `check-threshold` for the 08:00 scheduled check.
- The first successful run bootstraps state without sending retrospective alerts.
- Later runs notify when the display total crosses a new `20 M3` boundary.
- If one or more configured notification channels fail, the threshold state is not advanced so the alert can be retried.

## Commands

### `discover`

- Find a device by broadcast or explicitly assigned IP / MAC.
- Returns device IP, MAC, and raw discovery payload.

### `get-total-gas`

- Reads `request_usage ` and returns:
  - raw cumulative `heatvalue_total`
  - live current-cycle `heatvalue_count`
  - app-aligned display `gas_total_m3`
  - live display `gas_count_m3`
  - `remaining_to_next_threshold_m3`
- PicoClaw wrapper alias: `read-gas`

### `get-temp`

- Reads `request_data ` and returns the current `settemp`.
- PicoClaw wrapper alias: `read-temp`

### `set-temp`

- Sends `control_type:waterheatersettemp:<N>...`
- Verifies the final `settemp` by polling `request_data `.
- PicoClaw wrapper alias: `set-temperature`

### `check-threshold`

- Loads `data/famiclean-state.json`
- Reads current gas total
- Calculates the current fixed 20-M3 threshold
- Sends Telegram and Email alerts when a new threshold is crossed

## Resources

### `scripts/famiclean.py`

CLI entrypoint for all interactive and scheduled tasks.

### `fami-claw`

Skill-local PicoClaw wrapper that resolves the project home automatically, defaults to JSON output, and accepts stable aliases such as `read-temp`.

### `scripts/tools/`

Protocol, config, state, and notification helpers used by the CLI.

### `references/protocol.md`

Packet-level protocol notes, field mapping, and the `request_usage ` reply-port quirk.

### `references/deployment.md`

Deployment notes for Orangepi3 / Picoclaw, `.env` configuration, and daily cron wiring.
