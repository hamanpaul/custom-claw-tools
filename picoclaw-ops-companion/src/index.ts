import { loadConfig } from './config.js';
import { buildLayout, ensureLayout } from './layout.js';
import { createLogger } from './logger.js';

async function main(): Promise<void> {
  const config = loadConfig();
  const logger = createLogger(config.logLevel);
  const layout = buildLayout(config);

  await ensureLayout(layout);

  logger.log('info', 'runtime bootstrap complete', {
    projectRoot: config.projectRoot,
    workspaceRoot: config.workspaceRoot,
    notesRoot: config.notesRoot,
    opsRoot: layout.opsRoot,
    approvalTtlSeconds: config.approvalTtlSeconds,
    totpIssuer: config.totpIssuer,
  });
}

main().catch((error: unknown) => {
  const message = error instanceof Error ? error.message : String(error);
  console.error(JSON.stringify({ ts: new Date().toISOString(), level: 'error', message }));
  process.exitCode = 1;
});
