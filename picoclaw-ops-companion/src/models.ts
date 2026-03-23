import { z } from 'zod';

export const riskLevelSchema = z.enum(['low', 'medium', 'high']);
export const requestTypeSchema = z.enum([
  'github_research',
  'repo_relay_push',
  'npm_install_package',
  'workspace_analysis',
]);

const requestEnvelopeSchema = z.object({
  requestId: z.string().min(1),
  requestedBy: z.string().min(1),
});

const githubResearchRequestSchema = requestEnvelopeSchema.extend({
  type: z.literal('github_research'),
  scope: z.enum(['repo', 'org', 'user', 'global']),
  target: z.object({
    repo: z.string().min(1).optional(),
    owner: z.string().min(1).optional(),
  }),
  payload: z.object({
    query: z.string().min(1),
    mode: z.enum(['generic', 'issues', 'pull_requests', 'code', 'repositories']).default('generic'),
    limit: z.number().int().positive().max(100).default(10),
  }),
}).superRefine((value, ctx) => {
  if (value.scope === 'repo' && !value.target.repo) {
    ctx.addIssue({
      code: z.ZodIssueCode.custom,
      message: 'github_research with repo scope requires target.repo',
      path: ['target', 'repo'],
    });
  }

  if (value.scope === 'org' && !value.target.owner) {
    ctx.addIssue({
      code: z.ZodIssueCode.custom,
      message: 'github_research with org scope requires target.owner',
      path: ['target', 'owner'],
    });
  }
});

const repoRelayPushRequestSchema = requestEnvelopeSchema.extend({
  type: z.literal('repo_relay_push'),
  scope: z.literal('repo'),
  target: z.object({
    repoPath: z.string().min(1),
    remote: z.string().min(1).default('origin'),
    branch: z.string().min(1).default('main'),
  }),
  payload: z.object({
    revision: z.string().min(1).default('HEAD'),
    transport: z.enum(['relay', 'bundle']).default('relay'),
  }),
});

const npmInstallPackageRequestSchema = requestEnvelopeSchema.extend({
  type: z.literal('npm_install_package'),
  scope: z.enum(['project', 'user']),
  target: z.object({
    projectPath: z.string().min(1),
    packageManager: z.literal('npm').default('npm'),
  }),
  payload: z.object({
    packages: z.array(z.string().min(1)).min(1),
    dev: z.boolean().default(false),
    global: z.boolean().default(false),
  }),
});

const workspaceAnalysisRequestSchema = requestEnvelopeSchema.extend({
  type: z.literal('workspace_analysis'),
  scope: z.enum(['notes', 'workspace', 'repo']),
  target: z.object({
    path: z.string().min(1),
  }),
  payload: z.object({
    prompt: z.string().min(1),
    writeArtifacts: z.boolean().default(false),
  }),
});

export const companionRequestSchema = z.discriminatedUnion('type', [
  githubResearchRequestSchema,
  repoRelayPushRequestSchema,
  npmInstallPackageRequestSchema,
  workspaceAnalysisRequestSchema,
]);

export const approvalSummarySchema = z.object({
  action: z.string().min(1),
  cwd: z.string().min(1),
  sideEffects: z.array(z.string()).default([]),
});

export const riskDecisionSchema = z.object({
  requestId: z.string().min(1),
  type: requestTypeSchema,
  risk: riskLevelSchema,
  requiresApproval: z.boolean(),
  reasonCodes: z.array(z.string()).min(1),
  summary: approvalSummarySchema,
  decidedAt: z.string().datetime(),
});

export const approvalJobSchema = z.object({
  jobId: z.string().min(1),
  requestId: z.string().min(1),
  risk: riskLevelSchema,
  summary: approvalSummarySchema,
  requestedBy: z.string().min(1),
  nonce: z.string().min(1),
  ttlSeconds: z.number().int().positive(),
  createdAt: z.string().datetime(),
  expiresAt: z.string().datetime(),
  jobHash: z.string().min(1),
  approvalCommand: z.string().min(1),
  rejectCommand: z.string().min(1),
  status: z.enum(['pending', 'approved', 'rejected', 'expired']).default('pending'),
});

export const intakeResultSchema = z.object({
  requestId: z.string().min(1),
  status: z.enum([
    'ready_for_execution',
    'awaiting_approval',
    'rejected',
    'expired',
    'succeeded',
    'failed',
  ]),
  risk: riskLevelSchema,
  summary: z.string().min(1),
  approvalJobId: z.string().min(1).optional(),
  detail: z.string().optional(),
  artifactPath: z.string().min(1).optional(),
  updatedAt: z.string().datetime(),
});

export type CompanionRequest = z.infer<typeof companionRequestSchema>;
export type RiskDecision = z.infer<typeof riskDecisionSchema>;
export type ApprovalJob = z.infer<typeof approvalJobSchema>;
export type IntakeResult = z.infer<typeof intakeResultSchema>;
