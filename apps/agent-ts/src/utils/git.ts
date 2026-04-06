import { simpleGit } from 'simple-git';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { logger } from './logger.js';

export async function cloneRepository(
  cloneUrl: string,
  ref: string,
): Promise<string> {
  const repoDir = await mkdtemp(join(tmpdir(), 'lumis-repo-'));
  const log = logger.child({ repoDir, ref });

  log.info({ event: 'clone_started' });
  const git = simpleGit();
  await git.clone(cloneUrl, repoDir, ['--depth', '1', '--branch', ref]);
  log.info({ event: 'clone_completed' });

  return repoDir;
}

export async function cleanupRepo(repoPath: string): Promise<void> {
  try {
    await rm(repoPath, { recursive: true, force: true });
  } catch {
    logger.warn({ event: 'cleanup_failed', repoPath });
  }
}
