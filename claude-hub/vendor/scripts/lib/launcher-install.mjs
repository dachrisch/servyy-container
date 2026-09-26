// Installs the stable launcher (scripts/launcher/hub.mjs) next to the config - ~/.claude/claude-hub/hub.mjs
// by default - recording this plugin's root as the fallback it runs when no cached version is found.
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { configPath } from './hub-config.mjs';

export const PLUGIN_ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');

export function launcherPath(env = process.env) {
  return join(dirname(configPath(env)), 'claude-hub', 'hub.mjs');
}

export function installLauncher({ dryRun = false, env = process.env } = {}) {
  const path = launcherPath(env);
  const recorded = join(PLUGIN_ROOT);
  if (!dryRun) {
    const src = readFileSync(join(PLUGIN_ROOT, 'scripts', 'launcher', 'hub.mjs'), 'utf8')
      .replace('const RECORDED = null;', `const RECORDED = ${JSON.stringify(recorded)};`);
    mkdirSync(dirname(path), { recursive: true });
    writeFileSync(path, src, 'utf8');
  }
  return { path, recorded };
}
