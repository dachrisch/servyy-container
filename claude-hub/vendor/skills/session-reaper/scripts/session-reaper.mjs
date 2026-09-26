#!/usr/bin/env node
// Park background Claude sessions that are safe to park, revive them later from a ledger, list
// the whole fleet, and spawn a new session of either kind.
//
// Looks at every session `claude agents --json --all` reports on THIS machine, decides per session
// whether it may be parked, and - outside --dry-run - parks it with `claude stop`, which keeps the
// conversation. `claude respawn` brings it back. Nothing here ever runs `claude rm`, touches a
// worktree or deletes a workspace.
//
// Rules, evaluated in this order; the first one that matches decides:
//
//   not_background        interactive sessions are never parked
//   not_running           no live process - there is nothing to stop
//   self                  the session running this script
//   hub                   name's last word is "hub", cwd is the checkout root, or it is the id in
//                         <checkoutRoot>/.claude-service.json
//   pinned                listed in ~/.claude/jobs/pins.json (manual opt-out)
//   no_state              no readable state.json - a decision could not be explained
//   busy                  running a turn, or it has a background task in flight
//   never_prompted  PARK  no brief, never finished a turn, older than --grace-minutes
//   cleared         PARK  /clear was the last thing that happened, idle for --grace-minutes
//   in_grace              never_prompted / cleared, but still inside --grace-minutes
//   waiting_on_user       needs != null, or tempo/state is "blocked"
//   recently_active       last activity less than --idle-hours ago
//   handoff_backoff       idle, but its last handoff attempt failed less than --retry-hours ago
//   idle            PARK  no activity for --idle-hours: handoff first, then stop
//
// never_prompted and cleared come BEFORE waiting_on_user on purpose: a never-prompted session
// reports tempo=blocked with needs="send a prompt to start", which is not a question for anyone.
//
// Emits exactly one JSON object on stdout (or a table with --text):
//   reaper-plan | reaper-run | reaper-parked | reaper-fleet | session-revived | session-spawned | reaper-blocked
import { randomUUID } from 'node:crypto';
import { existsSync, mkdirSync, readdirSync, readFileSync, rmdirSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { homedir, hostname } from 'node:os';
import { basename, dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { claudeDir, HubConfigError, resolveSettings } from '../../../scripts/lib/hub-config.mjs';
import { installLauncher, launcherPath } from '../../../scripts/lib/launcher-install.mjs';
import { appendLine, emit, fail, formatTable, fullPath, parseCli, readJson, run, samePath, sleepMs, which, writeJson } from '../../../scripts/lib/proc.mjs';
import { findSentinel, findTranscript, iso, minutesSince, textContent, toUtc, transcriptFacts } from './transcript.mjs';

const EV = 'reaper-blocked';
const REAPER_VERSION = '2';
const HERE = dirname(fileURLToPath(import.meta.url));
// inFlight kinds that do not make a session busy: an armed cron, a passive artifact watch.
const PASSIVE_TASK_KINDS = ['session_cron', 'artifact_watch'];

const { values: o } = parseCli(process.argv.slice(2), {
  event: EV,
  options: {
    action: { type: 'string', default: 'run' },
    id: { type: 'string', default: '' },
    all: { type: 'boolean', default: false },
    desc: { type: 'string', default: '' },
    repos: { type: 'string', default: '' },
    ticket: { type: 'string', default: '' },
    task: { type: 'string', default: '' },
    'task-file': { type: 'string', default: '' },
    deck: { type: 'boolean', default: false },
    cwd: { type: 'string', default: '' },
    group: { type: 'string', default: '' },
    model: { type: 'string', default: '' },
    'permission-mode': { type: 'string', default: '' },
    branch: { type: 'string', default: '' },
    'grace-minutes': { type: 'string' },
    'idle-hours': { type: 'string' },
    'handoff-timeout-minutes': { type: 'string' },
    'max-handoffs': { type: 'string' },
    'retry-hours': { type: 'string' },
    'relay-model': { type: 'string' },
    root: { type: 'string', default: '' },
    'state-dir': { type: 'string', default: '' },
    'no-rearm': { type: 'boolean', default: false },
    text: { type: 'boolean', default: false },
    'dry-run': { type: 'boolean', default: false },
  },
});
let action = o.action === 'reap' ? 'run' : o.action;
if (!['run', 'list', 'revive', 'spawn', 'close'].includes(action)) fail(EV, 'bad_args', `--action must be run, reap, list, revive, spawn or close, not '${o.action}'`);
const dryRun = o['dry-run'];

// ---------------------------------------------------------------- settings and paths

let settings;
try {
  settings = resolveSettings({ flags: { root: o.root } });
} catch (e) {
  if (e instanceof HubConfigError) fail(EV, e.code, e.message);
  throw e;
}
function num(flag, fallback) {
  if (o[flag] === undefined) return fallback;
  const n = Number(o[flag]);
  if (!(n > 0)) fail(EV, 'bad_args', `--${flag} must be a positive number`);
  return n;
}
const R = settings.reaper;
const graceMinutes = num('grace-minutes', R.graceMinutes);
const idleHours = num('idle-hours', R.idleHours);
const handoffTimeoutMinutes = num('handoff-timeout-minutes', R.handoffTimeoutMinutes);
const maxHandoffs = num('max-handoffs', R.maxHandoffs);
const retryHours = num('retry-hours', R.retryHours);
const relayModel = o['relay-model'] || R.relayModel;
const checkoutRoot = settings.checkoutRoot;
const machine = settings.prefixExplicit ? settings.prefix : (process.env.COMPUTERNAME || hostname());

const claudeHome = claudeDir();
const jobsDir = join(claudeHome, 'jobs');
const handoffDir = join(claudeHome, 'handoff');
const stateDir = o['state-dir'] ? fullPath(o['state-dir']) : R.stateDir;
const ledgerPath = join(stateDir, 'ledger.jsonl');
const attemptsPath = join(stateDir, 'attempts.json');
const relayDir = join(stateDir, 'relay');
// Through the stable launcher, never this file: a handoff note outlives the plugin version that wrote it.
const reviveCmd = (id) => `node "${launcherPath()}" reaper --action revive --id ${id}`;

// ---------------------------------------------------------------- claude

// cron and Task Scheduler start with a thin PATH.
const claudeExe = which('claude', [join(homedir(), '.local', 'bin', 'claude'), join(homedir(), '.local', 'bin', 'claude.exe')]);
if (!claudeExe) fail(EV, 'tool_missing', 'claude is required but not on PATH');
const claude = (...args) => run(claudeExe, args);

function getAgents() {
  const r = claude('agents', '--json', '--all');
  if (!r.ok) fail(EV, 'agents_failed', `claude agents --json --all failed: ${r.text}`);
  try { return JSON.parse(r.text); } catch { return fail(EV, 'agents_unparsable', `claude agents output is not JSON: ${r.text}`); }
}

// `claude agents --all` also lists exited jobs; only a live one has a pid / status.
const isRunning = (a) => Boolean(a?.pid) || Boolean(a?.status);

function waitAgent(jobId, running, seconds = 30) {
  for (let i = 0; i < seconds; i++) {
    const a = getAgents().find((x) => x.id === jobId);
    if (a && isRunning(a) === running) return a;
    if (!a && !running) return null;
    sleepMs(1000);
  }
  return getAgents().find((x) => x.id === jobId) ?? null;
}

// The last word of the name, ignoring emoji, brackets and the ZWJ spacing some listings add.
// Never match a hub by its exact emoji string - listings render the ZWJ sequence differently.
function isHubName(name) {
  const words = String(name || '').split(/[^\p{L}\p{N}]+/u).filter(Boolean);
  return words.length > 0 && words[words.length - 1].toLowerCase() === 'hub';
}

// ---------------------------------------------------------------- ledger and attempts

function ledger() {
  if (!existsSync(ledgerPath)) return [];
  return readFileSync(ledgerPath, 'utf8').split(/\r?\n/).filter((l) => l.trim())
    .map((l) => { try { return JSON.parse(l); } catch { return null; } }).filter(Boolean);
}
const addLedger = (entry) => appendLine(ledgerPath, JSON.stringify(entry));
const attempts = () => readJson(attemptsPath) ?? {};
function saveAttempt(jobId, outcome, detail = '') {
  const h = attempts();
  h[jobId] = { at: new Date().toISOString(), outcome, detail };
  writeJson(attemptsPath, h);
}
// Parked sessions: the newest ledger event per id is a "parked", not a "revived".
function parked() {
  const latest = new Map();
  for (const e of ledger()) if (e.id) latest.set(String(e.id), e);
  return [...latest.values()].filter((e) => e.event === 'parked');
}
// The newest ledger event for one id: parked, revived or closed.
const latestEvent = (id) => ledger().filter((e) => String(e.id) === String(id)).pop() ?? null;
const reopenCmd = (meta) => {
  const repos = (meta?.repos ?? []).map((r) => r.repo).join(',');
  const ticket = meta?.ticket ? ` --ticket ${meta.ticket}` : '';
  return `node "${launcherPath()}" spinup${ticket} --desc "${meta?.desc ?? ''}" --repos "${repos}" --branch ${meta?.branch ?? ''}`;
};
const loopCount = (loops) => (loops ? (loops.crons ?? []).length + (loops.wakeup ? 1 : 0) : 0);

function formatLoops(loops) {
  const out = [];
  for (const c of loops?.crons ?? []) out.push(`- cron \`${c.cron}\` (${c.recurring ? 'recurring' : 'one-shot'}, id ${c.id}): ${c.prompt}`);
  if (loops?.wakeup) out.push(`- /loop dynamic wakeup (last delay ${loops.wakeup.delaySeconds}s): ${loops.wakeup.prompt}`);
  if (loops?.loop_command) out.push(`- /loop was invoked with: ${loops.loop_command.args}`);
  return out;
}

// ---------------------------------------------------------------- git facts (for the ledger)

function gitFacts(cwd) {
  if (!cwd || !existsSync(cwd) || !which('git')) return [];
  // A spinup workspace is not a repo; its .spinup.json names the worktrees inside it.
  let dirs = [];
  const spinup = readJson(join(cwd, '.spinup.json'));
  if (spinup?.repos) dirs = spinup.repos.map((r) => r.path);
  else if (run('git', ['-C', cwd, 'rev-parse', '--is-inside-work-tree']).text === 'true') dirs = [cwd];
  else {
    try {
      dirs = readdirSync(cwd, { withFileTypes: true }).filter((d) => d.isDirectory() && existsSync(join(cwd, d.name, '.git')))
        .map((d) => join(cwd, d.name));
    } catch { dirs = []; }
  }
  return dirs.filter((d) => d && existsSync(d)).map((dir) => {
    const g = (...a) => run('git', ['-C', dir, ...a]);
    const upstream = g('rev-parse', '--abbrev-ref', '@{upstream}');
    return {
      path: dir,
      branch: g('rev-parse', '--abbrev-ref', 'HEAD').text,
      upstream: upstream.ok ? upstream.text : null,
      dirty_files: g('status', '--porcelain').text.split('\n').filter(Boolean).length,
      unpushed: upstream.ok ? Number(g('rev-list', '--count', '@{upstream}..HEAD').text) : null,
      last_commits: g('log', '-3', '--format=%h %s').text.split('\n').filter(Boolean),
    };
  });
}

// ---------------------------------------------------------------- inputs

const selfJob = process.env.CLAUDE_JOB_DIR ? basename(process.env.CLAUDE_JOB_DIR) : '';
// A hub kept alive by a service on this box may remember its id here.
const serviceHubId = String(readJson(join(checkoutRoot, '.claude-service.json'))?.id ?? '');
const pinsRaw = readJson(join(jobsDir, 'pins.json'));
const pins = (Array.isArray(pinsRaw) ? pinsRaw : []).map((p) => (typeof p === 'string' ? p : String(p?.id ?? p?.jobId ?? '')));
const now = new Date();

// ---------------------------------------------------------------- relay (SendMessage via claude -p)

// SendMessage is a Claude tool, not a CLI command, so a one-shot headless session carries the
// message. It only delivers; the reply is read from the target's transcript, never trusted from
// the relay's own output.
function sendViaRelay(session, message) {
  const relayPrompt = `You are a one-shot message relay for the session-reaper script. Do exactly this and nothing else:

1. Call ListAgents.
2. Find the ONE peer session that is the background job with id ${session.id}, named "${session.name}", working in ${session.cwd}.
   Listings may render the leading emoji differently (split, or with a space) - match on the words after it.
   If no row matches, or more than one could, send nothing: print NOTFOUND or AMBIGUOUS and stop.
3. Call SendMessage with "to" copied exactly as the listing prints that row (add its [ref] if the listing shows one),
   and "message" set to the text between the two ==== lines below, verbatim.
4. Do not wait for a reply. Print SENT and stop.

====
${message}
====
`;
  mkdirSync(relayDir, { recursive: true });
  const r = run(claudeExe, ['-p', '--model', relayModel], { cwd: relayDir, input: relayPrompt });
  return { ok: /^\s*SENT\s*$/m.test(r.text), text: r.text };
}

function waitSentinel(transcript, nonce, timeoutMinutes, jobId) {
  const deadline = Date.now() + timeoutMinutes * 60000;
  while (Date.now() < deadline) {
    const note = findSentinel(transcript, nonce);
    if (note !== null) return { ok: true, note, outcome: 'answered', detail: '' };
    // A session that answers with a question instead is waiting on its user now - leave it.
    const st = readJson(join(jobsDir, String(jobId), 'state.json'));
    if (st?.needs && st?.tempo === 'blocked') return { ok: false, note: '', outcome: 'asked_instead', detail: String(st.needs) };
    sleepMs(10000);
  }
  return { ok: false, note: '', outcome: 'timeout', detail: `no reply within ${timeoutMinutes} min` };
}

function handoffRequest(d, nonce) {
  const loopLines = formatLoops(d.loops);
  const gitLines = (d.git ?? []).map((g) => `- ${g.path}: branch ${g.branch}, ${g.dirty_files} dirty file(s), ${g.unpushed !== null ? `${g.unpushed} unpushed commit(s)` : 'no upstream'}`);
  return `session-reaper: you have had no activity for over ${idleHours} h and are about to be parked (claude stop - your conversation is kept, and claude respawn brings you back). Please write your handoff note now.

Answer in ONE reply, and do not call any tool that needs approval (no edits, no pushes, no messages). Use this exact frame - the reaper reads only what is between the two markers:

<<REAPER-HANDOFF ${nonce}>>
# Resume: <task in one line>

**Goal:** <what done means>
**Start here:** \`cd <absolute path>\`  ·  branch \`<branch>\`

## Status
<done / in progress / blocked, with evidence: PR, run id, file>

## Branches and commits
<per repo: branch, commits that exist only locally, uncommitted work>

## Open questions
<decisions waiting on ${settings.owner}, or "none">

## Next steps
1. <the first concrete action after a revive>

## Loops
<every cron, /loop or other recurring job you were running, with its exact schedule and prompt, so a revive can re-arm it - parking kills them. "none" if there were none.>
<<END-REAPER-HANDOFF ${nonce}>>

What the reaper found mechanically (confirm or correct it in your note):
Loops:
${loopLines.length ? loopLines.join('\n') : '- none found in the transcript'}
Git:
${gitLines.length ? gitLines.join('\n') : '- not a git workspace'}
`;
}

// ---------------------------------------------------------------- list

if (action === 'list') {
  const agents = getAgents();
  const parkedRows = parked().map((e) => {
    const a = agents.find((x) => x.id === e.id);
    return {
      id: e.id, name: e.name, parked_at: e.at, rule: e.rule, reason: e.reason, cwd: e.cwd,
      loops: loopCount(e.loops), handoff_path: e.handoff_path,
      now: !a ? 'gone from claude agents (revive resumes it into a new job)' : isRunning(a) ? 'running again (revived outside the reaper)' : 'parked',
      revive: reviveCmd(e.id),
    };
  });
  if (!o.all) {
    if (o.text) {
      process.stdout.write(parkedRows.length ? `${formatTable(parkedRows, ['id', 'name', 'parked_at', 'rule', 'loops', 'now'])}\n` : `No parked sessions in ${ledgerPath}\n`);
      process.exit(0);
    }
    emit({ event: 'reaper-parked', machine, ledger: ledgerPath, parked: parkedRows });
    process.exit(0);
  }

  // --all: the whole fleet. `claude agents --all` lists background jobs AND interactive agent-deck
  // sessions; an exited job stays in that listing, which is how a stopped session still shows
  // what it was doing and what it is waiting for.
  const parkedById = new Map(parkedRows.map((e) => [String(e.id), e]));
  const closedIds = new Set();
  { const latest = new Map(); for (const e of ledger()) if (e.id) latest.set(String(e.id), e);
    for (const [k, e] of latest) if (e.event === 'closed') closedIds.add(k); }
  const seen = new Set();
  const rows = [];
  for (const a of agents) {
    const jid = String(a.id ?? '');
    if (o.id && jid !== o.id) continue;
    if (jid) seen.add(jid);
    const isJob = a.kind === 'background';
    // Only a background job has a state.json; an agent-deck session has none, and its startedAt
    // is not activity - leave its idle blank rather than print the session's age as idle.
    const st = jid ? readJson(join(jobsDir, jid, 'state.json')) : null;
    const last = toUtc(st?.updatedAt);
    const p = jid ? parkedById.get(jid) : null;
    const live = isRunning(a);
    const label = a.name || `(${basename(String(a.cwd ?? ''))})`;
    rows.push({
      id: jid, kind: isJob ? 'job' : 'deck', name: label, cwd: String(a.cwd ?? ''),
      state: String(st?.state || a.state || a.status || ''), status: String(a.status ?? ''),
      now: live ? 'live' : closedIds.has(jid) ? 'closed' : p ? 'parked' : 'stopped',
      idle_minutes: minutesSince(last, now), last_active: iso(last),
      started_at: a.startedAt ? iso(toUtc(a.startedAt)) : null,
      detail: String(st?.detail ?? ''), needs: st?.needs ?? null,
      parked_at: p?.parked_at ?? null, rule: p?.rule ?? '', handoff_path: p?.handoff_path ?? '',
      resume: closedIds.has(jid) && !live ? '' : p ? reviveCmd(jid) : jid && !live ? `claude respawn ${jid}` : !isJob && !live ? `agent-deck session start "${a.name}"` : '',
    });
  }
  // A parked job claude has already forgotten still has a ledger entry, and reviving it resumes
  // the conversation into a new job.
  for (const e of parkedRows) {
    const eid = String(e.id);
    if (seen.has(eid) || (o.id && eid !== o.id)) continue;
    rows.push({ id: eid, kind: 'job', name: e.name, cwd: e.cwd, state: 'parked', status: '', now: 'gone',
      idle_minutes: minutesSince(toUtc(e.parked_at), now), last_active: e.parked_at, started_at: null, detail: '', needs: null,
      parked_at: e.parked_at, rule: e.rule, handoff_path: e.handoff_path, resume: reviveCmd(eid) });
  }
  // Live first, then what can be brought back, then the rest; deck and job interleaved on purpose.
  const order = { live: 0, parked: 1, stopped: 2, gone: 3, closed: 4 };
  rows.sort((p, q) => order[p.now] - order[q.now] || p.kind.localeCompare(q.kind) || String(p.name).localeCompare(String(q.name)));
  if (o.text) {
    if (!rows.length) { process.stdout.write(`No sessions on ${machine}\n`); process.exit(0); }
    const table = rows.map((r) => ({ NOW: r.now, KIND: r.kind, ID: r.id, NAME: r.name, STATE: r.state, IDLE: r.idle_minutes,
      WHY: r.needs ? `needs: ${r.needs}` : r.detail }));
    process.stdout.write(`${formatTable(table, ['NOW', 'KIND', 'ID', 'NAME', 'STATE', 'IDLE', 'WHY'])}\n`);
    process.exit(0);
  }
  emit({ event: 'reaper-fleet', machine, at: now.toISOString(), ledger: ledgerPath, sessions: rows });
  process.exit(0);
}

// ---------------------------------------------------------------- spawn

if (action === 'spawn') {
  if (!o.desc) fail(EV, 'desc_missing', '--action spawn needs --desc "<2-5 words>"');
  let task = o.task;
  let briefPath = '';
  if (o['task-file']) {
    if (!existsSync(o['task-file'])) fail(EV, 'task_file_missing', `--task-file '${o['task-file']}' does not exist`);
    briefPath = fullPath(o['task-file']);
    if (!task) task = readFileSync(briefPath, 'utf8');
  }

  // -------- agent-deck session: an existing directory, no worktrees, no branch.
  if (o.deck) {
    const deckExe = which('agent-deck');
    if (!deckExe) fail(EV, 'tool_missing', 'agent-deck is required for --deck but is not on PATH');
    const path = o.cwd ? fullPath(o.cwd) : checkoutRoot;
    if (!existsSync(path)) fail(EV, 'cwd_missing', `--cwd '${path}' does not exist`);
    const title = [o.ticket, o.desc].filter(Boolean).join(' ');
    const deckArgs = ['launch', path, '-t', title, '-c', 'claude', '-json'];
    if (o.group) deckArgs.push('-g', o.group);
    // -message-file keeps a long brief out of the command line entirely.
    if (briefPath) deckArgs.push('-message-file', briefPath);
    else if (task) deckArgs.push('-message', task);
    if (dryRun) {
      emit({ event: 'session-spawned', result: 'planned', kind: 'deck', machine, title, cwd: path, group: o.group,
        command: `agent-deck ${deckArgs.join(' ')}` });
      process.exit(0);
    }
    const r = run(deckExe, deckArgs);
    if (!r.ok) fail(EV, 'spawn_failed', `agent-deck launch failed: ${r.text}`, { kind: 'deck' });
    let sid = '';
    try { sid = String(JSON.parse(r.text).id ?? ''); } catch { /* not JSON */ }
    emit({ event: 'session-spawned', result: 'started', kind: 'deck', machine, title, cwd: path, group: o.group,
      id: sid, output: r.text, attach: sid ? `agent-deck session attach ${sid}` : `agent-deck session attach "${title}"` });
    process.exit(0);
  }

  // -------- background job: spinup-session owns the workspace, the worktrees, the branch, the
  // session name and the start. Everything it can derive is NOT re-derived here.
  if (!o.repos) fail(EV, 'repos_missing', '--action spawn needs --repos for a background job (or --deck for an agent-deck session in an existing directory)');
  const spinup = join(HERE, '..', '..', 'spinup-session', 'scripts', 'spinup-session.mjs');
  if (!existsSync(spinup)) fail(EV, 'spinup_missing', `spinup-session.mjs not found at ${spinup}`);
  const sArgs = [spinup, '--desc', o.desc, '--repos', o.repos, '--root', checkoutRoot];
  // Only an explicit prefix is passed on; a derived one is left for spinup to derive, so it stays bracketed.
  if (settings.prefixExplicit) sArgs.push('--machine', settings.prefix);
  for (const k of ['ticket', 'branch', 'model', 'permission-mode']) if (o[k]) sArgs.push(`--${k}`, o[k]);
  if (briefPath) sArgs.push('--task-file', briefPath);
  else if (task) sArgs.push('--task', task);
  if (dryRun) sArgs.push('--dry-run');
  const r = run(process.execPath, sArgs);
  // spinup-session emits its own single JSON event. Pass it through verbatim so anything that
  // already reads those events keeps working.
  let parsed = null;
  try { parsed = JSON.parse(r.stdout); } catch { /* handled below */ }
  if (!parsed) fail(EV, 'spawn_failed', `spinup-session.mjs produced no JSON event: ${r.text}`, { kind: 'job' });
  process.stdout.write(`${r.stdout}\n`);
  process.exit(parsed.event === 'spinup-blocked' ? 1 : 0);
}

// ---------------------------------------------------------------- close

// A task session asked the hub to close it and the user agreed: stop it and remove its
// worktrees. Only a background job in a spinup workspace, never with uncommitted work, and
// never a branch - the branch keeps every commit, and spinup with --branch reattaches it.
if (action === 'close') {
  const CEV = 'close-blocked';
  if (!o.id) fail(CEV, 'id_missing', '--action close needs --id <job id> (the id in the close-request)');
  const a = getAgents().find((x) => x.id === o.id);
  if (!a) fail(CEV, 'not_found', `claude agents does not know ${o.id}`);
  if (a.kind !== 'background' || isHubName(a.name) || samePath(a.cwd, checkoutRoot) || (serviceHubId && a.id === serviceHubId)) {
    fail(CEV, 'not_closable', `${o.id} (${a.name}) is ${a.kind !== 'background' ? `a ${a.kind} session` : 'the hub'} - only background task sessions can be closed`);
  }
  const ws = a.cwd;
  const meta = readJson(join(ws, '.spinup.json'));
  if (!meta?.repos) fail(CEV, 'not_a_spinup_workspace', `${ws} has no .spinup.json - close only removes workspaces spinup-session created`);

  const facts = gitFacts(ws);
  const repos = meta.repos.map((r) => {
    const g = facts.find((x) => samePath(x.path, r.path));
    let unpushed = g?.unpushed ?? null;
    let noUpstream = false;
    if (g && g.upstream === null && r.base) {
      noUpstream = true;
      const n = run('git', ['-C', r.path, 'rev-list', '--count', `${r.base}..HEAD`]);
      unpushed = n.ok ? Number(n.stdout) : null;
    }
    return { repo: r.repo, path: r.path, branch: r.branch, source: r.source, exists: existsSync(r.path),
      dirty_files: g?.dirty_files ?? 0, unpushed, no_upstream: noUpstream };
  });
  const dirty = repos.filter((r) => r.dirty_files > 0);
  if (dirty.length) {
    fail(CEV, 'dirty_worktree', `uncommitted changes in ${dirty.map((r) => `${r.repo} (${r.dirty_files} file(s))`).join(', ')} - commit or discard them first; nothing was stopped or removed`, { id: o.id, repos });
  }
  const warnings = repos.filter((r) => r.unpushed > 0).map((r) => (r.no_upstream
    ? `${r.repo}: branch ${r.branch} has no upstream; its ${r.unpushed} local commit(s) stay on the branch`
    : `${r.repo}: ${r.unpushed} local commit(s) not pushed; branch ${r.branch} keeps them`));
  const branches = repos.map((r) => ({ repo: r.repo, branch: r.branch, source: r.source }));
  const reopen = reopenCmd(meta);
  const files = ['TASK.md', 'CLAUDE.md', '.spinup.json'].map((f) => join(ws, f));

  if (dryRun) {
    emit({ event: 'close-planned', id: o.id, name: a.name, workspace: ws, repos, warnings, branches,
      will: [isRunning(a) ? `claude stop ${o.id}` : 'session is not running',
        ...repos.filter((r) => r.exists).map((r) => `git -C "${r.source}" worktree remove "${r.path}"`),
        `remove ${files.map((f) => basename(f)).join(', ')} and the workspace directory if nothing else is in it`],
      keeps: 'every branch and commit; the conversation (claude --resume)', reopen });
    process.exit(0);
  }

  if (isRunning(a)) {
    const r = claude('stop', o.id);
    const after = waitAgent(o.id, false, 20);
    if (!r.ok || (after && isRunning(after))) fail(CEV, 'stop_failed', `claude stop ${o.id} failed: ${r.text}`, { id: o.id });
  }
  addLedger({ event: 'closed', at: new Date().toISOString(), machine, id: o.id, name: a.name, cwd: ws,
    sessionId: a.sessionId ?? null, git: facts, spinup: meta, reopen, reaper_version: REAPER_VERSION });

  const removed = [];
  const failed = [];
  for (const r of repos.filter((x) => x.exists)) {
    const rm = run('git', ['-C', r.source, 'worktree', 'remove', r.path]);
    if (rm.ok) removed.push(r.path);
    else failed.push({ path: r.path, message: rm.text });
  }
  // The workspace files stay while a worktree is still there, so it keeps explaining itself.
  if (!failed.length) for (const f of files) if (existsSync(f)) { rmSync(f); removed.push(f); }
  let kept = [];
  try { kept = readdirSync(ws).map((n) => join(ws, n)); } catch { kept = []; }
  if (!kept.length && existsSync(ws)) { rmdirSync(ws); removed.push(ws); } // only ever an empty directory
  emit({ event: 'session-closed', id: o.id, name: a.name, workspace: ws, removed, kept, failed, warnings, branches, reopen });
  process.exit(failed.length ? 1 : 0);
}

// ---------------------------------------------------------------- revive

if (action === 'revive') {
  if (!o.id) fail(EV, 'id_missing', '--action revive needs --id <job id>; --action list shows the parked ones');
  const last = latestEvent(o.id);
  if (last?.event === 'closed') {
    fail(EV, 'closed_not_revivable', `${o.id} was closed at ${last.at} and its worktrees were removed; the branch is kept - start it again with: ${last.reopen}`, { id: o.id });
  }
  const entry = ledger().filter((e) => e.id === o.id && e.event === 'parked').pop();
  if (!entry) fail(EV, 'not_in_ledger', `no parked entry for ${o.id} in ${ledgerPath}`);
  const agent = getAgents().find((a) => a.id === o.id);
  if (agent && isRunning(agent)) {
    emit({ event: 'session-revived', result: 'already-running', id: o.id, name: agent.name, attach: `claude attach ${o.id}` });
    process.exit(0);
  }
  const rearmWanted = loopCount(entry.loops) > 0 && !o['no-rearm'];
  if (dryRun) {
    emit({ event: 'session-revived', result: 'planned', id: o.id, name: entry.name,
      command: agent ? `claude respawn ${o.id}` : `claude --bg --resume ${entry.resumeSessionId} ${(entry.respawnFlags ?? []).join(' ')}`,
      rearm_loops: rearmWanted, loops: formatLoops(entry.loops), entry });
    process.exit(0);
  }

  // respawn keeps the job id, the name and Remote Control. Only when the job record is gone does
  // the conversation get resumed into a new job with the recorded flags.
  let how = 'respawn';
  const r = claude('respawn', o.id);
  let live = r.ok ? waitAgent(o.id, true, 30) : null;
  if (!(live && isRunning(live))) {
    how = 'resume';
    const r2 = run(claudeExe, ['--bg', '--resume', String(entry.resumeSessionId), ...(entry.respawnFlags ?? []).map(String)], { cwd: entry.cwd });
    live = null;
    for (let i = 0; i < 30 && !live; i++) {
      live = getAgents().filter((a) => isRunning(a) && samePath(a.cwd, entry.cwd) && a.id !== o.id)
        .sort((p, q) => (toUtc(q.startedAt) ?? 0) - (toUtc(p.startedAt) ?? 0))[0] ?? null;
      if (!live) sleepMs(1000);
    }
    if (!live) fail(EV, 'revive_failed', `respawn said: ${r.text} / resume said: ${r2.text}`, { id: o.id });
  }

  let rearm = null;
  if (rearmWanted) {
    const msg = `session-reaper: you were parked at ${entry.at} and have just been revived. Parking killed the loops you were running - re-arm them now, exactly as they were:

${formatLoops(entry.loops).join('\n')}

Your own handoff note from before the park is at ${entry.handoff_path}; where its Loops section differs from the list above, your note wins.`;
    sleepMs(5000); // let the respawned process register its inbox
    rearm = sendViaRelay({ id: live.id, name: live.name, cwd: live.cwd }, msg);
  }
  addLedger({ event: 'revived', at: new Date().toISOString(), machine, id: o.id, now_id: live.id, name: entry.name,
    how, rearm_sent: rearm ? rearm.ok : null, reaper_version: REAPER_VERSION });
  emit({ event: 'session-revived', result: how, id: live.id, previous_id: o.id, name: live.name,
    rearm: rearm ? { sent: rearm.ok, relay: rearm.text } : null, attach: `claude attach ${live.id}` });
  process.exit(0);
}

// ---------------------------------------------------------------- run: decide

function decide(agents) {
  const decisions = [];
  const notRunning = [];
  const graceMs = graceMinutes * 60000;
  const idleMs = idleHours * 3600000;
  const idleMin = Math.round(idleHours * 60);
  const att = attempts();

  for (const a of agents) {
    if (o.id && a.id !== o.id) continue;
    const name = String(a.name ?? '');
    const d = { id: a.id ?? null, name, kind: a.kind ?? null, cwd: a.cwd ?? null, status: a.status ?? null, state: a.state ?? null,
      decision: 'skip', rule: '', reason: '', idle_minutes: null };
    const decideAs = (rule, reason, decision = 'skip') => {
      d.rule = rule; d.reason = reason; d.decision = decision; decisions.push(d);
    };

    if (a.kind !== 'background') { decideAs('not_background', `kind=${a.kind}: only background jobs are ever parked`); continue; }
    if (!isRunning(a)) { notRunning.push({ id: a.id, name, state: a.state }); continue; }
    if (selfJob && a.id === selfJob) { decideAs('self', 'this is the session running the reaper'); continue; }
    if (isHubName(name)) { decideAs('hub', `name '${name}' ends in 'hub'`); continue; }
    if (samePath(a.cwd, checkoutRoot)) { decideAs('hub', `cwd is the checkout root ${checkoutRoot}`); continue; }
    if (serviceHubId && a.id === serviceHubId) { decideAs('hub', 'the session the hub service keeps alive'); continue; }
    if (pins.includes(a.id)) { decideAs('pinned', 'listed in ~/.claude/jobs/pins.json'); continue; }

    const st = readJson(join(jobsDir, String(a.id), 'state.json'));
    if (!st) { decideAs('no_state', `no readable state.json for ${a.id} - not parking what cannot be explained`); continue; }

    const updatedAt = toUtc(st.updatedAt);
    const createdAt = toUtc(st.createdAt);
    const tempo = String(st.tempo ?? '');
    const needs = st.needs ?? null;
    const detail = String(st.detail ?? '');
    const intent = String(st.intent ?? '');
    const inFlight = st.inFlight ?? null;
    const resumeSid = String(st.resumeSessionId ?? '');
    const transcript = findTranscript(claudeHome, resumeSid, st.linkScanPath ? String(st.linkScanPath) : '');
    const tf = transcriptFacts(transcript, now);

    // Last activity: the job's own clock or the transcript's last record, whichever is newer.
    let lastActive = updatedAt;
    if (tf.last_record_at && (!lastActive || tf.last_record_at > lastActive)) lastActive = tf.last_record_at;
    Object.assign(d, {
      detail, tempo, needs, last_active: iso(lastActive), idle_minutes: minutesSince(lastActive, now),
      sessionId: String(st.sessionId ?? ''), resumeSessionId: resumeSid,
      respawnFlags: (st.respawnFlags ?? []).filter((x) => x !== null && x !== undefined),
      transcript, loops: { crons: tf.crons, wakeup: tf.wakeup, loop_command: tf.loop_command },
    });

    // An armed cron (session_cron) or an artifact watch counts as an in-flight task but is
    // passive - a loop session between ticks is not busy. A live shell or subagent is.
    const kinds = (inFlight?.kinds ?? []).map(String);
    const activeKinds = kinds.filter((k) => !PASSIVE_TASK_KINDS.includes(k));
    let activeTasks = 0;
    if (inFlight) {
      activeTasks = Number(inFlight.queued ?? 0) + (activeKinds.length ? Number(inFlight.tasks ?? 0)
        : !kinds.length ? Number(inFlight.tasks ?? 0) - Number(inFlight.drainableMonitors ?? 0) : 0);
    }
    const neverPrompted = !intent.trim() && !st.firstTerminalAt
      && (/send a prompt to start/.test(detail) || /send a prompt to start/.test(String(needs ?? '')));
    const cleared = Boolean(tf.cleared_at) && !tf.prompted_after_clear;

    if (a.status === 'busy') { decideAs('busy', 'claude agents reports status=busy (a turn is running)'); continue; }
    if (activeTasks > 0) { decideAs('busy', `${activeTasks} background task(s) in flight (${kinds.join(', ')})`); continue; }

    if (neverPrompted) {
      const since = createdAt ?? lastActive;
      d.idle_minutes = minutesSince(since, now);
      if (since && now - since >= graceMs) decideAs('never_prompted', `never prompted; started ${d.idle_minutes} min ago (grace ${graceMinutes} min)`, 'park');
      else decideAs('in_grace', `never prompted, but only ${d.idle_minutes} min old (grace ${graceMinutes} min)`);
      continue;
    }
    if (cleared) {
      let since = tf.cleared_at;
      if (lastActive && lastActive > since) since = lastActive;
      d.cleared_at = iso(tf.cleared_at);
      d.idle_minutes = minutesSince(since, now);
      // /clear does not reset state.json: a question asked before it is still in `needs`, but the
      // context it belonged to is gone. Say so, so the stale question is visible.
      const stale = needs ? `; stale needs from before the clear: '${needs}'` : '';
      if (now - since >= graceMs) decideAs('cleared', `/clear at ${d.cleared_at}, nothing since; idle ${d.idle_minutes} min (grace ${graceMinutes} min)${stale}`, 'park');
      else decideAs('in_grace', `/clear'ed, idle only ${d.idle_minutes} min (grace ${graceMinutes} min)`);
      continue;
    }
    // The live status from `claude agents` wins over state.json: a loop session sits in
    // state=working between ticks. Only an older build without a status falls back to state.
    if (!a.status && a.state === 'working') { decideAs('busy', `state=working: '${detail}'`); continue; }
    if (needs || tempo === 'blocked' || a.state === 'blocked' || st.state === 'blocked') {
      decideAs('waiting_on_user', needs ? `needs: ${needs}` : `tempo=${tempo}, state=${a.state}: '${detail}'`);
      continue;
    }
    if (!lastActive) { decideAs('no_state', 'no updatedAt and no transcript timestamp - idle time unknown'); continue; }
    if (now - lastActive < idleMs) { decideAs('recently_active', `last activity ${d.idle_minutes} min ago (threshold ${idleMin} min)`); continue; }
    const prev = att[String(a.id)];
    if (prev && (now - toUtc(prev.at)) / 3600000 < retryHours) {
      decideAs('handoff_backoff', `idle ${d.idle_minutes} min, but its last handoff attempt (${prev.outcome}) was at ${prev.at}; retry after ${retryHours} h`);
      continue;
    }
    const lc = loopCount(d.loops);
    decideAs('idle', `idle ${d.idle_minutes} min (threshold ${idleMin} min), last: '${detail}'${lc ? `; ${lc} loop(s) recorded for re-arm` : ''}`, 'handoff-then-park');
  }
  for (const d of decisions) if (d.decision !== 'skip') d.git = gitFacts(d.cwd);
  return { decisions, notRunning };
}

const params = {
  grace_minutes: graceMinutes, idle_hours: idleHours, handoff_timeout_minutes: handoffTimeoutMinutes,
  max_handoffs: maxHandoffs, retry_hours: retryHours, relay_model: relayModel,
  checkout_root: checkoutRoot, state_dir: stateDir, self_job: selfJob, service_hub_id: serviceHubId,
};

function showText(title, decisions, notRunning) {
  const rows = decisions.map((x) => ({ DECISION: x.decision, RULE: x.rule, ID: x.id, NAME: x.name,
    IDLE: x.idle_minutes, OUTCOME: x.outcome ?? '', WHY: x.reason }))
    .sort((p, q) => (p.DECISION === 'skip') - (q.DECISION === 'skip') || p.RULE.localeCompare(q.RULE) || p.NAME.localeCompare(q.NAME));
  const out = [title, formatTable(rows, ['DECISION', 'RULE', 'ID', 'NAME', 'IDLE', 'OUTCOME', 'WHY'])];
  for (const x of decisions.filter((d) => loopCount(d.loops) > 0)) out.push(`Loops in ${x.id} ${x.name}:`, ...formatLoops(x.loops));
  if (notRunning.length) out.push('', `Not running, nothing to stop (${notRunning.length}): ${notRunning.map((n) => `${n.id} ${n.name}`).join(' | ')}`);
  process.stdout.write(`${out.join('\n')}\n`);
}

const stamp = () => now.toISOString().slice(0, 16).replace('T', ' ');
const { decisions, notRunning } = decide(getAgents());

if (dryRun) {
  if (o.text) {
    showText(`session-reaper DRY RUN on ${machine} at ${stamp()} UTC - nothing was changed.  grace=${graceMinutes} min, idle=${idleHours} h, IDLE column in minutes`, decisions, notRunning);
    process.exit(0);
  }
  emit({
    event: 'reaper-plan', machine, at: now.toISOString(), dry_run: true, params,
    would_park: decisions.filter((d) => d.decision !== 'skip'),
    skipped: decisions.filter((d) => d.decision === 'skip'),
    not_running: notRunning,
  });
  process.exit(0);
}

// ---------------------------------------------------------------- run: act

mkdirSync(stateDir, { recursive: true });
const lockPath = join(stateDir, 'run.lock');
// Taken atomically ('wx'), so a manual run and a scheduled one cannot both get it. A lock older
// than 2 h is from a run that died and is taken over.
function takeLock() {
  try {
    writeFileSync(lockPath, String(process.pid), { encoding: 'utf8', flag: 'wx' });
    return true;
  } catch (e) {
    if (e.code !== 'EEXIST') throw e;
    return false;
  }
}
if (!takeLock()) {
  const ageMin = (Date.now() - statSync(lockPath).mtimeMs) / 60000;
  if (ageMin < 120) fail(EV, 'locked', `another reaper run holds ${lockPath} (for ${Math.round(ageMin)} min)`);
  rmSync(lockPath, { force: true });
  if (!takeLock()) fail(EV, 'locked', `another reaper run took ${lockPath} just now`);
}
// fail() exits the process, which skips any finally block; release the lock on every exit path.
process.on('exit', () => rmSync(lockPath, { force: true }));
// The revive commands written into notes and the ledger call the launcher; make sure it exists.
if (!existsSync(launcherPath())) installLauncher();

function park(d, note, notePath) {
  const r = claude('stop', d.id);
  const after = waitAgent(d.id, false, 20);
  if (!r.ok || (after && isRunning(after))) { d.outcome = 'stop_failed'; d.stop_output = r.text; return; }
  addLedger({
    event: 'parked', at: new Date().toISOString(), machine, id: d.id, name: d.name, cwd: d.cwd,
    sessionId: d.sessionId, resumeSessionId: d.resumeSessionId, respawnFlags: d.respawnFlags, rule: d.rule,
    reason: d.reason, idle_minutes: d.idle_minutes, last_active: d.last_active, loops: d.loops, git: d.git,
    handoff_path: notePath, handoff: note, reaper_version: REAPER_VERSION,
  });
  d.outcome = 'parked';
}

try {
  let handoffs = 0;
  for (const d of decisions) {
    if (d.decision === 'park') {
      park(d, `No handoff: ${d.reason}. Nothing was in its context worth handing off.`, '');
      continue;
    }
    if (d.decision !== 'handoff-then-park') continue;
    if (handoffs >= maxHandoffs) { d.outcome = 'deferred'; d.outcome_detail = `max ${maxHandoffs} handoffs per run`; continue; }
    handoffs++;

    // Re-check right before asking: it may have woken up while earlier handoffs ran.
    const fresh = toUtc(readJson(join(jobsDir, String(d.id), 'state.json'))?.updatedAt);
    if (fresh && Date.now() - fresh < idleHours * 3600000) { d.outcome = 'woke_up'; continue; }

    const nonce = `${d.id}-${randomUUID().replace(/-/g, '').slice(0, 8)}`;
    const relay = sendViaRelay({ id: d.id, name: d.name, cwd: d.cwd }, handoffRequest(d, nonce));
    if (!relay.ok) {
      d.outcome = 'relay_failed'; d.relay = relay.text;
      saveAttempt(d.id, 'relay_failed', relay.text);
      continue;
    }
    const wait = waitSentinel(d.transcript, nonce, handoffTimeoutMinutes, d.id);
    if (!wait.ok) {
      d.outcome = `handoff_${wait.outcome}`; d.outcome_detail = wait.detail;
      saveAttempt(d.id, wait.outcome, wait.detail);
      continue;
    }
    // Next to resume-later's own files, so `resume-later list` finds reaper handoffs too.
    mkdirSync(handoffDir, { recursive: true });
    let slug = d.name.replace(/[^\p{L}\p{N}]+/gu, '-').replace(/^-+|-+$/g, '').toLowerCase();
    if (slug.length > 48) slug = slug.slice(0, 48).replace(/-+$/, '');
    const notePath = join(handoffDir, `reaper--${d.id}-${slug}.md`);
    const header = `<!-- session-reaper parked ${d.id} (${d.name}) on ${machine} at ${new Date().toISOString()}. Revive: ${reviveCmd(d.id)} -->\n`;
    writeFileSync(notePath, `${header}${wait.note}\n`, 'utf8');
    d.handoff_path = notePath;
    park(d, wait.note, notePath);
  }
} finally {
  rmSync(lockPath, { force: true });
}

const result = {
  event: 'reaper-run', machine, at: now.toISOString(), dry_run: false, params,
  acted: decisions.filter((d) => d.decision !== 'skip'),
  skipped: decisions.filter((d) => d.decision === 'skip'),
  not_running: notRunning, ledger: ledgerPath,
};
writeJson(join(stateDir, 'last-run.json'), result);
appendLine(join(stateDir, 'runs.jsonl'), JSON.stringify({ at: now.toISOString(),
  acted: result.acted.map((d) => `${d.id} ${d.rule} ${d.outcome ?? ''}`.trim()), skipped: result.skipped.length }));

if (o.text) { showText(`session-reaper RUN on ${machine} at ${stamp()} UTC`, decisions, notRunning); process.exit(0); }
emit(result);
