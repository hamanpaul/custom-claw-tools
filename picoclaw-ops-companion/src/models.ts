import { z } from 'zod';

export const riskLevelSchema = z.enum(['low', 'medium', 'high']);
export const requestTypeSchema = z.enum([
  'github_research',
  'repo_relay_push',
  'npm_install_package',
  'workspace_analysis',
]);

export const companionRequestSchema = z.object({
  requestId: z.string().min(1),
  type: requestTypeSchema,
  scope: z.string().min(1),
  target: z.record(z.string(), z.unknown()).default({}),
  payload: z.record(z.string(), z.unknown()).default({}),
  requestedBy: z.string().min(1),
});

export const approvalSummarySchema = z.object({
  action: z.string().min(1),
  cwd: z.string().min(1),
  sideEffects: z.array(z.string()).default([]),
});

export const approvalJobSchema = z.object({
  jobId: z.string().min(1),
  requestId: z.string().min(1),
  risk: riskLevelSchema,
  summary: approvalSummarySchema,
  nonce: z.string().min(1),
  ttlSeconds: z.number().int().positive(),
  status: z.enum(['pending', 'approved', 'rejected', 'expired']).default('pending'),
});

export type CompanionRequest = z.infer<typeof companionRequestSchema>;
export type ApprovalJob = z.infer<typeof approvalJobSchema>;
