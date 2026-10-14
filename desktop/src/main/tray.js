'use strict';
// Menu-bar icon: count of answering chats plus a menu of chats that need you.
const { app, Tray, Menu, nativeImage } = require('electron');
const links = require('./links');
const status = require('./status');
const windows = require('./windows');
const actions = require('./actions');

const MAX_ROWS = 8;
let tray = null;
let unsubscribe = null;
let lastSignature = '';
let hooks = { newChat() {}, quickAsk() {}, openOrbit() {} };

function elapsed(sinceEpoch) {
  const secs = Math.max(0, Math.floor(Date.now() / 1000 - Number(sinceEpoch)));
  if (!Number.isFinite(secs)) return '';
  if (secs < 60) return "<1m";
  if (secs < 3600) return `${Math.floor(secs / 60)}m`;
  return `${Math.floor(secs / 3600)}h ${Math.floor((secs % 3600) / 60)}m`;
}

function short(text, n = 46) {
  return text.length > n ? text.slice(0, n - 1) + '…' : text;
}

function rows(st) {
  const out = [];
  const seen = new Set();
  for (const sid of st.waiting) {
    if (seen.has(sid)) continue;
    seen.add(sid);
    out.push({ sid, label: `${short(status.title(sid))} — needs you` });
  }
  for (const sid of st.running) {
    if (seen.has(sid)) continue;
    seen.add(sid);
    const t = st.since[sid] ? ` · ${elapsed(st.since[sid])}` : '';
    out.push({ sid, label: `${short(status.title(sid))}${t}` });
  }
  return out.slice(0, MAX_ROWS);
}

function render(st) {
  if (!tray) return;
  const n = st.running.length;
  const m = st.waiting.length;
  tray.setTitle(st.up && n > 0 ? String(n) : '', { fontType: 'monospacedDigit' });

  const header = st.up ? `Orbit — ${n} answering · ${m} need${m === 1 ? 's' : ''} you` : 'Orbit — not responding';
  const items = st.up ? rows(st) : [];
  const loginOn = actions.launchAtLogin();
  const signature = JSON.stringify([header, items, loginOn]);
  tray.setToolTip(header);
  if (signature === lastSignature) return;
  lastSignature = signature;

  const template = [
    { label: header, enabled: false },
    ...items.map(({ sid, label }) => ({ label, click: () => windows.openChat(sid) })),
    { type: 'separator' },
    { label: 'New Chat', click: () => hooks.newChat() },
    { label: 'Quick Ask…', click: () => hooks.quickAsk() },
    { label: 'Open Orbit', click: () => hooks.openOrbit() },
    { type: 'separator' },
    { label: 'Stop Local Model', enabled: st.up, click: () => actions.stopLocalModel().then(status.refresh) },
    {
      label: 'Launch at Login', type: 'checkbox', checked: loginOn,
      click: (item) => { actions.setLaunchAtLogin(item.checked); lastSignature = ''; },
    },
    { label: 'Quit Orbit', click: () => app.quit() },
  ];
  tray.setContextMenu(Menu.buildFromTemplate(template));
}

function create(h) {
  if (tray) return;
  hooks = { ...hooks, ...h };
  const img = nativeImage.createFromPath(links.appFile('build', 'trayTemplate.png'));
  img.setTemplateImage(true);
  tray = new Tray(img);
  tray.setToolTip('Orbit');
  lastSignature = '';
  render(status.state);
  unsubscribe = status.onChange(render);
}

function destroy() {
  if (unsubscribe) unsubscribe();
  unsubscribe = null;
  if (tray) tray.destroy();
  tray = null;
}

/** Re-render after a pref outside the tray changed (e.g. Launch at Login from the app menu). */
function invalidate() { lastSignature = ''; render(status.state); }

module.exports = { create, destroy, invalidate, exists: () => !!tray };
