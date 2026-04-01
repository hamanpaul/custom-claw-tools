import { appendFileSync } from 'node:fs';

import { z, ZodError } from 'zod';

import { loadConfig } from './config.js';
import { buildLayout, ensureLayout } from './layout.js';
import { createLogger } from './logger.js';
import {
  buildNpmInstallPackageRequest,
  buildRepoRelayPushRequest,
  buildGithubResearchRequest,
  buildLoopbackHealth,
  buildStatusSummary,
  buildWorkspaceAnalysisRequest,
  canAutoExecuteRequestType,
  runDecisionWorkflowDirect,
  runExecuteWorkflowDirect,
  runIntakeWorkflowDirect,
  type StatusSummary,
} from './relay-core.js';

const JSON_RPC_VERSION = '2.0';
const LATEST_PROTOCOL_VERSION = '2025-11-25';
const SUPPORTED_PROTOCOL_VERSIONS = [
  '2025-11-25',
  '2025-06-18',
  '2025-03-26',
  '2024-11-05',
] as const;
const DEFAULT_LOW_RISK_SENDER = 'mcp:ops-companion';

type JsonRpcId = string | number | null;

type JsonRpcRequest = {
  jsonrpc?: string;
  id?: JsonRpcId;
  method?: string;
  params?: unknown;
};

type MessageFraming = 'content-length' | 'ndjson';

type TextContent = {
  type: 'text';
  text: string;
};

type ToolCallResult = {
  content: TextContent[];
  structuredContent: Record<string, unknown>;
  isError?: boolean;
};

type ToolResponse = {
  text: string;
  structuredContent: Record<string, unknown>;
  isError?: boolean;
};

type ToolDefinition<TArgs extends z.ZodTypeAny> = {
  name: string;
  description: string;
  inputSchema: Record<string, unknown>;
  argsSchema: TArgs;
  handler: (args: z.infer<TArgs>) => Promise<ToolResponse>;
};

const emptyObjectSchema = z.object({});
type TraceLogger = (event: string, details?: Record<string, unknown>) => void;

async function main(): Promise<void> {
  const config = loadConfig();
  const layout = buildLayout(config);
  const logger = createLogger(config.logLevel);
  const trace = createTraceLogger(process.env.PICOCLAW_OPS_MCP_TRACE_FILE);

  await ensureLayout(layout);

  trace('server_start', {
    pid: process.pid,
    cwd: process.cwd(),
    logLevel: config.logLevel,
  });

  const tools = new Map<string, ToolDefinition<z.ZodTypeAny>>();

  const registerTool = <TArgs extends z.ZodTypeAny>(
    tool: ToolDefinition<TArgs>,
  ): void => {
    tools.set(tool.name, tool as ToolDefinition<z.ZodTypeAny>);
  };

  registerTool({
    name: 'health',
    description:
      'Check ops companion runtime health and show the configured project, workspace, and notes roots.',
    inputSchema: {
      type: 'object',
      properties: {},
      additionalProperties: false,
    },
    argsSchema: emptyObjectSchema,
    handler: async () => {
      const health = buildLoopbackHealth(config);
      return {
        text: `ops companion is healthy on ${health.host}:${health.port}`,
        structuredContent: {
          health,
        },
      };
    },
  });

  registerTool({
    name: 'notes_analysis',
    description:
      'Analyze the PicoClaw notes tree through ops companion. Low-risk workspace_analysis requests are automatically intaken and executed.',
    inputSchema: {
      type: 'object',
      properties: {
        sender: {
          type: 'string',
          description:
            'Requester identity. Use telegram:<sender-id> when available. Low-risk runs default to mcp:ops-companion.',
          default: DEFAULT_LOW_RISK_SENDER,
        },
        prompt: {
          type: 'string',
          description: 'What to analyze about the notes tree.',
        },
        writeArtifacts: {
          type: 'boolean',
          description:
            'Whether the companion request payload should ask for additional written artifacts.',
          default: false,
        },
        requestId: {
          type: 'string',
          description: 'Optional caller-supplied request ID.',
        },
      },
      required: ['prompt'],
      additionalProperties: false,
    },
    argsSchema: z.object({
      sender: z.string().trim().min(1).default(DEFAULT_LOW_RISK_SENDER),
      prompt: z.string().trim().min(1),
      writeArtifacts: z.boolean().default(false),
      requestId: z.string().trim().min(1).optional(),
    }),
    handler: async (args) => {
      const workflow = await runIntakeWorkflowDirect(
        layout,
        config,
        buildWorkspaceAnalysisRequest(config, {
          sender: args.sender,
          path: config.notesRoot,
          prompt: args.prompt,
          scope: 'notes',
          writeArtifacts: args.writeArtifacts,
          requestId: args.requestId,
        }),
        true,
      );

      const compact = buildCompactWorkflowResult(workflow.status, workflow.execute);
      return {
        text: summarizeWorkflow(workflow.status, workflow.execute),
        structuredContent: compact,
      };
    },
  });

  registerTool({
    name: 'workspace_analysis',
    description:
      'Analyze a path inside notes, workspace, or repo roots through ops companion. Low-risk requests are automatically intaken and executed.',
    inputSchema: {
      type: 'object',
      properties: {
        sender: {
          type: 'string',
          description:
            'Requester identity. Use telegram:<sender-id> when available. Low-risk runs default to mcp:ops-companion.',
          default: DEFAULT_LOW_RISK_SENDER,
        },
        path: {
          type: 'string',
          description: 'Absolute path to analyze. It must stay within notes, workspace, or repo roots.',
        },
        prompt: {
          type: 'string',
          description: 'What to analyze about the target path.',
        },
        scope: {
          type: 'string',
          enum: ['notes', 'workspace', 'repo'],
          description:
            'Optional explicit scope. When omitted, ops companion infers the scope from the target path.',
        },
        writeArtifacts: {
          type: 'boolean',
          description:
            'Whether the companion request payload should ask for additional written artifacts.',
          default: false,
        },
        requestId: {
          type: 'string',
          description: 'Optional caller-supplied request ID.',
        },
      },
      required: ['path', 'prompt'],
      additionalProperties: false,
    },
    argsSchema: z.object({
      sender: z.string().trim().min(1).default(DEFAULT_LOW_RISK_SENDER),
      path: z.string().trim().min(1),
      prompt: z.string().trim().min(1),
      scope: z.enum(['notes', 'workspace', 'repo']).optional(),
      writeArtifacts: z.boolean().default(false),
      requestId: z.string().trim().min(1).optional(),
    }),
    handler: async (args) => {
      const workflow = await runIntakeWorkflowDirect(
        layout,
        config,
        buildWorkspaceAnalysisRequest(config, args),
        true,
      );

      const compact = buildCompactWorkflowResult(workflow.status, workflow.execute);
      return {
        text: summarizeWorkflow(workflow.status, workflow.execute),
        structuredContent: compact,
      };
    },
  });

  registerTool({
    name: 'github_research',
    description:
      'Run read-only GitHub research through the ops companion Copilot session. Low-risk requests are automatically intaken and executed.',
    inputSchema: {
      type: 'object',
      properties: {
        sender: {
          type: 'string',
          description:
            'Requester identity. Use telegram:<sender-id> when available. Low-risk runs default to mcp:ops-companion.',
          default: DEFAULT_LOW_RISK_SENDER,
        },
        query: {
          type: 'string',
          description: 'The GitHub research query or research prompt.',
        },
        scope: {
          type: 'string',
          enum: ['repo', 'org', 'user', 'global'],
          description:
            'Optional explicit GitHub scope. When omitted, ops companion infers repo/global from repo or owner fields.',
        },
        repo: {
          type: 'string',
          description: 'Repository in owner/name form. Required for repo scope.',
        },
        owner: {
          type: 'string',
          description: 'Owner or user name. Required for org or user scope.',
        },
        mode: {
          type: 'string',
          enum: ['generic', 'issues', 'pull_requests', 'code', 'repositories'],
          description: 'GitHub research mode.',
          default: 'generic',
        },
        limit: {
          type: 'integer',
          minimum: 1,
          maximum: 100,
          description: 'Maximum number of search results to request.',
          default: 10,
        },
        requestId: {
          type: 'string',
          description: 'Optional caller-supplied request ID.',
        },
      },
      required: ['query'],
      additionalProperties: false,
    },
    argsSchema: z.object({
      sender: z.string().trim().min(1).default(DEFAULT_LOW_RISK_SENDER),
      query: z.string().trim().min(1),
      scope: z.enum(['repo', 'org', 'user', 'global']).optional(),
      repo: z.string().trim().min(1).optional(),
      owner: z.string().trim().min(1).optional(),
      mode: z.enum(['generic', 'issues', 'pull_requests', 'code', 'repositories']).default('generic'),
      limit: z.number().int().positive().max(100).default(10),
      requestId: z.string().trim().min(1).optional(),
    }),
    handler: async (args) => {
      const workflow = await runIntakeWorkflowDirect(
        layout,
        config,
        buildGithubResearchRequest(args),
        true,
      );

      const compact = buildCompactWorkflowResult(workflow.status, workflow.execute);
      return {
        text: summarizeWorkflow(workflow.status, workflow.execute),
        structuredContent: compact,
      };
    },
  });

  registerTool({
    name: 'repo_relay_push',
    description:
      'Create a high-risk repo_relay_push request through ops companion. This produces an approval job and does not auto-execute until explicitly approved.',
    inputSchema: {
      type: 'object',
      properties: {
        sender: {
          type: 'string',
          description:
            'Original requester identity, usually telegram:<sender-id>. This will own the approval job.',
        },
        repoPath: {
          type: 'string',
          description: 'Absolute path to the target repository on the current host.',
        },
        remote: {
          type: 'string',
          description: 'Git remote name to push to.',
          default: 'origin',
        },
        branch: {
          type: 'string',
          description: 'Git branch to push.',
          default: 'main',
        },
        revision: {
          type: 'string',
          description: 'Revision to push.',
          default: 'HEAD',
        },
        transport: {
          type: 'string',
          enum: ['relay', 'bundle'],
          description: 'Requested relay transport.',
          default: 'relay',
        },
        requestId: {
          type: 'string',
          description: 'Optional caller-supplied request ID.',
        },
      },
      required: ['sender', 'repoPath'],
      additionalProperties: false,
    },
    argsSchema: z.object({
      sender: z.string().trim().min(1),
      repoPath: z.string().trim().min(1),
      remote: z.string().trim().min(1).default('origin'),
      branch: z.string().trim().min(1).default('main'),
      revision: z.string().trim().min(1).default('HEAD'),
      transport: z.enum(['relay', 'bundle']).default('relay'),
      requestId: z.string().trim().min(1).optional(),
    }),
    handler: async (args) => {
      const workflow = await runIntakeWorkflowDirect(
        layout,
        config,
        buildRepoRelayPushRequest(args),
        false,
      );

      const compact = buildCompactWorkflowResult(workflow.status, workflow.execute);
      return {
        text: summarizeWorkflow(workflow.status, workflow.execute),
        structuredContent: compact,
      };
    },
  });

  registerTool({
    name: 'npm_install_package',
    description:
      'Create an npm_install_package request through ops companion. Project installs may execute directly, while user/global installs require approval.',
    inputSchema: {
      type: 'object',
      properties: {
        sender: {
          type: 'string',
          description:
            'Requester identity. Use telegram:<sender-id> when available. This will own any approval job.',
        },
        projectPath: {
          type: 'string',
          description: 'Absolute project path for the install target.',
        },
        packages: {
          type: 'array',
          items: {
            type: 'string',
          },
          description: 'Package names to install.',
        },
        scope: {
          type: 'string',
          enum: ['project', 'user'],
          description:
            'Optional explicit install scope. When omitted, global installs imply user scope.',
        },
        dev: {
          type: 'boolean',
          description: 'Whether to install as a dev dependency.',
          default: false,
        },
        global: {
          type: 'boolean',
          description: 'Whether to perform a global install.',
          default: false,
        },
        requestId: {
          type: 'string',
          description: 'Optional caller-supplied request ID.',
        },
      },
      required: ['sender', 'projectPath', 'packages'],
      additionalProperties: false,
    },
    argsSchema: z.object({
      sender: z.string().trim().min(1),
      projectPath: z.string().trim().min(1),
      packages: z.array(z.string().trim().min(1)).min(1),
      scope: z.enum(['project', 'user']).optional(),
      dev: z.boolean().default(false),
      global: z.boolean().default(false),
      requestId: z.string().trim().min(1).optional(),
    }),
    handler: async (args) => {
      const request = buildNpmInstallPackageRequest(args);
      const workflow = await runIntakeWorkflowDirect(
        layout,
        config,
        request,
        canAutoExecuteRequestType(request.type),
      );

      const compact = buildCompactWorkflowResult(workflow.status, workflow.execute);
      return {
        text: summarizeWorkflow(workflow.status, workflow.execute),
        structuredContent: compact,
      };
    },
  });

  registerTool({
    name: 'approve_job',
    description:
      'Approve an existing ops companion job for the original sender using a 6-digit TOTP. If the job becomes ready, execution is triggered automatically.',
    inputSchema: {
      type: 'object',
      properties: {
        sender: {
          type: 'string',
          description:
            'Original requester identity, usually telegram:<sender-id>. This must match the request owner.',
        },
        jobId: {
          type: 'string',
          description: 'Approval job ID to approve.',
        },
        totp: {
          type: 'string',
          description: 'Current 6-digit TOTP code from the authenticator app.',
        },
        autoExecute: {
          type: 'boolean',
          description:
            'Whether to execute automatically after approval when the request reaches ready_for_execution.',
          default: true,
        },
      },
      required: ['sender', 'jobId', 'totp'],
      additionalProperties: false,
    },
    argsSchema: z.object({
      sender: z.string().trim().min(1),
      jobId: z.string().trim().min(1),
      totp: z.string().trim().regex(/^\d{6}$/, 'totp must be a 6-digit code'),
      autoExecute: z.boolean().default(true),
    }),
    handler: async (args) => {
      const workflow = await runDecisionWorkflowDirect(
        layout,
        config,
        {
          sender: args.sender,
          text: `/approve ${args.jobId} ${args.totp}`,
        },
        args.autoExecute,
      );

      const compact = {
        requestId: workflow.status.requestId,
        jobId: workflow.decision.jobId,
        action: workflow.decision.action,
        outcome: workflow.decision.outcome,
        resultStatus: workflow.status.result.status,
        executeSummary: workflow.execute?.summary ?? null,
        status: buildCompactStatus(workflow.status),
      };

      return {
        text: summarizeDecisionWorkflow(workflow.status, workflow.decision, workflow.execute),
        structuredContent: compact,
      };
    },
  });

  registerTool({
    name: 'reject_job',
    description:
      'Reject an existing ops companion approval job for the original sender.',
    inputSchema: {
      type: 'object',
      properties: {
        sender: {
          type: 'string',
          description:
            'Original requester identity, usually telegram:<sender-id>. This must match the request owner.',
        },
        jobId: {
          type: 'string',
          description: 'Approval job ID to reject.',
        },
      },
      required: ['sender', 'jobId'],
      additionalProperties: false,
    },
    argsSchema: z.object({
      sender: z.string().trim().min(1),
      jobId: z.string().trim().min(1),
    }),
    handler: async (args) => {
      const workflow = await runDecisionWorkflowDirect(
        layout,
        config,
        {
          sender: args.sender,
          text: `/reject ${args.jobId}`,
        },
        false,
      );

      const compact = {
        requestId: workflow.status.requestId,
        jobId: workflow.decision.jobId,
        action: workflow.decision.action,
        outcome: workflow.decision.outcome,
        resultStatus: workflow.status.result.status,
        status: buildCompactStatus(workflow.status),
      };

      return {
        text: summarizeDecisionWorkflow(workflow.status, workflow.decision, workflow.execute),
        structuredContent: compact,
      };
    },
  });

  registerTool({
    name: 'request_status',
    description:
      'Get request, result, approval, and audit status for an existing ops companion request.',
    inputSchema: {
      type: 'object',
      properties: {
        requestId: {
          type: 'string',
          description: 'Request ID to inspect.',
        },
      },
      required: ['requestId'],
      additionalProperties: false,
    },
    argsSchema: z.object({
      requestId: z.string().trim().min(1),
    }),
    handler: async (args) => {
      const status = await buildStatusSummary(layout, args.requestId);
      const compact = buildCompactStatus(status);

      return {
        text: summarizeStatus(status),
        structuredContent: compact,
      };
    },
  });

  registerTool({
    name: 'execute_request',
    description:
      'Execute an existing request that is already ready_for_execution. This is useful after approving a request whose execute wrapper is available.',
    inputSchema: {
      type: 'object',
      properties: {
        requestId: {
          type: 'string',
          description: 'Request ID to execute.',
        },
      },
      required: ['requestId'],
      additionalProperties: false,
    },
    argsSchema: z.object({
      requestId: z.string().trim().min(1),
    }),
    handler: async (args) => {
      const workflow = await runExecuteWorkflowDirect(layout, config, args.requestId);

      return {
        text: summarizeWorkflow(workflow.status, workflow.execute),
        structuredContent: {
          requestId: workflow.status.requestId,
          executeSummary: workflow.execute.summary,
          executeArtifactPath: workflow.execute.artifactPath ?? null,
          executeAuditPath: workflow.execute.auditPath,
          status: buildCompactStatus(workflow.status),
        },
      };
    },
  });

  const instructions = [
    'Use these tools to route repo, research, and approval tasks through picoclaw-ops-companion.',
    'Low-risk notes/workspace/github requests automatically intake and execute.',
    'High-risk requests can create approval jobs, and approval actions require the original sender identity plus a current 6-digit TOTP.',
  ].join(' ');

  const server = new StdioMcpServer({
    logger,
    instructions,
    trace,
    tools,
  });

  await server.run();
}

type StdioMcpServerOptions = {
  logger: ReturnType<typeof createLogger>;
  instructions: string;
  trace: TraceLogger;
  tools: Map<string, ToolDefinition<z.ZodTypeAny>>;
};

class StdioMcpServer {
  private readonly logger: ReturnType<typeof createLogger>;
  private readonly instructions: string;
  private readonly trace: TraceLogger;
  private readonly tools: Map<string, ToolDefinition<z.ZodTypeAny>>;
  private buffer = Buffer.alloc(0);
  private processing = Promise.resolve();
  private initialized = false;
  private framing: MessageFraming | null = null;

  constructor(options: StdioMcpServerOptions) {
    this.logger = options.logger;
    this.instructions = options.instructions;
    this.trace = options.trace;
    this.tools = options.tools;
  }

  async run(): Promise<void> {
    process.stdin.on('data', (chunk: Buffer | string) => {
      const data = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
      this.buffer = Buffer.concat([this.buffer, data]);
      this.processing = this.processing
        .then(() => this.drainBuffer())
        .catch((error: unknown) => {
          this.logger.log(
            'error',
            'mcp stdio buffer processing failed',
            {
              error: toErrorMessage(error),
            },
          );
        });
    });

    process.stdin.on('end', () => {
      this.trace('stdin_end');
      process.exit(0);
    });

    process.stdin.resume();
    await new Promise<void>((resolve) => {
      process.once('beforeExit', () => resolve());
    });
    this.trace('server_exit');
  }

  private async drainBuffer(): Promise<void> {
    while (true) {
      if (!this.framing) {
        this.framing = this.detectFraming();
      }

      if (!this.framing) {
        return;
      }

      const body =
        this.framing === 'content-length'
          ? this.readContentLengthMessage()
          : this.readNdjsonMessage();

      if (body === null) {
        return;
      }

      if (body.length === 0) {
        continue;
      }

      await this.handleRawBody(body);
    }
  }

  private detectFraming(): MessageFraming | null {
    for (const byte of this.buffer.values()) {
      if (byte === 0x0a || byte === 0x0d || byte === 0x20 || byte === 0x09) {
        continue;
      }

      if (byte === 0x7b || byte === 0x5b) {
        this.logger.log('debug', 'detected ndjson mcp stdio framing');
        this.trace('detected_framing', {
          framing: 'ndjson',
        });
        return 'ndjson';
      }

      if (byte === 0x43 || byte === 0x63) {
        this.logger.log('debug', 'detected content-length mcp stdio framing');
        this.trace('detected_framing', {
          framing: 'content-length',
        });
        return 'content-length';
      }

      this.logger.log('error', 'unable to detect mcp stdio framing', {
        byte,
      });
      this.trace('detect_framing_failed', {
        byte,
      });
      this.buffer = Buffer.alloc(0);
      return null;
    }

    return null;
  }

  private readContentLengthMessage(): string | null {
    const headerEnd = this.buffer.indexOf('\r\n\r\n');

    if (headerEnd === -1) {
      return null;
    }

    const headerText = this.buffer.slice(0, headerEnd).toString('utf8');
    const contentLength = this.parseContentLength(headerText);

    if (contentLength === null) {
      this.logger.log('error', 'mcp stdio message missing content-length header');
      this.trace('content_length_missing');
      this.buffer = Buffer.alloc(0);
      this.framing = null;
      return null;
    }

    const totalLength = headerEnd + 4 + contentLength;

    if (this.buffer.length < totalLength) {
      return null;
    }

    const body = this.buffer.slice(headerEnd + 4, totalLength).toString('utf8');
    this.buffer = this.buffer.slice(totalLength);

    return body;
  }

  private readNdjsonMessage(): string | null {
    while (true) {
      const newlineIndex = this.buffer.indexOf('\n');

      if (newlineIndex === -1) {
        return null;
      }

      const line = this.buffer.slice(0, newlineIndex).toString('utf8');
      this.buffer = this.buffer.slice(newlineIndex + 1);

      const body = line.replace(/\r$/, '');

      if (body.trim().length === 0) {
        continue;
      }

      return body;
    }
  }

  private parseContentLength(headerText: string): number | null {
    for (const line of headerText.split('\r\n')) {
      const separatorIndex = line.indexOf(':');

      if (separatorIndex === -1) {
        continue;
      }

      const name = line.slice(0, separatorIndex).trim().toLowerCase();

      if (name !== 'content-length') {
        continue;
      }

      const value = Number.parseInt(line.slice(separatorIndex + 1).trim(), 10);
      return Number.isFinite(value) && value >= 0 ? value : null;
    }

    return null;
  }

  private async handleRawBody(body: string): Promise<void> {
    let message: JsonRpcRequest;

    try {
      message = JSON.parse(body) as JsonRpcRequest;
    } catch (error) {
      this.trace('parse_error', {
        error: toErrorMessage(error),
      });
      this.sendError(null, -32700, `parse error: ${toErrorMessage(error)}`);
      return;
    }

    this.trace('message_received', summarizeMessage(message));

    if (message.jsonrpc !== JSON_RPC_VERSION || typeof message.method !== 'string') {
      this.sendError(message.id ?? null, -32600, 'invalid json-rpc request');
      return;
    }

    if (message.id === undefined) {
      await this.handleNotification(message.method, message.params);
      return;
    }

    await this.handleRequest(message.id, message.method, message.params);
  }

  private async handleNotification(method: string, params: unknown): Promise<void> {
    if (method === 'notifications/initialized') {
      this.initialized = true;
      this.logger.log('debug', 'mcp client initialized');
      this.trace('client_initialized');
      return;
    }

    this.logger.log('debug', 'ignoring unsupported mcp notification', {
      method,
      params: params ?? null,
    });
  }

  private async handleRequest(
    id: JsonRpcId,
    method: string,
    params: unknown,
  ): Promise<void> {
    switch (method) {
      case 'initialize': {
        const request = initializeParamsSchema.parse(params ?? {});
        const protocolVersion = resolveProtocolVersion(request.protocolVersion);

        this.sendResult(id, {
          protocolVersion,
          capabilities: {
            tools: {},
          },
          serverInfo: {
            name: 'picoclaw-ops-companion',
            version: '1.0.0',
          },
          instructions: this.instructions,
        });
        this.trace('initialize_result_sent', {
          protocolVersion,
        });
        return;
      }

      case 'ping': {
        this.sendResult(id, {});
        this.trace('ping_result_sent');
        return;
      }

      case 'tools/list': {
        this.sendResult(id, {
          tools: Array.from(this.tools.values()).map((tool) => ({
            name: tool.name,
            description: tool.description,
            inputSchema: tool.inputSchema,
          })),
        });
        this.trace('tools_list_sent', {
          toolCount: this.tools.size,
        });
        return;
      }

      case 'tools/call': {
        const request = toolCallParamsSchema.parse(params ?? {});
        const tool = this.tools.get(request.name);

        if (!tool) {
          this.trace('tool_not_found', {
            toolName: request.name,
          });
          this.sendError(id, -32601, `unknown tool: ${request.name}`);
          return;
        }

        try {
          const parsedArgs = tool.argsSchema.parse(request.arguments ?? {});
          const result = await tool.handler(parsedArgs);
          this.sendResult(id, toToolCallResult(result));
          this.trace('tool_call_succeeded', {
            toolName: request.name,
            isError: result.isError ?? false,
          });
        } catch (error) {
          const message = toErrorMessage(error);
          const details =
            error instanceof ZodError
              ? {
                  issues: error.issues.map((issue) => ({
                    path: issue.path.join('.'),
                    message: issue.message,
                  })),
                }
              : null;
          this.sendResult(id, {
            content: [
              {
                type: 'text',
                text: details
                  ? `${message}\n\n${JSON.stringify(details, null, 2)}`
                  : message,
              },
            ],
            structuredContent: {
              error: message,
              ...(details ? { details } : {}),
            },
            isError: true,
          });
          this.trace('tool_call_failed', {
            toolName: request.name,
            error: message,
          });
        }
        return;
      }

      default: {
        this.trace('method_not_found', {
          method,
        });
        this.sendError(id, -32601, `method not found: ${method}`);
      }
    }
  }

  private sendResult(id: JsonRpcId, result: Record<string, unknown>): void {
    this.writeMessage({
      jsonrpc: JSON_RPC_VERSION,
      id,
      result,
    });
  }

  private sendError(id: JsonRpcId, code: number, message: string): void {
    this.writeMessage({
      jsonrpc: JSON_RPC_VERSION,
      id,
      error: {
        code,
        message,
      },
    });
  }

  private writeMessage(payload: Record<string, unknown>): void {
    const body = JSON.stringify(payload);

    if (this.framing === 'ndjson') {
      process.stdout.write(`${body}\n`);
      return;
    }

    const header = `Content-Length: ${Buffer.byteLength(body, 'utf8')}\r\n\r\n`;
    process.stdout.write(header);
    process.stdout.write(body);
  }
}

const initializeParamsSchema = z.object({
  protocolVersion: z.string().trim().min(1).optional(),
  clientInfo: z
    .object({
      name: z.string().trim().min(1).optional(),
      version: z.string().trim().min(1).optional(),
    })
    .optional(),
  capabilities: z.record(z.string(), z.unknown()).optional(),
});

const toolCallParamsSchema = z.object({
  name: z.string().trim().min(1),
  arguments: z.record(z.string(), z.unknown()).optional(),
});

function resolveProtocolVersion(clientVersion?: string): string {
  if (!clientVersion) {
    return LATEST_PROTOCOL_VERSION;
  }

  return SUPPORTED_PROTOCOL_VERSIONS.includes(
    clientVersion as (typeof SUPPORTED_PROTOCOL_VERSIONS)[number],
  )
    ? clientVersion
    : LATEST_PROTOCOL_VERSION;
}

function toToolCallResult(result: ToolResponse): ToolCallResult {
  return {
    content: [
      {
        type: 'text',
        text: result.text,
      },
    ],
    structuredContent: result.structuredContent,
    ...(result.isError ? { isError: true } : {}),
  };
}

function createTraceLogger(traceFile?: string): TraceLogger {
  if (!traceFile || traceFile.trim().length === 0) {
    return () => {};
  }

  return (event, details = {}) => {
    const payload = {
      ts: new Date().toISOString(),
      pid: process.pid,
      event,
      ...details,
    };

    try {
      appendFileSync(traceFile, `${JSON.stringify(payload)}\n`, 'utf8');
    } catch (error) {
      process.stderr.write(
        `[ops-mcp-trace] failed to append trace event ${event}: ${toErrorMessage(error)}\n`,
      );
    }
  };
}

function summarizeMessage(message: JsonRpcRequest): Record<string, unknown> {
  const summary: Record<string, unknown> = {
    hasId: message.id !== undefined,
    id: message.id ?? null,
    method: message.method ?? null,
  };

  if (message.method === 'initialize' && isRecord(message.params)) {
    summary.protocolVersion =
      typeof message.params.protocolVersion === 'string'
        ? message.params.protocolVersion
        : null;
  }

  if (message.method === 'tools/call' && isRecord(message.params)) {
    summary.toolName = typeof message.params.name === 'string' ? message.params.name : null;
  }

  return summary;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function buildCompactWorkflowResult(
  status: StatusSummary,
  execute: {
    summary: string;
    artifactPath?: string;
    auditPath: string;
  } | null,
): Record<string, unknown> {
  return {
    requestId: status.requestId,
    requestType: status.request.type,
    requestedBy: status.request.requestedBy,
    resultStatus: status.result.status,
    resultSummary: status.result.summary,
    detail: status.result.detail ?? null,
    approvalJobId: status.result.approvalJobId ?? null,
    executeSummary: execute?.summary ?? null,
    executeArtifactPath: execute?.artifactPath ?? null,
    executeAuditPath: execute?.auditPath ?? null,
    status: buildCompactStatus(status),
  };
}

function buildCompactStatus(status: StatusSummary): Record<string, unknown> {
  return {
    requestId: status.requestId,
    requestType: status.request.type,
    requestedBy: status.request.requestedBy,
    scope: status.request.scope,
    resultStatus: status.result.status,
    resultSummary: status.result.summary,
    detail: status.result.detail ?? null,
    approvalJobId: status.result.approvalJobId ?? null,
    artifactPath: status.result.artifactPath ?? null,
    approvalStatus: status.approvalJob?.status ?? null,
    approvalCommand: status.approvalJob?.approvalCommand ?? null,
    rejectCommand: status.approvalJob?.rejectCommand ?? null,
    paths: status.paths,
  };
}

function summarizeWorkflow(
  status: StatusSummary,
  execute: {
    summary: string;
  } | null,
): string {
  if (status.result.status === 'awaiting_approval' && status.approvalJob) {
    return [
      `${status.request.type} request ${status.requestId} is awaiting approval.`,
      `Use ${status.approvalJob.approvalCommand} or ${status.approvalJob.rejectCommand}.`,
      JSON.stringify(buildCompactStatus(status), null, 2),
    ].join('\n\n');
  }

  const summary = execute?.summary ?? status.result.summary;

  return [
    `${summary} (request ${status.requestId}, status ${status.result.status}).`,
    JSON.stringify(buildCompactStatus(status), null, 2),
  ].join('\n\n');
}

function summarizeDecisionWorkflow(
  status: StatusSummary,
  decision: {
    action: 'approve' | 'reject';
    outcome: 'approved' | 'rejected' | 'expired';
    jobId: string;
  },
  execute: {
    summary: string;
  } | null,
): string {
  const headline =
    execute?.summary ??
    `job ${decision.jobId} ${decision.outcome} for request ${status.requestId} (${status.result.status})`;

  return [
    headline,
    JSON.stringify({
      jobId: decision.jobId,
      action: decision.action,
      outcome: decision.outcome,
      status: buildCompactStatus(status),
      executeSummary: execute?.summary ?? null,
    }, null, 2),
  ].join('\n\n');
}

function summarizeStatus(status: StatusSummary): string {
  const headline =
    status.result.status === 'awaiting_approval' && status.approvalJob
      ? `request ${status.requestId} is awaiting approval via job ${status.approvalJob.jobId}`
      : `request ${status.requestId} is ${status.result.status}: ${status.result.summary}`;

  return [
    headline,
    JSON.stringify(buildCompactStatus(status), null, 2),
  ].join('\n\n');
}

function toErrorMessage(error: unknown): string {
  if (error instanceof ZodError) {
    return `invalid tool arguments: ${error.issues
      .map((issue) => {
        const path = issue.path.length > 0 ? `${issue.path.join('.')}: ` : '';
        return `${path}${issue.message}`;
      })
      .join('; ')}`;
  }

  return error instanceof Error ? error.message : String(error);
}

main().catch((error: unknown) => {
  const logger = createLogger('error');
  logger.log('error', 'ops companion mcp server failed', {
    error: toErrorMessage(error),
  });
  process.exitCode = 1;
});
