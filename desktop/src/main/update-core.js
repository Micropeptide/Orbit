'use strict';
// Pure helpers for the updater (no Electron): version compare, SHA256SUMS
// parsing, picking a release from the GitHub API, pref validation.
// Covered by test/update-core.test.js.

const REPO = 'Micropeptide/Orbit';
const TAG_PREFIX = 'desktop-v';
const RELEASES_API = `https://api.github.com/repos/${REPO}/releases?per_page=20`;
const RELEASES_PAGE = `https://github.com/${REPO}/releases`;

const MODES = ['auto', 'notify', 'off'];
const INTERVALS = [1, 6, 24, 168]; // hours
const CHANNELS = ['stable', 'beta'];

const SEMVER_RE = /^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$/;

/** '1.2.3-beta.1' -> { major, minor, patch, pre: ['beta', 1] } or null. */
function parseVersion(v) {
  const m = SEMVER_RE.exec(String(v == null ? '' : v).trim());
  if (!m) return null;
  const pre = m[4] ? m[4].split('.').map((id) => (/^\d+$/.test(id) ? Number(id) : id)) : [];
  return { major: Number(m[1]), minor: Number(m[2]), patch: Number(m[3]), pre };
}

function comparePre(a, b) {
  if (!a.length && !b.length) return 0;
  if (!a.length) return 1;  // 1.0.0 > 1.0.0-beta
  if (!b.length) return -1;
  for (let i = 0; i < Math.max(a.length, b.length); i++) {
    if (i >= a.length) return -1; // shorter set of equal identifiers is lower
    if (i >= b.length) return 1;
    const x = a[i];
    const y = b[i];
    if (x === y) continue;
    const xn = typeof x === 'number';
    const yn = typeof y === 'number';
    if (xn && yn) return x < y ? -1 : 1;
    if (xn) return -1; // numeric identifiers sort below alphanumeric ones
    if (yn) return 1;
    return x < y ? -1 : 1;
  }
  return 0;
}

/** Semver precedence: -1, 0 or 1. Throws on an invalid version. */
function compareVersions(a, b) {
  const pa = parseVersion(a);
  const pb = parseVersion(b);
  if (!pa || !pb) throw new TypeError(`invalid version: ${!pa ? a : b}`);
  for (const k of ['major', 'minor', 'patch']) {
    if (pa[k] !== pb[k]) return pa[k] < pb[k] ? -1 : 1;
  }
  return comparePre(pa.pre, pb.pre);
}

function isNewer(candidate, current) {
  try { return compareVersions(candidate, current) > 0; } catch { return false; }
}

function assetNames(version) {
  return {
    dmg: `Orbit-${version}-arm64.dmg`,
    zip: `Orbit-${version}-arm64-mac.zip`,
    sums: 'SHA256SUMS.txt',
  };
}

/** Lines "<sha256>  <filename>" (also "<sha256> *<filename>") -> Map(filename -> hex). */
function parseSums(text) {
  const out = new Map();
  for (const raw of String(text || '').split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || line.startsWith('#')) continue;
    const m = /^([0-9a-fA-F]{64})\s+\*?(.+)$/.exec(line);
    if (!m) continue;
    const name = m[2].trim();
    if (name && !out.has(name)) out.set(name, m[1].toLowerCase());
  }
  return out;
}

/** Only assets attached to this repo's releases may be downloaded (redirects are checked separately). */
function isReleaseAssetURL(url) {
  let u;
  try { u = new URL(String(url)); } catch { return false; }
  return u.protocol === 'https:' && u.hostname === 'github.com'
    && u.pathname.startsWith(`/${REPO}/releases/download/`);
}

/**
 * The newest usable desktop release from GET /repos/:repo/releases, or null.
 * Usable: tag desktop-v<semver>, not a draft, carries the updater zip and
 * SHA256SUMS.txt. Prereleases (by flag or by a -pre version) only on "beta".
 */
function pickRelease(releases, { channel = 'stable' } = {}) {
  if (!Array.isArray(releases)) return null;
  let best = null;
  for (const r of releases) {
    if (!r || typeof r !== 'object' || r.draft) continue;
    if (typeof r.tag_name !== 'string' || !r.tag_name.startsWith(TAG_PREFIX)) continue;
    const version = r.tag_name.slice(TAG_PREFIX.length);
    const parsed = parseVersion(version);
    if (!parsed || version.startsWith('v')) continue;
    if (channel !== 'beta' && (r.prerelease || parsed.pre.length)) continue;
    const names = assetNames(version);
    const assets = Array.isArray(r.assets) ? r.assets : [];
    const find = (name) => assets.find((a) => a && a.name === name && isReleaseAssetURL(a.browser_download_url));
    const zip = find(names.zip);
    const sums = find(names.sums);
    if (!zip || !sums) continue;
    if (best && compareVersions(version, best.version) <= 0) continue;
    const dmg = find(names.dmg);
    best = {
      version,
      tag: r.tag_name,
      prerelease: !!r.prerelease || parsed.pre.length > 0,
      notes: typeof r.body === 'string' ? r.body : '',
      url: typeof r.html_url === 'string' && r.html_url.startsWith(`https://github.com/${REPO}/`) ? r.html_url : RELEASES_PAGE,
      publishedAt: typeof r.published_at === 'string' ? r.published_at : null,
      zip: { name: zip.name, url: zip.browser_download_url, size: Number(zip.size) || 0 },
      sums: { name: sums.name, url: sums.browser_download_url },
      dmg: dmg ? { name: dmg.name, url: dmg.browser_download_url } : null,
    };
  }
  return best;
}

/** First n characters of release notes, tidied for a dialog. */
function notesExcerpt(body, n = 600) {
  const text = String(body || '').replace(/\r\n?/g, '\n').replace(/\n{3,}/g, '\n\n').trim();
  return text.length > n ? text.slice(0, n).trimEnd() + '…' : text;
}

/**
 * Validate a partial prefs object from the renderer or menu.
 * Returns the clean patch; throws TypeError on a bad value. Unknown keys are ignored.
 */
function validatePrefs(input) {
  if (!input || typeof input !== 'object' || Array.isArray(input)) throw new TypeError('prefs must be an object');
  const out = {};
  if (input.autoUpdate !== undefined) {
    if (!MODES.includes(input.autoUpdate)) throw new TypeError(`autoUpdate must be one of ${MODES.join(', ')}`);
    out.autoUpdate = input.autoUpdate;
  }
  if (input.updateCheckEvery !== undefined) {
    const n = Number(input.updateCheckEvery);
    if (!INTERVALS.includes(n)) throw new TypeError(`updateCheckEvery must be one of ${INTERVALS.join(', ')}`);
    out.updateCheckEvery = n;
  }
  if (input.updateChannel !== undefined) {
    if (!CHANNELS.includes(input.updateChannel)) throw new TypeError(`updateChannel must be one of ${CHANNELS.join(', ')}`);
    out.updateChannel = input.updateChannel;
  }
  return out;
}

/** Read prefs as stored, falling back to defaults for anything malformed. */
function effectivePrefs(get) {
  const mode = get('autoUpdate');
  const every = Number(get('updateCheckEvery'));
  const channel = get('updateChannel');
  const skipped = get('skippedVersion');
  return {
    autoUpdate: MODES.includes(mode) ? mode : 'notify',
    updateCheckEvery: INTERVALS.includes(every) ? every : 24,
    updateChannel: CHANNELS.includes(channel) ? channel : 'stable',
    skippedVersion: typeof skipped === 'string' && parseVersion(skipped) ? skipped : null,
  };
}

/** ms until the next scheduled check (0 = now). */
function msUntilDue(lastCheck, everyHours, now = Date.now()) {
  const last = Number(lastCheck) || 0;
  const due = last + everyHours * 3600 * 1000;
  if (last > now) return 0; // clock went backwards: check
  return Math.max(0, due - now);
}

function relativeTime(ts, now = Date.now()) {
  const t = Number(ts);
  if (!t) return 'Never';
  const s = Math.max(0, Math.round((now - t) / 1000));
  if (s < 60) return 'just now';
  const plural = (n, unit) => `${n} ${unit}${n === 1 ? '' : 's'} ago`;
  if (s < 3600) return plural(Math.floor(s / 60), 'minute');
  if (s < 86400) return plural(Math.floor(s / 3600), 'hour');
  return plural(Math.floor(s / 86400), 'day');
}

module.exports = {
  REPO, TAG_PREFIX, RELEASES_API, RELEASES_PAGE, MODES, INTERVALS, CHANNELS,
  parseVersion, compareVersions, isNewer, assetNames, parseSums, isReleaseAssetURL,
  pickRelease, notesExcerpt, validatePrefs, effectivePrefs, msUntilDue, relativeTime,
};
