// The one place that knows where the hub config lives, what it may contain, and how a flag,
// an environment variable, the config and a default combine. Every script goes through here.
import { existsSync } from 'node:fs';
import { homedir, hostname } from 'node:os';
import { basename, dirname, join } from 'node:path';
import { fullPath, readJson } from './proc.mjs';

export class HubConfigError extends Error {
  constructor(code, message) {
    super(message);
    this.code = code;
  }
}

export const REAPER_DEFAULTS = Object.freeze({
  stateDir: null,
  graceMinutes: 30,
  idleHours: 2,
  handoffTimeoutMinutes: 10,
  maxHandoffs: 3,
  retryHours: 6,
  relayModel: 'haiku',
  everyMinutes: 15,
});
const TOP_KEYS = ['version', 'checkoutRoot', 'workspaceRoot', 'sessionPrefix', 'owner', 'repoMap',
  'noPrRepos', 'repoNotes', 'contextDirs', 'reaper'];
// vendored from june-hub (see claude-hub/vendor/VENDORED.md) and renamed for this project's own
// naming convention: claude-hub's startup.sh writes ~/.claude/claude-hub.json at container boot.
const SETUP_HINT = "claude-hub's startup.sh writes ~/.claude/claude-hub.json at container boot";

const home = (env) => env.HOME || env.USERPROFILE || homedir();
export const claudeDir = (env = process.env) => env.CLAUDE_CONFIG_DIR || join(home(env), '.claude');

export function configPath(env = process.env) {
  return env.CLAUDE_HUB_CONFIG || join(claudeDir(env), 'claude-hub.json');
}

// ~, $VAR, ${VAR} and %VAR%; an unknown variable is left as written.
export function expandPath(p, env = process.env) {
  if (typeof p !== 'string' || !p) return p;
  let s = p.replace(/^~(?=$|[\\/])/, home(env));
  s = s.replace(/\$\{([A-Za-z_][A-Za-z0-9_]*)\}/g, (m, v) => env[v] ?? m);
  s = s.replace(/\$([A-Za-z_][A-Za-z0-9_]*)/g, (m, v) => env[v] ?? m);
  s = s.replace(/%([A-Za-z_][A-Za-z0-9_]*)%/g, (m, v) => env[v] ?? m);
  return s;
}

export function validateConfig(c) {
  const p = [];
  if (!c || typeof c !== 'object' || Array.isArray(c)) return ['the config must be a JSON object'];
  for (const k of Object.keys(c)) if (!TOP_KEYS.includes(k)) p.push(`unknown key "${k}"`);
  if (c.version !== 1) p.push('"version" must be 1');
  if (typeof c.checkoutRoot !== 'string' || !c.checkoutRoot) p.push('"checkoutRoot" is required (a directory path)');
  for (const k of ['workspaceRoot', 'sessionPrefix', 'owner', 'repoMap']) {
    if (c[k] !== undefined && c[k] !== null && typeof c[k] !== 'string') p.push(`"${k}" must be a string or null`);
  }
  if (c.noPrRepos !== undefined
      && !(Array.isArray(c.noPrRepos) && c.noPrRepos.every((s) => typeof s === 'string' && /^[^/\s]+\/[^/\s]+$/.test(s)))) {
    p.push('"noPrRepos" must be a list of "owner/name" strings');
  }
  if (c.repoNotes !== undefined
      && (typeof c.repoNotes !== 'object' || c.repoNotes === null || Array.isArray(c.repoNotes)
          || !Object.values(c.repoNotes).every((v) => typeof v === 'string'))) {
    p.push('"repoNotes" must map "owner/name" to a string');
  }
  if (c.contextDirs !== undefined) {
    if (!Array.isArray(c.contextDirs)) p.push('"contextDirs" must be a list');
    else {
      c.contextDirs.forEach((d, i) => {
        for (const f of ['name', 'path', 'when']) {
          if (typeof d?.[f] !== 'string' || !d[f]) p.push(`contextDirs[${i}].${f} is required`);
        }
      });
    }
  }
  if (c.reaper !== undefined) {
    if (typeof c.reaper !== 'object' || c.reaper === null || Array.isArray(c.reaper)) p.push('"reaper" must be an object');
    else {
      for (const [k, v] of Object.entries(c.reaper)) {
        if (!(k in REAPER_DEFAULTS)) p.push(`unknown key "reaper.${k}"`);
        else if (k === 'stateDir' || k === 'relayModel') {
          if (v !== null && typeof v !== 'string') p.push(`"reaper.${k}" must be a string`);
        } else if (typeof v !== 'number' || !(v > 0)) p.push(`"reaper.${k}" must be a positive number`);
      }
    }
  }
  return p;
}

export function loadConfig({ env = process.env } = {}) {
  const path = configPath(env);
  if (!existsSync(path)) return { path, exists: false, config: null };
  const config = readJson(path);
  if (config === null) throw new HubConfigError('config_unreadable', `${path} is not valid JSON - fix it or ${SETUP_HINT}`);
  const problems = validateConfig(config);
  if (problems.length) throw new HubConfigError('config_invalid', `${path}: ${problems.join('; ')}`);
  return { path, exists: true, config };
}

// Durable and per machine, deliberately NOT under ~/.claude/jobs (that directory gets cleaned).
export function defaultStateDir(env = process.env, platform = process.platform) {
  if (platform === 'win32') return `${env.LOCALAPPDATA}\\session-reaper`;
  return join(env.XDG_STATE_HOME || join(home(env), '.local', 'state'), 'session-reaper');
}

// https / ssh:// / scp-style remotes -> {host, owner, name, slug}; a local path -> null.
export function parseRemote(url) {
  if (!url || typeof url !== 'string') return null;
  const u = url.trim();
  let m;
  if (/^[a-z][a-z0-9+.-]*:\/\//i.test(u)) m = u.match(/^[a-z][a-z0-9+.-]*:\/\/(?:[^@/]+@)?([^/:]+)(?::\d+)?\/(.+)$/i);
  else m = u.match(/^(?:[^@\s]+@)?([^:\s/\\]+):(?![\\/])(.+)$/);
  if (!m) return null;
  const [, host, path] = m;
  if (/^file$/i.test(host) || host.length === 1) return null;
  const parts = path.replace(/\/+$/, '').replace(/\.git$/i, '').split('/').filter(Boolean);
  if (parts.length < 2) return null;
  const [owner, name] = parts.slice(-2);
  return { host: host.toLowerCase(), owner, name, slug: `${owner}/${name}` };
}

export function inList(slug, list) {
  if (!slug) return false;
  const s = slug.toLowerCase();
  return (list || []).some((x) => x.toLowerCase() === s);
}

// What the hub service on this box calls itself ("pmvm-ghe" -> "pmvm"), else the hostname.
export function derivedMachine(checkoutRoot) {
  const svc = checkoutRoot ? readJson(join(checkoutRoot, '.claude-service.json')) : null;
  if (svc?.name) return String(svc.name).split('-')[0];
  const h = process.env.COMPUTERNAME || hostname();
  return h ? h.split('.')[0].toLowerCase() : 'local';
}

export function resolveSettings({ flags = {}, env = process.env } = {}) {
  const { path, exists, config } = loadConfig({ env });
  const c = config ?? {};
  const rootRaw = flags.root || env.SPINUP_ROOT || env.GHE_ROOT || c.checkoutRoot;
  if (!rootRaw) {
    throw new HubConfigError('config_missing',
      `no checkout root: ${path} does not exist and neither --root nor SPINUP_ROOT is set - ${SETUP_HINT}`);
  }
  const checkoutRoot = fullPath(expandPath(rootRaw, env));
  const workspaceRoot = c.workspaceRoot
    ? fullPath(expandPath(c.workspaceRoot, env))
    : join(dirname(checkoutRoot), `${basename(checkoutRoot)}-worktrees`);
  // An explicit prefix is the user's own label and is used verbatim (a glyph works);
  // only a derived one is bracketed.
  const explicit = flags.machine || env.SPINUP_MACHINE || c.sessionPrefix || '';
  const reaper = { ...REAPER_DEFAULTS, ...(c.reaper ?? {}) };
  reaper.stateDir = reaper.stateDir ? fullPath(expandPath(reaper.stateDir, env)) : defaultStateDir(env);
  return {
    configPath: path,
    configExists: exists,
    checkoutRoot,
    workspaceRoot,
    prefix: explicit || `[${derivedMachine(checkoutRoot)}]`,
    prefixExplicit: Boolean(explicit),
    owner: c.owner || 'the user',
    repoMap: fullPath(expandPath(c.repoMap || join(dirname(path), 'claude-hub', 'repos.md'), env)),
    noPrRepos: c.noPrRepos ?? [],
    repoNotes: c.repoNotes ?? {},
    contextDirs: (c.contextDirs ?? []).map((d) => ({ ...d, path: expandPath(d.path, env) })),
    reaper,
  };
}
