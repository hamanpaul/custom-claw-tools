import { readFile } from 'node:fs/promises';

import { parseCliArgs } from './cli.js';
import { loadConfig } from './config.js';
import { buildLayout, ensureLayout } from './layout.js';
import { createLogger } from './logger.js';
import {
  processExecutionRequest,
  processIntakeRequest,
  processRelayDecision,
} from './operations.js';
import { startLoopbackServer } from './server.js';
import { buildTotpProvisioning, writeTotpSecretFile } from './totp.js';

async function main(): Promise<void> {
  const command = parseCliArgs(process.argv.slice(2));
  const config = loadConfig({
    skipTotpSecretResolution:
      command.name === 'totp' || command.name === 'totp-gen',
  });
  const logger = createLogger(config.logLevel);
  const layout = buildLayout(config);

  await ensureLayout(layout);

  if (command.name === 'bootstrap') {
    logger.log('info', 'runtime bootstrap complete', {
      projectRoot: config.projectRoot,
      workspaceRoot: config.workspaceRoot,
      notesRoot: config.notesRoot,
      opsRoot: layout.opsRoot,
      listenHost: config.listenHost,
      listenPort: config.listenPort,
      copilotModel: config.copilotModel ?? null,
      copilotCliPath: config.copilotCliPath ?? null,
      copilotCliUrl: config.copilotCliUrl ?? null,
      approvalTtlSeconds: config.approvalTtlSeconds,
      totpAccountName: config.totpAccountName,
      totpIssuer: config.totpIssuer,
      totpSecretFile: config.totpSecretFile,
    });
    return;
  }

  if (command.name === 'totp') {
    const provisioning = buildTotpProvisioning({
      secret: command.secret,
      issuer: command.issuer ?? config.totpIssuer,
      accountName: command.accountName ?? config.totpAccountName,
      recommendedSecretFilePath: config.totpSecretFile,
    });

    logger.log('info', 'totp provisioning material generated', {
      generatedSecret: provisioning.generatedSecret,
      issuer: provisioning.issuer,
      accountName: provisioning.accountName,
      preferredEnvVar: provisioning.preferredEnvVar,
      recommendedSecretFilePath: provisioning.recommendedSecretFilePath,
    });

    process.stdout.write(`${JSON.stringify(provisioning, null, 2)}\n`);
    return;
  }

  if (command.name === 'totp-gen') {
    const provisioning = buildTotpProvisioning({
      secret: command.secret,
      issuer: command.issuer ?? config.totpIssuer,
      accountName: command.accountName ?? config.totpAccountName,
      recommendedSecretFilePath: config.totpSecretFile,
    });
    const generated = await writeTotpSecretFile({
      provisioning,
      force: command.force,
    });

    logger.log('info', 'totp secret file written', {
      accountName: generated.accountName,
      issuer: generated.issuer,
      path: generated.secretFile.path,
      overwritten: generated.secretFile.overwritten,
      generatedSecret: generated.generatedSecret,
    });

    process.stdout.write(`${JSON.stringify(generated, null, 2)}\n`);
    return;
  }

  if (command.name === 'listen') {
    await startLoopbackServer(layout, config, logger, {
      host: command.host,
      port: command.port,
    });
    return;
  }

  if (command.name === 'intake') {
    const outcome = await processIntakeRequest(
      layout,
      config,
      JSON.parse(await readRequestSource(command.requestPath)),
    );

    logger.log('info', 'request intake complete', {
      requestId: outcome.requestId,
      type: outcome.type,
      risk: outcome.risk,
      requiresApproval: outcome.requiresApproval,
      approvalJobId: outcome.approvalJobId,
    });

    process.stdout.write(`${JSON.stringify(outcome, null, 2)}\n`);
    return;
  }

  if (command.name === 'execute') {
    const outcome = await processExecutionRequest(layout, config, command.requestId);

    logger.log('info', 'request execution complete', outcome);

    process.stdout.write(`${JSON.stringify(outcome, null, 2)}\n`);
    return;
  }

  const outcome = await processRelayDecision(layout, config, {
    sender: command.sender,
    text: command.text,
  });

  logger.log('info', 'relay decision processed', outcome);

  process.stdout.write(`${JSON.stringify(outcome, null, 2)}\n`);
}

async function readRequestSource(requestPath: string): Promise<string> {
  if (requestPath === '-') {
    const chunks: string[] = [];

    for await (const chunk of process.stdin) {
      chunks.push(typeof chunk === 'string' ? chunk : chunk.toString('utf8'));
    }

    return chunks.join('');
  }

  return readFile(requestPath, 'utf8');
}

main().catch((error: unknown) => {
  const message = error instanceof Error ? error.message : String(error);
  process.stderr.write(
    `${JSON.stringify({ ts: new Date().toISOString(), level: 'error', message })}\n`,
  );
  process.exitCode = 1;
});
