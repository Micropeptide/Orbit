'use strict';
// URL classification and opening links outside the app.
const fs = require('fs');
const path = require('path');
const { execFile } = require('child_process');
const { shell } = require('electron');
const { pathToFileURL } = require('url');
const { orbitPort } = require('./prefs');

const APP_ROOT = path.join(__dirname, '..', '..');

function parse(url) {
  try { return new URL(String(url)); } catch { return null; }
}

/** http://127.0.0.1:<port>/… or http://localhost:<port>/… */
function isOrbitURL(url) {
  const u = parse(url);
  return !!u && u.protocol === 'http:' && (u.hostname === '127.0.0.1' || u.hostname === 'localhost')
    && u.port === String(orbitPort());
}

/** One of the app's own bundled pages (boot.html, quick.html). */
function isLocalAppPage(url) {
  const u = parse(url);
  if (!u || u.protocol !== 'file:') return false;
  const base = pathToFileURL(APP_ROOT + path.sep).href;
  return u.href.startsWith(base) && u.pathname.endsWith('.html');
}

function isPreviewURL(url) {
  return isOrbitURL(url) && parse(url).pathname.startsWith('/fs/');
}

const CHROME = '/Applications/Google Chrome.app';
const hasChrome = () => { try { return fs.statSync(CHROME).isDirectory(); } catch { return false; } };

/** Open a link outside the app. Prefers Google Chrome when installed (never Safari by choice). */
function openExternal(url) {
  const u = parse(url);
  if (!u || !['http:', 'https:', 'mailto:'].includes(u.protocol)) return false;
  if (u.protocol !== 'mailto:' && hasChrome()) {
    execFile('open', ['-a', 'Google Chrome', u.href], (err) => {
      if (err) shell.openExternal(u.href).catch(() => {});
    });
  } else {
    shell.openExternal(u.href).catch((err) => console.warn('[orbit] openExternal failed:', err.message));
  }
  return true;
}

function appFile(...p) { return path.join(APP_ROOT, ...p); }

module.exports = { isOrbitURL, isLocalAppPage, isPreviewURL, openExternal, appFile, APP_ROOT };
