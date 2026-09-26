// What a session's transcript says about it: when it was last /cleared, whether anything real
// happened after that, which loops are still armed, and whether a handoff reply has arrived.
import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

// state.json dates arrive as ISO strings or as epoch milliseconds.
export function toUtc(v) {
  if (v === null || v === undefined || v === '') return null;
  const d = typeof v === 'number' ? new Date(v) : new Date(String(v));
  return Number.isNaN(d.getTime()) ? null : d;
}

export function minutesSince(d, now) {
  return d ? Math.round((now - d) / 60000) : null;
}

export const iso = (d) => (d ? d.toISOString() : null);

export function textContent(content) {
  if (content === null || content === undefined) return '';
  if (typeof content === 'string') return content;
  return (Array.isArray(content) ? content : [content]).filter((c) => c?.type === 'text').map((c) => c.text).join('\n');
}

// The transcript is <projects>/<slug>/<resumeSessionId>.jsonl. The slug rules differ per OS, so
// look the file up by name instead of computing the directory.
export function findTranscript(claudeHome, sessionId, fallback) {
  if (sessionId) {
    const projects = join(claudeHome, 'projects');
    let dirs = [];
    try { dirs = readdirSync(projects, { withFileTypes: true }).filter((d) => d.isDirectory()); } catch { /* none */ }
    for (const d of dirs) {
      const p = join(projects, d.name, `${sessionId}.jsonl`);
      if (existsSync(p)) return p;
    }
  }
  return fallback && existsSync(fallback) ? fallback : null;
}

const readLines = (path) => readFileSync(path, 'utf8').split(/\r?\n/);
const parse = (l) => { try { return JSON.parse(l); } catch { return null; } };

// One pass over the transcript. Crons are session-only - they die with the process, on
// `claude stop` and on `claude respawn` alike - so this is the only record of them a revive has.
export function transcriptFacts(path, now) {
  const facts = { path, cleared_at: null, prompted_after_clear: false, last_record_at: null, crons: [], wakeup: null, loop_command: null };
  if (!path) return facts;
  const lines = readLines(path);
  let clearIdx = -1;
  const cronUses = new Map();
  const cronsById = new Map();
  const deleted = new Set();
  lines.forEach((l, i) => {
    // Cheap prefilter before parsing; independent of JSON spacing.
    if (!(l.includes('<command-name>/') || l.includes('Cron') || l.includes('ScheduleWakeup') || l.includes('Scheduled '))) return;
    const r = parse(l);
    if (!r) return;
    const content = r?.message?.content;
    const at = toUtc(r?.timestamp);
    if (typeof content === 'string') {
      // A slash command the user typed is a user record whose content IS the command markup.
      // A tool result that merely quotes "/clear" is an array and never lands here.
      if (/^\s*<command-name>\/clear<\/command-name>/.test(content)) clearIdx = i;
      else {
        const m = content.match(/^\s*<command-name>\/loop<\/command-name>[\s\S]*?<command-args>([\s\S]*?)<\/command-args>/);
        if (m) facts.loop_command = { args: m[1].trim(), at: iso(at) };
      }
      return;
    }
    for (const c of Array.isArray(content) ? content : []) {
      if (c?.type === 'tool_use') {
        if (c.name === 'CronCreate') cronUses.set(String(c.id), c.input);
        else if (c.name === 'CronDelete' && c.input?.id) deleted.add(String(c.input.id));
        else if (c.name === 'ScheduleWakeup') {
          facts.wakeup = { at: iso(at), stop: Boolean(c.input?.stop), delaySeconds: c.input?.delaySeconds ?? null,
            prompt: c.input?.prompt ?? null, reason: c.input?.reason ?? null };
        }
      } else if (c?.type === 'tool_result' && cronUses.has(String(c.tool_use_id))) {
        const m = textContent(c.content).match(/job ([0-9a-zA-Z]{6,})/);
        if (m) {
          const inp = cronUses.get(String(c.tool_use_id));
          cronsById.set(m[1], { id: m[1], cron: inp?.cron ?? null, recurring: Boolean(inp?.recurring),
            prompt: inp?.prompt ?? null, created_at: at });
        }
      }
    }
  });

  // Recurring crons auto-expire after 7 days; one-shots are kept - whether they fired is unknown.
  const week = 7 * 24 * 3600 * 1000;
  facts.crons = [...cronsById.values()]
    .filter((c) => !deleted.has(c.id) && (!c.recurring || !c.created_at || now - c.created_at < week))
    .map((c) => ({ ...c, created_at: iso(c.created_at) }));
  if (facts.wakeup?.stop) facts.wakeup = null;

  for (let j = lines.length - 1; j >= 0; j--) {
    const m = lines[j].match(/"timestamp":"([^"]+)"/);
    if (m) { facts.last_record_at = toUtc(m[1]); break; }
  }

  if (clearIdx >= 0) {
    facts.cleared_at = toUtc(parse(lines[clearIdx])?.timestamp);
    // Anything Claude said, or any real prompt (typed, remote or from a peer), after the /clear
    // means the session is in use again.
    for (let k = clearIdx + 1; k < lines.length; k++) {
      const r = parse(lines[k]);
      if (!r) continue;
      if (r.type === 'assistant') { facts.prompted_after_clear = true; break; }
      if (r.type !== 'user' || r.isMeta) continue;
      const txt = textContent(r?.message?.content);
      if (/^\s*<(command-name|command-message|local-command-)/.test(txt)) continue;
      if (txt.trim()) { facts.prompted_after_clear = true; break; }
    }
  }
  return facts;
}

// The handoff note between the markers, from an ASSISTANT record only - the request itself
// carries the nonce too.
export function findSentinel(path, nonce) {
  if (!path || !existsSync(path)) return null;
  const esc = nonce.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const re = new RegExp(`<<REAPER-HANDOFF ${esc}>>([\\s\\S]*?)<<END-REAPER-HANDOFF ${esc}>>`);
  const lines = readLines(path);
  for (let i = lines.length - 1; i >= 0; i--) {
    if (!lines[i].includes(`END-REAPER-HANDOFF ${nonce}`)) continue;
    const r = parse(lines[i]);
    if (r?.type !== 'assistant') continue;
    const m = textContent(r?.message?.content).match(re);
    if (m) return m[1].trim();
  }
  return null;
}
