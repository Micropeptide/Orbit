'use strict';
// Talking to (and, if needed, starting) the Orbit server. The server is a
// background service: we never start a second copy and never stop it.
const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawn, execFile } = require('child_process');
const { app, dialog } = require('electron');
const { prefs, orbitPort } = require('./prefs');
const installer = require('./installer');

const PROBE_TIMEOUT_MS = 1500;
const START_TIMEOUT_MS = 25000;

function baseURL() { return `http://127.0.0.1:${orbitPort()}`; }

async function getJSON(apiPath, timeoutMs = PROBE_TIMEOUT_MS) {
  const res = await fetch(baseURL() + apiPath, { signal: AbortSignal.timeout(timeoutMs) });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

async function postJSON(apiPath, body = {}, timeoutMs = 8000) {
  const res = await fetch(baseURL() + apiPath, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(timeoutMs),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json().catch(() => ({}));
}

/** Cheap liveness probe: true when /api/running answers with JSON. */
async function probe() {
  try {
    const j = await getJSON('/api/running');
    return !!j && Array.isArray(j.running);
  } catch {
    return false;
  }
}

const hasLauncher = (dir) => {
  try { return fs.statSync(path.join(dir, 'bin', 'orbit-ui')).isFile(); } catch { return false; }
};

/** Orbit's root folder: prefs, then folders above the app (dev run from <root>/desktop), then common install spots. */
function findOrbitRoot() {
  const candidates = [];
  if (typeof prefs.get('orbitRoot') === 'string') candidates.push(prefs.get('orbitRoot'));
  let dir = app.getAppPath();
  for (let i = 0; i < 8; i++) { // dev: <root>/desktop; packaged: <root>/desktop/dist/mac-arm64/Orbit.app/…
    const up = path.dirname(dir);
    if (up === dir) break;
    candidates.push(up);
    dir = up;
  }
  const home = os.homedir();
  candidates.push(path.join(home, 'Orbit'), path.join(home, 'Applications', 'Orbit'), '/Applications/Orbit');
  return candidates.find(hasLauncher) || null;
}

/** Ask the user for Orbit's folder. Returns the root or null. */
async function chooseOrbitRoot(parentWindow) {
  const opts = {
    title: 'Choose your Orbit folder',
    message: 'Select the Orbit folder (the one that contains bin/orbit-ui).',
    properties: ['openDirectory'],
    defaultPath: os.homedir(),
  };
  const r = parentWindow ? await dialog.showOpenDialog(parentWindow, opts) : await dialog.showOpenDialog(opts);
  if (r.canceled || !r.filePaths[0]) return null;
  const root = r.filePaths[0];
  if (!hasLauncher(root)) {
    await dialog.showMessageBox(parentWindow || undefined, {
      type: 'warning',
      message: 'That folder does not look like Orbit',
      detail: `No bin/orbit-ui was found in:\n${root}`,
    });
    return null;
  }
  prefs.set('orbitRoot', root);
  return root;
}

/** Label of a LaunchAgent whose plist mentions orbit-ui, or null. */
function findLaunchAgentLabel() {
  const dir = path.join(os.homedir(), 'Library', 'LaunchAgents');
  let names = [];
  try { names = fs.readdirSync(dir).filter((n) => n.endsWith('.plist')); } catch { return null; }
  for (const name of names) {
    let text = '';
    try { text = fs.readFileSync(path.join(dir, name), 'utf8'); } catch { continue; }
    if (!text.includes('orbit-ui')) continue;
    const m = text.match(/<key>\s*Label\s*<\/key>\s*<string>\s*([^<\s]+)\s*<\/string>/);
    if (m) return m[1];
  }
  return null;
}

function kickstart(label) {
  const uid = typeof process.getuid === 'function' ? process.getuid() : os.userInfo().uid;
  return new Promise((resolve) => {
    execFile('launchctl', ['kickstart', `gui/${uid}/${label}`], { timeout: 10000 }, (err) => {
      if (err) console.warn('[orbit] launchctl kickstart failed:', err.message);
      resolve(!err);
    });
  });
}

let spawnedByUs = false;
let failure = null;          // why the last start failed, for the boot page
function spawnProcess(cmd, args, cwd, extraEnv) {
  const child = spawn(cmd, args, {
    cwd,
    detached: true,
    stdio: 'ignore',
    env: { ...process.env, ...extraEnv, ORBIT_UI_PORT: String(orbitPort()) },
  });
  child.on('error', (err) => console.error('[orbit] could not start orbit-ui:', err.message));
  child.unref(); // background service: it outlives the app on purpose
  spawnedByUs = true;
}
function spawnServer(root) {
  spawnProcess(path.join(root, 'bin', 'orbit-ui'), ['--no-open'], root, {});
}

/** The server inside this app, run from its own Python environment with its data in Application Support. */
function spawnManaged(bundle) {
  const c = installer.serverCommand({ bundle });
  spawnProcess(c.cmd, c.args, c.cwd, c.env);
  const root = installer.managedRoot();
  const st = installer.readState(root);
  if (st) installer.writeState(root, { ...st, served: installer.bundleVersion(bundle) });
}

/** Tell the person why there is no server and what to do, when this Mac has no Python. */
async function explainNoPython(parentWindow) {
  const r = await dialog.showMessageBox(parentWindow || undefined, {
    type: 'info',
    buttons: ['Open python.org', 'Cancel'],
    defaultId: 0,
    message: 'Orbit needs Python 3.9 or newer',
    detail: 'Orbit’s server is written in Python and this Mac has none yet. Install Python from python.org '
      + '(or run `brew install python`), then open Orbit again — it sets itself up from there.',
  });
  if (r.response === 0) require('electron').shell.openExternal('https://www.python.org/downloads/macos/');
}

/** First launch of a downloaded Orbit.app (no Orbit folder anywhere): set up the bundled server and start it. */
async function startManaged(bundle, onStatus, parentWindow) {
  const root = installer.managedRoot();
  if (installer.needsSetup(root, bundle)) {
    try {
      await installer.setup({ root, bundle, onStatus });
    } catch (err) {
      console.error('[orbit] setup failed:', err.message);
      if (err.needsPython) await explainNoPython(parentWindow);
      failure = err.message + (err.log ? ` (details: ${err.log})` : '');
      return false;
    }
  }
  if (await probe()) return true;
  onStatus('Launching the Orbit server…');
  spawnManaged(bundle);
  return waitUntilUp(START_TIMEOUT_MS);
}

/** After an app update the managed server may still be the old one: ask it to quit so the new one starts. */
async function retireOutdatedManagedServer() {
  const bundle = installer.bundleDir();
  if (!bundle) return;
  const st = installer.readState(installer.managedRoot());
  if (!st || !st.ok || !st.served || st.served === installer.bundleVersion(bundle)) return;
  try { await postJSON('/api/restart_ui', {}); } catch { return; }
  const end = Date.now() + 20000;
  while (Date.now() < end) {
    if (!(await probe())) return;
    await new Promise((r) => setTimeout(r, 700));
  }
}

async function waitUntilUp(timeoutMs) {
  const end = Date.now() + timeoutMs;
  while (Date.now() < end) {
    if (await probe()) return true;
    await new Promise((r) => setTimeout(r, 700));
  }
  return false;
}

let inflight = null;
/**
 * Make sure the server answers. onStatus(text) reports progress to the boot page.
 * Resolves true when up. Concurrent callers share one attempt.
 */
function ensureServer(onStatus = () => {}, parentWindow = null) {
  if (!inflight) {
    inflight = (async () => {
      failure = null;
      await retireOutdatedManagedServer();
      if (await probe()) return true;
      onStatus('Starting Orbit…');
      if (await probe()) return true; // re-probe right before acting: never start a duplicate

      const label = findLaunchAgentLabel();
      if (label && (await kickstart(label))) {
        onStatus('Waking the Orbit background service…');
        return waitUntilUp(START_TIMEOUT_MS);
      }

      let root = findOrbitRoot();
      if (!root) {
        const bundle = installer.bundleDir();
        if (bundle) return startManaged(bundle, onStatus, parentWindow); // a downloaded app: it carries its own server
        onStatus('Where is Orbit installed?');
        root = await chooseOrbitRoot(parentWindow);
        if (!root) return false;
      }
      if (await probe()) return true;
      onStatus('Launching the Orbit server…');
      spawnServer(root);
      return waitUntilUp(START_TIMEOUT_MS);
    })().finally(() => { inflight = null; });
  }
  return inflight;
}

module.exports = {
  baseURL, getJSON, postJSON, probe, ensureServer, chooseOrbitRoot, findOrbitRoot,
  wasSpawnedByUs: () => spawnedByUs,
  lastFailure: () => failure,
};
