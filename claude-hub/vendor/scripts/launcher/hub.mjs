#!/usr/bin/env node
// claude-hub launcher (vendored from june-hub, see claude-hub/vendor/VENDORED.md). Installed to
// ~/.claude/claude-hub/hub.mjs the first time session-reaper.mjs runs, outside the versioned
// vendor mount, so a ledger-suggested command or a schedule can call one path that survives a
// re-vendor. It finds the newest installed copy and runs the requested script with the same
// node, passing arguments and exit code through.
//
//   node ~/.claude/claude-hub/hub.mjs <spinup|reaper|setup|schedule|learn> [args...]
//
// Self-contained on purpose: it must work when the vendor mount it was copied from is gone.
import { spawnSync } from 'node:child_process';
import { existsSync, readdirSync } from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';

const RECORDED = null; // replaced with the installing plugin's root at install time

const SCRIPTS = {
  spinup: ['skills', 'spinup-session', 'scripts', 'spinup-session.mjs'],
  reaper: ['skills', 'session-reaper', 'scripts', 'session-reaper.mjs'],
  setup: ['skills', 'hub-setup', 'scripts', 'hub-setup.mjs'],
  schedule: ['skills', 'session-reaper', 'scripts', 'install-schedule.mjs'],
  learn: ['skills', 'session-reaper', 'scripts', 'file-learning.mjs'],
};

function out(obj, code) {
  process.stdout.write(`${JSON.stringify(obj, null, 2)}\n`);
  process.exit(code);
}

const [cmd, ...args] = process.argv.slice(2);
if (!SCRIPTS[cmd]) {
  out({ event: 'launcher-blocked', error: 'bad_args', message: `usage: hub.mjs <${Object.keys(SCRIPTS).join('|')}> [args...]` }, 1);
}
const rel = SCRIPTS[cmd];

// Highest version wins, never the first glob hit: the cache keeps old versions side by side.
const semver = (v) => v.split(/[.-]/).slice(0, 3).map((n) => Number.parseInt(n, 10) || 0);
function newer(a, b) {
  const x = semver(a);
  const y = semver(b);
  for (let i = 0; i < 3; i++) if (x[i] !== y[i]) return x[i] > y[i];
  return false;
}
const dirs = (p) => { try { return readdirSync(p, { withFileTypes: true }).filter((d) => d.isDirectory()).map((d) => d.name); } catch { return []; } };

function candidates() {
  const home = process.env.HOME || process.env.USERPROFILE || homedir();
  const roots = [
    join(process.env.CLAUDE_CONFIG_DIR || join(home, '.claude'), 'plugins', 'cache'),
    join(process.env.CODEX_HOME || join(home, '.codex'), 'plugins', 'cache'),
  ];
  let best = null;
  for (const root of roots) {
    for (const marketplace of dirs(root)) {
      const base = join(root, marketplace, 'claude-hub');
      for (const version of dirs(base)) {
        const dir = join(base, version);
        if (existsSync(join(dir, ...rel)) && (!best || newer(version, best.version))) best = { dir, version };
      }
    }
  }
  return best?.dir ?? null;
}

const explicit = process.env.CLAUDE_HUB_VENDOR_ROOT;
const pluginRoot = (explicit && existsSync(join(explicit, ...rel)) ? explicit : null)
  ?? candidates()
  ?? (RECORDED && existsSync(join(RECORDED, ...rel)) ? RECORDED : null);
if (!pluginRoot) {
  out({ event: 'launcher-blocked', error: 'vendor_missing',
    message: 'no claude-hub vendor scripts found - check the /opt/vendor mount and CLAUDE_HUB_VENDOR_ROOT in docker-compose.yml' }, 1);
}
const r = spawnSync(process.execPath, [join(pluginRoot, ...rel), ...args], { stdio: 'inherit' });
process.exit(r.status ?? 1);
