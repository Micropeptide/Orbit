#!/usr/bin/env node
'use strict';
// Draws the menu-bar template icon (a tilted orbit ring around a dot) and writes
// build/trayTemplate.png (16px) and build/trayTemplate@2x.png (32px).
// Pure Node: supersampled coverage → RGBA → PNG via zlib. Run: npm run tray-icon
const fs = require('fs');
const path = require('path');
const zlib = require('zlib');

const CRC_TABLE = Array.from({ length: 256 }, (_, n) => {
  let c = n;
  for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
  return c >>> 0;
});
function crc32(buf) {
  let c = 0xffffffff;
  for (const b of buf) c = CRC_TABLE[(c ^ b) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}
function chunk(type, data) {
  const len = Buffer.alloc(4); len.writeUInt32BE(data.length);
  const td = Buffer.concat([Buffer.from(type, 'ascii'), data]);
  const crc = Buffer.alloc(4); crc.writeUInt32BE(crc32(td));
  return Buffer.concat([len, td, crc]);
}
function png(size, alpha) {
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(size, 0); ihdr.writeUInt32BE(size, 4);
  ihdr[8] = 8; ihdr[9] = 6; ihdr[10] = 0; ihdr[11] = 0; ihdr[12] = 0; // 8-bit RGBA
  const raw = Buffer.alloc(size * (size * 4 + 1));
  for (let y = 0; y < size; y++) {
    raw[y * (size * 4 + 1)] = 0; // filter: none
    for (let x = 0; x < size; x++) {
      const o = y * (size * 4 + 1) + 1 + x * 4;
      raw[o] = 0; raw[o + 1] = 0; raw[o + 2] = 0; // black; template images use alpha only
      raw[o + 3] = Math.round(255 * Math.min(1, Math.max(0, alpha[y * size + x])));
    }
  }
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk('IHDR', ihdr),
    chunk('IDAT', zlib.deflateSync(raw, { level: 9 })),
    chunk('IEND', Buffer.alloc(0)),
  ]);
}

// Geometry in 16pt units, centred at (8, 8).
const RING_A = 7.1, RING_B = 3.0, RING_W = 1.25, TILT = -28 * Math.PI / 180;
const PLANET_R = 2.5, GAP = 1.0;
const MOON = { t: 0.8 * Math.PI, r: 1.35 };

function inRing(px, py) {
  // Rotate into the ellipse frame; approximate distance to the ellipse by scaling.
  const c = Math.cos(-TILT), s = Math.sin(-TILT);
  const x = px * c - py * s, y = px * s + py * c;
  const k = Math.sqrt((x * x) / (RING_A * RING_A) + (y * y) / (RING_B * RING_B));
  if (k === 0) return false;
  // gradient-normalised distance to the k=1 contour
  const gx = x / (RING_A * RING_A), gy = y / (RING_B * RING_B);
  const d = (k * k - 1) / (2 * Math.hypot(gx, gy));
  return Math.abs(d) <= RING_W / 2;
}
function moonCenter() {
  const x = RING_A * Math.cos(MOON.t), y = RING_B * Math.sin(MOON.t);
  return [x * Math.cos(TILT) - y * Math.sin(TILT), x * Math.sin(TILT) + y * Math.cos(TILT)];
}

function render(size) {
  const scale = size / 16, SS = 8;
  const [mx, my] = moonCenter();
  const alpha = new Float32Array(size * size);
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      let hit = 0;
      for (let sy = 0; sy < SS; sy++) {
        for (let sx = 0; sx < SS; sx++) {
          const px = (x + (sx + 0.5) / SS) / scale - 8;
          const py = (y + (sy + 0.5) / SS) / scale - 8;
          const r = Math.hypot(px, py);
          const dm = Math.hypot(px - mx, py - my);
          let on = false;
          if (r <= PLANET_R) on = true;                       // planet
          else if (dm <= MOON.r) on = true;                   // moon on the ring
          else if (r > PLANET_R + GAP && dm > MOON.r + GAP * 0.8 && inRing(px, py)) on = true; // ring, with clearances
          if (on) hit++;
        }
      }
      alpha[y * size + x] = hit / (SS * SS);
    }
  }
  return png(size, alpha);
}

const out = path.join(__dirname, '..', 'build');
fs.mkdirSync(out, { recursive: true });
fs.writeFileSync(path.join(out, 'trayTemplate.png'), render(16));
fs.writeFileSync(path.join(out, 'trayTemplate@2x.png'), render(32));
console.log('wrote build/trayTemplate.png and build/trayTemplate@2x.png');
