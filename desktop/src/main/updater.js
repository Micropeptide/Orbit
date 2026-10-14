'use strict';
// Updates from GitHub Releases. The app is only ad-hoc signed, so Squirrel
// (Electron's autoUpdater) can't apply updates. Instead we download the
// release zip, check it against SHA256SUMS.txt, unpack it, and let a small
// shell script swap the bundle once this process has exited.
const fs = require('fs');
const fsp = require('fs/promises');
const os = require('os');
const path = require('path');
const crypto = require('crypto');
const { execFile, spawn } = require('child_process');
const { app, net, dialog, Notification, BrowserWindow, powerMonitor } = require('electron');
const { prefs } = require('./prefs');
const links = require('./links');
const server = require('./server');
const windows = require('./windows');
const core = require('./update-core');

const FIRST_CHECK_DELAY_MS = 30 * 1000;
const MIN_DELAY_MS = 5 * 1000;
const RETRY_MS = 60 * 60 * 1000;           // after a failed check
const IDLE_MS = 2 * 60 * 1000;             // no Orbit window focused for this long
const IDLE_POLL_MS = 20 * 1000;
const API_TIMEOUT_MS = 20 * 1000;
const STALL_MS = 60 * 1000;                // download: no bytes for this long
const MAX_ZIP_BYTES = 1024 * 1024 * 1024;
const MAX_TIMER_MS = 2 ** 31 - 1;
const RATE_LIMITED = 'GitHub is rate-limiting; try later.';

const state = {
  checking: false,
  latest: null,       // { version, notes, url, publishedAt, prerelease }
  available: false,
  downloading: false,
  progress: null,     // 0..1 while downloading
  staged: null,       // version that is downloaded, verified and ready
  error: null,
};
let release = null;     // full pick from update-core (asset URLs included)
let staged = null;      // { version, appPath, dir }
let checking = null;    // in-flight check promise
let downloading = null; // in-flight download promise
let installing = false;
let notifiedVersion = null;
let lastFailureAt = 0;
let checkTimer = null;
let idleTimer = null;
let unfocusedSince = null;
let started = false;
const listeners = new Set();
const live = new Set(); // notifications, kept so click handlers survive GC

const current = () => app.getVersion();
const settings = () => core.effectivePrefs((k) => prefs.get(k));
const errText = (err) => String((err && err.message) || err || 'Unknown error');

// ---------- state ----------
function getState() {
  return {
    current: current(),
    latest: state.latest ? { ...state.latest } : null,
    available: state.available,
    checking: state.checking,
    downloading: state.downloading,
    progress: state.progress,
    staged: state.staged,
    error: state.error,
    lastCheck: Number(prefs.get('lastUpdateCheck')) || null,
    prefs: settings(),
  };
}

let emitQueued = false;
function emit() {
  if (emitQueued) return;
  emitQueued = true;
  setImmediate(() => {
    emitQueued = false;
    const s = getState();
    for (const cb of listeners) { try { cb(s); } catch (err) { console.error('[orbit] update listener:', err); } }
  });
}

function onState(cb) { listeners.add(cb); return () => listeners.delete(cb); }

/** Version to offer in the tray ("Install Update <ver>…"), or null. */
function pendingVersion() {
  if (!state.available || !state.latest) return null;
  return state.latest.version === settings().skippedVersion ? null : state.latest.version;
}

function lastCheckedLabel() {
  return `Last checked: ${core.relativeTime(prefs.get('lastUpdateCheck'))}`;
}

// ---------- network ----------
async function getFromGitHub(url) {
  let res;
  try {
    res = await net.fetch(url, {
      headers: { Accept: 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28' },
      signal: AbortSignal.timeout(API_TIMEOUT_MS),
    });
  } catch (err) {
    throw new Error(`Couldn’t reach GitHub (${errText(err)}).`);
  }
  if (res.status === 403 || res.status === 429) throw new Error(RATE_LIMITED);
  if (!res.ok) throw new Error(`GitHub answered HTTP ${res.status}.`);
  if (res.url && !res.url.startsWith('https://')) throw new Error('Unexpected redirect from GitHub.');
  return res;
}

/** Stream url to dest (following https redirects), hashing as it goes. */
function download(url, dest, onProgress) {
  return new Promise((resolve, reject) => {
    const req = net.request({ url, redirect: 'manual' });
    let redirects = 0;
    let settled = false;
    let stall = null;
    const finish = (err, value) => {
      if (settled) return;
      settled = true;
      clearTimeout(stall);
      if (err) { try { req.abort(); } catch { /* already done */ } reject(err); } else resolve(value);
    };
    const armStall = () => {
      clearTimeout(stall);
      stall = setTimeout(() => finish(new Error('The download stalled.')), STALL_MS);
    };
    req.on('redirect', (_status, _method, redirectUrl) => {
      if (++redirects > 10 || !String(redirectUrl).startsWith('https://')) {
        finish(new Error('Unexpected download redirect.'));
        return;
      }
      req.followRedirect();
    });
    req.on('response', (res) => {
      if (res.statusCode !== 200) { finish(new Error(`Download failed: HTTP ${res.statusCode}.`)); return; }
      const lenHeader = res.headers['content-length'];
      const total = Number(Array.isArray(lenHeader) ? lenHeader[0] : lenHeader) || 0;
      if (total > MAX_ZIP_BYTES) { finish(new Error('The download is unexpectedly large.')); return; }
      const out = fs.createWriteStream(dest, { mode: 0o600 });
      const hash = crypto.createHash('sha256');
      let got = 0;
      armStall();
      res.on('data', (chunk) => {
        got += chunk.length;
        if (got > MAX_ZIP_BYTES) { finish(new Error('The download is unexpectedly large.')); return; }
        hash.update(chunk);
        armStall();
        if (total) onProgress(Math.min(1, got / total));
      });
      res.on('error', (err) => finish(err));
      out.on('error', (err) => finish(err));
      out.on('finish', () => finish(null, { sha256: hash.digest('hex'), bytes: got }));
      res.pipe(out);
    });
    req.on('error', (err) => finish(new Error(`Download failed (${errText(err)}).`)));
    armStall();
    req.end();
  });
}

function run(file, args) {
  return new Promise((resolve, reject) => {
    execFile(file, args, { timeout: 5 * 60 * 1000, maxBuffer: 4 * 1024 * 1024 }, (err, stdout, stderr) => {
      if (err) reject(new Error(`${path.basename(file)} failed: ${(stderr || err.message).toString().trim()}`));
      else resolve(String(stdout));
    });
  });
}

const plistValue = async (plist, key) => (await run('/usr/bin/plutil', ['-extract', key, 'raw', '-o', '-', plist])).trim();

// ---------- checking ----------
/**
 * source: 'timer' (may notify / auto-download), 'menu' (caller shows a dialog),
 * 'renderer' (the web UI shows it; may auto-download, never notifies).
 */
function check({ source = 'renderer' } = {}) {
  if (!checking) checking = doCheck(source).finally(() => { checking = null; });
  return checking;
}

async function doCheck(source) {
  state.checking = true;
  state.error = null;
  emit();
  const { updateChannel } = settings();
  try {
    const res = await getFromGitHub(core.RELEASES_API);
    let list;
    try { list = await res.json(); } catch { throw new Error('GitHub sent an unreadable answer.'); }
    if (!Array.isArray(list)) throw new Error('GitHub sent an unexpected answer.');
    const rel = core.pickRelease(list, { channel: updateChannel });
    release = rel;
    state.latest = rel ? { version: rel.version, notes: rel.notes, url: rel.url, publishedAt: rel.publishedAt, prerelease: rel.prerelease } : null;
    state.available = !!rel && core.isNewer(rel.version, current());
    if (staged && (!state.available || staged.version !== rel.version)) discardStaged();
    prefs.set('lastUpdateCheck', Date.now());
    lastFailureAt = 0;
    if (state.available && source !== 'menu') afterFound(rel, { quiet: source !== 'timer' });
  } catch (err) {
    lastFailureAt = Date.now();
    state.error = errText(err);
  } finally {
    state.checking = false;
    emit();
    schedule();
  }
  return getState();
}

function afterFound(rel, { quiet }) {
  const s = settings();
  if (rel.version === s.skippedVersion || s.autoUpdate === 'off') return;
  if (s.autoUpdate === 'auto' && !installBlocker()) {
    stage(rel)
      .then(() => watchIdle())
      .catch((err) => console.warn('[orbit] update download failed:', errText(err)));
    return;
  }
  // "notify", or "auto" when Orbit can't replace itself where it is.
  if (!quiet && notifiedVersion !== rel.version) {
    notifiedVersion = rel.version;
    showNotification(`Orbit ${rel.version} is available — click to install`, '', () => promptInstall());
  }
}

function showNotification(title, body, onClick) {
  if (!Notification.isSupported()) return;
  const n = new Notification({ title, body, silent: false });
  live.add(n);
  const done = () => live.delete(n);
  n.on('click', () => { done(); onClick(); });
  n.on('close', done);
  n.show();
  setTimeout(done, 30 * 60 * 1000);
}

// ---------- scheduling ----------
function schedule(minDelay = MIN_DELAY_MS) {
  clearTimeout(checkTimer);
  checkTimer = null;
  const s = settings();
  if (s.autoUpdate === 'off') return;
  const everyMs = s.updateCheckEvery * 3600 * 1000;
  let wait = core.msUntilDue(prefs.get('lastUpdateCheck'), s.updateCheckEvery);
  if (lastFailureAt) wait = Math.max(wait, lastFailureAt + Math.min(RETRY_MS, everyMs) - Date.now());
  wait = Math.min(MAX_TIMER_MS, Math.max(minDelay, wait));
  checkTimer = setTimeout(() => { checkTimer = null; check({ source: 'timer' }); }, wait);
}

// ---------- download & verify ----------
function setProgress(p, showInDock) {
  const rounded = Math.round(p * 100) / 100;
  if (rounded !== state.progress) { state.progress = rounded; emit(); }
  if (showInDock) for (const w of windows.mainWindows()) w.setProgressBar(p);
}

function clearDockProgress() {
  for (const w of windows.mainWindows()) w.setProgressBar(-1);
}

const updateDir = (version) => path.join(app.getPath('temp'), `orbit-update-${version}`);

/** Download, verify and unpack rel. Resolves to { version, appPath, dir }. */
function stage(rel, { showInDock = false } = {}) {
  if (staged && staged.version === rel.version) return Promise.resolve(staged);
  if (downloading) return downloading;
  downloading = (async () => {
    state.downloading = true;
    state.progress = 0;
    state.error = null;
    emit();
    const dir = updateDir(rel.version);
    try {
      await fsp.rm(dir, { recursive: true, force: true });
      await fsp.mkdir(dir, { recursive: true, mode: 0o700 });

      const sumsText = await (await getFromGitHub(rel.sums.url)).text();
      const expected = core.parseSums(sumsText).get(rel.zip.name);
      if (!expected) throw new Error(`SHA256SUMS.txt has no entry for ${rel.zip.name}; not installing.`);

      const zipPath = path.join(dir, rel.zip.name);
      const { sha256 } = await download(rel.zip.url, zipPath, (p) => setProgress(p, showInDock));
      if (sha256 !== expected) throw new Error('The download does not match its SHA-256 checksum; not installing.');

      const unpacked = path.join(dir, 'unpacked');
      await fsp.mkdir(unpacked);
      await run('/usr/bin/ditto', ['-x', '-k', zipPath, unpacked]);
      const appPath = path.join(unpacked, 'Orbit.app');
      const plist = path.join(appPath, 'Contents', 'Info.plist');
      if (!fs.existsSync(plist)) throw new Error('The update does not contain Orbit.app.');
      const version = await plistValue(plist, 'CFBundleShortVersionString').catch(() => '');
      if (version !== rel.version) throw new Error(`The update contains version ${version || 'unknown'}, expected ${rel.version}.`);
      if (app.isPackaged) {
        const mine = await plistValue(path.join(bundlePath(), 'Contents', 'Info.plist'), 'CFBundleIdentifier').catch(() => '');
        const theirs = await plistValue(plist, 'CFBundleIdentifier').catch(() => '');
        if (!mine || mine !== theirs) throw new Error('The update is not a build of this app.');
      }
      await fsp.rm(zipPath, { force: true });

      staged = { version: rel.version, appPath, dir };
      state.staged = rel.version;
      return staged;
    } catch (err) {
      await fsp.rm(dir, { recursive: true, force: true }).catch(() => {});
      state.error = errText(err);
      throw err;
    } finally {
      state.downloading = false;
      state.progress = null;
      downloading = null;
      if (showInDock) clearDockProgress();
      emit();
    }
  })();
  return downloading;
}

function discardStaged() {
  if (!staged) return;
  const { dir } = staged;
  staged = null;
  state.staged = null;
  stopIdle();
  fsp.rm(dir, { recursive: true, force: true }).catch(() => {});
}

// ---------- installing ----------
function bundlePath() { return path.resolve(process.execPath, '../../..'); }

/** Why Orbit can't replace its own bundle, or null when it can. */
function installBlocker() {
  if (!app.isPackaged) return 'Orbit is running from source, so it can’t replace itself.';
  const bundle = bundlePath();
  if (!bundle.endsWith('.app')) return 'Orbit couldn’t find its own app bundle.';
  if (bundle.includes('/AppTranslocation/')) {
    return 'macOS is running Orbit from a temporary read-only copy. Move Orbit.app to your Applications folder and open it from there.';
  }
  try {
    fs.accessSync(path.dirname(bundle), fs.constants.W_OK);
    fs.accessSync(bundle, fs.constants.W_OK);
  } catch {
    return `Orbit doesn’t have permission to replace itself in ${path.dirname(bundle)}.`;
  }
  return null;
}

// Args: PID APP NEW TRASHED RELAUNCH(0 none, 1 front, 2 background) LOG
const INSTALL_SCRIPT = `#!/bin/sh
# Orbit updater: swap the app bundle once the running copy has quit.
PID="$1"; APP="$2"; NEW="$3"; TRASHED="$4"; RELAUNCH="$5"; LOG="$6"
exec >>"$LOG" 2>&1
echo "$(date): installing $NEW over $APP"
i=0
while kill -0 "$PID" 2>/dev/null; do
  i=$((i + 1))
  if [ "$i" -gt 600 ]; then echo "Orbit did not quit; update cancelled"; exit 1; fi
  sleep 0.1
done
case "$APP" in *.app) ;; *) echo "not an app bundle: $APP"; exit 1 ;; esac
if [ ! -f "$NEW/Contents/Info.plist" ]; then echo "new bundle missing"; exit 1; fi
mkdir -p "$(dirname "$TRASHED")"
if ! mv "$APP" "$TRASHED"; then echo "could not move the old app to the Trash"; exit 1; fi
if ! mv "$NEW" "$APP"; then
  echo "could not move the new app into place; restoring the old one"
  mv "$TRASHED" "$APP"
  [ "$RELAUNCH" = 0 ] || open "$APP"
  exit 1
fi
xattr -dr com.apple.quarantine "$APP" 2>/dev/null
case "$RELAUNCH" in
  1) open "$APP" ;;
  2) open -g "$APP" ;;
esac
echo "done"
`;

/** Hand the staged bundle to the install script. The caller quits (or is quitting). */
function applyStaged(info, { relaunch }) {
  const blocker = installBlocker();
  if (blocker) throw new Error(blocker);
  if (!fs.existsSync(path.join(info.appPath, 'Contents', 'Info.plist'))) throw new Error('The downloaded update is gone; check again.');
  const trashDir = path.join(os.homedir(), '.Trash');
  let trashed = path.join(trashDir, `Orbit-${current()}.app`);
  if (fs.existsSync(trashed)) trashed = path.join(trashDir, `Orbit-${current()}-${Date.now()}.app`);
  const script = path.join(info.dir, 'install.sh');
  fs.writeFileSync(script, INSTALL_SCRIPT, { mode: 0o700 });
  prefs.set('justUpdatedTo', info.version);
  prefs.flushSync();
  const mode = relaunch === 'background' ? '2' : relaunch ? '1' : '0';
  const child = spawn('/bin/sh', [script, String(process.pid), bundlePath(), info.appPath, trashed, mode, path.join(info.dir, 'install.log')], {
    detached: true,
    stdio: 'ignore',
  });
  child.on('error', (err) => console.error('[orbit] could not start the update installer:', err.message));
  child.unref();
  installing = true;
  // If the quit gets cancelled, the script gives up after a minute; allow another try after that.
  setTimeout(() => { installing = false; }, 70 * 1000).unref();
}

function parentWindow() {
  const w = BrowserWindow.getFocusedWindow();
  return windows.isMainWindow(w) ? w : undefined;
}

/** Install the available update now and relaunch. Resolves to the state (unless Orbit quits). */
async function install({ fromDialog = false } = {}) {
  if (installing) return getState();
  const rel = release;
  if (!rel || !state.available) {
    state.error = 'There is no update to install. Check for updates first.';
    emit();
    return getState();
  }
  const blocker = installBlocker();
  if (blocker) {
    links.openExternal(rel.url);
    state.error = `${blocker} The release page is open in your browser so you can download Orbit ${rel.version} by hand.`;
    emit();
    if (fromDialog) {
      await dialog.showMessageBox(parentWindow(), {
        type: 'info',
        message: 'Orbit can’t update itself here',
        detail: `${blocker}\n\nThe release page is open in your browser: download ${core.assetNames(rel.version).dmg} and drag Orbit to Applications.`,
      });
    }
    return getState();
  }
  try {
    const info = await stage(rel, { showInDock: true });
    applyStaged(info, { relaunch: true });
    app.quit();
  } catch (err) {
    state.error = errText(err);
    emit();
    if (fromDialog) await dialog.showMessageBox(parentWindow(), { type: 'error', message: 'Couldn’t install the update', detail: state.error });
  }
  return getState();
}

async function promptInstall() {
  if (!release || !state.available) return;
  const v = release.version;
  const notes = core.notesExcerpt(release.notes, 600);
  const { response } = await dialog.showMessageBox(parentWindow(), {
    type: 'info',
    buttons: ['Install and Relaunch', 'Later', 'Skip This Version'],
    defaultId: 0,
    cancelId: 1,
    message: `Orbit ${v} is available`,
    detail: `You have ${current()}.${notes ? `\n\n${notes}` : ''}`,
  });
  if (response === 0) await install({ fromDialog: true });
  else if (response === 2) {
    prefs.set('skippedVersion', v);
    if (staged && staged.version === v) discardStaged();
    emit();
  }
}

/** App menu / tray "Check for Updates…": always checks, then answers with a dialog. */
async function checkNow() {
  const s = await check({ source: 'menu' });
  if (s.error) {
    await dialog.showMessageBox(parentWindow(), { type: 'error', message: 'Couldn’t check for updates', detail: s.error });
  } else if (!s.available) {
    await dialog.showMessageBox(parentWindow(), { type: 'info', message: `You’re up to date (${current()})` });
  } else {
    await promptInstall();
  }
}

// ---------- idle install ("auto" mode) ----------
function stopIdle() { clearTimeout(idleTimer); idleTimer = null; }

function watchIdle() {
  if (idleTimer || !staged) return;
  if (unfocusedSince === null && !BrowserWindow.getFocusedWindow()) unfocusedSince = Date.now();
  const tick = async () => {
    idleTimer = null;
    if (!staged || installing || settings().autoUpdate !== 'auto') return;
    idleTimer = setTimeout(tick, IDLE_POLL_MS);
    if (BrowserWindow.getFocusedWindow()) { unfocusedSince = null; return; }
    if (unfocusedSince === null || Date.now() - unfocusedSince < IDLE_MS) return;
    let running = null;
    try {
      const j = await server.getJSON('/api/running');
      running = j && Array.isArray(j.running) ? j.running : null;
    } catch { running = null; } // can't tell: wait (it still installs on quit)
    if (!running || running.length > 0) return;
    if (!staged || installing || BrowserWindow.getFocusedWindow()) return;
    try {
      applyStaged(staged, { relaunch: 'background' });
      stopIdle();
      app.quit();
    } catch (err) {
      state.error = errText(err);
      stopIdle();
      emit();
    }
  };
  idleTimer = setTimeout(tick, IDLE_POLL_MS);
}

// ---------- prefs ----------
/** Validated partial update of { autoUpdate, updateCheckEvery, updateChannel }. Throws TypeError on bad input. */
function setPrefs(input) {
  const patch = core.validatePrefs(input);
  const before = settings();
  for (const [k, v] of Object.entries(patch)) prefs.set(k, v);
  const after = settings();
  const channelChanged = after.updateChannel !== before.updateChannel;
  if (channelChanged) {
    release = null;
    state.latest = null;
    state.available = false;
    discardStaged();
  }
  if (after.autoUpdate !== 'auto') stopIdle();
  else if (staged) watchIdle();
  emit();
  if (after.autoUpdate === 'off') schedule();
  else if (channelChanged) check({ source: 'renderer' });
  else {
    schedule();
    if (after.autoUpdate === 'auto' && before.autoUpdate !== 'auto' && state.available && release) afterFound(release, { quiet: true });
  }
  return getState();
}

function setSkippedVersion(v) { prefs.set('skippedVersion', v); emit(); }

// ---------- startup ----------
function finishPreviousUpdate() {
  const target = prefs.get('justUpdatedTo');
  const skipped = prefs.get('skippedVersion');
  if (typeof skipped === 'string' && !core.isNewer(skipped, current())) prefs.set('skippedVersion', null);
  if (typeof target !== 'string' || !target) return null;
  prefs.set('justUpdatedTo', null);
  if (target === current()) {
    showNotification(`Orbit updated to ${target}`, 'Click to see what’s new.', () => {
      links.openExternal(`${core.RELEASES_PAGE}/tag/${core.TAG_PREFIX}${target}`);
    });
    return null;
  }
  const log = path.join(updateDir(target), 'install.log');
  console.warn(`[orbit] update to ${target} did not finish; see ${log}`);
  state.error = `The update to Orbit ${target} didn’t finish installing. Details: ${log}`;
  return target;
}

/** Remove leftover update folders (keeping the log of an install that failed). */
function cleanTemp(keepVersion) {
  const tmp = app.getPath('temp');
  let names = [];
  try { names = fs.readdirSync(tmp); } catch { return; }
  for (const name of names) {
    if (!name.startsWith('orbit-update-') || name === `orbit-update-${keepVersion}`) continue;
    fsp.rm(path.join(tmp, name), { recursive: true, force: true }).catch(() => {});
  }
}

function start() {
  if (started) return;
  started = true;
  const failed = finishPreviousUpdate();
  cleanTemp(failed);

  app.on('browser-window-focus', () => { unfocusedSince = null; });
  app.on('browser-window-blur', () => {
    setImmediate(() => { if (!BrowserWindow.getFocusedWindow() && unfocusedSince === null) unfocusedSince = Date.now(); });
  });
  // "auto" mode: a verified update waiting at quit is installed instead of a plain quit.
  app.on('before-quit', () => {
    if (installing || !staged || settings().autoUpdate !== 'auto') return;
    try { applyStaged(staged, { relaunch: false }); } catch (err) { console.warn('[orbit] install on quit skipped:', errText(err)); }
  });
  powerMonitor.on('resume', () => schedule(FIRST_CHECK_DELAY_MS));

  schedule(FIRST_CHECK_DELAY_MS);
  emit();
}

function stop() { clearTimeout(checkTimer); checkTimer = null; stopIdle(); }

module.exports = {
  start, stop, getState, onState, check, checkNow, install, promptInstall, setPrefs, setSkippedVersion,
  pendingVersion, lastCheckedLabel,
};
