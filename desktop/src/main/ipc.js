'use strict';
// IPC from pages. Every handler checks who is calling and validates inputs.
const { app, ipcMain, BrowserWindow } = require('electron');
const windows = require('./windows');
const links = require('./links');
const actions = require('./actions');
const server = require('./server');

const SID_RE = /^[A-Za-z0-9_.:-]{1,200}$/;   // chat ids: 2026…-a291, cq-<uuid>, oc-ses_…

/** Only the top frame of an Orbit page or one of the app's own pages may talk to main. */
function trustedSender(event) {
  const frame = event.senderFrame;
  if (!frame || frame.parent) return false;
  return links.isOrbitURL(frame.url) || links.isLocalAppPage(frame.url);
}

function senderWindow(event) {
  return BrowserWindow.fromWebContents(event.sender);
}

function on(channel, handler) {
  ipcMain.on(channel, (event, ...args) => {
    if (!trustedSender(event)) {
      console.warn(`[orbit] ignored ${channel} from untrusted frame`);
      if (channel.endsWith(':sync')) event.returnValue = null;
      return;
    }
    try { handler(event, ...args); } catch (err) { console.error(`[orbit] ${channel} failed:`, err); }
  });
}

function register({ quickPanel }) {
  on('orbit:app-info:sync', (event) => {
    event.returnValue = { version: app.getVersion() };
  });

  // The page has (or no longer has) an onCommand listener.
  on('orbit:command-ready', (event, ready) => {
    const win = senderWindow(event);
    if (windows.isMainWindow(win) && typeof ready === 'boolean') windows.markReady(win, ready);
  });

  on('orbit:set-active-chat', (event, sid, title) => {
    const win = senderWindow(event);
    if (!windows.isMainWindow(win)) return;
    const okSid = sid === null || sid === undefined || sid === '' ? null : (typeof sid === 'string' && SID_RE.test(sid) ? sid : undefined);
    if (okSid === undefined) return;
    const okTitle = typeof title === 'string' ? title.slice(0, 300) : '';
    windows.setActiveChat(win, okSid, okSid ? okTitle : '');
  });

  on('orbit:export-pdf', (event) => {
    const win = senderWindow(event);
    if (windows.isMainWindow(win)) actions.exportPDF(win);
  });

  on('orbit:open-external', (event, url) => {
    if (typeof url === 'string' && url.length <= 8192) links.openExternal(url);
  });

  on('orbit:quick-ask', () => quickPanel.show());

  on('orbit:set-titlebar-dark', (event, dark) => {
    const win = senderWindow(event);
    if (windows.isMainWindow(win) && typeof dark === 'boolean') windows.setDarkHint(win, dark);
  });

  // Boot page buttons.
  on('orbit:boot-retry', (event) => {
    const win = senderWindow(event);
    if (windows.isMainWindow(win) && links.isLocalAppPage(event.senderFrame.url)) windows.loadOrbit(win);
  });
  on('orbit:boot-choose-root', async (event) => {
    const win = senderWindow(event);
    if (!windows.isMainWindow(win) || !links.isLocalAppPage(event.senderFrame.url)) return;
    if (await server.chooseOrbitRoot(win)) windows.loadOrbit(win);
  });

  // Quick Ask panel.
  on('quick:submit', (event, text, background) => {
    if (!quickPanel.isSender(event.sender)) return;
    if (typeof text !== 'string' || typeof background !== 'boolean') return;
    const t = text.trim();
    if (!t || t.length > 100000) return;
    quickPanel.submit(t, background);
  });
  on('quick:hide', (event) => { if (quickPanel.isSender(event.sender)) quickPanel.hide(); });
  on('quick:resize', (event, height) => {
    if (quickPanel.isSender(event.sender) && Number.isFinite(height)) quickPanel.resize(height);
  });
}

module.exports = { register };
