import pino from 'pino';
import { config } from '../config.js';

export const logger = pino({
  level: config.logLevel,
  ...(config.isProduction
    ? {}
    : { transport: { target: 'pino-pretty', options: { colorize: true } } }),
  base: { service: 'agent-ts' },
  timestamp: pino.stdTimeFunctions.isoTime,
  formatters: {
    level(label) {
      return { level: label };
    },
  },
});
