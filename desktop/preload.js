'use strict';
// Bridge between the Orbit web UI and the desktop shell (sandboxed preload).
const { contextBridge, ipcRenderer } = require('electron');

const info = ipcRenderer.sendSync('orbit:app-info:sync') || {};
const listeners = new Set();
const updateListeners = new Set();

ipcRenderer.on('orbit:command', (_event, name, arg) => {
  for (const cb of [...listeners]) {
    try { cb(name, arg); } catch (err) { console.error('[orbitDesktop] command handler failed:', err); }
  }
});

ipcRenderer.on('orbit:updates:state', (_event, state) => {
  for (const cb of [...updateListeners]) {
    try { cb(state); } catch (err) { console.error('[orbitDesktop] update handler failed:', err); }
  }
});

contextBridge.exposeInMainWorld('orbitDesktop', {
  isDesktop: true,
  platform: process.platform,
  version: String(info.version || ''),

  /** cb(name, arg) for menu/tray/shortcut commands. Returns an unsubscribe function. */
  onCommand(cb) {
    if (typeof cb !== 'function') throw new TypeError('onCommand expects a function');
    listeners.add(cb);
    if (listeners.size === 1) ipcRenderer.send('orbit:command-ready', true);
    return () => {
      if (listeners.delete(cb) && listeners.size === 0) ipcRenderer.send('orbit:command-ready', false);
    };
  },
  /** Tell the shell which chat this window shows (null/'' when none). */
  setActiveChat(sid, title) { ipcRenderer.send('orbit:set-active-chat', sid ?? null, title ?? ''); },
  exportPDF() { ipcRenderer.send('orbit:export-pdf'); },
  openExternal(url) { ipcRenderer.send('orbit:open-external', String(url)); },
  quickAsk() { ipcRenderer.send('orbit:quick-ask'); },
  setTitleBarDark(dark) { ipcRenderer.send('orbit:set-titlebar-dark', !!dark); },

  /** App updates. Every call resolves to the state: {current, latest, available, downloading, progress, staged, error, lastCheck, prefs}. */
  updates: {
    getState() { return ipcRenderer.invoke('orbit:updates:get'); },
    check() { return ipcRenderer.invoke('orbit:updates:check'); },
    install() { return ipcRenderer.invoke('orbit:updates:install'); },
    /** Any of {autoUpdate: 'auto'|'notify'|'off', updateCheckEvery: 1|6|24|168, updateChannel: 'stable'|'beta'}; rejects on bad values. */
    setPrefs(p) {
      const src = p && typeof p === 'object' ? p : {};
      return ipcRenderer.invoke('orbit:updates:set-prefs', {
        autoUpdate: src.autoUpdate, updateCheckEvery: src.updateCheckEvery, updateChannel: src.updateChannel,
      });
    },
    /** cb(state) on every change. Returns an unsubscribe function. */
    onState(cb) {
      if (typeof cb !== 'function') throw new TypeError('onState expects a function');
      updateListeners.add(cb);
      return () => { updateListeners.delete(cb); };
    },
  },
});

// The built-in "Starting Orbit…" page gets two extra buttons' worth of API.
if (location.protocol === 'file:') {
  contextBridge.exposeInMainWorld('orbitBoot', {
    retry() { ipcRenderer.send('orbit:boot-retry'); },
    chooseFolder() { ipcRenderer.send('orbit:boot-choose-root'); },
    onStatus(cb) {
      if (typeof cb !== 'function') return;
      ipcRenderer.on('orbit:boot-status', (_e, s) => cb(s));
    },
  });
}
