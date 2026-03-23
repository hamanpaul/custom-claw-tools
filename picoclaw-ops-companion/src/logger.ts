export type LogLevel = 'debug' | 'info' | 'warn' | 'error';

const levelOrder: Record<LogLevel, number> = {
  debug: 10,
  info: 20,
  warn: 30,
  error: 40,
};

export function createLogger(level: LogLevel) {
  const threshold = levelOrder[level];

  return {
    log(messageLevel: LogLevel, message: string, meta?: Record<string, unknown>) {
      if (levelOrder[messageLevel] < threshold) {
        return;
      }

      const payload = {
        ts: new Date().toISOString(),
        level: messageLevel,
        message,
        ...(meta ? { meta } : {}),
      };

      process.stderr.write(`${JSON.stringify(payload)}\n`);
    },
  };
}
