import { readFile } from 'node:fs/promises';

import { loadConfig } from './config.js';
import { buildLayout, ensureLayout, type Layout } from './layout.js';
import type { CompanionRequest } from './models.js';
import {
  buildNpmInstallPackageRequest,
  buildRepoRelayPushRequest,
  buildGithubResearchRequest,
  buildStatusSummary,
  buildWorkspaceAnalysisRequest,
  canAutoExecuteRequestType,
  type DecisionResponse,
  type ExecuteResponse,
  type IntakeResponse,
  type LoopbackHealth,
} from './relay-core.js';

type RelayCommand =
  | {
      name: 'health';
    }
  | {
      name: 'status';
      requestId: string;
    }
  | {
      name: 'execute';
      requestId: string;
    }
  | {
      name: 'decision';
      sender: string;
      text: string;
      autoExecute: boolean;
    }
  | {
      name: 'intake-file';
      requestFile: string;
      autoExecute: boolean;
    }
  | {
      name: 'intake-json';
      requestJson: string;
      autoExecute: boolean;
    }
  | {
      name: 'workspace-analysis';
      sender: string;
      path: string;
      prompt: string;
      scope?: 'notes' | 'workspace' | 'repo';
      writeArtifacts: boolean;
      requestId?: string;
      autoExecute: boolean;
    }
  | {
      name: 'github-research';
      sender: string;
      query: string;
      scope?: 'repo' | 'org' | 'user' | 'global';
      repo?: string;
      owner?: string;
      mode: 'generic' | 'issues' | 'pull_requests' | 'code' | 'repositories';
      limit: number;
      requestId?: string;
      autoExecute: boolean;
    }
  | {
      name: 'repo-relay-push';
      sender: string;
      repoPath: string;
      remote?: string;
      branch?: string;
      revision?: string;
      transport?: 'relay' | 'bundle';
      requestId?: string;
      autoExecute: boolean;
    }
  | {
      name: 'npm-install-package';
      sender: string;
      projectPath: string;
      packages: string[];
      scope?: 'project' | 'user';
      dev: boolean;
      global: boolean;
      requestId?: string;
      autoExecute: boolean;
    };

const usage = [
  'Usage:',
  '  picoclaw-ops-relay health',
  '  picoclaw-ops-relay status --request-id <request-id>',
  '  picoclaw-ops-relay execute --request-id <request-id>',
  '  picoclaw-ops-relay decision --sender <telegram:id> --text "</approve ...>" [--auto-execute]',
  '  picoclaw-ops-relay intake-file --request-file <path> [--auto-execute]',
  '  picoclaw-ops-relay intake-json --request-json <json> [--auto-execute]',
  '  picoclaw-ops-relay workspace-analysis --sender <telegram:id> --path <path> --prompt <text> [--scope <notes|workspace|repo>] [--write-artifacts] [--request-id <request-id>] [--no-execute]',
  '  picoclaw-ops-relay github-research --sender <telegram:id> --query <text> [--scope <repo|org|user|global>] [--repo <owner/name>] [--owner <owner>] [--mode <generic|issues|pull_requests|code|repositories>] [--limit <n>] [--request-id <request-id>] [--no-execute]',
  '  picoclaw-ops-relay repo-relay-push --sender <telegram:id> --repo-path <path> [--remote <name>] [--branch <name>] [--revision <rev>] [--transport <relay|bundle>] [--request-id <request-id>] [--no-execute]',
  '  picoclaw-ops-relay npm-install-package --sender <telegram:id> --project-path <path> --package <name> [--package <name> ...] [--scope <project|user>] [--dev] [--global] [--request-id <request-id>] [--no-execute]',
].join('\n');

async function main(): Promise<void> {
  const command = parseRelayArgs(process.argv.slice(2));
  const config = loadConfig();
  const layout = buildLayout(config);

  await ensureLayout(layout);

  switch (command.name) {
    case 'health': {
      const health = await requestLoopback<LoopbackHealth>(config, '/health');
      writeOutput({
        command: command.name,
        health,
      });
      return;
    }

    case 'status': {
      writeOutput({
        command: command.name,
        ...(await buildStatusSummary(layout, command.requestId)),
      });
      return;
    }

    case 'execute': {
      const execute = await executeRequest(config, command.requestId);
      writeOutput({
        command: command.name,
        execute,
        status: await buildStatusSummary(layout, command.requestId),
      });
      return;
    }

    case 'decision': {
      const decision = await requestLoopback<DecisionResponse>(config, '/decision', {
        method: 'POST',
        body: JSON.stringify({
          sender: command.sender,
          text: command.text,
        }),
      });
      let status = await buildStatusSummary(layout, decision.requestId);
      const execute =
        command.autoExecute &&
        decision.outcome === 'approved' &&
        decision.resultStatus === 'ready_for_execution' &&
        canAutoExecuteRequestType(status.request.type)
          ? await executeRequest(config, decision.requestId)
          : null;
      if (execute) {
        status = await buildStatusSummary(layout, decision.requestId);
      }
      writeOutput({
        command: command.name,
        decision,
        execute,
        status,
      });
      return;
    }

    case 'intake-file': {
      const request = JSON.parse(await readFile(command.requestFile, 'utf8')) as CompanionRequest;
      writeOutput({
        command: command.name,
        ...(await runIntakeWorkflow(layout, config, request, command.autoExecute)),
      });
      return;
    }

    case 'intake-json': {
      const request = JSON.parse(command.requestJson) as CompanionRequest;
      writeOutput({
        command: command.name,
        ...(await runIntakeWorkflow(layout, config, request, command.autoExecute)),
      });
      return;
    }

    case 'workspace-analysis': {
      const request = buildWorkspaceAnalysisRequest(config, command);
      writeOutput({
        command: command.name,
        ...(await runIntakeWorkflow(layout, config, request, command.autoExecute)),
      });
      return;
    }

    case 'github-research': {
      const request = buildGithubResearchRequest(command);
      writeOutput({
        command: command.name,
        ...(await runIntakeWorkflow(layout, config, request, command.autoExecute)),
      });
      return;
    }

    case 'repo-relay-push': {
      const request = buildRepoRelayPushRequest(command);
      writeOutput({
        command: command.name,
        ...(await runIntakeWorkflow(layout, config, request, command.autoExecute)),
      });
      return;
    }

    case 'npm-install-package': {
      const request = buildNpmInstallPackageRequest(command);
      writeOutput({
        command: command.name,
        ...(await runIntakeWorkflow(layout, config, request, command.autoExecute)),
      });
      return;
    }
  }
}

function parseRelayArgs(argv: string[]): RelayCommand {
  const [command, ...rest] = argv;

  if (!command) {
    throw new Error(usage);
  }

  if (command === 'health') {
    return {
      name: 'health',
    };
  }

  if (command === 'status') {
    return {
      name: 'status',
      requestId: requireFlagValue(rest, '--request-id'),
    };
  }

  if (command === 'execute') {
    return {
      name: 'execute',
      requestId: requireFlagValue(rest, '--request-id'),
    };
  }

  if (command === 'decision') {
    return {
      name: 'decision',
      sender: requireFlagValue(rest, '--sender'),
      text: requireFlagValue(rest, '--text'),
      autoExecute: rest.includes('--auto-execute'),
    };
  }

  if (command === 'intake-file') {
    return {
      name: 'intake-file',
      requestFile: requireFlagValue(rest, '--request-file'),
      autoExecute: rest.includes('--auto-execute'),
    };
  }

  if (command === 'intake-json') {
    return {
      name: 'intake-json',
      requestJson: requireFlagValue(rest, '--request-json'),
      autoExecute: rest.includes('--auto-execute'),
    };
  }

  if (command === 'workspace-analysis') {
    return {
      name: 'workspace-analysis',
      sender: requireFlagValue(rest, '--sender'),
      path: requireFlagValue(rest, '--path'),
      prompt: requireFlagValue(rest, '--prompt'),
      scope: readFlagValue(rest, '--scope') as 'notes' | 'workspace' | 'repo' | undefined,
      writeArtifacts: rest.includes('--write-artifacts'),
      requestId: readFlagValue(rest, '--request-id'),
      autoExecute: !rest.includes('--no-execute'),
    };
  }

  if (command === 'github-research') {
    const mode = readFlagValue(rest, '--mode') ?? 'generic';
    const limitText = readFlagValue(rest, '--limit');
    const limit = limitText ? parsePositiveInt(limitText, '--limit') : 10;

    if (!['generic', 'issues', 'pull_requests', 'code', 'repositories'].includes(mode)) {
      throw new Error(`unsupported --mode value: ${mode}\n${usage}`);
    }

    return {
      name: 'github-research',
      sender: requireFlagValue(rest, '--sender'),
      query: requireFlagValue(rest, '--query'),
      scope: readFlagValue(rest, '--scope') as 'repo' | 'org' | 'user' | 'global' | undefined,
      repo: readFlagValue(rest, '--repo'),
      owner: readFlagValue(rest, '--owner'),
      mode: mode as 'generic' | 'issues' | 'pull_requests' | 'code' | 'repositories',
      limit,
      requestId: readFlagValue(rest, '--request-id'),
      autoExecute: !rest.includes('--no-execute'),
    };
  }

  if (command === 'repo-relay-push') {
    const transport = readFlagValue(rest, '--transport') ?? 'relay';

    if (!['relay', 'bundle'].includes(transport)) {
      throw new Error(`unsupported --transport value: ${transport}\n${usage}`);
    }

    return {
      name: 'repo-relay-push',
      sender: requireFlagValue(rest, '--sender'),
      repoPath: requireFlagValue(rest, '--repo-path'),
      remote: readFlagValue(rest, '--remote'),
      branch: readFlagValue(rest, '--branch'),
      revision: readFlagValue(rest, '--revision'),
      transport: transport as 'relay' | 'bundle',
      requestId: readFlagValue(rest, '--request-id'),
      autoExecute: !rest.includes('--no-execute'),
    };
  }

  if (command === 'npm-install-package') {
    const scope = readFlagValue(rest, '--scope');
    const packages = readFlagValues(rest, '--package');

    if (packages.length === 0) {
      throw new Error(`npm-install-package requires at least one --package <name>\n${usage}`);
    }

    if (scope !== undefined && !['project', 'user'].includes(scope)) {
      throw new Error(`unsupported --scope value: ${scope}\n${usage}`);
    }

    return {
      name: 'npm-install-package',
      sender: requireFlagValue(rest, '--sender'),
      projectPath: requireFlagValue(rest, '--project-path'),
      packages,
      scope: scope as 'project' | 'user' | undefined,
      dev: rest.includes('--dev'),
      global: rest.includes('--global'),
      requestId: readFlagValue(rest, '--request-id'),
      autoExecute: !rest.includes('--no-execute'),
    };
  }

  throw new Error(`unknown relay command: ${command}\n${usage}`);
}

async function runIntakeWorkflow(
  layout: Layout,
  config: ReturnType<typeof loadConfig>,
  request: CompanionRequest,
  autoExecute: boolean,
): Promise<{
  request: CompanionRequest;
  intake: IntakeResponse;
  execute: ExecuteResponse | null;
  status: Awaited<ReturnType<typeof buildStatusSummary>>;
}> {
  const intake = await requestLoopback<IntakeResponse>(config, '/intake', {
    method: 'POST',
    body: JSON.stringify(request),
  });
  const execute =
    autoExecute && intake.resultStatus === 'ready_for_execution'
      ? await executeRequest(config, intake.requestId)
      : null;

  return {
    request,
    intake,
    execute,
    status: await buildStatusSummary(layout, intake.requestId),
  };
}

async function executeRequest(
  config: ReturnType<typeof loadConfig>,
  requestId: string,
): Promise<ExecuteResponse> {
  return requestLoopback<ExecuteResponse>(config, '/execute', {
    method: 'POST',
    body: JSON.stringify({
      requestId,
    }),
  });
}

async function requestLoopback<T>(
  config: ReturnType<typeof loadConfig>,
  path: string,
  init?: RequestInit,
): Promise<T> {
  const response = await fetch(`http://${config.listenHost}:${config.listenPort}${path}`, {
    ...init,
    headers: {
      'content-type': 'application/json',
      ...(init?.headers ?? {}),
    },
  });
  const text = await response.text();
  const payload = text.length > 0 ? tryParseJson(text) : null;

  if (!response.ok) {
    const message =
      payload && typeof payload === 'object' && 'error' in payload && typeof payload.error === 'string'
        ? payload.error
        : text || `HTTP ${response.status}`;
    throw new Error(`loopback ${init?.method ?? 'GET'} ${path} failed: ${message}`);
  }

  if (payload === null) {
    throw new Error(`loopback ${init?.method ?? 'GET'} ${path} returned empty response`);
  }

  return payload as T;
}

function tryParseJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch (error) {
    throw new Error(`failed to parse loopback JSON response: ${text}`);
  }
}

function requireFlagValue(args: string[], flagName: string): string {
  const value = readFlagValue(args, flagName);

  if (value === undefined) {
    throw new Error(`missing ${flagName}\n${usage}`);
  }

  return value;
}

function readFlagValue(args: string[], flagName: string): string | undefined {
  const index = args.indexOf(flagName);

  if (index === -1) {
    return undefined;
  }

  const value = args[index + 1];

  return value === undefined || value.startsWith('--') ? undefined : value;
}

function parsePositiveInt(value: string, flagName: string): number {
  const parsed = Number.parseInt(value, 10);

  if (!Number.isInteger(parsed) || parsed <= 0) {
    throw new Error(`${flagName} must be a positive integer\n${usage}`);
  }

  return parsed;
}

function readFlagValues(argv: string[], flagName: string): string[] {
  const values: string[] = [];

  for (let index = 0; index < argv.length; index += 1) {
    if (argv[index] === flagName) {
      const value = argv[index + 1];

      if (value !== undefined) {
        values.push(value);
      }
    }
  }

  return values;
}

function writeOutput(value: unknown): void {
  process.stdout.write(`${JSON.stringify(value, null, 2)}\n`);
}

main().catch((error: unknown) => {
  const message = error instanceof Error ? error.message : String(error);
  process.stderr.write(
    `${JSON.stringify({ ts: new Date().toISOString(), level: 'error', message })}\n`,
  );
  process.exitCode = 1;
});
