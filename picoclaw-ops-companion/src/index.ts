import { readFile } from 'node:fs/promises';

import { persistRequestIntake } from './artifacts.js';
import { parseCliArgs } from './cli.js';
import { loadConfig } from './config.js';
import { buildLayout, ensureLayout } from './layout.js';
import { createLogger } from './logger.js';
import { companionRequestSchema } from './models.js';
import { buildApprovalJob, buildIntakeResult, classifyRisk } from './risk.js';

async function main(): Promise<void> {
  const command = parseCliArgs(process.argv.slice(2));
  const config = loadConfig();
  const logger = createLogger(config.logLevel);
  const layout = buildLayout(config);

  await ensureLayout(layout);

  if (command.name === 'bootstrap') {
    logger.log('info', 'runtime bootstrap complete', {
      projectRoot: config.projectRoot,
      workspaceRoot: config.workspaceRoot,
      notesRoot: config.notesRoot,
      opsRoot: layout.opsRoot,
      approvalTtlSeconds: config.approvalTtlSeconds,
      totpIssuer: config.totpIssuer,
    });
    return;
  }

  const request = companionRequestSchema.parse(
    JSON.parse(await readRequestSource(command.requestPath)),
  );
  const decision = classifyRisk(request);
  const approvalJob = decision.requiresApproval
    ? buildApprovalJob(request, decision, config)
    : undefined;
  const result = buildIntakeResult(request, decision, approvalJob);
  const artifacts = await persistRequestIntake(layout, {
    request,
    decision,
    approvalJob,
    result,
  });

  logger.log('info', 'request intake complete', {
    requestId: request.requestId,
    type: request.type,
    risk: decision.risk,
    requiresApproval: decision.requiresApproval,
    approvalJobId: approvalJob?.jobId,
  });

  process.stdout.write(
    `${JSON.stringify(
      {
        requestId: request.requestId,
        type: request.type,
        risk: decision.risk,
        requiresApproval: decision.requiresApproval,
        approvalJobId: approvalJob?.jobId ?? null,
        resultStatus: result.status,
        artifacts,
      },
      null,
      2,
    )}\n`,
  );
}

async function readRequestSource(requestPath: string): Promise<string> {
  if (requestPath === '-') {
    const chunks: string[] = [];

    for await (const chunk of process.stdin) {
      chunks.push(typeof chunk === 'string' ? chunk : chunk.toString('utf8'));
    }

    return chunks.join('');
  }

  return readFile(requestPath, 'utf8');
}

main().catch((error: unknown) => {
  const message = error instanceof Error ? error.message : String(error);
  process.stderr.write(
    `${JSON.stringify({ ts: new Date().toISOString(), level: 'error', message })}\n`,
  );
  process.exitCode = 1;
});
