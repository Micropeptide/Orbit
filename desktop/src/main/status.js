'use strict';
// Polls the Orbit server for running/waiting chats and drives the dock badge,
// dock bounce and notifications. Listeners (the tray) get every snapshot.
const { app, BrowserWindow, Notification } = require('electron');
const { prefs } = require('./prefs');
const server = require('./server');
const windows = require('./windows');

const FAST_MS = 4000;
const SLOW_MS = 15000;

const state = {
  up: false,
  running: [],      // sids answering now
  waiting: [],      // sids waiting on the user
  since: {},        // sid -> epoch seconds the answer started
  sessions: new Map(), // sid -> { title, unread, external, archived }
};
const listeners = new Set();
let baseline = true; // the first good poll (at launch or after an outage) only records state
let timer = null;
let stopped = false;
let polling = false;
const live = new Set();

const title = (sid) => (state.sessions.get(sid) || {}).title || 'Untitled chat';
const isExternal = (sid) => !!(state.sessions.get(sid) || {}).external;

function appFocused() { return !!BrowserWindow.getFocusedWindow(); }

/** True when the user is already looking at this chat in a focused Orbit window. */
function looking(sid) { return appFocused() && windows.focusedActiveSid() === sid; }

function notify(heading, sid) {
  if (!prefs.get('notifications') || !Notification.isSupported()) return;
  const n = new Notification({ title: heading, body: title(sid), silent: false });
  live.add(n); // keep a reference so the click handler survives garbage collection
  const done = () => live.delete(n);
  n.on('click', () => { done(); windows.openChat(sid); });
  n.on('close', done);
  n.show();
  setTimeout(done, 10 * 60 * 1000);
}

function updateBadge() {
  const ids = new Set(state.waiting.filter((s) => !isExternal(s)));
  for (const [sid, s] of state.sessions) if (s.unread && !s.external && !s.archived) ids.add(sid);
  const n = ids.size;
  if (app.dock) app.dock.setBadge(n > 0 ? String(n) : '');
  else app.setBadgeCount(n);
}

function applySnapshot(running, sessions) {
  const nextRunning = Array.isArray(running.running) ? running.running.filter((s) => typeof s === 'string') : [];
  const nextWaiting = Array.isArray(running.waiting) ? running.waiting.filter((s) => typeof s === 'string') : [];
  if (sessions && Array.isArray(sessions.items)) {
    const map = new Map();
    for (const it of sessions.items) {
      if (!it || typeof it.id !== 'string') continue;
      map.set(it.id, {
        title: typeof it.title === 'string' && it.title.trim() ? it.title.trim() : 'Untitled chat',
        unread: it.unread === true,
        external: it.external === true,
        archived: it.archived === true,
      });
    }
    state.sessions = map;
  }

  if (!baseline) {
    const nowRunning = new Set(nextRunning);
    const wasWaiting = new Set(state.waiting);
    for (const sid of state.running) {
      if (!nowRunning.has(sid) && !isExternal(sid) && !looking(sid)) notify('Answer ready', sid);
    }
    let newlyWaiting = false;
    for (const sid of nextWaiting) {
      if (wasWaiting.has(sid) || isExternal(sid)) continue;
      newlyWaiting = true;
      if (!looking(sid)) notify('Needs your approval', sid);
    }
    if (newlyWaiting && !appFocused() && app.dock) app.dock.bounce('informational');
  }
  baseline = false;

  state.running = nextRunning;
  state.waiting = nextWaiting;
  state.since = running.since && typeof running.since === 'object' ? running.since : {};
}

async function poll() {
  if (polling) return;
  polling = true;
  let ok = false;
  try {
    const [running, sessions] = await Promise.all([
      server.getJSON('/api/running'),
      server.getJSON('/api/sessions', 4000).catch(() => null),
    ]);
    applySnapshot(running, sessions);
    ok = true;
  } catch {
    ok = false;
  }
  if (!ok && state.up) baseline = true; // after an outage, don't treat everything as "finished"
  state.up = ok;
  updateBadge();
  for (const cb of listeners) { try { cb(state); } catch (err) { console.error('[orbit] status listener:', err); } }
  polling = false;
  clearTimeout(timer);
  if (!stopped) timer = setTimeout(poll, ok ? FAST_MS : SLOW_MS);
}

function start() { stopped = false; clearTimeout(timer); poll(); }
function stop() { stopped = true; clearTimeout(timer); }
function onChange(cb) { listeners.add(cb); return () => listeners.delete(cb); }
/** Poll right away (e.g. after the user acts) instead of waiting for the next tick. */
function refresh() { if (!stopped) { clearTimeout(timer); poll(); } }

module.exports = { start, stop, onChange, refresh, state, title };
