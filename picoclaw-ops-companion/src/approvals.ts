import { verifySync } from 'otplib';

import type { AppConfig } from './config.js';
import type { Layout } from './layout.js';
import type { ApprovalJob, IntakeResult } from './models.js';
import {
  appendAuditEvent,
  loadApprovalJob,
  loadResultArtifact,
  persistApprovalDecision,
} from './artifacts.js';

export type RelayDecision =
  | {
      action: 'approve';
      jobId: string;
      totp: string;
    }
  | {
      action: 'reject';
      jobId: string;
    };

export async function handleRelayDecision(
  layout: Layout,
  config: AppConfig,
  input: {
    sender: string;
    text: string;
  },
): Promise<{
  requestId: string;
  jobId: string;
  action: RelayDecision['action'];
  outcome: 'approved' | 'rejected' | 'expired';
  resultStatus: IntakeResult['status'];
  auditPath: string;
}> {
  const decision = parseRelayDecision(input.text);
  const approvalJob = await loadApprovalJob(layout, decision.jobId);
  const result = await loadResultArtifact(layout, approvalJob.requestId);

  if (approvalJob.requestedBy !== input.sender) {
    await appendAuditEvent(layout, approvalJob.requestId, 'approval_invalid_sender', {
      approvalJobId: approvalJob.jobId,
      expectedSender: approvalJob.requestedBy,
      actualSender: input.sender,
    });
    throw new Error(`sender mismatch for ${approvalJob.jobId}`);
  }

  if (approvalJob.status !== 'pending') {
    await appendAuditEvent(layout, approvalJob.requestId, 'approval_duplicate_attempt', {
      approvalJobId: approvalJob.jobId,
      status: approvalJob.status,
    });
    throw new Error(`job ${approvalJob.jobId} is already ${approvalJob.status}`);
  }

  if (Date.now() > Date.parse(approvalJob.expiresAt)) {
    const expiredJob: ApprovalJob = {
      ...approvalJob,
      status: 'expired',
    };
    const expiredResult: IntakeResult = {
      ...result,
      status: 'expired',
      summary: `approval expired for ${approvalJob.jobId}`,
      updatedAt: new Date().toISOString(),
    };
    const artifacts = await persistApprovalDecision(layout, {
      approvalJob: expiredJob,
      result: expiredResult,
      event: 'approval_expired',
      meta: {
        sender: input.sender,
      },
    });

    return {
      requestId: approvalJob.requestId,
      jobId: approvalJob.jobId,
      action: decision.action,
      outcome: 'expired',
      resultStatus: expiredResult.status,
      auditPath: artifacts.auditPath,
    };
  }

  if (decision.action === 'approve') {
    if (!config.totpSecret) {
      throw new Error('PICOCLAW_TOTP_SECRET is required for approve decisions');
    }

    if (
      !verifySync({
        secret: config.totpSecret,
        token: decision.totp,
        strategy: 'totp',
      })
    ) {
      await appendAuditEvent(layout, approvalJob.requestId, 'approval_invalid_totp', {
        approvalJobId: approvalJob.jobId,
        sender: input.sender,
      });
      throw new Error(`invalid TOTP for ${approvalJob.jobId}`);
    }

    const approvedJob: ApprovalJob = {
      ...approvalJob,
      status: 'approved',
    };
    const approvedResult: IntakeResult = {
      ...result,
      status: 'ready_for_execution',
      summary: `approval granted for ${approvalJob.jobId}; request is ready for execution`,
      updatedAt: new Date().toISOString(),
    };
    const artifacts = await persistApprovalDecision(layout, {
      approvalJob: approvedJob,
      result: approvedResult,
      event: 'approval_approved',
      meta: {
        sender: input.sender,
      },
    });

    return {
      requestId: approvalJob.requestId,
      jobId: approvalJob.jobId,
      action: decision.action,
      outcome: 'approved',
      resultStatus: approvedResult.status,
      auditPath: artifacts.auditPath,
    };
  }

  const rejectedJob: ApprovalJob = {
    ...approvalJob,
    status: 'rejected',
  };
  const rejectedResult: IntakeResult = {
    ...result,
    status: 'rejected',
    summary: `approval rejected for ${approvalJob.jobId}`,
    updatedAt: new Date().toISOString(),
  };
  const artifacts = await persistApprovalDecision(layout, {
    approvalJob: rejectedJob,
    result: rejectedResult,
    event: 'approval_rejected',
    meta: {
      sender: input.sender,
    },
  });

  return {
    requestId: approvalJob.requestId,
    jobId: approvalJob.jobId,
    action: decision.action,
    outcome: 'rejected',
    resultStatus: rejectedResult.status,
    auditPath: artifacts.auditPath,
  };
}

export function parseRelayDecision(text: string): RelayDecision {
  const trimmed = text.trim();
  const approveMatch = /^\/approve\s+(\S+)\s+(\d{6,8})$/.exec(trimmed);

  if (approveMatch) {
    const jobId = approveMatch[1];
    const totp = approveMatch[2];

    if (jobId === undefined || totp === undefined) {
      throw new Error(`unsupported relay command: ${text}`);
    }

    return {
      action: 'approve',
      jobId,
      totp,
    };
  }

  const rejectMatch = /^\/reject\s+(\S+)$/.exec(trimmed);

  if (rejectMatch) {
    const jobId = rejectMatch[1];

    if (jobId === undefined) {
      throw new Error(`unsupported relay command: ${text}`);
    }

    return {
      action: 'reject',
      jobId,
    };
  }

  throw new Error(`unsupported relay command: ${text}`);
}
