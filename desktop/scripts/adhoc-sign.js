'use strict';
// electron-builder afterPack hook: ad-hoc sign the app ("codesign --sign -").
// We use this instead of mac.identity "-" because electron-builder may then
// pick a personal development certificate from the keychain if one exists.
const path = require('path');
const { execFileSync } = require('child_process');

exports.default = async function adhocSign(context) {
  if (context.electronPlatformName !== 'darwin' && context.electronPlatformName !== 'mas') return;
  const appPath = path.join(context.appOutDir, `${context.packager.appInfo.productFilename}.app`);
  execFileSync('/usr/bin/codesign', ['--force', '--deep', '--sign', '-', appPath], { stdio: 'inherit' });
  console.log(`  • ad-hoc signed  file=${path.relative(process.cwd(), appPath)}`);
};
