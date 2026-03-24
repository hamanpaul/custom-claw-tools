import 'dotenv/config';
import { resolve } from 'node:path';

import { z } from 'zod';

const envSchema = z.object({
  PICOCLAW_OPS_PROJECT_ROOT: z.string().optional(),
  PICOCLAW_WORKSPACE_ROOT: z.string().default('/home/haman/.picoclaw/workspace'),
  PICOCLAW_NOTES_ROOT: z.string().default('/home/haman/.picoclaw/workspace/notes'),
  PICOCLAW_OPS_ROOT_NAME: z.string().default('ops-companion'),
  PICOCLAW_APPROVAL_TTL_SECONDS: z.coerce.number().int().positive().default(300),
  PICOCLAW_LOG_LEVEL: z.enum(['debug', 'info', 'warn', 'error']).default('info'),
  PICOCLAW_TOTP_SECRET: z.string().min(1).optional(),
  PAULCALW_SECRET: z.string().min(1).optional(),
  PICOCLAW_TOTP_ISSUER: z.string().default('PicoClaw Ops Companion'),
  PICOCLAW_TOTP_ACCOUNT_NAME: z.string().default('picoclaw-ops-companion'),
});

export type AppConfig = {
  projectRoot: string;
  workspaceRoot: string;
  notesRoot: string;
  opsRootName: string;
  approvalTtlSeconds: number;
  logLevel: 'debug' | 'info' | 'warn' | 'error';
  totpSecret?: string;
  totpIssuer: string;
  totpAccountName: string;
};

export function loadConfig(): AppConfig {
  const env = envSchema.parse(process.env);

  return {
    projectRoot: resolve(env.PICOCLAW_OPS_PROJECT_ROOT ?? process.cwd()),
    workspaceRoot: resolve(env.PICOCLAW_WORKSPACE_ROOT),
    notesRoot: resolve(env.PICOCLAW_NOTES_ROOT),
    opsRootName: env.PICOCLAW_OPS_ROOT_NAME,
    approvalTtlSeconds: env.PICOCLAW_APPROVAL_TTL_SECONDS,
    logLevel: env.PICOCLAW_LOG_LEVEL,
    totpSecret: env.PAULCALW_SECRET ?? env.PICOCLAW_TOTP_SECRET,
    totpIssuer: env.PICOCLAW_TOTP_ISSUER,
    totpAccountName: env.PICOCLAW_TOTP_ACCOUNT_NAME,
  };
}
