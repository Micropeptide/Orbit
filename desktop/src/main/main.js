'use strict';
// Orbit desktop: a native macOS shell around Orbit's local web UI.
const { app, BrowserWindow, session, nativeImage } = require('electron');
const { prefs, windowState } = require('./prefs');
const windows = require('./windows');
const links = require('./links');
const menu = require('./menu');
const tray = require('./tray');
const status = require('./status');
const quickPanel = require('./quick-panel');
const deeplink = require('./deeplink');
const ipc = require('./ipc');
const updater = require('./updater');

// Always "Orbit" (never "Electron"), even in a dev run: Dock, notifications, userData.
app.setName('Orbit');
app.setAppUserModelId('app.orbit.desktop');

if (!app.requestSingleInstanceLock()) {
  app.quit();
  process.exit(0);
}

// Deep links can arrive before the app is ready; hold them until then.
const pendingLinks = [];
const takeLink = (link) => {
  if (!link) return;
  if (app.isReady()) deeplink.handle(link);
  else pendingLinks.push(link);
};
app.on('will-finish-launching', () => {
  app.on('open-url', (event, url) => { event.preventDefault(); takeLink(url); });
});
app.on('second-instance', (_event, argv) => {
  const link = deeplink.findLink(argv);
  if (link) takeLink(link);
  else windows.showMain();
});

if (app.isPackaged) app.setAsDefaultProtocolClient('orbit');

app.setAboutPanelOptions({
  applicationName: 'Orbit',
  applicationVersion: app.getVersion(),
  credits: 'A native home for your local Orbit AI workspace.',
  website: 'https://runtianwu.com',
});

function setKeepInMenuBar(on) {
  prefs.set('keepInMenuBar', !!on);
  if (on) tray.create(trayHooks);
  else tray.destroy();
  menu.build(menuHooks);
}

const trayHooks = {
  newChat: () => windows.sendCommand('new-chat', undefined, windows.showMain(), { queue: true }),
  quickAsk: () => quickPanel.show(),
  openOrbit: () => windows.showMain(),
  checkForUpdates: () => updater.checkNow(),
  installUpdate: () => updater.promptInstall(),
};
const menuHooks = {
  quickAsk: () => quickPanel.toggle(),
  setKeepInMenuBar,
  onPrefsChanged: () => { menu.build(menuHooks); tray.invalidate(); },
  checkForUpdates: () => updater.checkNow(),
  setUpdatePrefs: (patch) => updater.setPrefs(patch),
};

// Rebuild the app menu only when something it shows changed (not on every download tick).
let menuSignature = '';
function refreshUpdateUI() {
  const s = updater.getState();
  const sig = JSON.stringify([s.prefs, updater.lastCheckedLabel()]);
  if (sig !== menuSignature) { menuSignature = sig; menu.build(menuHooks); }
  tray.refresh();
}

/** Only Orbit's own pages get permissions (clipboard, notifications, microphone…). */
function setupPermissions() {
  const allowed = new Set(['clipboard-read', 'clipboard-sanitized-write', 'notifications', 'media', 'fullscreen', 'pointerLock']);
  const ses = session.defaultSession;
  ses.setPermissionRequestHandler((wc, permission, cb, details) => {
    cb(allowed.has(permission) && links.isOrbitURL(details.requestingUrl || wc.getURL()));
  });
  ses.setPermissionCheckHandler((_wc, permission, origin) => allowed.has(permission) && links.isOrbitURL(origin));
}

app.whenReady().then(() => {
  if (!app.isPackaged && app.dock) {
    const icon = nativeImage.createFromPath(links.appFile('assets', 'icon.png'));
    if (!icon.isEmpty()) app.dock.setIcon(icon);
  }
  setupPermissions();
  ipc.register({ quickPanel });
  menu.build(menuHooks);
  if (prefs.get('keepInMenuBar') !== false) tray.create(trayHooks);
  quickPanel.registerShortcut();
  status.start();
  updater.onState(refreshUpdateUI);
  updater.start();
  setInterval(refreshUpdateUI, 60 * 1000); // keeps "Last checked: …" current

  const firstLink = pendingLinks.shift() || deeplink.findLink(process.argv);
  windows.createMainWindow();
  if (firstLink) deeplink.handle(firstLink);
  for (const link of pendingLinks.splice(0)) deeplink.handle(link);
});

// Dock icon click with no windows open: bring Orbit back.
app.on('activate', () => {
  if (windows.mainWindows().length === 0) windows.createMainWindow();
  else if (!BrowserWindow.getFocusedWindow()) windows.showMain();
});

// Stay alive in the menu bar (macOS norm) unless the user turned that off.
// (Checked per main window: the hidden Quick Ask panel never closes.)
windows.onLastClosed(() => { if (prefs.get('keepInMenuBar') === false) app.quit(); });
app.on('window-all-closed', () => { /* handled by onLastClosed */ });

app.on('will-quit', () => {
  quickPanel.unregisterShortcut();
  status.stop();
  updater.stop();
  prefs.flushSync();
  windowState.flushSync();
  // The Orbit server is a background service: it keeps running after we quit.
});

process.on('uncaughtException', (err) => console.error('[orbit] uncaught:', err));
