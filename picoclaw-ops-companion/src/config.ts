import 'dotenv/config';
import { readFileSync, statSync } from 'node:fs';
import { homedir } from 'node:os';
import { resolve } from 'node:path';
import { join } from 'node:path';

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
  PICOCLAW_TOTP_SECRET_FILE: z.string().optional(),
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
  totpSecretFile: string;
  totpIssuer: string;
  totpAccountName: string;
};

export function loadConfig(): AppConfig {
  const env = envSchema.parse(process.env);
  const totpSecretFile = resolve(
    env.PICOCLAW_TOTP_SECRET_FILE ??
      join(homedir(), '.config', 'picoclaw-ops-companion', 'totp.secret'),
  );

  return {
    projectRoot: resolve(env.PICOCLAW_OPS_PROJECT_ROOT ?? process.cwd()),
    workspaceRoot: resolve(env.PICOCLAW_WORKSPACE_ROOT),
    notesRoot: resolve(env.PICOCLAW_NOTES_ROOT),
    opsRootName: env.PICOCLAW_OPS_ROOT_NAME,
    approvalTtlSeconds: env.PICOCLAW_APPROVAL_TTL_SECONDS,
    logLevel: env.PICOCLAW_LOG_LEVEL,
    totpSecret: resolveTotpSecret(env, totpSecretFile),
    totpSecretFile,
    totpIssuer: env.PICOCLAW_TOTP_ISSUER,
    totpAccountName: env.PICOCLAW_TOTP_ACCOUNT_NAME,
  };
}

function resolveTotpSecret(
  env: z.infer<typeof envSchema>,
  totpSecretFile: string,
): string | undefined {
  const inlineSecret = env.PAULCALW_SECRET ?? env.PICOCLAW_TOTP_SECRET;

  if (inlineSecret) {
    return inlineSecret;
  }

  try {
    const stat = statSync(totpSecretFile);

    if (!stat.isFile()) {
      throw new Error(`TOTP secret path is not a file: ${totpSecretFile}`);
    }

    if ((stat.mode & 0o077) !== 0) {
      throw new Error(
        `TOTP secret file must not be readable by group/others: ${totpSecretFile}`,
      );
    }

    const secret = readFileSync(totpSecretFile, 'utf8').trim();

    return secret.length > 0 ? secret : undefined;
  } catch (error) {
    if (
      error instanceof Error &&
      'code' in error &&
      (error as NodeJS.ErrnoException).code === 'ENOENT'
    ) {
      return undefined;
    }

    throw error;
  }
}
