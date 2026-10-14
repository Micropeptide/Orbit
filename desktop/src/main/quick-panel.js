'use strict';
// Quick Ask: a Spotlight-style floating panel toggled by Option+Space.
const { BrowserWindow, screen, globalShortcut } = require('electron');
const links = require('./links');
const windows = require('./windows');

const WIDTH = 640;
const MIN_HEIGHT = 84;
const MAX_HEIGHT = 420;
const SHORTCUT = 'Alt+Space';

let win = null;
let shownAt = 0;

function create() {
  win = new BrowserWindow({
    width: WIDTH,
    height: MIN_HEIGHT,
    show: false,
    frame: false,
    transparent: true,
    backgroundColor: '#00000000',
    vibrancy: 'popover',
    visualEffectState: 'active',
    roundedCorners: true,
    hasShadow: true,
    resizable: false,
    minimizable: false,
    maximizable: false,
    fullscreenable: false,
    skipTaskbar: true,
    alwaysOnTop: true,
    type: 'panel', // NSPanel: floats over full-screen apps and doesn't drag Orbit's windows forward
    webPreferences: {
      preload: links.appFile('quick-preload.js'),
      contextIsolation: true,
      sandbox: true,
      nodeIntegration: false,
      spellcheck: true,
    },
  });
  win.setAlwaysOnTop(true, 'floating');
  win.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  win.webContents.on('will-navigate', (e) => e.preventDefault());
  win.on('blur', () => {
    // A blur right after showing is the previous app letting go; ignore it.
    if (Date.now() - shownAt > 200) hide();
  });
  win.on('closed', () => { win = null; });
  win.loadFile(links.appFile('quick.html'));
}

function position() {
  const { workArea: a } = screen.getDisplayNearestPoint(screen.getCursorScreenPoint());
  const [, h] = win.getSize();
  win.setBounds({
    x: Math.round(a.x + (a.width - WIDTH) / 2),
    y: Math.round(a.y + a.height / 3 - Math.max(h, MIN_HEIGHT) / 2 - a.height / 12),
    width: WIDTH,
    height: h,
  });
}

function show() {
  if (!win) create();
  const reveal = () => {
    position();
    shownAt = Date.now();
    win.show();
    win.focus();
    win.webContents.send('quick:shown');
  };
  if (win.webContents.isLoading()) win.webContents.once('did-finish-load', reveal);
  else reveal();
}

function hide() {
  if (win && win.isVisible()) win.hide();
}

function toggle() {
  if (win && win.isVisible()) hide();
  else show();
}

function resize(height) {
  if (!win) return;
  const h = Math.round(Math.min(MAX_HEIGHT, Math.max(MIN_HEIGHT, height)));
  const b = win.getBounds();
  if (b.height !== h) win.setBounds({ ...b, height: h });
}

/** Enter: open Orbit and send. Cmd+Enter: send in the background without showing Orbit. */
function submit(text, background) {
  hide();
  if (background) {
    const target = windows.ensureMainHidden();
    windows.sendCommand('new-chat-send', { text, background: true }, target, { queue: true });
  } else {
    const target = windows.showMain();
    windows.sendCommand('new-chat-send', { text }, target, { queue: true });
  }
}

function isSender(wc) { return !!win && !win.isDestroyed() && wc === win.webContents; }

function registerShortcut() {
  let ok = false;
  try { ok = globalShortcut.register(SHORTCUT, toggle); } catch (err) { console.warn('[orbit]', err.message); }
  if (!ok) console.warn(`[orbit] could not register the global shortcut ${SHORTCUT}; Quick Ask stays available from the File menu`);
  return ok;
}

function unregisterShortcut() {
  try { globalShortcut.unregister(SHORTCUT); } catch { /* already gone */ }
}

module.exports = { show, hide, toggle, resize, submit, isSender, registerShortcut, unregisterShortcut, SHORTCUT };
