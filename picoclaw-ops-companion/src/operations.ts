import { handleRelayDecision } from './approvals.js';
import { persistRequestIntake } from './artifacts.js';
import type { AppConfig } from './config.js';
import { executeRequest } from './execution.js';
import type { Layout } from './layout.js';
import { companionRequestSchema } from './models.js';
import { buildApprovalJob, buildIntakeResult, classifyRisk } from './risk.js';

export async function processIntakeRequest(
  layout: Layout,
  config: AppConfig,
  input: unknown,
): Promise<{
  requestId: string;
  type: string;
  risk: string;
  requiresApproval: boolean;
  approvalJobId: string | null;
  resultStatus: string;
  artifacts: Awaited<ReturnType<typeof persistRequestIntake>>;
}> {
  const request = companionRequestSchema.parse(input);
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

  return {
    requestId: request.requestId,
    type: request.type,
    risk: decision.risk,
    requiresApproval: decision.requiresApproval,
    approvalJobId: approvalJob?.jobId ?? null,
    resultStatus: result.status,
    artifacts,
  };
}

export async function processExecutionRequest(
  layout: Layout,
  config: AppConfig,
  requestId: string,
): Promise<Awaited<ReturnType<typeof executeRequest>>> {
  return executeRequest(layout, config, requestId);
}

export async function processRelayDecision(
  layout: Layout,
  config: AppConfig,
  input: {
    sender: string;
    text: string;
  },
): Promise<Awaited<ReturnType<typeof handleRelayDecision>>> {
  return handleRelayDecision(layout, config, input);
}
