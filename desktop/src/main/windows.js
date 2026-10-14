'use strict';
// Main Orbit windows: creation, bounds memory, boot page, navigation guards,
// and delivering menu/tray/quick-ask commands to the page.
const { app, BrowserWindow, nativeTheme, screen } = require('electron');
const { prefs, windowState } = require('./prefs');
const server = require('./server');
const links = require('./links');

const DEFAULT_SIZE = { width: 1240, height: 820 };
const windows = new Set();
const info = new WeakMap(); // win -> { ready, queue, activeSid, activeTitle, darkHint, autoShow }
let lastFocused = null;
const lastClosedHandlers = [];

const themeColor = (dark) => (dark ? '#1b1b1f' : '#ffffff');

// ---------- bounds ----------
function visibleOnSomeDisplay(b) {
  return screen.getAllDisplays().some(({ workArea: a }) =>
    b.x < a.x + a.width - 80 && b.x + b.width > a.x + 80 && b.y >= a.y - 10 && b.y < a.y + a.height - 80);
}

function initialBounds() {
  const s = windowState.all();
  const ok = ['x', 'y', 'width', 'height'].every((k) => Number.isFinite(s[k]));
  let b = ok ? { x: s.x, y: s.y, width: s.width, height: s.height } : { ...DEFAULT_SIZE };
  if (ok && !visibleOnSomeDisplay(b)) b = { ...DEFAULT_SIZE };
  // Cascade additional windows so they don't stack exactly.
  const n = windows.size;
  if (n > 0 && Number.isFinite(b.x)) { b.x += 26 * n; b.y += 26 * n; }
  return { bounds: b, maximized: !!s.maximized };
}

let saveTimer = null;
function saveBounds(win) {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    if (win.isDestroyed() || win.isFullScreen()) return;
    const maximized = win.isMaximized();
    const b = maximized ? { ...windowState.all() } : win.getBounds();
    windowState.replace({ x: b.x, y: b.y, width: b.width, height: b.height, maximized });
  }, 500);
}

// ---------- pages ----------
function sendBootStatus(win, text, failed = false) {
  if (!win.isDestroyed() && links.isLocalAppPage(win.webContents.getURL())) {
    win.webContents.send('orbit:boot-status', { text, failed });
  }
}

/** Load Orbit into win, showing the boot page and starting the server first if needed. */
async function loadOrbit(win) {
  if (win.isDestroyed()) return;
  if (await server.probe()) {
    win.loadURL(server.baseURL() + '/');
    return;
  }
  if (!links.isLocalAppPage(win.webContents.getURL())) await win.loadFile(links.appFile('boot.html')).catch(() => {});
  const up = await server.ensureServer((t) => sendBootStatus(win, t), win);
  if (win.isDestroyed()) return;
  if (up) {
    for (const w of windows) if (!w.isDestroyed() && links.isLocalAppPage(w.webContents.getURL())) w.loadURL(server.baseURL() + '/');
  } else {
    sendBootStatus(win, 'Orbit didn’t answer. Check that it is installed, then try again.', true);
  }
}

// ---------- creation ----------
function createMainWindow({ show = true } = {}) {
  const { bounds, maximized } = initialBounds();
  const win = new BrowserWindow({
    ...bounds,
    minWidth: 720,
    minHeight: 480,
    show: false,
    title: 'Orbit',
    titleBarStyle: 'hiddenInset',
    trafficLightPosition: { x: 14, y: 14 },
    backgroundColor: themeColor(nativeTheme.shouldUseDarkColors),
    webPreferences: {
      preload: links.appFile('preload.js'),
      contextIsolation: true,
      sandbox: true,
      nodeIntegration: false,
      spellcheck: true,
    },
  });
  windows.add(win);
  info.set(win, { ready: false, queue: [], activeSid: null, activeTitle: '', darkHint: null, autoShow: show });

  win.once('ready-to-show', () => {
    if (info.get(win).autoShow) {
      if (maximized) win.maximize();
      win.show();
    }
  });
  win.on('focus', () => { lastFocused = win; });
  for (const ev of ['resize', 'move', 'maximize', 'unmaximize']) win.on(ev, () => saveBounds(win));
  win.on('closed', () => {
    windows.delete(win);
    if (lastFocused === win) lastFocused = null;
    if (windows.size === 0) lastClosedHandlers.forEach((cb) => cb());
  });

  const wc = win.webContents;
  wc.on('did-start-navigation', ({ isMainFrame, isSameDocument }) => {
    if (isMainFrame && !isSameDocument) Object.assign(info.get(win) || {}, { ready: false, activeSid: null, activeTitle: '' });
  });
  wc.on('did-finish-load', () => applyZoom(wc));
  wc.on('did-fail-load', (_e, code, desc, url, isMainFrame) => {
    // -3 is ERR_ABORTED (e.g. a navigation replaced by another one): not a failure.
    if (isMainFrame && code !== -3 && links.isOrbitURL(url)) {
      console.warn(`[orbit] load failed (${code} ${desc}); showing the boot page`);
      win.loadFile(links.appFile('boot.html')).then(() => loadOrbit(win)).catch(() => {});
    }
  });
  guardNavigation(wc);
  // Keyboard shortcuts that macOS menus can't reliably own.
  wc.on('before-input-event', (event, input) => {
    if (input.type !== 'keyDown') return;
    if (input.control && !input.meta && !input.alt && input.key === 'Tab') {
      event.preventDefault();
      sendCommand(input.shift ? 'prev-tab' : 'next-tab', undefined, win);
    }
  });

  loadOrbit(win);
  return win;
}

// ---------- navigation guards ----------
function secureChildPrefs() {
  return { contextIsolation: true, sandbox: true, nodeIntegration: false };
}

function guardNavigation(wc) {
  wc.setWindowOpenHandler(({ url }) => {
    if (links.isPreviewURL(url)) {
      return {
        action: 'allow',
        overrideBrowserWindowOptions: {
          width: 1000, height: 760, minWidth: 360, minHeight: 240,
          backgroundColor: themeColor(nativeTheme.shouldUseDarkColors),
          webPreferences: secureChildPrefs(),
        },
      };
    }
    links.openExternal(url);
    return { action: 'deny' };
  });
  wc.on('did-create-window', (child) => guardNavigation(child.webContents));
  const guard = (event, url) => {
    if (links.isOrbitURL(url) || links.isLocalAppPage(url)) return;
    event.preventDefault();
    links.openExternal(url);
  };
  wc.on('will-navigate', guard);
  wc.on('will-redirect', (event, url, _inPlace, isMainFrame) => { if (isMainFrame) guard(event, url); });
}

// ---------- zoom ----------
function clampZoom(z) { return Math.min(3, Math.max(0.5, Math.round(z * 100) / 100)); }
function applyZoom(wc) { wc.setZoomFactor(clampZoom(Number(prefs.get('zoomFactor')) || 1)); }
function setZoom(next) {
  prefs.set('zoomFactor', clampZoom(next));
  for (const w of windows) if (!w.isDestroyed()) applyZoom(w.webContents);
}
function zoomBy(step) { setZoom((Number(prefs.get('zoomFactor')) || 1) + step); }

// ---------- lookup & commands ----------
function mainWindows() { return [...windows].filter((w) => !w.isDestroyed()); }
function isMainWindow(win) { return !!win && windows.has(win); }

/** The main window commands go to: focused, else last focused, else any. */
function targetWindow() {
  const focused = BrowserWindow.getFocusedWindow();
  if (isMainWindow(focused)) return focused;
  if (lastFocused && !lastFocused.isDestroyed()) return lastFocused;
  return mainWindows()[0] || null;
}

function showWindow(win) {
  if (!win || win.isDestroyed()) return;
  info.get(win).autoShow = true;
  if (win.isMinimized()) win.restore();
  win.show();
  win.focus();
}

/** Show (or recreate) a main window and return it. */
function showMain() {
  let win = targetWindow();
  if (!win) win = createMainWindow();
  else showWindow(win);
  app.focus({ steal: true });
  return win;
}

/** Make sure a main window exists without showing it (for background work). */
function ensureMainHidden() {
  return targetWindow() || createMainWindow({ show: false });
}

/** Local fallbacks when the page hasn't hooked up onCommand (boot page, older web UI). */
function fallback(name, win) {
  if (name === 'close-tab') win.close();
}

/**
 * Deliver a command to a window's page. If the page isn't listening yet,
 * queue page-level commands until it is (they flush on 'orbit:command-ready').
 */
function sendCommand(name, arg, win = targetWindow(), { queue = false } = {}) {
  if (!win || win.isDestroyed()) return;
  const st = info.get(win);
  if (st.ready) win.webContents.send('orbit:command', name, arg);
  else if (queue) st.queue.push([name, arg]);
  else fallback(name, win);
}

function markReady(win, ready) {
  const st = info.get(win);
  if (!st) return;
  st.ready = ready;
  if (ready && st.queue.length) {
    const q = st.queue.splice(0);
    for (const [name, arg] of q) win.webContents.send('orbit:command', name, arg);
  }
}

/** Open a chat in the visible main window. */
function openChat(sid) {
  const win = showMain();
  sendCommand('open-chat', { sid }, win, { queue: true });
}

function setActiveChat(win, sid, title) {
  const st = info.get(win);
  if (st) Object.assign(st, { activeSid: sid, activeTitle: title });
}

/** sid of the chat the user is looking at, or null when Orbit isn't focused. */
function focusedActiveSid() {
  const focused = BrowserWindow.getFocusedWindow();
  return isMainWindow(focused) ? info.get(focused).activeSid : null;
}

function activeTitle(win) {
  const st = info.get(win);
  return (st && st.activeTitle) || '';
}

function setDarkHint(win, dark) {
  const st = info.get(win);
  if (!st) return;
  st.darkHint = dark;
  win.setBackgroundColor(themeColor(dark));
}

nativeTheme.on('updated', () => {
  for (const w of mainWindows()) if (info.get(w).darkHint === null) w.setBackgroundColor(themeColor(nativeTheme.shouldUseDarkColors));
});

module.exports = {
  createMainWindow, mainWindows, isMainWindow, targetWindow, showMain, showWindow, ensureMainHidden,
  sendCommand, markReady, openChat, setActiveChat, focusedActiveSid, activeTitle, setDarkHint,
  zoomBy, setZoom, loadOrbit, onLastClosed: (cb) => lastClosedHandlers.push(cb),
};
