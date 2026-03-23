import { createHash, randomBytes } from 'node:crypto';

import type { AppConfig } from './config.js';
import type {
  ApprovalJob,
  CompanionRequest,
  IntakeResult,
  RiskDecision,
} from './models.js';

export function classifyRisk(request: CompanionRequest): RiskDecision {
  const decidedAt = new Date().toISOString();

  switch (request.type) {
    case 'github_research':
      return {
        requestId: request.requestId,
        type: request.type,
        risk: 'low',
        requiresApproval: false,
        reasonCodes: ['github-read-only-research'],
        summary: {
          action: `github research: ${request.payload.query}`,
          cwd: request.target.repo ?? request.target.owner ?? 'github',
          sideEffects: [],
        },
        decidedAt,
      };

    case 'workspace_analysis':
      return {
        requestId: request.requestId,
        type: request.type,
        risk: request.payload.writeArtifacts ? 'medium' : 'low',
        requiresApproval: false,
        reasonCodes: request.payload.writeArtifacts
          ? ['workspace-analysis-writes-artifacts']
          : ['workspace-analysis-read-only'],
        summary: {
          action: `workspace analysis: ${request.payload.prompt}`,
          cwd: request.target.path,
          sideEffects: request.payload.writeArtifacts ? ['workspace write'] : [],
        },
        decidedAt,
      };

    case 'npm_install_package': {
      const installScope = request.payload.global || request.scope === 'user' ? 'high' : 'medium';
      const packageList = request.payload.packages.join(' ');
      const installFlags = [
        request.payload.dev ? '--save-dev' : '',
        request.payload.global ? '--global' : '',
      ]
        .filter(Boolean)
        .join(' ');

      return {
        requestId: request.requestId,
        type: request.type,
        risk: installScope,
        requiresApproval: installScope === 'high',
        reasonCodes:
          installScope === 'high'
            ? ['user-environment-package-install']
            : ['project-package-install'],
        summary: {
          action: `npm install ${installFlags} ${packageList}`.trim(),
          cwd: request.target.projectPath,
          sideEffects:
            installScope === 'high'
              ? ['user environment write', 'package install']
              : ['project dependency write'],
        },
        decidedAt,
      };
    }

    case 'repo_relay_push':
      return {
        requestId: request.requestId,
        type: request.type,
        risk: 'high',
        requiresApproval: true,
        reasonCodes: ['remote-repository-write'],
        summary: {
          action: `git push ${request.target.remote} ${request.target.branch}`,
          cwd: request.target.repoPath,
          sideEffects: ['remote write'],
        },
        decidedAt,
      };
  }
}

export function buildApprovalJob(
  request: CompanionRequest,
  decision: RiskDecision,
  config: AppConfig,
): ApprovalJob {
  const createdAtDate = new Date();
  const createdAt = createdAtDate.toISOString();
  const expiresAt = new Date(
    createdAtDate.getTime() + config.approvalTtlSeconds * 1000,
  ).toISOString();
  const jobId = buildJobId(createdAtDate);
  const nonce = buildNonce(4);
  const jobHash = createHash('sha256')
    .update(
      JSON.stringify({
        requestId: request.requestId,
        requestedBy: request.requestedBy,
        risk: decision.risk,
        summary: decision.summary,
        nonce,
        expiresAt,
      }),
    )
    .digest('hex');

  return {
    jobId,
    requestId: request.requestId,
    risk: decision.risk,
    summary: decision.summary,
    requestedBy: request.requestedBy,
    nonce,
    ttlSeconds: config.approvalTtlSeconds,
    createdAt,
    expiresAt,
    jobHash,
    approvalCommand: `/approve ${jobId} <totp>`,
    rejectCommand: `/reject ${jobId}`,
    status: 'pending',
  };
}

export function buildIntakeResult(
  request: CompanionRequest,
  decision: RiskDecision,
  approvalJob?: ApprovalJob,
): IntakeResult {
  return {
    requestId: request.requestId,
    status: approvalJob ? 'awaiting_approval' : 'ready_for_execution',
    risk: decision.risk,
    summary: approvalJob
      ? `approval required before executing ${request.type}`
      : `${request.type} is ready for execution`,
    approvalJobId: approvalJob?.jobId,
    updatedAt: new Date().toISOString(),
  };
}

function buildJobId(date: Date): string {
  const stamp = date.toISOString().replace(/\D/g, '').slice(0, 14);

  return `job-${stamp}-${randomBytes(3).toString('hex')}`;
}

function buildNonce(length: number): string {
  const alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
  const bytes = randomBytes(length);

  return Array.from(bytes, (value) => alphabet[value % alphabet.length]).join('');
}
