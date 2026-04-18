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
type GitHubResearchSearchPlan = {
  id: string;
  label: string;
  query: string;
  scope: 'repo' | 'org' | 'user' | 'global';
  repo?: string;
  owner?: string;
  mode: 'generic' | 'issues' | 'pull_requests' | 'code' | 'repositories';
  limit: number;
};

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
  searchId: string;
  searchLabel: string;
  scope: GitHubResearchSearchPlan['scope'];
  targetLabel: string;
  endpoint: 'search/issues' | 'search/code' | 'search/repositories';
  mode: GitHubResearchSearchPlan['mode'];
  query: string;
  limit: number;
  executedAt: string;
  totalCount: number;
  items: GitHubSearchItem[];
};

type GitHubSearchInvocation = {
  toolName: string;
  executedAt: string;
  searchCount: number;
  searchIds: string[];
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
  searches: GitHubSearchResult[];
  toolInvocations: GitHubSearchInvocation[];
  assistantResponse: string;
};

const searchToolParameters = z.object({
  reason: z
    .string()
    .min(1)
    .optional()
    .describe('Why the agent wants to re-run the pre-approved GitHub search'),
  searchId: z
    .string()
    .min(1)
    .optional()
    .describe('Optional planned search ID when the request defines multiple searches'),
});

export async function runGithubResearchCopilot(
  config: AppConfig,
  request: GitHubResearchRequest,
): Promise<GitHubResearchExecutionArtifact> {
  const client = new CopilotClient(buildClientOptions(config));
  const policy = buildGitHubResearchPolicy(config, request);
  const searchPlan = buildGitHubResearchSearchPlan(request);
  const toolInvocations: GitHubSearchInvocation[] = [];
  const cachedSearchResults = new Map<string, GitHubSearchResult>();
  let session:
    | Awaited<ReturnType<CopilotClient['createSession']>>
    | undefined;
  let raisedError: unknown;

  const searchTool = defineTool(SEARCH_TOOL_NAME, {
    description:
      'Run the pre-approved GitHub search for the current structured github_research request and return normalized read-only results.',
    parameters: searchToolParameters,
    skipPermission: true,
    handler: async ({ reason, searchId }) => {
      const searchBatch = await executeGitHubSearchBatch(
        config,
        searchPlan,
        cachedSearchResults,
        searchId,
      );
      toolInvocations.push({
        toolName: SEARCH_TOOL_NAME,
        executedAt: searchBatch.executedAt,
        searchCount: searchBatch.searches.length,
        searchIds: searchBatch.searches.map((search) => search.searchId),
        itemCount: searchBatch.searches.reduce(
          (count, search) => count + search.items.length,
          0,
        ),
        totalCount: searchBatch.searches.reduce(
          (count, search) => count + search.totalCount,
          0,
        ),
        reason,
      });

      return searchBatch;
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

    const searches = ensureSearchInvocation(searchPlan, cachedSearchResults, toolInvocations);
    const primarySearch = searches[0];
    if (!primarySearch) {
      throw new Error('github_research completed without producing a cached search result');
    }

    return {
      requestId: request.requestId,
      sessionId: session.sessionId,
      model: config.copilotModel ?? null,
      workingDirectory: policy.workingDirectory,
      prompt: policy.prompt,
      systemMessage: policy.systemMessage,
      availableTools: policy.availableTools,
      excludedTools: policy.excludedTools,
      search: primarySearch,
      searches,
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
  const searchPlan = buildGitHubResearchSearchPlan(request);
  const targetLabel = describeSearchPlan(searchPlan);
  const searchPlanLines =
    searchPlan.length > 1
      ? [
          '',
          'Planned searches for this single request:',
          ...searchPlan.map(
            (search, index) =>
              `${index + 1}. id=${search.id}; label=${search.label}; scope=${search.scope}; target=${describeSearchTarget(search)}; mode=${search.mode}; limit=${search.limit}; query=${search.query}`,
          ),
          '',
          `Call "${SEARCH_TOOL_NAME}" once without searchId to execute every pending planned search in one batch before writing the final report.`,
          'If you must re-run a specific planned search, call the tool again with that searchId.',
          'Return one consolidated report across the whole plan, not one separate report per search.',
        ]
      : [];

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
      ...searchPlanLines,
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

function ensureSearchInvocation(
  searchPlan: GitHubResearchSearchPlan[],
  cachedSearchResults: Map<string, GitHubSearchResult>,
  toolInvocations: GitHubSearchInvocation[],
) {
  if (toolInvocations.length > 0) {
    return searchPlan
      .map((search) => cachedSearchResults.get(search.id))
      .filter((search): search is GitHubSearchResult => Boolean(search));
  }

  throw new Error(
    `Copilot session completed without calling the required ${SEARCH_TOOL_NAME} tool`,
  );
}

async function executeGitHubSearchBatch(
  config: AppConfig,
  searchPlan: GitHubResearchSearchPlan[],
  cachedSearchResults: Map<string, GitHubSearchResult>,
  searchId?: string,
): Promise<{
  executedAt: string;
  searches: GitHubSearchResult[];
}> {
  const selectedSearches = selectGitHubResearchSearches(
    searchPlan,
    cachedSearchResults,
    searchId,
  );
  const searches = await Promise.all(
    selectedSearches.map(async (search) => {
      const cached = cachedSearchResults.get(search.id);
      if (cached) {
        return cached;
      }

      const result = await executeGitHubSearch(config, search);
      cachedSearchResults.set(search.id, result);
      return result;
    }),
  );

  return {
    executedAt: new Date().toISOString(),
    searches,
  };
}

async function executeGitHubSearch(
  config: AppConfig,
  search: GitHubResearchSearchPlan,
): Promise<GitHubSearchResult> {
  const searchSpec = buildGitHubSearchSpec(search);
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

  return normalizeGitHubSearchResult(search, searchSpec, payload);
}

function buildGitHubSearchSpec(
  search: GitHubResearchSearchPlan,
): {
  endpoint: GitHubSearchResult['endpoint'];
  mode: GitHubResearchSearchPlan['mode'];
  query: string;
  limit: number;
} {
  const qualifiers = buildSearchQualifiers(search);

  switch (search.mode) {
    case 'issues':
      qualifiers.push('is:issue');
      return {
        endpoint: 'search/issues',
        mode: search.mode,
        query: [search.query, ...qualifiers].join(' ').trim(),
        limit: search.limit,
      };

    case 'pull_requests':
      qualifiers.push('is:pr');
      return {
        endpoint: 'search/issues',
        mode: search.mode,
        query: [search.query, ...qualifiers].join(' ').trim(),
        limit: search.limit,
      };

    case 'generic':
      return {
        endpoint: 'search/issues',
        mode: search.mode,
        query: [search.query, ...qualifiers].join(' ').trim(),
        limit: search.limit,
      };

    case 'code':
      return {
        endpoint: 'search/code',
        mode: search.mode,
        query: [search.query, ...qualifiers].join(' ').trim(),
        limit: search.limit,
      };

    case 'repositories':
      return {
        endpoint: 'search/repositories',
        mode: search.mode,
        query: [search.query, ...buildRepositoryQualifiers(search)].join(' ').trim(),
        limit: search.limit,
      };
  }
}

function buildSearchQualifiers(search: GitHubResearchSearchPlan): string[] {
  switch (search.scope) {
    case 'repo':
      return search.repo ? [`repo:${search.repo}`] : [];

    case 'org':
      return search.owner ? [`org:${search.owner}`] : [];

    case 'user':
      return search.owner ? [`user:${search.owner}`] : [];

    case 'global':
      return [];
  }
}

function buildRepositoryQualifiers(search: GitHubResearchSearchPlan): string[] {
  if (search.scope === 'repo' && search.repo) {
    const [owner, repoName] = search.repo.split('/', 2);

    return [owner ? `user:${owner}` : '', repoName ?? ''].filter(Boolean);
  }

  return buildSearchQualifiers(search);
}

function normalizeGitHubSearchResult(
  search: GitHubResearchSearchPlan,
  searchSpec: {
    endpoint: GitHubSearchResult['endpoint'];
    mode: GitHubResearchSearchPlan['mode'];
    query: string;
    limit: number;
  },
  payload: unknown,
): GitHubSearchResult {
  const executedAt = new Date().toISOString();

  if (searchSpec.endpoint === 'search/issues') {
    const result = issueSearchResponseSchema.parse(payload);

    return {
      searchId: search.id,
      searchLabel: search.label,
      scope: search.scope,
      targetLabel: describeSearchTarget(search),
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
      searchId: search.id,
      searchLabel: search.label,
      scope: search.scope,
      targetLabel: describeSearchTarget(search),
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
    searchId: search.id,
    searchLabel: search.label,
    scope: search.scope,
    targetLabel: describeSearchTarget(search),
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

function buildGitHubResearchSearchPlan(
  request: GitHubResearchRequest,
): GitHubResearchSearchPlan[] {
  const plannedSearches = request.payload.searches?.length
    ? request.payload.searches
    : [
        {
          query: request.payload.query ?? '',
          scope: request.scope === 'mixed' ? 'global' : request.scope,
          repo: request.target.repo,
          owner: request.target.owner,
          mode: request.payload.mode,
          limit: request.payload.limit,
        },
      ];

  return plannedSearches.map((search, index) => {
    const scope =
      search.scope ??
      (search.repo ? 'repo' : undefined) ??
      (search.owner ? request.scope === 'user' ? 'user' : 'org' : undefined) ??
      (request.scope === 'mixed' ? 'global' : request.scope);

    if (!scope) {
      throw new Error('github_research search plan contains an unresolved scope');
    }

    return {
      id: `search-${index + 1}`,
      label: search.label?.trim() || `search-${index + 1}`,
      query: search.query,
      scope,
      ...(search.repo ?? request.target.repo ? { repo: search.repo ?? request.target.repo } : {}),
      ...(search.owner ?? request.target.owner ? { owner: search.owner ?? request.target.owner } : {}),
      mode: search.mode ?? request.payload.mode,
      limit: search.limit ?? request.payload.limit,
    };
  });
}

function selectGitHubResearchSearches(
  searchPlan: GitHubResearchSearchPlan[],
  cachedSearchResults: Map<string, GitHubSearchResult>,
  searchId?: string,
): GitHubResearchSearchPlan[] {
  if (searchId) {
    const selectedSearch = searchPlan.find((search) => search.id === searchId);
    if (!selectedSearch) {
      throw new Error(`unknown github_research searchId: ${searchId}`);
    }
    return [selectedSearch];
  }

  const pendingSearches = searchPlan.filter((search) => !cachedSearchResults.has(search.id));
  if (pendingSearches.length > 0) {
    return pendingSearches;
  }

  return searchPlan;
}

function describeSearchPlan(searchPlan: GitHubResearchSearchPlan[]): string {
  if (searchPlan.length === 1 && searchPlan[0]) {
    return describeSearchTarget(searchPlan[0]);
  }

  return `${searchPlan.length}-search plan`;
}

function describeSearchTarget(search: GitHubResearchSearchPlan): string {
  return search.repo ?? search.owner ?? 'global-github';
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
