import { randomBytes } from 'node:crypto';

const BASE32_ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';

export type TotpProvisioning = {
  generatedSecret: boolean;
  secret: string;
  issuer: string;
  accountName: string;
  otpauthUri: string;
  recommendedSecretFilePath: string;
  preferredEnvVar: 'PAULCALW_SECRET';
  compatibleEnvVars: ['PAULCALW_SECRET', 'PICOCLAW_TOTP_SECRET'];
  manualEntry: {
    type: 'TOTP';
    algorithm: 'SHA1';
    digits: 6;
    periodSeconds: 30;
    issuer: string;
    accountName: string;
  };
};

export function buildTotpProvisioning(input: {
  secret?: string;
  issuer: string;
  accountName: string;
  recommendedSecretFilePath: string;
}): TotpProvisioning {
  const secret = input.secret
    ? normalizeBase32Secret(input.secret)
    : encodeBase32(randomBytes(20));

  validateBase32Secret(secret);

  const issuer = input.issuer.trim();
  const accountName = input.accountName.trim();

  if (issuer.length === 0) {
    throw new Error('issuer cannot be empty');
  }

  if (accountName.length === 0) {
    throw new Error('account name cannot be empty');
  }

  return {
    generatedSecret: input.secret === undefined,
    secret,
    issuer,
    accountName,
    otpauthUri: buildOtpAuthUri({
      issuer,
      accountName,
      secret,
    }),
    recommendedSecretFilePath: input.recommendedSecretFilePath,
    preferredEnvVar: 'PAULCALW_SECRET',
    compatibleEnvVars: ['PAULCALW_SECRET', 'PICOCLAW_TOTP_SECRET'],
    manualEntry: {
      type: 'TOTP',
      algorithm: 'SHA1',
      digits: 6,
      periodSeconds: 30,
      issuer,
      accountName,
    },
  };
}

function buildOtpAuthUri(input: {
  issuer: string;
  accountName: string;
  secret: string;
}): string {
  const label = `${input.issuer}:${input.accountName}`;
  const params = new URLSearchParams({
    secret: input.secret,
    issuer: input.issuer,
    algorithm: 'SHA1',
    digits: '6',
    period: '30',
  });

  return `otpauth://totp/${encodeURIComponent(label)}?${params.toString()}`;
}

function normalizeBase32Secret(secret: string): string {
  return secret.replace(/[\s-]+/g, '').replace(/=+$/g, '').toUpperCase();
}

function validateBase32Secret(secret: string): void {
  if (!/^[A-Z2-7]+$/.test(secret)) {
    throw new Error('base32 secret must contain only A-Z and 2-7');
  }

  const decoded = decodeBase32(secret);

  if (decoded.length < 16) {
    throw new Error(
      `base32 secret is too short; need at least 16 bytes after decode, got ${decoded.length}`,
    );
  }
}

function encodeBase32(bytes: Uint8Array): string {
  let buffer = 0;
  let bits = 0;
  let output = '';

  for (const byte of bytes) {
    buffer = (buffer << 8) | byte;
    bits += 8;

    while (bits >= 5) {
      output += BASE32_ALPHABET[(buffer >>> (bits - 5)) & 31];
      bits -= 5;
    }
  }

  if (bits > 0) {
    output += BASE32_ALPHABET[(buffer << (5 - bits)) & 31];
  }

  return output;
}

function decodeBase32(secret: string): Uint8Array {
  let buffer = 0;
  let bits = 0;
  const output: number[] = [];

  for (const character of secret) {
    const value = BASE32_ALPHABET.indexOf(character);

    if (value === -1) {
      throw new Error(`invalid base32 character: ${character}`);
    }

    buffer = (buffer << 5) | value;
    bits += 5;

    while (bits >= 8) {
      output.push((buffer >>> (bits - 8)) & 0xff);
      bits -= 8;
    }
  }

  return Uint8Array.from(output);
}
