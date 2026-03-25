import { readdir } from 'node:fs/promises';
import { isAbsolute, join, relative, resolve, sep } from 'node:path';

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

    default: {
      const failedResult: IntakeResult = {
        ...result,
        status: 'failed',
        summary: `execution wrapper for ${request.type} is not implemented yet`,
        detail:
          'Only workspace_analysis and github_research are executable in the current MVP slice.',
        updatedAt: new Date().toISOString(),
      };
      const artifacts = await persistResultUpdate(layout, {
        result: failedResult,
        event: 'execution_not_implemented',
        meta: {
          requestType: request.type,
        },
      });

      return {
        requestId,
        type: request.type,
        resultStatus: failedResult.status,
        summary: failedResult.summary,
        auditPath: artifacts.auditPath,
      };
    }
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
