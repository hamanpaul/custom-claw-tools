---
name: ops-companion
description: "Hand off repo, system, research, and approval work to picoclaw-ops-companion. Use intake, decision, execute, or listen with audit plus TOTP approval. workspace_analysis and github_research have live execute paths today."
---

# Ops Companion Skill

Use this skill when the request needs repo, system, research, or approval handling that should not be executed directly inside PicoClaw's default workspace policy.

## Fixed paths

- project root: `/home/haman/custom-claw-tools/picoclaw-ops-companion`
- artifacts root: `/home/haman/.picoclaw/workspace/notes/ops-companion`
- TOTP secret: `~/.config/picoclaw-ops-companion/totp.secret`
- loopback listener default: `http://127.0.0.1:45450`
- live skill path: `/home/haman/.picoclaw/workspace/skills/ops-companion/SKILL.md`
- legacy note: `/home/haman/.picoclaw/workspace/notes/claw/ops-companion-skill.md`

## When to use this skill

Use `ops-companion` when the task:

- touches repo, system, research, or approval flows
- needs audit artifacts or risk classification
- needs high-risk approval with Telegram sender plus TOTP
- crosses PicoClaw's normal workspace or policy boundary
- should be routed to the companion execution layer instead of direct ad hoc shell work

## Role split

### PicoClaw

- clarify the request
- turn the request into structured JSON
- relay `/approve <job-id> <totp>` or `/reject <job-id>` from Telegram
- if needed, call the companion through CLI or loopback HTTP
- summarize the result back to the user

### picoclaw-ops-companion

- validate the request schema
- classify risk
- create approval jobs
- verify sender, TOTP, and TTL
- write request, result, and audit artifacts
- expose loopback endpoints for local relay use
- run allowlisted execution wrappers and Copilot sessions

## Current support

### Live execute path today

- `workspace_analysis`
- `github_research` (read-only GitHub research via a restricted Copilot SDK session)

### Live companion entrypoints today

- CLI: `bootstrap`, `listen`, `intake`, `decision`, `execute`, `totp`, `totp-gen`
- loopback listener: `GET /health`, `POST /intake`, `POST /decision`, `POST /execute`

### Intake and approval exist, but execute is not implemented yet

- `repo_relay_push`

### Schema exists, but execute is not implemented yet

- `npm_install_package`

## Required workflow

1. Build a structured request JSON.
2. Choose one entrypoint:
   - CLI: run `intake`, `decision`, and `execute` from the project root.
   - Loopback: POST to `http://127.0.0.1:45450/intake`, `/decision`, and `/execute` if a local relay or wrapper is already using the listener.
3. Read `requestId`, `resultStatus`, and `approvalJobId` from the output.
4. If `resultStatus` is `awaiting_approval`, ask the user for `/approve <job-id> <totp>` or `/reject <job-id>` and relay the exact sender plus text to `decision`.
5. Only run `execute --request-id <request-id>` or POST `/execute` when `resultStatus` is `ready_for_execution`.
6. Summarize the result honestly and include artifact paths when they help.

## Commands

### Start listener

```bash
cd /home/haman/custom-claw-tools/picoclaw-ops-companion
npm run dev -- listen --host 127.0.0.1 --port 45450
```

### Health probe

```bash
curl http://127.0.0.1:45450/health
```

### Intake example

```bash
cd /home/haman/custom-claw-tools/picoclaw-ops-companion
cat <<'JSON' | npm run dev -- intake --request -
{
  "requestId": "ops-smoke-001",
  "requestedBy": "telegram:8313353234",
  "type": "workspace_analysis",
  "scope": "notes",
  "target": {
    "path": "/home/haman/.picoclaw/workspace/notes"
  },
  "payload": {
    "prompt": "Summarize the top-level notes layout for troubleshooting.",
    "writeArtifacts": false
  }
}
JSON
```

### Decision relay

```bash
cd /home/haman/custom-claw-tools/picoclaw-ops-companion
npm run dev -- decision --sender telegram:8313353234 --text "/approve <job-id> 123456"
```

```bash
cd /home/haman/custom-claw-tools/picoclaw-ops-companion
npm run dev -- decision --sender telegram:8313353234 --text "/reject <job-id>"
```

### Execute

```bash
cd /home/haman/custom-claw-tools/picoclaw-ops-companion
npm run dev -- execute --request-id <request-id>
```

## Guardrails

- Do not claim unsupported wrappers already execute.
- `github_research` is read-only research, not a general shell pass-through.
- Do not bypass the companion schema, approval, or audit flow.
- Do not ask for long-lived secrets; approval only needs the current 6-digit TOTP.
- If the companion returns `not implemented`, `failed`, `rejected`, or `expired`, report that state honestly.
- Keep PicoClaw as the front desk and the companion as the execution layer.
