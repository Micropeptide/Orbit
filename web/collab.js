// Orbit shared projects: the page a member (or the host) uses; the iPhone app shows this same page. It talks only to /api/collab/ on the host that served it.
// Every piece of text from anyone is put on the page with textContent / text nodes: nothing here ever builds HTML from a message.
// Working rules for this file: no inline handlers or scripts (the page's policy forbids them), no request to any other address, no service worker, and nothing that needs
// a secure page without a fallback (copying, sharing and the clipboard all degrade to a plain message).
(() => {
  'use strict';
  const BASE = ((document.querySelector('meta[name="orbit-base"]') || {}).content || '').replace(/\/$/, '');     // '' on a host's own door, '/r/<project>' behind the relay
  const API = BASE + '/api/collab';
  const KEY = 'orbit-collab:' + location.origin + BASE;
  const RELAY_PID = (/^\/r\/(p_[0-9a-f]{12})$/.exec(BASE) || [])[1] || null;       // behind the Orbit service people can sign in with an Orbit account
  const $app = document.getElementById('app');
  const COARSE = !!(window.matchMedia && matchMedia('(pointer: coarse)').matches);
  const NARROW = () => innerWidth <= 720;
  const LOOKS = ['\u{1F44D}', '✅', '\u{1F440}', '❤️'];
  const TURN_MODES = { free: 'first come, first served', round_robin: 'taking turns', approve_each: 'an approver says yes to each question' };

  // ---------------------------------------------------------------- state
  let S = null;                                   // {pid, token, name}
  let project = null, members = {}, chat = 'main';
  let raw = [], seen = new Set(), view = [], idx = new Map(), RX = {}, answered = new Set(), turnsOpen = {}, lastSeq = 0, moreBefore = false, loadingEarlier = false, loaded = false;
  let outbox = [], sentWait = [], editing = null, replyTo = null, divider = null;
  const expanded = new Set();
  let lastRead = {}, drafts = {};
  let net = { state: 'connecting', why: '', retryAt: 0 };
  let loopId = 0, wake = null, streamCtl = null, pollUntil = 0, shell = null, el = {};

  // ---------------------------------------------------------------- small helpers
  const h = (tag, attrs, ...kids) => {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (k === 'class') e.className = v; else if (k === 'style') e.style.cssText = v; else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
      else if (v !== false && v != null) e.setAttribute(k, v === true ? '' : v);
    }
    for (const k of kids.flat(2)) if (k != null && k !== false) e.append(k.nodeType ? k : document.createTextNode(String(k)));
    return e;
  };
  const NS = 'http://www.w3.org/2000/svg';
  const ICONS = {
    menu: 'M4 6h16M4 12h16M4 18h16', search: 'M11 4a7 7 0 1 0 0 14a7 7 0 0 0 0-14zM21 21l-4.3-4.3', files: 'M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8zM14 3v5h5',
    users: 'M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8a4 4 0 0 0 0 8zM22 21v-2a4 4 0 0 0-3-3.9M16 3.1a4 4 0 0 1 0 7.8', send: 'M22 2L11 13M22 2l-7 20-4-9-9-4z',
    clip: 'M21 12.5l-8.6 8.6a5.5 5.5 0 0 1-7.8-7.8L13.2 4.7a3.7 3.7 0 0 1 5.2 5.2L9.8 18.5a1.8 1.8 0 0 1-2.6-2.6L15 8.1',
    more: 'M5.2 12a.9.9 0 1 0 1.8 0a.9.9 0 1 0-1.8 0M11.1 12a.9.9 0 1 0 1.8 0a.9.9 0 1 0-1.8 0M17 12a.9.9 0 1 0 1.8 0a.9.9 0 1 0-1.8 0', reply: 'M9 14L4 9l5-5M4 9h10a6 6 0 0 1 6 6v3',
    copy: 'M11 9h9a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-9a2 2 0 0 1-2-2v-9a2 2 0 0 1 2-2zM5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1', pin: 'M12 17v5M9 3h6l-1 7 3 3v2H7v-2l3-3z',
    smile: 'M12 21a9 9 0 1 0 0-18a9 9 0 0 0 0 18zM8 14s1.5 2 4 2 4-2 4-2M9 9h.01M15 9h.01', x: 'M18 6L6 18M6 6l12 12', down: 'M12 5v14M19 12l-7 7-7-7',
    alert: 'M12 9v4M12 17h.01M10.3 3.9L1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z', refresh: 'M21 12a9 9 0 1 1-3-6.7L21 8M21 3v5h-5', plus: 'M12 5v14M5 12h14',
    link: 'M10 13a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1 1M14 11a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1-1', edit: 'M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z', trash: 'M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14',
    info: 'M12 21a9 9 0 1 0 0-18a9 9 0 0 0 0 18zM12 16v-4M12 8h.01', check: 'M5 12l5 5L20 7', download: 'M12 3v12M7 10l5 5 5-5M5 21h14', save: 'M5 3h11l3 3v15H5zM8 3v6h8M8 21v-7h8v7',
  };
  const fill = (node, ...kids) => node.replaceChildren(...kids.flat(2).filter((k) => k != null && k !== false));
  const icon = (n) => { const s = document.createElementNS(NS, 'svg'); s.setAttribute('viewBox', '0 0 24 24'); s.setAttribute('class', 'ic'); s.setAttribute('aria-hidden', 'true'); const p = document.createElementNS(NS, 'path'); p.setAttribute('d', ICONS[n] || ''); s.append(p); return s; };
  const ibtn = (name, label, onclick, cls) => h('button', { type: 'button', class: cls || 'quiet', title: label, 'aria-label': label, onclick }, icon(name));
  const lsGet = (k) => { try { return localStorage.getItem(k); } catch (e) { return null; } };
  const lsSet = (k, v) => { try { localStorage.setItem(k, v); } catch (e) { /* a private window: this lasts as long as the page */ } };
  const lsDel = (k) => { try { localStorage.removeItem(k); } catch (e) { /* nothing to remove */ } };
  const load = () => { try { return JSON.parse(lsGet(KEY) || 'null'); } catch (e) { return null; } };
  const save = (s) => lsSet(KEY, JSON.stringify(s));
  const hue = (id) => { let n = 0; for (const c of String(id)) n = (n * 31 + c.charCodeAt(0)) >>> 0; return n % 360; };
  const mark = (id, name, kind, cls) => h('div', { class: 'mk ' + (kind === 'model' ? 'model' : 'human') + (cls ? ' ' + cls : ''), style: '--h:' + hue(id), 'aria-hidden': 'true' }, String(name || '?').trim()[0] ? String(name).trim()[0].toUpperCase() : '?');
  const sleep = (ms) => new Promise((ok) => setTimeout(ok, ms));
  const clock = (ts) => new Date(ts * 1000).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
  const full = (ts) => new Date(ts * 1000).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' });
  const dayKey = (ts) => { const d = new Date(ts * 1000); return d.getFullYear() + '-' + d.getMonth() + '-' + d.getDate(); };
  const dayLabel = (ts) => { const d = new Date(ts * 1000), t = new Date(); if (dayKey(ts) === dayKey(t / 1000)) return 'Today'; if (dayKey(ts) === dayKey(t / 1000 - 86400)) return 'Yesterday'; return d.toLocaleDateString([], { weekday: 'long', month: 'long', day: 'numeric', year: d.getFullYear() === t.getFullYear() ? undefined : 'numeric' }); };
  const niceSize = (n) => n == null ? '' : n < 1024 ? n + ' B' : n < 1048576 ? (n / 1024).toFixed(1) + ' KB' : (n / 1048576).toFixed(1) + ' MB';
  const newId = () => 'c' + Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
  const first = (x) => (Array.isArray(x) ? x[0] : x);
  const nm = (id) => (members[id] && members[id].name) || (id && String(id).startsWith('model:') ? String(id).slice(6) : 'someone');
  const chatName = (id) => ((project && project.chats.find((c) => c.id === id)) || {}).name || id || 'Chat';
  const curChat = () => (project && project.chats.find((c) => c.id === chat)) || null;
  const grant = () => (project && project.my_grant) || {};
  const canPost = () => !!grant().can_post && !!project && (members[project.me] || {}).state !== 'muted';
  const meName = () => (S && S.name) || 'You';

  // ---------------------------------------------------------------- toasts and the status line
  function toast(msg, o = {}) {
    const box = document.getElementById('toasts') || document.body.appendChild(h('div', { id: 'toasts', class: 'toasts', role: 'status', 'aria-live': 'polite' }));
    const t = h('div', { class: 'toast' + (o.bad ? ' bad' : '') }, h('span', {}, msg), o.action ? h('button', { type: 'button', onclick: () => { t.remove(); o.action.run(); } }, o.action.label) : null);
    box.append(t); while (box.children.length > 3) box.firstChild.remove();
    setTimeout(() => t.remove(), o.ms || (o.action ? 9000 : 4500));
  }
  const copyText = async (t, msg) => {
    try { await navigator.clipboard.writeText(t); toast(msg || 'Copied.'); }
    catch (e) { const ta = h('textarea', { 'aria-hidden': 'true', style: 'position:fixed;opacity:0;top:0' }); ta.value = t; document.body.append(ta); ta.select(); let ok = false; try { ok = document.execCommand('copy'); } catch (x) { ok = false; } ta.remove(); toast(ok ? (msg || 'Copied.') : 'Could not copy. Select the text and copy it by hand.', ok ? {} : { bad: true }); }
  };

  // ---------------------------------------------------------------- talking to the host
  class ApiError extends Error { constructor(msg, status, code, kind) { super(msg); this.status = status || 0; this.code = code; this.kind = kind || 'http'; } }
  const HTTP_WORDS = { 502: 'The host is not answering right now.', 503: 'The host’s Orbit is not sharing right now.', 504: 'The host took too long to answer.', 429: 'Too many requests. Wait a moment.', 413: 'That is too large to send.', 404: 'That is not here (any more).' };
  async function request(path, o = {}) {
    const ctl = new AbortController(); let timedOut = false;
    const timer = setTimeout(() => { timedOut = true; ctl.abort(); }, o.timeout || 20000);
    if (o.signal) o.signal.addEventListener('abort', () => ctl.abort());
    try {
      let r;
      try {
        r = await fetch(API + path, {
          method: o.body !== undefined ? 'POST' : 'GET', signal: ctl.signal, cache: 'no-store',
          headers: Object.assign({}, o.body !== undefined ? { 'Content-Type': 'application/json' } : {}, S && S.token ? { Authorization: 'Bearer ' + S.token } : {}),
          body: o.body !== undefined ? JSON.stringify(o.body) : undefined,
        });
      } catch (e) {
        if (o.signal && o.signal.aborted) throw e;
        throw new ApiError(timedOut ? 'The host took too long to answer.' : navigator.onLine === false ? 'You are offline.' : 'Could not reach the host.', 0, timedOut ? 'timeout' : 'network', 'net');
      }
      const text = await r.text().catch(() => ''); let j = {};
      try { j = text ? JSON.parse(text) : {}; } catch (e) { j = {}; }
      if (!r.ok) throw new ApiError(j.error || HTTP_WORDS[r.status] || ('The host answered with an error (' + r.status + ').'), r.status, j.code, r.status >= 500 || r.status === 429 ? 'net' : 'http');
      return j;
    } finally { clearTimeout(timer); }
  }
  // reads try again by themselves when the link drops for a moment; a write is sent once (the outbox owns retries, and a message id makes a resend safe)
  async function api(path, o = {}) {
    const tries = o.body === undefined ? (o.retry === undefined ? 2 : o.retry) : 0;
    for (let i = 0; ; i++) {
      try { return await request(path, o); }
      catch (e) {
        if (e.status === 401 && !o.quiet401) { signedOut(); throw e; }
        if (!(e instanceof ApiError) || e.kind !== 'net' || i >= tries) throw e;
        await sleep(700 * (i + 1) * (i + 1));
      }
    }
  }
  function signedOut() { loopId++; if (streamCtl) streamCtl.abort(); lsDel(KEY); lsDel(KEY + ':out'); S = null; project = null; shell = null; boot(); }

  // ---------------------------------------------------------------- joining
  function bootCard(title, ...kids) { fill($app, h('div', { class: 'boot' }, h('div', { class: 'card' }, h('h1', {}, title), kids))); }
  function showJoin(p, i, s) {
    const name = h('input', { id: 'name', autocomplete: 'nickname', maxlength: 40, placeholder: 'Your name', 'aria-label': 'Your name' });
    const err = h('div', { class: 'err', role: 'alert' });
    const go = h('button', { class: 'primary', type: 'submit' }, 'Join the project');
    fill($app, h('div', { class: 'boot' }, h('form', { class: 'card', onsubmit: async (ev) => {
      ev.preventDefault(); go.disabled = true; err.textContent = '';
      try {
        const j = await request('/join', { body: { p, i, s, name: name.value.trim() || 'Guest' } });
        S = { pid: j.project || p, token: j.token, name: j.member.name }; save(S);
        history.replaceState(null, '', BASE + '/'); start();
      } catch (e) {
        if (RELAY_PID && e.status === 403 && /Orbit account/.test(e.message)) return signInBox({ invite: { p, i, s }, name: name.value.trim(), msg: 'This invitation is for people with an Orbit account.' });
        err.textContent = e.status === 401 ? 'This invitation does not work any more. Ask for a new one.' : e.kind === 'net' ? e.message + ' Check your connection and try again.' : e.message; go.disabled = false;
      }
    } }, h('h1', {}, 'Join a shared project'), h('p', {}, 'You were invited to work together in Orbit. Everything you write here is visible to the people in the project, and models you ask run on the host’s side.'),
      h('label', { for: 'name' }, 'What should people call you?'), name, err, h('div', { class: 'actions' }, go),
      RELAY_PID ? h('p', { class: 'hint' }, 'Or ', h('button', { type: 'button', class: 'link', onclick: () => signInBox({ invite: { p, i, s }, name: name.value.trim() }) }, 'join with your Orbit account')) : null)));
    name.focus();
  }

  // ---------------------------------------------------------------- starting up: a clear loading state, a readable error with Retry, and a way back in when the network returns
  let bootTimer = 0, bootTries = 0, bootRetryAt = 0, bootTick = 0;
  function showLoading(msg) {
    clearInterval(bootTick);
    const slow = h('p', { class: 'hint', role: 'status' }, '');
    fill($app, h('div', { class: 'boot' }, h('div', { class: 'card', 'aria-busy': 'true' }, h('h1', {}, msg || 'Opening the project'), h('p', { class: 'hint' }, 'Connecting to the host…'), h('div', { class: 'progress' }, h('i')), slow)));
    const t0 = Date.now();
    bootTick = setInterval(() => { const s = (Date.now() - t0) / 1000; slow.textContent = s > 20 ? 'Still trying. The host may be asleep or the link slow; this page keeps trying by itself.' : s > 6 ? 'This is taking longer than usual…' : ''; if (!document.body.contains(slow)) clearInterval(bootTick); }, 1000);
  }
  function showBootError(e) {
    clearInterval(bootTick); clearTimeout(bootTimer); clearInterval(bootTimer);
    const net_ = !(e instanceof ApiError) || e.kind === 'net';
    const msg = h('p', { class: 'err', role: 'alert' }, (e && e.message) || 'Something went wrong.');
    const auto = h('p', { class: 'hint', role: 'status' }, '');
    const retry = () => { clearInterval(bootTimer); bootTries++; start(); };
    fill($app, h('div', { class: 'boot' }, h('div', { class: 'card' }, h('h1', {}, net_ ? 'Cannot reach the project' : 'Cannot open this project'), msg,
      net_ ? h('p', { class: 'hint' }, 'Check that you are online and that the host’s Orbit is open. Your messages are safe and nothing is lost.') : h('p', { class: 'hint' }, 'Ask the host for a new invitation if this keeps happening.'),
      auto, h('div', { class: 'actions' }, h('button', { class: 'primary', type: 'button', onclick: retry }, icon('refresh'), ' Try again'), h('button', { type: 'button', onclick: () => location.reload() }, 'Reload the page')))));
    if (net_) {
      bootRetryAt = Date.now() + Math.min(5000 * (bootTries + 1), 30000);
      bootTimer = setInterval(() => { const s = Math.ceil((bootRetryAt - Date.now()) / 1000); if (!document.body.contains(auto)) return clearInterval(bootTimer); if (s <= 0) return retry(); auto.textContent = 'Trying again in ' + s + ' s…'; }, 500);
    }
  }
  async function start() {
    showLoading();
    try { project = await api('/p/' + S.pid, { quiet401: true, timeout: 25000 }); }
    catch (e) { if (e.status === 401) { lsDel(KEY); S = null; return boot(); } return showBootError(e); }
    bootTries = 0;
    members = Object.fromEntries(project.members.map((m) => [m.id, m]));
    try { lastRead = JSON.parse(lsGet(KEY + ':read') || 'null') || null; } catch (e) { lastRead = null; }
    const fresh = !lastRead; lastRead = lastRead || {};
    try { outbox = (JSON.parse(lsGet(KEY + ':out') || '[]') || []).map((o) => Object.assign(o, { state: o.state === 'failed' ? 'failed' : 'queued' })); } catch (e) { outbox = []; }
    const wanted = lsGet(KEY + ':chat'); if (wanted && !(hashChat) && project.chats.some((c) => c.id === wanted)) chat = wanted;
    if (hashChat && project.chats.some((c) => c.id === hashChat)) chat = hashChat;
    chat = (project.chats.find((c) => c.id === chat) || project.chats[0] || { id: 'main' }).id;
    raw = []; seen = new Set(); lastSeq = 0; moreBefore = false; loaded = false; cache.clear();
    buildShell(); renderAll();
    await firstLoad(fresh);
    connectLoop();
  }
  let hashChat = null;
  async function firstLoad(fresh) {
    el.log.setAttribute('aria-busy', 'true');
    try {
      const j = await api('/p/' + S.pid + '/events?tail=1&limit=300', { timeout: 30000 });
      if (j.more_before === undefined) { ingest(j.events || []); lastSeq = Math.max(lastSeq, j.next || 0); }            // an older host: it sends the first page of everything, the loop fetches the rest
      else { ingest(j.events || []); moreBefore = !!j.more_before; lastSeq = Math.max(j.head || 0, ...raw.map((e) => e.seq)); }
      loaded = true;
      if (fresh) { for (const c of project.chats) lastRead[c.id] = Math.max(0, ...raw.filter((e) => e.chat === c.id).map((e) => e.seq)); persistRead(); }
      setDivider(); renderAll(); scrollToDivider();
    } catch (e) {
      loaded = true; el.log.removeAttribute('aria-busy'); renderAll();
      setNet('offline', e.message); loadError = e;
      return;
    } finally { el.log.removeAttribute('aria-busy'); }
    loadError = null;
  }
  let loadError = null;
  function fatal(msg) { fill($app, h('div', { class: 'boot' }, h('div', { class: 'card' }, h('h1', {}, 'This page hit a problem'), h('p', { class: 'err', role: 'alert' }, msg), h('p', { class: 'hint' }, 'Nothing you wrote is lost.'), h('div', { class: 'actions' }, h('button', { class: 'primary', onclick: () => location.reload() }, 'Reload the page'))))); }
  let errShown = 0;
  const onProblem = (m) => { if (Date.now() - errShown < 8000) return; errShown = Date.now(); if (!shell) fatal(String(m || 'An unexpected error.').slice(0, 200)); else toast('Something went wrong on this page. If it keeps happening, reload it.', { bad: true, action: { label: 'Reload', run: () => location.reload() } }); };
  window.addEventListener('error', (e) => onProblem(e.message));
  window.addEventListener('unhandledrejection', (e) => { const r = e.reason; if (r && (r.name === 'AbortError' || r instanceof ApiError)) return; onProblem(r && r.message); });

  // ---------------------------------------------------------------- the connection: catch up with plain requests, then stream; when streaming does not work (a proxy that holds it back), poll
  function setNet(state, why) {
    const was = net.state; net.state = state; if (why !== undefined) net.why = why;
    if (state === 'live' || state === 'polling') net.retryAt = 0;
    if (!shell) return;
    const c = el.conn; if (c) {
      c.className = 'conn ' + (state === 'live' ? 'live' : state === 'polling' ? 'poll' : state === 'offline' ? 'off' : '');
      fill(c, h('i'), h('span', {}, state === 'live' ? 'Live' : state === 'polling' ? 'Live (slow link)' : state === 'offline' ? 'Offline' : 'Connecting…'));
      c.title = state === 'live' ? 'Messages arrive as they are written' : state === 'polling' ? 'Your connection holds streams back, so this page asks for news every few seconds' : state === 'offline' ? (net.why || 'Not connected') + ' Press to try now.' : 'Connecting to the project';
      c.setAttribute('role', state === 'offline' ? 'button' : 'status'); c.tabIndex = state === 'offline' ? 0 : -1;
    }
    drawNetbar(was);
  }
  let netTick = 0, okTimer = 0;
  function drawNetbar(was) {
    const b = el.netbar; if (!b) return;
    clearInterval(netTick); clearTimeout(okTimer);
    if (net.state === 'offline') {
      b.hidden = false; b.className = 'netbar' + (outbox.length ? '' : '');
      const say = h('span', { role: 'status' }), btn = h('button', { type: 'button', onclick: () => tryNow() }, icon('refresh'), ' Try now');
      fill(b, icon('alert'), say, btn);
      const upd = () => { const s = Math.max(0, Math.ceil((net.retryAt - Date.now()) / 1000)); say.textContent = (navigator.onLine === false ? 'You are offline. ' : (net.why || 'The host cannot be reached.') + ' ') + (outbox.length ? 'Your ' + outbox.length + ' unsent message' + (outbox.length === 1 ? '' : 's') + ' will go when the connection is back. ' : 'Messages will arrive when it is back. ') + (s ? 'Trying again in ' + s + ' s.' : 'Trying now…'); };
      upd(); netTick = setInterval(upd, 1000);
    } else if (was === 'offline' && (net.state === 'live' || net.state === 'polling')) {
      b.hidden = false; b.className = 'netbar ok'; fill(b, icon('check'), h('span', { role: 'status' }, 'Back online.')); okTimer = setTimeout(() => { b.hidden = true; }, 2500);
    } else b.hidden = true;
  }
  function tryNow() { net.retryAt = 0; if (wake) wake(); else if (shell) connectLoop(); }
  async function catchUp(my) {
    for (;;) {
      const j = await api(`/p/${S.pid}/events?after=${lastSeq}&limit=500`, { timeout: 25000 });
      if (my !== loopId) throw new DOMException('replaced', 'AbortError');
      const ev = j.events || []; if (!ev.length) break;
      ingest(ev, true); lastSeq = Math.max(lastSeq, ev[ev.length - 1].seq);
      if (ev.length < 500) break;
    }
  }
  async function connectLoop() {
    const my = ++loopId; if (streamCtl) streamCtl.abort();
    let wait = 1500, fails = 0, empties = 0;
    setNet(net.state === 'offline' ? 'offline' : 'connecting');
    while (my === loopId) {
      try {
        if (loadError) await firstLoadAgain();
        await catchUp(my);
        flush();
        if (Date.now() < pollUntil) {
          setNet('polling'); fails = 0; wait = 1500;
          await Promise.race([sleep(3000), new Promise((ok) => { wake = ok; })]); wake = null;
          continue;
        }
        const r = await runStream(my);
        wait = 1500;
        if (r === 'silent') { pollUntil = Date.now() + 5 * 60000; empties = 0; continue; }       // opened but nothing came, not even the keepalive: hold off streaming for a while
        empties = r === 'empty' ? empties + 1 : 0; if (empties >= 3) { pollUntil = Date.now() + 2 * 60000; empties = 0; }      // a stream that keeps closing at once is no use either
        await sleep(600);
      } catch (e) {
        if (my !== loopId) return;
        fails++;
        setNet('offline', (e && e.message && e instanceof ApiError) ? e.message : (navigator.onLine === false ? 'You are offline.' : 'The host cannot be reached.'));
        net.retryAt = Date.now() + wait; drawNetbar('offline-keep');
        await Promise.race([sleep(wait), new Promise((ok) => { wake = ok; })]); wake = null;
        wait = Math.min(Math.round(wait * 1.8), 30000);
      }
    }
  }
  async function firstLoadAgain() { const j = await api('/p/' + S.pid + '/events?tail=1&limit=300'); ingest(j.events || []); if (j.more_before !== undefined) { moreBefore = !!j.more_before; lastSeq = Math.max(lastSeq, j.head || 0); } loadError = null; renderAll(); }
  async function runStream(my) {
    const ctl = new AbortController(); streamCtl = ctl; let silent = false, bytes = 0, lastByte = Date.now();
    const dog = setInterval(() => { if (Date.now() - lastByte > (bytes ? 45000 : 27000)) { silent = true; ctl.abort(); } }, 4000);
    try {
      let r;
      try { r = await fetch(`${API}/p/${S.pid}/events?stream=1`, { headers: { Authorization: 'Bearer ' + S.token, Accept: 'text/event-stream', 'Last-Event-ID': String(lastSeq) }, signal: ctl.signal, cache: 'no-store' }); }
      catch (e) { if (silent) return 'silent'; if (ctl.signal.aborted && my !== loopId) throw e; throw new ApiError(navigator.onLine === false ? 'You are offline.' : 'Could not reach the host.', 0, 'network', 'net'); }
      if (r.status === 401) { signedOut(); throw new ApiError('Signed out', 401); }
      if (!r.ok) throw new ApiError(r.status === 429 ? 'Too many windows are open on this project.' : HTTP_WORDS[r.status] || 'The host did not answer (' + r.status + ').', r.status, '', 'net');
      if (!r.body || !r.body.getReader) { pollUntil = Date.now() + 10 * 60000; return 'silent'; }
      setNet('live', ''); lastByte = Date.now();
      const rd = r.body.getReader(), dec = new TextDecoder(); let buf = '';
      for (;;) {
        let chunk; try { chunk = await rd.read(); } catch (e) { if (silent) return 'silent'; if (my !== loopId) throw e; return bytes ? 'ended' : 'empty'; }
        if (chunk.done) break;
        bytes += chunk.value.length; lastByte = Date.now();
        buf += dec.decode(chunk.value, { stream: true });
        let i; while ((i = buf.indexOf('\n\n')) >= 0) { const frame = buf.slice(0, i); buf = buf.slice(i + 2); takeFrame(frame); }
      }
      return silent ? 'silent' : bytes ? 'ended' : 'empty';
    } finally { clearInterval(dog); if (streamCtl === ctl) streamCtl = null; }
  }
  function takeFrame(frame) {
    const line = frame.split('\n').find((l) => l.startsWith('data: ')); if (!line) return;
    let e; try { e = JSON.parse(line.slice(6)); } catch (x) { return; }
    if (e.seq <= lastSeq) return; lastSeq = e.seq; ingest([e], true);
  }
  // a link that dropped while the page was in the background: look again as soon as it is back in front or the network returns
  const nudge = () => { if (!S || !shell) return; net.retryAt = 0; if (wake) wake(); };
  window.addEventListener('online', () => { nudge(); flush(); });
  window.addEventListener('offline', () => { if (shell) setNet('offline', 'You are offline.'); });
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) return;
    nudge(); refreshProject(); markRead(); if (project) updateTitle();
    if (S && shell && net.state === 'live' && Date.now() - lastHidden > 25000) connectLoop();               // a stream a phone froze in the background is not to be trusted
  });
  let lastHidden = Date.now(); document.addEventListener('visibilitychange', () => { if (document.hidden) lastHidden = Date.now(); });
  window.addEventListener('pageshow', (e) => { if (e.persisted) nudge(); });

  // ---------------------------------------------------------------- the events: stored in order, then read into what the page shows (edits and deletes applied, reactions counted)
  const STRUCTURE = new Set(['chat', 'join', 'leave', 'grant', 'member_state', 'panic', 'config', 'chat_removed', 'resume']);
  function ingest(list, live) {
    let added = false, structure = false, sorted = true;
    for (const e of list) {
      if (!e || typeof e.seq !== 'number' || seen.has(e.seq)) continue;
      seen.add(e.seq); if (raw.length && e.seq < raw[raw.length - 1].seq) sorted = false; raw.push(e); added = true; if (live && STRUCTURE.has(e.type)) structure = true;
      if (e.type === 'chat_removed' && chat === (e.payload || {}).id) chat = 'main';
    }
    if (!added) return;
    if (!sorted) raw.sort((a, b) => a.seq - b.seq);
    derive(); if (structure) refreshProjectSoon();
    if (live && loaded && !divider && el.log && (document.hidden || !atBottom()) && list.some((e) => e.type === 'msg' && e.chat === chat && e.author !== (project && project.me))) divider = { chat, seq: lastRead[chat] || 0 };
    scheduleRender();
  }
  function derive() {
    view = raw.map((e) => (e.type === 'msg' ? Object.assign({}, e, { payload: Object.assign({}, e.payload) }) : e));
    idx = new Map(); for (const e of view) idx.set(e.id, e);
    RX = {}; answered = new Set(); turnsOpen = {};
    for (const e of view) {
      const p = e.payload || {};
      if (e.type === 'delete') { const t = idx.get(p.target); if (t && t.type === 'msg') t.payload = { deleted: true }; }
      else if (e.type === 'edit') { const t = idx.get(p.target); if (t && t.type === 'msg' && t.payload && !t.payload.deleted) { t.payload.text = p.text; t.payload.edited = true; } }
      else if (e.type === 'react' && p.target) { const t = (RX[p.target] = RX[p.target] || {}); (t[p.emoji] = t[p.emoji] || new Set()).add(e.author); }
      else if (e.type === 'approval') answered.add(p.request);
      else if ((e.type === 'guard_decision' || e.type === 'queue_add') && p.request) answered.add(p.request);
      else if (e.type === 'model_turn_start') turnsOpen[p.turn] = e;
      else if (e.type === 'model_turn_end') delete turnsOpen[p.turn];
    }
    const now = Date.now() / 1000; for (const [t, e] of Object.entries(turnsOpen)) if (now - e.ts > 3600) delete turnsOpen[t];
    sentWait = sentWait.filter((s) => lastSeq < s.seq);
  }
  async function loadEarlier() {
    if (loadingEarlier || !moreBefore) return; loadingEarlier = true; renderLog();
    const oldest = raw.length ? raw[0].seq : 0, log = el.log, before = log.scrollHeight - log.scrollTop;
    try {
      const j = await api(`/p/${S.pid}/events?before=${oldest}&limit=300`, { timeout: 30000 });
      moreBefore = !!j.more_before; ingest(j.events || []); loadingEarlier = false; renderLog(); log.scrollTop = log.scrollHeight - before;
    } catch (e) { loadingEarlier = false; renderLog(); toast('Could not load earlier messages. ' + e.message, { bad: true, action: { label: 'Try again', run: loadEarlier } }); }
  }
  async function refreshProject() {
    if (!S || !project) return;
    try { const p = await api('/p/' + S.pid, { retry: 0, timeout: 15000 }); project = p; members = Object.fromEntries(p.members.map((m) => [m.id, m])); if (!project.chats.some((c) => c.id === chat)) chat = 'main'; renderAll(); } catch (e) { /* the stream or the next try handles it */ }
  }
  let rps = 0; const refreshProjectSoon = () => { clearTimeout(rps); rps = setTimeout(refreshProject, 250); };
  setInterval(() => { if (S && project && !document.hidden) refreshProject(); }, 30000);

  // ---------------------------------------------------------------- read markers
  const unreadIn = (c) => { const lr = lastRead[c] || 0; let n = 0; for (const e of view) if (e.seq > lr && e.chat === c && e.type === 'msg' && e.author !== (project && project.me) && !(e.payload || {}).deleted) n++; return n; };
  let rtimer = 0; const persistRead = () => { clearTimeout(rtimer); rtimer = setTimeout(() => lsSet(KEY + ':read', JSON.stringify(lastRead)), 400); };
  function markRead() {
    if (!project || document.hidden || !el.log || !atBottom()) return;
    let top = 0; for (let i = view.length - 1; i >= 0; i--) if (view[i].chat === chat) { top = view[i].seq; break; }
    if (top > (lastRead[chat] || 0)) { lastRead[chat] = top; persistRead(); renderRail(); updateTitle(); }
  }
  function setDivider() { const n = unreadIn(chat); divider = n ? { chat, seq: lastRead[chat] || 0 } : null; }
  function scrollToDivider() { const d = el.log.querySelector('.newdiv'); if (d && divider) el.log.scrollTop = Math.max(0, d.getBoundingClientRect().top - el.log.getBoundingClientRect().top + el.log.scrollTop - 70); else el.log.scrollTop = el.log.scrollHeight; updateJump(); }
  const atBottom = () => el.log.scrollHeight - el.log.scrollTop - el.log.clientHeight < 90;
  function updateTitle() {
    let total = 0; for (const c of project.chats) total += unreadIn(c.id);
    const waiting = view.filter((x) => x.type === 'approval_request' && !answered.has((x.payload || {}).request)).length;
    const mine = !!grant().approver && waiting > 0;
    document.title = (mine ? `(${waiting}) Needs an answer · ` : total ? `(${total}) ` : '') + 'Orbit · ' + project.name;
  }

  // ---------------------------------------------------------------- the page
  function buildShell() {
    const ta = h('textarea', { id: 'text', rows: 1, maxlength: 20000, enterkeyhint: COARSE ? 'enter' : 'send', 'aria-label': 'Message', autocomplete: 'off', autocapitalize: 'sentences' });
    const pop = h('div', { class: 'mention', role: 'listbox', hidden: true, 'aria-label': 'People and models' });
    el = {};
    el.ta = ta; el.pop = pop;
    el.conn = h('button', { type: 'button', class: 'conn', onclick: () => { if (net.state === 'offline') tryNow(); } });
    el.netbar = h('div', { class: 'netbar', hidden: true });
    el.title = h('h1', {}); el.sub = h('span', { class: 'sub' }); el.here = h('div', { class: 'here', 'aria-hidden': 'true' });
    el.tools = h('div', { style: 'display:flex;gap:.3rem;align-items:center' });
    el.rail = h('aside', { class: 'chats', 'aria-label': 'Chats' }); el.room = h('aside', { class: 'room', 'aria-label': 'People, models and project' });
    el.log = h('div', { id: 'log', role: 'log', 'aria-label': 'Messages', 'aria-live': 'polite', 'aria-relevant': 'additions', tabindex: -1 });
    el.jump = h('button', { class: 'jump', type: 'button', hidden: true, onclick: () => { scrollEnd(true); } }, icon('down'), h('span', {}, 'Latest'), h('span', { class: 'badge', hidden: true }));
    el.frozen = h('div', { class: 'frozen', role: 'status', hidden: true }, 'This project is frozen by its host. Reading works; writing is paused.');
    el.reply = h('div', { class: 'replybar', hidden: true });
    el.asks = h('div', { class: 'asks', role: 'group', 'aria-label': 'Ask a model' });
    el.limits = h('div', { class: 'limits', role: 'status' });
    el.send = h('button', { class: 'primary send', type: 'submit', 'aria-label': 'Send', title: COARSE ? 'Send' : 'Send (Enter)' }, icon('send'));
    el.attach = h('button', { type: 'button', class: 'quiet', title: 'Attach a file to this chat', 'aria-label': 'Attach a file', onclick: () => pickFile((f) => uploadFile(f, { target: 'chat', chat, text: ta.value.trim() }).then(() => { ta.value = ''; autosize(); saveDraft(); }, () => {})) }, icon('clip'));
    el.field = h('form', { class: 'field', onsubmit: (ev) => { ev.preventDefault(); post(); } }, el.attach, ta, el.send);
    el.readonly = h('div', { class: 'banner readonly', role: 'status', hidden: true }, 'You can read this project but not write in it. Ask the host for more access if you need it.');
    el.composer = h('div', { class: 'composer' }, pop, el.reply, el.asks, el.field, el.limits);
    el.main = h('main', {}, el.frozen, el.log, el.jump, el.composer, el.readonly);
    el.scrim = h('div', { class: 'scrim', hidden: true, onclick: () => closeDrawers() });
    const nav = h('button', { type: 'button', class: 'navbtn quiet', 'aria-label': 'Chats', onclick: () => { shell.classList.toggle('nav-open'); el.scrim.hidden = !shell.classList.contains('nav-open'); } }, icon('menu'));
    el.btnSearch = h('button', { type: 'button', class: 'tb', title: 'Search (Ctrl/Cmd+K)', 'aria-label': 'Search', onclick: showSearch }, icon('search'), h('span', {}, 'Search'));
    el.btnFiles = h('button', { type: 'button', class: 'tb', title: 'Files', 'aria-label': 'Files', onclick: showFiles }, icon('files'), h('span', {}, 'Files'));
    el.btnRoom = h('button', { type: 'button', class: 'tb', title: 'People, models and project', 'aria-label': 'People and models', 'aria-expanded': 'false', onclick: toggleRoom }, icon('users'), h('span', {}, 'People'));
    const top = h('header', { class: 'top' }, nav, h('div', { class: 'ttl' }, el.title, el.sub), el.conn, h('span', { class: 'grow' }), el.here, el.btnSearch, el.btnFiles, el.btnRoom);
    shell = h('div', { class: 'shell' + (innerWidth > 1100 && lsGet(KEY + ':room') !== '0' ? ' room-open' : '') }, top, el.netbar, el.rail, el.main, el.room, el.scrim);
    fill($app, shell);
    wireComposer(); wireLog();
    setNet(net.state, net.why);
  }
  function toggleRoom() {
    const on = !shell.classList.contains('room-open'); shell.classList.toggle('room-open', on); if (innerWidth > 1100) lsSet(KEY + ':room', on ? '1' : '0');
    el.scrim.hidden = !(on && innerWidth <= 1100) && !shell.classList.contains('nav-open'); el.btnRoom.classList.toggle('on', on); el.btnRoom.setAttribute('aria-expanded', String(on)); if (on && innerWidth <= 1100) shell.classList.remove('nav-open');
  }
  function closeDrawers() { shell.classList.remove('nav-open'); if (innerWidth <= 1100) { shell.classList.remove('room-open'); el.btnRoom.classList.remove('on'); el.btnRoom.setAttribute('aria-expanded', 'false'); } el.scrim.hidden = true; }

  let sigs = {};
  const once = (k, sig, fn) => { if (sigs[k] === sig) return; sigs[k] = sig; fn(); };
  function renderAll() {
    if (!shell || !project) return;
    renderHeader(); renderRail(); renderRoom(); renderComposerBits(); renderLog(); updateTitle();
  }
  function renderHeader() {
    const online = (project.online || []).filter((m) => members[m]);
    once('head', [project.name, chatName(chat), online.join(), project.members.length, !!grant().files_download + '' + !!grant().files_browse + !!grant().files_upload_dir].join('|'), () => {
      el.title.textContent = project.name; el.sub.textContent = '# ' + chatName(chat) + ' · ' + (online.length ? online.length + ' here now' : project.members.length + ' ' + (project.members.length === 1 ? 'person' : 'people'));
      fill(el.here, ...online.slice(0, 4).map((m) => mark(m, nm(m), 'person', 'sm')), online.length > 4 ? h('span', { class: 'hint', style: 'margin-left:6px' }, '+' + (online.length - 4)) : null);
      const gr = grant(); el.btnFiles.hidden = !(gr.files_download || gr.files_browse || gr.files_upload_dir);
    });
    el.frozen.hidden = !project.frozen;
    const cp = canPost(); el.field.hidden = !cp; el.asks.hidden = !cp || !(project.models || []).length; el.readonly.hidden = cp;
    el.attach.hidden = !(grant().files_upload_chat && cp);
    el.ta.placeholder = (project.models || []).length ? (NARROW() ? 'Message, or @ to ask a model' : 'Write to the group, or type @ to ask a model') : 'Write to the group';
  }
  function renderRail() {
    const sig = JSON.stringify([chat, project.chats.map((c) => [c.id, c.name, unreadIn(c.id), c.imported || 0]), canPost()]);
    once('rail', sig, () => {
      const open = (id) => { openChat(id); };
      fill(el.rail, 
        h('h2', {}, 'Chats', h('span', { class: 'grow' }), canPost() ? h('button', { type: 'button', class: 'quiet', onclick: showNewChat, title: 'Start a new chat', 'aria-label': 'New chat' }, icon('plus'), ' New') : null),
        h('ul', { role: 'list' }, project.chats.map((c) => { const n = unreadIn(c.id); return h('li', { role: 'listitem' }, h('div', { class: 'chatrow' + (c.id === chat ? ' on' : '') + (n ? ' unread' : ''), tabindex: 0, role: 'button', 'aria-current': c.id === chat ? 'true' : 'false', 'data-chat': c.id, onclick: () => open(c.id),
          onkeydown: (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(c.id); } else if (e.key === 'ContextMenu') menu(e, chatMenu(c)); }, oncontextmenu: (e) => menu(e, chatMenu(c)) },
          h('span', { class: 'hash' }, '#'), h('span', { class: 'nm' }, c.name), c.imported ? h('span', { class: 'chip', title: 'Shared from the host’s Mac' }, 'imported') : null, n ? h('span', { class: 'badge', 'aria-label': n + ' unread' }, n > 99 ? '99+' : n) : null)); })),
        h('h2', {}, 'In this project'), h('div', { class: 'kv' }, project.members.length + ' ' + (project.members.length === 1 ? 'person' : 'people') + ' · ' + (project.models || []).length + ' model' + ((project.models || []).length === 1 ? '' : 's')),
        h('div', { style: 'display:grid;gap:.3rem;margin:.6rem .3rem' }, h('button', { type: 'button', onclick: () => { closeDrawers(); toggleRoom(); } }, icon('users'), ' People and models'), h('button', { type: 'button', onclick: showSearch }, icon('search'), ' Search')));
    });
  }
  const chatMenu = (c) => [{ label: 'Open', run: () => openChat(c.id) }, '-', canSave() ? { label: 'Save a copy of this chat…', run: () => { chat = c.id; showSave(); } } : null, { label: 'Search this project…', run: showSearch }, { label: 'Copy the chat name', run: () => copyText(c.name) }];
  const canSave = () => project && (project.allow_export !== false || project.me === project.owner);
  function renderRoom() {
    const gr = grant(), online = new Set(project.online || []);
    const sig = JSON.stringify([project.members.map((m) => [m.id, m.name, m.role, m.state, online.has(m.id)]), (project.models || []).map((m) => [m.handle, m.label, m.payer, m.usage && m.usage.label, m.usage && m.usage.left_pct]), pins().map((p) => p.seq), project.guard, project.my_limits, project.turn_mode, !!gr.can_add_members, project.frozen, theme()]);
    once('room', sig, () => {
      const people = project.members.map((m) => h('div', { class: 'person', tabindex: 0, role: 'button', 'aria-label': m.name + (m.role === 'owner' ? ', host' : '') + (online.has(m.id) ? ', here now' : ''), onclick: () => who(m), onkeydown: (e) => { if (e.key === 'Enter') who(m); },
        oncontextmenu: (e) => menu(e, [{ label: 'What can ' + (m.id === project.me ? 'I' : m.name) + ' do here?', run: () => who(m) }, m.id !== project.me && canPost() ? { label: 'Mention ' + m.name, run: () => insertMention(String(m.name).replace(/\s+/g, '')) } : null]) },
        mark(m.id, m.name, 'person', online.has(m.id) ? 'on' : ''), h('div', { class: 'info' }, h('span', { class: 'nm' }, m.name + (m.id === project.me ? ' (you)' : '')), h('span', { class: 'rl' }, (m.role === 'owner' ? 'host' : m.role) + (online.has(m.id) ? ' · here now' : ''))), m.state === 'muted' ? h('span', { class: 'chip warn' }, 'muted') : null));
      const models = (project.models || []).map((m) => h('div', { class: 'plate', tabindex: 0, role: 'button', title: 'Type @' + m.handle + ' to ask it', onclick: () => { closeDrawers(); insertMention(m.handle); }, onkeydown: (e) => { if (e.key === 'Enter') insertMention(m.handle); } },
        h('div', { class: 'top' }, h('b', {}, '@' + m.handle), m.label && m.label !== m.handle ? h('span', { class: 'hint' }, m.label) : null, m.payer && m.payer !== 'the host' ? h('span', { class: 'chip' }, 'paid by ' + m.payer) : null), usageLine(m.usage)));
      fill(el.room, 
        h('h2', {}, 'People', h('span', { class: 'grow' }), gr.can_add_members ? h('button', { type: 'button', class: 'quiet', onclick: showInvite }, icon('plus'), ' Invite') : null), people,
        (project.models || []).length ? [h('h2', {}, 'Models you can ask'), models, h('div', { class: 'kv' }, 'Questions are answered: ' + (TURN_MODES[project.turn_mode] || 'in order') + '.')] : [h('h2', {}, 'Models'), h('div', { class: 'kv' }, 'The host has not shared a model yet. You can still chat with the people here.')],
        (project.my_limits || []).length ? [h('h2', {}, 'Your allowance'), ...project.my_limits.map((l) => limitMeter(l))] : null,
        pins().length ? [h('h2', {}, 'Pinned'), h('div', { class: 'pins' }, pins().map((x) => h('p', { class: 'pinned', title: 'Pinned by ' + nm(x.author) }, String((x.payload || {}).text || '').slice(0, 140))))] : null,
        h('h2', {}, 'This project'), h('div', { class: 'kv' }, 'Models work in ' + (project.working_dir || 'the project folder') + '.'),
        project.guard && project.guard.enabled ? [h('div', { class: 'kv' }, 'A second model reviews risky actions first, following the owner’s rules. It can refuse or ask a person; it cannot allow what your permissions forbid.'), project.guard.instructions ? h('div', { class: 'kv', style: 'white-space:pre-wrap' }, project.guard.instructions) : null] : null,
        h('h2', {}, 'You'), h('div', { style: 'display:grid;gap:.4rem;margin:.2rem .3rem' },
          h('button', { type: 'button', onclick: () => showGrant(project.my_summary, 'What you can do here') }, icon('info'), ' My permissions'),
          canSave() ? h('button', { type: 'button', onclick: showSave }, icon('save'), ' Save a copy of this chat') : null,
          h('button', { type: 'button', onclick: showShortcuts }, 'Keyboard shortcuts'),
          h('label', { class: 'hint', style: 'display:flex;gap:.5rem;align-items:center;margin:.2rem 0' }, 'Theme', h('select', { 'aria-label': 'Theme', onchange: (e) => setTheme(e.target.value) }, ['auto', 'light', 'dark'].map((t) => h('option', { value: t, selected: theme() === t }, t[0].toUpperCase() + t.slice(1)))))));
    });
  }
  const pins = () => view.filter((x) => x.type === 'decision_pin' && x.chat === chat).slice(-5).reverse();
  const theme = () => lsGet('orbit-collab-theme') || 'auto';
  function setTheme(t) { lsSet('orbit-collab-theme', t); applyTheme(); sigs.room = null; }
  function applyTheme() { const t = theme(), r = document.documentElement; if (t === 'light' || t === 'dark') r.setAttribute('data-theme', t); else r.removeAttribute('data-theme'); const m = document.querySelector('meta[name="theme-color"]'); if (m) m.setAttribute('content', t === 'dark' ? '#111918' : '#0d6e68'); }
  const usageLine = (u) => u ? h('div', { class: 'meter ' + (u.state || '') }, u.left_pct != null ? h('div', { class: 'bar', 'aria-hidden': 'true' }, h('i', { style: 'width:' + Math.max(0, Math.min(100, u.left_pct)) + '%' })) : null, h('span', { class: 'hint' }, u.label)) : null;
  const limitMeter = (l) => { const left = Math.max(0, l.limit - l.used), pct = l.limit ? Math.round((left / l.limit) * 100) : 0; return h('div', { class: 'meter ' + (left === 0 ? 'out' : pct <= 25 ? 'low' : ''), style: 'margin:.3rem .5rem' }, h('div', { class: 'bar', 'aria-hidden': 'true' }, h('i', { style: 'width:' + pct + '%' })), h('span', { class: 'hint' }, `${left} of ${l.limit} questions left this ${l.per}`)); };
  function renderComposerBits() {
    const ms = project.models || [], sig = JSON.stringify([ms.map((m) => [m.handle, m.usage && m.usage.state, m.usage && m.usage.label]), project.my_limits, replyTo && replyTo.id]);
    once('bits', sig, () => {
      fill(el.asks, h('span', { class: 'hint', style: 'align-self:center;flex:none' }, 'Ask'), ...ms.map((m) => h('button', { type: 'button', title: m.label + (m.payer && m.payer !== 'the host' ? ' · paid by ' + m.payer : '') + (m.usage ? ' · ' + m.usage.label : ''), onclick: () => insertMention(m.handle) }, '@' + m.handle, m.usage && m.usage.state && m.usage.state !== 'ok' ? h('small', { class: m.usage.state }, m.usage.state === 'out' ? 'used up' : 'low') : null)));
      fill(el.limits, ...(project.my_limits || []).map((l) => h('span', { class: 'num' }, `Questions to models: ${l.used} of ${l.limit} this ${l.per}`)));
      el.reply.hidden = !replyTo;
      if (replyTo) fill(el.reply, h('span', {}, 'Replying to ', h('b', {}, replyTo.name), ': ' + replyTo.snippet), h('button', { type: 'button', class: 'quiet', 'aria-label': 'Cancel the reply', onclick: () => { replyTo = null; sigs.bits = null; renderComposerBits(); } }, icon('x')));
    });
  }
  function insertMention(handle) { const t = el.ta; if (!t || !canPost()) return; t.value += (t.value && !/\s$/.test(t.value) ? ' ' : '') + '@' + handle + ' '; autosize(); saveDraft(); t.focus(); }
  function openChat(id) {
    if (id === chat) { closeDrawers(); return; }
    saveDraft(); chat = id; lsSet(KEY + ':chat', id); closeDrawers(); editing = null; replyTo = null; sigs.bits = null;
    setDivider(); el.ta.value = drafts[id] !== undefined ? drafts[id] : (lsGet(KEY + ':draft:' + id) || ''); autosize(); sigs = {}; renderAll(); scrollToDivider(); markRead();
  }
  async function newChatOpened(id) { await refreshProject(); openChat(id); }

  // ---------------------------------------------------------------- the log
  const cache = new Map();
  let raf = 0, rto = 0;                                                         // a frame, or a short timer if frames are not being drawn (a hidden or throttled page): whichever comes first
  function scheduleRender() { if (raf) return; const go = () => { cancelAnimationFrame(raf); clearTimeout(rto); raf = 0; renderAll(); }; raf = requestAnimationFrame(go); rto = setTimeout(go, 120); }
  function scrollEnd(smooth) { el.log.scrollTo ? el.log.scrollTo({ top: el.log.scrollHeight, behavior: smooth && !matchMedia('(prefers-reduced-motion: reduce)').matches ? 'smooth' : 'auto' }) : (el.log.scrollTop = el.log.scrollHeight); }
  function updateJump() {
    const far = el.log.scrollHeight - el.log.scrollTop - el.log.clientHeight > 220, n = unreadIn(chat);
    el.jump.hidden = !far; const b = el.jump.querySelector('.badge'); b.hidden = !n; b.textContent = n > 99 ? '99+' : n;
  }
  function wireLog() {
    el.log.addEventListener('scroll', () => { updateJump(); markRead(); if (el.log.scrollTop < 60 && moreBefore && !loadingEarlier && loaded) loadEarlier(); }, { passive: true });
  }
  function renderLog() {
    if (!el.log || !project) return;
    const stick = atBottom() || !loaded, items = logItems();
    const want = []; for (const it of items) { let c = cache.get(it.k); if (!c || c.sig !== it.sig) { c = { sig: it.sig, el: it.make() }; c.el.dataset.k = it.k; cache.set(it.k, c); } it.seen = true; want.push(c.el); }
    const keys = new Set(items.map((i) => i.k)); for (const k of cache.keys()) if (!keys.has(k)) cache.delete(k);
    const log = el.log; let i = 0;
    for (const e of want) { if (log.children[i] !== e) log.insertBefore(e, log.children[i] || null); i++; }
    while (log.children.length > want.length) log.lastChild.remove();
    if (stick) { log.scrollTop = log.scrollHeight; }
    updateJump(); if (stick) markRead();
  }
  function logItems() {
    const out = [], pid = project.me, mine = view.filter((e) => !e.chat || e.chat === chat);
    const canR = canPost(), canDl = !!grant().files_download;
    if (moreBefore || loadingEarlier) out.push({ k: 'earlier', sig: 'e' + loadingEarlier, make: () => h('div', { class: 'loadmore' }, h('button', { type: 'button', class: 'quiet', disabled: loadingEarlier, onclick: loadEarlier }, loadingEarlier ? 'Loading…' : 'Load earlier messages')) });
    if (!loaded) out.push({ k: 'skel', sig: 's', make: () => h('div', { class: 'skel', 'aria-label': 'Loading messages', role: 'status' }, h('i'), h('i'), h('i')) });
    else if (loadError) out.push({ k: 'lerr', sig: 'x' + loadError.message, make: () => h('div', { class: 'empty', role: 'alert' }, h('h2', {}, 'Messages did not load'), h('p', {}, loadError.message), h('p', { class: 'hint' }, 'This page keeps trying by itself.'), h('button', { class: 'primary', type: 'button', onclick: tryNow }, icon('refresh'), ' Try now')) });
    else if (!mine.some((e) => e.type === 'msg') && !outbox.some((o) => o.chat === chat) && !moreBefore) out.push(emptyItem());
    let prev = null, prevDay = '', steps = null, dividerDone = false;
    const flushSteps = () => { if (steps) { out.push(stepsItem(steps)); steps = null; } };
    for (const e of mine) {
      const p = e.payload || {}, dk = dayKey(e.ts);
      if (e.type === 'tool_request' || e.type === 'tool_result' || (e.type === 'guard_decision' && !p.request)) { (steps = steps || []).push(e); continue; }
      if (e.type === 'react' || e.type === 'edit' || e.type === 'delete' || e.type === 'approval' || e.type === 'model_turn_end' && (!p.status || p.status === 'ok')) continue;
      if (e.type === 'approval_request') { flushSteps(); if (!answered.has(p.request)) out.push(approvalItem(e)); prev = null; continue; }
      const isShown = e.type === 'msg' || sysLine(e);
      if (!isShown) continue;
      flushSteps();
      if (dk !== prevDay) { prevDay = dk; out.push({ k: 'day:' + dk, sig: dk, make: () => h('div', { class: 'day', role: 'separator' }, h('span', {}, dayLabel(e.ts))) }); prev = null; }
      if (e.type === 'msg') {
        if (divider && !dividerDone && divider.chat === chat && e.seq > divider.seq && e.author !== pid) { dividerDone = true; out.push({ k: 'newdiv', sig: 'n', make: () => h('div', { class: 'newdiv', role: 'separator' }, 'New') }); prev = null; }
        const cont = !!(prev && prev.type === 'msg' && prev.author === e.author && dk === dayKey(prev.ts) && e.ts - prev.ts < 300 && String((prev.payload || {}).initiated_by || '') === String(p.initiated_by || '') && !(prev.payload || {}).deleted);
        out.push(msgItem(e, cont, canR, canDl)); prev = e;
      } else { out.push(sysItem(e)); prev = null; }
    }
    flushSteps();
    for (const t of Object.values(turnsOpen)) if (!t.chat || t.chat === chat) out.push(workingItem(t));
    for (const o of [...outbox, ...sentWait.filter((s) => lastSeq < s.seq)]) if (o.chat === chat) out.push(outItem(o));
    return out;
  }
  function emptyItem() {
    const ms = project.models || [];
    return { k: 'empty', sig: [ms.length, canPost(), project.members.length].join(), make: () => h('div', { class: 'empty' }, h('h2', {}, curChat() && chatName(chat) !== 'Main' ? 'Start the conversation in ' + chatName(chat) : 'Nothing here yet'),
      h('p', {}, canPost() ? 'Say hello to the group' + (ms.length ? ', or ask a model.' : '.') : 'Nobody has written here yet.'),
      h('div', { class: 'tips' },
        ms.length && canPost() ? h('div', { class: 'tip' }, 'Type ', h('b', {}, '@' + ms[0].handle), ' and a question to ask a model. Everyone in the project sees the answer, who asked and who pays.') : null,
        project.members.length > 1 ? h('div', { class: 'tip' }, 'People here: ' + project.members.map((m) => m.name).slice(0, 6).join(', ') + '.') : h('div', { class: 'tip' }, 'You are the only one here so far.' + (grant().can_add_members ? ' Use People, then Invite, to add someone.' : '')),
        h('div', { class: 'tip' }, 'Press and hold a message (or right-click it) to reply, react, pin or copy. Press ? for shortcuts.'))) };
  }

  // ----- a message
  function msgItem(e, cont, canR, canDl) {
    const p = e.payload || {}, rx = RX[e.id] || {}, q = p.reply_to ? idx.get(p.reply_to) : null;
    const rxs = Object.entries(rx).map(([k, v]) => k + v.size + (v.has(project.me) ? '*' : '')).join(',');
    const sig = [e.seq, p.text || '', p.edited ? 1 : 0, p.deleted ? 1 : 0, cont ? 1 : 0, q ? (q.payload || {}).text : '', rxs, (p.attachments || []).map((a) => a.id).join(), canR, canDl, editing === e.seq, expanded.has(e.seq), (members[e.author] || {}).name, (members[e.author] || {}).role, (project.models || []).length, divider && divider.seq].join('\u0001');
    return { k: 'e' + e.seq, sig, make: () => buildMsg(e, cont, canR, canDl, rx, q) };
  }
  function buildMsg(e, cont, canR, canDl, rx, q) {
    const p = e.payload || {}, isModel = String(e.author).startsWith('model:'), handle = isModel ? String(e.author).slice(6) : null, m = members[e.author];
    const name = isModel ? (handle === 'imported' ? (p.model_label || 'Earlier answer') : handle) : (m ? m.name : 'Someone');
    const mineMsg = e.author === project.me && !p.deleted && !isModel, cfg = isModel ? (project.models || []).find((x) => x.handle === handle) : null;
    const head = [h('span', { class: 'who' }, name)];
    if (m && m.role === 'owner') head.push(h('span', { class: 'chip host' }, 'host'));
    if (isModel) head.push(h('span', { class: 'chip model' }, 'model'));
    if (e.author === project.me) head.push(h('span', { class: 'chip you' }, 'you'));
    if (p.imported) head.push(h('span', { class: 'chip', title: 'Copied into the project from the host’s own chats' }, 'imported'));
    head.push(h('time', { title: full(e.ts), datetime: new Date(e.ts * 1000).toISOString() }, clock(e.ts)));
    if (isModel && p.initiated_by) head.push(h('span', {}, 'for ' + nm(p.initiated_by)));
    if (isModel && p.model_label && p.model_label !== name) head.push(h('span', {}, 'via ' + p.model_label));
    if (cfg && cfg.payer && cfg.payer !== 'the host') head.push(h('span', { class: 'chip' }, 'paid by ' + cfg.payer));
    if (p.edited) head.push(h('span', {}, '(edited)'));
    let text;
    if (editing === e.seq && mineMsg) text = editBox(e);
    else {
      text = h('div', { class: 'mtext' }); const t = p.deleted ? 'This message was deleted.' : (p.text || ''); text.append(p.deleted ? document.createTextNode(t) : md(t));
      const long = !p.deleted && (t.length > 1600 || t.split('\n').length > 24);
      if (long && !expanded.has(e.seq)) text.classList.add('clip');
      if (long) text = h('div', {}, text, h('button', { type: 'button', class: 'more quiet', onclick: () => { if (expanded.has(e.seq)) expanded.delete(e.seq); else expanded.add(e.seq); scheduleRender(); } }, expanded.has(e.seq) ? 'Show less' : 'Show more'));
    }
    const items = () => actionsFor(e, canR, mineMsg);
    const row = h('div', { class: 'm' + (isModel ? ' model' : '') + (e.author === project.me ? ' me' : '') + (cont ? ' cont' : '') + (p.deleted ? ' deleted' : ''), 'data-seq': e.seq, role: 'article', 'aria-label': name + ' at ' + clock(e.ts),
      oncontextmenu: (ev) => { if (!String(window.getSelection()).trim()) openActions(ev, e, items(), canR); } },
      h('div', { class: 'nodecol' }, cont ? h('span', { class: 'time' }, clock(e.ts)) : mark(isModel ? 'model:' + handle : e.author, name, isModel ? 'model' : 'person')),
      h('div', { class: 'mbody' }, cont ? null : h('div', { class: 'mhead' }, head),
        q ? h('div', { class: 'quote', role: 'button', tabindex: 0, title: 'Go to the message', onclick: () => gotoSeq(q.seq), onkeydown: (k) => { if (k.key === 'Enter') gotoSeq(q.seq); } }, h('b', {}, q.author && String(q.author).startsWith('model:') ? String(q.author).slice(6) : nm(q.author)), ': ' + String((q.payload || {}).text || 'deleted message').replace(/\s+/g, ' ').slice(0, 140)) : null,
        text,
        !p.deleted && Array.isArray(p.attachments) && p.attachments.length ? h('div', { class: 'att' }, p.attachments.map((a) => canDl ? h('button', { type: 'button', class: 'file', title: 'Download', onclick: () => download(`/p/${S.pid}/attachment/${a.id}`, a.name) }, icon('download'), h('span', {}, a.name), h('span', { class: 'hint' }, niceSize(a.size))) : h('span', { class: 'chip', title: 'You cannot download this' }, a.name + ' (attached)'))) : null,
        Object.keys(rx).length ? h('div', { class: 'rx' }, Object.entries(rx).map(([em, ws]) => h('button', { type: 'button', class: ws.has(project.me) ? 'mine' : '', title: [...ws].map(nm).join(', '), 'aria-label': em + ' ' + ws.size + (ws.has(project.me) ? ', yours' : ''), onclick: () => { if (canR && !ws.has(project.me)) react(e, em); } }, em + ' ' + ws.size))) : null),
      p.deleted ? null : [h('div', { class: 'mtools' }, canR ? ibtn('smile', 'React', (ev) => openActions(ev, e, items(), canR, true)) : null, canR ? ibtn('reply', 'Reply', () => startReply(e)) : null, ibtn('more', 'More', (ev) => openActions(ev, e, items(), canR))),
        h('button', { type: 'button', class: 'quiet dotsbtn', 'aria-label': 'Message actions', onclick: (ev) => openActions(ev, e, items(), canR) }, icon('more'))]);
    longPress(row, (ev) => openActions(ev, e, items(), canR));
    return row;
  }
  function actionsFor(e, canR, mineMsg) {
    const p = e.payload || {};
    return [
      !p.deleted ? { label: 'Copy the text', icon: 'copy', run: () => copyText(p.text || '') } : null,
      canR ? { label: 'Reply', icon: 'reply', run: () => startReply(e) } : null,
      canR ? { label: 'Pin for everyone', icon: 'pin', run: () => pin(e) } : null,
      mineMsg && !(p.attachments || []).length ? { label: 'Edit', icon: 'edit', run: () => { editing = e.seq; scheduleRender(); } } : null,
      mineMsg ? '-' : null,
      mineMsg ? { label: 'Delete', icon: 'trash', danger: true, run: () => deleteMsg(e) } : null];
  }
  function editBox(e) {
    const ta = h('textarea', { rows: 3, maxlength: 20000, 'aria-label': 'Edit the message', style: 'width:100%' }); ta.value = (e.payload || {}).text || '';
    const done = () => { editing = null; scheduleRender(); };
    const saveIt = async () => { const text = ta.value.trim(); if (!text) return; try { await api('/p/' + S.pid + '/intent', { body: { id: newId(), type: 'edit', chat: e.chat || chat, payload: { target: e.id, text } } }); done(); } catch (x) { toast(x.message, { bad: true }); } };
    ta.addEventListener('keydown', (k) => { if (k.key === 'Enter' && !k.shiftKey && !k.isComposing && !COARSE) { k.preventDefault(); saveIt(); } else if (k.key === 'Escape') done(); });
    setTimeout(() => { ta.focus(); ta.setSelectionRange(ta.value.length, ta.value.length); }, 0);
    return h('div', {}, ta, h('div', { style: 'display:flex;gap:.4rem;margin-top:.3rem;align-items:center' }, h('button', { class: 'primary', type: 'button', onclick: saveIt }, 'Save'), h('button', { type: 'button', onclick: done }, 'Cancel'), h('span', { class: 'hint' }, COARSE ? '' : 'Enter saves, Esc cancels')));
  }
  const react = (e, emoji) => api('/p/' + S.pid + '/intent', { body: { id: newId(), type: 'react', chat: e.chat || chat, payload: { target: e.id, emoji } } }).catch((x) => toast(x.message, { bad: true }));
  const pin = (e) => api('/p/' + S.pid + '/intent', { body: { id: newId(), type: 'decision_pin', chat: e.chat || chat, payload: { text: String((e.payload || {}).text || '').slice(0, 500) } } }).then(() => toast('Pinned for everyone.')).catch((x) => toast(x.message, { bad: true }));
  function startReply(e) {
    const p = e.payload || {}, name = String(e.author).startsWith('model:') ? String(e.author).slice(6) : nm(e.author);
    replyTo = { id: e.id, name, snippet: String(p.text || '').replace(/\s+/g, ' ').slice(0, 80) }; sigs.bits = null; renderComposerBits(); el.ta.focus();
  }
  function deleteMsg(e) {
    confirmBox('Delete this message?', 'It disappears for everyone. A message a model has already read cannot be deleted.', 'Delete', async () => { try { await api('/p/' + S.pid + '/intent', { body: { id: newId(), type: 'delete', chat: e.chat || chat, payload: { target: e.id } } }); } catch (x) { toast(x.message, { bad: true }); } });
  }
  async function gotoSeq(seq, c) {
    if (c && c !== chat) openChat(c);
    for (let i = 0; i < 6 && raw.length && raw[0].seq > seq && moreBefore; i++) await loadEarlier();
    renderLog(); const row = el.log.querySelector(`.m[data-seq="${seq}"]`);
    if (row) { row.scrollIntoView({ block: 'center' }); row.classList.remove('hit'); void row.offsetWidth; row.classList.add('hit'); } else toast('That message is not in the part of the chat this page has loaded.');
  }

  // ----- the rest of the record: who joined, what a model did, questions waiting for a yes
  function sysLine(e) {
    const p = e.payload || {};
    switch (e.type) {
      case 'decision_pin': return { cls: 'pin', t: [h('b', {}, nm(e.author)), ' pinned: ' + String(p.text || '').slice(0, 200)] };
      case 'join': return { t: [h('b', {}, p.name || 'Someone'), ' joined'] };
      case 'leave': return { t: [h('b', {}, nm(p.member)), ' left the project'] };
      case 'panic': return { cls: 'bad', t: ['The project was frozen'] };
      case 'config': return p.frozen === false ? { t: ['The freeze was lifted'] } : null;
      case 'grant': return { t: [h('b', {}, nm(p.set_by)), ' changed what ', h('b', {}, nm(p.member)), ' can do'] };
      case 'queue_add': return (!p.refused && !p.waiting_for_approval && !(p.position > 1)) ? null : { t: p.refused ? [h('b', {}, nm(p.by)), ': ' + p.refused] : p.waiting_for_approval ? [h('b', {}, nm(p.by)), ' asked ' + p.model + ': waiting for an approver'] : [h('b', {}, nm(p.by)), ' asked ' + p.model + ': waiting, number ' + p.position] };
      case 'model_turn_start': return null;                                  // the answer carries who asked and who pays; while it works the page shows a working line
      case 'turn_changes': { const bits = [['created', 'created'], ['modified', 'changed'], ['deleted', 'removed']].filter(([k]) => (p[k] || []).length).map(([k, w]) => `${w} ${p[k].join(', ')}`), extra = (p.more || 0) + (p.hidden || 0); return { t: [h('b', {}, p.model || 'The model'), `, asked by ${p.asked_by_name || nm(p.asked_by)}, ${bits.join('; ') || 'changed files you cannot see'}${extra ? ` (and ${extra} more)` : ''}${p.truncated ? ' (the folder is large, so this list may be incomplete)' : ''}`] }; }
      case 'file_upload': return { t: [h('b', {}, nm(p.by)), ` put ${p.path} into the project folder (${niceSize(p.size)})`] };
      case 'file_edit': return { t: [h('b', {}, nm(p.by)), ` edited ${p.path}`] };
      case 'turn_undone': return { t: [`The host undid the file changes of one answer (${p.files || 0} file${p.files === 1 ? '' : 's'})`] };
      case 'model_turn_end': return p.status && p.status !== 'ok' ? { cls: 'bad', t: [p.status === 'stopped' ? 'The answer was stopped.' : p.status === 'refused' ? 'That was not allowed.' : 'The model could not answer.'] } : null;
      case 'chat': return null;
      default: return null;
    }
  }
  function sysItem(e) { const s = sysLine(e); return { k: 'e' + e.seq, sig: e.seq + ':' + JSON.stringify(e.payload || {}).length + (s.cls || '') + Object.keys(members).map((k) => members[k].name).join(), make: () => h('div', { class: 'sys ' + (s.cls || ''), role: 'listitem' }, h('div', { class: 'dot' }), h('div', { class: 't', title: full(e.ts) }, s.t)) }; }
  function stepsItem(list) {
    const k = 'steps:' + list[0].seq, bad = list.filter((e) => (e.type === 'guard_decision' && (e.payload || {}).verdict !== 'allow') || (e.type === 'tool_result' && !(e.payload || {}).ok)).length;
    const n = list.filter((e) => e.type === 'tool_request').length, who_ = first((turnsOpen[(list[0].payload || {}).turn] || {}).payload && turnsOpen[(list[0].payload || {}).turn].payload.initiated_by);
    return { k, sig: list.map((e) => e.seq).join() + (list.length), make: () => h('details', { class: 'steps sys' }, h('summary', { style: 'grid-column:1/-1;padding-left:34px' }, `${n || list.length} step${(n || list.length) === 1 ? '' : 's'} by the model`, bad ? h('span', { class: 'chip bad' }, bad + ' refused or failed') : null, who_ ? h('span', { class: 'hint' }, 'for ' + nm(who_)) : null),
      h('div', { style: 'grid-column:2' }, list.map((e) => { const p = e.payload || {};
        if (e.type === 'tool_request') return h('div', { class: 'row' }, `${p.tool} ${(p.touches || []).join(', ')}`, h('span', {}, ` · asked by ${nm(p.requested_by)}`));
        if (e.type === 'tool_result') return h('div', { class: 'row' + (p.ok ? '' : ' bad') }, p.ok ? 'done' : 'failed');
        return h('div', { class: 'row' + (p.verdict === 'allow' ? '' : ' bad') }, (p.verdict === 'allow' ? 'Allowed' + (p.approver ? ' by ' + nm(p.approver) : '') : 'Refused') + (p.tool ? ': ' + p.tool : '') + '. ' + (p.reason || '')); }))) };
  }
  function workingItem(t) { const p = t.payload; return { k: 'work:' + p.turn, sig: p.turn, make: () => h('div', { class: 'working', role: 'status' }, h('span', { class: 'dots', 'aria-hidden': 'true' }, h('i'), h('i'), h('i')), h('span', {}, `${p.model || p.label} is working for ${nm(first(p.initiated_by))}…`)) }; }
  // a model's action that needs a person's yes: the exact action, who asked and why; an approver can answer it right here
  function approvalItem(e) {
    const p = e.payload || {}, got = view.filter((x) => x.type === 'approval' && (x.payload || {}).request === p.request && x.payload.decision === 'allow').length;
    const can = !!grant().approver && (project.me !== p.requested_by || project.me === project.owner);
    return { k: 'appr:' + p.request, sig: [p.request, got, can].join(), make: () => {
      const note = h('input', { placeholder: 'A note for the model (optional)', maxlength: 200, 'aria-label': 'Note' }), isTurn = p.tool === 'model_turn';
      const send = async (decision, mode, b) => { b.disabled = true; try { await api('/p/' + S.pid + '/intent', { body: { id: newId(), type: 'approval', chat: e.chat || chat, payload: { request: p.request, decision, mode, note: note.value.trim() } } }); } catch (x) { b.disabled = false; toast(x.message, { bad: true }); } };
      const btn = (label, d, m, cls) => { const b = h('button', { type: 'button', class: cls || '', onclick: () => send(d, m, b) }, label); return b; };
      return h('div', { class: 'approval', role: 'group', 'aria-label': 'Needs an answer' },
        h('b', {}, isTurn ? `${nm(p.requested_by)} ${p.reason || 'wants to ask a model'}` : `${nm(p.requested_by)}’s request needs an answer`), h('div', { class: 'what' }, (isTurn ? '' : p.tool + ' ') + (p.args_summary || '')),
        isTurn ? null : h('div', { class: 'hint' }, 'Why it asks: ' + (p.reason || '')),
        (p.need || 1) > 1 ? h('div', { class: 'hint' }, `This needs ${p.need} different approvers (${got} so far). Anyone’s no stops it.`) : null, (p.touches && p.touches.length) ? h('div', { class: 'hint' }, 'It touches: ' + p.touches.join(', ')) : null,
        can ? h('div', { class: 'row' }, note, btn(isTurn ? 'Let it ask' : 'Approve once', 'allow', 'once', 'primary'), isTurn ? null : btn('Approve for this chat (1 hour)', 'allow', 'chat'), btn(isTurn ? 'Do not ask' : 'Deny', 'deny', 'once'))
          : h('div', { class: 'hint' }, project.me === p.requested_by ? 'Waiting for an approver (nobody approves their own request).' : 'Waiting for an approver.')); } };
  }

  // ---------------------------------------------------------------- a message of mine that has not reached the host yet: it says exactly where it is, and what to do about it
  function outItem(o) {
    return { k: 'o:' + o.id, sig: [o.state, o.err, (o.payload.text || '').length, o.seq].join(), make: () => {
      const st = o.state === 'sending' ? h('div', { class: 'mstate' }, h('span', { class: 'spin', 'aria-hidden': 'true' }), 'Sending…')
        : o.state === 'sent' ? h('div', { class: 'mstate' }, icon('check'), 'Sent')
        : o.state === 'failed' ? h('div', { class: 'mstate bad', role: 'alert' }, icon('alert'), (o.err || 'The host did not accept it.') + ' ', h('button', { type: 'button', onclick: () => retryOut(o.id) }, 'Try again'), h('button', { type: 'button', onclick: () => editOut(o.id) }, 'Edit'), h('button', { type: 'button', class: 'danger', onclick: () => dropOut(o.id) }, 'Discard'))
        : h('div', { class: 'mstate' }, icon('refresh'), 'Waiting for the connection. It sends by itself. ', h('button', { type: 'button', onclick: () => retryOut(o.id) }, 'Send now'), h('button', { type: 'button', class: 'quiet', onclick: () => dropOut(o.id) }, 'Discard'));
      const t = h('div', { class: 'mtext' }); t.append(md(o.payload.text || ''));
      return h('div', { class: 'm me pending' + (o.state === 'failed' ? ' failed' : ''), 'data-out': o.id }, h('div', { class: 'nodecol' }, mark(project.me, meName(), 'person')), h('div', { class: 'mbody' }, h('div', { class: 'mhead' }, h('span', { class: 'who' }, meName()), h('span', { class: 'chip you' }, 'you'), h('time', {}, clock(o.ts / 1000))), t, st)); } };
  }
  const persistOut = () => lsSet(KEY + ':out', JSON.stringify(outbox.map((o) => ({ id: o.id, type: o.type, chat: o.chat, payload: o.payload, ts: o.ts, state: o.state === 'failed' ? 'failed' : 'queued', err: o.err }))));
  function post() {
    const ta = el.ta, text = ta.value.trim(); if (!text || !canPost()) return;
    const o = { id: newId(), type: 'msg', chat, payload: replyTo ? { text, reply_to: replyTo.id } : { text }, ts: Date.now(), state: 'queued' };
    outbox.push(o); ta.value = ''; autosize(); drafts[chat] = ''; saveDraft(); replyTo = null; sigs.bits = null; divider = null; persistOut(); renderAll(); scrollEnd(false); flush();
  }
  const retryOut = (id) => { const o = outbox.find((x) => x.id === id); if (o) { o.state = 'queued'; o.err = ''; persistOut(); renderLog(); flush(); } };
  const dropOut = (id) => { outbox = outbox.filter((x) => x.id !== id); persistOut(); renderAll(); };
  const editOut = (id) => { const o = outbox.find((x) => x.id === id); if (!o) return; if (o.chat !== chat) openChat(o.chat); el.ta.value = (el.ta.value ? el.ta.value + '\n' : '') + o.payload.text; autosize(); dropOut(id); el.ta.focus(); };
  let flushing = false, flushTimer = 0, flushWait = 3000;
  async function flush() {
    if (flushing || !S) return; flushing = true; clearTimeout(flushTimer);
    try {
      for (const o of outbox.slice()) {
        if (o.state === 'failed') continue;
        o.state = 'sending'; renderLog();
        try { const r = await request('/p/' + S.pid + '/intent', { body: { id: o.id, type: o.type, chat: o.chat, payload: o.payload }, timeout: 25000 }); outbox = outbox.filter((x) => x !== o); o.state = 'sent'; o.seq = r.seq || 0; if (o.seq > lastSeq) sentWait.push(o); persistOut(); flushWait = 3000; }
        catch (e) {
          if (e.status === 401) { signedOut(); return; }
          if (e instanceof ApiError && e.kind === 'http') { o.state = 'failed'; o.err = e.message; persistOut(); toast('A message was not accepted: ' + e.message, { bad: true }); }
          else { o.state = 'queued'; o.err = e.message; persistOut(); flushTimer = setTimeout(flush, flushWait); flushWait = Math.min(flushWait * 2, 30000); break; }
        }
      }
    } finally { flushing = false; renderAll(); }
  }

  // ---------------------------------------------------------------- the box you type in
  const autosize = () => { const t = el.ta; if (!t) return; t.style.height = 'auto'; t.style.height = Math.min(t.scrollHeight, 176) + 'px'; };
  let dtimer = 0; const saveDraft = () => { drafts[chat] = el.ta.value; clearTimeout(dtimer); dtimer = setTimeout(() => lsSet(KEY + ':draft:' + chat, el.ta.value), 300); };
  function wireComposer() {
    const ta = el.ta; ta.value = lsGet(KEY + ':draft:' + chat) || '';
    ta.addEventListener('input', () => { autosize(); saveDraft(); });
    ta.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey && !e.isComposing && !COARSE) { e.preventDefault(); post(); }
      else if (e.key === 'ArrowUp' && !ta.value && !COARSE) { const last = [...view].reverse().find((x) => x.type === 'msg' && x.chat === chat && x.author === project.me && !(x.payload || {}).deleted && !(x.payload.attachments || []).length); if (last) { e.preventDefault(); editing = last.seq; renderLog(); } }
    });
    mentions(ta, el.pop); autosize();
    ta.addEventListener('focus', () => { setTimeout(() => { if (atBottom()) scrollEnd(false); }, 250); });
  }
  // typing @ lists the models people may ask (and the people in the project): Up/Down to choose, Tab or Enter to put it in, Esc to close
  function mentions(ta, pop) {
    let items = [], at = 0, sel = 0;
    const close = () => { pop.hidden = true; items = []; };
    const choose = (i) => { const m = items[i]; if (!m) return; const before = ta.value.slice(0, at), after = ta.value.slice(ta.selectionStart); ta.value = before + '@' + m.handle + ' ' + after; const pos = (before + '@' + m.handle + ' ').length; ta.setSelectionRange(pos, pos); close(); ta.focus(); autosize(); saveDraft(); };
    const draw = () => { fill(pop, ...items.map((m, i) => h('div', { role: 'option', class: i === sel ? 'on' : '', 'aria-selected': String(i === sel), onpointerdown: (e) => { e.preventDefault(); choose(i); } }, mark(m.kind === 'model' ? 'model:' + m.handle : m.handle, m.handle, m.kind === 'model' ? 'model' : 'person', 'sm'), h('b', {}, '@' + m.handle), h('span', { class: 'hint' }, m.kind === 'model' ? `${m.label} · paid by ${m.payer}` : 'person'), m.usage ? h('span', { class: 'hint u ' + (m.usage.state || '') }, m.usage.label) : null))); pop.hidden = !items.length; };
    ta.addEventListener('input', () => {
      const m = /(^|\s)@([\w.-]*)$/.exec(ta.value.slice(0, ta.selectionStart)); if (!m) return close();
      at = ta.selectionStart - m[2].length - 1; const q = m[2].toLowerCase();
      items = (project.models || []).map((x) => ({ handle: x.handle, label: x.label, payer: x.payer, usage: x.usage, kind: 'model' })).concat((project.members || []).filter((x) => x.id !== project.me && x.state !== 'removed').map((x) => ({ handle: String(x.name).replace(/\s+/g, ''), label: x.name, kind: 'person' }))).filter((x) => x.handle.toLowerCase().startsWith(q)).slice(0, 8);
      sel = 0; draw();
    });
    ta.addEventListener('keydown', (e) => {
      if (pop.hidden) return;
      if (e.key === 'ArrowDown') { e.preventDefault(); sel = (sel + 1) % items.length; draw(); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); sel = (sel - 1 + items.length) % items.length; draw(); }
      else if (e.key === 'Tab' || (e.key === 'Enter' && !e.shiftKey && !e.isComposing)) { e.preventDefault(); e.stopImmediatePropagation(); choose(sel); }
      else if (e.key === 'Escape') { e.preventDefault(); close(); }
    }, true);
    ta.addEventListener('blur', () => setTimeout(close, 150));
  }

  // ---------------------------------------------------------------- reading what people wrote: a small, safe Markdown (code, lists, quotes, bold, links); everything is made of nodes, never of markup
  const URL_TRIM = /[.,;:!?'"”’]+$/;
  function inline(s) {
    const out = [], re = /`([^`\n]+)`|\*\*([^*\n]+?)\*\*|\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)|(https?:\/\/[^\s<>"]+)|(^|[\s(])(@[\w.-]+)|(?:^|[^\w*])\*([^*\n]+?)\*(?![\w*])/g;
    let last = 0, m;
    while ((m = re.exec(s))) {
      if (m.index > last) out.push(s.slice(last, m.index));
      if (m[1] != null) out.push(h('code', {}, m[1]));
      else if (m[2] != null) out.push(h('strong', {}, inline(m[2])));
      else if (m[3] != null) out.push(h('a', { href: m[4], target: '_blank', rel: 'noopener noreferrer' }, m[3]));
      else if (m[5] != null) { let u = m[5], tail = ''; const t = URL_TRIM.exec(u); if (t) { tail = t[0]; u = u.slice(0, -tail.length); } if (u.endsWith(')') && !u.includes('(')) { u = u.slice(0, -1); tail = ')' + tail; } out.push(h('a', { href: u, target: '_blank', rel: 'noopener noreferrer' }, u)); if (tail) out.push(tail); }
      else if (m[7] != null) { if (m[6]) out.push(m[6]); const me = project && String(meName()).replace(/\s+/g, '').toLowerCase() === m[7].slice(1).toLowerCase(); out.push(h('span', { class: 'at' + (me ? ' me' : '') }, m[7])); }
      else if (m[8] != null) { const lead = m[0].slice(0, m[0].indexOf('*')); if (lead) out.push(lead); out.push(h('em', {}, m[8])); }
      last = m.index + m[0].length;
    }
    if (last < s.length) out.push(s.slice(last));
    return out;
  }
  function codeBlock(src, lang) {
    const pre = h('pre', {}, h('code', {}, src));
    return h('div', { class: 'codeblock' }, h('div', { class: 'bar' }, h('span', {}, lang || 'code'), h('span', { class: 'grow' }), h('button', { type: 'button', class: 'quiet', onclick: () => copyText(src, 'Code copied.') }, icon('copy'), ' Copy')), pre);
  }
  function md(text) {
    const frag = document.createDocumentFragment(), lines = String(text).replace(/\r\n?/g, '\n').split('\n'); let i = 0;
    const isBlockStart = (l) => /^\s*(```|~~~)/.test(l) || /^#{1,3}\s/.test(l) || /^\s*>/.test(l) || /^\s*([-*•])\s+/.test(l) || /^\s*\d+[.)]\s+/.test(l);
    while (i < lines.length) {
      const line = lines[i], fence = /^\s*(```|~~~)\s*([\w+#.-]*)\s*$/.exec(line);
      if (fence) { const buf = []; i++; while (i < lines.length && !new RegExp('^\\s*' + fence[1] + '\\s*$').test(lines[i])) buf.push(lines[i++]); i++; frag.append(codeBlock(buf.join('\n'), fence[2])); continue; }
      if (!line.trim()) { i++; continue; }
      const hd = /^(#{1,3})\s+(.*)$/.exec(line); if (hd) { frag.append(h('h' + (hd[1].length + 2), {}, inline(hd[2]))); i++; continue; }
      if (/^\s*>/.test(line)) { const buf = []; while (i < lines.length && /^\s*>/.test(lines[i])) buf.push(lines[i++].replace(/^\s*>\s?/, '')); frag.append(h('blockquote', {}, md(buf.join('\n')))); continue; }
      const ul = /^\s*([-*•])\s+/.test(line), ol = /^\s*\d+[.)]\s+/.test(line);
      if (ul || ol) { const li = []; const rx = ul ? /^\s*([-*•])\s+/ : /^\s*\d+[.)]\s+/; while (i < lines.length && rx.test(lines[i])) li.push(h('li', {}, inline(lines[i++].replace(rx, '')))); frag.append(h(ul ? 'ul' : 'ol', {}, li)); continue; }
      const buf = []; while (i < lines.length && lines[i].trim() && !(buf.length && isBlockStart(lines[i]))) buf.push(lines[i++]);
      const kids = []; buf.forEach((l, n) => { if (n) kids.push(h('br')); kids.push(inline(l)); }); frag.append(h('p', {}, kids));
    }
    return frag;
  }

  // ---------------------------------------------------------------- menus: a popover on a mouse, a sheet from the bottom on a touch screen (also on a long press)
  function closeMenu() { document.querySelectorAll('.ctx,.sheetwrap').forEach((m) => m.remove()); }
  function menu(ev, items, quick) {
    ev.preventDefault(); ev.stopPropagation(); closeMenu();
    const rows = items.filter(Boolean); if (!rows.length && !quick) return;
    const run = (it) => () => { closeMenu(); it.run(); };
    const body = [quick ? h('div', { class: 'quick' }, quick.map((q) => h('button', { type: 'button', 'aria-label': 'React ' + q.e, onclick: () => { closeMenu(); q.run(); } }, q.e))) : null,
      ...rows.map((it) => it === '-' ? h('div', { class: 'sep' }) : h('button', { type: 'button', role: 'menuitem', class: 'item' + (it.danger ? ' danger' : ''), onclick: run(it) }, it.icon ? icon(it.icon) : null, it.label))];
    if (NARROW() || COARSE || ev.__sheet) {
      const wrap = h('div', { class: 'sheetwrap', onclick: (e) => { if (e.target === wrap) closeMenu(); } }, h('div', { class: 'sheet', role: 'menu' }, h('div', { class: 'grab' }), ev.__quote ? h('div', { class: 'quote' }, ev.__quote) : null, body));
      document.body.append(wrap); const f = wrap.querySelector('button.item') || wrap.querySelector('button'); if (f && !COARSE) f.focus(); return;
    }
    const m = h('div', { class: 'ctx', role: 'menu' }, body); document.body.append(m);
    const r = ev.target && ev.target.getBoundingClientRect ? ev.target.getBoundingClientRect() : { left: 0, bottom: 0 };
    const x = ev.clientX || r.left, y = ev.clientY || r.bottom;
    m.style.left = Math.max(6, Math.min(x, innerWidth - m.offsetWidth - 6)) + 'px'; m.style.top = Math.max(6, Math.min(y, innerHeight - m.offsetHeight - 6)) + 'px';
    const f = m.querySelector('button.item'); if (f) f.focus();
    m.addEventListener('keydown', (e) => { const b = [...m.querySelectorAll('button')], i = b.indexOf(document.activeElement); if (e.key === 'ArrowDown') { e.preventDefault(); b[(i + 1) % b.length].focus(); } else if (e.key === 'ArrowUp') { e.preventDefault(); b[(i - 1 + b.length) % b.length].focus(); } else if (e.key === 'Escape') closeMenu(); });
  }
  function openActions(ev, e, items, canR, reactFirst) {
    const quick = canR ? LOOKS.map((x) => ({ e: x, run: () => react(e, x) })) : null;
    ev.__quote = String((e.payload || {}).text || '').replace(/\s+/g, ' ').slice(0, 120); if (reactFirst) ev.__sheet = false;
    menu(ev, items, quick);
  }
  function longPress(node, fn) {
    if (!COARSE) return; let t = 0, sx = 0, sy = 0;
    const cancel = () => { clearTimeout(t); t = 0; };
    node.addEventListener('touchstart', (ev) => { if (ev.touches.length !== 1 || ev.target.closest('a,button,textarea,input,pre')) return; sx = ev.touches[0].clientX; sy = ev.touches[0].clientY; t = setTimeout(() => { t = 0; if (navigator.vibrate) try { navigator.vibrate(8); } catch (x) { /* no haptics */ } fn({ preventDefault() {}, stopPropagation() {}, target: node, clientX: sx, clientY: sy }); }, 480); }, { passive: true });
    node.addEventListener('touchmove', (ev) => { if (t && (Math.abs(ev.touches[0].clientX - sx) > 9 || Math.abs(ev.touches[0].clientY - sy) > 9)) cancel(); }, { passive: true });
    node.addEventListener('touchend', cancel, { passive: true }); node.addEventListener('touchcancel', cancel, { passive: true });
  }
  document.addEventListener('click', (e) => { if (!e.target.closest('.ctx')) document.querySelectorAll('.ctx').forEach((m) => m.remove()); });
  window.addEventListener('blur', () => document.querySelectorAll('.ctx').forEach((m) => m.remove()));
  window.addEventListener('resize', () => document.querySelectorAll('.ctx').forEach((m) => m.remove()));

  // ---------------------------------------------------------------- dialogs
  const dlg = (title, ...kids) => { const d = h('dialog', { 'aria-label': title }, h('h2', {}, title), kids); document.body.append(d); const shut = d.close.bind(d); d.close = (v) => { shut(v); setTimeout(() => d.remove(), 0); }; d.addEventListener('close', () => d.remove()); d.addEventListener('click', (e) => { if (e.target === d) d.close(); }); d.showModal(); return d; };
    function confirmBox(title, text, label, run) { const d = dlg(title, h('p', {}, text), h('div', { class: 'actions' }, h('button', { type: 'button', onclick: () => d.close() }, 'Cancel'), h('button', { type: 'button', class: 'primary', onclick: () => { d.close(); run(); } }, label))); }
  function showShortcuts() {
    const rows = [['Ctrl/Cmd + K', 'Search this project'], ['/', 'Write a message'], ['Enter', 'Send (Shift+Enter for a new line)'], ['@', 'Ask a model or mention someone'], ['Up arrow (empty box)', 'Edit your last message'], ['Alt + Up / Down', 'Previous or next chat'], ['Right-click a message', 'Reply, react, pin, copy'], ['Esc', 'Close a window or menu'], ['?', 'This list']];
    const d = dlg('Keyboard shortcuts', h('div', { class: 'kbd' }, rows.map(([k, t]) => [h('kbd', {}, k), h('span', {}, t)])), h('div', { class: 'actions' }, h('button', { type: 'button', onclick: () => d.close() }, 'Close')));
  }
  function showSave() {
    const d = dlg('Save a copy of this chat', h('p', {}, 'Everything you can read in this chat, with who wrote each message. Tool calls are not included.'),
      h('div', { style: 'display:grid;gap:.5rem' }, h('button', { class: 'primary', type: 'button', onclick: () => { saveCopy('orbit', '.orbit-chat.json'); d.close(); } }, 'Orbit file'), h('span', { class: 'hint' }, 'In your own Orbit, Settings, Shared projects, "Import a saved shared chat" turns it into a chat of your own.'),
        h('button', { type: 'button', onclick: () => { saveCopy('md', '.md'); d.close(); } }, 'Readable text (Markdown)')), h('div', { class: 'actions' }, h('button', { type: 'button', onclick: () => d.close() }, 'Close')));
  }
  async function saveCopy(fmt, ext) {
    try {
      const r = await fetch(`${API}/p/${S.pid}/export?format=${fmt}&chat=${encodeURIComponent(chat)}`, { headers: { Authorization: 'Bearer ' + S.token } });
      if (!r.ok) { const j = await r.json().catch(() => ({})); return toast(j.error || 'Could not save a copy.', { bad: true }); }
      const url = URL.createObjectURL(await r.blob());
      const name = (project.name + ' - ' + chatName(chat)).replace(/[^\w .-]+/g, '_').slice(0, 80);
      const a = h('a', { href: url, download: name + ext }); document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 4000);
    } catch (e) { toast('Could not save a copy. ' + e.message, { bad: true }); }
  }
  function who(m) { showGrant(m.summary, m.name + (m.role ? ' (' + (m.role === 'owner' ? 'host' : m.role) + ')' : '')); }
  function showGrant(lines, title) { const d = dlg(title, lines && lines.length ? h('ul', {}, lines.map((s) => h('li', {}, s))) : h('p', {}, 'Not shown.'), h('div', { class: 'actions' }, h('button', { type: 'button', onclick: () => d.close() }, 'Close'))); }
  // words anywhere in what this member can read; each result names its chat, author and time and takes you to that message
  function showSearch() {
    const out = h('div', { class: 'results', role: 'list', 'aria-live': 'polite' }), box = h('input', { type: 'search', placeholder: 'Words to find', maxlength: 200, 'aria-label': 'Search words', enterkeyhint: 'search' });
    const hl = (text, words) => { const kids = []; let rest = text; const re = new RegExp('(' + words.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|') + ')', 'ig'); let last = 0, m; while ((m = re.exec(rest))) { if (m.index > last) kids.push(rest.slice(last, m.index)); kids.push(h('mark', {}, m[0])); last = m.index + m[0].length; if (!m[0]) break; } if (last < rest.length) kids.push(rest.slice(last)); return kids; };
    const go = async () => {
      const q = box.value.trim(); if (!q) return; fill(out, h('p', { class: 'hint' }, 'Searching…'));
      try {
        const j = await api('/p/' + S.pid + '/search?q=' + encodeURIComponent(q)), words = q.split(/\s+/).filter(Boolean).slice(0, 8);
        fill(out, ...(j.results.length ? j.results.map((e) => h('div', { role: 'listitem', class: 'r' }, h('div', { class: 'h' }, h('b', {}, String(e.author).startsWith('model:') ? String(e.author).slice(6) : nm(e.author)), ' in #' + chatName(e.chat) + ' · ' + full(e.ts)),
          h('div', {}, hl(String((e.payload || {}).text || '').replace(/\s+/g, ' ').slice(0, 300), words)), h('button', { type: 'button', class: 'link', onclick: () => { d.close(); gotoSeq(e.seq, e.chat); } }, 'Go to this message'))) : [h('p', { class: 'hint' }, 'Nothing found for “' + q + '”.')]));
      } catch (x) { fill(out, h('p', { class: 'err', role: 'alert' }, x.message), h('button', { type: 'button', onclick: go }, 'Try again')); }
    };
    box.addEventListener('keydown', (ev) => { if (ev.key === 'Enter') { ev.preventDefault(); go(); } });
    const d = dlg('Search this project', h('div', { class: 'row2' }, box, h('button', { class: 'primary', type: 'button', style: 'flex:none', onclick: go }, 'Search')), out, h('div', { class: 'actions' }, h('button', { type: 'button', onclick: () => d.close() }, 'Close'))); box.focus();
  }
  // a new chat, shared with everyone or only with the people ticked (the host can still read it on their own Mac)
  function showNewChat() {
    const name = h('input', { placeholder: 'Name, e.g. Figures for the paper', maxlength: 60, 'aria-label': 'Chat name' }), priv = h('input', { type: 'checkbox', id: 'np' });
    const others = project.members.filter((m) => m.id !== project.me && m.state !== 'muted');
    const boxes = others.map((m) => h('label', { style: 'display:flex;gap:.5rem;align-items:center;color:var(--ink)' }, h('input', { type: 'checkbox', 'data-m': m.id }), m.name));
    const list = h('div', { hidden: true }, h('p', { class: 'hint' }, 'You are always in it. The people you tick can read it and write in it; nobody else in the project can see it.'), ...boxes);
    priv.addEventListener('change', () => { list.hidden = !priv.checked; });
    const go = async (b) => {
      try {
        const sel = [...list.querySelectorAll('input:checked')].map((x) => x.dataset.m);
        if (priv.checked && !sel.length) return toast('Tick at least one person, or untick "Only some people".', { bad: true });
        b.disabled = true; const j = await api('/p/' + S.pid + '/chats', { body: { name: name.value.trim() || 'New chat', private: priv.checked, members: sel } });
        d.close(); newChatOpened(j.chat);
      } catch (x) { b.disabled = false; toast(x.message, { bad: true }); }
    };
    const create = h('button', { class: 'primary', type: 'button', onclick: () => go(create) }, 'Create chat');
    const d = dlg('New chat', name, h('label', { style: 'display:flex;gap:.5rem;align-items:center;color:var(--ink)' }, priv, 'Only some people'), list, h('div', { class: 'actions' }, h('button', { type: 'button', onclick: () => d.close() }, 'Cancel'), create)); name.focus();
  }
  // an invitation, for a member who may add people: one dialog, one button, the link ready to copy or share
  function showInvite() {
    const role = h('select', { 'aria-label': 'What they can do' }, [['commenter', 'Commenter: can write, models only read'], ['editor', 'Editor: works with the models and files'], ['viewer', 'Viewer: reads only']].map(([v, t]) => h('option', { value: v }, t)));
    const days = h('select', { 'aria-label': 'How long it works' }, [[1, '1 day'], [7, '7 days'], [30, '30 days']].map(([v, t]) => h('option', { value: v, selected: v === 7 }, t)));
    const out = h('div', {}), go = h('button', { class: 'primary', type: 'button', onclick: async () => {
      go.disabled = true; fill(out, h('p', { class: 'hint' }, 'Making the link…'));
      try {
        const j = await api('/p/' + S.pid + '/invite', { body: { role: role.value, uses: 1, expires_in: +days.value * 86400 } }), link = j.link;
        const inp = h('input', { readonly: true, value: link, 'aria-label': 'Invitation link', onfocus: (e) => e.target.select() });
        fill(out, h('p', {}, 'Send this link to one person. It works once.'), h('div', { class: 'linkbox' }, inp, h('button', { type: 'button', class: 'primary', onclick: () => copyText(link, 'Invitation link copied.') }, icon('copy'), ' Copy')),
          navigator.share ? h('button', { type: 'button', onclick: () => navigator.share({ title: 'Join ' + project.name, url: link }).catch(() => {}) }, 'Share…') : null);
      } catch (x) { fill(out, h('p', { class: 'err', role: 'alert' }, x.message)); }
      go.disabled = false;
    } }, 'Make an invitation link');
    const d = dlg('Invite someone', h('label', {}, 'They can'), role, h('label', {}, 'The link works for'), days, h('div', { class: 'actions' }, go), out, h('div', { class: 'actions' }, h('button', { type: 'button', onclick: () => d.close() }, 'Close')));
  }

  // ---------------------------------------------------------------- files: what the models made, the project folder, uploads and edits (each part is a switch the host set)
  async function download(path, fallback) {
    try {
      const r = await fetch(API + path, { headers: { Authorization: 'Bearer ' + S.token } });
      if (!r.ok) { const j = await r.json().catch(() => ({})); return toast(j.error || 'Could not download that.', { bad: true }); }
      const cd = r.headers.get('Content-Disposition') || '', m = /filename\*=UTF-8''([^;]+)/.exec(cd);
      const name = m ? decodeURIComponent(m[1]) : fallback || 'file';
      const url = URL.createObjectURL(await r.blob()); const a = h('a', { href: url, download: name }); document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 4000);
    } catch (e) { toast('Could not download that. ' + e.message, { bad: true }); }
  }
  function pickFile(cb) { const i = h('input', { type: 'file', style: 'display:none' }); i.addEventListener('change', () => { if (i.files[0]) cb(i.files[0]); i.remove(); }); document.body.append(i); i.click(); }
  // a file goes up in pieces of 400 kB (so it can pass the relay), then is put in place; progress is shown as a message
  async function uploadFile(file, opts) {
    const bar = h('div', { class: 'toast', role: 'status' }, h('span', { class: 'spin' }), h('span', {}, `Sending ${file.name}…`)); const box = document.getElementById('toasts') || document.body.appendChild(h('div', { id: 'toasts', class: 'toasts', role: 'status' })); box.append(bar); const say = bar.lastChild;
    try {
      const b = await api('/p/' + S.pid + '/upload', { body: { name: file.name, size: file.size, target: opts.target, dir: opts.dir || '', chat: opts.chat || 'main', text: opts.text || '' } });
      for (let n = 0, off = 0; off < file.size; n++, off += b.chunk) {
        const piece = file.slice(off, off + b.chunk);
        const r = await fetch(`${API}/p/${S.pid}/upload/${b.id}/chunk?n=${n}`, { method: 'POST', headers: { Authorization: 'Bearer ' + S.token, 'Content-Type': 'application/octet-stream' }, body: piece });
        if (!r.ok) { const j = await r.json().catch(() => ({})); try { await api(`/p/${S.pid}/upload/${b.id}/abort`, { body: {} }); } catch (x) { /* gone */ } throw new Error(j.error || 'the upload failed'); }
        say.textContent = `Sending ${file.name}… ${Math.min(100, Math.round(((off + piece.size) / file.size) * 100))}%`;
      }
      const done = await api(`/p/${S.pid}/upload/${b.id}/finish`, { body: {} });
      say.textContent = opts.target === 'dir' ? `${file.name} is in the project folder as ${done.path}` : `${file.name} was attached`; setTimeout(() => bar.remove(), 4000); return done;
    } catch (e) { bar.remove(); toast((e.message || 'The upload failed.'), { bad: true }); throw e; }
  }
  function showFiles() {
    const gr = grant(); let tab = gr.files_download ? 'made' : 'folder', path = '';
    const body = h('div', { class: 'filesbody' }), tabs = h('div', { class: 'tabs' });
    const d = dlg('Files', tabs, body, h('div', { class: 'actions' }, h('button', { type: 'button', onclick: () => d.close() }, 'Close'))); d.classList.add('files');
    const draw = async () => {
      fill(tabs, ...[gr.files_download ? ['made', 'Made in chats'] : null, gr.files_browse || gr.files_upload_dir ? ['folder', 'Project folder'] : null].filter(Boolean).map(([k, l]) => h('button', { type: 'button', class: tab === k ? 'on' : '', onclick: () => { tab = k; draw(); } }, l)));
      fill(body, h('p', { class: 'hint' }, 'Loading…'));
      try {
        if (tab === 'made') {
          const j = await api('/p/' + S.pid + '/generated');
          fill(body, 
            ...(j.attachments.length ? [h('h3', {}, 'Attached to chats'), ...j.attachments.map((a) => h('div', { class: 'frow' }, h('span', { class: 'nm' }, a.name), h('span', { class: 'hint' }, `${niceSize(a.size)} · ${a.by || ''} · ${full(a.ts)}`), h('button', { type: 'button', onclick: () => download(`/p/${S.pid}/attachment/${a.id}`, a.name) }, icon('download'), ' Download')))] : []),
            ...(j.files.length ? [h('h3', {}, 'Made by the models'), ...j.files.map((f) => h('div', { class: 'frow' }, h('span', { class: 'nm' }, f.path), h('span', { class: 'hint' }, `${niceSize(f.size)} · ${f.kind === 'created' ? 'new' : 'changed'} · ${f.model || ''} for ${f.by || ''}`), h('button', { type: 'button', onclick: () => download(`/p/${S.pid}/file?path=${encodeURIComponent(f.path)}`, f.path.split('/').pop()) }, icon('download'), ' Download')))] : []),
            ...(!j.files.length && !j.attachments.length ? [h('p', { class: 'hint' }, 'No file has been made or attached in the chats you can see yet.')] : []));
        } else {
          const j = await api('/p/' + S.pid + '/files?path=' + encodeURIComponent(path)), up = path === '' ? '' : path.split('/').slice(0, -1).join('/');
          fill(body, 
            h('p', { class: 'hint' }, 'Project folder' + (path ? ' / ' + path : '')), path ? h('div', { class: 'frow' }, h('button', { type: 'button', onclick: () => { path = up; draw(); } }, 'Up one folder')) : null,
            ...j.entries.map((e) => h('div', { class: 'frow' }, e.type === 'dir' ? h('button', { type: 'button', class: 'link nm', onclick: () => { path = (path ? path + '/' : '') + e.name; draw(); } }, e.name + '/') : h('span', { class: 'nm' }, e.name), h('span', { class: 'hint' }, e.type === 'file' ? niceSize(e.size) : 'folder'),
              e.type === 'file' && gr.files_browse ? h('button', { type: 'button', onclick: () => download(`/p/${S.pid}/file?path=${encodeURIComponent((path ? path + '/' : '') + e.name)}`, e.name) }, icon('download'), ' Download') : e.editable ? h('button', { type: 'button', onclick: () => editFile((path ? path + '/' : '') + e.name) }, 'Edit') : null)),
            !j.entries.length ? h('p', { class: 'hint' }, 'Nothing here that you can see.') : null,
            j.can_upload ? h('p', {}, h('button', { class: 'primary', type: 'button', onclick: () => pickFile((f) => uploadFile(f, { target: 'dir', dir: path }).then(draw, () => {})) }, 'Put a file in this folder')) : null);
        }
      } catch (e) { fill(body, h('p', { class: 'err', role: 'alert' }, e.message), h('button', { type: 'button', onclick: draw }, 'Try again')); }
    };
    function editFile(rel) {
      api('/p/' + S.pid + '/filetext?path=' + encodeURIComponent(rel)).then((t) => {
        const ta = h('textarea', { rows: 16, style: 'width:100%;font-family:var(--mono);font-size:14px', spellcheck: 'false' }); ta.value = t.content;
        const e = dlg(rel, ta, h('div', { class: 'actions' }, h('button', { type: 'button', onclick: () => e.close() }, 'Cancel'), h('button', { class: 'primary', type: 'button', onclick: async () => { try { await api('/p/' + S.pid + '/filetext', { body: { path: rel, content: ta.value, sha: t.sha } }); toast('Saved.'); e.close(); } catch (x) { toast(x.message, { bad: true }); } } }, 'Save')));
      }).catch((x) => toast(x.message, { bad: true }));
    }
    draw();
  }

  // ---------------------------------------------------------------- keys
  document.addEventListener('keydown', (e) => {
    if (!project || !shell) return;
    const typing = /^(INPUT|TEXTAREA|SELECT)$/.test((document.activeElement || {}).tagName || ''), modal = document.querySelector('dialog[open]');
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); if (!modal) showSearch(); }
    else if (e.key === '/' && !typing && !modal) { e.preventDefault(); if (el.ta && !el.field.hidden) el.ta.focus(); }
    else if (e.key === '?' && !typing && !modal) { e.preventDefault(); showShortcuts(); }
    else if (e.key === 'Escape') { closeMenu(); if (!modal) closeDrawers(); }
    else if (e.altKey && (e.key === 'ArrowUp' || e.key === 'ArrowDown') && !modal) { e.preventDefault(); const i = project.chats.findIndex((c) => c.id === chat), n = project.chats.length; if (n) openChat(project.chats[(i + (e.key === 'ArrowDown' ? 1 : n - 1)) % n].id); }
  });
  // a phone's keyboard shrinks what can be seen: the page follows the visible height, so the box you type in is never hidden behind it
  function fit() { const vv = window.visualViewport; document.documentElement.style.setProperty('--vvh', Math.round(vv ? vv.height : innerHeight) + 'px'); if (vv && vv.offsetTop > 0) window.scrollTo(0, 0); if (el.log && shell && atBottomLate) scrollEnd(false); }
  let atBottomLate = false;
  if (window.visualViewport) { visualViewport.addEventListener('resize', () => { atBottomLate = !!(el.log && atBottom()); fit(); }); visualViewport.addEventListener('scroll', fit); }
  window.addEventListener('resize', () => { fit(); if (shell && innerWidth > 1100) { el.scrim.hidden = true; } });
  fit(); applyTheme();

  // ---------------------------------------------------------------- signing in with an Orbit account (only behind the Orbit service)
  const b64u = (buf) => btoa(String.fromCharCode(...new Uint8Array(buf))).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  const unb64u = (t) => Uint8Array.from(atob(t.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - (t.length % 4)) % 4)), (c) => c.charCodeAt(0));
  const rand = (n) => b64u(crypto.getRandomValues(new Uint8Array(n)));
  const SKEY = 'orbit-signin:' + RELAY_PID;
  async function svc(path, body, root) {
    let r; try { r = await fetch((root ? '' : BASE) + path, { method: body ? 'POST' : 'GET', headers: body ? { 'Content-Type': 'application/json' } : {}, body: body ? JSON.stringify(body) : undefined }); } catch (e) { const x = new Error('Could not reach the Orbit service.'); x.status = 0; throw x; }
    const j = await r.json().catch(() => ({}));
    if (!r.ok) { const e = new Error(j.error || ('error ' + r.status)); e.status = r.status; e.code = j.code; throw e; }
    return j;
  }
  const SIGNIN_ERR = { access_denied: 'Sign-in was cancelled.', consent_required: 'No Orbit account for that login yet.', turnstile_required: 'No Orbit account for that login yet.', rate_limited: 'Wait a few minutes, then try again.' };
  async function signInBox(o = {}) {
    const err = h('div', { class: 'err', role: 'alert' }, o.msg || ''), list = h('div', { class: 'methods' }, h('p', { class: 'hint' }, 'Loading…'));
    fill($app, h('div', { class: 'boot' }, h('div', { class: 'card' }, h('h1', {}, 'Sign in with Orbit'), h('p', {}, o.invite ? 'This invitation is for a person with an Orbit account.' : 'Use your Orbit account to open this project.'), list, err)));
    let m; try { m = await svc('/auth/methods', null, true); } catch (e) { fill(list, h('p', { class: 'err' }, 'Could not reach the Orbit service.'), h('button', { type: 'button', onclick: () => signInBox(o) }, 'Try again')); return; }
    const btns = (m.methods || []).filter((x) => x.kind !== 'passkey' || window.PublicKeyCredential).map((x) => h('button', { class: x.kind === 'hosted' ? '' : 'primary', type: 'button', onclick: () => (x.kind === 'passkey' ? passkeyIn(o, err) : redirectIn(x.id, o, err)) }, x.label));
    fill(list, ...(btns.length ? btns : [h('p', { class: 'err' }, 'No way to sign in is set up on the service yet.')]));
  }
  async function redirectIn(id, o, err) {
    try {
      const verifier = rand(32), state = rand(16), challenge = b64u(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier)));
      sessionStorage.setItem(SKEY, JSON.stringify({ pid: RELAY_PID, verifier, state, started: Date.now(), invite: o.invite || null, name: o.name || '' }));
      location.assign(`${BASE}/account/start/${encodeURIComponent(id)}?code_challenge=${challenge}&state=${state}`);
    } catch (e) { err.textContent = 'This browser cannot start a sign-in here (it needs a secure page).'; }
  }
  async function passkeyIn(o, err) {
    err.textContent = '';
    try {
      const pk = (await svc('/account/passkey/options', {})).publicKey; pk.challenge = unb64u(pk.challenge);
      (pk.allowCredentials || []).forEach((c) => { c.id = unb64u(c.id); });
      const c = await navigator.credentials.get({ publicKey: pk }), r = c.response;
      const res = await svc('/account/passkey/verify', { credential: { id: c.id, rawId: b64u(c.rawId), type: c.type, response: { clientDataJSON: b64u(r.clientDataJSON), authenticatorData: b64u(r.authenticatorData), signature: b64u(r.signature), userHandle: r.userHandle ? b64u(r.userHandle) : undefined } } });
      return enterWith(res, o.invite, o.name);
    } catch (e) {
      if (e.name === 'NotAllowedError') return;
      err.textContent = e.status === 401 && e.code === 'unknown_credential' ? 'That passkey is not an Orbit account’s. Create an account first.' : e.status === 429 ? 'Wait a minute, then try again.' : 'Sign-in did not work. Try again.';
    }
  }
  async function handleSignin() {
    const q = new URLSearchParams(location.search), code = q.get('code'), error = q.get('error'), state = q.get('state');
    history.replaceState(null, '', BASE + '/');                                          // the code must not stay in the address bar or the history
    let rec = null; try { rec = JSON.parse(sessionStorage.getItem(SKEY) || 'null'); sessionStorage.removeItem(SKEY); } catch (e) { /* no record */ }
    if (!rec || rec.pid !== RELAY_PID || Date.now() - rec.started > 15 * 60000 || rec.state !== state) return signInBox({});     // not started here (or too old): a code is useless without its verifier
    if (error) return signInBox({ invite: rec.invite, name: rec.name, msg: SIGNIN_ERR[error] || 'Sign-in did not work. Try again.' });
    bootCard('Signing in…', h('div', { class: 'progress' }, h('i')));
    try { return enterWith(await svc('/account/proof', { code, code_verifier: rec.verifier }), rec.invite, rec.name); }
    catch (e) { return signInBox({ invite: rec.invite, name: rec.name, msg: e.status === 429 ? 'Wait a minute, then try again.' : 'Sign-in did not work. Try again.' }); }
  }
  // the proof goes to the host through the relay: with an invitation it joins, without one it comes back as a member (or as the account the host added)
  async function enterWith(res, invite, name) {
    const proof = res.token, acct = res.account || {}; let j;
    try {
      if (invite) {
        try { j = await request('/join', { body: { p: invite.p, i: invite.i, s: invite.s, name: name || acct.name || 'Member', account_token: proof } }); }
        catch (e) { if (e.status === 401 && /invite/i.test(e.message)) j = await request('/p/' + RELAY_PID + '/signin', { body: { account_token: proof, name: name || undefined } }); else throw e; }
      } else j = await request('/p/' + RELAY_PID + '/signin', { body: { account_token: proof, name: name || undefined } });
    } catch (e) { return signInProblem(e, acct, invite, name); }
    S = { pid: j.project || RELAY_PID, token: j.token, name: j.member.name }; save(S); history.replaceState(null, '', BASE + '/'); start();
  }
  function signInProblem(e, acct, invite, name) {
    if (e.status === 403 && e.code === 'not_a_member') {
      const id = acct.id || '';
      return fill($app, h('div', { class: 'boot' }, h('div', { class: 'card' }, h('h1', {}, 'Not added yet'), h('p', {}, `You are signed in as ${acct.name || 'an Orbit account'}, but you have not been added to this project. Send the host this account id and try again:`),
        h('p', {}, h('code', { style: 'word-break:break-all' }, id)), h('div', { class: 'actions' }, h('button', { class: 'primary', type: 'button', onclick: () => copyText(id, 'Account id copied.') }, 'Copy the id'), h('button', { type: 'button', onclick: () => signInBox({ invite, name }) }, 'Try again')))));
    }
    const msg = e.status === 403 && /different Orbit account/i.test(e.message) ? 'This invitation was made for a different Orbit account. Sign in with the right one.'
      : e.status === 401 && /invite/i.test(e.message) ? 'This invitation no longer works. Ask the host for a new one.'
      : e.status === 503 || e.code === 'host_offline' ? 'The host is offline. Try again later.' : e.status === 429 ? 'Wait a minute, then try again.' : e.status === 401 ? 'Sign in again.' : e.message;
    signInBox({ invite, name, msg });
  }

  // ---------------------------------------------------------------- start
  function boot() {
    const q = new URLSearchParams(location.search), hash = new URLSearchParams(location.hash.slice(1));
    if (RELAY_PID && location.pathname === BASE + '/signin') return handleSignin();
    if (location.pathname === BASE + '/join' && q.get('p') && q.get('i') && q.get('s')) return showJoin(q.get('p'), q.get('i'), q.get('s'));
    if (hash.get('t') && hash.get('p')) { S = { pid: hash.get('p'), token: hash.get('t'), name: hash.get('n') || 'Host' }; save(S); if (hash.get('c')) { chat = hash.get('c'); hashChat = chat; } history.replaceState(null, '', BASE + '/'); return start(); }
    S = load();
    if (S && S.pid && S.token) return start();
    if (RELAY_PID) return signInBox({});
    bootCard('Orbit shared projects', h('p', {}, 'Open an invitation link to join a project.'), h('p', { class: 'hint' }, 'The host sends you a link that starts with this address. Open it in this browser.'));
  }
  boot();
})();
