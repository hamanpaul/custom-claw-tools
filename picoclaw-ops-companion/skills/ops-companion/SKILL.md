---
name: ops-companion
description: "Route repo, research, and approval tasks through fixed ops helper commands on this PicoClaw host. Prefer `ops-notes-analysis`, `ops-workspace-analysis`, `ops-github-research`, `ops-repo-relay-push`, `ops-npm-install-package`, `ops-approve`, `ops-reject`, and `ops-request-status` over raw shell."
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
- live helper commands root: `/home/haman/.picoclaw/workspace/bin`

## When to use this skill

Use `ops-companion` when the task:

- asks to analyze notes/workspace/repo content through the companion bridge
- asks for GitHub research through the companion bridge
- asks to approve or reject an existing ops job
- asks for request/job status from `ops-companion`
- needs audit artifacts or risk classification
- needs high-risk approval with Telegram sender plus TOTP
- crosses PicoClaw's normal workspace or policy boundary
- should be routed to the companion execution layer instead of direct ad hoc shell work

## Critical routing rule

For requests covered by this skill, **prefer the fixed helper commands in `~/.picoclaw/workspace/bin` and do not replace them with generic `ls`, `find`, `gh`, or ad hoc shell pipelines**.

If the user asks for:

- notes analysis -> use `ops-notes-analysis`
- workspace/repo path analysis -> use `ops-workspace-analysis`
- GitHub research -> use `ops-github-research`
- create repo push approval job -> use `ops-repo-relay-push`
- create npm install request -> use `ops-npm-install-package`
- `/approve <job-id> <totp>` -> use `ops-approve`
- `/reject <job-id>` -> use `ops-reject`
- status lookup -> use `ops-request-status`

Only fall back to raw shell if the helper command cannot express the request.

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

- MCP tools:
  - `mcp_opscompanion_health`
  - `mcp_opscompanion_notes_analysis`
  - `mcp_opscompanion_workspace_analysis`
  - `mcp_opscompanion_github_research`
  - `mcp_opscompanion_repo_relay_push`
  - `mcp_opscompanion_npm_install_package`
  - `mcp_opscompanion_approve_job`
  - `mcp_opscompanion_reject_job`
  - `mcp_opscompanion_request_status`
  - `mcp_opscompanion_execute_request`
- CLI: `bootstrap`, `listen`, `intake`, `decision`, `execute`, `totp`, `totp-gen`
- relay wrapper: `bin/picoclaw-ops-relay`
- helper wrappers:
  - `ops-notes-analysis`
  - `ops-workspace-analysis`
  - `ops-github-research`
  - `ops-repo-relay-push`
  - `ops-npm-install-package`
  - `ops-approve`
  - `ops-reject`
  - `ops-request-status`
- loopback listener: `GET /health`, `POST /intake`, `POST /decision`, `POST /execute`

### High-risk execute path today

- `repo_relay_push`
  - `transport=relay` performs a real `git push`
  - `transport=bundle` writes a `.bundle` artifact for handoff
- `npm_install_package`
  - `scope=project` executes a project-local install and must not use `--global`
  - `scope=user` requires `--global` and still requires approval before execution

## Required workflow

1. Determine sender identity. Use `telegram:<sender-id>` when available.
2. Prefer the `mcp_opscompanion_*` MCP tools when available through the PicoClaw gateway path.
3. If MCP tool selection is unavailable for the current surface, fall back to a fixed helper command from `~/.picoclaw/workspace/bin`.
4. Read `requestId`, `resultStatus`, and `approvalJobId` from the JSON output.
5. If `resultStatus` is `awaiting_approval`, show `/approve <job-id> <totp>` or `/reject <job-id>`.
6. If the user provides `/approve` or `/reject`, relay it with `mcp_opscompanion_approve_job` / `mcp_opscompanion_reject_job` or the matching helper command.
7. Summarize the result honestly and include artifact paths when they help.

## MCP-first routing

When the current PicoClaw surface exposes MCP tools, use them directly:

- notes analysis -> `mcp_opscompanion_notes_analysis`
- workspace/repo path analysis -> `mcp_opscompanion_workspace_analysis`
- GitHub research -> `mcp_opscompanion_github_research`
- create repo push approval job -> `mcp_opscompanion_repo_relay_push`
- create npm install request -> `mcp_opscompanion_npm_install_package`
- approve job -> `mcp_opscompanion_approve_job`
- reject job -> `mcp_opscompanion_reject_job`
- request status -> `mcp_opscompanion_request_status`
- explicit execution after approval -> `mcp_opscompanion_execute_request`

## Mandatory command mapping

Use these exact helper commands when MCP tools are not available:

```bash
ops-notes-analysis SENDER "PROMPT..."
```

```bash
ops-workspace-analysis [--scope notes|workspace|repo] [--write-artifacts] SENDER PATH "PROMPT..."
```

```bash
ops-github-research [--mode MODE] [--limit N] SENDER OWNER REPO "QUERY..."
```

```bash
ops-repo-relay-push [--remote NAME] [--branch NAME] [--revision REV] [--transport relay|bundle] [--no-execute] SENDER REPO_PATH
```

```bash
ops-npm-install-package [--scope project|user] [--dev] [--global] --package NAME [--package NAME ...] [--no-execute] SENDER PROJECT_PATH
```

- `--scope project` + `--global` is invalid
- `--scope user` without `--global` is invalid

```bash
ops-approve SENDER JOB_ID TOTP
```

```bash
ops-reject SENDER JOB_ID
```

```bash
ops-request-status REQUEST_ID
```

Natural-language mapping examples:

- “分析 notes 頂層結構” -> `ops-notes-analysis telegram:<PRIMARY_USER_ID> "分析 notes 頂層結構"`
- “分析 `/home/haman/.picoclaw/workspace/notes/root-note`” -> `ops-workspace-analysis telegram:<PRIMARY_USER_ID> /home/haman/.picoclaw/workspace/notes/root-note "..."`  
- “研究 `hamanpaul/custom-claw-tools` 最近的 obs-auto-moc 變更” -> `ops-github-research telegram:<PRIMARY_USER_ID> hamanpaul custom-claw-tools "..."`
- “/approve job-xxx 123456” -> `ops-approve telegram:<PRIMARY_USER_ID> job-xxx 123456`
- “/reject job-xxx” -> `ops-reject telegram:<PRIMARY_USER_ID> job-xxx`

## Advanced entrypoints

If helper commands are insufficient, then use:

- `bin/picoclaw-ops-relay`
- `picoclaw-ops-companion` CLI
- loopback listener `http://127.0.0.1:45450`

## Guardrails

- Do not bypass the helper commands when they already fit the request.
- Do not claim unsupported wrappers already execute.
- `github_research` is read-only research, not a general shell pass-through.
- Do not bypass the companion schema, approval, or audit flow.
- Do not ask for long-lived secrets; approval only needs the current 6-digit TOTP.
- If the companion returns `failed`, `rejected`, or `expired`, report that state honestly.
- Keep PicoClaw as the front desk and the companion as the execution layer.
