'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const I = require('../src/main/installer');
const B = require('../scripts/bundle-server');

const tmp = () => fs.mkdtempSync(path.join(os.tmpdir(), 'orbit-inst-'));

test('python versions are read from `python --version`', () => {
  assert.deepStrictEqual(I.parsePythonVersion('Python 3.13.2\n'), [3, 13, 2]);
  assert.deepStrictEqual(I.parsePythonVersion('Python 3.9'), [3, 9, 0]);
  assert.strictEqual(I.parsePythonVersion('command not found'), null);
});

test('Orbit needs Python 3.9 or newer', () => {
  assert.ok(I.versionOk([3, 9, 6]));
  assert.ok(I.versionOk([3, 14, 0]));
  assert.ok(!I.versionOk([3, 8, 18]));
  assert.ok(!I.versionOk([2, 7, 18]));
  assert.ok(!I.versionOk(null));
});

test('findPython picks the newest usable one and skips too-old and broken ones', () => {
  const versions = {
    '/opt/homebrew/bin/python3.12': 'Python 3.12.4',
    '/opt/homebrew/bin/python3.10': 'Python 3.10.1',
    '/opt/homebrew/bin/python3': 'Python 3.8.1',
    '/usr/bin/python3': 'Python 3.9.6',
  };
  const got = I.findPython({ env: {}, exists: (p) => p in versions, hasCLT: () => true, probe: (p) => versions[p] || '' });
  assert.strictEqual(got.path, '/opt/homebrew/bin/python3.12');
  assert.deepStrictEqual(got.version, [3, 12, 4]);
  assert.strictEqual(I.findPython({ env: {}, exists: () => false, hasCLT: () => true, probe: () => '' }), null);
});

test('findPython prefers a well-supported Python over the newest one', () => {
  const versions = {
    '/opt/homebrew/bin/python3.15': 'Python 3.15.0',
    '/opt/homebrew/bin/python3.13': 'Python 3.13.7',
    '/opt/homebrew/bin/python3.12': 'Python 3.12.4',
    '/usr/bin/python3': 'Python 3.9.6',
  };
  const got = I.findPython({ env: {}, exists: (p) => p in versions, hasCLT: () => true, probe: (p) => versions[p] || '' });
  assert.strictEqual(got.path, '/opt/homebrew/bin/python3.12');
  const only = { '/opt/homebrew/bin/python3.15': 'Python 3.15.0', '/usr/bin/python3': 'Python 3.9.6' };
  const fallback = I.findPython({ env: {}, exists: (p) => p in only, hasCLT: () => true, probe: (p) => only[p] || '' });
  assert.strictEqual(fallback.path, '/usr/bin/python3');     // 3.9 still beats a too-new 3.15
});

test('/usr/bin/python3 is never run without the Command Line Tools (macOS would open an install dialog)', () => {
  const list = I.pythonCandidates({ env: {}, exists: (p) => p === '/usr/bin/python3', hasCLT: () => false });
  assert.deepStrictEqual(list, []);
  const withCLT = I.pythonCandidates({ env: {}, exists: (p) => p === '/usr/bin/python3', hasCLT: () => true });
  assert.deepStrictEqual(withCLT, ['/usr/bin/python3']);
});

test('ORBIT_PYTHON is tried first', () => {
  const list = I.pythonCandidates({ env: { ORBIT_PYTHON: '/x/python' }, exists: () => true, hasCLT: () => false });
  assert.strictEqual(list[0], '/x/python');
});

test('the managed folder is in Application Support and the venv inside it', () => {
  assert.strictEqual(I.managedRoot('/Users/someone'), '/Users/someone/Library/Application Support/Orbit');
  assert.strictEqual(I.venvPython('/r'), '/r/venv/bin/python');
});

test('setup is needed until a venv exists and the requirements match what was installed', () => {
  const root = tmp(), bundle = tmp();
  fs.writeFileSync(path.join(bundle, 'requirements.txt'), 'requests>=2\n');
  assert.ok(I.needsSetup(root, bundle), 'no venv yet');
  fs.mkdirSync(path.join(root, 'venv', 'bin'), { recursive: true });
  fs.writeFileSync(I.venvPython(root), '');
  assert.ok(I.needsSetup(root, bundle), 'venv without a finished install');
  I.writeState(root, { ok: true, requirements: I.sha256File(path.join(bundle, 'requirements.txt')) });
  assert.ok(!I.needsSetup(root, bundle));
  fs.writeFileSync(path.join(bundle, 'requirements.txt'), 'requests>=2\nnumpy\n');
  assert.ok(I.needsSetup(root, bundle), 'a newer app brought new packages');
  I.writeState(root, { ok: false, requirements: I.sha256File(path.join(bundle, 'requirements.txt')) });
  assert.ok(I.needsSetup(root, bundle), 'an install that did not finish is retried');
});

test('pip output becomes short status lines', () => {
  assert.strictEqual(I.pipStatus('Collecting markitdown>=0.1.2'), 'Installing markitdown…');
  assert.strictEqual(I.pipStatus('  Downloading numpy-2.0.2-cp39-macosx_14_0_arm64.whl (5.3 MB)'), 'Downloading numpy…');
  assert.strictEqual(I.pipStatus('Installing collected packages: a, b'), 'Installing the packages…');
  assert.strictEqual(I.pipStatus('Requirement already satisfied: x'), null);
});

test('requirement lines drop comments and blanks', () => {
  assert.deepStrictEqual(I.requirementLines('# top\nrequests>=2.31   # http\n\npillow>=10\n'), ['requests>=2.31', 'pillow>=10']);
});

test('the server runs from the bundle with its data in the managed folder', () => {
  const c = I.serverCommand({ root: '/r', bundle: '/app/orbit-server', port: 8899 });
  assert.strictEqual(c.cmd, '/r/venv/bin/python');
  assert.deepStrictEqual(c.args, ['/app/orbit-server/bin/orbit-ui', '--no-open']);
  assert.strictEqual(c.env.ORBIT_HOME, '/r');
  assert.strictEqual(c.cwd, '/r');
});

test('setup says so plainly when there is no Python, and touches nothing', async () => {
  const root = path.join(tmp(), 'Orbit'), bundle = tmp();
  fs.mkdirSync(path.join(bundle, 'bin'), { recursive: true });
  await assert.rejects(I.setup({ root, bundle, python: null }), (e) => e.needsPython === true && /Python 3\.9/.test(e.message));
  assert.ok(!fs.existsSync(root));
});

test('setup builds a venv and installs the listed packages (a real python, offline: no packages listed)', async () => {
  const py = I.findPython();
  if (!py) return;                                               // CI box without Python 3.9+
  const root = path.join(tmp(), 'Orbit'), bundle = tmp();
  fs.mkdirSync(path.join(bundle, 'bin'), { recursive: true });
  fs.writeFileSync(path.join(bundle, 'bin', 'orbit-ui'), '#!/bin/sh\n');
  fs.writeFileSync(path.join(bundle, 'VERSION'), '9.9.9\n');
  fs.writeFileSync(path.join(bundle, 'requirements.txt'), '# nothing to install\n');
  const seen = [];
  const r = await I.setup({ root, bundle, python: py, onStatus: (t) => seen.push(t) });
  assert.ok(fs.existsSync(I.venvPython(root)));
  for (const d of I.DATA_FOLDERS) assert.ok(fs.statSync(path.join(root, d)).isDirectory(), d);
  assert.strictEqual(I.readState(root).bundle, '9.9.9');
  assert.ok(!I.needsSetup(root, bundle));
  assert.ok(seen.some((t) => /first time/.test(t)));
  assert.strictEqual(r.root, root);
});

test('setup keeps what is already in the folder', async () => {
  const py = I.findPython();
  if (!py) return;
  const root = path.join(tmp(), 'Orbit'), bundle = tmp();
  fs.mkdirSync(path.join(root, 'sessions'), { recursive: true });
  fs.writeFileSync(path.join(root, 'sessions', 'cq-keep.json'), '{"keep":true}');
  fs.mkdirSync(path.join(bundle, 'bin'), { recursive: true });
  fs.writeFileSync(path.join(bundle, 'requirements.txt'), '');
  await I.setup({ root, bundle, python: py });
  assert.strictEqual(fs.readFileSync(path.join(root, 'sessions', 'cq-keep.json'), 'utf8'), '{"keep":true}');
});

test('the bundler leaves out unused vendor files and caches', () => {
  const src = tmp(), dst = path.join(tmp(), 'out');
  const put = (rel, text = 'x') => { const p = path.join(src, rel); fs.mkdirSync(path.dirname(p), { recursive: true }); fs.writeFileSync(p, text); };
  put('vendor/mermaid/dist/mermaid.min.js'); put('vendor/mermaid/dist/mermaid.js'); put('vendor/mermaid/LICENSE');
  put('vendor/katex/dist/katex.min.js'); put('vendor/katex/dist/katex.mjs'); put('vendor/katex/src/a.js');
  put('app.js'); put('__pycache__/a.pyc'); put('x.pyc'); put('.DS_Store');
  B.copyTree(src, dst, B.WEB_DROP);
  const have = (rel) => fs.existsSync(path.join(dst, rel));
  assert.ok(have('vendor/mermaid/dist/mermaid.min.js') && have('vendor/mermaid/LICENSE') && have('vendor/katex/dist/katex.min.js') && have('app.js'));
  assert.ok(!have('vendor/mermaid/dist/mermaid.js') && !have('vendor/katex/dist/katex.mjs') && !have('vendor/katex/src/a.js'));
  assert.ok(!have('__pycache__') && !have('x.pyc') && !have('.DS_Store'));
});

test('the bundler refuses a tree with somebody’s home folder or account name in it', () => {
  const d = tmp();
  const owner = ['runtian', 'wu'].join('');
  fs.writeFileSync(path.join(d, 'a.py'), `PATH = "/Users/someone/project"  # a placeholder\nSITE = "https://${owner}.com"\n`);
  assert.deepStrictEqual(B.findings(d), []);
  fs.writeFileSync(path.join(d, 'b.py'), 'PATH = "/Users/jane/project"\n');
  fs.writeFileSync(path.join(d, 'c.py'), `user = "${owner}"\n`);
  const got = B.findings(d).join('\n');
  assert.match(got, /b\.py: \/Users\/jane/);
  assert.match(got, /c\.py: the owner's account name/);
});
