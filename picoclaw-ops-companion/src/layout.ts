import { mkdir } from 'node:fs/promises';
import { join } from 'node:path';

import type { AppConfig } from './config.js';

export type Layout = {
  opsRoot: string;
  requestsDir: string;
  approvalsDir: string;
  resultsDir: string;
  logsDir: string;
  stateDir: string;
};

export function buildLayout(config: AppConfig): Layout {
  const opsRoot = join(config.notesRoot, config.opsRootName);

  return {
    opsRoot,
    requestsDir: join(opsRoot, 'requests'),
    approvalsDir: join(opsRoot, 'approvals'),
    resultsDir: join(opsRoot, 'results'),
    logsDir: join(opsRoot, 'logs'),
    stateDir: join(opsRoot, 'state'),
  };
}

export async function ensureLayout(layout: Layout): Promise<void> {
  await Promise.all(
    Object.values(layout).map((dir) => mkdir(dir, { recursive: true })),
  );
}
