import express from 'express';
import { config } from './config.js';
import { logger } from './utils/logger.js';
import { runAnalysis } from './graph/index.js';
import type { AnalysisRequest } from './graph/types.js';

const app = express();
app.use(express.json({ limit: '50mb' }));

app.get('/health', (_req, res) => {
  res.json({ status: 'ok', service: 'lumis-agent-ts' });
});

app.post('/analyze', async (req, res) => {
  const request = req.body as AnalysisRequest;
  const log = logger.child({ jobId: request.jobId, tenantId: request.tenantId });

  log.info({ event: 'analysis_request_received', analysisType: request.analysisType });

  try {
    const result = await runAnalysis(request);
    log.info({
      event: 'analysis_completed',
      findingsCount: result.findings.length,
      scoreGlobal: result.scores.global,
    });
    res.json(result);
  } catch (err) {
    log.error({ event: 'analysis_failed', error: (err as Error).message });
    res.status(500).json({ error: (err as Error).message });
  }
});

app.listen(config.port, () => {
  logger.info({ event: 'server_started', port: config.port, env: config.nodeEnv });
});
