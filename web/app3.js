// Project settings for a shared project, in one place: opened from the gear above the project (or its right-click menu).
// Everything goes through /api/collabhost (the host's own window), so the owner's login never reaches the page the members use.
const PS_ROLES = {admin: 'Admin: can manage people and settings', editor: 'Editor: works with the models and the files', commenter: 'Commenter: can write, models only read', viewer: 'Viewer: reads only', guest: 'Guest: very limited'};
const PS_FILES = [['files_download', 'download files'], ['files_browse', 'browse the project folder'], ['files_edit', 'edit files'], ['files_upload_chat', 'attach files to chats'], ['files_upload_dir', 'upload into the folder']];
const PS_MODES = {free: 'First come, first served', round_robin: 'Take turns between people', approve_each: 'I approve every question before a model runs'};
const PS_TWO = [['delete', 'Deleting files'], ['git_push', 'Pushing to git'], ['install', 'Installing software'], ['network', 'Using the network'], ['run_code', 'Running programs and scripts']];

async function openProjectSettings(pid, tab) {
  const st = await shCall({op: 'status'});
  if (!st || st.error) return toast((st && st.error) || 'Shared projects are off');
  const proj = () => (st.projects || []).find(x => x.id === pid);
  if (!proj()) return toast('That project is not here any more');
  const host = $('#modalhost');
  const TABS = [['overview', 'Project'], ['people', 'People and invitations'], ['access', 'Sharing and access'], ['models', 'Models'], ['safety', 'Rules and safety'], ['activity', 'Activity and backup']];
  host.innerHTML = `<div class=modal><div class="sheet settings" style="height:min(84vh,780px)"><header><b id=ps_title></b><button class=ghost style="margin-left:auto" id=ps_x>Close</button></header>
   <div class=setgrid><nav class="tabs vnav" id=ps_nav></nav><div class=body id=ps_body></div></div></div></div>`;
  $('#ps_title').textContent = proj().name + ' · settings';
  $('#ps_x').onclick = closeModal;
  host.querySelector('.modal').onclick = e => { if (e.target.classList.contains('modal')) closeModal(); };
  const body = $('#ps_body'), nav = $('#ps_nav');
  const call = async d => { const r = await shCall(Object.assign({project: pid}, d)); if (!r || r.error) { toast((r && r.error) || 'That did not work'); return null; } return r; };
  const copy = async (t, msg) => { try { await navigator.clipboard.writeText(t); toast(msg || 'copied'); } catch (e) { prompt('Copy this:', t); } };
  const ago = t => { const s = Math.max(0, Date.now() / 1000 - t); return s < 90 ? 'just now' : s < 5400 ? Math.round(s / 60) + ' min ago' : s < 172800 ? Math.round(s / 3600) + ' h ago' : Math.round(s / 86400) + ' days ago'; };
  const refresh = async () => { const s = await shCall({op: 'status'}); if (s && !s.error) Object.assign(st, s); try { loadShared(); } catch (e) { /* the sidebar catches up later */ } };
  nav.innerHTML = TABS.map(([k, t]) => `<button data-t=${k}>${esc(t)}</button>`).join('');

  const R = {};
  R.overview = async () => {
    const p = proj(), g = await call({op: 'guard'}); if (!g) return;
    body.innerHTML = `<div class=sec>This project</div><div class=grid>
     <label>Name</label><div style="display:flex;gap:6px"><input id=ps_name value="${esc(p.name)}" maxlength=80 style="flex:1"><button class=ghost id=ps_rename>Rename</button></div>
     <label>Working folder</label><div style="word-break:break-all">${esc(p.working_dir)}</div>
     <label>People</label><div>${p.members} ${p.members === 1 ? 'person' : 'people'} <a href=# id=ps_goto_people>manage</a></div>
     <label>How questions to a model are taken</label><select id=ps_mode>${Object.entries(PS_MODES).map(([k, t]) => `<option value=${k}${g.turn_mode === k ? ' selected' : ''}>${esc(t)}</option>`).join('')}</select>
     <div class=hint2>With one model on one Mac, questions are answered one at a time anyway; this decides whose comes next.</div>
     <label>Saving copies</label><label><input type=checkbox id=ps_export${p.allow_export !== false ? ' checked' : ''}> Members may save copies of chats <span class=note>(it cannot stop a screenshot)</span></label></div>
    <div class=sec>Freeze</div><div class=note style="margin-left:0">${p.frozen ? 'Everything is frozen: nobody can write or run anything.' : 'Freezing stops every model and every action at once, for everyone. Reading still works. You can lift it again.'}</div>
    <div style="margin:8px 0"><button class="${p.frozen ? 'primary' : 'ghost'}" id=ps_freeze style="${p.frozen ? '' : 'color:var(--bad)'}">${p.frozen ? 'Lift the freeze' : 'Freeze everything'}</button></div>`;
    $('#ps_goto_people').onclick = e => { e.preventDefault(); show('people'); };
    $('#ps_rename').onclick = async () => { const v = $('#ps_name').value.trim(); if (!v || v === p.name) return; if (await call({op: 'project_settings', name: v})) { await refresh(); $('#ps_title').textContent = v + ' · settings'; toast('renamed'); } };
    $('#ps_mode').onchange = async e => { if (await call({op: 'set_turn_mode', mode: e.target.value})) toast('saved'); };
    $('#ps_export').onchange = async e => { if (!await call({op: 'project_settings', allow_export: e.target.checked})) e.target.checked = !e.target.checked; else toast(e.target.checked ? 'members may save copies' : 'members cannot save copies'); };
    $('#ps_freeze').onclick = async () => { if (!p.frozen && !confirm('Freeze everything in "' + p.name + '"?')) return; if (await call({op: p.frozen ? 'resume' : 'panic'})) { await refresh(); show('overview'); } };
  };

  R.people = async () => {
    const r = await call({op: 'people'}); if (!r) return;
    const roleSel = (m) => `<select data-role="${esc(m.id)}">${r.roles.map(x => `<option value=${x}${m.role === x ? ' selected' : ''}>${esc(x)}</option>`).join('')}</select>`;
    const mem = r.members.map(m => `<div class=card style="margin:8px 0;padding:10px" data-m="${esc(m.id)}"><div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap"><b>${esc(m.name)}</b>
      ${m.owner ? '<span class=note style="margin-left:0">host</span>' : `${roleSel(m)}`}${m.account ? '<span class=note style="margin-left:0">Orbit account</span>' : ''}${m.state === 'muted' ? '<span class=note style="margin-left:0">muted</span>' : ''}
      <span style="flex:1"></span>${m.owner ? '' : `<button class=ghost data-act="${m.state === 'muted' ? 'unmute' : 'mute'}">${m.state === 'muted' ? 'Unmute' : 'Mute'}</button><button class=ghost data-act=remove style="color:var(--bad)">Remove</button>`}</div>
      <div class=note style="margin:4px 0 0">${esc(m.summary || '')}</div>
      ${m.owner ? '' : `<details style="margin-top:4px"><summary class=note style="margin-left:0;cursor:pointer">Files and limits</summary>
       <div style="display:flex;gap:12px;flex-wrap:wrap;margin:6px 0">${PS_FILES.map(([f, t]) => `<label><input type=checkbox data-file=${f}${m.files[f] ? ' checked' : ''}> ${t}</label>`).join('')}</div>
       <div class=note style="margin-left:0">Questions to models: <input type=number min=0 data-bud=turns_per_hour value="${m.budget.turns_per_hour || ''}" placeholder="∞" style="width:64px"> an hour, <input type=number min=0 data-bud=turns_per_day value="${m.budget.turns_per_day || ''}" placeholder="∞" style="width:64px"> a day <span class=note>(empty = no limit)</span></div></details>`}</div>`).join('');
    const inv = (r.invites || []).map(i => `<div class=row style="display:flex;gap:8px;align-items:center;margin:3px 0"><span>${esc(i.role || 'invitation')}${i.account_required ? ' · Orbit account only' : ''}</span><span class=note>${i.uses_left < 0 || i.uses_left == null ? 'any number of uses' : i.uses_left + ' use' + (i.uses_left === 1 ? '' : 's') + ' left'}${i.expires_at ? ' · expires ' + new Date(i.expires_at * 1000).toLocaleString() : ''}</span><button class=ghost data-rev="${esc(i.id)}">Cancel it</button></div>`).join('');
    const web = !!(await shCall({op: 'relay_status'}) || {}).projects?.[pid];
    body.innerHTML = `<div class=sec>Invite someone</div><div class=grid>
      <label>They can</label><select id=iv_role>${r.roles.map(x => `<option value=${x}${x === 'editor' ? ' selected' : ''}>${esc(PS_ROLES[x] || x)}</option>`).join('')}</select>
      <label>The link works for</label><select id=iv_exp><option value=3600>1 hour</option><option value=86400 selected>1 day</option><option value=604800>7 days</option><option value=2592000>30 days</option></select>
      <label>Number of people</label><select id=iv_uses><option value=1 selected>one person</option><option value=5>up to 5 people</option><option value=25>up to 25 people</option><option value=0>anyone who has the link</option></select>
      <label>Sign-in</label><label><input type=checkbox id=iv_acct> they must sign in with an Orbit account</label>
      <label>Add by account id</label><div><input id=iv_for placeholder="acc_… (optional: only that Orbit account can use it)" style="width:100%"><div class=hint2 style="margin:2px 0 0">They find it on the sign-in screen when they open the web link and are not added yet. No link is needed: they open the project's address, sign in, and are in.</div></div>
      <label>Link goes through</label><div>${web ? 'the Orbit web link (works from anywhere)' : 'this Mac directly (only people who can reach it)'}${web ? '' : ` <a href=# id=iv_pub>switch on the web link</a>`}</div>
      <label></label><div><button class=primary id=iv_go>Make the link</button></div></div><div id=iv_out></div>
     <div class=sec>People (${r.members.length})</div>${mem}
     <div class=sec>Open invitations</div>${inv || '<div class=note style="margin-left:0">None.</div>'}`;
    $('#iv_pub') && ($('#iv_pub').onclick = async e => { e.preventDefault(); if (await call({op: 'relay_publish'})) { toast('the web link is on'); show('people'); } });
    $('#iv_go').onclick = async () => {
      const o = await call({op: 'invite', role: $('#iv_role').value, expires_in: +$('#iv_exp').value, uses: +$('#iv_uses').value, account_required: $('#iv_acct').checked || !!$('#iv_for').value.trim(), for_account: $('#iv_for').value.trim() || undefined}); if (!o) return;
      const addr = o.for_account ? (o.page_link || o.link) : o.link;
      $('#iv_out').innerHTML = `<div class=card style="padding:10px;margin:8px 0"><div class=note style="margin:0 0 4px">${o.for_account ? 'Only that Orbit account can use this. Send them the project address:' : 'Send this to the person.'} ${/127\.0\.0\.1|localhost/.test(o.link) ? 'It points at this Mac only: switch on the web link in "Sharing and access" first.' : ''}</div><input readonly value="${esc(addr)}" style="width:100%" onclick=this.select()><div style="margin-top:6px"><button class=primary id=iv_cp>Copy the link</button></div></div>`;
      $('#iv_cp').onclick = () => copy(addr, 'link copied');
    };
    body.querySelectorAll('[data-m]').forEach(card => {
      const mid = card.dataset.m;
      card.querySelectorAll('[data-act]').forEach(b => b.onclick = async () => { if (b.dataset.act === 'remove' && !confirm('Remove this person from the project?')) return; if (await call({op: 'member_action', member: mid, action: b.dataset.act})) show('people'); });
      const rs = card.querySelector('[data-role]'); if (rs) rs.onchange = async () => { if (await call({op: 'member_action', member: mid, action: 'role', value: rs.value})) { toast('saved'); show('people'); } };
      card.querySelectorAll('[data-file]').forEach(c => c.onchange = async () => { if (!await call({op: 'member_action', member: mid, action: 'files', value: {[c.dataset.file]: c.checked}})) c.checked = !c.checked; else toast('saved'); });
      card.querySelectorAll('[data-bud]').forEach(i => i.onchange = async () => { const v = {}; card.querySelectorAll('[data-bud]').forEach(x => { v[x.dataset.bud] = x.value === '' || +x.value <= 0 ? '' : Math.round(+x.value); }); if (await call({op: 'member_action', member: mid, action: 'budget', value: v})) toast('saved'); });
    });
    body.querySelectorAll('[data-rev]').forEach(b => b.onclick = async () => { if (await call({op: 'member_action', member: b.dataset.rev, action: 'revoke_invite'})) show('people'); });
  };

  R.access = async () => {
    const rs = await shCall({op: 'relay_status'}), mine = rs && rs.projects && rs.projects[pid], chk = await call({op: 'check'});
    const mode = st.mode;
    body.innerHTML = `<div class=sec>The web link <span class=note>recommended</span></div>
     <div class=note style="margin-left:0">People open a link on ${esc((rs && rs.service) || 'the Orbit service').replace(/^https?:\/\//, '')} and work in the project from anywhere: nothing on this Mac is exposed, no VPN or address to set up. Your Mac connects out to the service while Orbit is running.</div>
     <div style="margin:8px 0">${mine ? `<span class=note style="margin-left:0">${esc(mine.state === 'connected' ? 'on and connected' : mine.state || 'on')}${mine.error ? ' · ' + esc(mine.error) : ''}</span><div style="margin-top:6px"><input readonly value="${esc(mine.link || '')}" style="width:100%" onclick=this.select()></div>
       <div style="margin-top:6px;display:flex;gap:6px"><button class=ghost id=ac_cp>Copy the link</button><button class=ghost id=ac_off style="color:var(--bad)">Switch the web link off</button></div>` : `<button class=primary id=ac_on>Switch the web link on</button> <span class=note>needs your Orbit account (Settings, General)</span>`}</div>
     <div class=sec>Direct address of this Mac</div><div class=grid>
      <label>Who can reach it</label><select id=ac_mode><option value=local${mode === 'local' ? ' selected' : ''}>Only this Mac (use the web link for others)</option><option value=tailscale${mode === 'tailscale' ? ' selected' : ''}>People on my Tailscale network</option><option value=lan${mode === 'lan' ? ' selected' : ''}>People on this local network</option></select>
      <div class=hint2>Optional. People using the web link never need this.</div>
      <label>Door</label><div>${st.running ? 'open at ' + esc(st.public_url || '') : 'closed: shared projects are off'}</div></div>
     <div class=sec>Checkup</div>${(chk && chk.checks || []).map(c => `<div style="margin:3px 0"><span style="color:${c.ok ? '#2e9e5b' : 'var(--bad)'}">${c.ok ? '✓' : '✕'}</span> <b>${esc(c.name)}</b> <span class=note>${esc(c.detail)}</span></div>`).join('')}`;
    $('#ac_on') && ($('#ac_on').onclick = async () => { if (await call({op: 'relay_publish'})) { toast('the web link is on'); show('access'); } });
    $('#ac_off') && ($('#ac_off').onclick = async () => { if (!confirm('People who use the web link will lose access until you switch it on again. Their invitations keep working there once it is back.')) return; if (await call({op: 'relay_unpublish'})) show('access'); });
    $('#ac_cp') && ($('#ac_cp').onclick = () => copy(mine.link, 'link copied'));
    $('#ac_mode').onchange = async e => { const r = await shCall({op: 'configure', mode: e.target.value}); if (r && !r.error) { Object.assign(st, r); toast('saved'); show('access'); } else toast((r && r.error) || 'could not change that'); };
  };

  R.models = async () => {
    let models = []; try { const m = await (await fetch('/api/models')).json(); models = (m.models || m || []).filter(x => x && x.id); } catch (e) { /* the list stays empty */ }
    let mine = JSON.parse(JSON.stringify(st.models || []));
    const draw = () => {
      body.innerHTML = `<div class=sec>Models people can ask</div><div class=note style="margin-left:0">These apply to every shared project on this Mac. People ask a model by typing @ in the chat. A model works with only the rights of the person who asked.</div>
       ${mine.map((m, i) => `<div class=card style="margin:8px 0;padding:10px"><div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap"><b>@${esc(m.handle)}</b><span>${esc((models.find(x => x.id === m.id) || {}).label || m.label || m.id)}</span><span style="flex:1"></span><button class=ghost data-del=${i} style="color:var(--bad)">Remove</button></div>
        <div class=grid style="margin-top:8px"><label>Name people see</label><input data-f=label data-i=${i} value="${esc(m.label)}" maxlength=60>
        <label>Who pays</label><input data-f=payer data-i=${i} value="${esc(m.payer)}" maxlength=80>
        <label>Show what is left</label><label><input type=checkbox data-f=share_usage data-i=${i}${m.share_usage ? ' checked' : ''}> people see how much of this model's allowance is left, and when it resets</label></div></div>`).join('') || '<div class=note style="margin-left:0">No models yet: without one, nobody can ask a model anything.</div>'}
       <div class=sec>Add a model</div><input id=pm_q placeholder="Search your ready models" style="width:100%"><div id=pm_list style="max-height:220px;overflow:auto;margin-top:6px"></div>
       <div style="margin-top:10px"><button class=primary id=pm_save>Save</button></div>`;
      const have = new Set(mine.map(m => m.id)), list = () => {
        const q = $('#pm_q').value.toLowerCase();
        $('#pm_list').innerHTML = models.filter(m => !have.has(m.id) && m.ready !== false && (!q || (m.label || m.id).toLowerCase().includes(q) || m.id.toLowerCase().includes(q))).slice(0, 40).map(m => `<div style="display:flex;gap:8px;align-items:center;margin:2px 0"><span style="flex:1">${esc(m.label || m.id)} <span class=note>${esc(m.provider_label || '')}</span></span><button class=ghost data-add="${esc(m.id)}">Add</button></div>`).join('') || '<div class=note style="margin-left:0">Nothing more to add.</div>';
        $('#pm_list').querySelectorAll('[data-add]').forEach(b => b.onclick = () => {
          const m = models.find(x => x.id === b.dataset.add); let base = (m.label || m.id).toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim().split(' ')[0] || 'model', hd = base, n = 2;
          while (mine.some(x => x.handle.toLowerCase() === hd)) hd = base + n++;
          mine.push({handle: hd.slice(0, 29), id: m.id, label: m.label || m.id, payer: 'the host', share_usage: false}); sync(); draw();
        });
      };
      const sync = () => body.querySelectorAll('[data-f]').forEach(i => { const m = mine[+i.dataset.i]; if (m) m[i.dataset.f] = i.type === 'checkbox' ? i.checked : i.value.trim(); });
      body.querySelectorAll('[data-del]').forEach(b => b.onclick = () => { sync(); mine.splice(+b.dataset.del, 1); draw(); });
      $('#pm_q').oninput = list; list();
      $('#pm_save').onclick = async () => { sync(); const r = await shCall({op: 'configure', models: mine}); if (r && !r.error) { Object.assign(st, r); toast('saved'); } else toast((r && r.error) || 'could not save'); };
    };
    draw();
  };

  R.safety = async () => {
    const r = await call({op: 'guard'}); if (!r) return; const g = r.guard;
    body.innerHTML = `<div class=sec>Needs two approvers</div><div class=note style="margin-left:0">For these kinds of action one approver is not enough: two different people must say yes, and anyone's no stops it.</div>
     <div id=tp style="margin:6px 0">${PS_TWO.map(([k, t]) => `<label style="display:block"><input type=checkbox data-tp=${k}${(r.two_person || []).includes(k) ? ' checked' : ''}> ${t}</label>`).join('')}</div><button class=primary id=tp_save>Save</button>
     <div class=sec>Guard</div><div class=note style="margin-left:0">A second model reads every risky action before it runs, with the rules you write below, and can refuse it or send it to a person. It can never allow what a person's permissions forbid.</div>
     <div class=grid style="margin-top:8px"><label>Guard</label><label><input type=checkbox id=gd_on${g.enabled ? ' checked' : ''}> review actions before they run</label>
      <label>Model</label><select id=gd_model>${(r.models.length ? r.models : [{id: g.model_id, label: g.model_id || '(no model available)'}]).map(m => `<option value="${esc(m.id)}"${m.id === g.model_id ? ' selected' : ''}>${esc(m.label)}</option>`).join('')}</select>
      <div class=hint2>Pick a model that is not the one doing the work.</div>
      <label>Reviews</label><select id=gd_scope><option value=risky${g.scope === 'risky' ? ' selected' : ''}>risky actions only</option><option value=all${g.scope === 'all' ? ' selected' : ''}>every action</option></select>
      <label>Your rules</label><textarea id=gd_text rows=7 maxlength=4000 style="width:100%">${esc(g.instructions)}</textarea>
      <label></label><div><button class=primary id=gd_save>Save the guard</button></div></div>`;
    $('#tp_save').onclick = async () => { const d = await call({op: 'set_two_person', flags: [...body.querySelectorAll('#tp input:checked')].map(x => x.dataset.tp)}); if (d) toast('saved'); };
    $('#gd_save').onclick = async () => { const d = await call({op: 'set_guard', guard: {enabled: $('#gd_on').checked, model_id: $('#gd_model').value, scope: $('#gd_scope').value, instructions: $('#gd_text').value}}); if (d) toast('saved'); };
  };

  R.activity = async () => {
    const [ch, chats] = await Promise.all([call({op: 'recent_changes'}), call({op: 'project_chats'})]); if (!ch || !chats) return;
    body.innerHTML = `<div class=sec>Latest changes to files</div>${(ch.changes || []).map(c => `<div class=card style="margin:6px 0;padding:8px"><b>${esc(c.model || 'a model')}</b> for ${esc(c.asked_by_name || 'someone')} <span class=note>${c.ts ? ago(c.ts) : ''}</span>
      <div class=note style="margin:2px 0 0">${[['created', 'created'], ['modified', 'changed'], ['deleted', 'deleted']].map(([k, t]) => (c[k] || []).length ? t + ' ' + c[k].slice(0, 4).map(esc).join(', ') + (c[k].length > 4 ? '…' : '') : '').filter(Boolean).join(' · ')}</div>
      ${c.can_undo ? `<button class=ghost data-undo="${esc(c.turn)}" style="margin-top:4px">Undo these changes</button>` : ''}</div>`).join('') || '<div class=note style="margin-left:0">No file changes yet.</div>'}
     <div class=sec>Chats in this project</div>${(chats.chats || []).map(c => `<div style="display:flex;gap:8px;align-items:center;margin:3px 0">#${esc(c.name)}${c.imported ? ` <span class=note style="margin-left:0">shared from this Mac (${c.imported} messages)</span>` : ''}<span style="flex:1"></span>${c.id === 'main' ? '' : `<button class=ghost data-rm="${esc(c.id)}" style="color:var(--bad)">Take out of the project</button>`}</div>`).join('')}
     <div class=sec>Backup</div><div class=note style="margin-left:0">A backup holds the project's record and its people, but nobody's login: you restore it in Settings, Shared projects.</div>
     <div style="margin:8px 0"><button class=ghost id=bk_go>Back up this project</button> <span id=bk_out class=note style="margin-left:6px"></span></div>`;
    body.querySelectorAll('[data-undo]').forEach(b => b.onclick = async () => { if (!confirm('Put the files back as they were before that answer?')) return; const r = await call({op: 'undo_turn', turn: b.dataset.undo}); if (r) { toast('undone'); show('activity'); } });
    body.querySelectorAll('[data-rm]').forEach(b => b.onclick = async () => { if (!confirm('Take this chat out of the project? It disappears for everyone, history included.')) return; if (await call({op: 'remove_chat', chat: b.dataset.rm})) { await refresh(); show('activity'); } });
    $('#bk_go').onclick = async () => { const r = await call({op: 'backup_project'}); if (r) $('#bk_out').textContent = 'saved: ' + (r.path || r.file || 'done'); };
  };

  let cur = '';
  async function show(t) {
    cur = t; nav.querySelectorAll('button').forEach(b => b.classList.toggle('on', b.dataset.t === t));
    body.innerHTML = '<div class=note style="margin-left:0">Loading…</div>';
    try { await R[t](); } catch (e) { if (cur === t) body.innerHTML = '<div class=note style="margin-left:0">Could not load this page: ' + esc(e.message || String(e)) + '</div>'; }
    body.scrollTop = 0;
  }
  nav.querySelectorAll('button').forEach(b => b.onclick = () => show(b.dataset.t));
  show(R[tab] ? tab : 'overview');
}

// "New shared project": the three things it needs, then it is open and (if the web link is the way people reach this Mac) switched on at the service
async function newSharedProject() {
  const st = await shCall({op: 'status'});
  if (!st || st.error) return toast((st && st.error) || 'Could not reach Orbit');
  if (!st.enabled) {
    if (!confirm('Shared projects are off. Switch them on? People can only get in with an invitation from you, and you can freeze everything at any time.')) return;
    const r = await shCall({op: 'configure', enabled: true}); if (!r || r.error) return toast((r && r.error) || 'could not switch it on');
  }
  const host = $('#modalhost');
  host.innerHTML = `<div class=modal><div class="sheet auto" style="max-width:520px"><header><b>New shared project</b><button class=ghost style="margin-left:auto" id=np_x>Close</button></header>
   <div class=body style="padding:16px 20px"><div class=note style="margin:0 0 10px">A shared project is a folder on this Mac that people you invite work in with you, together with models. You can change everything later.</div>
   <div class=grid><label>Name</label><input id=np_name placeholder="e.g. Methylation notebook" maxlength=80>
   <label>Working folder</label><input id=np_dir placeholder="/absolute/path/to/the/folder the models work in">
   <label>Your name</label><input id=np_me maxlength=40>
   <label></label><div><button class=primary id=np_go>Create</button> <span class=note id=np_msg style="margin-left:6px"></span></div></div></div></div></div>`;
  $('#np_me').value = PREF.get('shared_name', 'Me');
  try { const w = await (await fetch('/api/state')).json(); if (w && w.workspace) $('#np_dir').value = w.workspace; } catch (e) { /* the person types it */ }
  host.querySelector('.modal').onclick = e => { if (e.target.classList.contains('modal')) closeModal(); };
  $('#np_x').onclick = closeModal; $('#np_name').focus();
  $('#np_go').onclick = async () => {
    const msg = $('#np_msg'); msg.textContent = 'Creating…';
    const r = await shCall({op: 'create', name: $('#np_name').value, owner_name: $('#np_me').value, working_dir: $('#np_dir').value.trim()});
    if (!r || r.error) { msg.textContent = (r && r.error) || 'That did not work'; return; }
    PREF.set('shared_name', $('#np_me').value.trim() || 'Me');
    const rs = await shCall({op: 'relay_status'});
    if (st.mode === 'local' && rs && rs.projects && Object.keys(rs.projects).length) await shCall({op: 'relay_publish', project: r.project.id});       // the web link is how people reach this Mac: this project too
    closeModal(); await loadShared(); openShared(r.project.id); toast('project created: invite people with the Invite button');
  };
}
