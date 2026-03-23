export type CliCommand =
  | {
      name: 'bootstrap';
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
    };

const usage = [
  'Usage:',
  '  picoclaw-ops-companion bootstrap',
  '  picoclaw-ops-companion intake --request <path|->',
  '  picoclaw-ops-companion execute --request-id <request-id>',
  '  picoclaw-ops-companion decision --sender <sender> --text "</approve ...>"',
].join('\n');

export function parseCliArgs(argv: string[]): CliCommand {
  if (argv.length === 0) {
    return { name: 'bootstrap' };
  }

  const [command, ...rest] = argv;

  if (command === 'bootstrap') {
    return { name: 'bootstrap' };
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

  throw new Error(`unknown command: ${command}\n${usage}`);
}
