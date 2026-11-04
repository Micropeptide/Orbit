'use strict';
// First-run setup for a downloaded Orbit.app. The app carries Orbit's server (a read-only copy in
// Contents/Resources/orbit-server). What it cannot carry is a Python with Orbit's packages, so the first
// launch makes one for the person: a virtualenv in ~/Library/Application Support/Orbit/venv, filled from
// the bundled requirements.txt. Their data (chats, settings, memory…) lives in that same folder, apart from
// the app, so updating or deleting Orbit.app never touches it.
//
// A person who already runs Orbit from a folder (git clone, install.sh) is not affected: server.js uses
// that folder first and only comes here when there is none.
const fs = require('fs');
const os = require('os');
const path = require('path');
const crypto = require('crypto');
const { spawn, execFileSync } = require('child_process');

const MIN_PYTHON = [3, 9];
const STATE_FILE = '.desktop-install.json';
const DATA_FOLDERS = ['config', 'memory', 'skills', 'knowledge', 'sessions', 'workspace', 'trash', 'logs', 'backups'];

const managedRoot = (home = os.homedir()) => path.join(home, 'Library', 'Application Support', 'Orbit');
const venvPython = (root) => path.join(root, 'venv', 'bin', 'python');

/** The bundled server: inside the packaged app, or build/orbit-server in a source checkout. */
function bundleDir() {
  const here = [
    process.resourcesPath && path.join(process.resourcesPath, 'orbit-server'),
    path.join(__dirname, '..', '..', 'build', 'orbit-server'),
  ].filter(Boolean);
  return here.find((d) => fs.existsSync(path.join(d, 'bin', 'orbit-ui'))) || null;
}

function parsePythonVersion(text) {
  const m = /Python\s+(\d+)\.(\d+)(?:\.(\d+))?/.exec(String(text || ''));
  return m ? [Number(m[1]), Number(m[2]), Number(m[3] || 0)] : null;
}
const versionOk = (v) => !!v && (v[0] > MIN_PYTHON[0] || (v[0] === MIN_PYTHON[0] && v[1] >= MIN_PYTHON[1]));
const cmpVersion = (a, b) => (a[0] - b[0]) || (a[1] - b[1]) || (a[2] - b[2]);

/** Where a Python might be. /usr/bin/python3 only counts once the Command Line Tools exist: without them
 *  macOS answers by opening an "install developer tools" dialog, which is not what a launch should do. */
function pythonCandidates({ env = process.env, exists = fs.existsSync, hasCLT = commandLineToolsInstalled } = {}) {
  const list = [];
  if (env.ORBIT_PYTHON) list.push(env.ORBIT_PYTHON);
  for (const minor of [14, 13, 12, 11, 10]) {
    list.push(`/opt/homebrew/bin/python3.${minor}`, `/usr/local/bin/python3.${minor}`);
  }
  list.push('/opt/homebrew/bin/python3', '/usr/local/bin/python3',
    '/Library/Frameworks/Python.framework/Versions/Current/bin/python3');
  const out = list.filter((p) => exists(p));
  if (exists('/usr/bin/python3') && hasCLT()) out.push('/usr/bin/python3');
  return out;
}

function commandLineToolsInstalled() {
  try { execFileSync('/usr/bin/xcode-select', ['-p'], { stdio: 'ignore', timeout: 5000 }); return true; } catch { return false; }
}

/** The newest usable Python 3.9+ on this Mac: {path, version} or null. */
function findPython(opts = {}) {
  const probe = opts.probe || ((p) => {
    try { return execFileSync(p, ['--version'], { encoding: 'utf8', timeout: 10000, stdio: ['ignore', 'pipe', 'pipe'] }); } catch { return ''; }
  });
  let best = null;
  for (const p of pythonCandidates(opts)) {
    const v = parsePythonVersion(probe(p));
    if (!versionOk(v)) continue;
    if (!best || rank(v) > rank(best.version) || (rank(v) === rank(best.version) && cmpVersion(v, best.version) > 0)) best = { path: p, version: v };
  }
  return best;
}

/** Which Pythons to prefer. The newest is not the best: a brand-new Python has no ready-made wheels for
 *  numpy, pandas or pillow yet, and a build from source can take half an hour or fail. 3.12 and 3.13 have
 *  them all; older ones work; a version newer than 3.13 or the old 3.9 comes last. */
function rank(v) {
  if (v[0] !== 3) return 0;
  const order = { 12: 9, 13: 8, 11: 7, 10: 6, 14: 4, 9: 3 };
  return order[v[1]] || (v[1] > 14 ? 1 : 2);
}

function sha256File(file) {
  try { return crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex'); } catch { return null; }
}

function readState(root) {
  try { return JSON.parse(fs.readFileSync(path.join(root, STATE_FILE), 'utf8')); } catch { return null; }
}
function writeState(root, state) {
  fs.mkdirSync(root, { recursive: true });
  fs.writeFileSync(path.join(root, STATE_FILE), JSON.stringify(state, null, 2));
}

/** Does the managed folder need (re)building? True when there is no venv, or the bundled requirements changed. */
function needsSetup(root, bundle) {
  if (!fs.existsSync(venvPython(root))) return true;
  const st = readState(root);
  if (!st || !st.ok) return true;
  return st.requirements !== sha256File(path.join(bundle, 'requirements.txt'));
}

function bundleVersion(bundle) {
  try { return fs.readFileSync(path.join(bundle, 'VERSION'), 'utf8').trim(); } catch { return null; }
}

/** A short line for the boot page from one line of pip's output, or null. */
function pipStatus(line) {
  const s = String(line || '').trim();
  let m = /^Collecting\s+([A-Za-z0-9_.\-]+)/.exec(s);
  if (m) return `Installing ${m[1]}…`;
  m = /^Downloading\s+(\S+)/.exec(s);
  if (m) return `Downloading ${path.basename(m[1]).split('-')[0]}…`;
  if (/^Installing collected packages/.test(s)) return 'Installing the packages…';
  return null;
}

/** Packages Orbit lists in requirements.txt, one per entry, comments dropped. */
function requirementLines(text) {
  return String(text || '').split(/\r?\n/).map((l) => l.replace(/\s+#.*$/, '').trim()).filter((l) => l && !l.startsWith('#'));
}

function run(cmd, args, { cwd, env, onLine, log } = {}) {
  return new Promise((resolve) => {
    const child = spawn(cmd, args, { cwd, env: { ...process.env, ...env }, stdio: ['ignore', 'pipe', 'pipe'] });
    let tail = '';
    const feed = (buf) => {
      const text = buf.toString();
      if (log) try { fs.appendFileSync(log, text); } catch { /* the log is a courtesy */ }
      tail = (tail + text).slice(-4000);
      if (onLine) text.split(/\r?\n/).forEach((l) => l && onLine(l));
    };
    child.stdout.on('data', feed);
    child.stderr.on('data', feed);
    child.on('error', (e) => resolve({ code: -1, tail: String(e.message || e) }));
    child.on('close', (code) => resolve({ code, tail }));
  });
}

class SetupError extends Error {
  constructor(message, { needsPython = false, log = null } = {}) { super(message); this.needsPython = needsPython; this.log = log; }
}

/**
 * Make the managed folder ready: data folders, a venv, the packages. onStatus(text) reports progress.
 * Safe to run again; existing data is never touched. The packages are installed all at once, and if that
 * fails (one wheel missing for this Python) one by one, so a single odd package does not stop Orbit —
 * the server starts on the standard library alone and every package it can't import is simply a tool
 * that says what to install.
 */
async function setup({ root = managedRoot(), bundle = bundleDir(), onStatus = () => {}, python = findPython() } = {}) {
  if (!bundle) throw new SetupError('This copy of Orbit does not include its server.');
  if (!python) {
    throw new SetupError('Orbit needs Python 3.9 or newer, and this Mac has none yet.', { needsPython: true });
  }
  fs.mkdirSync(root, { recursive: true });
  for (const d of DATA_FOLDERS) fs.mkdirSync(path.join(root, d), { recursive: true });
  const log = path.join(root, 'logs', 'desktop-install.log');
  try { fs.appendFileSync(log, `\n--- ${new Date().toISOString()} setup with ${python.path}\n`); } catch { /* ignore */ }

  if (!fs.existsSync(venvPython(root))) {
    onStatus('Setting up Orbit for the first time…');
    const r = await run(python.path, ['-m', 'venv', path.join(root, 'venv')], { log });
    if (r.code !== 0) throw new SetupError(`Could not create Orbit's Python environment: ${r.tail.trim().split('\n').pop()}`, { log });
  }
  const py = venvPython(root);
  const reqFile = path.join(bundle, 'requirements.txt');
  const pipEnv = { PIP_DISABLE_PIP_VERSION_CHECK: '1', PIP_NO_INPUT: '1', PYTHONNOUSERSITE: '1' };
  const onLine = (l) => { const s = pipStatus(l); if (s) onStatus(s); };

  if (fs.existsSync(reqFile)) {
    onStatus('Installing Orbit’s packages (a few minutes, once)…');
    let r = await run(py, ['-m', 'pip', 'install', '--progress-bar', 'off', '-r', reqFile], { env: pipEnv, onLine, log });
    let skipped = [];
    if (r.code !== 0) {
      onStatus('Retrying the packages one at a time…');
      for (const line of requirementLines(fs.readFileSync(reqFile, 'utf8'))) {
        const one = await run(py, ['-m', 'pip', 'install', '--progress-bar', 'off', line], { env: pipEnv, onLine, log });
        if (one.code !== 0) skipped.push(line);
      }
      if (skipped.length === requirementLines(fs.readFileSync(reqFile, 'utf8')).length) {
        throw new SetupError(`Could not install Orbit's packages. Check your internet connection and try again. (${r.tail.trim().split('\n').pop()})`, { log });
      }
    }
    writeState(root, { ok: true, requirements: sha256File(reqFile), bundle: bundleVersion(bundle), python: python.path, skipped, at: new Date().toISOString() });
  } else {
    writeState(root, { ok: true, requirements: null, bundle: bundleVersion(bundle), python: python.path, skipped: [], at: new Date().toISOString() });
  }
  return { root, python: py };
}

/** How to start the managed server: its venv's Python running the bundled bin/orbit-ui, data in `root`. */
function serverCommand({ root = managedRoot(), bundle = bundleDir(), port } = {}) {
  return {
    cmd: venvPython(root),
    args: [path.join(bundle, 'bin', 'orbit-ui'), '--no-open'],
    cwd: root,
    env: { ORBIT_HOME: root, ...(port ? { ORBIT_UI_PORT: String(port) } : {}) },
  };
}

module.exports = {
  MIN_PYTHON, STATE_FILE, DATA_FOLDERS, SetupError,
  managedRoot, venvPython, bundleDir, parsePythonVersion, versionOk, pythonCandidates, findPython,
  rank, sha256File, readState, writeState, needsSetup, bundleVersion, pipStatus, requirementLines, setup, serverCommand,
};
