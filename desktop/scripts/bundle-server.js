'use strict';
// Copies Orbit's server into desktop/build/orbit-server, which electron-builder puts in the app as
// Contents/Resources/orbit-server. That is what lets a downloaded Orbit.app run on a Mac that has no Orbit
// folder: the app sets up a Python environment on first launch (src/main/installer.js) and runs this copy.
//
// Run it from the PUBLIC tree (the sanitised repo), never from a dev tree full of personal data. It also
// refuses to finish if what it copied still looks personal.
//
//   node scripts/bundle-server.js            writes build/orbit-server
//   node scripts/bundle-server.js --check    only scans an existing build/orbit-server
const fs = require('fs');
const path = require('path');
const { version } = require('../package.json');

const DESKTOP = path.join(__dirname, '..');
// ORBIT_BUNDLE_SRC points at the sanitised public tree when the app is built from a dev checkout.
const REPO = process.env.ORBIT_BUNDLE_SRC ? path.resolve(process.env.ORBIT_BUNDLE_SRC) : path.resolve(DESKTOP, '..');
const OUT = path.join(DESKTOP, 'build', 'orbit-server');

// Never copied, wherever they sit.
const SKIP_NAMES = new Set(['__pycache__', '.DS_Store', 'node_modules', '.git', 'venv', '.venv']);
const SKIP_SUFFIX = ['.pyc', '.pyo', '.bak', '.orig', '.log', '~'];

// Served files the page does not load (the unminified mermaid build alone is 24 MB).
const WEB_DROP = [
  /^vendor\/mermaid\/(?!dist\/mermaid\.min\.js$|LICENSE$)/,
  /^vendor\/[^/]+\/README/i,
  /^vendor\/katex\/(src|contrib)\//,
  /^vendor\/katex\/(cli\.js|katex\.js|package\.json)$/,
  /^vendor\/katex\/dist\/(katex\.mjs|katex\.js|README\.md)$/,
];

const INCLUDE = [
  { src: 'bin', drop: [/(^|\/)[^/]*-llm$/] },
  { src: 'web', drop: WEB_DROP },
  { src: 'docs/claude-science-instructions.md' },
  { src: 'docs/claude-science-skill' },
  { src: 'requirements.txt' },
  { src: 'LICENSE', optional: true },
];

function skipped(name) {
  return SKIP_NAMES.has(name) || SKIP_SUFFIX.some((s) => name.endsWith(s));
}

function copyTree(src, dst, drop, rel = '') {
  const st = fs.statSync(src);
  if (st.isDirectory()) {
    fs.mkdirSync(dst, { recursive: true });
    for (const name of fs.readdirSync(src).sort()) {
      if (skipped(name)) continue;
      const r = rel ? `${rel}/${name}` : name;
      const child = path.join(src, name);
      if (!fs.statSync(child).isDirectory() && drop.some((re) => re.test(r))) continue;   // rules name files; a folder is kept if anything in it is
      copyTree(child, path.join(dst, name), drop, r);
    }
    if (!fs.readdirSync(dst).length) fs.rmdirSync(dst);                                  // nothing left in it
  } else {
    fs.mkdirSync(path.dirname(dst), { recursive: true });
    fs.copyFileSync(src, dst);
    fs.chmodSync(dst, st.mode & 0o111 ? 0o755 : 0o644);
  }
}

function* walk(dir) {
  for (const name of fs.readdirSync(dir)) {
    const p = path.join(dir, name);
    const st = fs.lstatSync(p);
    if (st.isDirectory()) yield* walk(p);
    else if (st.isFile()) yield p;
  }
}

// Paths like /Users/someone are placeholders; any other /Users/<name> is somebody's home.
// The owner's account name is spelled out in pieces so this file does not itself contain it.
const OWNER = ['runtian', 'wu'].join('');
const PLACEHOLDER_USERS = new Set(['someone', 'you', 'name', 'user', 'username', 'USER', 'Shared', 'me', 'your-name', 'yourname']);
function findings(root) {
  const out = [];
  for (const file of walk(root)) {
    const buf = fs.readFileSync(file);
    if (buf.includes(0)) continue;                      // binaries (fonts, images) are not text
    const text = buf.toString('utf8').split(`${OWNER}.com`).join('');
    const rel = path.relative(root, file);
    let m;
    const users = /\/Users\/([A-Za-z0-9._-]+)/g;
    while ((m = users.exec(text))) if (!PLACEHOLDER_USERS.has(m[1])) out.push(`${rel}: /Users/${m[1]}`);
    if (text.toLowerCase().includes(OWNER)) out.push(`${rel}: the owner's account name`);
    if (/\.ts\.net\b/.test(text)) out.push(`${rel}: a tailnet name`);
  }
  return out;
}

function main() {
  if (process.argv.includes('--check')) {
    if (!fs.existsSync(OUT)) { console.error('nothing to check: build/orbit-server does not exist'); process.exit(2); }
  } else {
    if (!fs.existsSync(path.join(REPO, 'bin', 'orbit-ui'))) {
      console.error(`bundle-server: no bin/orbit-ui in ${REPO} — run this from Orbit's repo (desktop/ inside it)`);
      process.exit(2);
    }
    fs.rmSync(OUT, { recursive: true, force: true });
    for (const item of INCLUDE) {
      const src = path.join(REPO, item.src);
      if (!fs.existsSync(src)) {
        if (item.optional) continue;
        console.error(`bundle-server: missing ${item.src}`);
        process.exit(2);
      }
      copyTree(src, path.join(OUT, item.src), item.drop || []);
    }
    fs.writeFileSync(path.join(OUT, 'VERSION'), version + '\n');
  }
  const bad = findings(OUT);
  if (bad.length) {
    console.error('bundle-server: this looks personal, so nothing may ship it:');
    bad.slice(0, 30).forEach((b) => console.error('  ' + b));
    fs.rmSync(OUT, { recursive: true, force: true });
    process.exit(1);
  }
  let n = 0, bytes = 0;
  for (const f of walk(OUT)) { n++; bytes += fs.statSync(f).size; }
  console.log(`bundle-server: ${n} files, ${(bytes / 1048576).toFixed(1)} MB, version ${version}, clean`);
}

if (require.main === module) main();
module.exports = { copyTree, findings, WEB_DROP, INCLUDE };
