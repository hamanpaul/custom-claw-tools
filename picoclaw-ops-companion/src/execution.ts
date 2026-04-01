import { copyFile, readdir, stat, unlink } from 'node:fs/promises';
import { isAbsolute, join, relative, resolve, sep } from 'node:path';
import { execFile, type ExecFileException } from 'node:child_process';
import { promisify } from 'node:util';

import type { AppConfig } from './config.js';
import type { Layout } from './layout.js';
import type { CompanionRequest, IntakeResult } from './models.js';
import {
  appendAuditEvent,
  loadRequestArtifact,
  loadResultArtifact,
  persistResultUpdate,
  writeExecutionArtifact,
} from './artifacts.js';
import { runGithubResearchCopilot } from './copilot.js';

const execFileAsync = promisify(execFile);

export async function executeRequest(
  layout: Layout,
  config: AppConfig,
  requestId: string,
): Promise<{
  requestId: string;
  type: CompanionRequest['type'];
  resultStatus: IntakeResult['status'];
  summary: string;
  artifactPath?: string;
  auditPath: string;
}> {
  const request = await loadRequestArtifact(layout, requestId);
  const result = await loadResultArtifact(layout, requestId);

  if (result.status !== 'ready_for_execution') {
    const auditPath = await appendAuditEvent(layout, requestId, 'execution_not_ready', {
      requestType: request.type,
      resultStatus: result.status,
    });

    throw new Error(
      `request ${requestId} is not ready for execution; current status is ${result.status} (audit: ${auditPath})`,
    );
  }

  switch (request.type) {
    case 'workspace_analysis':
      return executeWorkspaceAnalysis(layout, config, request, result);

    case 'github_research':
      return executeGithubResearch(layout, config, request, result);

    case 'repo_relay_push':
      return executeRepoRelayPush(layout, config, request, result);

    case 'npm_install_package':
      return executeNpmInstallPackage(layout, config, request, result);

  }

  const unreachableRequest: never = request;
  throw new Error(`unreachable request type: ${JSON.stringify(unreachableRequest)}`);
}

async function executeRepoRelayPush(
  layout: Layout,
  config: AppConfig,
  request: Extract<CompanionRequest, { type: 'repo_relay_push' }>,
  result: IntakeResult,
): Promise<{
  requestId: string;
  type: CompanionRequest['type'];
  resultStatus: IntakeResult['status'];
  summary: string;
  artifactPath?: string;
  auditPath: string;
}> {
  try {
    const repoPath = resolve(request.target.repoPath);
    await assertDirectoryExists(repoPath, 'repo path');
    await assertWithinAllowedRoot(repoPath, config.projectRoot, 'repo_relay_push repoPath');
    await assertGitRepository(repoPath);

    await appendAuditEvent(layout, request.requestId, 'execution_repo_relay_push_started', {
      requestType: request.type,
      repoPath,
      remote: request.target.remote,
      branch: request.target.branch,
      revision: request.payload.revision,
      transport: request.payload.transport,
    });

    const remoteUrl = await getGitOutput(repoPath, ['remote', 'get-url', request.target.remote]);

    let artifactPath: string | undefined;
    let summary: string;
    let detail: string;

    if (request.payload.transport === 'relay') {
      await runGit(repoPath, [
        'push',
        request.target.remote,
        `${request.payload.revision}:refs/heads/${request.target.branch}`,
      ]);
      const artifact = {
        executedAt: new Date().toISOString(),
        transport: request.payload.transport,
        repoPath,
        remote: request.target.remote,
        remoteUrl,
        branch: request.target.branch,
        revision: request.payload.revision,
        command: [
          'git',
          'push',
          request.target.remote,
          `${request.payload.revision}:refs/heads/${request.target.branch}`,
        ],
      };
      artifactPath = await writeExecutionArtifact(layout, request.requestId, 'repo-relay-push', artifact);
      summary = `git push completed for ${request.target.remote}/${request.target.branch}`;
      detail = `transport=relay, revision=${request.payload.revision}, remoteUrl=${remoteUrl}`;
    } else {
      const bundleSource = await resolveBundleSourceRef(repoPath, request.payload.revision);
      const bundleTempPath = join(layout.stateDir, `${request.requestId}.${Date.now()}.bundle`);
      try {
        await runGit(repoPath, ['bundle', 'create', bundleTempPath, bundleSource]);
        artifactPath = join(layout.resultsDir, `${toSafeSegment(request.requestId)}.repo-relay-push.bundle`);
        await copyFile(bundleTempPath, artifactPath);
        const bundleHeads = await getGitOutput(repoPath, ['bundle', 'list-heads', bundleTempPath]);
        const metadataPath = await writeExecutionArtifact(layout, request.requestId, 'repo-relay-push', {
          executedAt: new Date().toISOString(),
          transport: request.payload.transport,
          repoPath,
          remote: request.target.remote,
          remoteUrl,
          branch: request.target.branch,
          revision: request.payload.revision,
          bundleSource,
          bundlePath: artifactPath,
          bundleHeads,
        });
        summary = `git bundle prepared for ${request.target.remote}/${request.target.branch}`;
        detail = `transport=bundle, source=${bundleSource}, metadata=${metadataPath}`;
      } finally {
        await unlink(bundleTempPath).catch(() => undefined);
      }
    }

    const succeededResult: IntakeResult = {
      ...result,
      status: 'succeeded',
      summary,
      detail,
      artifactPath,
      updatedAt: new Date().toISOString(),
    };
    const artifacts = await persistResultUpdate(layout, {
      result: succeededResult,
      event: 'execution_succeeded',
      meta: {
        requestType: request.type,
        artifactPath: artifactPath ?? null,
        transport: request.payload.transport,
        remote: request.target.remote,
        branch: request.target.branch,
      },
    });

    return {
      requestId: request.requestId,
      type: request.type,
      resultStatus: succeededResult.status,
      summary: succeededResult.summary,
      artifactPath,
      auditPath: artifacts.auditPath,
    };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    const failedResult: IntakeResult = {
      ...result,
      status: 'failed',
      summary: `repo relay push failed for ${request.target.repoPath}`,
      detail: message,
      updatedAt: new Date().toISOString(),
    };
    await persistResultUpdate(layout, {
      result: failedResult,
      event: 'execution_failed',
      meta: {
        requestType: request.type,
        error: message,
      },
    });
    throw error;
  }
}

async function executeNpmInstallPackage(
  layout: Layout,
  config: AppConfig,
  request: Extract<CompanionRequest, { type: 'npm_install_package' }>,
  result: IntakeResult,
): Promise<{
  requestId: string;
  type: CompanionRequest['type'];
  resultStatus: IntakeResult['status'];
  summary: string;
  artifactPath?: string;
  auditPath: string;
}> {
  try {
    const projectPath = resolve(request.target.projectPath);
    await assertDirectoryExists(projectPath, 'project path');
    const isUserScope = request.scope === 'user';
    const isGlobalInstall = request.payload.global;

    if (isUserScope !== isGlobalInstall) {
      throw new Error('npm_install_package requires scope=user to match payload.global=true');
    }

    if (isGlobalInstall && request.payload.dev) {
      throw new Error('npm_install_package cannot combine global install with dev dependencies');
    }

    if (request.scope === 'project') {
      await assertWithinAllowedRoot(projectPath, config.projectRoot, 'npm_install_package projectPath');
    } else {
      const withinWorkspace = isWithinAllowedRoot(projectPath, config.workspaceRoot);
      const withinRepo = isWithinAllowedRoot(projectPath, config.projectRoot);

      if (!withinWorkspace && !withinRepo) {
        throw new Error(
          `npm_install_package user scope projectPath ${projectPath} is outside allowed roots ${config.workspaceRoot} and ${config.projectRoot}`,
        );
      }
    }

    const packageJsonPath = join(projectPath, 'package.json');

    let packageJsonStat: Awaited<ReturnType<typeof stat>> | null = null;

    if (request.scope === 'project') {
      await assertFileExists(packageJsonPath, 'package.json');
      packageJsonStat = await stat(packageJsonPath);
    }

    const args = ['install'];

    if (request.payload.dev) {
      args.push('--save-dev');
    }

    if (request.payload.global) {
      args.push('--global');
    }

    args.push(...request.payload.packages);

    await appendAuditEvent(layout, request.requestId, 'execution_npm_install_started', {
      requestType: request.type,
      projectPath,
      scope: request.scope,
      global: request.payload.global,
      dev: request.payload.dev,
      packages: request.payload.packages,
    });

    const { stdout, stderr } = await runCommand('npm', args, projectPath);
    const packageLockPath = join(projectPath, 'package-lock.json');
    const packageLockExists = await pathExists(packageLockPath);

    const artifactPath = await writeExecutionArtifact(layout, request.requestId, 'npm-install-package', {
      executedAt: new Date().toISOString(),
      cwd: projectPath,
      scope: request.scope,
      command: ['npm', ...args],
      packages: request.payload.packages,
      dev: request.payload.dev,
      global: request.payload.global,
      packageJsonPath: request.scope === 'project' ? packageJsonPath : null,
      packageJsonMtimeMs: request.scope === 'project' ? packageJsonStat?.mtimeMs ?? null : null,
      packageLockPath: request.scope === 'project' && packageLockExists ? packageLockPath : null,
      stdout,
      stderr,
    });

    const succeededResult: IntakeResult = {
      ...result,
      status: 'succeeded',
      summary: `npm install completed for ${request.payload.packages.join(', ')}`,
      detail: `scope=${request.scope}, global=${request.payload.global}, dev=${request.payload.dev}`,
      artifactPath,
      updatedAt: new Date().toISOString(),
    };
    const artifacts = await persistResultUpdate(layout, {
      result: succeededResult,
      event: 'execution_succeeded',
      meta: {
        requestType: request.type,
        artifactPath,
        scope: request.scope,
        global: request.payload.global,
        packages: request.payload.packages,
      },
    });

    return {
      requestId: request.requestId,
      type: request.type,
      resultStatus: succeededResult.status,
      summary: succeededResult.summary,
      artifactPath,
      auditPath: artifacts.auditPath,
    };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    const failedResult: IntakeResult = {
      ...result,
      status: 'failed',
      summary: `npm install failed for ${request.target.projectPath}`,
      detail: message,
      updatedAt: new Date().toISOString(),
    };
    await persistResultUpdate(layout, {
      result: failedResult,
      event: 'execution_failed',
      meta: {
        requestType: request.type,
        error: message,
      },
    });
    throw error;
  }
}

async function executeGithubResearch(
  layout: Layout,
  config: AppConfig,
  request: Extract<CompanionRequest, { type: 'github_research' }>,
  result: IntakeResult,
): Promise<{
  requestId: string;
  type: CompanionRequest['type'];
  resultStatus: IntakeResult['status'];
  summary: string;
  artifactPath?: string;
  auditPath: string;
}> {
  try {
    await appendAuditEvent(layout, request.requestId, 'execution_copilot_session_started', {
      requestType: request.type,
      scope: request.scope,
      mode: request.payload.mode,
      limit: request.payload.limit,
      target: request.target,
    });

    const artifact = await runGithubResearchCopilot(config, request);
    const artifactPath = await writeExecutionArtifact(
      layout,
      request.requestId,
      'github-research',
      artifact,
    );
    const succeededResult: IntakeResult = {
      ...result,
      status: 'succeeded',
      summary: `github research completed for ${describeGitHubResearchTarget(request)}`,
      detail: `mode=${request.payload.mode}, totalCount=${artifact.search.totalCount}, toolCalls=${artifact.toolInvocations.length}`,
      artifactPath,
      updatedAt: new Date().toISOString(),
    };
    const artifacts = await persistResultUpdate(layout, {
      result: succeededResult,
      event: 'execution_succeeded',
      meta: {
        requestType: request.type,
        artifactPath,
        sessionId: artifact.sessionId,
        toolCalls: artifact.toolInvocations.length,
      },
    });

    return {
      requestId: request.requestId,
      type: request.type,
      resultStatus: succeededResult.status,
      summary: succeededResult.summary,
      artifactPath,
      auditPath: artifacts.auditPath,
    };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    const failedResult: IntakeResult = {
      ...result,
      status: 'failed',
      summary: `github research failed for ${describeGitHubResearchTarget(request)}`,
      detail: message,
      updatedAt: new Date().toISOString(),
    };
    await persistResultUpdate(layout, {
      result: failedResult,
      event: 'execution_failed',
      meta: {
        requestType: request.type,
        error: message,
      },
    });
    throw error;
  }
}

async function executeWorkspaceAnalysis(
  layout: Layout,
  config: AppConfig,
  request: Extract<CompanionRequest, { type: 'workspace_analysis' }>,
  result: IntakeResult,
): Promise<{
  requestId: string;
  type: CompanionRequest['type'];
  resultStatus: IntakeResult['status'];
  summary: string;
  artifactPath?: string;
  auditPath: string;
}> {
  try {
    const allowedRoot = resolveAllowedRoot(config, request.scope);
    const targetPath = resolve(request.target.path);
    const relativePath = relative(allowedRoot, targetPath);

    if (
      isAbsolute(relativePath) ||
      relativePath === '..' ||
      relativePath.startsWith(`..${sep}`)
    ) {
      throw new Error(`target path ${targetPath} is outside allowed root ${allowedRoot}`);
    }

    const summary = await collectWorkspaceSummary(targetPath, 2, 64);
    const artifactPath = await writeExecutionArtifact(
      layout,
      request.requestId,
      'workspace-analysis',
      {
        ...summary,
        prompt: request.payload.prompt,
        allowedRoot,
      },
    );
    const succeededResult: IntakeResult = {
      ...result,
      status: 'succeeded',
      summary: `workspace analysis completed for ${targetPath}`,
      detail: `directories=${summary.totals.directories}, files=${summary.totals.files}, sampledEntries=${summary.entries.length}`,
      artifactPath,
      updatedAt: new Date().toISOString(),
    };
    const artifacts = await persistResultUpdate(layout, {
      result: succeededResult,
      event: 'execution_succeeded',
      meta: {
        requestType: request.type,
        artifactPath,
      },
    });

    return {
      requestId: request.requestId,
      type: request.type,
      resultStatus: succeededResult.status,
      summary: succeededResult.summary,
      artifactPath,
      auditPath: artifacts.auditPath,
    };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    const failedResult: IntakeResult = {
      ...result,
      status: 'failed',
      summary: `workspace analysis failed for ${request.target.path}`,
      detail: message,
      updatedAt: new Date().toISOString(),
    };
    await persistResultUpdate(layout, {
      result: failedResult,
      event: 'execution_failed',
      meta: {
        requestType: request.type,
        error: message,
      },
    });
    throw error;
  }
}

async function collectWorkspaceSummary(
  rootPath: string,
  maxDepth: number,
  maxEntries: number,
): Promise<{
  rootPath: string;
  generatedAt: string;
  totals: {
    directories: number;
    files: number;
  };
  entries: Array<{
    path: string;
    kind: 'directory' | 'file';
    depth: number;
  }>;
}> {
  const entries: Array<{
    path: string;
    kind: 'directory' | 'file';
    depth: number;
  }> = [];
  let directories = 0;
  let files = 0;

  async function walk(currentPath: string, depth: number): Promise<void> {
    if (depth > maxDepth || entries.length >= maxEntries) {
      return;
    }

    const children = await readdir(currentPath, { withFileTypes: true });

    children.sort((left, right) => left.name.localeCompare(right.name));

    for (const child of children) {
      const childPath = join(currentPath, child.name);
      const childRelativePath = relative(rootPath, childPath);

      if (child.isDirectory()) {
        directories += 1;
        entries.push({
          path: childRelativePath,
          kind: 'directory',
          depth,
        });

        if (entries.length >= maxEntries) {
          return;
        }

        await walk(childPath, depth + 1);
      } else {
        files += 1;
        entries.push({
          path: childRelativePath,
          kind: 'file',
          depth,
        });
      }

      if (entries.length >= maxEntries) {
        return;
      }
    }
  }

  await walk(rootPath, 0);

  return {
    rootPath,
    generatedAt: new Date().toISOString(),
    totals: {
      directories,
      files,
    },
    entries,
  };
}

function resolveAllowedRoot(
  config: AppConfig,
  scope: Extract<CompanionRequest, { type: 'workspace_analysis' }>['scope'],
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

function describeGitHubResearchTarget(
  request: Extract<CompanionRequest, { type: 'github_research' }>,
): string {
  return request.target.repo ?? request.target.owner ?? 'global-github';
}

async function runGit(repoPath: string, args: string[]): Promise<{
  stdout: string;
  stderr: string;
}> {
  return runCommand('git', args, repoPath);
}

async function getGitOutput(repoPath: string, args: string[]): Promise<string> {
  const { stdout } = await runGit(repoPath, args);
  return stdout.trim();
}

async function runCommand(
  command: string,
  args: string[],
  cwd: string,
): Promise<{
  stdout: string;
  stderr: string;
}> {
  try {
    const { stdout, stderr } = await execFileAsync(command, args, {
      cwd,
      maxBuffer: 8 * 1024 * 1024,
      env: process.env,
    });

    return {
      stdout: stdout.trim(),
      stderr: stderr.trim(),
    };
  } catch (error) {
    if (
      error instanceof Error &&
      'stdout' in error &&
      'stderr' in error
    ) {
      const execError = error as ExecFileException & {
        stdout?: string;
        stderr?: string;
      };
      const stdout = typeof execError.stdout === 'string'
        ? execError.stdout.trim()
        : '';
      const stderr = typeof execError.stderr === 'string'
        ? execError.stderr.trim()
        : '';
      const exitCode = typeof execError.code === 'number'
        ? execError.code
        : null;
      const details = [error.message];

      if (exitCode !== null) {
        details.push(`exitCode=${exitCode}`);
      }

      if (stdout.length > 0) {
        details.push(`stdout=${stdout}`);
      }

      if (stderr.length > 0) {
        details.push(`stderr=${stderr}`);
      }

      throw new Error(details.join('; '));
    }

    throw error;
  }
}

async function assertGitRepository(repoPath: string): Promise<void> {
  const output = await getGitOutput(repoPath, ['rev-parse', '--is-inside-work-tree']);

  if (output !== 'true') {
    throw new Error(`${repoPath} is not a git work tree`);
  }
}

async function assertDirectoryExists(path: string, label: string): Promise<void> {
  const pathStat = await stat(path).catch((error: unknown) => {
    throw new Error(`${label} does not exist: ${path}`);
  });

  if (!pathStat.isDirectory()) {
    throw new Error(`${label} is not a directory: ${path}`);
  }
}

async function assertFileExists(path: string, label: string): Promise<void> {
  const pathStat = await stat(path).catch((error: unknown) => {
    throw new Error(`${label} does not exist: ${path}`);
  });

  if (!pathStat.isFile()) {
    throw new Error(`${label} is not a file: ${path}`);
  }
}

async function assertWithinAllowedRoot(
  targetPath: string,
  allowedRoot: string,
  label: string,
): Promise<void> {
  if (!isWithinAllowedRoot(targetPath, allowedRoot)) {
    throw new Error(`${label} ${targetPath} is outside allowed root ${allowedRoot}`);
  }
}

async function resolveBundleSourceRef(repoPath: string, revision: string): Promise<string> {
  if (revision === 'HEAD') {
    return `refs/heads/${await currentBranchName(repoPath)}`;
  }

  const branchRef = `refs/heads/${revision}`;

  if (await gitRefExists(repoPath, branchRef)) {
    return branchRef;
  }

  const tagRef = `refs/tags/${revision}`;

  if (await gitRefExists(repoPath, tagRef)) {
    return tagRef;
  }

  if (await gitRefExists(repoPath, revision)) {
    return revision;
  }

  throw new Error(
    `bundle transport could not resolve revision ${revision} to a named ref`,
  );
}

async function currentBranchName(repoPath: string): Promise<string> {
  const output = await getGitOutput(repoPath, ['branch', '--show-current']);

  if (!output) {
    throw new Error(`unable to determine current branch for ${repoPath}`);
  }

  return output;
}

async function pathExists(path: string): Promise<boolean> {
  try {
    await stat(path);
    return true;
  } catch {
    return false;
  }
}

function toSafeSegment(value: string): string {
  return value.replace(/[^A-Za-z0-9._-]+/g, '-');
}

function isWithinAllowedRoot(targetPath: string, allowedRoot: string): boolean {
  const relativePath = relative(resolve(allowedRoot), resolve(targetPath));

  return (
    relativePath === '' ||
    (!isAbsolute(relativePath) &&
      relativePath !== '..' &&
      !relativePath.startsWith(`..${sep}`))
  );
}

async function gitRefExists(repoPath: string, ref: string): Promise<boolean> {
  try {
    await runGit(repoPath, ['show-ref', '--verify', ref]);
    return true;
  } catch {
    return false;
  }
}
