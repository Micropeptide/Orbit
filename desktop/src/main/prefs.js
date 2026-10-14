'use strict';
// Small JSON stores in userData: prefs.json (settings) and window-state.json
// (bounds). Writes are debounced; flushSync() runs on quit.
const fs = require('fs');
const path = require('path');
const { app } = require('electron');

const DEFAULT_PREFS = {
  orbitRoot: null,
  port: null,
  zoomFactor: 1,
  keepInMenuBar: true,
  notifications: true,
  // Updates (see updater.js)
  autoUpdate: 'notify',       // 'auto' | 'notify' | 'off'
  updateCheckEvery: 24,       // hours: 1, 6, 24, 168
  updateChannel: 'stable',    // 'stable' | 'beta'
  lastUpdateCheck: 0,         // epoch ms of the last successful check
  skippedVersion: null,
  justUpdatedTo: null,        // set just before installing; shows "Orbit updated to …" after relaunch
};

function createStore(fileName, defaults) {
  const file = () => path.join(app.getPath('userData'), fileName);
  let data = { ...defaults };
  let timer = null;

  try {
    const raw = JSON.parse(fs.readFileSync(file(), 'utf8'));
    if (raw && typeof raw === 'object' && !Array.isArray(raw)) data = { ...defaults, ...raw };
  } catch { /* first run or unreadable: use defaults */ }

  function writeNow() {
    clearTimeout(timer);
    timer = null;
    try {
      fs.mkdirSync(path.dirname(file()), { recursive: true });
      const tmp = file() + '.tmp';
      fs.writeFileSync(tmp, JSON.stringify(data, null, 2));
      fs.renameSync(tmp, file());
    } catch (err) {
      console.error(`[orbit] could not save ${fileName}:`, err.message);
    }
  }

  return {
    get: (key) => data[key],
    all: () => ({ ...data }),
    set(key, value) {
      data[key] = value;
      clearTimeout(timer);
      timer = setTimeout(writeNow, 400);
    },
    replace(obj) {
      data = { ...defaults, ...obj };
      clearTimeout(timer);
      timer = setTimeout(writeNow, 400);
    },
    flushSync() { if (timer) writeNow(); },
  };
}

const prefs = createStore('prefs.json', DEFAULT_PREFS);
const windowState = createStore('window-state.json', {});

function validPort(v) {
  const n = Number(v);
  return Number.isInteger(n) && n > 0 && n < 65536 ? n : null;
}

// ORBIT_UI_PORT env, else prefs, else 8899.
function orbitPort() {
  return validPort(process.env.ORBIT_UI_PORT) || validPort(prefs.get('port')) || 8899;
}

module.exports = { prefs, windowState, orbitPort };
