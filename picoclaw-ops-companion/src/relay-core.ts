import { randomBytes } from 'node:crypto';
import { readdir } from 'node:fs/promises';
import { isAbsolute, join, relative, resolve, sep } from 'node:path';

import { loadApprovalJob, loadRequestArtifact, loadResultArtifact } from './artifacts.js';
import type { AppConfig } from './config.js';
import type { Layout } from './layout.js';
import type { ApprovalJob, CompanionRequest, IntakeResult } from './models.js';
import {
  processExecutionRequest,
  processIntakeRequest,
  processRelayDecision,
} from './operations.js';

export type LoopbackHealth = {
  ok: boolean;
  host: string;
  port: number;
  projectRoot: string;
  workspaceRoot: string;
  notesRoot: string;
  copilotModel: string | null;
  copilotCliUrl: string | null;
  copilotCliPath: string | null;
};

export type IntakeResponse = Awaited<ReturnType<typeof processIntakeRequest>>;
export type DecisionResponse = Awaited<ReturnType<typeof processRelayDecision>>;
export type ExecuteResponse = Awaited<ReturnType<typeof processExecutionRequest>>;

export type WorkspaceAnalysisInput = {
  sender: string;
  path: string;
  prompt: string;
  scope?: 'notes' | 'workspace' | 'repo';
  writeArtifacts: boolean;
  requestId?: string;
};

export type GithubResearchInput = {
  sender: string;
  query: string;
  scope?: 'repo' | 'org' | 'user' | 'global';
  repo?: string;
  owner?: string;
  mode: 'generic' | 'issues' | 'pull_requests' | 'code' | 'repositories';
  limit: number;
  requestId?: string;
};

export type RepoRelayPushInput = {
  sender: string;
  repoPath: string;
  remote?: string;
  branch?: string;
  revision?: string;
  transport?: 'relay' | 'bundle';
  requestId?: string;
};

export type NpmInstallPackageInput = {
  sender: string;
  projectPath: string;
  packages: string[];
  scope?: 'project' | 'user';
  dev: boolean;
  global: boolean;
  requestId?: string;
};

export type StatusSummary = {
  requestId: string;
  paths: {
    requestPath: string;
    resultPath: string;
    approvalPath: string | null;
    auditPaths: string[];
  };
  request: CompanionRequest;
  result: IntakeResult;
  approvalJob: ApprovalJob | null;
};

export function buildLoopbackHealth(config: AppConfig): LoopbackHealth {
  return {
    ok: true,
    host: config.listenHost,
    port: config.listenPort,
    projectRoot: config.projectRoot,
    workspaceRoot: config.workspaceRoot,
    notesRoot: config.notesRoot,
    copilotModel: config.copilotModel ?? null,
    copilotCliUrl: config.copilotCliUrl ?? null,
    copilotCliPath: config.copilotCliPath ?? null,
  };
}

export async function runIntakeWorkflowDirect(
  layout: Layout,
  config: AppConfig,
  request: CompanionRequest,
  autoExecute: boolean,
): Promise<{
  request: CompanionRequest;
  intake: IntakeResponse;
  execute: ExecuteResponse | null;
  status: StatusSummary;
}> {
  const intake = await processIntakeRequest(layout, config, request);
  const execute =
    autoExecute && intake.resultStatus === 'ready_for_execution'
      ? await processExecutionRequest(layout, config, intake.requestId)
      : null;

  return {
    request,
    intake,
    execute,
    status: await buildStatusSummary(layout, intake.requestId),
  };
}

export async function runDecisionWorkflowDirect(
  layout: Layout,
  config: AppConfig,
  input: {
    sender: string;
    text: string;
  },
  autoExecute: boolean,
): Promise<{
  decision: DecisionResponse;
  execute: ExecuteResponse | null;
  status: StatusSummary;
}> {
  const decision = await processRelayDecision(layout, config, input);
  let status = await buildStatusSummary(layout, decision.requestId);
  const execute =
    autoExecute &&
    decision.outcome === 'approved' &&
    decision.resultStatus === 'ready_for_execution' &&
    canAutoExecuteRequestType(status.request.type)
      ? await processExecutionRequest(layout, config, decision.requestId)
      : null;

  if (execute) {
    status = await buildStatusSummary(layout, decision.requestId);
  }

  return {
    decision,
    execute,
    status,
  };
}

export async function runExecuteWorkflowDirect(
  layout: Layout,
  config: AppConfig,
  requestId: string,
): Promise<{
  execute: ExecuteResponse;
  status: StatusSummary;
}> {
  const execute = await processExecutionRequest(layout, config, requestId);

  return {
    execute,
    status: await buildStatusSummary(layout, requestId),
  };
}

export function buildWorkspaceAnalysisRequest(
  config: AppConfig,
  command: WorkspaceAnalysisInput,
): CompanionRequest {
  const targetPath = resolve(command.path);
  const scope = command.scope ?? detectWorkspaceScope(config, targetPath);
  const allowedRoot = allowedRootForScope(config, scope);

  ensureWithinRoot(targetPath, allowedRoot, `workspace-analysis ${scope}`);

  return {
    requestId: command.requestId ?? buildRequestId('workspace-analysis'),
    requestedBy: command.sender,
    type: 'workspace_analysis',
    scope,
    target: {
      path: targetPath,
    },
    payload: {
      prompt: command.prompt,
      writeArtifacts: command.writeArtifacts,
    },
  };
}

export function buildGithubResearchRequest(
  command: GithubResearchInput,
): CompanionRequest {
  const scope = resolveGithubScope(command);

  if (scope === 'repo' && !command.repo) {
    throw new Error('github-research with repo scope requires --repo <owner/name>');
  }

  if ((scope === 'org' || scope === 'user') && !command.owner) {
    throw new Error(`github-research with ${scope} scope requires --owner <owner>`);
  }

  if (scope === 'global' && (command.repo || command.owner)) {
    throw new Error('github-research with global scope cannot include --repo or --owner');
  }

  return {
    requestId: command.requestId ?? buildRequestId('github-research'),
    requestedBy: command.sender,
    type: 'github_research',
    scope,
    target: {
      ...(command.repo ? { repo: command.repo } : {}),
      ...(command.owner ? { owner: command.owner } : {}),
    },
    payload: {
      query: command.query,
      mode: command.mode,
      limit: command.limit,
    },
  };
}

export function buildRepoRelayPushRequest(
  command: RepoRelayPushInput,
): CompanionRequest {
  return {
    requestId: command.requestId ?? buildRequestId('repo-relay-push'),
    requestedBy: command.sender,
    type: 'repo_relay_push',
    scope: 'repo',
    target: {
      repoPath: resolve(command.repoPath),
      remote: command.remote ?? 'origin',
      branch: command.branch ?? 'main',
    },
    payload: {
      revision: command.revision ?? 'HEAD',
      transport: command.transport ?? 'relay',
    },
  };
}

export function buildNpmInstallPackageRequest(
  command: NpmInstallPackageInput,
): CompanionRequest {
  const scope = command.scope ?? (command.global ? 'user' : 'project');
  const globalInstall = command.global;

  if (scope === 'project' && globalInstall) {
    throw new Error(
      'npm-install-package cannot combine --scope project with --global; use --scope user --global for approved user installs',
    );
  }

  if (scope === 'user' && !globalInstall) {
    throw new Error(
      'npm-install-package user scope requires --global so request scope and execution policy stay aligned',
    );
  }

  if (globalInstall && command.dev) {
    throw new Error('npm-install-package cannot combine user/global scope with --dev');
  }

  return {
    requestId: command.requestId ?? buildRequestId('npm-install-package'),
    requestedBy: command.sender,
    type: 'npm_install_package',
    scope,
    target: {
      projectPath: resolve(command.projectPath),
      packageManager: 'npm',
    },
    payload: {
      packages: command.packages,
      dev: command.dev,
      global: globalInstall,
    },
  };
}

export function canAutoExecuteRequestType(
  requestType: CompanionRequest['type'],
): boolean {
  return (
    requestType === 'workspace_analysis' ||
    requestType === 'github_research' ||
    requestType === 'repo_relay_push' ||
    requestType === 'npm_install_package'
  );
}

export async function buildStatusSummary(
  layout: Layout,
  requestId: string,
): Promise<StatusSummary> {
  const request = await loadRequestArtifact(layout, requestId);
  const result = await loadResultArtifact(layout, requestId);
  const approvalJob = result.approvalJobId
    ? await loadApprovalJob(layout, result.approvalJobId)
    : null;

  return {
    requestId,
    paths: {
      requestPath: join(layout.requestsDir, `${toSafeSegment(requestId)}.json`),
      resultPath: join(layout.resultsDir, `${toSafeSegment(requestId)}.json`),
      approvalPath: result.approvalJobId
        ? join(layout.approvalsDir, `${toSafeSegment(result.approvalJobId)}.json`)
        : null,
      auditPaths: await listAuditPaths(layout, requestId),
    },
    request,
    result,
    approvalJob,
  };
}

function resolveGithubScope(
  command: GithubResearchInput,
): 'repo' | 'org' | 'user' | 'global' {
  if (command.scope) {
    return command.scope;
  }

  if (command.repo) {
    return 'repo';
  }

  if (command.owner) {
    throw new Error('github-research with --owner requires explicit --scope org or user');
  }

  return 'global';
}

function detectWorkspaceScope(
  config: AppConfig,
  targetPath: string,
): 'notes' | 'workspace' | 'repo' {
  if (isWithinRoot(targetPath, config.notesRoot)) {
    return 'notes';
  }

  if (isWithinRoot(targetPath, config.workspaceRoot)) {
    return 'workspace';
  }

  if (isWithinRoot(targetPath, config.projectRoot)) {
    return 'repo';
  }

  throw new Error(
    `cannot infer workspace scope for ${targetPath}; pass --scope notes|workspace|repo`,
  );
}

function allowedRootForScope(
  config: AppConfig,
  scope: 'notes' | 'workspace' | 'repo',
): string {
  switch (scope) {
    case 'notes':
      return config.notesRoot;
    case 'workspace':
      return config.workspaceRoot;
    case 'repo':
      return config.projectRoot;
  }
}

async function listAuditPaths(layout: Layout, requestId: string): Promise<string[]> {
  const safeRequestId = toSafeSegment(requestId);
  const entries = await readdir(layout.logsDir, { withFileTypes: true });

  return entries
    .filter((entry) => entry.isFile() && entry.name.includes(`-${safeRequestId}-`))
    .map((entry) => join(layout.logsDir, entry.name))
    .sort();
}

function ensureWithinRoot(targetPath: string, rootPath: string, label: string): void {
  if (!isWithinRoot(targetPath, rootPath)) {
    throw new Error(`${label} target ${targetPath} is outside allowed root ${rootPath}`);
  }
}

function isWithinRoot(targetPath: string, rootPath: string): boolean {
  const resolvedTarget = resolve(targetPath);
  const resolvedRoot = resolve(rootPath);
  const relativePath = relative(resolvedRoot, resolvedTarget);

  return (
    relativePath === '' ||
    (!isAbsolute(relativePath) &&
      relativePath !== '..' &&
      !relativePath.startsWith(`..${sep}`))
  );
}

function buildRequestId(prefix: string): string {
  const stamp = new Date().toISOString().replace(/\D/g, '').slice(0, 14);
  const suffix = randomBytes(3).toString('hex');

  return `req-${toSafeSegment(prefix)}-${stamp}-${suffix}`;
}

function toSafeSegment(value: string): string {
  return value.replace(/[^A-Za-z0-9._-]+/g, '-');
}
