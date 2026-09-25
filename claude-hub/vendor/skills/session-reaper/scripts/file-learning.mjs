#!/usr/bin/env node
// File one learning from a task session into a Claude Code auto-memory dir, after the user
// approved it in the close flow. Writes a new topic file (never overwrites one) and appends its
// line to the index. Run it BEFORE the close: the target names come from the workspace's
// .spinup.json, which the close deletes.
//
// Emits exactly one JSON object: learning-filed | learning-blocked
import { appendFileSync, existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { emit, fail, parseCli, readJson, run } from '../../../scripts/lib/proc.mjs';

const EV = 'learning-blocked';
const TYPES = ['feedback', 'project', 'reference', 'user'];
const { values: o } = parseCli(process.argv.slice(2), {
  event: EV,
  options: {
    workspace: { type: 'string', default: '' },
    target: { type: 'string', default: '' },
    dir: { type: 'string', default: '' },
    type: { type: 'string', default: '' },
    name: { type: 'string', default: '' },
    title: { type: 'string', default: '' },
    description: { type: 'string', default: '' },
    body: { type: 'string', default: '' },
    'body-file': { type: 'string', default: '' },
    index: { type: 'string', default: 'MEMORY.md' },
    commit: { type: 'boolean', default: false },
    'dry-run': { type: 'boolean', default: false },
  },
});

if (!TYPES.includes(o.type)) fail(EV, 'bad_args', `--type must be one of ${TYPES.join(', ')}`);
if (!/^[a-z0-9]+(-[a-z0-9]+)*$/.test(o.name)) fail(EV, 'bad_args', '--name must be kebab-case (a-z, 0-9, -)');
for (const k of ['title', 'description']) if (!o[k].trim()) fail(EV, 'bad_args', `--${k} is required`);
if (/[\r\n]/.test(o.title + o.description)) fail(EV, 'bad_args', '--title and --description must be one line');
const body = o['body-file'] ? readFileSync(o['body-file'], 'utf8') : o.body;
if (!body.trim()) fail(EV, 'bad_args', '--body or --body-file is required');
if (!/^(MEMORY|index_[A-Za-z0-9_-]+)\.md$/.test(o.index)) fail(EV, 'bad_args', '--index must be MEMORY.md or an index_<area>.md sub-index, never a topic file');

let dir = o.dir;
if (!dir) {
  if (!o.workspace || !o.target) fail(EV, 'bad_args', 'pass --dir, or --workspace and --target');
  const metaPath = join(o.workspace, '.spinup.json');
  if (!existsSync(metaPath)) {
    fail(EV, 'no_spinup_json', `${metaPath} is gone - file learnings before the close, or pass --dir`);
  }
  const meta = readJson(metaPath) ?? {};
  // memory_targets lists every repo and folder (0.2.0+); memory[] only those that had an index.
  const targets = { general: meta.own_memory, ...Object.fromEntries((meta.memory ?? []).map((m) => [m.name, m.dir])), ...(meta.memory_targets ?? {}) };
  targets.general = meta.own_memory; // a repo directory called "general" never shadows it
  dir = Object.hasOwn(targets, o.target) ? targets[o.target] : '';
  if (!dir) fail(EV, 'unknown_target', `'${o.target}' is not a target of this workspace; valid: ${Object.keys(targets).join(', ')}`);
}

const file = `${o.type}_${o.name.replace(/-/g, '_')}.md`;
const path = join(dir, file);
const index = join(dir, o.index);
if (existsSync(path)) fail(EV, 'exists', `${path} already exists - update it by hand or pick another --name`);

const content = `---\nname: ${o.name}\ndescription: ${o.description.trim()}\nmetadata:\n  type: ${o.type}\n---\n\n${body.trim()}\n`;
const line = `- [${o.title.trim()}](${file}) — ${o.description.trim()}\n`;
const warnings = [];
let committed = false;

if (!o['dry-run']) {
  mkdirSync(dir, { recursive: true });
  writeFileSync(path, content, { encoding: 'utf8', flag: 'wx' });
  const prev = existsSync(index) ? readFileSync(index, 'utf8') : '';
  appendFileSync(index, (prev && !prev.endsWith('\n') ? '\n' : '') + line, 'utf8');
  if (o.commit) {
    const top = run('git', ['-C', dir, 'rev-parse', '--show-toplevel']);
    if (!top.ok) warnings.push('not_committed: the memory dir is not in a git repo');
    else if (run('git', ['-C', dir, 'check-ignore', '-q', file]).ok) warnings.push('not_committed: the memory dir is gitignored');
    else {
      const add = run('git', ['-C', dir, 'add', '--', file, o.index]);
      const ci = add.ok && run('git', ['-C', dir, 'commit', '-q', '-m', `memory: ${o.name}`, '--', file, o.index]);
      committed = Boolean(ci && ci.ok);
      if (!committed) warnings.push(`not_committed: ${(ci || add).text}`);
    }
  }
}
const text = existsSync(index) ? readFileSync(index, 'utf8') : line;
const indexLines = text.split(/\r?\n/).filter((l) => l.trim()).length;
const indexBytes = Buffer.byteLength(text);
if (indexLines > 200 || indexBytes > 25600) warnings.push('index_over_limit');
else if (indexLines > 150 || indexBytes > 20480) warnings.push('index_near_limit');
emit({ event: 'learning-filed', dry_run: o['dry-run'], path, index, index_lines: indexLines, index_bytes: indexBytes, committed, warnings });
