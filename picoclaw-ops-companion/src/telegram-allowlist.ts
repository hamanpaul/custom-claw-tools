import { execFile } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import {
  chmod,
  copyFile,
  mkdir,
  readFile,
  rename,
  stat,
  unlink,
  writeFile,
} from 'node:fs/promises';
import { basename, dirname, join, resolve } from 'node:path';
import { promisify } from 'node:util';

import type { CliCommand } from './cli.js';
import type { AppConfig } from './config.js';

const execFileAsync = promisify(execFile);

const recommendedEntryFormat = 'telegram:<user-id>' as const;

const supportedEntryFormats = [
  'telegram:<user-id>',
  '<user-id>',
  '@username',
  '<user-id>|<username>',
] as const;

type JsonObject = Record<string, unknown>;

type TelegramAllowlistCliCommand = Extract<CliCommand, { name: 'telegram-allowlist' }>;

type LoadedPicoClawTelegramConfig = {
  document: JsonObject;
  telegramConfig: JsonObject;
  telegramEnabled: boolean;
  storedAllowFrom: string[];
  effectiveAllowFrom: string[];
  fileMode: number;
};

export type TelegramAllowlistResult = {
  action: TelegramAllowlistCliCommand['action'];
  configPath: string;
  gatewayService: string;
  telegramEnabled: boolean;
  recommendedEntryFormat: typeof recommendedEntryFormat;
  supportedEntryFormats: readonly string[];
  storedAllowFrom: string[];
  effectiveAllowFrom: string[];
  afterAllowFrom: string[];
  added: string[];
  removed: string[];
  changed: boolean;
  dryRun: boolean;
  backupPath: string | null;
  gatewayRestarted: boolean;
};

export async function processTelegramAllowlistCommand(
  config: AppConfig,
  command: TelegramAllowlistCliCommand,
): Promise<TelegramAllowlistResult> {
  const configPath = resolve(command.configPath ?? config.picoclawConfigFile);
  const loaded = await loadPicoClawTelegramConfig(configPath);
  const requestedEntries = normalizeRequestedEntries(command.entries, command.action);

  let afterAllowFrom = loaded.effectiveAllowFrom;

  if (command.action === 'add') {
    afterAllowFrom = appendUniqueEntries(loaded.effectiveAllowFrom, requestedEntries);
  } else if (command.action === 'remove') {
    const removeSet = new Set(requestedEntries);
    afterAllowFrom = loaded.effectiveAllowFrom.filter((entry) => !removeSet.has(entry));
  } else if (command.action === 'replace') {
    afterAllowFrom = requestedEntries;
  }

  if (
    command.action !== 'show' &&
    afterAllowFrom.length === 0 &&
    !command.allowEmpty
  ) {
    throw new Error(
      'telegram allow_from would become empty; rerun with --allow-empty to acknowledge open access',
    );
  }

  const changed = !arraysEqual(loaded.storedAllowFrom, afterAllowFrom);
  const added = afterAllowFrom.filter(
    (entry) => !loaded.effectiveAllowFrom.includes(entry),
  );
  const removed = loaded.effectiveAllowFrom.filter(
    (entry) => !afterAllowFrom.includes(entry),
  );

  let backupPath: string | null = null;
  let gatewayRestarted = false;

  if (command.action !== 'show' && changed && !command.dryRun) {
    loaded.telegramConfig.allow_from = afterAllowFrom;
    backupPath = await backupPicoClawConfig(configPath);
    await writePicoClawConfig(configPath, loaded.document, loaded.fileMode);

    if (command.restartGateway) {
      try {
        await restartGatewayService(config.picoclawGatewayService);
        gatewayRestarted = true;
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        throw new Error(
          `telegram allowlist updated at ${configPath}, but failed to restart ${config.picoclawGatewayService}: ${message}; backup: ${backupPath}`,
        );
      }
    }
  }

  return {
    action: command.action,
    configPath,
    gatewayService: config.picoclawGatewayService,
    telegramEnabled: loaded.telegramEnabled,
    recommendedEntryFormat,
    supportedEntryFormats,
    storedAllowFrom: loaded.storedAllowFrom,
    effectiveAllowFrom: loaded.effectiveAllowFrom,
    afterAllowFrom,
    added,
    removed,
    changed,
    dryRun: command.dryRun,
    backupPath,
    gatewayRestarted,
  };
}

async function loadPicoClawTelegramConfig(
  configPath: string,
): Promise<LoadedPicoClawTelegramConfig> {
  const configStat = await stat(configPath);

  if (!configStat.isFile()) {
    throw new Error(`PicoClaw config path is not a file: ${configPath}`);
  }

  const document = parseJsonObject(
    JSON.parse(await readFile(configPath, 'utf8')) as unknown,
    `PicoClaw config at ${configPath}`,
  );
  const channelsConfig = getOrCreateObject(
    document,
    'channels',
    `channels section in ${configPath}`,
  );
  const telegramConfig = getOrCreateObject(
    channelsConfig,
    'telegram',
    `channels.telegram section in ${configPath}`,
  );
  const storedAllowFrom = readStringArray(
    telegramConfig.allow_from,
    `${configPath} channels.telegram.allow_from`,
  );

  return {
    document,
    telegramConfig,
    telegramEnabled: readBoolean(telegramConfig.enabled),
    storedAllowFrom,
    effectiveAllowFrom: normalizeStoredEntries(storedAllowFrom),
    fileMode: configStat.mode & 0o777 ? configStat.mode & 0o777 : 0o600,
  };
}

function parseJsonObject(value: unknown, label: string): JsonObject {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error(`${label} must be a JSON object`);
  }

  return value as JsonObject;
}

function getOrCreateObject(
  parent: JsonObject,
  key: string,
  label: string,
): JsonObject {
  const existing = parent[key];

  if (existing === undefined) {
    const created: JsonObject = {};
    parent[key] = created;
    return created;
  }

  return parseJsonObject(existing, label);
}

function readStringArray(value: unknown, label: string): string[] {
  if (value === undefined) {
    return [];
  }

  if (!Array.isArray(value)) {
    throw new Error(`${label} must be an array of strings`);
  }

  return value.map((entry, index) => {
    if (typeof entry !== 'string') {
      throw new Error(`${label}[${index}] must be a string`);
    }

    return entry;
  });
}

function readBoolean(value: unknown): boolean {
  return typeof value === 'boolean' ? value : false;
}

function normalizeStoredEntries(entries: string[]): string[] {
  return dedupeEntries(entries.map((entry) => entry.trim()).filter((entry) => entry.length > 0));
}

function normalizeRequestedEntries(
  entries: string[],
  action: TelegramAllowlistCliCommand['action'],
): string[] {
  const normalized = dedupeEntries(
    entries.map((entry) => entry.trim()).filter((entry) => entry.length > 0),
  );

  if (entries.length > 0 && normalized.length === 0) {
    throw new Error('telegram allowlist entries cannot be empty');
  }

  if (action === 'add' || action === 'replace') {
    for (const entry of normalized) {
      if (!isSupportedTelegramAllowEntry(entry)) {
        throw new Error(
          `unsupported telegram allowlist entry: ${entry}; supported formats: ${supportedEntryFormats.join(', ')}`,
        );
      }
    }
  }

  return normalized;
}

function dedupeEntries(entries: string[]): string[] {
  const seen = new Set<string>();
  const deduped: string[] = [];

  for (const entry of entries) {
    if (seen.has(entry)) {
      continue;
    }

    seen.add(entry);
    deduped.push(entry);
  }

  return deduped;
}

function isSupportedTelegramAllowEntry(entry: string): boolean {
  return (
    /^telegram:-?\d+$/.test(entry) ||
    /^-?\d+$/.test(entry) ||
    /^@[^@\s]+$/.test(entry) ||
    /^-?\d+\|[^|\s]+$/.test(entry)
  );
}

function appendUniqueEntries(current: string[], requested: string[]): string[] {
  const next = [...current];
  const seen = new Set(current);

  for (const entry of requested) {
    if (seen.has(entry)) {
      continue;
    }

    seen.add(entry);
    next.push(entry);
  }

  return next;
}

function arraysEqual(left: string[], right: string[]): boolean {
  if (left.length !== right.length) {
    return false;
  }

  return left.every((value, index) => value === right[index]);
}

async function backupPicoClawConfig(configPath: string): Promise<string> {
  const backupDir = join(dirname(configPath), 'backups');
  await mkdir(backupDir, { recursive: true });
  await chmod(backupDir, 0o700);
  const backupPath = join(
    backupDir,
    `${basename(configPath)}.telegram-allowlist.${buildBackupTimestamp()}.bak`,
  );
  await copyFile(configPath, backupPath);
  await chmod(backupPath, 0o600);
  return backupPath;
}

function buildBackupTimestamp(): string {
  return new Date()
    .toISOString()
    .replaceAll('-', '')
    .replaceAll(':', '')
    .replaceAll('.', '');
}

async function writePicoClawConfig(
  configPath: string,
  document: JsonObject,
  fileMode: number,
): Promise<void> {
  const tempPath = `${configPath}.${process.pid}.${randomUUID()}.tmp`;

  try {
    await writeFile(tempPath, `${JSON.stringify(document, null, 2)}\n`, {
      encoding: 'utf8',
      mode: fileMode,
    });
    await chmod(tempPath, fileMode);
    await rename(tempPath, configPath);
    await chmod(configPath, fileMode);
  } catch (error) {
    await unlink(tempPath).catch(() => undefined);
    throw error;
  }
}

async function restartGatewayService(serviceName: string): Promise<void> {
  await execFileAsync('systemctl', ['--user', 'restart', serviceName]);
  const { stdout } = await execFileAsync('systemctl', ['--user', 'is-active', serviceName]);

  if (stdout.trim() !== 'active') {
    throw new Error(`${serviceName} is not active after restart`);
  }
}
