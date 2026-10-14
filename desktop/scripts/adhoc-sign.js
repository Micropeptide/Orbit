'use strict';
// electron-builder afterPack hook: give the app its Icon Composer icon, then ad-hoc sign
// it ("codesign --sign -").
//
// The icon: macOS 26 and later show an app that has only a classic .icns on a grey plate
// of their own, whatever shape the .icns is. build/Orbit.icon (made with Icon Composer's
// format) is compiled by Xcode's actool into Assets.car and named in Info.plist
// (CFBundleIconName), which the system shows full-bleed, light and dark. The .icns stays
// for older macOS. Without Xcode 26's actool the build goes on with the .icns alone.
//
// Signing: ad-hoc instead of mac.identity "-", because electron-builder may then pick a
// personal development certificate from the keychain if one exists.
const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFileSync } = require('child_process');

function addIconComposerIcon(appPath) {
  const src = path.join(__dirname, '..', 'build', 'Orbit.icon');
  if (!fs.existsSync(src)) return;
  const out = fs.mkdtempSync(path.join(os.tmpdir(), 'orbit-icon-'));
  try {
    execFileSync('/usr/bin/xcrun', ['actool', src, '--compile', out,
      '--output-partial-info-plist', path.join(out, 'partial.plist'),
      '--app-icon', 'Orbit', '--include-all-app-icons', '--target-device', 'mac',
      '--minimum-deployment-target', '11.0', '--platform', 'macosx'], { stdio: 'ignore' });
  } catch (e) {
    console.warn('  • Orbit.icon not compiled (needs Xcode 26 or later): the .icns icon only');
    return;
  }
  const car = path.join(out, 'Assets.car');
  if (!fs.existsSync(car)) return;
  fs.copyFileSync(car, path.join(appPath, 'Contents', 'Resources', 'Assets.car'));
  execFileSync('/usr/bin/plutil', ['-replace', 'CFBundleIconName', '-string', 'Orbit',
    path.join(appPath, 'Contents', 'Info.plist')]);
  fs.rmSync(out, { recursive: true, force: true });
  console.log('  • Icon Composer icon added  name=Orbit');
}

exports.default = async function adhocSign(context) {
  if (context.electronPlatformName !== 'darwin' && context.electronPlatformName !== 'mas') return;
  const appPath = path.join(context.appOutDir, `${context.packager.appInfo.productFilename}.app`);
  addIconComposerIcon(appPath);
  execFileSync('/usr/bin/codesign', ['--force', '--deep', '--sign', '-', appPath], { stdio: 'inherit' });
  console.log(`  • ad-hoc signed  file=${path.relative(process.cwd(), appPath)}`);
};
