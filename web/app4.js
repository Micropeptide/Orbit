// (app4.js) A small QR code maker (byte mode, error correction L, versions 1 to 10: up to 271 characters), so an invitation can be scanned from a phone without any outside service.
// window.orbitQR(text) -> array of rows of 0/1, or null when the text is too long; window.orbitQRCanvas(text, px) -> a <canvas> (or null).
(() => {
  'use strict';
  // [data codewords per block, error-correction codewords per block, blocks of the first kind, blocks of the second kind (one data codeword more)]
  const V = [null, [19, 7, 1, 0], [34, 10, 1, 0], [55, 15, 1, 0], [80, 20, 1, 0], [108, 26, 1, 0], [68, 18, 2, 0], [78, 20, 2, 0], [97, 24, 2, 0], [116, 30, 2, 0], [68, 18, 2, 2]];
  const ALIGN = [null, [], [6, 18], [6, 22], [6, 26], [6, 30], [6, 34], [6, 22, 38], [6, 24, 42], [6, 26, 46], [6, 28, 50]];
  const EXP = new Uint8Array(512), LOG = new Uint8Array(256);
  for (let i = 0, x = 1; i < 255; i++) { EXP[i] = x; LOG[x] = i; x <<= 1; if (x & 256) x ^= 0x11d; }
  for (let i = 255; i < 512; i++) EXP[i] = EXP[i - 255];
  const mul = (a, b) => (a && b ? EXP[LOG[a] + LOG[b]] : 0);
  function rs(data, n) {                                                        // the n error-correction codewords of a block
    let g = [1];
    for (let i = 0; i < n; i++) { const next = new Array(g.length + 1).fill(0); g.forEach((c, j) => { next[j] ^= c; next[j + 1] ^= mul(c, EXP[i]); }); g = next; }
    const r = new Array(n).fill(0);
    for (const d of data) { const f = d ^ r[0]; r.shift(); r.push(0); for (let j = 0; j < n; j++) r[j] ^= mul(g[j + 1], f); }
    return r;
  }
  const bch = (v, poly, bits) => { let r = v << bits; const top = poly.toString(2).length; for (let i = r.toString(2).length; i >= top; i--) if (r & (1 << (i - 1))) r ^= poly << (i - top); return (v << bits) | r; };
  function encode(text) {
    const bytes = Array.from(new TextEncoder().encode(text));
    let ver = 0; for (let v = 1; v <= 10; v++) { const [d, , b1, b2] = V[v]; if (bytes.length + 2 + (v >= 10 ? 1 : 0) <= d * b1 + (d + 1) * b2) { ver = v; break; } }
    if (!ver) return null;
    const [dcw, ecw, b1, b2] = V[ver], total = dcw * b1 + (dcw + 1) * b2, bits = [];
    const put = (val, n) => { for (let i = n - 1; i >= 0; i--) bits.push((val >> i) & 1); };
    put(4, 4); put(bytes.length, ver >= 10 ? 16 : 8); bytes.forEach((b) => put(b, 8));
    for (let i = 0; i < 4 && bits.length < total * 8; i++) bits.push(0);
    while (bits.length % 8) bits.push(0);
    const cw = []; for (let i = 0; i < bits.length; i += 8) cw.push(parseInt(bits.slice(i, i + 8).join(''), 2));
    for (let p = 0; cw.length < total; p++) cw.push(p % 2 ? 0x11 : 0xec);
    const blocks = []; let o = 0;
    for (let i = 0; i < b1 + b2; i++) { const n = i < b1 ? dcw : dcw + 1; blocks.push(cw.slice(o, o + n)); o += n; }
    const ecs = blocks.map((b) => rs(b, ecw)), out = [];
    for (let i = 0; i < dcw + 1; i++) for (const b of blocks) if (i < b.length) out.push(b[i]);
    for (let i = 0; i < ecw; i++) for (const e of ecs) out.push(e[i]);
    return { ver, out };
  }
  function build(ver, codewords, mask) {
    const n = 17 + 4 * ver, M = Array.from({ length: n }, () => new Array(n).fill(null)), F = Array.from({ length: n }, () => new Array(n).fill(false));
    const set = (r, c, v) => { if (r >= 0 && c >= 0 && r < n && c < n) { M[r][c] = v ? 1 : 0; F[r][c] = true; } };
    const finder = (r, c) => { for (let i = -1; i <= 7; i++) for (let j = -1; j <= 7; j++) set(r + i, c + j, i >= 0 && i <= 6 && j >= 0 && j <= 6 && (i === 0 || i === 6 || j === 0 || j === 6 || (i >= 2 && i <= 4 && j >= 2 && j <= 4))); };
    finder(0, 0); finder(0, n - 7); finder(n - 7, 0);
    for (let i = 8; i < n - 8; i++) { set(6, i, i % 2 === 0); set(i, 6, i % 2 === 0); }
    const A = ALIGN[ver], last = A[A.length - 1]; for (const r of A) for (const c of A) { if ((r === 6 && c === 6) || (r === 6 && c === last) || (r === last && c === 6)) continue; for (let i = -2; i <= 2; i++) for (let j = -2; j <= 2; j++) set(r + i, c + j, Math.max(Math.abs(i), Math.abs(j)) !== 1); }
    set(n - 8, 8, 1);
    for (let i = 0; i < 9; i++) { if (!F[8][i]) set(8, i, 0); if (!F[i][8]) set(i, 8, 0); }
    for (let i = 0; i < 8; i++) { if (!F[8][n - 1 - i]) set(8, n - 1 - i, 0); if (!F[n - 1 - i][8]) set(n - 1 - i, 8, 0); }
    if (ver >= 7) { const v = bch(ver, 0x1f25, 12); for (let i = 0; i < 18; i++) { const bit = (v >> i) & 1, a = Math.floor(i / 3), b = (i % 3) + n - 11; set(a, b, bit); set(b, a, bit); } }
    const bits = []; for (const c of codewords) for (let i = 7; i >= 0; i--) bits.push((c >> i) & 1);
    let bi = 0, up = true;
    for (let c = n - 1; c > 0; c -= 2) {
      if (c === 6) c = 5;
      for (let k = 0; k < n; k++) {
        const r = up ? n - 1 - k : k;
        for (let j = 0; j < 2; j++) { const cc = c - j; if (F[r][cc]) continue; let v = bi < bits.length ? bits[bi++] : 0; const m = [(r + cc) % 2 === 0, r % 2 === 0, cc % 3 === 0, (r + cc) % 3 === 0, (Math.floor(r / 2) + Math.floor(cc / 3)) % 2 === 0, ((r * cc) % 2) + ((r * cc) % 3) === 0, (((r * cc) % 2) + ((r * cc) % 3)) % 2 === 0, (((r + cc) % 2) + ((r * cc) % 3)) % 2 === 0][mask]; if (m) v ^= 1; M[r][cc] = v; }
      }
      up = !up;
    }
    const fmt = bch((1 << 3) | mask, 0x537, 10) ^ 0x5412;                           // error-correction level L is 01
    for (let i = 0; i < 15; i++) {
      const bit = (fmt >> i) & 1;
      if (i < 6) set(i, 8, bit); else if (i === 6) set(7, 8, bit); else if (i === 7) set(8, 8, bit); else if (i === 8) set(8, 7, bit); else set(8, 14 - i, bit);
      if (i < 8) set(8, n - 1 - i, bit); else set(n - 15 + i, 8, bit);
    }
    set(n - 8, 8, 1);
    return M;
  }
  function penalty(M) {
    const n = M.length; let p = 0;
    for (let pass = 0; pass < 2; pass++) { for (let i = 0; i < n; i++) { let run = 1; for (let j = 1; j < n; j++) { const a = pass ? M[j][i] : M[i][j], b = pass ? M[j - 1][i] : M[i][j - 1]; if (a === b) { run++; if (run === 5) p += 3; else if (run > 5) p++; } else run = 1; } } }
    for (let i = 0; i < n - 1; i++) for (let j = 0; j < n - 1; j++) if (M[i][j] === M[i + 1][j] && M[i][j] === M[i][j + 1] && M[i][j] === M[i + 1][j + 1]) p += 3;
    const pat = [1, 0, 1, 1, 1, 0, 1, 0, 0, 0, 0], rev = pat.slice().reverse();
    for (let i = 0; i < n; i++) for (let j = 0; j <= n - 11; j++) for (const q of [pat, rev]) { let a = true, b = true; for (let k = 0; k < 11; k++) { if (M[i][j + k] !== q[k]) a = false; if (M[j + k][i] !== q[k]) b = false; } if (a) p += 40; if (b) p += 40; }
    let dark = 0; for (const r of M) for (const v of r) dark += v; p += Math.floor(Math.abs((dark * 100) / (n * n) - 50) / 5) * 10;
    return p;
  }
  window.orbitQR = (text) => {
    const e = encode(String(text)); if (!e) return null;
    let best = null, bp = Infinity;
    for (let m = 0; m < 8; m++) { const M = build(e.ver, e.out, m), p = penalty(M); if (p < bp) { bp = p; best = M; } }
    return best;
  };
  window.orbitQRCanvas = (text, px) => {
    const M = window.orbitQR(text); if (!M) return null;
    const q = 4, n = M.length, s = Math.max(2, Math.floor((px || 220) / (n + 2 * q))), c = document.createElement('canvas'); c.width = c.height = (n + 2 * q) * s;
    const g = c.getContext('2d'); g.fillStyle = '#fff'; g.fillRect(0, 0, c.width, c.height); g.fillStyle = '#000';
    for (let r = 0; r < n; r++) for (let k = 0; k < n; k++) if (M[r][k]) g.fillRect((k + q) * s, (r + q) * s, s, s);
    c.setAttribute('role', 'img'); c.setAttribute('aria-label', 'QR code of the invitation link'); return c;
  };
})();
