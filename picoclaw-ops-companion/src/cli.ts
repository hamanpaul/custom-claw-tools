export type CliCommand =
  | {
      name: 'bootstrap';
    }
  | {
      name: 'listen';
      host?: string;
      port?: number;
    }
  | {
      name: 'totp';
      secret?: string;
      accountName?: string;
      issuer?: string;
    }
  | {
      name: 'totp-gen';
      secret?: string;
      accountName?: string;
      issuer?: string;
      force: boolean;
    }
  | {
      name: 'intake';
      requestPath: string;
    }
  | {
      name: 'execute';
      requestId: string;
    }
  | {
      name: 'decision';
      sender: string;
      text: string;
    }
  | {
      name: 'telegram-allowlist';
      action: 'show' | 'add' | 'remove' | 'replace';
      entries: string[];
      configPath?: string;
      restartGateway: boolean;
      dryRun: boolean;
      allowEmpty: boolean;
    };

const usage = [
  'Usage:',
  '  picoclaw-ops-companion bootstrap',
  '  picoclaw-ops-companion listen [--host <host>] [--port <port>]',
  '  picoclaw-ops-companion totp [--account-name <name>] [--issuer <issuer>] [--secret <base32>]',
  '  picoclaw-ops-companion totp-gen [--account-name <name>] [--issuer <issuer>] [--secret <base32>] [--force]',
  '  picoclaw-ops-companion intake --request <path|->',
  '  picoclaw-ops-companion execute --request-id <request-id>',
  '  picoclaw-ops-companion decision --sender <sender> --text "</approve ...>"',
  '  picoclaw-ops-companion telegram-allowlist show [--config <path>]',
  '  picoclaw-ops-companion telegram-allowlist add --entry <value> [--entry <value> ...] [--config <path>] [--dry-run] [--restart-gateway]',
  '  picoclaw-ops-companion telegram-allowlist remove --entry <value> [--entry <value> ...] [--config <path>] [--dry-run] [--restart-gateway] [--allow-empty]',
  '  picoclaw-ops-companion telegram-allowlist replace [--entry <value> ...] [--config <path>] [--allow-empty] [--dry-run] [--restart-gateway]',
].join('\n');

export function parseCliArgs(argv: string[]): CliCommand {
  if (argv.length === 0) {
    return { name: 'bootstrap' };
  }

  const [command, ...rest] = argv;

  if (command === 'bootstrap') {
    return { name: 'bootstrap' };
  }

  if (command === 'listen') {
    const hostFlagIndex = rest.indexOf('--host');
    const portFlagIndex = rest.indexOf('--port');

    return {
      name: 'listen',
      host: hostFlagIndex === -1 ? undefined : rest[hostFlagIndex + 1],
      port:
        portFlagIndex === -1
          ? undefined
          : parsePort(rest[portFlagIndex + 1], '--port'),
    };
  }

  if (command === 'totp') {
    const secretFlagIndex = rest.indexOf('--secret');
    const accountNameFlagIndex = rest.indexOf('--account-name');
    const issuerFlagIndex = rest.indexOf('--issuer');

    return {
      name: 'totp',
      secret: secretFlagIndex === -1 ? undefined : rest[secretFlagIndex + 1],
      accountName:
        accountNameFlagIndex === -1 ? undefined : rest[accountNameFlagIndex + 1],
      issuer: issuerFlagIndex === -1 ? undefined : rest[issuerFlagIndex + 1],
    };
  }

  if (command === 'totp-gen') {
    const secretFlagIndex = rest.indexOf('--secret');
    const accountNameFlagIndex = rest.indexOf('--account-name');
    const issuerFlagIndex = rest.indexOf('--issuer');

    return {
      name: 'totp-gen',
      secret: secretFlagIndex === -1 ? undefined : rest[secretFlagIndex + 1],
      accountName:
        accountNameFlagIndex === -1 ? undefined : rest[accountNameFlagIndex + 1],
      issuer: issuerFlagIndex === -1 ? undefined : rest[issuerFlagIndex + 1],
      force: rest.includes('--force'),
    };
  }

  if (command === 'intake') {
    const requestFlagIndex = rest.indexOf('--request');
    const requestPath = requestFlagIndex === -1 ? undefined : rest[requestFlagIndex + 1];

    if (requestPath === undefined) {
      throw new Error(`missing --request for intake command\n${usage}`);
    }

    return {
      name: 'intake',
      requestPath,
    };
  }

  if (command === 'execute') {
    const requestIdFlagIndex = rest.indexOf('--request-id');
    const requestId = requestIdFlagIndex === -1 ? undefined : rest[requestIdFlagIndex + 1];

    if (requestId === undefined) {
      throw new Error(`execute requires --request-id\n${usage}`);
    }

    return {
      name: 'execute',
      requestId,
    };
  }

  if (command === 'decision') {
    const senderFlagIndex = rest.indexOf('--sender');
    const textFlagIndex = rest.indexOf('--text');
    const sender = senderFlagIndex === -1 ? undefined : rest[senderFlagIndex + 1];
    const text = textFlagIndex === -1 ? undefined : rest[textFlagIndex + 1];

    if (sender === undefined || text === undefined) {
      throw new Error(`decision requires --sender and --text\n${usage}`);
    }

    return {
      name: 'decision',
      sender,
      text,
    };
  }

  if (command === 'telegram-allowlist') {
    const [action, ...actionArgs] = rest;

    if (
      action !== 'show' &&
      action !== 'add' &&
      action !== 'remove' &&
      action !== 'replace'
    ) {
      throw new Error(
        `telegram-allowlist requires one of: show, add, remove, replace\n${usage}`,
      );
    }

    const configPath = parseOptionalFlagValue(actionArgs, '--config');
    const entries = collectFlagValues(actionArgs, '--entry');
    const dryRun = actionArgs.includes('--dry-run');
    const restartGateway = actionArgs.includes('--restart-gateway');
    const allowEmpty = actionArgs.includes('--allow-empty');

    if ((action === 'add' || action === 'remove') && entries.length === 0) {
      throw new Error(`telegram-allowlist ${action} requires at least one --entry\n${usage}`);
    }

    if (action === 'replace' && entries.length === 0 && !allowEmpty) {
      throw new Error(
        'telegram-allowlist replace requires at least one --entry; pass --allow-empty to clear allow_from\n' +
          usage,
      );
    }

    if (action === 'show' && entries.length > 0) {
      throw new Error(`telegram-allowlist show does not accept --entry\n${usage}`);
    }

    return {
      name: 'telegram-allowlist',
      action,
      entries,
      configPath,
      restartGateway,
      dryRun,
      allowEmpty,
    };
  }

  throw new Error(`unknown command: ${command}\n${usage}`);
}

function parsePort(value: string | undefined, flagName: string): number {
  if (value === undefined) {
    throw new Error(`${flagName} requires a numeric value\n${usage}`);
  }

  const parsed = Number.parseInt(value, 10);

  if (!Number.isInteger(parsed) || parsed < 1 || parsed > 65535) {
    throw new Error(`${flagName} must be a valid TCP port\n${usage}`);
  }

  return parsed;
}

function parseOptionalFlagValue(argv: string[], flagName: string): string | undefined {
  const flagIndex = argv.indexOf(flagName);

  if (flagIndex === -1) {
    return undefined;
  }

  const value = argv[flagIndex + 1];

  if (value === undefined) {
    throw new Error(`${flagName} requires a value\n${usage}`);
  }

  return value;
}

function collectFlagValues(argv: string[], flagName: string): string[] {
  const values: string[] = [];

  for (let index = 0; index < argv.length; index += 1) {
    if (argv[index] !== flagName) {
      continue;
    }

    const value = argv[index + 1];

    if (value === undefined) {
      throw new Error(`${flagName} requires a value\n${usage}`);
    }

    values.push(value);
    index += 1;
  }

  return values;
}
