'use strict';
// Writes dist/SHA256SUMS.txt for this version's dmg and zip ("<sha256>  <file>"),
// the format the in-app updater checks downloads against.
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { version } = require('../package.json');
const { assetNames } = require('../src/main/update-core');

const dist = path.join(__dirname, '..', 'dist');
const names = assetNames(version);

function sha256(file) {
  return new Promise((resolve, reject) => {
    const hash = crypto.createHash('sha256');
    fs.createReadStream(file).on('error', reject).on('data', (c) => hash.update(c)).on('end', () => resolve(hash.digest('hex')));
  });
}

(async () => {
  const lines = [];
  for (const name of [names.dmg, names.zip]) {
    const file = path.join(dist, name);
    if (!fs.existsSync(file)) {
      console.error(`missing ${path.relative(process.cwd(), file)} (did electron-builder run?)`);
      process.exit(1);
    }
    lines.push(`${await sha256(file)}  ${name}`);
  }
  fs.writeFileSync(path.join(dist, names.sums), lines.join('\n') + '\n');
  console.log(`wrote dist/${names.sums}:\n${lines.join('\n')}`);
})().catch((err) => { console.error(err); process.exit(1); });
