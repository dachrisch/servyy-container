#!/usr/bin/env node
// Create a per-task workspace of git worktrees and start a Remote Control Claude session on it.
//
//   <workspaceRoot>/<slug>/<repo>   one worktree per repo the task needs
//
// One task -> one directory -> one background session named "<prefix> <ticket> <desc>".
// Everything here is deterministic - where the workspace goes, the branch, the base, the session
// name, what the child session is told. Deciding WHICH repos a task needs is the skill's job;
// they come in with --repos. Validation happens before any mutation: if one repo cannot get its
// worktree, nothing is created and nothing is started.
//
// Emits exactly one JSON object on stdout:
//   session-ready | session-exists | workspace-ready | spinup-planned | spinup-blocked
import { existsSync, mkdirSync, readFileSync, realpathSync, statSync, writeFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { join, sep } from 'node:path';
import { HubConfigError, inList, parseRemote, resolveSettings } from '../../../scripts/lib/hub-config.mjs';
import { memoryDirFor, readIndex } from '../../../scripts/lib/memory.mjs';
import { emit, fail, fullPath, parseCli, run, samePath, sleepMs, which, writeJson } from '../../../scripts/lib/proc.mjs';

const EV = 'spinup-blocked';
const PERMISSION_MODES = ['', 'acceptEdits', 'auto', 'bypassPermissions', 'manual', 'dontAsk', 'plan'];
// Spun-up sessions already sit in a worktree; see `isolated` below for why the tool is denied.
const NO_ENTER_WORKTREE = '--disallowedTools=EnterWorktree';
const { values: o } = parseCli(process.argv.slice(2), {
  event: EV,
  options: {
    desc: { type: 'string', default: '' },
    repos: { type: 'string', default: '' },
    ticket: { type: 'string', default: '' },
    task: { type: 'string', default: '' },
    'task-file': { type: 'string', default: '' },
    'memory-from': { type: 'string', default: '' },
    branch: { type: 'string', default: '' },
    base: { type: 'string', default: '' },
    root: { type: 'string', default: '' },
    machine: { type: 'string', default: '' },
    'permission-mode': { type: 'string', default: '' },
    model: { type: 'string', default: '' },
    'no-fetch': { type: 'boolean', default: false },
    'no-start': { type: 'boolean', default: false },
    'dry-run': { type: 'boolean', default: false },
  },
});
if (!PERMISSION_MODES.includes(o['permission-mode'])) {
  fail(EV, 'bad_args', `--permission-mode must be one of ${PERMISSION_MODES.filter(Boolean).join(', ')}`);
}
const dryRun = o['dry-run'];

// ---------------------------------------------------------------- small helpers

function slugify(text, max = 48) {
  let s = text.toLowerCase()
    .replace(/[ä]/g, 'ae').replace(/[ö]/g, 'oe').replace(/[ü]/g, 'ue').replace(/ß/g, 'ss')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
  if (s.length > max) {
    s = s.slice(0, max);
    const cut = s.lastIndexOf('-');
    if (cut >= 12) s = s.slice(0, cut);
    s = s.replace(/^-+|-+$/g, '');
  }
  return s;
}

const git = (...a) => run('git', a);

function worktreeList(repoRoot) {
  const r = git('-C', repoRoot, 'worktree', 'list', '--porcelain');
  if (!r.ok) return [];
  const entries = [];
  let cur = null;
  for (const line of r.text.split(/\r?\n/)) {
    if (line.startsWith('worktree ')) {
      if (cur) entries.push(cur);
      cur = { path: fullPath(line.slice(9)), branch: '', detached: false };
    } else if (line.startsWith('branch ') && cur) cur.branch = line.slice(7).replace(/^refs\/heads\//, '');
    else if (line === 'detached' && cur) cur.detached = true;
  }
  if (cur) entries.push(cur);
  return entries;
}

function defaultBranch(repoRoot) {
  const head = () => {
    const r = git('-C', repoRoot, 'symbolic-ref', '--quiet', 'refs/remotes/origin/HEAD');
    return r.ok ? r.text.replace(/^refs\/remotes\/origin\//, '').trim() : '';
  };
  let b = head();
  if (!b) {
    git('-C', repoRoot, 'remote', 'set-head', 'origin', '--auto');
    b = head();
  }
  if (!b) {
    for (const cand of ['main', 'master']) {
      if (git('-C', repoRoot, 'rev-parse', '--verify', '--quiet', `refs/remotes/origin/${cand}`).ok) return cand;
    }
  }
  return b;
}

// Read the configured URL, never `git remote get-url`: that expands insteadOf rewrites and would
// report the rewritten address instead of the remote the user actually configured.
function remoteSlug(repoRoot) {
  const r = git('-C', repoRoot, 'config', '--get', 'remote.origin.url');
  return r.ok ? parseRemote(r.text)?.slug ?? null : null;
}

const claudeExe = which('claude', [join(homedir(), '.local', 'bin', 'claude'), join(homedir(), '.local', 'bin', 'claude.exe')]);
function claudeAgents() {
  const r = run(claudeExe, ['agents', '--json']);
  if (!r.ok) return [];
  try { return JSON.parse(r.text); } catch { return []; }
}
const findSessionForPath = (p) => claudeAgents().find((a) => a.cwd && samePath(a.cwd, p));

// ---------------------------------------------------------------- inputs

for (const [tool, found] of [['git', which('git')], ['claude', claudeExe]]) {
  if (!found) fail(EV, 'tool_missing', `${tool} is required but not on PATH`);
}
if (!o.desc.trim()) fail(EV, 'desc_missing', '--desc is required (2 to 5 words)');
if (!o.repos.trim()) fail(EV, 'repos_missing', '--repos is required (directory names under the checkout root)');

let s;
try {
  s = resolveSettings({ flags: { root: o.root, machine: o.machine } });
} catch (e) {
  if (e instanceof HubConfigError) fail(EV, e.code, e.message);
  throw e;
}
if (!existsSync(s.checkoutRoot)) {
  fail(EV, 'ghe_root_missing', `checkout root not found at ${s.checkoutRoot} - fix checkoutRoot in ${s.configPath} or pass --root`);
}

const repoList = o.repos.split(/[,;\s]+/).map((r) => r.trim()).filter(Boolean);

// Folders outside git whose auto memory should brief the session: "name=path;name=path".
const memoryFrom = [];
for (const part of o['memory-from'].split(';').map((x) => x.trim()).filter(Boolean)) {
  const eq = part.indexOf('=');
  if (eq < 1) fail(EV, 'bad_args', `--memory-from wants name=path, got '${part}'`);
  const name = part.slice(0, eq).trim();
  if (name === 'general' || repoList.includes(name) || memoryFrom.some((m) => m.name === name)) {
    fail(EV, 'bad_args', `--memory-from name '${name}' is reserved or already used - pick another`);
  }
  const given = fullPath(part.slice(eq + 1).trim());
  // Claude Code keys memory on the real path, so resolve links the way it does.
  let source = given;
  try { source = fullPath(realpathSync(given)); } catch { /* missing: warned below */ }
  memoryFrom.push({ name, source, exists: existsSync(given) && statSync(given).isDirectory() });
}
let task = o.task;
if (o['task-file']) {
  if (!existsSync(o['task-file'])) fail(EV, 'task_file_missing', `--task-file ${o['task-file']} does not exist`);
  task = readFileSync(o['task-file'], 'utf8');
}

const descClean = o.desc.replace(/\s+/g, ' ').trim();
const ticketClean = o.ticket.trim();
const nameTail = [ticketClean, descClean].filter(Boolean).join(' ');
const sessionName = `${s.prefix} ${nameTail}`;
const slug = ticketClean ? `${slugify(ticketClean, 24)}-${slugify(descClean, 40)}` : slugify(descClean, 52);
if (!slug) fail(EV, 'bad_slug', `cannot build a directory name from '${o.desc}'`);
const workspace = fullPath(join(s.workspaceRoot, slug));
const branchName = o.branch.trim() || `claude/${slug}`;
const machine = s.prefixExplicit ? s.prefix : s.prefix.replace(/^\[|\]$/g, '');

// ---------------------------------------------------------------- plan (no mutation)

const plan = [];
const problems = [];
for (const repo of repoList) {
  const srcPath = join(s.checkoutRoot, repo);
  if (!existsSync(srcPath)) {
    problems.push({ repo, error: 'repo_missing', message: `no checkout at ${srcPath}` });
    continue;
  }
  const top = git('-C', srcPath, 'rev-parse', '--show-toplevel');
  if (!top.ok) {
    problems.push({ repo, error: 'not_a_repo', message: `${srcPath} is not a git repository` });
    continue;
  }
  // A junction or symlink resolves to its real checkout here, which is what the worktree must be
  // registered against. A linked worktree resolves to the main working tree.
  let repoRoot = fullPath(top.text);
  let worktrees = worktreeList(repoRoot);
  if (worktrees.length) {
    repoRoot = worktrees[0].path;
    worktrees = worktreeList(repoRoot);
  }
  let linked = false;
  try { linked = !samePath(realpathSync(srcPath), srcPath); } catch { /* keep false */ }

  if (!o['no-fetch'] && !dryRun) git('-C', repoRoot, 'fetch', 'origin', '--quiet');

  const defBranch = defaultBranch(repoRoot);
  if (!defBranch && !o.base) {
    problems.push({ repo, error: 'no_default_branch', message: `cannot resolve origin/HEAD for ${repoRoot} - pass --base` });
    continue;
  }
  const baseName = o.base || defBranch;
  let baseRef = baseName;
  if (!baseName.startsWith('origin/') && git('-C', repoRoot, 'rev-parse', '--verify', '--quiet', `refs/remotes/origin/${baseName}`).ok) {
    baseRef = `origin/${baseName}`;
  }
  if (!git('-C', repoRoot, 'rev-parse', '--verify', '--quiet', baseRef).ok) {
    problems.push({ repo, error: 'bad_base', message: `base '${baseName}' does not exist in ${repo} (resolved as '${baseRef}')` });
    continue;
  }

  const target = fullPath(join(workspace, repo));
  const existing = worktrees.find((w) => samePath(w.path, target));
  const branchLives = worktrees.find((w) => w.branch === branchName);
  const branchKnown = git('-C', repoRoot, 'rev-parse', '--verify', '--quiet', `refs/heads/${branchName}`).ok;
  const remote = remoteSlug(repoRoot);

  if (existing) {
    // Re-running for a task that already has its workspace is the normal case, not an error.
    plan.push({ repo, source: repoRoot, path: target, branch: existing.branch, base: baseRef,
      default_branch: defBranch, remote, linked, action: 'exists' });
    continue;
  }
  if (existsSync(target)) {
    problems.push({ repo, error: 'path_occupied', message: `${target} exists but git does not know it as a worktree - inspect it by hand` });
    continue;
  }
  if (branchLives) {
    problems.push({ repo, error: 'branch_in_use', message: `branch '${branchName}' is already checked out in ${branchLives.path} - pass a different --branch` });
    continue;
  }
  plan.push({ repo, source: repoRoot, path: target, branch: branchName, base: baseRef, default_branch: defBranch,
    remote, linked, action: branchKnown ? 'checkout-existing-branch' : 'create-branch' });
}

if (problems.length) {
  fail(EV, 'repo_problems', 'no worktree was created and no session was started', {
    workspace, session_name: sessionName, repos: plan, blocked: problems,
  });
}

const existingSession = findSessionForPath(workspace);

if (dryRun) {
  emit({
    event: 'spinup-planned', machine, ticket: ticketClean, desc: descClean, session_name: sessionName, slug,
    workspace, ghe_root: s.checkoutRoot, branch: branchName, repos: plan,
    existing_session: existingSession ? { id: existingSession.id, name: existingSession.name } : null,
  });
  process.exit(0);
}

// ---------------------------------------------------------------- build the workspace

mkdirSync(workspace, { recursive: true });

const created = [];
for (const p of plan) {
  const entry = { repo: p.repo, path: p.path, branch: p.branch, base: p.base, source: p.source, remote: p.remote, linked: p.linked };
  if (p.action !== 'exists') {
    const add = p.action === 'checkout-existing-branch'
      ? git('-C', p.source, 'worktree', 'add', p.path, p.branch)
      : git('-C', p.source, 'worktree', 'add', '-b', p.branch, p.path, p.base);
    if (!add.ok) {
      fail(EV, 'worktree_add_failed', `git worktree add failed for ${p.repo}: ${add.text}`, {
        workspace, created, failed_repo: p.repo,
      });
    }
  }
  entry.head = git('-C', p.path, 'rev-parse', '--short', 'HEAD').text;
  entry.status = p.action === 'exists' ? 'existed' : 'created';
  created.push(entry);
}

// The memory the session loads by itself: its git root's (the workspace may sit inside a repo,
// e.g. a dotfiles home), else the workspace's own. Copy the others' indexes into the brief.
const topWs = git('-C', workspace, 'rev-parse', '--show-toplevel');
const ownMemory = memoryDirFor(topWs.ok ? fullPath(topWs.text) : workspace);
const MEMORY_LINES = 60;
const memory = [];
// Every repo and folder is a place a learning can be filed, whether or not it has memory yet.
const memoryTargets = {};
const warnings = [];
for (const src of [...created.map((c) => ({ name: c.repo, source: c.source, exists: true })), ...memoryFrom]) {
  const dir = memoryDirFor(src.source);
  if (!src.exists) { warnings.push(`memory_from_missing: ${src.source}`); continue; }
  memoryTargets[src.name] = dir;
  if (samePath(dir, ownMemory) || memory.some((m) => samePath(m.dir, dir))) continue;
  const idx = readIndex(dir, MEMORY_LINES);
  if (idx) memory.push({ name: src.name, source: src.source, dir, lines: idx.lines, total: idx.total, truncated: idx.truncated, overLimit: idx.overLimit });
  else if (memoryFrom.includes(src)) warnings.push(`memory_from_empty: ${src.source}`);
}
warnings.push(...memory.filter((m) => m.overLimit).map((m) => `memory_index_over_limit: ${m.dir}`));
const memorySection = memory.length ? `
## Prior knowledge

Earlier sessions left notes (Claude Code auto memory) for the repos and folders this task touches.
Your own auto memory loads as usual; these do not, so their indexes are copied here. When a line
matches what you are doing, read its topic file before you start on that part.

${memory.map((m) => `### \`${m.name}\` memory (\`${m.dir}\`)

${m.lines.join('\n')}${m.truncated ? `\n(${m.total - m.lines.length} more lines: read \`${join(m.dir, 'MEMORY.md')}\`)` : ''}`).join('\n\n')}
` : '';

const title = nameTail;
const now = new Date();
const stamp = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')} `
  + `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`;
const brief = task.trim() || '_No brief was passed to spinup-session. Ask before assuming what this is about._';
const table = created.map((c) => `| \`${c.repo}\` | \`${c.branch}\` | \`${c.base}\` | \`${c.head}\` | \`${c.source}\` |`).join('\n');

// Background sessions are told to call EnterWorktree unless their cwd is under .claude/worktrees/.
// These worktrees are not, and EnterWorktree's approval prompt never reaches claude.ai/code, so
// the session hangs on it. The start command also denies the tool; this line says why.
const branchList = [...new Set(created.map((c) => `\`${c.branch}\``))].join(', ');
const isolated = `**You are already isolated.** Each repo directory here is a git worktree on its own branch (${branchList}), created by the hub for this task. Do not call \`EnterWorktree\`: its approval prompt cannot be answered from claude.ai/code and blocks the session. Edit and commit here directly.`;

const taskMd = `# ${title}

${isolated}

${brief}

## Workspace

| Repo | Branch | Cut from | HEAD | Source checkout |
|---|---|---|---|---|
${table}

Created ${stamp} by \`spinup-session\` on **${machine}**, from \`${s.checkoutRoot}\`.
Session name: **${sessionName}**
`;

// Personal rules come from the config, keyed by remote - never by directory name, which differs
// from machine to machine.
const rules = [`- ${isolated}`];
for (const c of created) {
  if (inList(c.remote, s.noPrRepos)) {
    rules.push(`- **Never push a branch or open a PR against \`${c.remote}\` without ${s.owner}'s explicit go-ahead in the current conversation.** Local branches, commits, builds and tests are fine; when the work is committed, stop and report the branch plus what a PR would say.`);
  }
  const note = Object.entries(s.repoNotes).find(([slug]) => inList(c.remote, [slug]))?.[1];
  if (note) rules.push(`- \`${c.repo}\`: ${note}`);
  if (c.linked) {
    rules.push(`- \`${c.repo}\` is a link to a live working checkout (\`${c.source}\`). This worktree is safe, but do not reset, stash or switch branches in the source checkout.`);
  }
}
rules.push(`- Work in the worktree directories, not in \`${s.checkoutRoot}\`. The branches live in the source repos, so \`git -C <source> branch\` sees them.`);

// How the session finishes: it owns the brief as its goal, knows when it is done, and then asks
// the hub to close it by itself. The hub's close still waits for the user's OK.
const finish = [
  `- **The brief is your goal.** Work toward it on your own and do not stop halfway to ask whether to continue. Ask ${s.owner} (\`AskUserQuestion\`, the options panel) only for a real decision you cannot make yourself, or for what the rules above reserve for them: pushes and PRs in no-PR repos, sending mail, production writes.`,
  '- **Done** means the deliverable exists (PR merged where the repo\'s flow allows a PR, committed locally where it does not, draft created, comment posted, ...) and you have given the final report. An open PR is not done: stay open while it is reviewed, work the review comments, and wait for the merge. If the goal cannot be reached, done means the blocker is reported. Never while a question to the user is still open.',
  '- **Clean the worktrees first.** Any untracked or modified file makes the close fail with `dirty_worktree`. Commit it, or move it where it belongs outside the worktree (e.g. the customer\'s project folder) and delete it here, until `git status --short` prints nothing in every worktree.',
  '- **Learnings go in the close-request, not in your own auto memory.** A fact the next session on one of these repos or folders should know (a gotcha, an API quirk, a decision and its reason) goes into the close-request as a `learnings:` block, one line each: `- <target> | <feedback|project|reference> | <kebab-name> | <the fact in one line>`. `<target>` is a repo directory from the table above, a folder passed for this task, or `general`. A fact about one customer goes to that customer\'s folder target, never to `general`: `general` loads in every session, for every customer. The hub files the ones the user approves. Leave out what the repo, its git history or its CLAUDE.md already records.',
  '- **Then send the close-request by yourself, without being asked.** Your job id is the last path segment of `$CLAUDE_JOB_DIR`; the hub is the session on this machine whose name ends in `hub` (find it with `ListAgents`). Send it one `SendMessage`: `close-request <job id>` with this workspace path, the branches, whether everything is pushed, what you did with scratch files, a one-line result, and the `learnings:` block if there is one. The hub asks the user, then stops this session and removes the worktrees; branches are kept. Never stop yourself or remove a worktree yourself.',
  '- If the user keeps working with you after that (or says to keep it running), stay open: the close waits for their OK anyway. Send a new close-request when the new work is done.',
];

const layout = created.map((c) => `| \`${c.repo}\` | \`${c.source}\` | \`${c.branch}\` | \`${c.base}\` |`).join('\n');
const claudeMd = `# Task workspace - ${title}

This directory is **not** a repository. It was created by the \`spinup-session\` skill on
**${machine}** and each subdirectory is a git worktree of the matching checkout in \`${s.checkoutRoot}\`:

| Directory | Worktree of | Branch | Cut from |
|---|---|---|---|
${layout}

The brief is in [TASK.md](TASK.md); \`.spinup.json\` carries the same facts machine-readably.
The repo-level \`CLAUDE.md\` inside each worktree still applies - read it before changing that repo.

## Rules that apply here

${rules.join('\n')}
${memorySection}
## Finishing: goal, done, close

${finish.join('\n')}
`;

writeFileSync(join(workspace, 'TASK.md'), taskMd, 'utf8');
writeFileSync(join(workspace, 'CLAUDE.md'), claudeMd, 'utf8');

const meta = {
  machine, ticket: ticketClean, desc: descClean, slug, session_name: sessionName, workspace,
  ghe_root: s.checkoutRoot, branch: branchName, repos: created, task: task.trim(),
  own_memory: ownMemory, memory_targets: memoryTargets,
  memory: memory.map(({ name, source, dir, lines, truncated, overLimit }) => ({ name, source, dir, lines: lines.length, truncated, overLimit })),
  created_at: now.toISOString(), session: null,
};
const metaPath = join(workspace, '.spinup.json');
writeJson(metaPath, meta);

if (o['no-start']) {
  emit({
    event: 'workspace-ready', machine, ticket: ticketClean, desc: descClean, session_name: sessionName,
    workspace, repos: created, memory: meta.memory.map(({ name, dir, lines, overLimit }) => ({ name, dir, lines, overLimit })), warnings,
    next: `cd '${workspace}'; claude --bg --remote-control '${sessionName}' --name '${sessionName}' ${NO_ENTER_WORKTREE}`,
  });
  process.exit(0);
}

// ---------------------------------------------------------------- start the session

if (existingSession) {
  emit({
    event: 'session-exists', machine, session_name: existingSession.name,
    session: { id: existingSession.id, sessionId: existingSession.sessionId, state: existingSession.state, name: existingSession.name },
    workspace, repos: created, memory: meta.memory.map(({ name, dir, lines, overLimit }) => ({ name, dir, lines, overLimit })), warnings, attach: `claude attach ${existingSession.id}`,
    message: 'a session is already running in this workspace - send it a message instead of starting a second one',
  });
  process.exit(0);
}

let prompt = '';
if (task.trim()) {
  const repoLines = created.map((c) => `- ${c.repo}${sep}  - worktree of ${c.source}, branch ${c.branch}`).join('\n');
  prompt = `${task.trim()}

---
You were started for this task in a fresh workspace: ${workspace}
It is not a repository - each subdirectory is a git worktree that was created for this job:

${repoLines}

You are already isolated: do not call EnterWorktree, edit and commit in these worktrees directly.
Read TASK.md for the brief and CLAUDE.md for the layout and the rules that apply here, then start.`;
}

// `=` form: --disallowedTools is variadic and would swallow the prompt. Claude Code keeps it in the
// job's respawnFlags, so a reaper revive and `claude respawn` deny the tool too.
const cliArgs = ['--bg', '--remote-control', sessionName, '--name', sessionName, NO_ENTER_WORKTREE];
if (o['permission-mode']) cliArgs.push('--permission-mode', o['permission-mode']);
if (o.model) cliArgs.push('--model', o.model);
if (prompt) cliArgs.push(prompt);
const start = run(claudeExe, cliArgs, { cwd: workspace });

// The id printed by --bg is not worth parsing; `claude agents` is the source of truth, and a
// freshly started session takes a moment to appear there.
let session = null;
for (let i = 0; i < 30 && !session; i++) {
  session = findSessionForPath(workspace);
  if (!session) sleepMs(1000);
}
if (!session) {
  fail(EV, 'session_not_started', `the workspace is ready but no session came up. claude said: ${start.text}`, {
    workspace, repos: created, session_name: sessionName,
  });
}

meta.session = { id: session.id, sessionId: session.sessionId, name: session.name,
  started_at: new Date().toISOString(), prompt_sent: Boolean(prompt) };
writeJson(metaPath, meta);

emit({
  event: 'session-ready', machine, ticket: ticketClean, desc: descClean, session_name: session.name,
  workspace, ghe_root: s.checkoutRoot, repos: created, memory: meta.memory.map(({ name, dir, lines, overLimit }) => ({ name, dir, lines, overLimit })), warnings,
  session: { id: session.id, sessionId: session.sessionId, state: session.state, name: session.name, prompt_sent: Boolean(prompt) },
  attach: `claude attach ${session.id}`,
  logs: `claude logs ${session.id}`,
});
