/**
 * Session messaging plugin for OpenCode.
 *
 * Provides directed messaging between independent top-level sessions on the
 * same host (opencode.web container, codey.lehel.xyz):
 *   session_register(name) -> session_list() -> session_send(to, text, mode)
 *   -> session_check()
 *
 * Parent<->subagent sessions stay native (session.create parentID /
 * children). This plugin fills the gap for independent sessions: a
 * first-class send_message(target, message) plus name->ID discovery.
 *
 * Delivery modes (locked scope):
 *   notify (default): inject context via prompt with noReply:true, never
 *     interrupts a busy turn. Target reads on next poll.
 *   ask: prompt without noReply, triggers a model turn in the target.
 *     Use only when you want the target to act now.
 *
 * Registry: JSON file at ~/.local/share/opencode/session-registry.json
 * ($SESSION_REGISTRY override). Persists via the opencode_root volume and
 * survives session DB pruning. Scope v1: opencode<->opencode only.
 */

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const NAME_RE = /^[a-z0-9]+(-[a-z0-9]+)*$/;
const MAX_NAME_LEN = 64;

export function defaultRegistryPath() {
  const override = (process.env.SESSION_REGISTRY || '').trim();
  if (override) return override;
  return path.join(os.homedir(), '.local', 'share', 'opencode', 'session-registry.json');
}

export function validateSessionName(name) {
  if (typeof name !== 'string' || !NAME_RE.test(name.trim()) || name.trim().length > MAX_NAME_LEN) {
    throw new Error(`invalid session name "${name}": use kebab-case, e.g. bob-infra`);
  }
  return name.trim();
}

export function normalizeMode(mode) {
  if (mode === undefined || mode === null || mode === '') return 'notify';
  if (mode === 'notify' || mode === 'ask') return mode;
  throw new Error(`invalid mode "${mode}": expected notify or ask`);
}

export function formatEnvelope({ from, text, thread, replyTo }) {
  const sender = validateSessionName(from);
  if (typeof text !== 'string' || !text.trim()) throw new Error('message text must not be empty');
  const parts = [`[from:${sender}]`];
  if (thread) parts.push(`[thread:${String(thread).trim()}]`);
  if (replyTo) parts.push(`[reply_to:${String(replyTo).trim()}]`);
  return `${parts.join('')}\n\n${text.trim()}`;
}

export function readRegistry(registryPath = defaultRegistryPath()) {
  try {
    const raw = fs.readFileSync(registryPath, 'utf8');
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) return parsed;
    return {};
  } catch (err) {
    if (err && err.code === 'ENOENT') return {};
    if (err instanceof SyntaxError) return {};
    throw err;
  }
}

export function writeRegistry(registryPath = defaultRegistryPath(), data = {}) {
  const dir = path.dirname(registryPath);
  fs.mkdirSync(dir, { recursive: true, mode: 0o700 });
  const tmp = `${registryPath}.tmp.${process.pid}`;
  fs.writeFileSync(tmp, JSON.stringify(data, null, 2), { mode: 0o600 });
  fs.renameSync(tmp, registryPath);
  try {
    fs.chmodSync(registryPath, 0o600);
  } catch {
    // best effort; rename already preserved content
  }
}

const SESSION_ID_RE = /^(ses_[A-Za-z0-9]+|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$/i;

export function looksLikeSessionID(value) {
  return typeof value === 'string' && SESSION_ID_RE.test(value.trim());
}

// Resolve to a registry name -> session ID, or a raw session ID passthrough.
// Returns null when `to` is neither, so the caller can attempt a title lookup.
export function resolveTarget(to, registry = {}) {
  if (typeof to !== 'string' || !to.trim()) throw new Error('target session must not be empty');
  const key = to.trim();
  if (registry[key] && registry[key].sessionID) return registry[key].sessionID;
  if (looksLikeSessionID(key)) return key; // raw session ID passthrough
  return null;
}

// Match live, top-level sessions by title, in tiers: exact (case-sensitive) ->
// case-insensitive -> substring. Returns [] if nothing matches any tier.
export function matchSessionsByTitle(sessions, query, { excludeId } = {}) {
  const q = typeof query === 'string' ? query.trim() : '';
  if (!q) return [];
  const candidates = (Array.isArray(sessions) ? sessions : []).filter(
    (s) => s && s.id && !s.parentID && s.id !== excludeId && typeof s.title === 'string' && s.title
  );
  const tiers = [
    (s) => s.title === q,
    (s) => s.title.toLowerCase() === q.toLowerCase(),
    (s) => s.title.toLowerCase().includes(q.toLowerCase()),
  ];
  for (const predicate of tiers) {
    const hits = candidates.filter(predicate);
    if (hits.length) return hits;
  }
  return [];
}

// Resolve `to` to a target session ID: registered name -> raw ID -> live title.
async function resolveTargetLive(to, registry, client, context) {
  const direct = resolveTarget(to, registry);
  if (direct) return direct;

  const key = to.trim();
  let sessions = [];
  try {
    const res = await client.session.list();
    sessions = res.data || res || [];
  } catch {
    sessions = [];
  }

  const matches = matchSessionsByTitle(sessions, key, { excludeId: context && context.sessionID });
  if (matches.length === 1) return matches[0].id;
  if (matches.length > 1) {
    const list = matches.map((s) => `${s.id} "${s.title}"`).join(', ');
    throw new Error(`target "${key}" is ambiguous; match one of: ${list}`);
  }

  const available = sessions
    .filter((s) => s && s.id && !s.parentID && s.id !== (context && context.sessionID))
    .slice(0, 20)
    .map((s) => `${s.id} "${s.title || 'untitled'}"`)
    .join(', ');
  throw new Error(
    `no session matches "${key}". ${available ? `live sessions: ${available}` : 'no live sessions; use session_register first'}`
  );
}

function nameForSessionID(registry, sessionID) {
  for (const [name, entry] of Object.entries(registry)) {
    if (entry && entry.sessionID === sessionID) return name;
  }
  return 'unknown';
}

function textOfPart(part) {
  if (!part || typeof part !== 'object') return '';
  if (typeof part.text === 'string') return part.text;
  if (typeof part.content === 'string') return part.content;
  return '';
}

export const SessionMessagingPlugin = async ({ client }) => {
  const { tool } = await import('@opencode-ai/plugin');

  return {
    tool: {
      session_register: tool({
        description: 'Register this session under a kebab-case name for inter-session messaging.',
        args: {
          name: tool.schema.string().describe('Unique session name, e.g. bob-infra'),
          title: tool.schema.string().optional().describe('Optional human title stored in registry'),
        },
        async execute(args, context) {
          const name = validateSessionName(args.name);
          const registryPath = defaultRegistryPath();
          const registry = readRegistry(registryPath);
          registry[name] = {
            sessionID: context.sessionID,
            title: args.title || '',
            directory: context.directory || '',
            updatedAt: new Date().toISOString(),
          };
          writeRegistry(registryPath, registry);
          return `registered as ${name} (session ${context.sessionID})`;
        },
      }),

      session_list: tool({
        description: 'List registered sessions by name plus unregistered live sessions (by title and ID).',
        args: {},
        async execute(_args, context) {
          const registry = readRegistry();
          let sessions = [];
          try {
            const res = await client.session.list();
            sessions = res.data || res || [];
          } catch {
            sessions = [];
          }
          const byId = new Map(sessions.map((s) => [s.id, s]));
          const registeredIds = new Set(
            Object.values(registry).map((e) => e && e.sessionID).filter(Boolean)
          );

          const lines = Object.entries(registry).map(([name, e]) => {
            const live = byId.get(e.sessionID);
            return `- ${name} -> ${e.sessionID}${e.title ? ` "${e.title}"` : ''}${live && live.title ? ` (live: "${live.title}")` : ''}`;
          });

          const unregistered = sessions
            .filter(
              (s) => s && s.id && !registeredIds.has(s.id) && !s.parentID && s.id !== (context && context.sessionID)
            )
            .sort((a, b) => ((b.time && b.time.updated) || 0) - ((a.time && a.time.updated) || 0))
            .slice(0, 20)
            .map((s) => `- (unregistered) ${s.id} "${s.title || 'untitled'}"${s.directory ? ` [${s.directory}]` : ''}`);

          const parts = [];
          parts.push(lines.length ? lines.join('\n') : 'no registered sessions; use session_register first');
          if (unregistered.length) {
            parts.push(`Unregistered live sessions (addressable by raw id or title):\n${unregistered.join('\n')}`);
          }
          return parts.join('\n\n');
        },
      }),

      session_send: tool({
        description: 'Send a message to another session. Target by registered name, raw session ID, or live title. notify (default) injects context; ask triggers a model turn.',
        args: {
          to: tool.schema.string().describe('Target: registered session name, raw session ID, or a live session title'),
          text: tool.schema.string().describe('Message body: task, evidence refs, next action'),
          mode: tool.schema.string().optional().describe('notify (default) or ask'),
          thread: tool.schema.string().optional().describe('Thread/topic id for grouping'),
          reply_to: tool.schema.string().optional().describe('Message id this replies to'),
        },
        async execute(args, context) {
          if (!args.text || !args.text.trim()) throw new Error('message text must not be empty');
          const mode = normalizeMode(args.mode);
          const registry = readRegistry();
          const targetID = await resolveTargetLive(args.to, registry, client, context);
          const from = nameForSessionID(registry, context.sessionID);
          const envelope = formatEnvelope({
            from: from === 'unknown' ? 'unknown' : from,
            text: args.text,
            thread: args.thread,
            replyTo: args.reply_to,
          });
          await client.session.prompt({
            path: { id: targetID },
            body: {
              parts: [{ type: 'text', text: envelope }],
              ...(mode === 'notify' ? { noReply: true } : {}),
            },
          });
          return mode === 'notify'
            ? `notified ${args.to} (context injected, target reads on next poll)`
            : `message sent to ${args.to} (model turn triggered)`;
        },
      }),

      session_check: tool({
        description: 'Check this session for incoming inter-session messages.',
        args: {
          limit: tool.schema.number().optional().describe('Max messages to scan (default 30)'),
        },
        async execute(args, context) {
          const limit = args.limit || 30;
          const res = await client.session.messages({ path: { id: context.sessionID } });
          const items = res.data || res || [];
          const hits = [];
          for (const item of items.slice(-limit)) {
            for (const part of item.parts || []) {
              const text = textOfPart(part);
              if (text.includes('[from:')) hits.push(text.split('\n\n')[0]);
            }
          }
          if (hits.length === 0) return 'no incoming session messages';
          return hits.join('\n');
        },
      }),
    },
  };
};
