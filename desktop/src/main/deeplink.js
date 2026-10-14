'use strict';
// orbit:// links. A link can open a chat or pre-fill the composer, but it can
// never run anything by itself.
const windows = require('./windows');

const SID_RE = /^[A-Za-z0-9_.:-]{1,200}$/;   // chat ids: 2026…-a291, cq-<uuid>, oc-ses_…
const MAX_TEXT = 20000;

function findLink(argv) {
  return (Array.isArray(argv) ? argv : []).find((a) => typeof a === 'string' && a.toLowerCase().startsWith('orbit://')) || null;
}

/** Returns [command, arg] or null. */
function parse(link) {
  let u;
  try { u = new URL(link); } catch { return null; }
  if (u.protocol !== 'orbit:') return null;
  const parts = decodeURIComponent(u.pathname).split('/').filter(Boolean);
  if (u.hostname === 'chat' && parts.length === 1 && SID_RE.test(parts[0])) return ['open-chat', { sid: parts[0] }];
  if (u.hostname === 'new') {
    const text = (u.searchParams.get('text') || '').slice(0, MAX_TEXT);
    return ['new-chat-send', { text, draft: true }];
  }
  return null;
}

function handle(link) {
  const parsed = parse(link);
  if (!parsed) { console.warn('[orbit] ignored deep link'); return; }
  const win = windows.showMain();
  if (parsed[0] === 'new-chat-send' && !parsed[1].text) windows.sendCommand('new-chat', undefined, win, { queue: true });
  else windows.sendCommand(parsed[0], parsed[1], win, { queue: true });
}

module.exports = { findLink, parse, handle };
