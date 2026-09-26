// Process, path and output helpers shared by every claude-hub vendored script. No dependencies.
import { spawnSync } from 'node:child_process';
import { appendFileSync, existsSync, mkdirSync, readFileSync, statSync, writeFileSync } from 'node:fs';
import { delimiter, dirname, join, posix, resolve as resolvePath, win32 } from 'node:path';
import { parseArgs } from 'node:util';

export function emit(obj) {
  process.stdout.write(`${JSON.stringify(obj, null, 2)}\n`);
}

export function fail(event, code, message, extra = {}) {
  emit({ event, error: code, message, ...extra });
  process.exit(1);
}

// CLAUDE_HUB_FAST=1 (tests only) shrinks every wait; it never changes a decision.
const FAST = process.env.CLAUDE_HUB_FAST === '1';
export const pollInterval = (ms) => (FAST ? Math.max(10, Math.round(ms / 200)) : ms);
export function sleepMs(ms) {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, pollInterval(ms));
}

// On Windows only names carrying a PATHEXT extension count: npm drops an extensionless sh shim
// next to claude.cmd, and spawning that file fails.
export function which(cmd, extraCandidates = [], { platform = process.platform, path = process.env.PATH, pathext = process.env.PATHEXT } = {}) {
  const win = platform === 'win32';
  const exts = win ? (pathext || '.COM;.EXE;.BAT;.CMD').split(';').filter(Boolean).map((e) => e.toLowerCase()) : [''];
  for (const dir of (path || '').split(win ? ';' : delimiter).filter(Boolean)) {
    for (const ext of exts) {
      const p = join(dir, cmd + ext);
      try { if (statSync(p).isFile()) return p; } catch { /* next */ }
    }
  }
  return extraCandidates.find((p) => p && existsSync(p)) ?? null;
}

// How to spawn a resolved command without a shell. An npm .cmd shim is read for the script it
// wraps and run with this node directly: cmd.exe would cut a multi-line argument at the first
// newline and expand %VAR% even inside quotes. Any other .cmd/.bat needs cmd.exe.
export function resolveCommand(file, platform = process.platform) {
  if (platform === 'win32' && /\.(cmd|bat)$/i.test(file)) {
    let text = '';
    try { text = readFileSync(file, 'utf8'); } catch { /* unreadable: fall back to the shell */ }
    const m = text.match(/"%dp0%\\([^"]+\.[cm]?js)"/i);
    if (m) {
      const lib = file.includes('\\') ? win32 : posix;
      const script = lib.join(lib.dirname(file), m[1].replace(/\\/g, lib.sep));
      if (existsSync(script)) return { file: process.execPath, prefix: [script], shell: false };
    }
    return { file, prefix: [], shell: true };
  }
  return { file, prefix: [], shell: false };
}

// Arguments are passed as an array, never through a shell, so spaces, umlauts, emoji and newlines
// survive. The one exception is a non-npm Windows .cmd/.bat, which only cmd.exe can run; an
// argument cmd.exe would mangle (a newline, a %) is refused there rather than silently cut.
export function run(cmd, args = [], { cwd, input, env } = {}) {
  const rc = resolveCommand(cmd);
  const opts = { cwd, input, env, encoding: 'utf8', windowsHide: true, maxBuffer: 64 * 1024 * 1024 };
  let r;
  if (rc.shell) {
    if (args.some((a) => /[\r\n%]/.test(a))) {
      return { ok: false, code: -1, stdout: '', text: `${cmd} can only run through cmd.exe, which cannot pass a multi-line or %-containing argument - install the native claude (claude.exe) instead` };
    }
    const quote = (a) => (/[\s"&|<>^]/.test(a) ? `"${a.replace(/"/g, '""')}"` : a);
    r = spawnSync([quote(cmd), ...args.map(quote)].join(' '), { ...opts, shell: true });
  } else {
    r = spawnSync(rc.file, [...rc.prefix, ...args], opts);
  }
  if (r.error) return { ok: false, code: -1, stdout: '', text: String(r.error.message) };
  const out = (r.stdout ?? '').trim();
  const err = (r.stderr ?? '').trim();
  return { ok: r.status === 0, code: r.status ?? -1, stdout: out, text: [out, err].filter(Boolean).join('\n') };
}

export function fullPath(p, platform = process.platform) {
  if (!p) return '';
  const lib = platform === 'win32' ? win32 : posix;
  let s = platform === 'win32' ? p.replace(/\//g, '\\') : p;
  s = platform === process.platform ? resolvePath(s) : lib.resolve(s);
  const root = lib.parse(s).root;
  while (s.length > root.length && /[\\/]$/.test(s)) s = s.slice(0, -1);
  return s;
}

export function samePath(a, b, platform = process.platform) {
  if (!a || !b) return false;
  const x = fullPath(a, platform);
  const y = fullPath(b, platform);
  return platform === 'win32' ? x.toLowerCase() === y.toLowerCase() : x === y;
}

// UTF-8, BOM tolerated (Windows Notepad writes one), null on any error.
export function readJson(path) {
  try { return JSON.parse(readFileSync(path, 'utf8').replace(/^﻿/, '')); } catch { return null; }
}

export function writeJson(path, obj) {
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, `${JSON.stringify(obj, null, 2)}\n`, 'utf8');
}

export function appendLine(path, line) {
  mkdirSync(dirname(path), { recursive: true });
  appendFileSync(path, `${line}\n`, 'utf8');
}

export function formatTable(rows, cols) {
  const cell = (v) => (v === null || v === undefined ? '' : String(v)).replace(/\s+/g, ' ');
  const width = cols.map((c) => Math.max(c.length, ...rows.map((r) => cell(r[c]).length)));
  const line = (vals) => vals.map((v, i) => (i === vals.length - 1 ? v : v.padEnd(width[i]))).join('  ');
  return [line(cols), line(width.map((w) => '-'.repeat(w))), ...rows.map((r) => line(cols.map((c) => cell(r[c]))))].join('\n');
}

export function parseCli(argv, { event, options, allowPositionals = false }) {
  try {
    return parseArgs({ args: argv, options, strict: true, allowPositionals });
  } catch (e) {
    return fail(event, 'bad_args', e.message);
  }
}
