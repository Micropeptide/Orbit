'use strict';
// node --test test/  — no Electron and no network needed.
const test = require('node:test');
const assert = require('node:assert/strict');
const core = require('../src/main/update-core');

const DL = 'https://github.com/Micropeptide/Orbit/releases/download';

function fakeRelease(version, extra = {}) {
  const tag = `desktop-v${version}`;
  const names = core.assetNames(version);
  return {
    tag_name: tag,
    draft: false,
    prerelease: false,
    body: `Notes for ${version}`,
    html_url: `https://github.com/Micropeptide/Orbit/releases/tag/${tag}`,
    published_at: '2026-10-01T00:00:00Z',
    assets: [names.dmg, names.zip, names.sums].map((name) => ({
      name, size: 100, browser_download_url: `${DL}/${tag}/${name}`,
    })),
    ...extra,
  };
}

test('compareVersions orders by semver precedence', () => {
  const ordered = ['0.1.0', '0.1.1', '0.2.0-alpha', '0.2.0-alpha.1', '0.2.0-alpha.beta', '0.2.0-beta', '0.2.0-beta.2', '0.2.0-beta.11', '0.2.0-rc.1', '0.2.0', '0.10.0', '1.0.0'];
  for (let i = 0; i < ordered.length - 1; i++) {
    assert.equal(core.compareVersions(ordered[i], ordered[i + 1]), -1, `${ordered[i]} < ${ordered[i + 1]}`);
    assert.equal(core.compareVersions(ordered[i + 1], ordered[i]), 1);
  }
  assert.equal(core.compareVersions('1.2.3', 'v1.2.3'), 0);
  assert.equal(core.compareVersions('1.2.3+build.5', '1.2.3'), 0);
  assert.throws(() => core.compareVersions('1.2', '1.2.0'), TypeError);
  assert.throws(() => core.compareVersions('01.2.3', '1.2.3'), TypeError);
  assert.equal(core.isNewer('0.2.0', '0.1.0'), true);
  assert.equal(core.isNewer('0.1.0', '0.1.0'), false);
  assert.equal(core.isNewer('garbage', '0.1.0'), false);
});

test('parseSums reads "<sha256>  <file>" lines', () => {
  const a = 'a'.repeat(64);
  const b = 'B'.repeat(64);
  const sums = core.parseSums(`${a}  Orbit-0.2.0-arm64.dmg\r\n${b} *Orbit-0.2.0-arm64-mac.zip\n\n# comment\nnot a line\n${'c'.repeat(63)}  short.zip\n`);
  assert.equal(sums.size, 2);
  assert.equal(sums.get('Orbit-0.2.0-arm64.dmg'), a);
  assert.equal(sums.get('Orbit-0.2.0-arm64-mac.zip'), 'b'.repeat(64));
  assert.equal(sums.get('short.zip'), undefined);
  assert.equal(core.parseSums('').size, 0);
  assert.equal(core.parseSums(null).size, 0);
});

test('pickRelease takes the newest stable desktop release', () => {
  const list = [
    fakeRelease('0.3.0', { draft: true }),
    fakeRelease('0.4.0-beta.1', { prerelease: true }),
    { tag_name: 'v9.9.9', draft: false, prerelease: false, assets: [] },           // not a desktop tag
    { tag_name: 'server-v5.0.0', draft: false, prerelease: false, assets: [] },
    fakeRelease('0.2.0'),
    fakeRelease('0.2.1'),
    fakeRelease('0.1.0'),
    null,
  ];
  const r = core.pickRelease(list, { channel: 'stable' });
  assert.equal(r.version, '0.2.1');
  assert.equal(r.tag, 'desktop-v0.2.1');
  assert.equal(r.zip.name, 'Orbit-0.2.1-arm64-mac.zip');
  assert.equal(r.zip.url, `${DL}/desktop-v0.2.1/Orbit-0.2.1-arm64-mac.zip`);
  assert.equal(r.sums.name, 'SHA256SUMS.txt');
  assert.equal(r.dmg.name, 'Orbit-0.2.1-arm64.dmg');
  assert.equal(r.notes, 'Notes for 0.2.1');
});

test('pickRelease includes prereleases only on the beta channel', () => {
  const list = [fakeRelease('0.2.0'), fakeRelease('0.3.0-beta.1', { prerelease: true }), fakeRelease('0.3.0-rc.1')];
  assert.equal(core.pickRelease(list).version, '0.2.0');
  assert.equal(core.pickRelease(list, { channel: 'beta' }).version, '0.3.0-rc.1');
  // a later stable release beats its betas
  assert.equal(core.pickRelease([...list, fakeRelease('0.3.0')], { channel: 'beta' }).version, '0.3.0');
});

test('pickRelease skips releases missing the zip or sums, or with foreign asset URLs', () => {
  const noZip = fakeRelease('0.5.0');
  noZip.assets = noZip.assets.filter((a) => !a.name.endsWith('-mac.zip'));
  const noSums = fakeRelease('0.4.0');
  noSums.assets = noSums.assets.filter((a) => a.name !== 'SHA256SUMS.txt');
  const foreign = fakeRelease('0.3.0');
  foreign.assets = foreign.assets.map((a) => ({ ...a, browser_download_url: `https://example.com/${a.name}` }));
  const r = core.pickRelease([noZip, noSums, foreign, fakeRelease('0.2.0')]);
  assert.equal(r.version, '0.2.0');
  assert.equal(core.pickRelease([noZip, noSums, foreign]), null);
  assert.equal(core.pickRelease({ message: 'API rate limit exceeded' }), null);
  assert.equal(core.pickRelease([]), null);
});

test('validatePrefs accepts known values and rejects others', () => {
  assert.deepEqual(core.validatePrefs({ autoUpdate: 'auto', updateCheckEvery: 6, updateChannel: 'beta', extra: 1 }),
    { autoUpdate: 'auto', updateCheckEvery: 6, updateChannel: 'beta' });
  assert.deepEqual(core.validatePrefs({}), {});
  assert.throws(() => core.validatePrefs({ autoUpdate: 'sometimes' }), TypeError);
  assert.throws(() => core.validatePrefs({ updateCheckEvery: 2 }), TypeError);
  assert.throws(() => core.validatePrefs({ updateChannel: 'nightly' }), TypeError);
  assert.throws(() => core.validatePrefs(null), TypeError);
  assert.throws(() => core.validatePrefs([]), TypeError);
});

test('scheduling, notes and labels', () => {
  const H = 3600 * 1000;
  const now = 1_000_000_000_000;
  assert.equal(core.msUntilDue(0, 24, now), 0);
  assert.equal(core.msUntilDue(now - 2 * H, 24, now), 22 * H);
  assert.equal(core.msUntilDue(now - 2 * H, 1, now), 0);
  assert.equal(core.msUntilDue(now + H, 24, now), 0); // clock went backwards
  assert.equal(core.notesExcerpt('x'.repeat(700)).length, 601);
  assert.equal(core.notesExcerpt('short\r\n\r\n\r\n\r\nnotes'), 'short\n\nnotes');
  assert.equal(core.relativeTime(0, now), 'Never');
  assert.equal(core.relativeTime(now - 10 * 1000, now), 'just now');
  assert.equal(core.relativeTime(now - 60 * 1000, now), '1 minute ago');
  assert.equal(core.relativeTime(now - 3 * H, now), '3 hours ago');
  assert.equal(core.relativeTime(now - 50 * H, now), '2 days ago');
  assert.deepEqual(core.effectivePrefs(() => undefined),
    { autoUpdate: 'notify', updateCheckEvery: 24, updateChannel: 'stable', skippedVersion: null });
});
