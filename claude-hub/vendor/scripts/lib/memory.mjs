// Where Claude Code keeps a project's auto memory, and reading its MEMORY.md index for a brief.
// Claude Code keys the dir on the project's git root: every character outside [A-Za-z0-9] in the
// path becomes '-' (/home/u/dev/x -> -home-u-dev-x, C:\Users\x -> C--Users-x).
import { existsSync, readFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { isAbsolute, join } from 'node:path';

export const INDEX_LINE_LIMIT = 200;
export const INDEX_BYTE_LIMIT = 25600;

export function claudeConfigDir(env = process.env) {
  return env.CLAUDE_CONFIG_DIR || join(env.HOME || env.USERPROFILE || homedir(), '.claude');
}

export function projectKey(p) {
  return p.replace(/[^A-Za-z0-9]/g, '-');
}

export function memoryDirFor(projectPath, env = process.env) {
  return join(claudeConfigDir(env), 'projects', projectKey(projectPath), 'memory');
}

// Non-empty index lines, capped, with relative topic links made absolute so a session in another
// directory can open them.
export function readIndex(dir, maxLines = 60) {
  const file = join(dir, 'MEMORY.md');
  if (!existsSync(file)) return null;
  const text = readFileSync(file, 'utf8');
  const all = text.split(/\r?\n/).filter((l) => l.trim());
  const abs = (line) => line.replace(/\]\(([^)\s]+\.md)\)/g, (m, target) =>
    (isAbsolute(target) || /^[a-z][a-z0-9+.-]*:/i.test(target) ? m : `](${join(dir, target)})`));
  const bytes = Buffer.byteLength(text);
  return {
    dir, total: all.length, bytes,
    overLimit: all.length > INDEX_LINE_LIMIT || bytes > INDEX_BYTE_LIMIT,
    truncated: all.length > maxLines,
    lines: all.slice(0, maxLines).map(abs),
  };
}
