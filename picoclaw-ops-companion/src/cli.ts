export type CliCommand =
  | {
      name: 'bootstrap';
    }
  | {
      name: 'intake';
      requestPath: string;
    };

const usage = [
  'Usage:',
  '  picoclaw-ops-companion bootstrap',
  '  picoclaw-ops-companion intake --request <path|->',
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

  throw new Error(`unknown command: ${command}\n${usage}`);
}
