import { mkdir, readFile, rename, writeFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { randomUUID } from 'node:crypto';

import type { Layout } from './layout.js';
import type {
  ApprovalJob,
  CompanionRequest,
  IntakeResult,
  RiskDecision,
} from './models.js';
import { approvalJobSchema, intakeResultSchema } from './models.js';

export type IntakeArtifacts = {
  requestPath: string;
  decisionPath: string;
  resultPath: string;
  approvalPath?: string;
  auditPath: string;
};

export type DecisionArtifacts = {
  approvalPath: string;
  resultPath: string;
  auditPath: string;
};

export async function persistRequestIntake(
  layout: Layout,
  input: {
    request: CompanionRequest;
    decision: RiskDecision;
    result: IntakeResult;
    approvalJob?: ApprovalJob;
  },
): Promise<IntakeArtifacts> {
  const requestPath = join(layout.requestsDir, `${toSafeSegment(input.request.requestId)}.json`);
  const decisionPath = join(
    layout.stateDir,
    `${toSafeSegment(input.request.requestId)}.decision.json`,
  );
  const resultPath = join(layout.resultsDir, `${toSafeSegment(input.request.requestId)}.json`);
  const approvalPath = input.approvalJob
    ? join(layout.approvalsDir, `${toSafeSegment(input.approvalJob.jobId)}.json`)
    : undefined;
  const auditPath = join(
    layout.logsDir,
    `${new Date().toISOString().replaceAll(':', '-')}-${toSafeSegment(input.request.requestId)}-intake.json`,
  );

  await Promise.all([
    writeJsonAtomic(requestPath, input.request),
    writeJsonAtomic(decisionPath, input.decision),
    writeJsonAtomic(resultPath, input.result),
    ...(approvalPath && input.approvalJob
      ? [writeJsonAtomic(approvalPath, input.approvalJob)]
      : []),
  ]);

  await writeJsonAtomic(auditPath, {
    ts: new Date().toISOString(),
    event: 'request_intake',
    requestId: input.request.requestId,
    risk: input.decision.risk,
    requiresApproval: input.decision.requiresApproval,
    approvalJobId: input.approvalJob?.jobId,
    artifacts: {
      requestPath,
      decisionPath,
      resultPath,
      ...(approvalPath ? { approvalPath } : {}),
    },
  });

  return {
    requestPath,
    decisionPath,
    resultPath,
    approvalPath,
    auditPath,
  };
}

export async function loadApprovalJob(layout: Layout, jobId: string): Promise<ApprovalJob> {
  const approvalPath = buildApprovalPath(layout, jobId);

  return approvalJobSchema.parse(JSON.parse(await readFile(approvalPath, 'utf8')));
}

export async function loadResultArtifact(layout: Layout, requestId: string): Promise<IntakeResult> {
  const resultPath = buildResultPath(layout, requestId);

  return intakeResultSchema.parse(JSON.parse(await readFile(resultPath, 'utf8')));
}

export async function persistApprovalDecision(
  layout: Layout,
  input: {
    approvalJob: ApprovalJob;
    result: IntakeResult;
    event: string;
    meta?: Record<string, unknown>;
  },
): Promise<DecisionArtifacts> {
  const approvalPath = buildApprovalPath(layout, input.approvalJob.jobId);
  const resultPath = buildResultPath(layout, input.result.requestId);

  await Promise.all([
    writeJsonAtomic(approvalPath, input.approvalJob),
    writeJsonAtomic(resultPath, input.result),
  ]);

  const auditPath = await appendAuditEvent(layout, input.result.requestId, input.event, {
    approvalJobId: input.approvalJob.jobId,
    status: input.approvalJob.status,
    resultStatus: input.result.status,
    ...(input.meta ?? {}),
  });

  return {
    approvalPath,
    resultPath,
    auditPath,
  };
}

export async function appendAuditEvent(
  layout: Layout,
  requestId: string,
  event: string,
  meta?: Record<string, unknown>,
): Promise<string> {
  const auditPath = join(
    layout.logsDir,
    `${new Date().toISOString().replaceAll(':', '-')}-${toSafeSegment(requestId)}-${toSafeSegment(event)}.json`,
  );

  await writeJsonAtomic(auditPath, {
    ts: new Date().toISOString(),
    event,
    requestId,
    ...(meta ? { meta } : {}),
  });

  return auditPath;
}

async function writeJsonAtomic(path: string, value: unknown): Promise<void> {
  await mkdir(dirname(path), { recursive: true });

  const tempPath = `${path}.${process.pid}.${randomUUID()}.tmp`;
  const payload = `${JSON.stringify(value, null, 2)}\n`;

  await writeFile(tempPath, payload, 'utf8');
  await rename(tempPath, path);
}

function buildApprovalPath(layout: Layout, jobId: string): string {
  return join(layout.approvalsDir, `${toSafeSegment(jobId)}.json`);
}

function buildResultPath(layout: Layout, requestId: string): string {
  return join(layout.resultsDir, `${toSafeSegment(requestId)}.json`);
}

function toSafeSegment(value: string): string {
  return value.replace(/[^A-Za-z0-9._-]+/g, '-');
}
