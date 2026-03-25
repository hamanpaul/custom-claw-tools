import { createServer, type IncomingMessage, type ServerResponse } from 'node:http';

import { ZodError } from 'zod';

import type { AppConfig } from './config.js';
import type { Layout } from './layout.js';
import { processExecutionRequest, processIntakeRequest, processRelayDecision } from './operations.js';

type Logger = {
  log(
    level: 'debug' | 'info' | 'warn' | 'error',
    message: string,
    meta?: Record<string, unknown>,
  ): void;
};

export async function startLoopbackServer(
  layout: Layout,
  config: AppConfig,
  logger: Logger,
  overrides: {
    host?: string;
    port?: number;
  } = {},
): Promise<void> {
  const host = overrides.host ?? config.listenHost;
  const port = overrides.port ?? config.listenPort;
  const server = createServer((request, response) => {
    void handleRequest(request, response, { layout, config, logger, host, port });
  });

  await new Promise<void>((resolve, reject) => {
    server.once('error', reject);
    server.listen(port, host, () => {
      server.off('error', reject);
      resolve();
    });
  });

  logger.log('info', 'ops companion loopback listener started', {
    host,
    port,
    projectRoot: config.projectRoot,
    workspaceRoot: config.workspaceRoot,
    notesRoot: config.notesRoot,
  });

  await new Promise<void>((resolve, reject) => {
    server.once('close', resolve);
    server.once('error', reject);
  });
}

async function handleRequest(
  request: IncomingMessage,
  response: ServerResponse,
  context: {
    layout: Layout;
    config: AppConfig;
    logger: Logger;
    host: string;
    port: number;
  },
): Promise<void> {
  const method = request.method ?? 'GET';
  const url = new URL(request.url ?? '/', `http://${context.host}:${context.port}`);

  context.logger.log('debug', 'loopback request received', {
    method,
    path: url.pathname,
  });

  try {
    if (method === 'GET' && url.pathname === '/health') {
      writeJson(response, 200, {
        ok: true,
        host: context.host,
        port: context.port,
        projectRoot: context.config.projectRoot,
        workspaceRoot: context.config.workspaceRoot,
        notesRoot: context.config.notesRoot,
        copilotModel: context.config.copilotModel ?? null,
        copilotCliUrl: context.config.copilotCliUrl ?? null,
        copilotCliPath: context.config.copilotCliPath ?? null,
      });
      return;
    }

    if (method === 'POST' && url.pathname === '/intake') {
      const payload = await readJsonBody(request);
      const outcome = await processIntakeRequest(
        context.layout,
        context.config,
        payload,
      );

      writeJson(response, 200, outcome);
      return;
    }

    if (method === 'POST' && url.pathname === '/decision') {
      const payload = decisionPayloadSchema.parse(await readJsonBody(request));
      const outcome = await processRelayDecision(
        context.layout,
        context.config,
        payload,
      );

      writeJson(response, 200, outcome);
      return;
    }

    if (method === 'POST' && url.pathname === '/execute') {
      const payload = executePayloadSchema.parse(await readJsonBody(request));
      const outcome = await processExecutionRequest(
        context.layout,
        context.config,
        payload.requestId,
      );

      writeJson(response, 200, outcome);
      return;
    }

    if (url.pathname === '/health' || url.pathname === '/intake' || url.pathname === '/decision' || url.pathname === '/execute') {
      writeJson(response, 405, {
        error: `method ${method} is not allowed for ${url.pathname}`,
      });
      return;
    }

    writeJson(response, 404, {
      error: `unknown endpoint: ${url.pathname}`,
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    const statusCode = resolveErrorStatus(error);

    context.logger.log(statusCode >= 500 ? 'error' : 'warn', 'loopback request failed', {
      method,
      path: url.pathname,
      statusCode,
      error: message,
    });

    writeJson(response, statusCode, {
      error: message,
    });
  }
}

const decisionPayloadSchema = {
  parse(input: unknown): { sender: string; text: string } {
    if (
      typeof input !== 'object' ||
      input === null ||
      typeof (input as { sender?: unknown }).sender !== 'string' ||
      typeof (input as { text?: unknown }).text !== 'string'
    ) {
      throw new Error('decision payload must include string sender and text fields');
    }

    return {
      sender: (input as { sender: string }).sender,
      text: (input as { text: string }).text,
    };
  },
};

const executePayloadSchema = {
  parse(input: unknown): { requestId: string } {
    if (
      typeof input !== 'object' ||
      input === null ||
      typeof (input as { requestId?: unknown }).requestId !== 'string'
    ) {
      throw new Error('execute payload must include string requestId');
    }

    return {
      requestId: (input as { requestId: string }).requestId,
    };
  },
};

async function readJsonBody(request: IncomingMessage): Promise<unknown> {
  const chunks: Buffer[] = [];
  let totalBytes = 0;

  for await (const chunk of request) {
    const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
    totalBytes += buffer.byteLength;

    if (totalBytes > 1024 * 1024) {
      throw new Error('request body exceeds 1 MiB limit');
    }

    chunks.push(buffer);
  }

  if (chunks.length === 0) {
    throw new Error('request body is required');
  }

  return JSON.parse(Buffer.concat(chunks).toString('utf8'));
}

function writeJson(
  response: ServerResponse,
  statusCode: number,
  payload: Record<string, unknown>,
): void {
  response.statusCode = statusCode;
  response.setHeader('content-type', 'application/json; charset=utf-8');
  response.end(`${JSON.stringify(payload, null, 2)}\n`);
}

function resolveErrorStatus(error: unknown): number {
  if (error instanceof SyntaxError || error instanceof ZodError) {
    return 400;
  }

  if (error instanceof Error) {
    if (error.message.includes('not ready for execution')) {
      return 409;
    }

    return 400;
  }

  return 500;
}
