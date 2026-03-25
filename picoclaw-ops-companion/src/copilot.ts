import { execFile } from 'node:child_process';
import { promisify } from 'node:util';

import { CopilotClient, defineTool } from '@github/copilot-sdk';
import type {
  CopilotClientOptions,
  PermissionHandler,
  PermissionRequestResult,
} from '@github/copilot-sdk';
import { z } from 'zod';

import type { AppConfig } from './config.js';
import type { CompanionRequest } from './models.js';

const execFileAsync = promisify(execFile);
const SEARCH_TOOL_NAME = 'perform_structured_github_search';
const TOOL_TIMEOUT_MS = 30_000;
const SESSION_TIMEOUT_MS = 120_000;

type GitHubResearchRequest = Extract<CompanionRequest, { type: 'github_research' }>;

type GitHubSearchItem = {
  kind: 'issue' | 'pull_request' | 'code' | 'repository';
  title: string;
  url: string;
  repository?: string;
  number?: number;
  state?: string;
  updatedAt?: string;
  path?: string;
  description?: string;
  stars?: number;
  snippet?: string;
};

type GitHubSearchResult = {
  endpoint: 'search/issues' | 'search/code' | 'search/repositories';
  mode: GitHubResearchRequest['payload']['mode'];
  query: string;
  limit: number;
  executedAt: string;
  totalCount: number;
  items: GitHubSearchItem[];
};

type GitHubSearchInvocation = {
  toolName: string;
  executedAt: string;
  itemCount: number;
  totalCount: number;
  reason?: string;
};

export type GitHubResearchExecutionArtifact = {
  requestId: string;
  sessionId: string;
  model: string | null;
  workingDirectory: string;
  prompt: string;
  systemMessage: string;
  availableTools: string[];
  excludedTools: string[];
  search: GitHubSearchResult;
  toolInvocations: GitHubSearchInvocation[];
  assistantResponse: string;
};

const searchToolParameters = z.object({
  reason: z
    .string()
    .min(1)
    .optional()
    .describe('Why the agent wants to re-run the pre-approved GitHub search'),
});

export async function runGithubResearchCopilot(
  config: AppConfig,
  request: GitHubResearchRequest,
): Promise<GitHubResearchExecutionArtifact> {
  const client = new CopilotClient(buildClientOptions(config));
  const policy = buildGitHubResearchPolicy(config, request);
  const toolInvocations: GitHubSearchInvocation[] = [];
  let session:
    | Awaited<ReturnType<CopilotClient['createSession']>>
    | undefined;
  let raisedError: unknown;

  const searchTool = defineTool(SEARCH_TOOL_NAME, {
    description:
      'Run the pre-approved GitHub search for the current structured github_research request and return normalized read-only results.',
    parameters: searchToolParameters,
    skipPermission: true,
    handler: async ({ reason }) => {
      const search = await executeGitHubSearch(config, request);
      toolInvocations.push({
        toolName: SEARCH_TOOL_NAME,
        executedAt: search.executedAt,
        itemCount: search.items.length,
        totalCount: search.totalCount,
        reason,
      });

      return search;
    },
  });

  try {
    await client.start();
    session = await client.createSession({
      clientName: 'picoclaw-ops-companion',
      ...(config.copilotModel ? { model: config.copilotModel } : {}),
      workingDirectory: policy.workingDirectory,
      tools: [searchTool],
      availableTools: policy.availableTools,
      excludedTools: policy.excludedTools,
      streaming: false,
      infiniteSessions: { enabled: false },
      systemMessage: {
        content: policy.systemMessage,
      },
      onPermissionRequest: createPermissionHandler(),
    });

    const response = await session.sendAndWait(
      {
        prompt: policy.prompt,
      },
      SESSION_TIMEOUT_MS,
    );
    const assistantResponse = response?.data.content.trim() ?? '';

    if (assistantResponse.length === 0) {
      throw new Error('Copilot SDK returned no assistant response for github_research');
    }

    const search = await ensureSearchInvocation(config, request, toolInvocations);

    return {
      requestId: request.requestId,
      sessionId: session.sessionId,
      model: config.copilotModel ?? null,
      workingDirectory: policy.workingDirectory,
      prompt: policy.prompt,
      systemMessage: policy.systemMessage,
      availableTools: policy.availableTools,
      excludedTools: policy.excludedTools,
      search,
      toolInvocations,
      assistantResponse,
    };
  } catch (error) {
    raisedError = error;
    throw error;
  } finally {
    const cleanupErrors = await cleanupCopilotResources(client, session);

    if (cleanupErrors.length > 0 && raisedError instanceof Error) {
      raisedError.message = `${raisedError.message}; cleanup errors: ${cleanupErrors.join('; ')}`;
    }

    if (cleanupErrors.length > 0 && raisedError === undefined) {
      throw new Error(`Copilot SDK cleanup failed: ${cleanupErrors.join('; ')}`);
    }
  }
}

function buildClientOptions(config: AppConfig): CopilotClientOptions {
  const options: CopilotClientOptions = {
    cwd: config.projectRoot,
    autoStart: true,
    logLevel: 'error',
  };

  if (config.copilotCliUrl) {
    options.cliUrl = config.copilotCliUrl;
    return options;
  }

  if (config.copilotCliPath) {
    options.cliPath = config.copilotCliPath;
  }

  return options;
}

function buildGitHubResearchPolicy(
  config: AppConfig,
  request: GitHubResearchRequest,
): {
  workingDirectory: string;
  systemMessage: string;
  prompt: string;
  availableTools: string[];
  excludedTools: string[];
} {
  const targetLabel =
    request.target.repo ??
    request.target.owner ??
    'global-github';

  return {
    workingDirectory: config.projectRoot,
    systemMessage: [
      'You are PicoClaw Ops Companion running a structured github_research request.',
      'Operate in read-only mode.',
      `Only use the custom tool "${SEARCH_TOOL_NAME}" to gather evidence.`,
      'Do not ask for extra permissions, do not edit files, and do not invoke shell or URL tools.',
      'Base every conclusion on the tool output.',
    ].join('\n'),
    prompt: [
      'Execute this structured request:',
      `- requestId: ${request.requestId}`,
      `- scope: ${request.scope}`,
      `- target: ${targetLabel}`,
      `- mode: ${request.payload.mode}`,
      `- limit: ${request.payload.limit}`,
      `- query: ${request.payload.query}`,
      '',
      `Use "${SEARCH_TOOL_NAME}" at least once, then produce a concise report with these sections:`,
      'Summary:',
      'Findings:',
      'References:',
      'Next steps:',
    ].join('\n'),
    availableTools: [SEARCH_TOOL_NAME],
    excludedTools: [],
  };
}

function createPermissionHandler(): PermissionHandler {
  return (request): PermissionRequestResult => {
    if (request.kind === 'custom-tool' && request.toolName === SEARCH_TOOL_NAME) {
      return { kind: 'approved' };
    }

    return {
      kind: 'denied-by-rules',
      rules: [
        {
          toolName:
            typeof request.toolName === 'string' ? request.toolName : 'unknown-tool',
          reason: 'picoclaw-ops-companion only allows the structured GitHub search tool',
        },
      ],
    };
  };
}

async function ensureSearchInvocation(
  config: AppConfig,
  request: GitHubResearchRequest,
  toolInvocations: GitHubSearchInvocation[],
): Promise<GitHubSearchResult> {
  if (toolInvocations.length > 0) {
    return executeGitHubSearch(config, request);
  }

  throw new Error(
    `Copilot session completed without calling the required ${SEARCH_TOOL_NAME} tool`,
  );
}

async function executeGitHubSearch(
  config: AppConfig,
  request: GitHubResearchRequest,
): Promise<GitHubSearchResult> {
  const searchSpec = buildGitHubSearchSpec(request);
  const args = [
    'api',
    '--method',
    'GET',
    searchSpec.endpoint,
    '-f',
    `q=${searchSpec.query}`,
    '-F',
    `per_page=${searchSpec.limit}`,
  ];
  const { stdout } = await execFileAsync('gh', args, {
    cwd: config.projectRoot,
    env: {
      ...process.env,
      GH_PAGER: 'cat',
      PAGER: 'cat',
    },
    timeout: TOOL_TIMEOUT_MS,
    maxBuffer: 4 * 1024 * 1024,
  });
  const payload = JSON.parse(stdout);

  return normalizeGitHubSearchResult(searchSpec, payload);
}

function buildGitHubSearchSpec(
  request: GitHubResearchRequest,
): {
  endpoint: GitHubSearchResult['endpoint'];
  mode: GitHubResearchRequest['payload']['mode'];
  query: string;
  limit: number;
} {
  const qualifiers = buildSearchQualifiers(request);

  switch (request.payload.mode) {
    case 'issues':
      qualifiers.push('is:issue');
      return {
        endpoint: 'search/issues',
        mode: request.payload.mode,
        query: [request.payload.query, ...qualifiers].join(' ').trim(),
        limit: request.payload.limit,
      };

    case 'pull_requests':
      qualifiers.push('is:pr');
      return {
        endpoint: 'search/issues',
        mode: request.payload.mode,
        query: [request.payload.query, ...qualifiers].join(' ').trim(),
        limit: request.payload.limit,
      };

    case 'generic':
      return {
        endpoint: 'search/issues',
        mode: request.payload.mode,
        query: [request.payload.query, ...qualifiers].join(' ').trim(),
        limit: request.payload.limit,
      };

    case 'code':
      return {
        endpoint: 'search/code',
        mode: request.payload.mode,
        query: [request.payload.query, ...qualifiers].join(' ').trim(),
        limit: request.payload.limit,
      };

    case 'repositories':
      return {
        endpoint: 'search/repositories',
        mode: request.payload.mode,
        query: [request.payload.query, ...buildRepositoryQualifiers(request)].join(' ').trim(),
        limit: request.payload.limit,
      };
  }
}

function buildSearchQualifiers(request: GitHubResearchRequest): string[] {
  switch (request.scope) {
    case 'repo':
      return request.target.repo ? [`repo:${request.target.repo}`] : [];

    case 'org':
      return request.target.owner ? [`org:${request.target.owner}`] : [];

    case 'user':
      return request.target.owner ? [`user:${request.target.owner}`] : [];

    case 'global':
      return [];
  }
}

function buildRepositoryQualifiers(request: GitHubResearchRequest): string[] {
  if (request.scope === 'repo' && request.target.repo) {
    const [owner, repoName] = request.target.repo.split('/', 2);

    return [owner ? `user:${owner}` : '', repoName ?? ''].filter(Boolean);
  }

  return buildSearchQualifiers(request);
}

function normalizeGitHubSearchResult(
  searchSpec: {
    endpoint: GitHubSearchResult['endpoint'];
    mode: GitHubResearchRequest['payload']['mode'];
    query: string;
    limit: number;
  },
  payload: unknown,
): GitHubSearchResult {
  const executedAt = new Date().toISOString();

  if (searchSpec.endpoint === 'search/issues') {
    const result = issueSearchResponseSchema.parse(payload);

    return {
      endpoint: searchSpec.endpoint,
      mode: searchSpec.mode,
      query: searchSpec.query,
      limit: searchSpec.limit,
      executedAt,
      totalCount: result.total_count,
      items: result.items.map((item) => ({
        kind: item.pull_request ? 'pull_request' : 'issue',
        title: item.title,
        url: item.html_url,
        repository: extractRepositoryName(item.repository_url),
        number: item.number,
        state: item.state,
        updatedAt: item.updated_at,
        snippet: normalizeSnippet(item.body),
      })),
    };
  }

  if (searchSpec.endpoint === 'search/code') {
    const result = codeSearchResponseSchema.parse(payload);

    return {
      endpoint: searchSpec.endpoint,
      mode: searchSpec.mode,
      query: searchSpec.query,
      limit: searchSpec.limit,
      executedAt,
      totalCount: result.total_count,
      items: result.items.map((item) => ({
        kind: 'code',
        title: `${item.repository.full_name}:${item.path}`,
        url: item.html_url,
        repository: item.repository.full_name,
        path: item.path,
      })),
    };
  }

  const result = repositorySearchResponseSchema.parse(payload);

  return {
    endpoint: searchSpec.endpoint,
    mode: searchSpec.mode,
    query: searchSpec.query,
    limit: searchSpec.limit,
    executedAt,
    totalCount: result.total_count,
    items: result.items.map((item) => ({
      kind: 'repository',
      title: item.full_name,
      url: item.html_url,
      repository: item.full_name,
      description: item.description ?? undefined,
      updatedAt: item.updated_at,
      stars: item.stargazers_count,
    })),
  };
}

async function cleanupCopilotResources(
  client: CopilotClient,
  session?: Awaited<ReturnType<CopilotClient['createSession']>>,
): Promise<string[]> {
  const cleanupErrors: string[] = [];

  if (session) {
    try {
      await session.disconnect();
    } catch (error) {
      cleanupErrors.push(extractErrorMessage(error));
    }
  }

  try {
    const stopErrors = await client.stop();
    cleanupErrors.push(
      ...stopErrors.map((error) => extractErrorMessage(error)),
    );
  } catch (error) {
    cleanupErrors.push(extractErrorMessage(error));
  }

  return cleanupErrors;
}

function extractRepositoryName(repositoryUrl?: string): string | undefined {
  if (!repositoryUrl) {
    return undefined;
  }

  try {
    const url = new URL(repositoryUrl);
    const segments = url.pathname.split('/').filter(Boolean);

    if (segments.length < 2) {
      return undefined;
    }

    return `${segments[0]}/${segments[1]}`;
  } catch {
    return undefined;
  }
}

function normalizeSnippet(value: string | null | undefined): string | undefined {
  if (!value) {
    return undefined;
  }

  return value.replace(/\s+/g, ' ').trim().slice(0, 240);
}

function extractErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

const issueSearchResponseSchema = z.object({
  total_count: z.number().int().nonnegative(),
  items: z.array(
    z.object({
      html_url: z.string().url(),
      title: z.string().min(1),
      number: z.number().int().positive(),
      state: z.string().min(1).optional(),
      updated_at: z.string().optional(),
      repository_url: z.string().url().optional(),
      body: z.string().nullable().optional(),
      pull_request: z.record(z.string(), z.unknown()).optional(),
    }),
  ),
});

const codeSearchResponseSchema = z.object({
  total_count: z.number().int().nonnegative(),
  items: z.array(
    z.object({
      html_url: z.string().url(),
      path: z.string().min(1),
      repository: z.object({
        full_name: z.string().min(1),
      }),
    }),
  ),
});

const repositorySearchResponseSchema = z.object({
  total_count: z.number().int().nonnegative(),
  items: z.array(
    z.object({
      full_name: z.string().min(1),
      html_url: z.string().url(),
      description: z.string().nullable().optional(),
      updated_at: z.string().optional(),
      stargazers_count: z.number().int().nonnegative(),
    }),
  ),
});
