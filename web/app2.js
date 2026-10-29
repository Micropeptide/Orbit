function settingsIndex(){
 if(settingsIndex.cache)return settingsIndex.cache;
 const src=String(openSettings), names={};
 const tabs_=[...src.matchAll(/data-t=(\w+)>([^<]+)</g)];tabs_.forEach(m=>names[m[1]]=m[2].replace('&amp;','&').replace(' →',''));
 const out=[],seen=new Set();
 const parts=src.split(/if\(name==='(\w+)'\)/);
 for(let i=1;i<parts.length;i+=2){const tab=parts[i],body=parts[i+1];if(!names[tab])continue;
  out.push({tab,text:names[tab],label:'tab'});
  for(const m of body.matchAll(/class=sec[^>]*>([^<]{3,80})|<label[^>]*>([^<]{3,60})<\/label>/g)){
   const text=(m[1]||m[2]).trim().replace(/&amp;/g,'&');const k=tab+'|'+text;
   if(seen.has(k)||/\$\{/.test(text))continue;seen.add(k);out.push({tab,text,label:names[tab]})}}
 return settingsIndex.cache=out}
async function openSettings(tab){
 MEM_ORBIT=false;
 tab=tab||(MODELS.harness_mode?'claude':(MODELS.codex_mode?'codex':'general'));   // Claude Code mode: its settings first
 const info=await (await fetch('/api/info')).json();INFO=info;
 const st=info.settings;
 const mem=await (await fetch('/api/memory')).json();
 const ins=(await (await fetch('/api/instructions')).json()).text||'';
 const mcp=await (await fetch('/api/mcp')).json();
 PROMPTS=await (await fetch('/api/prompts')).json();
 const host=$('#modalhost');
 host.innerHTML=`<div class=modal><div class="sheet settings">
  <header><b>Settings</b><span class=sfindwrap><input type=search id=sfind placeholder="Search settings" autocomplete=off><div class=sfindres id=sfindres></div></span>
  <button class=ghost style="margin-left:auto" id=closex>Close</button></header>
  <div class=setgrid><nav class="tabs vnav">
   <span class=tgrp>Orbit</span>
   <button data-t=general>General</button><button data-t=models>Models &amp; keys</button>
   <button data-t=tools>Tools</button><button data-t=memory>Memory</button>
   <button data-t=mcp>MCP</button><button data-t=library>Library →</button>
   <span class=tgrp>How chats run</span>
   <button data-t=claude>Claude Code</button><button data-t=codex>Codex</button>
   <button data-t=model>Local server</button><button data-t=servers>Cluster models</button>
   <span class=tgrp>This Mac</span>
   <button data-t=phone>Phone</button><button data-t=collab>Shared projects</button><button data-t=helpers>Helpers</button><button data-t=backup>Backup</button>
   <button data-t=status>Status</button>
  </nav><div class=body id=sbody></div></div>
  <footer><button class=primary id=savebtn>Save</button>
   <button class=ghost id=restartbtn>Save &amp; restart server</button>
   <span class=note id=snote></span></footer></div></div>`;
 $('#closex').onclick=closeModal;
 // Search: every section and field name, read from the tabs' own drawing code, so a
 // new setting is findable the day it is added. A hit opens its tab and shows it.
 {const inp=$('#sfind'),res=$('#sfindres'),idx=settingsIndex();let sel=0,hits=[];
  const pick=h=>{res.innerHTML='';inp.value='';tabs(h.tab).then(()=>{
   const want=h.text.toLowerCase();
   const node=[...$('#sbody').querySelectorAll('.sec,label,b,.note')].find(n=>(n.textContent||'').toLowerCase().includes(want));
   if(node){node.scrollIntoView({block:'center'});node.classList.add('sflash');setTimeout(()=>node.classList.remove('sflash'),1600)}})};
  const draw=()=>{res.innerHTML='';hits.forEach((h,i)=>{const r=el(`<div class="${i===sel?'sel':''}"><b></b><small></small></div>`);
   r.querySelector('b').textContent=h.text;r.querySelector('small').textContent=h.label;r.onmousedown=e=>{e.preventDefault();pick(h)};res.appendChild(r)})};
  inp.oninput=()=>{const t=inp.value.trim().toLowerCase();sel=0;
   hits=!t?[]:idx.filter(h=>h.text.toLowerCase().includes(t)||h.label.toLowerCase().includes(t)).slice(0,12);draw()};
  inp.onkeydown=e=>{if(!hits.length)return;
   if(e.key==='ArrowDown'){e.preventDefault();sel=(sel+1)%hits.length;draw()}
   if(e.key==='ArrowUp'){e.preventDefault();sel=(sel-1+hits.length)%hits.length;draw()}
   if(e.key==='Enter'){e.preventDefault();pick(hits[sel])}
   if(e.key==='Escape'){e.stopPropagation();inp.value='';hits=[];draw()}};
  inp.onblur=()=>setTimeout(()=>{res.innerHTML=''},150)}
 host.querySelector('.modal').onclick=e=>{if(e.target.classList.contains('modal'))closeModal()};
 const body=$('#sbody');
 const draft=JSON.parse(JSON.stringify(st));
 // what Settings showed when it opened: Save sends only what you changed here. It sent the
 // whole snapshot, so a fallback model added a moment ago (saved at once), or anything
 // changed from the phone meanwhile, was put back the way it was when this opened.
 let orig=JSON.parse(JSON.stringify(st));
 // the free-text boxes of tabs you have left: switching tabs used to drop their edits
 let editIns=null, editMcp=null;
 function keepText(){if($('#m_ins'))editIns=$('#m_ins').value;if($('#mcp_json'))editMcp=$('#mcp_json').value}
 async function tabs(n){host.querySelectorAll('.tabs button').forEach(b=>b.classList.toggle('on',b.dataset.t===n));
  keepText();collect();RENDER_GEN++;await render(n);
  if(n==='general'){drawDeskUpdates(body);drawWebUpdates(body);drawAccount(body);drawScience(body)}
  if(editIns!=null&&$('#m_ins'))$('#m_ins').value=editIns;
  if(editMcp!=null&&$('#mcp_json'))$('#mcp_json').value=editMcp}
 host.querySelectorAll('.tabs button').forEach(b=>b.onclick=()=>{
  if(b.dataset.t==='library'){closeModal();showPane('lib');return}
  tabs(b.dataset.t)});

 async function render(name){
  // a tab that loads slowly must not draw over the tab you have since opened
  const gen=RENDER_GEN;
  // the servers tab saves each server on its own, so Settings' own Save buttons are left out of it
  ['#savebtn','#restartbtn'].forEach(id=>{const b=$(id);if(b)b.style.display=(name==='servers'||name==='collab')?'none':''});
  if(name==='general'){
   body.innerHTML=`<div class=sec>Conversation</div><div class=grid>
    <label>Thinking mode</label><div class=sw><input type=checkbox id=g_think><span class=note>slower but much more accurate</span></div>
    <label>Reasoning effort</label><select id=g_eff><option>low</option><option>medium</option><option>xhigh</option></select>
    <label>Show thinking</label><div class=sw><input type=checkbox id=g_show></div>
    <label>Max tool rounds</label><input type=number id=g_rounds min=0 max=100000 placeholder="0 = no limit">
    <div class=hint2>How many tool-calling rounds one answer may take. Research tasks need 40+.</div>
    <label>Max minutes per answer</label><input type=number id=g_mins min=0 max=100000 placeholder="0 = no limit">
    <label>Tell me it's still going every</label><input type=number id=g_notice min=0 max=1440 placeholder="minutes · 0 = never">
    <div class=hint2>Backstop so a stuck task can't run forever. 0 = no limit.</div>
    <label>Auto-compact at</label><div style="display:flex;gap:8px;align-items:center">
      <input type=number id=g_ac min=0 max=100 style="max-width:110px"><span class=note>% of context (0 = off)</span></div>
    <div class=hint2>When the window fills past this, older turns are summarised automatically before your next message.</div>
    <label>Reviews a local chat's actions</label><select id=g_reviewer></select>
    <div class=hint2>Only for chats on the model running on this Mac. That model answers one
     request at a time, so it cannot be asked whether its own next action is safe — the question
     queues behind the answer and times out. A model somewhere else can be. It sees the action and
     the rule's concern, and anything but a clear yes still comes to you; <b>sudo</b>, rewriting
     history and forced pushes are never put to it at all. Off = you are asked, as now.</div>
    <label>Side work goes to</label><select id=g_helper></select>
    <div class=hint2>Chat titles, compaction summaries, saved-memory extraction, the skill writer,
     the review and the completion check are Orbit's own work, not the answer.
     A CLI-backed choice (Claude Code, Codex) starts that whole agent for each one, which is slow
     for something as small as a title — an API model is usually the better fit here.
     A model on this Mac takes one request at a time, so asking it to review the turn it just
     finished means queueing behind that turn — pick a hosted model here and the review runs while
     the local one is busy. "the model answering" keeps today's behaviour.</div>
    <label>Review what an answer changed</label><div class=sw><select id=g_review>
      <option value="">off</option><option value="changes">report what is wrong</option>
      <option value="fix">report, and have it fix what is real (up to 2 rounds)</option></select>
      <span class=note>when a turn writes files, a second model reads the diff, with what was asked; lockfiles are skipped and anything it could not read is named</span></div>
    <label>Offer to keep going</label><div class=sw><input type=checkbox id=g_goaloffer>
      <span class=note>when an answer plainly leaves work undone, offer to make it a goal — and take the offer on its own after
       <input type=number id=g_goalwait min=0 max=3600 style="width:5em"> seconds unless you answer (0: wait for you)</span></div>
    <label>Check the work before finishing</label><div class=sw><input type=checkbox id=g_verify>
      <span class=note>ask the side-work model whether the request was actually carried out, and carry
       on if it was not (at most twice)</span></div>
    <div class=hint2>It reads the transcript for evidence rather than asking the model that just
     answered whether it is happy. A verifier that breaks passes the work — it can never trap a
     finished answer in a loop.</div>
    <label>Quiet mode</label><div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
      <span class=note id=g_quiet></span><button class=ghost id=g_quiet3>quiet for 3 h</button><button class=ghost id=g_quietoff>off</button></div>
    <div class=hint2>While quiet, the model server runs with fan mode "default": macOS manages the fans, with no boost while it generates. Takes effect the next time the server starts (Settings → Local server → restart). The permanent choice is "Fan mode" under Local server.</div>
    <label>Recycle bin keeps</label><div style="display:flex;gap:8px;align-items:center">
      <input type=number id=g_td min=1 max=365 style="max-width:110px"><span class=note>days</span></div>
    </div>
    <div class=sec>Appearance <small>— stored in this browser</small></div><div class=grid>
    <label>Theme</label><select id=g_theme><option value=system>follow system</option>
      <option value=light>light</option><option value=dark>dark</option></select>
    <label>Text size</label><div style="display:flex;gap:8px;align-items:center">
      <input type=range id=g_font min=13 max=19 step=1 style="max-width:180px">
      <span class=note id=g_fontv></span></div>
    <label>Sidebar width</label><div style="display:flex;gap:8px;align-items:center">
      <input type=range id=g_sw min=190 max=460 step=10 style="max-width:180px">
      <span class=note id=g_swv></span></div>
    </div>
    <div class=sec>Sampling <small>— blank = the model's own defaults for the current mode</small></div><div class=grid>
    <label>Temperature</label><input type=text id=s_temp placeholder="auto (1.0 thinking / 0.7 instruct)">
    <label>Top P</label><input type=text id=s_top_p placeholder="auto (0.95 / 0.8)">
    <label>Top K</label><input type=text id=s_top_k placeholder="auto (20)">
    <label>Presence penalty</label><input type=text id=s_pres placeholder="auto (0 / 1.5)">
    </div>
    <div class=sec>Backup</div><div class=grid>
    <label>Whole setup</label><div style="display:flex;gap:8px;flex-wrap:wrap">
      <button class=ghost id=g_backup>Export archive</button>
      <button class=ghost id=g_restore>Restore from archive…</button>
      <span class=note id=g_bk></span></div>
    <div class=hint2>Config, memory, skills, knowledge, sessions and code — not the venv.</div>
    </div>
    <div class=sec>System prompt
      <small>— <span id=g_sysreset style="color:var(--acc);cursor:pointer">reset to default</span></small></div>
    <textarea class=ta id=g_sys></textarea>
    <div class=grid style="margin-top:10px">
    <label>Include instructions</label><div class=sw><input type=checkbox id=g_useins></div>
    <label>Include memory</label><div class=sw><input type=checkbox id=g_usemem></div></div>`;
   $('#g_think').checked=!!draft.thinking;$('#g_show').checked=!!draft.show_thinking;
   $('#g_eff').value=draft.reasoning_effort||'medium';$('#g_rounds').value=draft.max_tool_rounds??0;
   $('#g_mins').value=draft.max_turn_minutes??0;$('#g_notice').value=draft.long_run_notice_min??30;
   $('#g_ac').value=draft.autocompact_pct??80;
   $('#g_review').value=['changes','fix'].includes(draft.auto_review)?draft.auto_review:'';
   $('#g_verify').checked=!!draft.verify_turns;
   $('#g_goaloffer').checked=draft.goal_offers!==false;$('#g_goalwait').value=draft.goal_offer_wait_s??120;
   {const sel=$('#g_reviewer'),cur=draft.review_model||'';
    // a reviewer has to be somewhere else: a local one is the problem, not the fix
    // somewhere else, able to answer, and not a CLI agent: a reviewer judges, it must not be
    // able to act on the text it is judging
    const away=(MODELS.models||[]).filter(m=>!m.switch&&m.ready!==false&&m.provider!=='local'&&m.provider!=='bionic'
      &&!/cli$/i.test(m.kind||'')&&!/ · CLI$/.test(m.label||''));
    const g2={};away.forEach(m=>{(g2[m.provider_label||'other']=g2[m.provider_label||'other']||[]).push(m)});
    sel.innerHTML='<option value="">off — ask me</option>'+
     Object.entries(g2).map(([g,list])=>`<optgroup label="${esc(g)}">`+list.map(m=>{
      const cli=/cli$/i.test(m.kind||'')||/ · CLI$/.test(m.label||'');
      return `<option value="${esc(m.id)}"${m.id===cur?' selected':''}>${esc(m.label||m.model)}`
        +(cli?' — spawns the CLI, slow for this':'')+`</option>`}).join('')+'</optgroup>').join('')}
   {const sel=$('#g_helper'),cur=draft.helper_model||'';
    // grouped by provider, and a CLI-backed choice says what it costs: those spawn a
    // whole coding agent per call, which is a lot of machinery to name a chat
    const groups={};
    (MODELS.models||[]).filter(m=>!m.switch&&m.ready!==false)
     .forEach(m=>{(groups[m.provider_label||'other']=groups[m.provider_label||'other']||[]).push(m)});
    sel.innerHTML='<option value="">the model answering this chat</option>'+
     Object.entries(groups).map(([g,list])=>`<optgroup label="${esc(g)}">`+list.map(m=>{
      const cli=/cli$/i.test(m.kind||'')||/ · CLI$/.test(m.label||'');
      return `<option value="${esc(m.id)}"${m.id===cur?' selected':''}>${esc(m.label||m.model)}`
        +(cli?' — spawns the CLI':'')+`</option>`}).join('')+'</optgroup>').join('')}$('#g_td').value=draft.trash_days??30;
   const drawQuiet=()=>{const u=+draft.quiet_until||0;$('#g_quiet').textContent=u*1000>Date.now()?
     'on until '+new Date(u*1000).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}):'off'};
   const setQuiet=async until=>{const r=await apiPost('/api/settings',{settings:{quiet_until:until}},'quiet mode');
    if(r){draft.quiet_until=until;drawQuiet()}};
   $('#g_quiet3').onclick=()=>setQuiet(Date.now()/1000+3*3600);$('#g_quietoff').onclick=()=>setQuiet(0);drawQuiet();
   $('#g_theme').value=PREF.get('theme','system');
   $('#g_font').value=PREF.get('font',15);$('#g_fontv').textContent=PREF.get('font',15)+'px';
   $('#g_sw').value=PREF.get('sidew',256);$('#g_swv').textContent=PREF.get('sidew',256)+'px';
   $('#g_backup').onclick=async()=>{$('#g_bk').textContent='archiving…';
    const r=await (await fetch('/api/backup',{method:'POST'})).json();
    $('#g_bk').textContent=`${(r.bytes/1048576).toFixed(1)} MB → ${r.path.split('/').pop()}`;
    toast('saved to workspace')};
   $('#g_restore').onclick=async()=>{
    const p=prompt('Path to a qwen-backup-*.tar.gz');if(!p)return;
    $('#g_bk').textContent='restoring…';
    const r=await (await fetch('/api/restore',{method:'POST',
     headers:{'Content-Type':'application/json'},body:JSON.stringify({path:p})})).json();
    $('#g_bk').textContent=r.error||`restored ${r.restored} files`;
    loadSessions()};
   $('#g_sysreset').onclick=async()=>{
    const d=await (await fetch('/api/default_prompt')).json();
    $('#g_sys').value=d.text;toast('restored default prompt')};
   $('#g_theme').onchange=e=>applyTheme(e.target.value);
   $('#g_font').oninput=e=>{applyFont(e.target.value);$('#g_fontv').textContent=e.target.value+'px'};
   $('#g_sw').oninput=e=>{applySidebar(e.target.value);$('#g_swv').textContent=e.target.value+'px'};
   $('#g_sys').value=draft.system_prompt||'';$('#g_useins').checked=!!draft.use_instructions;
   $('#g_usemem').checked=!!draft.use_memory;
   const sm=draft.sampling||{};
   $('#s_temp').value=sm.temperature??'';$('#s_top_p').value=sm.top_p??'';
   $('#s_top_k').value=sm.top_k??'';$('#s_pres').value=sm.presence_penalty??'';
  }
  if(name==='collab'){await renderCollab(body,gen);return}
  if(name==='helpers'){await renderHelpers(body,gen);return}
  if(name==='phone'){
   const r=await (await fetch('/api/remote')).json();
   if(gen!==RENDER_GEN)return;      // you moved to another tab while this loaded
   const ts=r.tailscale||{};
   const modes=[['off','Off','Only this Mac can reach Orbit. The default.'],
     ['internet','Internet (no Tailscale)','Reachable from any network at your own web address, through a Cloudflare tunnel that only you can pass (emailed code, or the phone app’s key). The Mac opens no port; nothing is on the Wi-Fi. Needs the one-time setup in docs/INTERNET_DOOR.md.'],
     ['tailscale','Tailscale','Reachable from anywhere on your tailnet, and bound to the tailnet interface only — the port is not on whatever Wi-Fi you are using.'],
     ['lan','Local network','Reachable from this Wi-Fi. Simplest at home; do not use on a network you do not trust.']];
   body.innerHTML=`<div class=sec>Phone access
     <small>— off by default; Orbit has no login, so nothing reaches it unpaired</small></div>
    ${modes.map(([v,label,why])=>`<label class=memrow style="cursor:pointer;align-items:flex-start">
      <input type=radio name=rmode value="${v}" ${r.mode===v?'checked':''} style="margin-top:3px">
      <span><b>${label}</b><br><span class=note>${why}</span></span></label>`).join('')}
    ${r.hint?`<div class=hint2 style="color:var(--warn);margin-top:8px">${esc(r.hint)}</div>`:''}
    <div class=sec style="margin-top:16px">Status</div>
    <div class=grid>
     <label>Reachable at</label><input readonly value="${esc(r.url||'— not reachable yet')}">
     <label>Tailscale</label><input readonly value="${ts.installed?(ts.running?('connected · '+(ts.name||ts.ip)):'installed, not connected'):'not installed'}">
     <label>Internet address</label><input readonly value="${r.tunnel&&r.tunnel.set_up?esc('https://'+r.tunnel.host+(r.tunnel.credentials?'':'  (phone key missing — run: orbit-tunnel rotate)')):'not set up — run bin/orbit-tunnel setup (docs/INTERNET_DOOR.md)'}">
     <label>This network</label><input readonly value="${esc(r.lan_ip||'unknown')}">
    </div>
    ${r.enabled&&r.url?`<div class=sec style="margin-top:16px">Pair a device</div>
      <div style="display:flex;gap:18px;align-items:flex-start;flex-wrap:wrap">
       <img src="/api/remote/qr?ts=${Date.now()}" width=300 height=300
            style="border-radius:12px;background:#fff;padding:8px;image-rendering:pixelated;max-width:100%;height:auto">
       <div style="flex:1;min-width:220px">
        <div class=note>Scan it with the Orbit app on your iPhone. The code carries the
         address and a one-time pairing code, good once for fifteen minutes; the phone
         trades it for a token of its own, kept in its Keychain and never typed.</div>
        <button class=ghost id=applink style="margin-top:10px">Copy a pairing link</button>
        <span class=note> for AirDrop or a message to your phone; tap it there. It works once, like the code, and carries the same key: keep it private.</span><br>
        <button class=ghost id=rot style="margin-top:10px">Unpair every device</button>
        <div class=hint2>For one lost device, revoke just that one below.</div>
       </div></div>
      <div class=sec style="margin-top:16px">Pair a browser</div>
      <div class=note style="margin-left:0">For a browser on another computer: open the link there once and it stays
       signed in, until you revoke it below.</div>
      <button class=ghost id=weblink style="margin-top:10px">Show a pairing link</button>
      <div id=webpair style="margin-top:10px"></div>`
      :'<div class=note style="margin-top:12px">Turn on a mode above, then restart, to pair a device.</div>'}
    <div class=hint2 style="margin-top:14px">Changing the mode needs a restart —
     use <b>Save &amp; restart server</b> below, or the Restart button in the sidebar.</div>
    <div class=sec style="margin-top:16px">Devices <small>— each with its own token</small></div>
    <div id=devlist class=note>…</div>
    <div class=sec style="margin-top:16px">Push when the app is closed</div>
    <div class=grid>
     <label>ntfy address</label><input type=url id=p_ntfy placeholder="https://ntfy.sh/your-private-topic">
     <label>Only say "open Orbit"</label><div class=sw><input type=checkbox id=p_priv>
      <span class=note>the push never carries the text of an answer, a command or a chat name</span></div>
    </div>
    <div class=note style="margin-top:6px">The phone only shows its own notifications while the app is running. With an
     <a href="https://ntfy.sh" target=_blank rel=noopener>ntfy</a> topic (install the ntfy app and subscribe to it), a goal
     that finishes overnight, or an approval nobody is watching, reaches the phone anyway. It sends that text to the ntfy
     server you name — pick a long, private topic, or run your own. Empty: nothing is sent. Save to apply.</div>`;
   $('#p_ntfy').value=draft.push_ntfy_url||'';$('#p_priv').checked=!!draft.push_private;
   body.querySelectorAll('input[name=rmode]').forEach(b=>b.onchange=async()=>{
    const d=await apiPost('/api/remote/mode',{mode:b.value},'changing phone access');
    if(d){toast('saved — restart to apply');render('phone')}
    else render('phone')});
   const al=$('#applink'); if(al)al.onclick=async()=>{
    const r=await fetch('/api/remote/applink');const d=await r.json().catch(()=>({}));
    if(!r.ok)return toast(d.error||'could not make a link');
    try{await navigator.clipboard.writeText(d.link);toast('pairing link copied — send it to your phone and tap it ('+Math.round((d.expires_in||900)/60)+' min, once)')}
    catch(e){prompt('Copy this pairing link',d.link)}};
   const rot=$('#rot'); if(rot)rot.onclick=async()=>{
    if(!confirm('Unpair every device? Each one must scan the QR again.'))return;
    if(await apiPost('/api/remote/rotate',{},'unpairing')){toast('every device unpaired');render('phone')}};
   const wl=$('#weblink'); if(wl)wl.onclick=async()=>{
    const r=await fetch('/api/remote/weblink');const d=await r.json().catch(()=>({}));
    if(!r.ok)return toast(d.error||'could not make a link');
    const box=$('#webpair');
    box.innerHTML=`<div style="display:flex;gap:18px;align-items:flex-start;flex-wrap:wrap">
      <img src="${d.qr}" width=170 height=170 alt="pairing link as a QR code" style="border-radius:12px;background:#fff;padding:6px">
      <div style="flex:1;min-width:240px"><div class=note style="margin-left:0">Scan it with the phone's camera, or send the link
       to the device. Good once, for ${Math.round((d.expires_in||900)/60)} minutes.</div>
       <div style="display:flex;gap:6px;margin-top:8px"><input readonly id=weblinkv style="font-family:var(--mono);font-size:var(--fs-xs)">
        <button class=ghost id=weblinkc>Copy</button></div></div></div>`;
    $('#weblinkv').value=d.link;
    $('#weblinkc').onclick=async()=>{try{await navigator.clipboard.writeText(d.link);toast('link copied — it works once')}
     catch(e){$('#weblinkv').select();toast('select and copy it')}};
    setTimeout(drawDevices,15000)};
   drawDevices();
  }
  if(name==='backup'){
   const b=await (await fetch('/api/backup/status')).json();
   if(gen!==RENDER_GEN)return;      // you moved to another tab while this loaded
   const when=t=>t?new Date(t*1000).toLocaleString():'never';
   const size=n=>n>1e6?(n/1e6).toFixed(1)+' MB':Math.round(n/1e3)+' KB';
   body.innerHTML=`<div class=sec>Automatic backup
     <small>— chats, memory, skills, knowledge and settings, once a day</small></div>
    <label class=memrow style="cursor:pointer;align-items:flex-start">
     <input type=checkbox id=bk_on ${b.enabled?'checked':''} style="margin-top:3px">
     <span><b>Back up automatically</b><br><span class=note>${b.icloud
       ?'Into iCloud Drive › Orbit Backups, so a lost Mac costs a restore, not the conversations.'
       :'iCloud Drive is not set up on this Mac, so archives stay in Orbit\'s own backups folder.'}</span></span></label>
    <div class=grid style="margin-top:10px">
     <label>Folder</label><input id=bk_dest value="${esc(b.dest)}">
     <label>Every</label><input id=bk_every type=number min=1 value="${b.every_hours}">
     <label>Keep</label><input id=bk_keep type=number min=1 value="${b.keep}">
    </div>
    <div class=hint2>Every: hours between archives. Keep: how many recent archives to hold on to.</div>
    <label class=memrow style="cursor:pointer"><input type=checkbox id=bk_ws ${b.include_workspace?'checked':''}>
     <span>Include the workspace folder <span class=note>— files it made; can be large</span></span></label>
    <label class=memrow style="cursor:pointer"><input type=checkbox id=bk_sec ${b.include_secrets?'checked':''}>
     <span>Include API keys and the pairing token <span class=note>— off, so a stolen archive cannot spend your keys</span></span></label>
    <div class=sec style="margin-top:16px">Chats other programs keep
     <small>— Claude Code, Claude desktop, Codex and Antigravity hold their own; a mirror of them sits beside the archives</small></div>
    <label class=memrow style="cursor:pointer"><input type=checkbox id=bk_ext ${b.include_external!==false?'checked':''}>
     <span>Back up those chats too <span class=note>— only what is new or changed is copied; nothing in the mirror is ever deleted</span></span></label>
    ${(b.external_sources||[]).map(x=>`<label class=memrow style="cursor:pointer;margin-left:22px"><input type=checkbox data-ext="${esc(x.id)}" ${x.on?'checked':''}>
     <span>${esc(x.label)} <span class=note>— ${esc(x.note)}</span></span></label>`).join('')}
    <div class=hint2>Temporary chats are never copied, and leave nothing in these programs either.
     ${(b.external_state&&b.external_state.at)?'Last copy '+when(b.external_state.at)+': '+(b.external_state.copied||0)+' files ('+size(b.external_state.bytes||0)+')'+(b.external_state.left?', '+b.external_state.left+' more to come on the next run':'')+'.':'Not copied yet.'}</div>
    <div style="display:flex;gap:8px;margin-top:10px">
     <button class=ghost id=bk_save>Save</button><button class=ghost id=bk_now>Back up now</button>
     <button class=ghost id=bk_extnow title="copy the other programs' chats now (the first time can take a while)">Back up those chats now</button>
     <button class=ghost id=bk_extback title="put back chats the programs no longer have; never overwrites">Put back missing chats</button></div>
    <div class=sec style="margin-top:16px">Archives
     <small>— last ${b.last?when(b.last.mtime):'never'} · ${b.count} kept · ${size(b.total_bytes||0)}</small></div>
    ${(b.backups||[]).map(x=>`<div class=memrow><span style="flex:1"><b>${esc(x.name)}</b><br>
       <span class=note>${when(x.mtime)} · ${size(x.bytes)}</span></span>
       <button class=ghost data-restore="${esc(x.name)}">Put back what is missing</button></div>`).join('')
     ||'<div class=note>No archives yet.</div>'}
    <div class=hint2 style="margin-top:10px">Restoring only adds chats, memory, skills and knowledge
     the Mac no longer has. It never overwrites what is here now.</div>`;
   $('#bk_save').onclick=async()=>{
    const d=await apiPost('/api/backup/settings',{enabled:$('#bk_on').checked,dest:$('#bk_dest').value,
      every_hours:+$('#bk_every').value,keep:+$('#bk_keep').value,
      include_workspace:$('#bk_ws').checked,include_secrets:$('#bk_sec').checked,
      include_external:$('#bk_ext').checked,
      external:Object.fromEntries([...body.querySelectorAll('[data-ext]')].map(x=>[x.dataset.ext,x.checked]))},'saving');
    if(d){toast('saved');render('backup')}};
   $('#bk_on').onchange=async()=>{
    if(await apiPost('/api/backup/settings',{enabled:$('#bk_on').checked},'saving'))
     toast($('#bk_on').checked?'automatic backup on':'automatic backup off')};
   $('#bk_extnow').onclick=async()=>{
    await apiPost('/api/backup/settings',{include_external:$('#bk_ext').checked,
     external:Object.fromEntries([...body.querySelectorAll('[data-ext]')].map(x=>[x.dataset.ext,x.checked]))},'saving');
    if(await apiPost('/api/backup/external_now',{},'starting'))toast('copying those chats in the background — come back to this page to see how far it got')};
   $('#bk_extback').onclick=async()=>{
    if(!confirm('Put back chats that Claude Code, Codex or Antigravity no longer have and the mirror does? Nothing there is overwritten.'))return;
    const d=await apiPost('/api/backup/restore_external',{},'restoring');
    if(d)toast(d.n?('put back '+d.n+' files'):'nothing was missing')};
   $('#bk_now').onclick=async()=>{
    const d=await apiPost('/api/backup/now',{},'writing the archive');
    if(d){toast('wrote '+d.name);render('backup')}};
   body.querySelectorAll('[data-restore]').forEach(x=>x.onclick=async()=>{
    if(!confirm('Put back what this archive has and the Mac no longer does? Nothing here is overwritten.'))return;
    const d=await apiPost('/api/backup/restore_missing',{name:x.dataset.restore},'restoring');
    if(d)toast(d.n?('put back '+d.n+' files'):'nothing was missing')});
  }
  if(name==='models'){
   await loadModels();
   if(gen!==RENDER_GEN)return;      // you moved to another tab while this loaded
   const provs=MODELS.providers||{}, keys=MODELS.keys||{};
   // harness providers have their own cards below; this list is the rest
   const rows=MODELS.models.filter(m=>!/^harness(-direct)?:/.test(m.id)).map(m=>`<div class=memrow>
     <b>${esc(m.label||m.model)}</b>
     <span>${esc(m.provider_label)}${m.context?' · '+(m.context/1000|0)+'k context':''}${
       m.ready?'':' · <span style="color:var(--warn)">needs a key</span>'}${
       m.switch?' · <span style="color:var(--mut)">loads on demand</span>':''}</span>
     ${m.id===(MODELS.default||'')?'<span class=pill>default</span>'
       :`<button class=ghost data-def="${esc(m.id)}">make default</button>`}
     ${m.provider==='local'?'':`<button class=ghost data-forget="${esc(m.id)}">remove</button>`}
    </div>`).join('');
   const provRows=Object.entries(provs).map(([pid,pv])=>{
    const kn=pv.key||'';
    return `<div class=memrow style="align-items:center">
      <b>${esc(pv.label||pid)}</b>
      <span>${esc(pv.kind)}${pv.base_url?' · '+esc(pv.base_url.replace(/^https?:\/\//,'')):''}</span>
      ${kn?`<input id="k_${esc(pid)}" type=password style="max-width:230px"
            placeholder="${keys[kn]?esc(keys[kn]):'paste '+esc(kn)}">`
          :`<span class=note style="min-width:230px">${pv.server?(pv.server.running?'serving — no key needed':'server off — starts when you use it'):'no key needed'}</span>`}
      ${pv.server&&!pv.server.running?`<button class=ghost data-bionic="${esc(pid)}">start server</button>`
        :`<button class=ghost data-fetch="${esc(pid)}">fetch models</button>`}
      ${pv.keys_url?`<a class=note href="${esc(pv.keys_url)}" target=_blank>get a key ↗</a>`:''}
     </div>`}).join('');
   body.innerHTML=`<div class=sec>Providers
     <small>— for Claude Code mode and Orbit alike · keys are stored in config/secrets.json on this Mac and sent only to their provider</small></div>
    <div id=hm_box class=note>loading…</div>
    <div id=fb_box style="margin-top:18px"></div>
    <div class=sec style="margin-top:18px">Cheaper hours <small>— providers that charge less at some times of day</small></div>
    <div class=note>Models in the pickers are marked 🟢 while their provider's discount is on, 🟠 when it applies at other hours. <button class=ghost id=op_show>Show the policies</button></div>
    <div class=sec style="margin-top:18px">More models for Orbit's own chat
     <small>— the local server, coding CLIs you are signed into, OpenAI-compatible servers</small></div>
    ${rows||'<div class=note>None yet.</div>'}
    <div class=sec style="margin-top:18px">Their providers</div>
    ${provRows}
    <div class=hint2 style="margin-top:10px">Anything speaking the OpenAI API works —
     add your own below (vLLM, SGLang, a colleague's server).</div>
    <div class=grid style="margin-top:10px">
     <label>New provider id</label><input id=np_id placeholder="my-server">
     <label>Label</label><input id=np_label placeholder="Lab GPU box">
     <label>Wire format</label><select id=np_kind><option value=openai>OpenAI-compatible</option>
       <option value=anthropic>Anthropic</option></select>
     <label>Base URL</label><input id=np_base placeholder="http://10.0.0.5:8000/v1">
     <label>Key name</label><input id=np_key placeholder="MY_SERVER_KEY (blank if none)">
    </div>
    <button class=ghost id=np_add style="margin-top:9px">Add provider</button>`;
   body.querySelectorAll('[data-def]').forEach(b=>b.onclick=async()=>{
    await apiPost('/api/model/default',{id:b.dataset.def},'setting the default');
    toast('default model set'); render('models')});
   body.querySelectorAll('[data-forget]').forEach(b=>b.onclick=async()=>{
    if(!confirm('Remove '+b.dataset.forget+' from the list?'))return;
    if(await apiPost('/api/model/forget',{id:b.dataset.forget},'removing'))
     toast('removed — fetch that provider\'s models again to bring it back');render('models')});
   body.querySelectorAll('[data-bionic]').forEach(b=>b.onclick=async()=>{
    b.textContent='starting…';b.disabled=true;
    const d=await apiPost('/api/bionic/start',{},'starting Bionic');
    toast(d&&d.ok?'Bionic is serving':'could not start it'+(d&&d.detail?': '+d.detail:''));
    render('models')});
   body.querySelectorAll('[data-fetch]').forEach(b=>b.onclick=async()=>{
    const pid=b.dataset.fetch, inp=$('#k_'+pid);
    if(inp&&inp.value.trim()){
     const kn=(provs[pid]||{}).key;
     await apiPost('/api/secrets/save',{secrets:{[kn]:inp.value.trim()}},'saving the key')}
    b.textContent='asking…';
    const d=await apiPost('/api/model/fetch',{provider:pid},'fetching models');
    b.textContent='fetch models';
    if(!d)return;
    if(d.error){toast(d.error.slice(0,120));return}
    toast(d.found+' models from '+pid); render('models')});
   $('#np_add').onclick=async()=>{
    const id=$('#np_id').value.trim(); if(!id)return toast('the provider needs an id');
    await apiPost('/api/model/provider',{id,provider:{
      label:$('#np_label').value.trim()||id, kind:$('#np_kind').value,
      base_url:$('#np_base').value.trim(), key:$('#np_key').value.trim()}},'adding the provider');
    toast('provider added'); render('models')};
   renderHarnessModels($('#hm_box'));renderFallback($('#fb_box'));
   $('#op_show').onclick=()=>{closeModal();showOffpeak()};
  }
  if(name==='model'){
   const sv=draft.server||{};
   body.innerHTML=`<div class=sec>Server <small>— these need a restart</small></div><div class=grid>
    <label>Context window</label><input type=number id=v_ctx step=1024>
    <div class=hint2>Bigger allows longer chats; KV cache grows with it.</div>
    <label>KV quantization</label><select id=v_kv><option>off</option><option>q8</option><option>q4</option></select>
    <div class=hint2>q8 halves KV memory at near-zero quality cost.</div>
    <label>Fan mode</label><select id=v_fan><option>default</option><option>smart</option><option>max</option></select>
    <label>Thermal polling</label><div class=sw><input type=checkbox id=v_therm></div>
    <label>Draft depth (MTP)</label><input type=number id=v_depth min=1 max=3>
    <label>Prefill chunk tokens</label><input type=number id=v_pre step=512>
    <div class=hint2>Lower = smaller memory spike on long prompts.</div>
    <label>Server reasoning default</label><select id=v_reason><option>off</option><option>auto</option><option>on</option></select>
    <div class=hint2>For clients that don't ask (OpenCode). This UI always asks explicitly.</div>
    <label>Scheduler</label><select id=v_sched><option>serial</option><option>cooperative</option></select>
    <label>Idle shutdown (min)</label><input type=number id=v_idle min=0>
    <div class=hint2>Watchdog stops the server after this long with no activity. 0 disables.</div>
    </div>`;
   $('#v_ctx').value=sv.context_window;$('#v_kv').value=sv.kv_quant;$('#v_fan').value=sv.fan_mode;
   $('#v_therm').checked=!!sv.thermal_poll;$('#v_depth').value=sv.depth;
   $('#v_pre').value=sv.prefill_chunk_tokens;$('#v_reason').value=sv.reasoning;
   $('#v_sched').value=sv.scheduler_mode;$('#v_idle').value=draft.idle_min;
  }
  if(name==='tools'){
   const en=draft.tools_enabled||{};
   const names=[...new Set([...(info.all_tools||[]),...(info.tools||[])])];
   const mode=draft.autonomy_mode||'ask';
   const AUTOMODES=[
    ['ask','Ask every time','the default — every risky action stops for your explicit approval, like today'],
    ['auto','Auto-approve safe actions',
     'file edits and deletions that stay inside the workspace run without asking; anything that reaches the rest of the machine, the network, or your own source still asks'],
    ['full','Full computer access',
     'like Claude Code’s --dangerously-skip-permissions — turns on shell, write-anywhere and cluster write for this session, and runs everything else without asking. A short list of machine-wide actions (sudo, shutdown, the keychain, publishing a package, rewriting git history, force-pushing, deleting quota) still always asks, and a hard floor (wiping a disk, a fork bomb, a reverse shell, piping a download into a shell, killing every process, anything aimed at a protected path like your home directory) is never approvable at all, in any mode.'],
   ];
   body.innerHTML=`<div class=sec>Autonomy <small>— how much it can do without asking first</small></div>
    ${AUTOMODES.map(([v,label,why])=>`<label class=memrow style="cursor:pointer;align-items:flex-start">
      <input type=radio name=automode value="${v}" ${mode===v?'checked':''} style="margin-top:3px">
      <span><b>${label}</b><br><span class=note>${esc(why)}</span></span></label>`).join('')}
    <div class=hint2 style="margin:8px 0 4px">Every action is written to <code>logs/safety.log</code>
     regardless of mode, including which ones ran unattended.</div>
    <div class=sec>Your own rules <small>— personal allow/deny patterns on top of the tiers above, like Claude Code's Bash(git diff:*)</small></div>
    <div id=rulelist></div>
    <div class=grid style="margin-top:8px">
     <label>Tool</label><input type=text id=r_tool placeholder="* (any tool) or e.g. run_shell">
     <label>Pattern</label><input type=text id=r_pattern placeholder="e.g. git diff* or rm -rf*">
     <label>Note</label><input type=text id=r_note placeholder="optional — why">
    </div>
    <div style="display:flex;gap:8px;margin-top:8px">
     <button class=ghost id=r_deny>Add deny rule</button>
     <button class=ghost id=r_allow>Add allow rule</button>
    </div>
    <div class=hint2>Deny always blocks that pattern, in every autonomy mode — it can only ever add
     restriction, never lift the hard floor below. Allow pre-approves a normally-confirm-level match
     without asking, in any mode — it can never reach a blocked action, only skip a question that would
     otherwise have been asked.</div>
    <div class=sec>Permissions</div><div class=grid>
     <label>Code execution</label><div class=sw><input type=checkbox id=t_code><span class=note>the python tool runs real code on your Mac</span></div>
     <label>Enable shell</label><div class=sw><input type=checkbox id=t_shell><span class=note>lets the model run shell commands ${mode==='full'?'— on anyway, from Full access':''}</span></div>
     <label>the cluster write access</label><div class=sw><input type=checkbox id=t_h2><span class=note>qsub / qdel / remote commands — read-only status always works ${mode==='full'?'— on anyway, from Full access':''}</span></div>
     <label>Write anywhere</label><div class=sw><input type=checkbox id=t_wany><span class=note>otherwise writes stay in workspace/ ${mode==='full'?'— on anyway, from Full access':''}</span></div>
    </div>
    <div class=sec>Seeing what it builds <small>— a browser, the iOS Simulator and Mac app windows, for any agent</small></div>
    <div class=grid>
     <label>Offer them to</label><div class=sw style="flex-wrap:wrap;gap:12px">
      <label><input type=checkbox data-le=claude> Claude Code</label>
      <label><input type=checkbox data-le=codex> Codex</label>
      <label><input type=checkbox data-le=opencode> OpenCode</label>
      <label title="each tool is a definition read on every message: a small local model pays for that in seconds"><input type=checkbox data-le=orbit> Orbit's own agent</label></div>
     <label>Kinds of tool</label><div class=sw style="flex-wrap:wrap;gap:12px">
      <label><input type=checkbox data-lg=browser> Browser</label>
      <label><input type=checkbox data-lg=simulator> iPhone simulator</label>
      <label><input type=checkbox data-lg=mac> Mac app windows</label></div>
    </div>
    <div class=hint2 id=lookstat>Checking what this Mac has…</div>
    <div class=hint2>An agent that builds a web page, an iPhone app or a Mac app can open it, take a screenshot
     and check the result before it says it works. The browser is a separate throwaway Chrome profile, with none
     of your logins. A model that cannot read images gets the page's text and a list of what is clickable
     instead. Looking runs without asking; starting or quitting an app on this Mac asks.</div>
    <div class=sec>Delegation <small>— the smart model decides; cheaper models do the small jobs</small></div>
    <div class=grid>
     <label>Delegation</label><div class=sw><input type=checkbox id=t_deleg>
      <span class=note>gives a chat's model a <code>delegate</code> tool: it hands small, well-specified tasks (searching, summarising,
       boilerplate, running a command and reporting) to the cheapest model that is ready, and keeps the design, the hard bugs, the
       security-sensitive parts and the final check for itself</span></div>
     <label>How eagerly</label><div class=sw><select id=t_deleg_eager>
       <option value=high>Eager — every request is sorted first; easy work goes to a cheaper model, and a reminder comes after a run of direct tool calls</option>
       <option value=balanced>Balanced — the model is told about delegation and decides</option>
       <option value=careful>Careful — only clearly mechanical jobs</option></select></div>
     <label>Second try</label><div class=sw><input type=checkbox id=t_deleg_esc>
      <span class=note>a light worker that ends with <code>Confidence: low</code> has its task done again by a standard model</span></div>
     <label>Claude Code subagents</label><div class=sw><input type=checkbox id=t_deleg_sub>
      <span class=note>with delegation on, Claude Code's own subagents (its Task tool) run on the small model too (Haiku on your plan)</span></div>
     <label>Workers may change files</label><div class=sw><input type=checkbox id=t_deleg_wr>
      <span class=note>otherwise workers only read and report. A worker that changes files works as its lead does, in the same folder, and the lead is told to check the result</span></div>
    </div>
    <div class=hint2>Each chat can differ: <code>/delegate on</code>, <code>/delegate off</code>, <code>/delegate auto</code>. A failed worker is skipped for ten minutes
     and the next one is tried. Models that train on your data (Meta's Contributor variants) are never picked unless you place them below.</div>
    <div id=delegbox class=hint2>loading the roster…</div>
    <div class=sec>Orbit improving itself <small>— agents can fix and extend Orbit, with a reviewer in the way</small></div>
    <div class=grid>
     <label>Mode</label><div><select id=si_mode><option value=off>Off — nothing can change Orbit</option>
      <option value=propose>Propose only — agents suggest; you approve each change</option>
      <option value=auto>Reviewed — applied by itself when the tests pass and another model finds it safe</option></select></div>
     <label>Reviewer</label><div><select id=si_rev></select> <span class=note>a different account from the one that wrote the change; the second opinion for risky ones is chosen by itself</span></div>
    </div>
    <div class=hint2>An agent that hits a limit or bug in Orbit proposes the fix with the <code>orbit_improve</code> tool. It is tried in a private copy of Orbit
     (the whole test suite must pass), scanned for risky code, and read by a reviewer model that treats it as untrusted. <b>Anything touching Orbit's permission rules,
     secrets, remote access, the terminal or this feature itself is never applied without you.</b> Every change is backed up and can be rolled back here; if Orbit
     will not start after one, it is put back by itself.</div>
    <div id=sibox class=hint2>loading…</div>
    <div class=sec>Screen control <small>— not covered by Full access; a separate decision</small></div>
    <div class=grid>
     <label>Screen control</label><div class=sw><input type=checkbox id=t_screen>
      <span class=note>lets the model see your screen and click, type and press keys on this Mac — in
       <b>any</b> app, not just the workspace</span></div>
    </div>
    <div class=hint2>Needs two macOS permissions you grant by hand — Settings will tell you which,
     the first time an action is refused: <b>Screen Recording</b> (for screenshots) and
     <b>Accessibility</b> (for clicks and keystrokes), both in System Settings → Privacy &amp; Security.
     Nothing here can turn those on for you. A screenshot only actually gets <em>seen</em> by a
     vision-capable model — a hosted Claude model, or one Bionic runs on this Mac that says it takes
     images, but not the MTPLX local model or a CLI-backed one — but every
     mode still asks before a click or keystroke unless you have turned on Full access, same as any
     other confirm-level action.</div>
    <div class=sec>Easy mode <small>— a short bench of tools instead of the whole workshop</small></div>
    <div class=hint2>Orbit's tool schemas cost about 9,800 tokens of every request — three times its
     system prompt — and a small model chooses better from a dozen tools than from fifty. With easy
     mode on, only the tools ticked below are offered; everything else stays installed and comes back
     the moment you turn it off. In Claude Code mode the second list applies instead.</div>
    <div style="margin:4px 0"><label style="display:inline-flex;gap:6px;align-items:center">
      <input type=checkbox id=t_easy> <b>Only the essential tools</b></label>
      <span class=note id=easycount></span></div>
    <div id=easybox style="display:none">
     <div class=sec style="margin-top:10px">Orbit's own agent <small>— ticked tools are offered</small></div>
     <div class=toolgrid id=easygrid></div>
     <div class=sec style="margin-top:10px">Claude Code tools <small>— what Claude Code reported having</small>
      <button class=ghost style="font-size:11px;margin-left:6px" id=easylearn>ask Claude Code again</button></div>
     <div class=toolgrid id=easyclaude><span class=note>loading…</span></div>
     <div class=sec style="margin-top:10px">Claude Code MCP servers <small>— each one's tools ride in every request</small></div>
     <div class=hint2>None ticked means none are started, which is usually what you want: a server's
      tools cost prompt whether or not they are ever called. Easy mode also turns hooks off for the
      run, because a plugin's hooks expect that plugin's server to be there.</div>
     <div class=toolgrid id=easymcp><span class=note>loading…</span></div>
    </div>
    <div class=sec>Available tools <small>— turned off here, a tool is gone from every mode</small></div><div class=toolgrid id=tg></div>`;
   $('#t_easy').checked=!!draft.easy_mode;
   $('#easybox').style.display=draft.easy_mode?'':'none';
   $('#t_easy').onchange=e=>{draft.easy_mode=e.target.checked;
    $('#easybox').style.display=e.target.checked?'':'none'};
   drawEasyTools(draft);
   $('#t_code').checked=draft.code_execution!==false;
   $('#t_h2').checked=!!draft.cluster_write;
   $('#t_shell').checked=!!draft.shell_enabled;$('#t_wany').checked=!!draft.write_any;
   $('#t_screen').checked=!!draft.computer_use_enabled;

   {const si=draft.self_improve||{};
    $('#si_mode').value=si.mode||'off';
    $('#si_rev').innerHTML=modelOptions(si.reviewer||'','automatic');
    $('#si_mode').onchange=e=>{draft.self_improve={...(draft.self_improve||{}),mode:e.target.value}};
    $('#si_rev').onchange=e=>{draft.self_improve={...(draft.self_improve||{}),reviewer:e.target.value}};
    draft.self_improve={...si,mode:si.mode||'off'};
    const siApi=async b=>{try{const r=await fetch('/api/selfimprove',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)});const d=await r.json();if(!r.ok){toast(d.error||'failed');return null}return d}catch(e){toast('could not reach Orbit');return null}};
    const drawSI=async()=>{const box=$('#sibox');if(!box)return;
     const d=await siApi({op:'list'});if(!d)return;
     box.innerHTML='';
     const chip={applied:'applied',verified:'applied · verified',needs_person:'waiting for you',rejected:'not applied',rolled_back:'rolled back',queued:'queued',testing:'testing…',reviewing:'being reviewed…',approved:'approved'};
     if(!(d.proposals||[]).length)box.appendChild(el('<div class=note>No proposals yet.</div>'));
     (d.proposals||[]).forEach(p=>{
      const r=el('<div style="border:1px solid var(--line);border-radius:8px;padding:6px 9px;margin:5px 0"></div>');
      r.appendChild(el('<div></div>')).innerHTML='<b></b> <span class=note></span>';
      r.querySelector('b').textContent=p.title;r.querySelector('.note').textContent='— '+(chip[p.status]||p.status);
      const sub=el('<div class=note></div>');sub.textContent=(p.why||'')+' · '+(p.files||[]).join(', ')+(p.proposer?' · by '+p.proposer.replace(/^(harness|codex|claude-cli|agy-cli|muse-cli):/,''):'');r.appendChild(sub);
      const acts=el('<div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:4px"></div>');
      const b=(t,fn,tip)=>{const x=el('<button class=ghost></button>');x.textContent=t;if(tip)x.title=tip;x.onclick=async()=>{x.disabled=true;try{await fn()}finally{x.disabled=false}drawSI()};acts.appendChild(x)};
      b('Details',async()=>{const v=await siApi({op:'diff',id:p.id});if(!v)return;
        openSheet(p.title,(body)=>{body.style.padding='12px 18px 16px';
         const t=(h,txt)=>{body.appendChild(el('<div class=sec></div>')).textContent=h;const pre=el('<pre class=taskout style="white-space:pre-wrap;max-height:30vh"></pre>');pre.textContent=txt;body.appendChild(pre)};
         t('Problem',v.problem||'');
         t('Checks',[v.tests?('Tests: '+(v.tests.ok?'passed':'FAILED')):'',...(v.protected||[]).map(x=>'Protected: '+x),...(v.scan||[]).map(f=>`Scan [${f.severity}] ${f.what} — ${f.path}: ${f.line}`),
           ...(v.verdicts||[]).map(x=>`Reviewer: ${x.approve?'approves':'says no'}, danger ${x.danger}. ${[...x.concerns,...x.reasons].join(' ')}`)].filter(Boolean).join('\n')||'—');
         t('Change',v.diff||'');
         if(v.tests&&!v.tests.ok)t('Test output',v.tests.tail||'')},{sub:p.id})});
      if(p.status==='needs_person'&&(p.files||[]).length)b('Approve and apply',async()=>{if(!confirm('Apply this change to Orbit? It is backed up and can be rolled back.'))return;const v=await siApi({op:'approve',id:p.id});if(v)toast('applied')},'applies it, with a backup');
      if(['needs_person','queued'].includes(p.status))b('Reject',()=>siApi({op:'reject',id:p.id}));
      if(['applied','verified'].includes(p.status))b('Roll back',async()=>{if(!confirm('Put the files back as they were before this change?'))return;const v=await siApi({op:'rollback',id:p.id});if(v)toast('rolled back')});
      r.appendChild(acts);box.appendChild(r)})};
    drawSI()}

   {const dl=draft.delegation||{};
    $('#t_deleg').checked=!!dl.enabled;$('#t_deleg_sub').checked=dl.subagents!==false;$('#t_deleg_wr').checked=!!dl.allow_changes;
    $('#t_deleg_eager').value=['careful','balanced','high'].includes(dl.eagerness)?dl.eagerness:'high';$('#t_deleg_esc').checked=dl.escalate!==false;
    draft.delegation={...dl,overrides:{...(dl.overrides||{})},exclude_providers:[...(dl.exclude_providers||[])],
     tiers:{light:[...((dl.tiers||{}).light||[])],standard:[...((dl.tiers||{}).standard||[])]}};
    fetch('/api/delegation').then(r=>r.json()).then(v=>{const box=$('#delegbox');if(!box)return;
     const DL=draft.delegation,byId={};(v.roster||[]).forEach(r=>byId[r.id]=r);
     const label=id=>(byId[id]||{}).label||id;
     const provName=p=>(v.providers||{})[p]||p;
     const led=v.ledger||{};
     const tierInfo={light:['Light','the cheapest models, for mechanical or read-only work'],standard:['Standard','for work that needs some care; if none of these can, the light ones are tried next']};
     const draw=()=>{
      box.innerHTML='';
      // 1. providers you do not have
      const pv=el('<div style="margin:6px 0"><b>Never use these</b> <span class=note>— accounts you have no subscription for. Anything on them is skipped when Orbit chooses by itself.</span></div>');
      const prow=el('<div style="display:flex;flex-wrap:wrap;gap:4px 14px;margin:4px 0"></div>');
      Object.keys(v.providers||{}).sort().forEach(p=>{
       const c=el('<label style="display:flex;gap:5px;align-items:center;white-space:nowrap"><input type=checkbox><span></span></label>');
       c.querySelector('span').textContent=provName(p);
       const cb=c.querySelector('input');cb.checked=DL.exclude_providers.includes(p);
       cb.onchange=()=>{DL.exclude_providers=DL.exclude_providers.filter(x=>x!==p);if(cb.checked)DL.exclude_providers.push(p);draw()};
       prow.appendChild(c)});
      pv.appendChild(prow);
      const quick=el('<div style="display:flex;gap:8px;flex-wrap:wrap"></div>');
      const mine=el('<button class=ghost title="excludes every account except Claude, Codex, Antigravity, Meta and Muse Code">Use only my subscriptions</button>');
      mine.onclick=()=>{const keep=['claude','codex','antigravity','meta','muse-code'];DL.exclude_providers=Object.keys(v.providers||{}).filter(p=>!keep.includes(p));draw()};
      quick.appendChild(mine);pv.appendChild(quick);box.appendChild(pv);
      // 2. one ordered list per tier
      ['light','standard'].forEach(t=>{
       const list=DL.tiers[t];
       const sec=el('<div style="margin:10px 0 4px"></div>');
       sec.appendChild(el('<div></div>')).innerHTML='<b>'+tierInfo[t][0]+'</b> <span class=note>— '+esc(tierInfo[t][1])+'</span>';
       if(!list.length){
        const auto=((v.order||{})[t]||[]).filter(id=>!(t==='standard'&&((v.order||{}).light||[]).includes(id))).slice(0,6);
        const a=el('<div class=note style="margin:3px 0"></div>');
        a.textContent='Automatic'+(auto.length?': '+auto.map(label).join(' → '):' — nothing ready here yet');
        sec.appendChild(a);
        const w=el('<button class=ghost>Write this order down, to change it</button>');
        w.onclick=()=>{DL.tiers[t]=auto.slice();draw()};sec.appendChild(w);
       }else{
        list.forEach((id,i)=>{
         const r=el('<div style="display:flex;align-items:center;gap:6px;margin:3px 0"><span class=note style="width:18px;text-align:right"></span><span style="flex:1"></span><span class=note></span></div>');
         const sp=r.children;sp[0].textContent=(i+1)+'.';sp[1].textContent=label(id);
         sp[2].textContent=provName((byId[id]||{}).provider||'')+(byId[id]?'':' — not ready now');
         const mk=(txt,tip,fn,dis)=>{const b=el('<button class=ghost style="padding:1px 7px"></button>');b.textContent=txt;b.title=tip;b.disabled=!!dis;b.onclick=fn;r.appendChild(b)};
         mk('↑','earlier',()=>{list.splice(i,1);list.splice(i-1,0,id);draw()},i===0);
         mk('↓','later',()=>{list.splice(i,1);list.splice(i+1,0,id);draw()},i===list.length-1);
         mk('✕','remove',()=>{list.splice(i,1);draw()});
         sec.appendChild(r)});
        const reset=el('<button class=ghost>Back to automatic</button>');reset.onclick=()=>{DL.tiers[t]=[];draw()};sec.appendChild(reset);
       }
       const add=el('<select style="margin-left:6px;max-width:320px"></select>');
       const groups={};(v.roster||[]).filter(r=>!list.includes(r.id)).forEach(r=>{(groups[provName(r.provider)]=groups[provName(r.provider)]||[]).push(r)});
       add.innerHTML='<option value="">+ add a model to this list…</option>'+Object.entries(groups).sort().map(([g,rs])=>`<optgroup label="${esc(g)}">${rs.map(r=>`<option value="${esc(r.id)}">${esc(r.label)}${r.tier==='lead'?' (a lead model)':''}</option>`).join('')}</optgroup>`).join('');
       add.onchange=()=>{if(add.value){DL.tiers[t].push(add.value);draw()}};
       sec.appendChild(add);box.appendChild(sec)});
      // 3. what has happened
      const used=Object.entries(led.stats||{}).map(([m,s])=>label(m)+' '+s.tasks).join(', ');
      if(led.tasks)box.appendChild(el('<div class=note></div>')).textContent='Handed on so far: '+led.tasks+' tasks ('+(led.tokens||0).toLocaleString()+' tokens)'+(led.fails?', '+led.fails+' failed':'')+' — '+used;
      const tu=led.turns||{};
      if(tu.total)box.appendChild(el('<div class=note></div>')).textContent='Delegated in '+tu.delegated+' of '+tu.total+' answers that used tools ('+Math.round((tu.share||0)*100)+'%). If this stays low, set "How eagerly" to Eager.';
      box.appendChild(el('<div class=note>Save settings to apply. A listed model that is not ready, or that just failed, is skipped for now, never swapped for one you did not choose. Best models (Opus, Fable, Sol, Astra) only work when you put them in a list.</div>'))};
     draw()}).catch(()=>{})}
   {const LE=draft.look_engines||['claude','codex','opencode'],LG=draft.look_groups||['browser','simulator','mac'];
    body.querySelectorAll('[data-le]').forEach(c=>{c.checked=LE.includes(c.dataset.le);
     c.onchange=()=>{draft.look_engines=[...body.querySelectorAll('[data-le]')].filter(x=>x.checked).map(x=>x.dataset.le)}});
    body.querySelectorAll('[data-lg]').forEach(c=>{c.checked=LG.includes(c.dataset.lg);
     c.onchange=()=>{draft.look_groups=[...body.querySelectorAll('[data-lg]')].filter(x=>x.checked).map(x=>x.dataset.lg)}});
    fetch('/api/look/status').then(r=>r.json()).then(st=>{const x=$('#lookstat');if(!x)return;
     x.innerHTML=[st.browser?`Browser: ${esc(st.browser)} ✓`:'Browser: no Chrome, Chromium, Brave or Edge found',
      st.simulator?'iPhone simulator: Xcode found ✓':'iPhone simulator: Xcode not found',
      st.taps?'taps and typing in the simulator ✓':'taps and typing in the simulator need AXe: <code>brew install cameroncooke/axe/axe</code>',
      'Mac app windows: Screen Recording must be granted to the app that runs Orbit (System Settings → Privacy &amp; Security)'].join(' · ')}).catch(()=>{})}
   const rules=draft.permission_rules||{allow:[],deny:[]};
   const rl=$('#rulelist');
   const ruleRow=(kind,r,i)=>{const row=el('<div class=memrow></div>');
    const b=document.createElement('b');b.textContent=(kind==='deny'?'deny ':'allow ')+(r.tool||'*');
    b.style.color=kind==='deny'?'var(--err)':'var(--ok, #2a7)';
    const sp=document.createElement('span');
    sp.textContent=r.pattern+(r.note?' — '+r.note:'');
    const del=el('<button class=ghost>remove</button>');
    del.onclick=async()=>{await fetch('/api/permissions/remove',{method:'POST',
      headers:{'Content-Type':'application/json'},body:JSON.stringify({kind,index:i})});
     openSettings('tools')};
    row.appendChild(b);row.appendChild(sp);row.appendChild(del);return row};
   if(!rules.deny.length&&!rules.allow.length)rl.innerHTML='<div class=note>No rules yet — none needed until you add one.</div>';
   rules.deny.forEach((r,i)=>rl.appendChild(ruleRow('deny',r,i)));
   rules.allow.forEach((r,i)=>rl.appendChild(ruleRow('allow',r,i)));
   const addRule=kind=>async()=>{
    const tool=$('#r_tool').value.trim()||'*',pattern=$('#r_pattern').value.trim();
    if(!pattern)return;
    await fetch('/api/permissions/add',{method:'POST',headers:{'Content-Type':'application/json'},
     body:JSON.stringify({kind,tool,pattern,note:$('#r_note').value.trim()})});
    openSettings('tools')};
   $('#r_deny').onclick=addRule('deny');$('#r_allow').onclick=addRule('allow');
   $('#t_screen').onchange=e=>{
    if(e.target.checked&&!confirm(
      "Screen control lets Orbit see your screen and click, type and press keys — in any app, "+
      "not just this project. A click or keystroke still always asks for your approval first, "+
      "unless you have separately turned on Full computer access.\n\nIt needs Screen Recording and "+
      "Accessibility granted to it by hand in System Settings → Privacy & Security — nothing here "+
      "can grant those for you.\n\nTurn it on?")){
     e.target.checked=false}};
   body.querySelectorAll('input[name=automode]').forEach(r=>r.onchange=()=>{
    if(r.value==='full'&&!confirm(
      "Full computer access lets Orbit run shell commands, write anywhere on this Mac, and "+
      "reach the cluster without asking first — for the rest of this session, across every chat.\n\n"+
      "It still always asks before: sudo, shutting down, the keychain, publishing a package, "+
      "rewriting git history, force-pushing, or destructive SQL. It will never wipe a disk, run a "+
      "fork bomb, open a reverse shell, pipe a download into a shell, kill every process, or touch "+
      "a protected path like your home directory — no mode lifts those.\n\nTurn it on?")){
     render('tools');return}
    draft.autonomy_mode=r.value;render('tools')});
   const tg=$('#tg');
   const groups={'built-in':[],'paperfetch':[],'zotero':[],'other MCP':[]};
   names.forEach(n=>{
    if(n.startsWith('paperfetch_'))groups['paperfetch'].push(n);
    else if(n.startsWith('zotero_'))groups['zotero'].push(n);
    else if((info.all_tools||[]).includes(n)&&!n.includes('_'))groups['built-in'].push(n);
    else if(['web_search','fetch_url','read_file','write_file','run_shell','fetch_paper_pdf',
             'search_knowledge','use_skill','list_skills','check_citations','list_dir',
             'grep_files','http_json','pubmed_search','arabidopsis_gene','sequence',
             'cluster_status','cluster_ls','cluster_read','cluster_run','cluster_submit',
             'cluster_qdel','alphafold','uniprot','ncbi','remember','python',
             'screen_look','screen_click','screen_move','screen_drag','screen_type',
             'screen_key','screen_scroll'].includes(n))
      groups['built-in'].push(n);
    else groups['other MCP'].push(n)});
   Object.entries(groups).forEach(([g,list])=>{
    if(!list.length)return;
    tg.appendChild(el(`<div class=grp>${g} (${list.length})</div>`));
    list.forEach(n=>{const l=document.createElement('label');
     const c=document.createElement('input');c.type='checkbox';c.dataset.tool=n;
     c.checked=en[n]!==false;
     if(!c.checked)l.classList.add('off');
     c.onchange=()=>l.classList.toggle('off',!c.checked);
     l.appendChild(c);
     const sp=document.createElement('span');sp.textContent=n;l.appendChild(sp);tg.appendChild(l)})})
  }
  if(name==='memory'&&(MODELS.harness_mode||isClaudeChat())&&!MEM_ORBIT){
   await renderClaudeMemory(body,()=>{MEM_ORBIT=true;render('memory')});
  }
  else if(name==='memory'){
   MEM_ORBIT=false;
   body.innerHTML=`${MODELS.harness_mode?`<div class=note style="margin-bottom:8px">Orbit's own instructions and memory: used by chats that do not run through Claude Code. <a style="cursor:pointer;color:var(--acc)" id=m_toclaude>Claude Code's →</a></div>`:''}${MODELS.codex_mode&&!MODELS.harness_mode?`<div class=note style="margin-bottom:8px">Orbit's own instructions and memory. Codex chats read Codex's AGENTS.md (and, if you keep it on, Orbit's standing instructions below): <a style="cursor:pointer;color:var(--acc)" id=m_tocodex>Codex's instructions →</a></div>`:''}
    <div class=sec>General instructions <small>— always prepended, like a CLAUDE.md</small></div>
    <textarea class=ta id=m_ins placeholder="e.g. I'm a biology grad student. Prefer concise answers with citations. Always give exact gene IDs."></textarea>
    <div class=sec>Memories <small>— durable facts, injected into every chat</small></div>
    <div id=memlist></div>
    <div class=grid style="margin-top:10px"><label>New memory name</label>
     <input type=text id=m_name placeholder="lab-context"></div>
    <textarea class=ta id=m_text style="min-height:110px;margin-top:8px" placeholder="What should Orbit always know?"></textarea>
    <button class=ghost id=m_add style="margin-top:8px">Add memory</button>`;
   $('#m_ins').value=ins;
   if($('#m_toclaude'))$('#m_toclaude').onclick=()=>render('memory');
   if($('#m_tocodex'))$('#m_tocodex').onclick=()=>tabs('codex');
   const ml=$('#memlist');
   if(!mem.length)ml.innerHTML='<div class=note>No memories yet.</div>';
   mem.forEach(m=>{const r=el('<div class=memrow><b></b><span></span><button class=ghost>edit</button><button class=ghost>delete</button></div>');
    r.querySelector('b').textContent=m.name;r.querySelector('span').textContent=m.title;
    const [ed,del]=r.querySelectorAll('button');
    ed.onclick=async()=>{const d=await (await fetch('/api/memory/'+m.name)).json();
     $('#m_name').value=m.name;$('#m_text').value=d.text;$('#m_text').focus()};
    del.onclick=async()=>{await fetch('/api/memory/delete',{method:'POST',
      headers:{'Content-Type':'application/json'},body:JSON.stringify({name:m.name})});openSettings('memory')};
    ml.appendChild(r)});
   $('#m_add').onclick=async()=>{const n=$('#m_name').value.trim(),t=$('#m_text').value.trim();
    if(!n||!t)return;
    await fetch('/api/memory/save',{method:'POST',headers:{'Content-Type':'application/json'},
     body:JSON.stringify({name:n,text:t})});openSettings('memory')};
  }
  if(name==='prompts'){
   body.innerHTML=`<div class=sec>Saved prompts <small>— become slash commands, e.g. /review</small></div>
    <div id=plist></div>
    <div class=grid style="margin-top:10px">
     <label>Command name</label><input type=text id=p_name placeholder="review">
     <label>Description</label><input type=text id=p_desc placeholder="critique a result">
    </div>
    <textarea class=ta id=p_text style="min-height:120px;margin-top:8px" placeholder="The prompt text inserted when you type the command."></textarea>
    <button class=ghost id=p_add style="margin-top:8px">Save prompt</button>`;
   const pl=$('#plist');
   const keys=Object.keys(PROMPTS);
   if(!keys.length)pl.innerHTML='<div class=note>No saved prompts yet.</div>';
   keys.forEach(n=>{const r=el('<div class=memrow><b></b><span></span><button class=ghost>edit</button><button class=ghost>delete</button></div>');
    r.querySelector('b').textContent='/'+n;r.querySelector('span').textContent=PROMPTS[n].desc||'';
    const [ed,del]=r.querySelectorAll('button');
    ed.onclick=()=>{$('#p_name').value=n;$('#p_desc').value=PROMPTS[n].desc||'';$('#p_text').value=PROMPTS[n].text||''};
    del.onclick=async()=>{await fetch('/api/prompts/delete',{method:'POST',
      headers:{'Content-Type':'application/json'},body:JSON.stringify({name:n})});openSettings('prompts')};
    pl.appendChild(r)});
   $('#p_add').onclick=async()=>{const n=$('#p_name').value.trim().replace(/^\//,'');
    if(!n||!$('#p_text').value.trim())return;
    await fetch('/api/prompts/save',{method:'POST',headers:{'Content-Type':'application/json'},
     body:JSON.stringify({name:n,desc:$('#p_desc').value,text:$('#p_text').value})});
    openSettings('prompts')};
  }

  if(name==='knowledge'){
   const docs=await (await fetch('/api/knowledge')).json();
   if(gen!==RENDER_GEN)return;      // you moved to another tab while this loaded
   body.innerHTML=`<div class=sec>Document library <small>— searched by the search_knowledge tool</small></div>
    <div id=klist></div>
    <div style="margin-top:10px;display:flex;gap:8px;align-items:center">
     <button class=ghost id=k_add>Add documents</button>
     <button class=ghost id=k_reindex>Reindex</button>
     <span class=note id=k_note></span></div>
    <input type=file id=k_file multiple hidden>`;
   const kl=$('#klist');
   if(!docs.length)kl.innerHTML='<div class=note>Empty. Add PDFs, docx, markdown, csv — anything readable.</div>';
   docs.forEach(dd=>{const r=el('<div class=memrow><b></b><span></span><button class=ghost>delete</button></div>');
    r.querySelector('b').textContent=dd.name;
    r.querySelector('span').textContent=`${(dd.bytes/1024).toFixed(0)} KB · ${dd.chunks} chunks`;
    r.querySelector('button').onclick=async()=>{
      if(!confirm('Move '+dd.name+' to the recycle bin?'))return;
      if(await apiPost('/api/knowledge/delete',{name:dd.name},'delete'))toast('moved to bin');
      openSettings('knowledge')};
    kl.appendChild(r)});
   $('#k_add').onclick=()=>$('#k_file').click();
   $('#k_file').onchange=async e=>{
    $('#k_note').textContent='indexing...';
    for(const f of [...e.target.files]){const fd=new FormData();fd.append('file',f);
     await fetch('/api/knowledge/upload',{method:'POST',body:fd})}
    openSettings('knowledge')};
   $('#k_reindex').onclick=async()=>{$('#k_note').textContent='reindexing...';
    const r=await (await fetch('/api/knowledge/reindex',{method:'POST'})).json();
    $('#k_note').textContent=`${r.docs} docs · ${r.chunks} chunks`};
  }
  if(name==='agents'){
   const d=await (await fetch('/api/agents')).json();
   if(gen!==RENDER_GEN)return;      // you moved to another tab while this loaded
   const ags=d.agents||{};
   body.innerHTML=`<div class=sec>Agents <small>— a preset instruction set plus a tool subset</small></div>
    <div id=alist></div>
    <div class=grid style="margin-top:10px">
     <label>Name</label><input type=text id=a_name placeholder="paper-reviewer">
     <label>Description</label><input type=text id=a_desc placeholder="critiques methods and stats">
    </div>
    <textarea class=ta id=a_ins style="min-height:120px;margin-top:8px" placeholder="Instructions this agent always follows."></textarea>
    <div class=sec>Tools this agent may use <small>— none checked = all tools</small></div>
    <div class=toolgrid id=a_tools></div>
    <button class=ghost id=a_add style="margin-top:10px">Save agent</button>`;
   const al=$('#alist');
   const keys=Object.keys(ags);
   if(!keys.length)al.innerHTML='<div class=note>No agents yet.</div>';
   keys.forEach(n=>{const r=el('<div class=memrow><b></b><span></span><button class=ghost>edit</button><button class=ghost>delete</button></div>');
    r.querySelector('b').textContent=n;r.querySelector('span').textContent=ags[n].desc||'';
    const [ed,del]=r.querySelectorAll('button');
    ed.onclick=()=>{$('#a_name').value=n;$('#a_desc').value=ags[n].desc||'';
     $('#a_ins').value=ags[n].instructions||'';
     const t=ags[n].tools||[];
     document.querySelectorAll('#a_tools input').forEach(c=>c.checked=t.includes(c.dataset.at))};
    del.onclick=async()=>{await fetch('/api/agents/delete',{method:'POST',
      headers:{'Content-Type':'application/json'},body:JSON.stringify({name:n})});
      openSettings('agents');loadAgents()};
    al.appendChild(r)});
   const at=$('#a_tools');
   (info.all_tools||info.tools||[]).forEach(n=>{const l=document.createElement('label');
    const c=document.createElement('input');c.type='checkbox';c.dataset.at=n;l.appendChild(c);
    const sp=document.createElement('span');sp.textContent=n;l.appendChild(sp);at.appendChild(l)});
   $('#a_add').onclick=async()=>{const n=$('#a_name').value.trim();if(!n)return;
    const tools=[...document.querySelectorAll('#a_tools input')].filter(c=>c.checked).map(c=>c.dataset.at);
    await fetch('/api/agents/save',{method:'POST',headers:{'Content-Type':'application/json'},
     body:JSON.stringify({name:n,desc:$('#a_desc').value,instructions:$('#a_ins').value,tools})});
    openSettings('agents');loadAgents()};
  }

  if(name==='skills'){
   const sk=await (await fetch('/api/skills')).json();
   if(gen!==RENDER_GEN)return;      // you moved to another tab while this loaded
   body.innerHTML=`<div class=sec>Skills <small>— procedures the model loads with use_skill</small></div>
    <div id=sklist></div>
    <div class=grid style="margin-top:10px"><label>Skill name</label>
     <input type=text id=sk_name placeholder="wgbs-qc"></div>
    <textarea class=ta id=sk_text style="min-height:200px;margin-top:8px" placeholder="# WGBS QC&#10;&#10;1. Check conversion rate from the lambda spike-in...&#10;2. ..."></textarea>
    <button class=ghost id=sk_add style="margin-top:8px">Save skill</button>`;
   const sl=$('#sklist');
   if(!sk.length)sl.innerHTML='<div class=note>No skills yet. A skill is a written procedure the model follows exactly.</div>';
   sk.forEach(k=>{const r=el('<div class=memrow><b></b><span></span><button class=ghost>edit</button><button class=ghost>delete</button></div>');
    r.querySelector('b').textContent=k.name;r.querySelector('span').textContent=k.title;
    const [ed,del]=r.querySelectorAll('button');
    ed.onclick=async()=>{const d=await (await fetch('/api/skill/'+k.name)).json();
     $('#sk_name').value=k.name;$('#sk_text').value=d.text};
    del.onclick=async()=>{if(await apiPost('/api/skills/delete',{name:k.name},'deleting the skill'))
      toast(k.name+' is in the bin — restore it from there');openSettings('skills')};
    sl.appendChild(r)});
   $('#sk_add').onclick=async()=>{const n=$('#sk_name').value.trim();
    if(!n||!$('#sk_text').value.trim())return;
    await fetch('/api/skills/save',{method:'POST',headers:{'Content-Type':'application/json'},
     body:JSON.stringify({name:n,text:$('#sk_text').value})});openSettings('skills')};
  }
  if(name==='mcp'){
   body.innerHTML=`<div class=sec>MCP servers <small>— same format as Claude's config</small></div>
    <textarea class=ta id=mcp_json style="min-height:250px"></textarea>
    <div class=note style="margin-top:8px">Saving reconnects every server.</div>
    <div id=mcperr class=err style="margin-top:6px"></div>`;
   $('#mcp_json').value=JSON.stringify(mcp,null,2);
   $('#mcperr').textContent=Object.entries(info.tool_errors||{}).map(([k,v])=>k+': '+v).join(' | ');
  }
  if(name==='codex'){
   body.innerHTML='<div class=note>loading Codex…</div>';
   const cx=await (await fetch('/api/codex/config')).json();
   if(gen!==RENDER_GEN)return;      // you moved to another tab while this loaded
   const c=cx.settings||{},i=cx.info||{},toml=cx.config_toml||{};
   const hostsList=await remoteHosts();
   if(gen!==RENDER_GEN)return;      // you moved to another tab while this loaded
   const rl=i.rate_limits||{};const pct=w=>w&&w.usedPercent!=null?`${Math.max(0,100-w.usedPercent)}% left`:'';
   body.innerHTML=`<div class=note style="margin-bottom:10px">Codex mode runs chats through Codex's own agent — its tools, sandbox, skills, plugins and MCP servers — on your ChatGPT account or any provider in Models &amp; keys. Skills, plugins, MCP servers and AGENTS.md below are Codex's own (<code>~/.codex</code>), so the Codex CLI and app see the same.</div>
    <div class=sec>Codex on this Mac</div><div class=grid>
     <label>Installed</label><div>${i.installed?esc(i.version||'yes'):'no — <code>brew install codex</code>'}</div>
     <label>Your account</label><div>${i.login==='chatgpt'?'signed in with ChatGPT':i.login==='api_key'?'an API key':'not signed in'} <button class=ghost id=cx_login>${i.login?'Sign in again':'Sign in'}…</button></div>
     ${rl.primary||rl.secondary?`<label>ChatGPT limits</label><div>${[pct(rl.primary)&&'5 hours: '+pct(rl.primary),pct(rl.secondary)&&'week: '+pct(rl.secondary)].filter(Boolean).join(' · ')}</div>`:''}
     <label>Codex's own defaults</label><div class=note>${toml.model?'model '+esc(toml.model):''}${toml.model_reasoning_effort?' · effort '+esc(toml.model_reasoning_effort):''} <span>(~/.codex/config.toml — used by the Codex CLI; Orbit chats use the model you pick)</span></div>
    </div>
    <div class=sec>Models</div>
    <div class=note>Your ChatGPT account's models come from Codex's sign-in. Every other provider, key and account is shared with Orbit and Claude Code: <button class=ghost id=cx_tomodels>Settings → Models &amp; keys</button>.</div>
    <div class=sec>Defaults for new Codex chats <small>— each chat can still change its own (model picker, folder chip, mode)</small></div><div class=grid>
     <label>Model</label><select id=cx_dmodel>${modelOptions(MODELS.codex_mode?MODELS.default:'','Codex mode\'s last model',id=>id.startsWith('codex:'))}</select>
     <label>Permission mode</label><select id=cx_mode>${Object.entries(CQ_MODES).map(([k,v])=>`<option value=${k}>${v}</option>`).join('')}</select>
     <div class=hint2>Auto: everyday commands and edits inside the chat's folder run; Orbit's safety check puts anything risky to you and refuses the unrecoverable. Accept edits: commands ask. Plan: read-only. Bypass: no sandbox, no questions.</div>
     <label>Reasoning effort</label><select id=cx_effort><option value="">Codex's own</option><option>minimal</option><option>low</option><option>medium</option><option>high</option><option>xhigh</option></select>
     <label>Runs on</label><select id=cx_host><option value="">This Mac</option>${(hostsList||[]).map(h=>`<option value="${esc(h.host)}">${esc(h.host)}</option>`).join('')}</select>
     <label>Folder on this Mac</label><div style="display:flex;gap:6px"><input type=text id=cx_dir placeholder="Orbit workspace" style="flex:1"><button class=ghost id=cx_dirpick>Choose…</button></div>
     <label>Scheduled runs</label><select id=cx_unatt><option value=auto>Auto — Orbit's safety check decides</option><option value=deny>refuse anything that needs approval</option><option value=allow>allow everything (careful)</option></select>
    </div>
    <div class=sec>Instructions</div><div class=grid>
     <label>Orbit's context</label><div class=sw><input type=checkbox id=cx_octx><span class=note>the project's rules and your standing instructions, as Codex developer instructions</span></div>
     <label>Extra instructions</label><textarea class=ta id=cx_dev style="min-height:50px" placeholder="for every Codex chat Orbit starts"></textarea>
    </div>
    <button class=primary id=cx_save style="margin-top:6px">Save Codex defaults</button> <span class=note id=cx_note></span>
    <div class=sec>AGENTS.md <small>— ${esc(cx.agents_md_path||'~/.codex/AGENTS.md')}, read by Codex everywhere (a folder's own AGENTS.md adds to it)</small></div>
    <textarea class=ta id=cx_agents style="min-height:120px;font-family:var(--mono);font-size:12.5px"></textarea>
    <button class=ghost id=cx_agentsave>Save AGENTS.md</button> <span class=note id=cx_agentnote></span>
    <div class=sec>Machines over SSH <small>— Codex chats can run on them too</small></div><div id=cx_hosts></div>
    <div class=grid style="margin-top:6px">
     <label>Install there</label><div class=sw><input type=checkbox id=cx_rinst><span class=note>install (or upgrade) Codex on a machine when a chat needs it — the official Linux build of this Mac's version, in ~/.local/bin</span></div>
     <label>Keep running</label><div style="display:flex;gap:6px;align-items:center"><input type=number id=cx_keep min=1 max=1440 style="width:80px"><span class=note>minutes idle, then Codex there is closed (login nodes limit processes)</span></div>
    </div>
    <div class=sec>Skills <small>— ~/.codex/skills</small></div>
    <div style="display:flex;gap:8px;margin-bottom:6px"><input type=text id=cxs_src placeholder="install from git URL, owner/repo or folder" style="flex:1"><button class=ghost id=cxs_inst>Install</button></div>
    <div id=cxs_list class=cqskills></div><div class=note id=cxs_note></div>
    <div class=sec>Plugins <small>— codex plugin</small></div><div id=cxp_list></div>
    <div style="display:flex;gap:8px;margin-top:6px"><input type=text id=cxp_name placeholder="plugin@marketplace" style="flex:1"><button class=ghost id=cxp_add>Install</button>
     <input type=text id=cxm_src placeholder="add marketplace (URL / owner/repo)" style="flex:1"><button class=ghost id=cxm_add>Add</button></div><div class=note id=cxp_note></div>
    <div class=sec>MCP servers <small>— codex mcp</small></div><div id=cxmcp_list></div>
    <div style="display:flex;gap:8px;margin-top:6px"><input type=text id=cxmcp_name placeholder="name" style="width:140px"><input type=text id=cxmcp_cmd placeholder="command and arguments, e.g. npx -y @modelcontextprotocol/server-filesystem ~/data" style="flex:1"><button class=ghost id=cxmcp_add>Add</button></div><div class=note id=cxmcp_note></div>`;
   $('#cx_tomodels').onclick=()=>tabs('models');
   $('#cx_login').onclick=async()=>{const r=await apiPost('/api/codex/login',{},'sign in');if(r)toast('Terminal opened — finish signing in there, then reopen this tab')};
   $('#cx_mode').value=c.permission_mode||'auto';$('#cx_effort').value=c.default_effort||'';$('#cx_host').value=c.default_host||'';
   $('#cx_dir').value=c.default_dir||'';$('#cx_unatt').value=c.unattended||'auto';$('#cx_octx').checked=c.orbit_context!==false;
   $('#cx_dev').value=c.developer_instructions||'';$('#cx_rinst').checked=c.remote_install!==false;$('#cx_keep').value=c.remote_keep_alive_min||30;
   $('#cx_dirpick').onclick=async()=>{const r=await apiPost('/api/pick_folder',{start:$('#cx_dir').value||'~',prompt:'Folder for new Codex chats'},'folder');if(r&&r.path)$('#cx_dir').value=r.path};
   const saveCx=async(extra)=>{const r=await apiPost('/api/codex/settings',{settings:{permission_mode:$('#cx_mode').value,default_effort:$('#cx_effort').value,
     default_host:$('#cx_host').value,default_dir:$('#cx_dir').value.trim(),unattended:$('#cx_unatt').value,orbit_context:$('#cx_octx').checked,
     developer_instructions:$('#cx_dev').value,remote_install:$('#cx_rinst').checked,remote_keep_alive_min:+$('#cx_keep').value||30,...(extra||{})}},'Codex settings');
    if(r)$('#cx_note').textContent='saved';return r};
   $('#cx_save').onclick=async()=>{await saveCx();const m=$('#cx_dmodel').value;
    if(m&&MODELS.codex_mode){await apiPost('/api/model/default',{id:m},'default model');MODELS.default=m}
    else if(m){await apiPost('/api/settings',{settings:{codex_default:m}},'default model')}};
   ['cx_rinst','cx_keep'].forEach(id=>$('#'+id).onchange=()=>saveCx());
   $('#cx_agents').value=cx.agents_md||'';
   $('#cx_agentsave').onclick=async()=>{const r=await apiPost('/api/codex/agents_md',{text:$('#cx_agents').value},'AGENTS.md');if(r)$('#cx_agentnote').textContent='saved (the previous version is backed up)'};
   // hosts
   const hb=$('#cx_hosts');
   if(!(hostsList||[]).length)hb.innerHTML='<div class=note>No hosts in ~/.ssh/config.</div>';
   (hostsList||[]).forEach(h=>{const pr=h.probe||{};
    const r=el(`<div class=memrow style="align-items:center;gap:8px"><b style="min-width:120px"></b><span class=note style="flex:1"></span><button class=ghost data-a=inst>Install or check Codex</button><button class=ghost data-a=login>Copy this Mac's sign-in</button></div>`);
    r.querySelector('b').textContent=h.host;
    r.querySelector('.note').textContent=pr.ok?(pr.codex?`Codex ${pr.codex_version||''} · ${pr.codex_login||'not signed in'}`:'no Codex there yet'):(pr.error?'unreachable last time':'not checked yet');
    r.onclick=async ev=>{const a=ev.target.dataset.a;if(!a)return;
     if(a==='inst'){ev.target.textContent='checking…';const x=await apiPost('/api/codex/install',{host:h.host},'install');ev.target.textContent='Install or check Codex';
      if(x)r.querySelector('.note').textContent=`Codex ${x.version||''} at ${x.path}`}
     if(a==='login'){if(!confirm(`Copy your Codex sign-in (this Mac's ~/.codex/auth.json) to ${h.host}? Saved there readable only by your account; administrators of that machine could still read it. Only needed for your ChatGPT account's models.`))return;
      const x=await apiPost('/api/codex/copy_login',{host:h.host},'copy sign-in');if(x)toast('signed in on '+h.host)}};
    hb.appendChild(r)});
   // skills
   const drawSk=list=>{const b=$('#cxs_list');b.innerHTML=list.length?'':'<div class=note>No skills in ~/.codex/skills.</div>';
    list.forEach(x=>{const r=el('<div class=r><div style="flex:1"><b></b><small></small></div><button class=ghost style="font-size:11px">remove</button></div>');
     r.querySelector('b').textContent=x.name;r.querySelector('small').textContent=x.description||'';
     r.querySelector('button').onclick=async()=>{if(!confirm('Move the Codex skill '+x.name+' to the Trash?'))return;
      const d=await apiPost('/api/codex/manage',{kind:'skills',op:'remove',name:x.dir},'remove skill');if(d)r.remove()};b.appendChild(r)})};
   drawSk(cx.skills||[]);
   $('#cxs_inst').onclick=async()=>{const src=$('#cxs_src').value.trim();if(!src)return;$('#cxs_note').textContent='installing…';
    const d=await apiPost('/api/codex/manage',{kind:'skills',op:'install',source:src},'install skill');
    if(d){$('#cxs_note').textContent='installed: '+(d.installed||[]).join(', ');drawSk((await (await fetch('/api/codex/config')).json()).skills||[])}};
   // plugins
   const pl=(cx.plugins&&cx.plugins.installed)||[];
   $('#cxp_list').innerHTML=cx.plugins_error?`<div class=note>${esc(cx.plugins_error)}</div>`:(pl.length?'':'<div class=note>No plugins installed.</div>');
   pl.forEach(x=>{const r=el(`<div class=memrow style="align-items:center"><b style="flex:1"></b><span class=note></span><button class=ghost>remove</button></div>`);
    r.querySelector('b').textContent=x.pluginId||x.name;r.querySelector('.note').textContent=(x.enabled?'on':'off')+(x.version?' · '+x.version:'');
    r.querySelector('button').onclick=async()=>{if(!confirm('Remove the Codex plugin '+(x.pluginId||x.name)+'?'))return;
     const d=await apiPost('/api/codex/manage',{kind:'plugins',op:'remove',name:x.pluginId||x.name},'remove plugin');if(d)r.remove()};
    $('#cxp_list').appendChild(r)});
   $('#cxp_add').onclick=async()=>{const n=$('#cxp_name').value.trim();if(!n)return;$('#cxp_note').textContent='installing…';
    const d=await apiPost('/api/codex/manage',{kind:'plugins',op:'add',name:n},'install plugin');$('#cxp_note').textContent=d?'installed — reopen the tab to see it':''};
   $('#cxm_add').onclick=async()=>{const n=$('#cxm_src').value.trim();if(!n)return;
    const d=await apiPost('/api/codex/manage',{kind:'plugins',op:'marketplace',name:n},'add marketplace');$('#cxp_note').textContent=d?'marketplace added':''};
   // MCP
   const ml=Array.isArray(cx.mcp)?cx.mcp:[];
   $('#cxmcp_list').innerHTML=cx.mcp_error?`<div class=note>${esc(cx.mcp_error)}</div>`:(ml.length?'':'<div class=note>No MCP servers.</div>');
   ml.forEach(x=>{const r=el(`<div class=memrow style="align-items:center"><b style="min-width:140px"></b><span class=note style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"></span><button class=ghost>remove</button></div>`);
    r.querySelector('b').textContent=x.name;const t=x.transport||{};
    r.querySelector('.note').textContent=(x.enabled===false?'off · ':'')+(t.command?[t.command,...(t.args||[])].join(' '):(t.url||t.type||''));
    r.querySelector('button').onclick=async()=>{if(!confirm('Remove the Codex MCP server '+x.name+'?'))return;
     const d=await apiPost('/api/codex/manage',{kind:'mcp',op:'remove',name:x.name},'remove MCP server');if(d)r.remove()};
    $('#cxmcp_list').appendChild(r)});
   $('#cxmcp_add').onclick=async()=>{const n=$('#cxmcp_name').value.trim(),cmd=$('#cxmcp_cmd').value.trim();if(!n||!cmd)return;
    const d=await apiPost('/api/codex/manage',{kind:'mcp',op:'add',name:n,command:cmd.match(/"[^"]*"|\S+/g).map(x=>x.replace(/^"|"$/g,''))},'add MCP server');
    if(d)$('#cxmcp_note').textContent='added — reopen the tab to see it'};
   return}
  if(name==='claude'){
   const [d,cc]=await Promise.all([(await fetch('/api/claude/info?sid='+encodeURIComponent(sid||''))).json(),
                                  (await fetch('/api/claude/config')).json()]);
   if(gen!==RENDER_GEN)return;      // you moved to another tab while this loaded
   const c=d.settings||{}, us=cc.user||{}, perm=us.permissions||{};
   const known=d.mcp_known||[];
   const lines=a=>(a||[]).join('\n'), unlines=v=>v.split('\n').map(x=>x.trim()).filter(Boolean);
   body.innerHTML=`<div class=note style="margin-bottom:10px">Claude Code · local Qwen is <b>claude-qwen</b> in a window: the same command, your Claude setup as it is.
     Changes to skills, plugins, MCP servers and permissions below are made to Claude itself (<code>${esc(cc.paths&&cc.paths.user||'')}</code>), so the terminal sees them too.</div>
    <div class=sec>Models</div>
    <div class=note>Providers, accounts and keys are shared with Orbit's own chat, on one page: <button class=ghost id=cc_tomodels>Settings → Models &amp; keys</button>. Every model there runs through Claude Code in Claude Code mode — including <b>Claude · your subscription</b>, plain Claude Code on your own login with no API key.</div>
    <div class=sec>Remote machines (SSH) <small>— chats that run Claude Code on another machine</small></div>
    <div id=cc_remote class=note>loading…</div>
    <div class=sec>Permissions <small>— Claude's settings</small></div><div class=grid>
    <label>Default mode</label><select id=cc_mode><option value="">default (ask)</option>${Object.entries(CQ_MODES).filter(([k])=>k!=='default').map(([k,v])=>`<option value=${k}>${v}</option>`).join('')}</select>
    <label>Allow</label><textarea class=ta id=cc_allow style="min-height:60px" placeholder="one rule per line, e.g. Bash(git diff:*)"></textarea>
    <label>Ask</label><textarea class=ta id=cc_ask style="min-height:40px"></textarea>
    <label>Deny</label><textarea class=ta id=cc_deny style="min-height:40px"></textarea>
    <label>Extra folders</label><textarea class=ta id=cc_dirs style="min-height:40px" placeholder="additionalDirectories, one per line"></textarea>
    <label>Hooks</label><div class=sw><input type=checkbox id=cc_hooks><span class=note>run the hooks in your Claude settings (disableAllHooks off)</span></div>
    </div><button class=primary id=cc_save>Save to Claude's settings</button> <span class=note id=cc_note></span>

    <div class=sec>Skills <small>— ~/.claude/skills</small></div>
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:6px"><input type=text id=sk_find placeholder="filter" style="max-width:200px">
     <input type=text id=sk_src placeholder="install from git URL, owner/repo or folder" style="flex:1;min-width:220px"><button class=ghost id=sk_inst>Install</button></div>
    <div class=note id=sk_note></div><div class=cqskills id=sk_list></div>

    <div class=sec>Plugins</div><div id=pl_list class=note>loading…</div>
    <div style="display:flex;gap:8px;margin-top:6px"><input type=text id=pl_name placeholder="plugin@marketplace" style="flex:1"><button class=ghost id=pl_inst>Install</button>
     <input type=text id=mk_src placeholder="add marketplace (URL / owner/repo)" style="flex:1"><button class=ghost id=mk_add>Add</button></div>
    <div class=note id=pl_note></div>

    <div class=sec>MCP servers <small>— claude mcp</small></div><div id=mcp_list class=note>checking…</div>

    <div class=sec>Defaults for new chats <small>— each chat can still change its own (model picker, folder chip, mode switch)</small></div><div class=grid>
    <label>Model</label><select id=cq_dmodel>${modelOptions(MODELS.default||'','',id=>id.startsWith('harness:')||id.startsWith('claude-qwen'))}</select>
    <label>Permission mode</label><select id=cq_mode><option value="">Claude's own (its settings' defaultMode)</option>${Object.entries(CQ_MODES).map(([k,v])=>`<option value=${k}>${v}</option>`).join('')}</select>
    <div class=hint2>Auto: Claude decides which actions are safe to run without asking, and asks for the rest.</div>
    <label>Reasoning effort</label><select id=cq_deffort><option value="">Claude's own</option><option>low</option><option>medium</option><option>high</option><option>xhigh</option><option>max</option></select>
    <label>Runs on</label><select id=cq_dhost><option value="">This Mac</option></select>
    <label>Folder on this Mac</label><div style="display:flex;gap:6px"><input type=text id=cq_ddir placeholder="Orbit workspace" style="flex:1"><button class=ghost id=cq_ddirpick>Choose…</button></div>
    <div class=hint2>On another machine new chats start in that host's folder (Remote machines below), else your first bookmark there, else home.</div>
    </div>
    <div class=sec>claude-qwen launcher <small>— for the terminal command and Orbit alike</small></div><div class=grid>
    <label>Profile</label><select id=cq_profile><option value=standard>standard — Claude as you have it set up</option>
      <option value=lean>lean — built-in tools and skills only</option></select>
    <label>On a local model</label><select id=cq_lprof><option value=lean>lean — plugins, their servers and hooks left out</option>
      <option value="">the same profile as everything else</option></select>
    <div class=hint2>A model on this Mac pays for the system prompt in seconds. Measured here: the
     standard profile sent Claude Code 40k tokens of plugins, MCP servers and hooks and a single
     file read took 179s; lean sent 10k and took 44s, for the same answer.</div>
    <label>MCP servers loaded</label><div id=cq_mcp><div class=hint2 style="margin:0 0 4px">Keep “all of them” unless you need a short prompt: a shorter list also leaves out the servers your plugins bring, while their hooks still run (context-mode, for one, then sends web fetches to tools that are not loaded).</div>${known.map(n=>`<label style="display:inline-flex;gap:4px;margin-right:10px"><input type=checkbox value="${esc(n)}"> ${esc(n)}</label>`).join('')}
      <label style="display:inline-flex;gap:4px"><input type=checkbox value="*"> all of them</label></div>
    <label>Tools turned off</label><input type=text id=cq_dis>
    <div class=hint2>WebSearch needs Anthropic's servers and cannot work on a local model.</div>
    </div>

    <div class=sec>In Orbit</div><div class=grid>
    <label>Unattended runs</label><select id=cq_unatt><option value="">same as the chat</option>
      <option value=acceptEdits>accept file edits</option><option value=dontAsk>don't ask (Claude's rules only)</option>
      <option value=bypassPermissions>bypass — allow everything</option></select>
    <label>"Don't ask again" saves to</label><select id=cq_dest><option value=suggested>where Claude suggests</option>
      <option value=localSettings>the folder's .claude/settings.local.json</option><option value=projectSettings>the folder's .claude/settings.json</option>
      <option value=userSettings>~/.claude/settings.json</option><option value=session>this session only</option></select>
    <label>Terminal sessions</label><div class=sw><input type=checkbox id=cq_hist><span class=note>list claude-qwen sessions in the sidebar</span></div>
    <label>…on any model</label><div class=sw><input type=checkbox id=cq_histall><span class=note>also Claude sessions on other models (always, in Claude Code mode)</span></div>
    </div>
    <details style="margin-top:8px"><summary class=note>Orbit extras — each adds something Claude itself would not do (all off)</summary><div class=grid style="margin-top:6px">
    <label>Orbit's safety rules</label><div class=sw><input type=checkbox id=cq_orules><span class=note>Orbit's rules, autonomy mode and folder limit on top of Claude's</span></div>
    <label>Next-message suggestions</label><div class=sw><input type=checkbox id=cq_sugg><span class=note>after each answer Claude Code may suggest what to say next (a small extra call; offered above the box, Tab to use it)</span></div>
    <label>Orbit's tools</label><div class=sw><input type=checkbox id=cq_otools><span class=note>memory, chat search, scheduling, web search</span></div>
    <label>Project tools</label><div class=sw><input type=checkbox id=cq_ptools><span class=note>a trusted project's own .orbit/tools</span></div>
    <label>Skill routing</label><div class=sw><input type=checkbox id=cq_route><span class=note>offer only the skills that match each chat</span></div>
    <label>Always-offered skills</label><input type=text id=cq_core>
    <label>Skill hints</label><div class=sw><input type=checkbox id=cq_hint><span class=note>name matching skills in the message</span></div>
    <label>Orbit's skills</label><div class=sw><input type=checkbox id=cq_oskills><span class=note>Orbit's saved skills as a plugin</span></div>
    <label>Orbit's context</label><div class=sw><input type=checkbox id=cq_octx><span class=note>Orbit's project rules and instructions in the prompt</span></div>
    <label>Message times</label><div class=sw><input type=checkbox id=cq_time><span class=note>prefix each message with when it was sent</span></div>
    <label>Extra instructions</label><textarea class=ta id=cq_append style="min-height:50px"></textarea>
    </div></details>
    <button class=primary id=cq_save style="margin-top:8px">Save defaults and options</button> <span class=note id=cq_note></span>`;
   $('#cc_tomodels').onclick=()=>tabs('models');
   renderRemoteHosts($('#cc_remote'));
   // permissions
   $('#cc_mode').value=perm.defaultMode&&perm.defaultMode!=='default'?perm.defaultMode:'';
   $('#cc_allow').value=lines(perm.allow);$('#cc_ask').value=lines(perm.ask);$('#cc_deny').value=lines(perm.deny);
   $('#cc_dirs').value=lines(perm.additionalDirectories);$('#cc_hooks').checked=!us.disableAllHooks;
   $('#cc_save').onclick=async()=>{
    const r=await apiPost('/api/claude/claude_settings',{patch:{permissions:{defaultMode:$('#cc_mode').value||null,
      allow:unlines($('#cc_allow').value),ask:unlines($('#cc_ask').value),deny:unlines($('#cc_deny').value),
      additionalDirectories:unlines($('#cc_dirs').value)},disableAllHooks:$('#cc_hooks').checked?null:true}},'Claude settings');
    if(r)$('#cc_note').textContent='saved to Claude — applies to its next session'};
   // skills
   let SK=cc.skills||[];
   const drawSkills=()=>{const f=$('#sk_find').value.toLowerCase(),box=$('#sk_list');box.innerHTML='';
    const shown=SK.filter(x=>!f||x.name.toLowerCase().includes(f)||(x.description||'').toLowerCase().includes(f));
    $('#sk_note').textContent=`${SK.length} skills · ${SK.filter(x=>!x.enabled).length} turned off`+(shown.length<SK.length?` · ${shown.length} shown`:'');
    shown.slice(0,300).forEach(x=>{const r=el('<div class=r><input type=checkbox><div style="flex:1"><b></b><small></small></div><button class=ghost style="font-size:11px">remove</button></div>');
     const cb=r.querySelector('input');cb.checked=x.enabled;r.querySelector('b').textContent=x.name;
     r.querySelector('small').textContent=(x.description||'').slice(0,220);
     cb.onchange=async()=>{const d=await apiPost('/api/claude/skills',{op:'toggle',name:x.name,on:cb.checked},'skill');if(d){x.enabled=cb.checked;drawSkills()}};
     r.querySelector('button').onclick=async()=>{if(!confirm('Move the skill '+x.name+' to the Trash?'))return;
      const d=await apiPost('/api/claude/skills',{op:'remove',name:x.name},'remove skill');if(d){SK=SK.filter(y=>y!==x);drawSkills()}};
     box.appendChild(r)});
    if(shown.length>300)box.appendChild(el(`<div class=note>… ${shown.length-300} more — filter to find them</div>`))};
   $('#sk_find').oninput=drawSkills;drawSkills();
   $('#sk_inst').onclick=async()=>{const src=$('#sk_src').value.trim();if(!src)return;$('#sk_note').textContent='installing…';
    const d=await apiPost('/api/claude/skills',{op:'install',source:src},'install skill');
    if(d){$('#sk_note').textContent='installed: '+(d.installed||[]).join(', ')+((d.skipped||[]).length?' · already there: '+d.skipped.join(', '):'');
     SK=(await (await fetch('/api/claude/config')).json()).skills||SK;drawSkills()}};
   // plugins
   const drawPlugins=async()=>{const pd=await (await fetch('/api/claude/plugins')).json(),box=$('#pl_list');if(!box)return;box.innerHTML='';
    (pd.plugins||[]).forEach(p=>{const r=el('<div class=memrow><input type=checkbox><b></b><span></span><button class=ghost>update</button><button class=ghost>uninstall</button></div>');
     const [up,un]=r.querySelectorAll('button');
     r.querySelector('input').checked=!!p.enabled;r.querySelector('b').textContent=p.id;r.querySelector('span').textContent=(p.version||'')+' · '+(p.scope||'');
     const act=async op=>{$('#pl_note').textContent=op+'…';const d=await apiPost('/api/claude/plugins',{op,name:p.id},op);
      $('#pl_note').textContent=d?(d.output||op+' done'):'';drawPlugins()};
     r.querySelector('input').onchange=e=>act(e.target.checked?'enable':'disable');up.onclick=()=>act('update');
     un.onclick=()=>{if(confirm('Uninstall '+p.id+'?'))act('uninstall')};box.appendChild(r)});
    if(!(pd.plugins||[]).length)box.textContent=pd.error||'no plugins installed'};
   drawPlugins();
   $('#pl_inst').onclick=async()=>{const n=$('#pl_name').value.trim();if(!n)return;$('#pl_note').textContent='installing…';
    const d=await apiPost('/api/claude/plugins',{op:'install',name:n},'install plugin');$('#pl_note').textContent=d?d.output:'';drawPlugins()};
   $('#mk_add').onclick=async()=>{const n=$('#mk_src').value.trim();if(!n)return;$('#pl_note').textContent='adding…';
    const d=await apiPost('/api/claude/plugins',{op:'marketplace_add',name:n},'add marketplace');$('#pl_note').textContent=d?d.output:''};
   // MCP
   (async()=>{const md=await (await fetch('/api/claude/mcp')).json(),box=$('#mcp_list');if(!box)return;box.innerHTML='';
    (md.servers||[]).forEach(m=>{const r=el('<div class=memrow><b></b><span></span><button class=ghost>remove</button></div>');
     r.querySelector('b').textContent=m.name;r.querySelector('span').textContent=m.status+' · '+m.target;
     r.querySelector('button').onclick=async()=>{if(!confirm('Remove the MCP server '+m.name+' from Claude?'))return;
      const d=await apiPost('/api/claude/mcp',{op:'remove',name:m.name},'remove MCP server');if(d)r.remove()};
     box.appendChild(r)});
    if(!(md.servers||[]).length)box.textContent=md.error||'none';
    box.appendChild(el('<div class=hint2>Add servers with <code>claude mcp add</code> in a terminal, or ask Claude to.</div>'))})();
   // launcher + Orbit options
   $('#cq_profile').value=c.profile==='lean'?'lean':'standard';
   $('#cq_lprof').value=c.local_profile==='lean'?'lean':'';$('#cq_mode').value=c.permission_mode||'';
   $('#cq_unatt').value=c.unattended_mode||'';$('#cq_dest').value=c.rule_destination||'suggested';
   $('#cq_hist').checked=c.history!==false;$('#cq_histall').checked=!!c.history_all_models;
   $('#cq_dis').value=(c.disallowed_tools||[]).join(', ');
   $('#cq_orules').checked=!!c.orbit_rules;$('#cq_sugg').checked=!!c.prompt_suggestions;$('#cq_otools').checked=!!c.orbit_tools;$('#cq_ptools').checked=!!c.project_tools;
   $('#cq_route').checked=!!c.skill_routing;$('#cq_core').value=(c.core_skills||[]).join(', ');$('#cq_hint').checked=!!c.skill_hint;
   $('#cq_oskills').checked=!!c.orbit_skills;$('#cq_octx').checked=!!c.orbit_context;$('#cq_time').checked=!!c.message_time;
   $('#cq_append').value=c.append_system||'';
   $('#cq_deffort').value=c.default_effort||'';$('#cq_ddir').value=c.default_dir||'';
   remoteHosts().then(hs=>{const sel=$('#cq_dhost');if(!sel)return;
    hs.forEach(h=>sel.appendChild(el(`<option value="${esc(h.host)}">${esc(h.host)} (SSH)</option>`)));sel.value=c.default_host||''});
   $('#cq_ddirpick').onclick=async()=>{const p=await pickFolder($('#cq_ddir').value.trim(),'Folder new chats start in');if(p)$('#cq_ddir').value=p};
   body.querySelectorAll('#cq_mcp input').forEach(x=>x.checked=(c.mcp_servers||[]).includes(x.value));
   const list=v=>v.split(',').map(x=>x.trim()).filter(Boolean);
   $('#cq_save').onclick=async()=>{
    const dm=$('#cq_dmodel').value;
    if(dm&&dm!==(MODELS.default||''))await apiPost('/api/model/default',{id:dm},'default model');
    const r=await apiPost('/api/claude/settings',{settings:{profile:$('#cq_profile').value,
     local_profile:$('#cq_lprof').value,permission_mode:$('#cq_mode').value,
     default_effort:$('#cq_deffort').value,default_host:$('#cq_dhost').value,default_dir:$('#cq_ddir').value.trim(),
     unattended_mode:$('#cq_unatt').value,rule_destination:$('#cq_dest').value,history:$('#cq_hist').checked,
     history_all_models:$('#cq_histall').checked,disallowed_tools:list($('#cq_dis').value),
     mcp_servers:[...body.querySelectorAll('#cq_mcp input')].filter(x=>x.checked).map(x=>x.value),
     orbit_rules:$('#cq_orules').checked,prompt_suggestions:$('#cq_sugg').checked,orbit_tools:$('#cq_otools').checked,project_tools:$('#cq_ptools').checked,
     skill_routing:$('#cq_route').checked,core_skills:list($('#cq_core').value),skill_hint:$('#cq_hint').checked,
     orbit_skills:$('#cq_oskills').checked,orbit_context:$('#cq_octx').checked,message_time:$('#cq_time').checked,
     append_system:$('#cq_append').value}},'Claude Code options');
    if(r){$('#cq_note').textContent='saved — applies from the next message (and the next claude-qwen)';drawClaudeBar()}};
   return}
  if(name==='servers'){
   body.innerHTML='<div class=hint2 style="margin:0 0 12px">Models that run on a GPU of a cluster: start and stop them, set when they run, and get an e-mail when one is up.</div><div id=srvconn></div><div id=srvbox>loading…</div>';
   await drawServers(gen);
  }
  if(name==='status'){
   const s=info.status||{};
   const dts=(s.last&&s.last.decode_tok_s)||0;
   body.innerHTML=`<div class=stat>
     <div><b>${s.running?'running':'stopped'}</b><small>server</small></div>
     <div><b>${s.memory_gb||'?'} GB</b><small>model memory</small></div>
     <div><b>${dts?dts.toFixed(0):'?'}</b><small>decode tok/s</small></div>
     <div><b>${s.context_used||0}</b><small>context used</small></div>
    </div>
    <div class=sec>Launch flags</div>
    <pre style="background:var(--panel);padding:11px;border-radius:9px;overflow-x:auto;font-size:12px">${esc(JSON.stringify(s.flags||{},null,1))}</pre>
    <div class=sec>System prompt actually sent</div>
    <pre style="background:var(--panel);padding:11px;border-radius:9px;overflow-x:auto;font-size:12px;white-space:pre-wrap" id=syspre>loading...</pre>`;
   fetch('/api/system_preview',{method:'POST'}).then(r=>r.json()).then(d=>{const p=$('#syspre');if(p)p.textContent=d.text});
  }
 }
 function collect(){
  const num=v=>v===''||v==null?null:Number(v);
  if($('#g_think')){draft.thinking=$('#g_think').checked;draft.show_thinking=$('#g_show').checked;
   draft.reasoning_effort=$('#g_eff').value;draft.max_tool_rounds=Number($('#g_rounds').value)||0;
   draft.max_turn_minutes=Number($('#g_mins').value)||0;
   draft.long_run_notice_min=Number($('#g_notice').value)||0;
   draft.autocompact_pct=Number($('#g_ac').value);
   draft.helper_model=$('#g_helper')?$('#g_helper').value:(draft.helper_model||'');
   // its own id: g_review is the auto-review checkbox, and sharing it meant $() found
   // the select, so that switch could never be ticked and every save cleared it
   draft.review_model=$('#g_reviewer')?$('#g_reviewer').value:(draft.review_model||'');
   draft.auto_review=$('#g_review')?$('#g_review').value:(draft.auto_review||'');
   if($('#g_goaloffer')){draft.goal_offers=$('#g_goaloffer').checked;draft.goal_offer_wait_s=Math.max(0,Number($('#g_goalwait').value)||0)}
   draft.verify_turns=($('#g_verify')&&$('#g_verify').checked)?'tools':'';draft.trash_days=Number($('#g_td').value)||30;
   draft.system_prompt=$('#g_sys').value;draft.use_instructions=$('#g_useins').checked;
   draft.use_memory=$('#g_usemem').checked;
   draft.sampling={temperature:num($('#s_temp').value),top_p:num($('#s_top_p').value),
    top_k:num($('#s_top_k').value),presence_penalty:num($('#s_pres').value)}}
  if($('#v_ctx')){draft.server=Object.assign(draft.server||{},{
   context_window:Number($('#v_ctx').value),kv_quant:$('#v_kv').value,fan_mode:$('#v_fan').value,
   thermal_poll:$('#v_therm').checked,depth:Number($('#v_depth').value),
   prefill_chunk_tokens:Number($('#v_pre').value),reasoning:$('#v_reason').value,
   scheduler_mode:$('#v_sched').value});draft.idle_min=Number($('#v_idle').value)}
  if($('#p_ntfy')){draft.push_ntfy_url=$('#p_ntfy').value.trim();draft.push_private=$('#p_priv').checked}
  if($('#t_shell')){draft.shell_enabled=$('#t_shell').checked;draft.write_any=$('#t_wany').checked;
   draft.code_execution=$('#t_code').checked;draft.cluster_write=$('#t_h2').checked;
   draft.computer_use_enabled=$('#t_screen').checked;
   draft.delegation={...(draft.delegation||{}),enabled:$('#t_deleg').checked,subagents:$('#t_deleg_sub').checked,allow_changes:$('#t_deleg_wr').checked,eagerness:$('#t_deleg_eager').value,escalate:$('#t_deleg_esc').checked};
   const am=document.querySelector('input[name=automode]:checked');
   if(am)draft.autonomy_mode=am.value;
   const en={};document.querySelectorAll('[data-tool]').forEach(c=>{en[c.dataset.tool]=c.checked});
   draft.tools_enabled=en;
   draft.easy_mode=$('#t_easy').checked;
   const keep=[...document.querySelectorAll('[data-easy]')].filter(c=>c.checked).map(c=>c.dataset.easy);
   if(keep.length)draft.easy_tools=keep;
   }
 }
 async function save(){
  collect();
  // Claude Code's own list lives in its settings, not Orbit's
  const ckeep=[...document.querySelectorAll('[data-ceasy]')].filter(c=>c.checked).map(c=>c.dataset.ceasy);
  const mkeep=[...document.querySelectorAll('[data-mcpeasy]')].map(c=>c.checked?c.dataset.mcpeasy:null).filter(Boolean);
  if(ckeep.length||document.querySelector('[data-mcpeasy]')){
   const st={};
   if(ckeep.length)st.easy_tools=ckeep;
   if(document.querySelector('[data-mcpeasy]'))st.easy_mcp=mkeep;   // none ticked = none started
   await apiPost('/api/claude/settings',{settings:st},'saving Claude Code easy mode')}
  keepText();
  if(editIns!=null&&editIns!==ins){await fetch('/api/instructions',{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify({text:editIns})})}
  if(editMcp!=null&&editMcp!==JSON.stringify(mcp,null,2)){try{const cfg=JSON.parse(editMcp);
    const r=await (await fetch('/api/mcp/save',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({config:cfg})})).json();
    if($('#mcperr'))$('#mcperr').textContent=Object.entries(r.tool_errors||{}).map(([k,v])=>k+': '+v).join(' | ');
   }catch(e){if($('#mcperr'))$('#mcperr').textContent='invalid JSON: '+e;return false}}
  const changed={};
  Object.keys(draft).forEach(k=>{if(JSON.stringify(draft[k])!==JSON.stringify(orig[k]))changed[k]=draft[k]});
  const r=await (await fetch('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({settings:changed})})).json();
  orig=JSON.parse(JSON.stringify(draft));
  INFO.tools=r.tools;$('#tools').dataset.orbit=r.tools.length+' tools ready';if(!MODELS.harness_mode)$('#tools').textContent=r.tools.length+' tools ready';
  INFO.settings=Object.assign(INFO.settings||{},{easy_mode:!!draft.easy_mode});drawEasyBtn();
  $('#snote').textContent='saved '+new Date().toLocaleTimeString();
  return true}
 $('#savebtn').onclick=async()=>{if(await save())setTimeout(closeModal,400)};
 $('#restartbtn').onclick=async()=>{if(!await save())return;
  $('#snote').textContent='restarting server...';
  const d=await (await fetch('/api/server/restart',{method:'POST'})).json();
  $('#snote').textContent=d.msg;refreshStatus()};
 tabs(tab);
}

async function refreshRunning(){
 if(document.hidden&&!RUNNING.size)return;          // a hidden tab with nothing running has nothing to learn
 try{const r=await (await fetch('/api/running')).json();
  const now=new Set(r.running||[]), wait=new Set(r.waiting||[]);
  const since=r.since||{}, sinceMoved=JSON.stringify(since)!==JSON.stringify(RUN_SINCE);
  const talk=r.talking||{};
  if(JSON.stringify(talk)!==JSON.stringify(TALKING)){TALKING=talk;LIST_SIG=null;renderSessions();
   if(sid&&(talk[sid]||LINKS[sid]&&LINKS[sid].talking_to))loadLinks(sid)}
  if(sinceMoved){RUN_SINCE=since;LIST_SIG=null}
  let changed = sinceMoved || now.size!==RUNNING.size || [...now].some(x=>!RUNNING.has(x))
             || wait.size!==WAITING.size || [...wait].some(x=>!WAITING.has(x));
  RUNNING=now; WAITING=wait;
  syncBusy();                                // Send / Queue always says what the Mac is doing
  if(changed){renderSessions()}              // a chat may have finished elsewhere
  // a chat that started generating is on disk but not yet in our list -- fetch it,
  // otherwise there is no row in the sidebar to click back to
  if([...RUNNING].some(x=>!SESSIONS.find(s=>s.id===x)))loadSessions();
  const badge=$('#runbadge');
  if(badge)badge.textContent=RUNNING.size?`${RUNNING.size} running`:'';
  drawBgChip();
 }catch(e){}}
setInterval(refreshRunning,2000);

// A chat can change under you -- a message sent from the phone, or another
// window. Ask the Mac for a cheap stamp of the open chat every few seconds and
// re-read it when the count moves; join an answer someone else started.
// Carrying a chat on in Claude desktop: the desktop app keeps its own copy of a conversation and does not
// see turns taken in Orbit. The note says where the session lives (id, transcript, folder), how to resume
// it, and what the latest turns were -- paste it into the desktop chat -- or Claude writes a fuller one.
// Crew (bin/crew.py): a builder chat and a reviewer chat, on different models, that keep improving a project in a folder
// round after round -- build, checkpoint in git, review, build again -- until you pause or stop them.
let CREW_TIMER=null;
async function crewApi(body){
 try{const r=await fetch('/api/crew',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const d=await r.json();if(!r.ok){toast(d.error||'failed');return null}return d}catch(e){toast('could not reach Orbit');return null}}
function crewDefaults(){
 const ms=(MODELS.models||[]).filter(m=>m.ready!==false);
 const muse=ms.find(m=>m.id.startsWith('muse-cli:muse-spark'))||ms.find(m=>m.id.startsWith('muse-cli:'));
 const wonder=ms.find(m=>m.id==='harness:meta/muse-wonder-1.0');
 const builder=(muse||wonder||ms[0]||{}).id||'';
 const other=ms.find(m=>m.id.startsWith('harness:claude/')&&m.id!==builder)||wonder||ms.find(m=>m.id!==builder);
 return {builder,reviewer:(other&&other.id!==builder?other:(ms.find(m=>m.id!==builder)||{})).id||''}}
function crewAgo(t){const s=Math.max(0,Date.now()/1000-t);return s<90?'just now':s<5400?Math.round(s/60)+' min ago':s<172800?Math.round(s/3600)+' h ago':Math.round(s/86400)+' days ago'}
// One side of a crew: a list of chats, each a new chat on a model or one you already have.
function crewParties(host,role,initial,mayBeEmpty){
 const rows=[];
 const sessions=(typeof SESSIONS!=='undefined'?SESSIONS:[]).filter(s=>!s.external&&!s.archived&&!s.temp);
 const wrap=el('<div></div>');host.appendChild(wrap);
 const note=el('<div class=note></div>');
 const addRow=(init)=>{
  const r=el('<div style="display:flex;gap:6px;align-items:center;margin:3px 0;flex-wrap:wrap"></div>');
  const kind=el('<select style="width:150px"><option value=model>a new chat on</option><option value=chat>a chat I have</option></select>');
  const pick=el('<select style="flex:1;min-width:170px"></select>');
  const omodel=el('<select style="width:185px" title="which model this chat works on while the crew runs — its own model is put back when the crew stops"></select>');
  omodel.innerHTML=modelOptions('','its own model');
  const oeffort=el('<select style="width:110px" title="how hard this chat thinks while the crew runs"><option value="">default</option><option value=low>low</option><option value=medium>medium</option><option value=high>high</option><option value=xhigh>xhigh</option><option value=max>max</option></select>');
  const fill=()=>{pick.innerHTML=kind.value==='model'?modelOptions((init&&init.model)||'','pick a model'):
    '<option value="">pick a chat</option>'+sessions.map(s=>`<option value="${esc(s.id)}"${init&&init.sid===s.id?' selected':''}>${esc((s.title||s.id).slice(0,70))}</option>`).join('');
    omodel.style.display=kind.value==='chat'?'':'none';
    if(init){if(kind.value==='chat'&&init.model)omodel.value=init.model;if(init.effort)oeffort.value=init.effort;}};
  if(init&&init.sid)kind.value='chat';fill();kind.onchange=()=>{init=null;fill()};
  const rm=el('<button class=ghost title="remove">✕</button>');
  rm.onclick=()=>{rows.splice(rows.indexOf(r),1);r.remove();upd()};
  r.append(kind,pick,omodel,oeffort,rm);
  r._get=()=>{if(!pick.value)return null;
    return kind.value==='model'?{model:pick.value,effort:oeffort.value||null}:{sid:pick.value,model:omodel.value||null,effort:oeffort.value||null}};
  rows.push(r);wrap.appendChild(r);upd()};
 const add=el('<button class=ghost style="margin-top:2px"></button>');add.textContent='+ add another '+role;host.appendChild(add);host.appendChild(note);
 add.onclick=()=>addRow(null);
 function upd(){note.textContent=!rows.length?(mayBeEmpty?'none: the builder\'s own chat reviews its work':'add at least one '+role):
   (role==='builder'&&rows.length>1?'they take turns, round by round':role==='reviewer'&&rows.length>1?'each scores every round; the scores are averaged':'')}
 (initial||[]).forEach(addRow);upd();
 return {get(){const out=[];for(const r of rows){const g=r._get();if(!g)return null;out.push(g)}return out}}}
function crewEdit(r){
 openSheet('Edit '+r.title,(body)=>{
  body.style.padding='12px 18px 16px';
  body.innerHTML=`<div class=sheetnote>The builder reads the new brief straight away if it is mid-answer, otherwise at the start of its next round. It is also saved as <code>CREW_BRIEF.md</code> in the project folder. What it has built stays.</div>
   <div class=grid><label>Brief</label><textarea id=ce_b rows=16 style="width:100%"></textarea>
   <label>Judged on</label><textarea id=ce_c rows=5 style="width:100%"></textarea>
   <label>Reference</label><input id=ce_r></div>
   <div class=row2 style="margin-top:8px"><button class=primary id=ce_go>Save</button></div>`;
  body.querySelector('#ce_b').value=r.brief||'';body.querySelector('#ce_c').value=r.criteria||'';body.querySelector('#ce_r').value=r.reference||'';
  body.querySelector('#ce_go').onclick=async()=>{
   const v=id=>body.querySelector(id).value;
   const d=await crewApi({op:'edit',id:r.id,brief:v('#ce_b'),criteria:v('#ce_c'),reference:v('#ce_r')});
   if(d){toast('instructions updated');closeSheet();openCrew()}}
 },{sub:'the builder and the reviewer use the new text from now on'})}
// --- the cluster page: bin/cluster.py
async function openCluster(){
 let alive=true,timer=null,data=null,busy=false;
 const api=async(op,extra)=>{const r=await fetch('/api/cluster',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({op,...(extra||{})})});
  const j=await r.json().catch(()=>({}));if(!r.ok)throw new Error(j.error||('error '+r.status));return j};
 const dur=t=>{if(t==null)return '—';t=Math.max(0,Math.round(t));const d=Math.floor(t/86400),h=Math.floor(t%86400/3600),m=Math.floor(t%3600/60);return d?`${d} d ${h} h`:h?`${h} h ${m} min`:m?`${m} min`:`${t} s`};
 const ago=t=>{const d=Date.now()/1000-t;return d<20?'just now':d<90?Math.round(d)+' s ago':d<5400?Math.round(d/60)+' min ago':Math.round(d/3600)+' h ago'};
 const gbs=kb=>kb==null?'—':kb>=1024**3?(kb/1024**3).toFixed(1)+' TB':kb>=1024**2?(kb/1024**2).toFixed(1)+' GB':Math.round(kb/1024)+' MB';
 const bar=(pct,note)=>{const l=pct>=95?'bad':pct>=85?'warn':'';return `<div class="clbar ${l}"><i style="width:${Math.min(100,pct||0)}%"></i></div><div class=note>${note}</div>`};
 const pill=st=>`<span class="clpill ${esc(st)}">${esc(String(st).toLowerCase().replace(/_/g,' '))}</span>`;
 const m=openSheet('Cluster',body=>{body.style.padding='12px 18px 18px';
  body.innerHTML=`<div class=sheetnote id=cl_head>Looking at the cluster…</div><div id=cl_res></div><div id=cl_main></div>`},{sub:'jobs · queue · disk · GPUs · errors'});
 const body=m.querySelector('.pvbody');
 const res=txt=>{const r=body.querySelector('#cl_res');r.innerHTML='';if(!txt)return;const d=el('<div class=clres></div>');d.textContent=txt;
  const x=el('<div style="text-align:right"><button class=ghost>close</button></div>');x.querySelector('button').onclick=()=>r.innerHTML='';r.appendChild(d);r.appendChild(x);r.scrollIntoView({block:'nearest'})};
 const doing=async(label,fn)=>{if(busy)return;busy=true;const h=body.querySelector('#cl_head');const old=h.textContent;h.textContent=label+'…';
  try{return await fn()}catch(e){res('Error: '+e.message)}finally{busy=false;if(alive)h.textContent=old}};
 const askOrbit=async jid=>{await doing('Collecting what Orbit needs',async()=>{const j=await api('ask',{id:jid});closeSheet();await newChat();const q_=$('#q');q_.value=j.text;q_.focus();q_.dispatchEvent(new Event('input',{bubbles:true}))})};
 // what is using the disk: measured by a small batch job (a big shared disk takes minutes to hours), shown as it comes in
 let du=null,duTimer=null;                      // {which, label, status, error}
 const labelOf=w=>({home:'Home',scratch:'Scratch',mine:'My folder on the lab disk',lab:'Who uses the lab disk'}[w]||w);
 const kbIn=t=>{const m=/^([\d.]+)\s*([KMGTP]?)/i.exec(String(t||''));return m?parseFloat(m[1])*{'':1,K:1,M:1024,G:1024**2,T:1024**3,P:1024**4}[m[2].toUpperCase()]:0};
 const showDu=async(which,refresh)=>{clearTimeout(duTimer);const keep=du&&du.which===which?du.status:null;du={which,label:labelOf(which),status:keep,busy:true};drawDu();
  try{du.status=await api('du_status',{which,refresh:!!refresh});du.busy=false}catch(e){du.error=e.message;du.busy=false}
  drawDu();if(du&&du.status&&du.status.running)duTimer=setTimeout(()=>{if(alive&&du&&du.which===which)showDu(which,true)},10000)};
 const startDu=async()=>{if(!du)return;const w=du.which;try{await api('du_start',{which:w});await showDu(w,true)}catch(e){du.error=e.message;drawDu()}};
 const drawDu=()=>{const box=body.querySelector('#cl_du');if(!box)return;box.innerHTML='';if(!du)return;
  const st=du.status,sn=data&&data.snapshot,labUsed=sn&&(sn.shared||[])[0]?kbIn(sn.shared[0].used):0;
  const c=el('<div class=srvcard style="margin:10px 0 0"></div>');
  let h=`<div class=srvhead><b>${esc(du.label)}</b><span class=note>${st?esc(st.path):''}</span><button class=ghost data-x=close style="margin-left:auto">close</button></div>`;
  if(du.error)h+=`<div class=srverr>${esc(du.error)}</div>`;
  if(du.busy&&!st)h+=`<div class=note>Reading from the cluster (this can take a few seconds)…</div>`;
  if(st){
   h+=`<div class=note>${du.busy?'Reading again…':'Read '+(st.read_at?ago(st.read_at):'')}${st.cached?' (kept from last time)':''} <button class=ghost data-x=refresh style="padding:1px 8px;font-size:var(--fs-xs)">Refresh</button></div>`;
   if(st.running)h+=`<div class=note>Measuring on a compute node: ${st.entries} of ${st.total_entries||'?'} entries done${st.started_at?', started '+ago(st.started_at):''}. The list below fills in as it goes; it checks again every 10 seconds.</div>`;
   else if(st.done)h+=`<div class=note>Measured ${ago(st.measured_at)}. <button class=ghost data-x=again style="padding:1px 8px;font-size:var(--fs-xs)">Measure again</button></div>`;
   else if(!st.rows.length)h+=`<div class=note>Not measured yet. This runs a small job on a compute node (never on the login node) that counts what is directly inside this place${du.which==='lab'?'':', then lists its biggest files, the kinds of file and what has not changed for a year'}${du.which==='lab'?'. <b>The lab disk is big (every file of every person is counted, two folders at a time): it can take an hour or more and puts some load on the shared disk, so a quiet time is best.</b>':': minutes for a home or scratch folder'}. <button class=primary data-x=start style="margin-left:6px">Measure</button></div>`;
   const base=du.which==='lab'&&labUsed?labUsed:st.total_kb||1;
   if(du.which==='lab'&&st.people&&st.people.length){
    h+=`<table class=cltbl><tr><th>#</th><th>Person</th><th>Using</th><th style="width:34%">Share of the disk</th><th>Folders</th></tr>`+st.people.map((p,i)=>`<tr><td>${i+1}</td><td><b>${esc(p.owner)}</b></td><td>${gbs(p.kb)}</td>
     <td><div class="clbar ${p.kb/base>.3?'warn':''}" style="margin:2px 0"><i style="width:${Math.min(100,Math.round(100*p.kb/base))}%"></i></div><small class=note>${(100*p.kb/base).toFixed(1)}%</small></td>
     <td><small class=note>${p.folders.map(f=>esc(f.split('/').pop())).join(', ')}</small></td></tr>`).join('')+'</table>';
    if(labUsed&&!st.running){const seen=st.total_kb;h+=`<div class=note>Counted ${gbs(seen)} of ${gbs(labUsed)} in use${seen<labUsed*.97?': the rest is in files the measuring job could not read (someone else’s private folders) or changed meanwhile':''}.</div>`}
   }else if(st.rows.length){
    h+=`<table class=cltbl><tr><th>Name</th><th>Size</th><th style="width:32%">Share</th><th></th></tr>`+st.rows.slice(0,40).map(r=>`<tr><td>${r.kind==='d'?'📁 ':''}<b>${esc(r.path.split('/').pop())}</b></td><td>${gbs(r.kb)}</td>
     <td><div class="clbar" style="margin:2px 0"><i style="width:${Math.min(100,Math.round(100*r.kb/base))}%"></i></div><small class=note>${(100*r.kb/base).toFixed(1)}%</small></td>
     <td class=acts>${r.kind==='d'&&r.kb>1048576?`<button class=ghost data-in="${esc(r.path)}">Look inside ▸</button>`:''}</td></tr>`).join('')+'</table>'}}
  if(st&&du.which!=='lab'){
   const sm=st.summary;
   if(sm)h+=`<div class=note style="margin-top:8px"><b>${sm.files.toLocaleString()}</b> files, ${gbs(sm.kb)}${sm.old_files?`; <b>${gbs(sm.old_kb)}</b> in ${sm.old_files.toLocaleString()} files not changed for over a year (the first place to look for room)`:''}.</div>`;
   if((st.ext||[]).length)h+=`<div class=sec style="margin-top:10px">What kinds of file</div><table class=cltbl><tr><th>Kind</th><th>Files</th><th>Size</th><th style="width:34%">Share</th></tr>`+st.ext.slice(0,12).map(x=>`<tr><td><b>${esc(x.ext)}</b></td><td>${x.count.toLocaleString()}</td><td>${gbs(x.kb)}</td>
     <td><div class=clbar style="margin:2px 0"><i style="width:${Math.min(100,Math.round(100*x.kb/Math.max(1,sm?sm.kb:st.total_kb)))}%"></i></div></td></tr>`).join('')+'</table>';
   if((st.files||[]).length)h+=`<div class=sec style="margin-top:10px">Biggest files</div><table class=cltbl><tr><th>File</th><th>Size</th><th>Last changed</th></tr>`+st.files.slice(0,15).map(f=>`<tr><td><b>${esc(f.path.split('/').pop())}</b><br><small class=note>${esc(f.path)}</small></td><td>${gbs(f.kb)}</td>
     <td>${f.mtime?new Date(f.mtime*1000).toLocaleDateString():'—'}</td></tr>`).join('')+'</table>';
   if(st.running&&st.total_entries&&st.entries>=st.total_entries)h+=`<div class=note>The folders are counted; now listing the biggest files and the kinds of file.</div>`;
  }
  c.innerHTML=h;box.appendChild(c);
  c.querySelector('[data-x=close]').onclick=()=>{clearTimeout(duTimer);du=null;drawDu()};
  const s1=c.querySelector('[data-x=start]'),s2=c.querySelector('[data-x=again]'),s3=c.querySelector('[data-x=refresh]');
  if(s3)s3.onclick=()=>showDu(du.which,true);
  if(s1)s1.onclick=()=>{if(du.which==='lab'&&!confirm('Count every file on the lab disk? It can take an hour or more and loads the shared disk. Better at a quiet time.'))return;startDu()};
  if(s2)s2.onclick=()=>{if(du.which==='lab'&&!confirm('Measure the lab disk again? It can take an hour or more.'))return;startDu()};
  c.querySelectorAll('[data-in]').forEach(b=>b.onclick=()=>showDu(b.dataset.in))};
 let hist=null;                                  // {days, data, at}: the last usage history read
 const drawHist=()=>{const box=body.querySelector('#cl_hist');if(!box||!hist)return;const d=hist.data;
  body.querySelector('#cl_hnote').textContent='read '+ago(hist.at);
  const mx=Math.max(1,...d.daily.map(x=>x.gpu_hours||x.cpu_hours/50));
  box.innerHTML=`<div class=stat><div><b>${d.ran}</b><small>jobs that ran (${d.completed} finished, ${d.failed} failed, ${d.cancelled} cancelled)</small></div>
   <div><b>${d.gpu_hours.toLocaleString()}</b><small>GPU-hours</small></div><div><b>${d.cpu_hours.toLocaleString()}</b><small>CPU-hours</small></div>
   <div><b>${d.median_wait!=null?dur(d.median_wait):'—'}</b><small>typical wait before starting</small></div></div>`
   +(d.daily.length?`<div style="display:flex;align-items:flex-end;gap:3px;height:56px;margin:8px 0">${d.daily.map(x=>`<div title="${esc(x.day)}: ${x.jobs} jobs, ${x.gpu_hours} GPU-h, ${x.cpu_hours} CPU-h" style="flex:1;min-width:4px;background:var(--acc);border-radius:2px 2px 0 0;height:${Math.max(4,Math.round(52*((x.gpu_hours||x.cpu_hours/50))/mx))}px;opacity:.75"></div>`).join('')}</div><div class=note>one bar a day: GPU-hours (CPU-hours when no GPU was used)</div>`:'')
   +(d.by_name.length?`<table class=cltbl><tr><th>Job name</th><th>Runs</th><th>Finished / failed</th><th>Usually waits</th><th>Usually runs</th><th>GPU-hours</th></tr>`+d.by_name.map(r=>`<tr><td><b>${esc(r.name)}</b></td><td>${r.jobs}</td><td>${r.ok} / ${r.failed}</td><td>${r.median_wait!=null?dur(r.median_wait):'—'}</td><td>${dur(r.median_run)}</td><td>${r.gpu_hours}</td></tr>`).join('')+'</table>':'<div class=note>Nothing ran in that time.</div>')};
 const draw=()=>{if(!alive||!data)return;const sn=data.snapshot,cfg=data.config||{},n=cfg.notify||{};
  const head=body.querySelector('#cl_head');
  head.innerHTML=sn?`<b>${esc(cfg.host)}</b> · ${esc((sn.host||{}).node||'')} · looked ${ago(data.at)}${data.error?` · <span class=srverr>${esc(data.error)}</span>`:''}
   <button class=ghost id=cl_re style="margin-left:10px">Refresh</button> <label style="margin-left:8px"><input type=checkbox id=cl_auto ${body._auto!==false?'checked':''}> refresh every 30 s while this is open</label>`
   :`Could not reach the cluster${data.error?': <span class=srverr>'+esc(data.error)+'</span>':''} <button class=ghost id=cl_re>Try again</button>`;
  head.querySelector('#cl_re').onclick=()=>load(true);
  const au=head.querySelector('#cl_auto');if(au)au.onchange=()=>{body._auto=au.checked};
  const main=body.querySelector('#cl_main');if(!sn){main.innerHTML='';return}
  const jobs=sn.jobs||[],lim=((sn.account||{}).limits)||{},gpusInUse=jobs.filter(j=>j.state==='RUNNING').reduce((a,j)=>a+j.gpus,0);
  const ms=new Set(data.model_server_jobs||[]);
  const rf=cfg.refresh||{};
  let h='';
  // what needs a look
  const allProbs=sn.problems||[],probs=allProbs.filter(p=>!p.dismissed),away=allProbs.filter(p=>p.dismissed);
  const prow=(p,back)=>`<div class="clprob ${p.level}" style="${back?'opacity:.6':''}"><span>${p.level==='bad'?'⛔':p.level==='warn'?'⚠':'ℹ'}</span><span style="flex:1">${esc(p.text)}</span><button class=ghost data-${back?'restore':'dismiss'}="${esc(p.key||'')}" title="${back?'Show this in the list again':'Put this away. It comes back if it gets worse or changes.'}" style="padding:0 8px">${back?'bring back':'×'}</button></div>`;
  h+=`<div class=sec style="margin-top:0">Needs a look${away.length?` <small><a href="#" id=cl_showaway>${away.length} put away ${body._away?'▾':'▸'}</a></small>`:''}</div>`+(probs.length?probs.map(p=>prow(p,false)).join(''):'<div class=note>Nothing: no disk filling up, nothing failing, nothing stuck.</div>');
  if(away.length&&body._away)h+=away.map(p=>prow(p,true)).join('');
  // jobs
  h+=`<div class=sec>Your jobs <small>— ${jobs.length?jobs.filter(j=>j.state==='RUNNING').length+' running, '+jobs.filter(j=>j.state==='PENDING').length+' waiting':'none in the queue'}</small></div>`;
  if(jobs.length)h+=`<table class=cltbl><tr><th>Job</th><th>State</th><th>Where / why</th><th>Time</th><th>Asked for</th><th></th></tr>`+jobs.map(j=>`<tr data-id="${esc(j.id)}">
    <td><b>${esc(j.name)}</b><br><small class=note>${esc(j.id)}${ms.has(j.name)?' · a model server (see Cluster models)':''}</small></td><td>${pill(j.state)}</td>
    <td>${j.state==='RUNNING'?esc(j.node||''):esc(j.reason||'queued')}${j.state==='PENDING'&&j.start_est?`<br><small class=note>expected start ${esc(j.start_est.replace('T',' '))}</small>`:''}</td>
    <td>${j.state==='RUNNING'?dur(j.elapsed)+' of '+dur(j.limit)+`<br><small class=note>${dur(j.left)} left</small>`:'waiting'}</td>
    <td>${j.gpus?j.gpus+' GPU · ':''}${j.cpus||'?'} CPU · ${esc(j.mem||'')}</td>
    <td class=acts>${j.state==='PENDING'?'<button class=ghost data-a=why>Why waiting</button>':'<button class=ghost data-a=out>Output</button>'}<button class=ghost data-a=ask title="Open a chat about this job">Ask Orbit</button><button class=ghost data-a=cancel>Cancel</button></td></tr>`).join('')+'</table>';
  // recent
  const rec=(sn.recent||[]).slice(0,12);
  h+=`<div class=sec>Last three days</div>`+(rec.length?`<table class=cltbl><tr><th>Job</th><th>Result</th><th>Ran for</th><th>Exit</th><th>Started</th><th></th></tr>`+rec.map(r=>`<tr data-id="${esc(r.id)}"><td><b>${esc(r.name)}</b><br><small class=note>${esc(r.id)}${r.node?' · '+esc(r.node):''}</small></td>
    <td>${pill(r.state)}</td><td>${dur(r.elapsed)}</td><td>${esc(r.exit)}</td><td>${esc((r.start||'').replace('T',' ').slice(5,16))}</td>
    <td class=acts>${['FAILED','OUT_OF_MEMORY','NODE_FAIL','TIMEOUT'].includes(r.state)?'<button class=ghost data-a=diag>What went wrong</button><button class=ghost data-a=ask>Ask Orbit</button>':''}<button class=ghost data-a=eff>Efficiency</button></td></tr>`).join('')+'</table>':'<div class=note>No jobs in the last three days.</div>');
  // how you have used it: asked for, not automatic
  h+=`<div class=sec>Usage history <small>— from the scheduler's records; shows the last reading, read again on schedule or when you press Refresh</small></div><div class=srvact>${[1,7,30].map(d=>`<button class=ghost data-h=${d}>${d===1?'Last day':'Last '+d+' days'}</button>`).join('')}<button class=ghost id=cl_hre style="padding:1px 8px;font-size:var(--fs-xs)">Refresh</button><span class=note id=cl_hnote></span></div><div id=cl_hist></div>`;
  // storage
  h+=`<div class=sec>Disk <small>— quota numbers read ${sn.slow_at?ago(sn.slow_at):'never'}; folder breakdowns show when they were measured</small> <button class=ghost id=cl_rdisk style="padding:1px 8px;font-size:var(--fs-xs)">Read the numbers again</button></div>`;
  h+=`<div class=stat style="grid-template-columns:repeat(auto-fill,minmax(230px,1fr))">`;
  (sn.storage||[]).forEach(q=>{const w=q.label==='Home'?'home':q.label==='Scratch'?'scratch':'';
   h+=`<div><b>${esc(q.label)}</b>${q.pct!=null?bar(q.pct,`${gbs(q.used_kb)} of ${gbs(q.quota_kb||q.limit_kb)} · ${q.pct}%${q.files_pct!=null?' · files '+q.files_pct+'%':''}`):`<div class=note>${gbs(q.used_kb)} used, no quota</div>`}${w?`<button class=ghost data-du=${w} style="padding:2px 8px;font-size:var(--fs-xs)">Largest folders ▸</button>`:''}${(data.growth&&data.growth[q.label]!=null)?`<div class=note>${data.growth[q.label]>=0?'+':'−'}${gbs(Math.abs(data.growth[q.label]))} in a week</div>`:''}</div>`});
  (sn.shared||[]).forEach(d=>{h+=`<div><b>Lab project disk</b>${bar(d.pct,`${esc(d.used)} of ${esc(d.size)} · ${d.pct}% · ${esc(d.avail)} free<br>${esc(d.mount)}`)}${cfg.project_dir?'<button class=ghost data-du=lab style="padding:2px 8px;font-size:var(--fs-xs)">Who uses it ▸</button> <button class=ghost data-du=mine style="padding:2px 8px;font-size:var(--fs-xs)">My folder ▸</button>':''}</div>`});
  h+=`</div><div id=cl_du></div>`;
  // gpus
  const g=sn.gpus||{};
  h+=`<div class=sec>GPUs <small>— ${g.total?g.free+' of '+g.total+' free':'no data'}${lim.gpus!=null?` · you may use ${lim.gpus} at once, using ${gpusInUse} now`:''}</small></div>`;
  if((g.models||[]).length)h+=`<table class=cltbl><tr><th>Model</th><th>Memory</th><th>Nodes</th><th>GPUs</th><th>Free</th></tr>`+g.models.map(x=>`<tr><td>${esc(x.model)}</td><td>${esc(x.vram||'')}</td><td>${x.nodes}</td><td>${x.gpus}</td><td><b>${x.free}</b></td></tr>`).join('')+'</table>';
  h+=`<details style="margin-top:6px"><summary style="cursor:pointer">By node (${(g.nodes||[]).length})</summary><table class=cltbl><tr><th>Node</th><th>Model</th><th>Free GPUs</th><th>State</th><th>Idle CPUs</th><th>Free memory</th></tr>`+(g.nodes||[]).map(x=>`<tr><td>${esc(x.node)}</td><td>${esc(x.model||'')}</td><td>${x.free}/${x.total}</td><td>${esc(x.state||'')}</td><td>${esc(x.idle_cpus||'')}</td><td>${esc(x.free_mem||'')}</td></tr>`).join('')+'</table></details>';
  h+=`<div class=srvact style="margin-top:8px"><b>Where would my job start now?</b> <input id=cl_g type=number min=1 value=1 style="width:56px"> GPU <input id=cl_mem type=number min=0 value=32 style="width:70px"> GB memory <input id=cl_c type=number min=0 value=8 style="width:60px"> CPUs
   <input id=cl_mod placeholder="GPU model (optional)" style="width:150px"><button class=ghost id=cl_fit>Check</button><span class=note id=cl_fitres></span></div>`;
  // account and queue
  const a=sn.account||{},pt=a.partition||{};
  h+=`<div class=sec>Your limits and the queue</div><div class=stat>
   <div><b>${esc(a.account||'—')}</b><small>account</small></div><div><b>${a.fairshare!=null?a.fairshare.toFixed(2):'—'}</b><small>fair-share (higher starts sooner)</small></div>
   <div><b>${lim.running_jobs!=null?jobs.filter(j=>j.state==='RUNNING').length+' / '+lim.running_jobs:'—'}</b><small>running jobs, of what you may</small></div>
   <div><b>${lim.gpus!=null?gpusInUse+' / '+lim.gpus:'—'}</b><small>GPUs in use, of what you may</small></div>
   <div><b>${pt.idle_cpus!=null?pt.idle_cpus.toLocaleString():'—'}</b><small>idle CPUs on ${esc(pt.name||'the partition')} (of ${pt.cpus?pt.cpus.toLocaleString():'?'})</small></div>
   <div><b>${pt.max_time?esc(pt.max_time):'—'}</b><small>longest job allowed</small></div></div>`;
  // login node
  const hs=sn.host||{};
  h+=`<div class=sec>Login node <small>— ${esc(hs.node||'')}</small></div>${bar(hs.processes&&hs.process_limit?Math.round(100*hs.processes/hs.process_limit):0,`${hs.processes??'?'} of your processes of ${hs.process_limit??'?'} allowed here${hs.load?' · load '+esc(hs.load):''}. A login node with too many cannot start a new shell: stop what you do not need.`)}
   <div class=srvact><button class=ghost data-a=procs>Show my processes</button></div><div id=cl_procs></div>`;
  // events
  const ev=data.events||[];
  h+=`<div class=sec>What happened</div>`+(ev.length?ev.map(e=>`<div class=clev><small>${ago(e.t)}</small>${esc(e.text)}${e.cause&&e.cause.fix?`<div class=note>${esc(e.cause.explained||'')}${e.cause.explained?'<br>':''}<b>${esc(e.cause.title||'')}.</b> ${esc(e.cause.fix)}</div>`:''}
    ${e.detail?`<details><summary>details</summary><div class=clres>${esc(e.detail)}</div></details>`:''}${e.job&&['failed','error','pending'].includes(e.kind)?` <button class=ghost data-a=ask data-id="${esc(e.job)}" style="padding:1px 8px;font-size:var(--fs-xs)">Ask Orbit</button>`:''}</div>`).join(''):'<div class=note>Nothing yet. Orbit watches the queue and tells you when a job starts, ends, fails, waits too long or prints an error.</div>');
  // settings
  h+=`<div class=sec>Watching</div><div class=grid>
   <label>Watch the queue</label><div class=sw><input type=checkbox id=cl_watch ${cfg.watch?'checked':''}><span class=note>every 90 seconds while something of yours is queued or running, every 10 minutes otherwise; one shared login, never a new one each time</span></div>
   <label>Tell me when</label><div class=sw style="flex-wrap:wrap;gap:14px">${[['started','a job starts'],['finished','a job finishes'],['failed','a job fails'],['errors','a running job prints an error'],['pending','a job has waited 4 h'],['disk','a disk is filling up'],['digest','a summary each morning']].map(([k,t])=>`<label><input type=checkbox data-n=${k} ${n[k]?'checked':''}> ${t}</label>`).join('')}</div>
   <label>Explain failures</label><div class=sw><input type=checkbox id=cl_expl ${cfg.explain!==false?'checked':''}><span class=note>a short plain-language reading of why a job failed, written by Orbit's helper model from the cluster's own diagnosis</span></div>
   <label>Read again by itself</label><div class=sw style="flex-wrap:wrap;gap:8px"><input type=checkbox id=cl_rf ${rf.on?'checked':''}> every
    <select id=cl_rfh>${[[6,'6 hours'],[12,'12 hours'],[24,'day'],[48,'2 days'],[168,'week']].map(([v,t])=>`<option value=${v} ${+rf.every_h===v?'selected':''}>${t}</option>`).join('')}</select>
    <span id=cl_rfat>at <input id=cl_rft type=time value="${esc(rf.at||'03:00')}"></span>
    <label style="font-weight:normal"><input type=checkbox id=cl_rfm ${rf.remeasure!==false?'checked':''}> measure my own folders again (home, scratch, my project folder, folders I looked inside), only the ones that changed; the lab-wide count and other people’s folders are never done by themselves</label>
    <span class=note style="flex-basis:100%">Quotas, disk sizes, limits, GPUs and usage history are read again then, quietly. Each folder is first checked for changes (its quota, or any file modified since) and skipped if nothing changed; anything over a week old is measured regardless${data.next_refresh?'. Next: '+new Date(data.next_refresh*1000).toLocaleString([], {weekday:'short',hour:'2-digit',minute:'2-digit'}):''}. If the Mac was asleep, it happens when it wakes.</span></div>
   <label>Project folder</label><input id=cl_proj value="${esc(cfg.project_dir||'')}" placeholder="/path/to/project/yourlab" style="max-width:300px"></div>
   <div class=srvact><button class=primary id=cl_save>Save</button><span class=note id=cl_savemsg></span></div>`;
  main.innerHTML=h;
  // actions
  main.querySelectorAll('[data-a]').forEach(b=>b.onclick=async()=>{
   const row=b.closest('[data-id]'),id=b.dataset.id||(row&&row.dataset.id),a_=b.dataset.a;
   if(a_==='ask')return askOrbit(id);
   if(a_==='cancel'){if(!confirm('Cancel job '+id+'?'))return;return doing('Cancelling',async()=>{data=await api('cancel',{id});draw()})}
   if(a_==='why')return doing('Asking the cluster',async()=>res((await api('explain',{id,kind:'why'})).text));
   if(a_==='diag')return doing('Reading the diagnosis',async()=>res((await api('explain',{id,kind:'diagnose'})).text));
   if(a_==='out')return doing('Reading its output',async()=>res((await api('output',{id})).text));
   if(a_==='eff')return doing('Reading its accounting',async()=>{const e=await api('efficiency',{id});
     res(`Job ${id}\nCPU used: ${e.cpu_eff!=null?e.cpu_eff+'% of '+e.cpus+' CPUs':'unknown'}\nMemory used: ${e.mem_used_mb!=null?e.mem_used_mb+' MB of '+(e.mem_requested_mb||'?')+' MB asked for'+(e.mem_eff!=null?' ('+e.mem_eff+'%)':''):'unknown'}\n\n${(e.notes||[]).join('\n')||(e.cpu_eff==null&&e.mem_eff==null?'Slurm did not record what it used (the job was too short, or accounting does not keep it).':'Nothing to change: it asked for about what it used.')}`)});
   if(a_==='procs')return doing('Listing your processes',async()=>{const p=(await api('processes')).processes;const box=main.querySelector('#cl_procs');
     box.innerHTML=`<table class=cltbl><tr><th>Process</th><th>Running for</th><th></th></tr>${p.map(x=>`<tr><td><code>${esc(x.cmd)}</code><br><small class=note>pid ${x.pid}</small></td><td>${dur(x.age)}</td><td class=acts>${x.system?'<small class=note>keeps your login</small>':`<button class=ghost data-kill=${x.pid}>Stop</button>`}</td></tr>`).join('')}</table>`;
     box.querySelectorAll('[data-kill]').forEach(k=>k.onclick=()=>{if(!confirm('Stop process '+k.dataset.kill+'?'))return;doing('Stopping',async()=>{await api('stop_process',{pid:k.dataset.kill});main.querySelector('[data-a=procs]').click()})})})});
  main.querySelectorAll('[data-dismiss]').forEach(b=>b.onclick=()=>doing('Putting it away',async()=>{data=await api('dismiss',{key:b.dataset.dismiss});draw()}));
  main.querySelectorAll('[data-restore]').forEach(b=>b.onclick=()=>doing('Bringing it back',async()=>{data=await api('restore',{key:b.dataset.restore});draw()}));
  const sa=main.querySelector('#cl_showaway');if(sa)sa.onclick=e=>{e.preventDefault();body._away=!body._away;draw()};
  const rd=main.querySelector('#cl_rdisk');if(rd)rd.onclick=()=>doing('Reading quotas and disk sizes (can take a while)',async()=>{data=await api('look',{force:true,slow:true});draw()});
  main.querySelectorAll('[data-du]').forEach(b=>b.onclick=()=>showDu(b.dataset.du));
  drawDu();
  if(!hist){const hs=Object.values(data.history||{}).sort((a,b)=>(b.read_at||0)-(a.read_at||0))[0];if(hs)hist={days:hs.days,data:hs,at:hs.read_at}}
  const readHist=(days,refresh)=>doing('Reading the accounting',async()=>{const r=await api('history',{days,refresh:!!refresh});hist={days,data:r,at:r.read_at};(data.history=data.history||{})[days]=r;drawHist()});
  main.querySelectorAll('[data-h]').forEach(b=>b.onclick=()=>readHist(+b.dataset.h,false));
  main.querySelector('#cl_hre').onclick=()=>readHist(hist?hist.days:7,true);
  drawHist();
  main.querySelector('#cl_fit').onclick=()=>doing('Checking',async()=>{const r=await api('where',{gpus:+main.querySelector('#cl_g').value||1,mem_gb:+main.querySelector('#cl_mem').value||0,cpus:+main.querySelector('#cl_c').value||0,model:main.querySelector('#cl_mod').value});
   main.querySelector('#cl_fitres').textContent=r.over_limit?`You may use only ${r.gpu_limit} GPUs at once: this would wait for ever.`:r.nodes.length?'Fits now on: '+r.nodes.map(x=>`${x.node} (${x.model}, ${x.free_gpus} free, ${x.free_mem} memory)`).join('; '):'Nothing has that free right now: it would wait. Ask for less memory or fewer CPUs, or another GPU model.'});
  const rfh=main.querySelector('#cl_rfh'),rfat=main.querySelector('#cl_rfat');const syncAt=()=>{rfat.style.display=+rfh.value>=24?'':'none'};rfh.onchange=syncAt;syncAt();
  main.querySelector('#cl_save').onclick=()=>doing('Saving',async()=>{const notify={};main.querySelectorAll('[data-n]').forEach(c=>notify[c.dataset.n]=c.checked);
   data=await api('config',{refresh:{on:main.querySelector('#cl_rf').checked,every_h:+main.querySelector('#cl_rfh').value,at:main.querySelector('#cl_rft').value,remeasure:main.querySelector('#cl_rfm').checked},watch:main.querySelector('#cl_watch').checked,explain:main.querySelector('#cl_expl').checked,project_dir:main.querySelector('#cl_proj').value,notify});main.querySelector('#cl_savemsg').textContent='saved';await load(true)})};
 const load=async force=>{if(busy&&!force)return;try{data=await api('look',{force:!!force});try{data.growth=(await api('growth')).growth}catch(_){}draw()}catch(e){body.querySelector('#cl_head').textContent='Could not read the cluster: '+e.message}};
 try{data=await api('look',{cached:true});if(data.snapshot){data.growth={};draw()}}catch(_){}
 await load(true);
 timer=setInterval(()=>{if(!document.body.contains(body)){alive=false;clearInterval(timer);return}if(body._auto!==false&&!busy)load(false)},30000)}
async function openCrew(){
 const m=openSheet('Crew',(body)=>{
  body.style.padding='12px 18px 16px';
  body.innerHTML=`<div class=sheetnote>A <b>builder</b> and a <b>reviewer</b> on different models. The builder builds in its own folder; Orbit checkpoints it in git; the reviewer runs it and scores it; the review becomes the builder's next brief. It does not decide it is finished: it keeps going through errors, limits and restarts until you pause or stop it, or hit a limit you set. Both are ordinary chats you can open and talk to.</div>
   <div id=crewlist></div>
   <details id=crewnew style="margin-top:10px;border:1px solid var(--line);border-radius:9px;padding:8px 10px"><summary style="cursor:pointer"><b>Start a new crew</b></summary>
    <div class=grid style="margin-top:8px">
     <label>Name</label><input id=cw_title placeholder="e.g. BlotScribe, rebuilt">
     <label>What to build</label><textarea id=cw_brief rows=5 placeholder="Describe the app: who it is for, what it must do, the stack if you care. The builder starts from this."></textarea>
     <label>Folder</label><input id=cw_folder placeholder="(optional) default: ~/Rdirectory/Crew/<name>">
     <label>Reference</label><input id=cw_ref placeholder="(optional) an existing project to read for ideas — nothing is copied from it">
     <label>Judged on</label><textarea id=cw_crit rows=3 placeholder="(optional) the criteria the reviewer scores against — e.g. the hackathon's judging rubric"></textarea>
     <label>Builders</label><div id=cw_b></div>
     <label>Reviewers</label><div id=cw_r></div>
     <label>Stop after</label><div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center"><input id=cw_h type=number min=0 step=1 style="width:70px" placeholder="0"> hours
      <input id=cw_n type=number min=0 step=1 style="width:70px" placeholder="0"> rounds <input id=cw_t type=number min=0 step=100000 style="width:110px" placeholder="0"> tokens <span class=note>(0 = never)</span></div>
    </div>
    <div class=note style="margin:6px 0">Each side can be one chat or several, new or yours: several builders take turns round by round; several reviewers each score the round and the scores are averaged; with no reviewer, the builder's own chat steps back and reviews its work. A chat of yours is used as it is — or on a model and effort you pick for it — and gets its folder, model, permissions and effort put back when the crew stops. Every chat works without asking you, inside the folder. A model API bills for every round, so a token limit is worth setting for a long run.</div>
    <button class=primary id=cw_go>Start</button></details>`;
  const d0=crewDefaults();
  const PB=crewParties(body.querySelector('#cw_b'),'builder',[{model:d0.builder}],false);
  const PR=crewParties(body.querySelector('#cw_r'),'reviewer',d0.reviewer?[{model:d0.reviewer}]:[],true);
  body.querySelector('#cw_go').onclick=async()=>{
   const v=id=>body.querySelector(id).value.trim();
   const bs=PB.get(),rs=PR.get();
   if(bs===null||rs===null){toast('pick a model or a chat for every row');return}
   const r=await crewApi({op:'start',title:v('#cw_title'),brief:v('#cw_brief'),folder:v('#cw_folder'),reference:v('#cw_ref'),criteria:v('#cw_crit'),
    builders:bs,reviewers:rs,hours:+v('#cw_h')||0,max_rounds:+v('#cw_n')||0,max_tokens:+v('#cw_t')||0});
   if(r){toast('crew started');body.querySelector('#crewnew').open=false;draw()}};
  const draw=async()=>{
   const list=body.querySelector('#crewlist');if(!list)return;
   let d;try{d=await (await fetch('/api/crew',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({op:'list'})})).json()}catch(e){return}
   list.innerHTML='';
   if(!(d.runs||[]).length){list.appendChild(el('<div class=sheetnote>No crews yet.</div>'));if(!body.querySelector('#crewnew').dataset.opened){body.querySelector('#crewnew').open=true;body.querySelector('#crewnew').dataset.opened=1}}
   (d.runs||[]).forEach(r=>{
    const last=r.last||{},lim=r.limits||{};
    const st=r.state==='running'?(r.attention?'needs you':r.phase==='review'?'reviewing':r.phase==='build'?'building':'between rounds'):r.state;
    const card=el('<div class=usecard style="margin:8px 0"></div>');
    const lims=[lim.hours?lim.hours+' h':'',lim.max_rounds?lim.max_rounds+' rounds':'',lim.max_tokens?(lim.max_tokens/1e6).toFixed(1)+'M tokens':''].filter(Boolean).join(', ');
    card.innerHTML=`<div class=usename></div><div class=note id=cs></div><div id=cr style="margin:4px 0"></div><div id=cb class=note></div><div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:6px" id=ca></div>`;
    card.querySelector('.usename').textContent=r.title+' — '+st;
    const who=(l)=>(l||[]).map(x=>x.existing?'“'+ttl0(x.sid)+'”':(x.model||'').replace(/^(harness|codex|claude-cli|agy-cli|muse-cli):/,'')).join(' + ');
    const ttl0=sid=>{const x=(typeof SESSIONS!=='undefined'?SESSIONS:[]).find(s=>s.id===sid);return x?(x.title||sid).slice(0,26):sid};
    card.querySelector('#cs').textContent=`${who(r.builders)||'?'} builds · ${(r.reviewers||[]).length?who(r.reviewers)+' reviews':'the builder reviews itself'} · round ${r.round} · best ${r.best==null?'—':r.best+' (round '+r.best_round+')'} · last ${last.score==null?'—':last.score} · ${(r.tokens||0).toLocaleString()} tokens · started ${crewAgo(r.started)}${lims?' · stops after '+lims:' · no limit'}`;
    const ac=r.activity;
    if(ac&&r.state==='running'){const a=el('<div class=note style="margin:3px 0"></div>');
     const mins=Math.floor((ac.secs||0)/60);
     a.textContent=ac.what?ac.what:(ac.busy?(r.phase==='review'?'Reviewing':'Building')+' for '+(mins?mins+' min':(ac.secs||0)+' s')+' · '+(ac.steps||0)+' steps so far'+(ac.status?' · '+ac.status:''):
       ac.queued?'The message is waiting in “'+ac.title+'” until that chat is free':'Waiting for “'+(ac.title||'the chat')+'” to start');
     card.querySelector('#cr').appendChild(a)}
    const note=r.attention||r.reason;
    if(note){const n=el('<div class=sheetnote></div>');n.textContent=note;if(r.attention||r.state==='paused')n.style.color='var(--err)';card.querySelector('#cr').appendChild(n)}
    if(last.summary){const n=el('<div class=note></div>');n.textContent='Reviewer, round '+last.round+': '+last.summary;card.querySelector('#cr').appendChild(n)}
    if((r.backlog||[]).length){card.querySelector('#cb').textContent='Next: '+r.backlog.slice(0,3).join(' · ')}
    const acts=card.querySelector('#ca');
    const btn=(t,fn,tip)=>{const b=el('<button class=ghost></button>');b.textContent=t;if(tip)b.title=tip;b.onclick=async()=>{b.disabled=true;try{await fn()}finally{b.disabled=false}draw()};acts.appendChild(b)};
    if(r.state==='running')btn('Pause',()=>crewApi({op:'pause',id:r.id}),'stops the current answer; Resume carries on from the same round');
    else if(r.state!=='stopped')btn(r.state==='done'?'Raise the limit…':'Resume',async()=>{
      if(r.state==='done'){const h=prompt('Run for how many more hours in total? (0 = no limit)',String(Math.max(1,(+lim.hours||0)+12)));if(h===null)return;await crewApi({op:'limits',id:r.id,hours:+h||0,max_rounds:0,max_tokens:0})}
      else await crewApi({op:'resume',id:r.id})});
    if(r.state!=='stopped')btn('Stop',()=>crewApi({op:'stop',id:r.id}),'ends the run; the folder and the chats stay');
    btn('Edit instructions…',()=>crewEdit(r),'change the brief, how it is judged or the reference while it runs; the builder is told at once');
    btn('Tell the builder…',async()=>{const t=prompt('A note for the builder\'s next round (it comes before the reviewer\'s list):');if(t)await crewApi({op:'note',id:r.id,text:t});if(t)toast('noted')});
    btn('Limits…',async()=>{
      const h=prompt('Stop after how many hours? (0 = never)',String(lim.hours||0));if(h===null)return;
      const n=prompt('Stop after how many rounds? (0 = never)',String(lim.max_rounds||0));if(n===null)return;
      const t=prompt('Stop after how many tokens? (0 = never)',String(lim.max_tokens||0));if(t===null)return;
      await crewApi({op:'limits',id:r.id,hours:+h||0,max_rounds:+n||0,max_tokens:+t||0})});
    const ttl=sid=>{const x=(typeof SESSIONS!=='undefined'?SESSIONS:[]).find(s=>s.id===sid);return x?(x.title||sid).slice(0,28):sid};
    const seen=new Set();
    (r.builders||[]).forEach((b,i)=>{if(b.sid&&!seen.has(b.sid)){seen.add(b.sid);btn('Open '+((r.builders||[]).length>1?'builder '+(i+1):'builder')+(b.existing?' ('+ttl(b.sid)+')':''),()=>{closeSheet();openSession(b.sid)})}});
    (r.reviewers||[]).forEach((b,i)=>{if(b.sid&&!seen.has(b.sid)){seen.add(b.sid);btn('Open '+((r.reviewers||[]).length>1?'reviewer '+(i+1):'reviewer')+(b.existing?' ('+ttl(b.sid)+')':''),()=>{closeSheet();openSession(b.sid)})}});
    btn('Folder',()=>crewApi({op:'reveal',id:r.id}),r.folder);
    if(r.state!=='running')btn('Delete',async()=>{if(confirm('Remove this crew from the list? Its folder and chats are kept.'))await crewApi({op:'delete',id:r.id})});
    list.appendChild(card)})};
  draw();
  clearInterval(CREW_TIMER);
  CREW_TIMER=setInterval(()=>{if(!document.querySelector('#modalhost .pvmodal')||!body.isConnected){clearInterval(CREW_TIMER);return}draw()},6000)
 },{sub:'build · review · improve, until you stop it'});
}
async function openHandoff(forSid){
 let d;try{d=await (await fetch('/api/handoff?sid='+encodeURIComponent(forSid||sid))).json()}catch(e){toast('could not read the chat');return}
 if(d.error){toast(d.error);return}
 openSheet('Hand off to Claude desktop',(body)=>{
  body.style.padding='12px 18px 16px';
  const intro=el('<div class=sheetnote></div>');
  intro.textContent='Claude desktop keeps its own copy of a conversation, so it does not know what happened here. '+
   'Paste this note into the desktop chat: it says where the session is, how to resume it, and what the latest turns were.';
  body.appendChild(intro);
  if((d.desktop_holders||[]).length){
   // the usual reason it "has no idea": the app keeps a Claude Code running for every session it has open
   const w=el('<div class=sheetnote style="color:var(--err)"></div>');
   w.textContent='Claude desktop has this session open right now, with its own copy of the conversation: what you write there next will not include what happened here.';
   const b=el('<button class=ghost style="margin-left:8px">Close its open copy</button>');
   b.onclick=async()=>{b.disabled=true;
    const r=await fetch('/api/handoff/release',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({sid:forSid||sid})}).then(x=>x.json()).catch(()=>({msg:'failed'}));
    w.textContent=r.msg||'done';w.style.color=r.ok?'var(--ok)':'var(--err)'};
   w.appendChild(b);body.appendChild(w)}
  const pre=el('<pre class=taskout style="max-height:46vh;white-space:pre-wrap"></pre>');pre.textContent=d.text;body.appendChild(pre);
  const row=el('<div class=row2 style="margin-top:8px"><button class=primary id=hocopy>Copy note</button><button class=ghost id=howrite>Have Claude write a fuller note</button></div>');
  row.querySelector('#hocopy').onclick=()=>{copy(d.text);toast('copied — paste it into the Claude desktop chat')};
  row.querySelector('#howrite').onclick=()=>{
   if(forSid&&forSid!==sid){toast('open that chat first');return}
   closeModal();q.value=d.prompt;setTimeout(()=>go(),0)};
  body.appendChild(row);
  const hint=el('<div class=sheetnote style="margin-top:6px"></div>');
  hint.textContent='The fuller note is written by Claude in this chat and saved as HANDOFF.md in the working folder: tell the desktop chat to read that file.';
  body.appendChild(hint)},{sub:d.session?('session '+d.session.slice(0,8)):''})}
// Claude Code's /usage: how much of each plan is used. The figures are what Claude itself reported
// with its last answers, so opening this costs nothing; "Check now" asks it with one tiny question.
async function showClaudeUsage(refresh){
 openSheet('Claude plan usage',(body,acts)=>{
  body.style.padding='12px 18px 16px';
  const bar=(w)=>{
   const used=Math.max(0,Math.min(100,+w.used||0));
   const col=used>=90?'var(--err)':used>=75?'#d98a1a':'var(--acc)';
   const resets=w.resets?new Date(+w.resets*1000):null;
   const left=resets?Math.max(0,(resets-Date.now())/1000):null;
   const lt=left==null?'':left>=86400?Math.round(left/86400*10)/10+' days':left>=3600?Math.floor(left/3600)+'h '+Math.round(left%3600/60)+'m':Math.max(1,Math.round(left/60))+' min';
   const r=el(`<div class=usewin><div class=usehd><span></span><b></b></div><div class=usebar><i></i></div><div class=usesub></div></div>`);
   r.querySelector('.usehd span').textContent=w.name;
   r.querySelector('.usehd b').textContent=used+'% used';
   const i=r.querySelector('.usebar i');i.style.width=used+'%';i.style.background=col;
   r.querySelector('.usesub').textContent=resets?(w.stale?'reset since — ':'')+'resets '+resets.toLocaleString([],{weekday:'short',hour:'numeric',minute:'2-digit'})+(w.stale?'':' · in '+lt):'';
   return r};
  const draw=(d)=>{
   body.innerHTML='';
   (d.accounts||[]).forEach(a=>{
    const card=el('<div class=usecard><div class=usename></div></div>');
    card.querySelector('.usename').textContent=a.label+(a.main?' ★ main':'')+(a.ready?'':' — not signed in');
    const u=a.usage;
    if(u&&u.windows&&u.windows.length){u.windows.forEach(w=>card.appendChild(bar(w)));
     if(u.age>120){const n=el('<div class=usesub></div>');n.textContent='as of '+Math.round(u.age/60)+' min ago';card.appendChild(n)}}
    else if(u&&u.usage_based&&u.credits){
     const c=u.credits,money=x=>(c.currency==='USD'?'$':c.currency+' ')+x.toLocaleString([],{minimumFractionDigits:2,maximumFractionDigits:2});
     const r=bar({name:'month (credits)',used:+c.pct||0,resets:u.renews});
     r.querySelector('.usehd b').textContent=money(c.used)+' of '+money(c.limit)+' used';
     card.appendChild(r);
     if(c.reached){const n=el('<div class=usesub style="color:var(--err)">monthly limit reached</div>');card.appendChild(n)}}
    else if(u&&u.usage_based){
     const n=el('<div class=usesub></div>');
     n.textContent='Usage-based billing: no 5-hour or weekly window — a monthly allowance that renews '+new Date(+u.renews*1000).toLocaleDateString([],{month:'short',day:'numeric'})+'. For the amount left, give this account a usage login (Settings → Models & keys).';card.appendChild(n)}
    else{const n=el('<div class=usesub></div>');n.textContent=a.error?('could not read it: '+a.error):'no figures yet — press Check now';card.appendChild(n)}
    // what has gone through Orbit this month, priced by Claude Code at list prices: the one monthly
    // figure an account without a 5-hour or weekly window has (Claude does not say how much of it is left)
    if(u&&u.spend&&u.spend.runs){const m=el('<div class=usesub style="margin-top:6px"></div>');
     m.textContent='This month through Orbit: ≈ $'+u.spend.usd.toFixed(2)+' at list prices ('+u.spend.runs+' answer'+(u.spend.runs===1?'':'s')+') — not counting the Claude app or the terminal.';card.appendChild(m)}
    body.appendChild(card)});
   const row=el('<div class=row2 style="margin-top:10px"><button class=ghost id=usenow>Check now</button><button class=ghost id=usestats>Orbit\'s own stats</button></div>');
   row.querySelector('#usenow').onclick=async e=>{e.target.disabled=true;e.target.textContent='asking Claude…';
    try{draw(await (await fetch('/api/claude/usage?refresh=1')).json())}catch(x){e.target.textContent='failed'}};
   row.querySelector('#usestats').onclick=()=>{closeModal();showStats(7)};
   body.appendChild(row)};
  body.innerHTML='<div class=sheetnote>reading…</div>';
  fetch('/api/claude/usage'+(refresh?'?refresh=1':'')).then(r=>r.json()).then(draw).catch(()=>{body.innerHTML='<div class=sheetnote>could not read it</div>'})
 },{sub:'what Claude reported with its last answers'})}
// Claude Code names each batch of tool calls in a line ("Counted fruit-related lines in recent
// transcripts"), as its desktop app shows them: that line goes above the batch's first row, which
// is found by the call ids. The rows stay, and open as before.
function toolSummaryLine(ids,text,scope){
 const root=scope||wrap;
 const rows=(ids||[]).map(id=>root.querySelector('details.tool[data-id="'+CSS.escape(id)+'"]')).filter(Boolean);
 if(!rows.length||!text)return;
 const first=rows[0];
 const prev=first.previousElementSibling;
 if(prev&&prev.classList.contains('toolsum')&&prev.dataset.t===text)return;     // already drawn
 const line=el('<div class=toolsum><span class=tsarr>▸</span><span class=tst></span></div>');
 line.querySelector('.tst').textContent=text;line.dataset.t=text;
 line.title=rows.length+' tool call'+(rows.length===1?'':'s')+' — click to show or hide them';
 let open=true;
 line.onclick=()=>{open=!open;line.querySelector('.tsarr').textContent=open?'▸':'▾';rows.forEach(r=>r.style.display=open?'':'none')};
 first.before(line)}
// What Claude Code thinks you will say next, offered above the box: click it (or press Tab in an
// empty box) to use it, and it goes away as soon as you type anything or send.
function showSuggestion(forSid,text){
 const old=$('#sugg');if(old)old.remove();
 if(!text||forSid!==sid)return;
 const box=el('<div id=sugg class=sugg title="Claude Code suggests this as your next message — click, or press Tab in an empty box"><span class=sg></span><button class=ghost>use</button><button class=ghost aria-label=dismiss>×</button></div>');
 box.querySelector('.sg').textContent=text;
 const use=()=>{q.value=text;box.remove();fitQ&&fitQ();q.focus()};
 box.querySelector('.sg').onclick=use;box.querySelector('button').onclick=use;
 box.querySelectorAll('button')[1].onclick=()=>box.remove();
 const cw=document.querySelector('.cwrap');if(cw)cw.insertBefore(box,cw.querySelector('.chips')||cw.firstChild)}
document.addEventListener('keydown',e=>{
 const g=$('#sugg');
 if(e.key==='Tab'&&g&&document.activeElement===q&&!q.value&&!e.shiftKey){e.preventDefault();q.value=g.querySelector('.sg').textContent;g.remove()}});
q.addEventListener('input',()=>{const g=$('#sugg');if(g&&q.value)g.remove()});
let WATCH_N=null, WATCH_SID=null, WATCH_GONE=null;
async function watchOpenChat(){
 // a temporary chat has no file to stamp, and a chat that 404s once (deleted,
 // or never saved) is not polled again -- both used to 404 every 3 seconds
 if(!sid||tempMode||sid===WATCH_GONE||busy||SENDING.has(sid)||livePoll||switching||document.hidden)return;
 try{
  const st=await (await fetch('/api/stamp/'+sid)).json();
  if(st.error){WATCH_GONE=sid;return}
  if(WATCH_SID!==sid||WATCH_N===null){WATCH_SID=sid;WATCH_N=st.n;return}   // no baseline yet
  if(st.n!==WATCH_N||st.running){
   WATCH_N=st.n;
   const typing=q.value, hadFocus=document.activeElement===q;  // keep what you were typing
   await openSession(sid);
   q.value=typing; if(hadFocus)q.focus();
  }
 }catch(e){}
}
setInterval(watchOpenChat,3000);
setInterval(()=>{if(!document.hidden&&sid&&QUEUE_SID===sid&&(QUEUE.items||[]).length&&!busy)loadQueue(sid)},9000);
document.addEventListener('visibilitychange',()=>{if(!document.hidden)watchOpenChat()});
// and the list itself, so a chat that moved on another device moves here too
// The list used to be re-read only while nothing was answering, so a chat started
// elsewhere (the phone, a scheduled task, another window) stayed hidden until you
// reloaded -- and a stale "busy" hid it for good. A cheap stamp is asked for instead,
// whatever is running, and the list is re-read only when it moves.
let LIST_STAMP=null;
async function pollList(force){
 if(document.hidden&&!force)return;
 try{
  const st=await (await fetch('/api/sessions/stamp')).json();
  const k=JSON.stringify(st);
  if(k===LIST_STAMP&&!force)return;
  LIST_STAMP=k;await loadSessions();
 }catch(e){}}
setInterval(pollList,4000);
// back on this window: everything it may have missed while away, at once
function catchUp(){if(document.hidden)return;
 refreshRunning();pollList(true);watchOpenChat();pollBg();pollGit();
 if(sid&&QUEUE_SID===sid)loadQueue(sid)}
addEventListener('focus',catchUp);document.addEventListener('visibilitychange',catchUp);

async function refreshStatus(){
 try{const s=await (await fetch('/api/status'+(sid?'?sid='+encodeURIComponent(sid):''))).json();
  $('#dot').classList.toggle('up',!!s.running);
  $('#fmodel').textContent=(s.model||'stopped')+(s.memory_gb?' · '+s.memory_gb+' GB':'');
  const c=s.context;
  if(c&&c.max){
   const pct=Math.min(100,c.pct);
   $('#ctxbox').style.display='';$('#ctxbar').style.width=pct+'%';
   $('#ctxbar').style.background=pct>85?'var(--err)':pct>65?'var(--warn)':'var(--acc)';
   $('#ctxtxt').textContent=`${Math.round(pct)}% · ${c.used.toLocaleString()}/${c.max.toLocaleString()}`;
   const limit=(INFO.settings&&INFO.settings.autocompact_pct)||80;
   $('#ctxbox').title=`${c.basis} — this chat only · click for the breakdown`+
    (pct>=limit?' · auto-compact will trigger':'');
   $('#ctxbox').style.cursor='pointer';
   $('#ctxbox').onclick=showContext;
   // Claude Code warns once the window is nearly full, with what to do about it
   const left=Math.max(0,100-pct);
   if(pct>=limit-5&&!ctxWarned){ctxWarned=true;
    sysline(`Context low (${Math.round(left)}% remaining) — /compact to summarise and carry on`)}
   if(pct<limit-15)ctxWarned=false}
  else $('#ctxbox').style.display='none';
 }catch(e){}}

let ctxWarned=false;
let RENDER_GEN=0;
let fileLimit=60;
const ICON={image:'\u{1F5BC}',doc:'\u{1F4C4}',code:'\u{1F4C3}',data:'\u{1F9EC}',other:'\u{1F4C1}'};
function human(b){return b>1048576?(b/1048576).toFixed(1)+' MB':b>1024?(b/1024).toFixed(0)+' KB':b+' B'}
async function renderFiles(){
 const box=$('#files');box.innerHTML='<div class=note>loading...</div>';
 const fd=await (await fetch(`/api/files?limit=${fileLimit}`)).json();
 const list=fd.items||fd; const fileTotal=fd.total??list.length;
 if(!list.length){box.innerHTML=`<div class=fileinner><div class=sec>Files</div>
   <div class=note>Nothing yet. Files you attach, papers it downloads, and plots it makes appear here.</div></div>`;return}
 const areas={generated:'Created by Orbit',uploaded:'You attached',papers:'Downloaded papers'};
 box.innerHTML='';
 const inner=el('<div class=fileinner></div>');box.appendChild(inner);
 const bar=el(`<div class=sel-bar>
   <span>sort</span>
   <select id=fsort style="max-width:150px">
    <option value=date>newest</option><option value=name>name</option>
    <option value=size>size</option><option value=kind>type</option></select>
   <span id=selinfo></span>
   <button class=ghost id=selall>select all</button>
   <button class=ghost id=selnone>clear</button>
   <button class=ghost id=selknow>add to knowledge</button>
   <button class=ghost id=seldel style="color:var(--err)">delete selected</button>
  </div>`);
 inner.appendChild(bar);
 const filt=el(`<div class=filters style="padding:0 0 12px">
   <button data-a=all class=on>All (${list.length})</button></div>`);
 ['generated','uploaded','papers'].forEach(a=>{
  const n=list.filter(f=>f.area===a).length;
  if(n)filt.appendChild(el(`<button data-a=${a}>${areas[a]} (${n})</button>`))});
 inner.appendChild(filt);
 const grid=el('<div class=filegrid></div>');inner.appendChild(grid);
 let picked=new Set(), curArea='all', sortBy='date';
 const upd=()=>{$('#selinfo').textContent=picked.size?picked.size+' selected':'';};
 const sorter=a=>({date:(x,y)=>y.mtime-x.mtime,name:(x,y)=>x.name.localeCompare(y.name),
   size:(x,y)=>y.bytes-x.bytes,kind:(x,y)=>x.kind.localeCompare(y.kind)}[a]);
 const draw=area=>{curArea=area;grid.innerHTML='';
  list.filter(f=>area==='all'||f.area===area).sort(sorter(sortBy)).forEach(f=>{
   const url='/api/ws/'+f.rel.split('/').map(encodeURIComponent).join('/');
   const c=el('<div class=fcard></div>');
   const th=el('<div class=thumb></div>');
   if(f.kind==='image'){const i=document.createElement('img');i.loading='lazy';i.src='/api/thumb/'+f.rel.split('/').map(encodeURIComponent).join('/');i.onerror=()=>{i.src=url};th.appendChild(i)}
   else th.appendChild(el(`<span>${ICON[f.kind]||ICON.other}</span>`));
   th.style.cursor='pointer';th.onclick=()=>window.open(url,'_blank');
   c.appendChild(th);
   const m=el('<div class=meta></div>');
   const b=document.createElement('b');b.textContent=f.name;b.title=f.rel;m.appendChild(b);
   const sm=document.createElement('small');
   sm.textContent=`${human(f.bytes)} \u00b7 ${new Date(f.mtime*1000).toLocaleDateString()}`;
   m.appendChild(sm);
   if(f.from_title){const src=document.createElement('small');
    src.style.display='block';src.style.marginTop='2px';src.style.color='var(--acc)';
    src.style.cursor='pointer';src.textContent='\u2190 '+f.from_title.slice(0,28);
    src.title='open the chat that made this';
    src.onclick=()=>{showChats();openSession(f.from_sid)};m.appendChild(src)}
   c.appendChild(m);
   const acts=el('<div class=acts></div>');
   const dl=document.createElement('a');dl.textContent='open';dl.href=url;dl.target='_blank';
   acts.appendChild(dl);
   const at=document.createElement('button');at.textContent='use in chat';
   at.onclick=()=>{showChats();q.value=(q.value+' '+f.rel).trim();q.focus();
    toast('referenced '+f.name)};
   acts.appendChild(at);
   const rm=document.createElement('button');rm.textContent='delete';
   rm.onclick=async()=>{if(!confirm('Delete '+f.name+'?'))return;
    if(await apiPost('/api/files/delete',{rel:f.rel},'delete'))toast('moved to bin');
    renderFiles()};
   acts.appendChild(rm);
   const rn=document.createElement('button');rn.textContent='rename';
   rn.onclick=async()=>{const n=prompt('New name',f.name);if(!n||n===f.name)return;
    await apiPost('/api/files/rename',{rel:f.rel,name:n},'rename');renderFiles()};
   acts.appendChild(rn);
   if(f.area==='generated'){const hi=document.createElement('button');hi.textContent='history';
    hi.onclick=()=>showCheckpoints(f.rel,f.name);acts.appendChild(hi)}
   const kb=document.createElement('button');kb.textContent='to knowledge';
   kb.onclick=async()=>{
    if(await apiPost('/api/knowledge/from_upload',{rel:f.rel},'adding to knowledge'))
     toast('added to knowledge')};
   acts.appendChild(kb);
   c.onclick=e=>{if(e.target.tagName==='BUTTON'||e.target.tagName==='A'||e.target.tagName==='IMG')return;
    if(picked.has(f.rel))picked.delete(f.rel);else picked.add(f.rel);
    c.classList.toggle('picked',picked.has(f.rel));upd()};
   if(picked.has(f.rel))c.classList.add('picked');
   c.appendChild(acts);grid.appendChild(c)})};
 setTimeout(()=>{
  const so=$('#fsort');if(so)so.onchange=()=>{sortBy=so.value;draw(curArea)};
  const sa=$('#selall');if(sa)sa.onclick=()=>{list.forEach(f=>picked.add(f.rel));draw(curArea);upd()};
  const sn=$('#selnone');if(sn)sn.onclick=()=>{picked.clear();draw(curArea);upd()};
  const sk=$('#selknow');if(sk)sk.onclick=async()=>{
   if(!picked.size)return toast('nothing selected');
   for(const rel of picked)await fetch('/api/knowledge/from_upload',{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify({rel})});
   toast(picked.size+' added to knowledge');picked.clear();renderFiles()};
  const sd=$('#seldel');if(sd)sd.onclick=async()=>{
   if(!picked.size)return toast('nothing selected');
   if(!confirm('Move '+picked.size+' file(s) to the recycle bin?'))return;
   for(const rel of picked)await fetch('/api/files/delete',{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify({rel})});
   picked.clear();renderFiles()};
 },0);
 filt.querySelectorAll('button').forEach(b=>b.onclick=()=>{
  filt.querySelectorAll('button').forEach(x=>x.classList.toggle('on',x===b));draw(b.dataset.a)});
 draw('all');
 if(fileTotal>list.length){
  const more=el(`<button class=ghost style="margin-top:14px">load ${fileTotal-list.length} more</button>`);
  more.onclick=()=>{fileLimit+=60;renderFiles()};inner.appendChild(more)}}

function showShortcuts(){
 $('#modalhost').innerHTML=`<div class=modal><div class="sheet auto" style="max-width:520px">
  <header><b>Keyboard shortcuts</b><button class=ghost style="margin-left:auto" id=kx>close</button></header>
  <div class=body><div class=shortcuts>
   <b class=kgroup>Writing</b>
   <span class=kbd>Enter</span><span>send (queues it while an answer runs)</span>
   <span class=kbd>&#8984;Enter</span><span>send into the running answer, as a note it reads next</span>
   <span class=kbd>Shift+Enter</span><span>new line</span>
   <span class=kbd>Ctrl+J</span><span>new line</span>
   <span class=kbd>/</span><span>commands</span>
   <span class=kbd>@</span><span>mention a file</span>
   <span class=kbd>!</span><span>shell mode — run a command yourself; the output joins the chat</span>
   <span class=kbd>#</span><span>save the line to memory</span>
   <span class=kbd>&#8593; / &#8595;</span><span>earlier messages you sent (empty box)</span>
   <span class=kbd>Ctrl+R</span><span>search what you sent before</span>
   <span class=kbd>Ctrl+L</span><span>clear the box</span>
   <b class=kgroup>While it works</b>
   <span class=kbd>Esc</span><span>stop the answer (or clear the box)</span>
   <span class=kbd>Esc Esc</span><span>rewind to an earlier message</span>
   <span class=kbd>Shift+Tab</span><span>cycle the permission mode (plan, accept edits, auto…)</span>
   <span class=kbd>Ctrl+O</span><span>show every tool call in full</span>
   <span class=kbd>Ctrl+T</span><span>show or hide the todo list</span>
   <b class=kgroup>Around the app</b>
   <span class=kbd>&#8984;K</span><span>new chat</span>
   <span class=kbd>&#8984;F</span><span>search chats</span>
   <span class=kbd>&#8984;,</span><span>settings</span>
   <span class=kbd>&#8984;J</span><span>files</span>
   <span class=kbd>&#8984;P</span><span>search everything</span>
   <span class=kbd>&#8984;G</span><span>jump to one of your messages</span>
   <span class=kbd>&#8997;&#8593; / &#8997;&#8595;</span><span>previous / next message of yours</span>
   <span class=kbd>&#8984;&#8679;K</span><span>new chat with a chosen model, folder or harness</span>
   <span class=kbd>Ctrl+&#96;</span><span>terminal in the chat's folder</span>
   <span class=kbd>Alt+1…9</span><span>go to a tab (&#8984;1…9 in Orbit for Mac)</span>
   <span class=kbd>?</span><span>this help — and <a href="#" onclick="openGuide();return false">the user guide</a> for everything else</span>
   <span class=kbd>Esc</span><span>close / cancel menu</span>
  </div></div></div></div>`;
 $('#kx').onclick=closeModal;
 $('#modalhost').querySelector('.modal').onclick=e=>{if(e.target.classList.contains('modal'))closeModal()}}

$('#log').addEventListener('scroll',()=>{
 const b=$('#log').scrollHeight-$('#log').scrollTop-$('#log').clientHeight;
 $('#tobottom').style.display=(b>250&&!stickToBottom)?'block':'none'});
$('#tobottom').onclick=()=>bottom(true);      // and follow it again from here on


/* ---------------- view switching ---------------- */
const PANES=['log','files','lib','tasks','trash','shared'];
// ---------------------------------------------------------------- shared projects inside Orbit: their chats in the sidebar, the project in a pane of its own
const SH={projects:[],chats:{},on:false};
async function shCall(d){try{const r=await fetch('/api/collabhost',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(d)});const j=await r.json().catch(()=>({}));if(!r.ok||j.error){return d.quiet?null:{error:(j.error||'error '+r.status)}}return j}catch(e){return null}}
async function loadShared(){
 const st=await shCall({op:'status'});
 if(!st||st.error||!st.enabled){SH.on=false;SH.projects=[];SH.chats={};drawSharedSidebar();return}
 SH.on=true;SH.projects=st.projects||[];
 for(const p of SH.projects){const r=await shCall({op:'project_chats',project:p.id});SH.chats[p.id]=r&&r.chats?r.chats:[]}
 drawSharedSidebar();
 const sig=JSON.stringify([SH.projects.map(p=>[p.id,p.name,p.members,p.frozen]),SH.chats]);
 if(sig!==SH._sig){SH._sig=sig;try{if(document.querySelector('.herogrid'))drawHero()}catch(x){}}}
function drawSharedSidebar(){
 const box=$('#sharedsecs');if(!box)return;box.innerHTML='';
 if(!SH.projects.length){{const b=el('<div class=srow style="display:flex;gap:6px;align-items:center;padding:5px 12px;cursor:pointer;opacity:.75"><span>＋</span><span>Share a project with people…</span></div>');b.onclick=newSharedProject;box.appendChild(b)}return}
 SH.projects.forEach(p=>{
  const key='sec_shared_'+p.id,open=PREF.get(key,'1')!=='x',chats=SH.chats[p.id]||[];
  const h=el(`<div class="sechead${open?'':' closed'}" title="A project you share with other people"><span class=caret>▾</span><span class=lbl>Shared · ${esc(p.name)}</span><span class=ct>${p.members}</span></div>`);
  const body=el(`<div class="secbody${open?'':' closed'}"><div class=slist></div></div>`);
  h.onclick=()=>{PREF.set(key,open?'x':'1');drawSharedSidebar()};
  h.oncontextmenu=e=>{e.preventDefault();e.stopPropagation();projectMenu(e,p)};
  box.appendChild(h);box.appendChild(body);
  if(!open)return;
  const list=body.firstChild;
  list.appendChild(sharedRow(p,{id:'',name:'Open the project'},true));
  chats.forEach(c=>list.appendChild(sharedRow(p,c,false)))});
 const nb=el('<div class=srow style="display:flex;gap:6px;align-items:center;padding:4px 12px;cursor:pointer;opacity:.6;font-size:var(--fs-sm)"><span>＋</span><span>New shared project…</span></div>');nb.onclick=newSharedProject;box.appendChild(nb);
}
function sharedRow(p,c,whole){
 const d=el(`<div class="srow" style="display:flex;gap:6px;align-items:center;padding:5px 8px;cursor:pointer;border-radius:8px"><span style="opacity:.6">${whole?'▣':'#'}</span><span class=t style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(c.name||c.id)}</span>${c.imported?'<span class=note title="Shared from this Mac">⇧</span>':''}</div>`);
 d.onclick=()=>openShared(p.id,whole?'':c.id);
 if(whole)d.oncontextmenu=e=>{e.preventDefault();e.stopPropagation();projectMenu(e,p)};
 if(!whole)d.oncontextmenu=e=>{e.preventDefault();e.stopPropagation();ctxMenu(e,[
  {icon:'⤴',label:'Open',run:()=>openShared(p.id,c.id)},
  {icon:'⇩',label:'Make this a local chat',sub:'copy it here, take it out of the project',run:async()=>{
    if(!confirm(`Copy "${c.name}" into your own chats and take it out of "${p.name}"?\n\nThe others can no longer read it there. Your copy has the messages as they are now.`))return;
    const r=await shCall({op:'copy_chat',project:p.id,chat:c.id});if(!r||r.error)return toast((r&&r.error)||'could not copy it');
    const x=await shCall({op:'remove_chat',project:p.id,chat:c.id});if(x&&x.error)toast(x.error);
    toast('now a local chat: '+r.title);loadSessions();loadShared()}},
  {icon:'⇧',label:'Make a copy in my chats',run:async()=>{const r=await shCall({op:'copy_chat',project:p.id,chat:c.id});if(!r||r.error)return toast((r&&r.error)||'could not copy it');toast('copied: '+r.title);loadSessions()}},
  ...(c.id==='main'?[]:['-',{icon:'✖',label:'Remove from the project',danger:true,run:async()=>{
    if(!confirm(`Remove "${c.name}" from "${p.name}"? Nobody in the project can read it afterwards. Your own chats are not touched.`))return;
    const r=await shCall({op:'remove_chat',project:p.id,chat:c.id});if(r&&r.error)return toast(r.error);loadShared()}}])])};
 return d}
// what a right-click on a shared project offers: the things people look for first, and the settings behind them
function projectMenu(e,p){
 const web=async()=>{const r=await shCall({op:'relay_status'});return r&&r.projects&&r.projects[p.id]};
 ctxMenu(e,[
  {icon:'⤴',label:'Open the project',run:()=>openShared(p.id)},
  {icon:'＋',label:'Invite someone…',run:()=>openProjectSettings(p.id,'people')},
  {icon:'⚙',label:'Project settings…',run:()=>openProjectSettings(p.id,'overview')},
  '-',
  {icon:'⇧',label:'Add a chat from this Mac…',run:()=>pickLocalChatFor(e,p)},
  {icon:'⧉',label:'Copy the web link',sub:'for people to open',run:async()=>{const w=await web();if(!w)return toast('The web link is off: open Project settings, Sharing and access');try{await navigator.clipboard.writeText(w.link);toast('web link copied')}catch(x){prompt('Copy this:',w.link)}}},
  {icon:'▣',label:'Open in my browser',run:async()=>{const r=await shCall({op:'open',project:p.id,launch:true});if(r&&r.error)toast(r.error)}},
  '-',
  p.frozen?{icon:'▶',label:'Lift the freeze',run:async()=>{await shCall({op:'resume',project:p.id});loadShared()}}
          :{icon:'❄',label:'Freeze everything',danger:true,run:async()=>{if(!confirm(`Freeze "${p.name}"? Nobody can write or run anything until you lift it.`))return;await shCall({op:'panic',project:p.id});loadShared()}}])}
async function pickLocalChatFor(e,p){
 const r=await shCall({op:'local_chats'});if(!r||r.error)return toast((r&&r.error)||'could not list your chats');
 const rows=(r.chats||[]).slice(0,25);if(!rows.length)return toast('You have no chats to add');
 ctxMenu(e,rows.map(c=>({icon:'#',label:c.title||'(untitled)',run:()=>shareChatInto(p,c.id)})))}
// the member page, inside Orbit, with a slim bar of the things the owner needs
function openShared(pid,chat){
 showPane('shared');const box=$('#shared');
 const sig=pid+'|'+(chat||'');
 const p=(SH.projects||[]).find(x=>x.id===pid)||{id:pid,name:'Shared project'};
 if(box.dataset.sig!==sig){
  box.dataset.sig=sig;
  box.innerHTML=`<div class=shbar style="display:flex;gap:8px;align-items:center;padding:6px 12px;border-bottom:1px solid var(--line);flex:none"><b class=shname style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap"></b><span class=note id=shinfo style="margin-left:0"></span><span style="flex:1"></span>
   <button class=ghost data-a=invite title="Invite someone">＋ Invite</button><button class=ghost data-a=settings title="People, access, models, rules">⚙ Project settings</button><button class=ghost data-a=reload title="Reload the page">⟳</button></div>
   <div style="position:relative;flex:1 1 auto;min-height:0"><iframe title="Shared project" style="border:0;position:absolute;inset:0;width:100%;height:100%" src="/shared/${encodeURIComponent(pid)}/?r=${Date.now()}#p=${encodeURIComponent(pid)}&t=orbit&n=${encodeURIComponent(PREF.get('shared_name','Me'))}${chat?'&c='+encodeURIComponent(chat):''}"></iframe></div>`;
  box.querySelector('.shname').textContent=p.name;
  box.querySelector('#shinfo').textContent=`${p.members||''} ${p.members===1?'person':'people'}${p.frozen?' · frozen':''}`;
  box.querySelector('[data-a=invite]').onclick=()=>openProjectSettings(pid,'people');
  box.querySelector('[data-a=settings]').onclick=()=>openProjectSettings(pid,'overview');
  box.querySelector('[data-a=reload]').onclick=()=>{const f=box.querySelector('iframe');f.src=f.src.replace(/\?r=\d+/,'?r='+Date.now())};
  box.querySelector('.shbar').oncontextmenu=e=>{e.preventDefault();projectMenu(e,p)}}}
// "Add to a shared project…" in a chat's menu: what would be shared is shown first
async function shareChatInto(p,sid){
 const pv=await shCall({op:'share_preview',project:p.id,chat:sid});if(!pv||pv.error)return toast((pv&&pv.error)||'could not look at that chat');
 const warn=(pv.warnings||[]).length?`\n\nWarning: it looks like it contains ${[...new Set(pv.warnings.map(w=>w.kind))].join(', ')}. Everyone in the project could read that.`:'';
 if(!confirm(`Add "${pv.title}" to "${p.name}"?\n\n${pv.messages} messages (what you and the model said; tool output and images are not copied) become a new chat in the project, visible to everyone in it. Your own chat stays as it is, and you can take it out of the project again at any time.${warn}`))return;
 const r=await shCall({op:'share_chat',project:p.id,chat:sid,confirm_secrets:!!warn});if(!r||r.error)return toast((r&&r.error)||'could not share it');
 toast('added to '+p.name);loadShared()}
async function addChatToShared(e,s){
 if(!SH.projects.length)return toast('No shared project yet: Settings, Shared projects');
 ctxMenu(e,[{icon:'←',label:'Back',run:()=>chatMenu(e,s)},'-',...SH.projects.map(p=>({icon:'▣',label:p.name,run:()=>shareChatInto(p,s.id)}))])}
setTimeout(loadShared,1500);setInterval(()=>{if(!document.hidden)loadShared()},30000);

function showPane(name){
 PANES.forEach(p=>{const e=$('#'+p);if(e)e.style.display=(p===name?'':'none')});
 if(name==='log')setTimeout(drawHero,0);
 setTimeout(drawOutline,0);
 $('.composer').style.display=(name==='log'?'':'none');
 ['chats','files','lib','tasks','trash'].forEach(n=>{
  const b=$('#nav_'+n);if(b)b.classList.toggle('on',(n==='chats'?'log':n)===name)});
 if(name==='files')renderFiles(); if(name==='tasks')renderTasks();
 if(name==='trash')renderTrash(); if(name==='lib')renderLibrary();
}
function showChats(){showPane('log')}
function showFiles(){showPane('files')}
$('#nav_chats').onclick=()=>showPane('log');
$('#nav_files').onclick=()=>showPane('files');
$('#nav_lib').onclick=()=>showPane('lib');
$('#nav_tasks').onclick=()=>showPane('tasks');
$('#nav_trash').onclick=()=>showPane('trash');


let libTab='knowledge';
async function renderLibrary(){
 const box=$('#lib');
 const info=await (await fetch('/api/info')).json();INFO=info;
 box.innerHTML=`<div class=pane>
   <div class=filters style="padding:0 0 14px">
     ${['knowledge','skills','agents','prompts'].map(t=>
       `<button data-l=${t} class="${t===libTab?'on':''}">${t[0].toUpperCase()+t.slice(1)}</button>`).join('')}
   </div><div id=libbody></div></div>`;
 box.querySelectorAll('[data-l]').forEach(b=>b.onclick=()=>{libTab=b.dataset.l;renderLibrary()});
 const body=$('#libbody');

 if(libTab==='knowledge'){
  const docs=await (await fetch('/api/knowledge')).json();
  const projOpts=`<option value="">everything (global)</option>`+
    Object.entries(PROJECTS).map(([id,p])=>`<option value="${id}">${esc(p.name)}</option>`).join('');
  body.innerHTML=`<div class=sec>Document library
    <small>— searched by search_knowledge before the web</small></div>
   <div id=klist></div>
   <div style="margin-top:12px;display:flex;gap:8px;align-items:center;flex-wrap:wrap">
    <button class=ghost id=k_add>Add documents</button>
    <button class=ghost id=k_reindex>Reindex</button>
    <span class=note id=k_note></span></div>
   <input type=file id=k_file multiple hidden>`;
  const kl=$('#klist');
  if(!docs.length)kl.innerHTML='<div class=note>Empty. Add PDFs, papers, protocols — anything readable.</div>';
  docs.forEach(d=>{
   const r=el('<div class=memrow></div>');
   r.appendChild(el(`<b>${esc(d.name)}</b>`));
   r.appendChild(el(`<span>${(d.bytes/1024).toFixed(0)} KB · ${d.chunks} chunks</span>`));
   const sel=el(`<select style="max-width:190px">${projOpts}</select>`);
   sel.value=d.project||'';
   sel.onchange=async()=>{await fetch('/api/knowledge/project',{method:'POST',
     headers:{'Content-Type':'application/json'},
     body:JSON.stringify({name:d.name,project:sel.value||null})});
    toast(sel.value?'scoped to project':'now global')};
   r.appendChild(sel);
   const del=el('<button class=ghost>delete</button>');
   del.onclick=async()=>{
    if(!confirm('Move '+d.name+' to the recycle bin?'))return;
    if(await apiPost('/api/knowledge/delete',{name:d.name},'delete'))toast('moved to bin');
    renderLibrary()};
   r.appendChild(del);kl.appendChild(r)});
  $('#k_add').onclick=()=>$('#k_file').click();
  $('#k_file').onchange=async e=>{$('#k_note').textContent='indexing…';
   for(const f of [...e.target.files]){const fd=new FormData();fd.append('file',f);
    await fetch('/api/knowledge/upload',{method:'POST',body:fd})}
   renderLibrary()};
  $('#k_reindex').onclick=async()=>{$('#k_note').textContent='reindexing…';
   const r=await (await fetch('/api/knowledge/reindex',{method:'POST'})).json();
   $('#k_note').textContent=`${r.docs} docs · ${r.chunks} chunks`};
 }

 if(libTab==='skills'){
  const sk=await (await fetch('/api/skills')).json();
  body.innerHTML=`<div class=sec>Skills <small>— procedures the model loads on demand</small></div>
   <div id=sklist></div>
   <div class=grid style="margin-top:12px"><label>Skill name</label>
    <input type=text id=sk_name placeholder="wgbs-qc"></div>
   <textarea class=ta id=sk_text style="min-height:200px;margin-top:8px"
     placeholder="# WGBS QC&#10;&#10;1. Check conversion rate against the lambda spike-in…"></textarea>
   <button class=ghost id=sk_add style="margin-top:8px">Save skill</button>`;
  const sl=$('#sklist');
  if(!sk.length)sl.innerHTML='<div class=note>No skills yet. Use “save as skill” on a good answer.</div>';
  sk.forEach(k=>{const r=el('<div class=memrow></div>');
   r.appendChild(el(`<b>${esc(k.name)}</b>`));r.appendChild(el(`<span>${esc(k.title)}</span>`));
   const ed=el('<button class=ghost>edit</button>');
   ed.onclick=async()=>{const d=await (await fetch('/api/skill/'+k.name)).json();
    $('#sk_name').value=k.name;$('#sk_text').value=d.text;$('#sk_text').scrollIntoView()};
   const del=el('<button class=ghost>delete</button>');
   del.onclick=async()=>{if(await apiPost('/api/skills/delete',{name:k.name},'deleting the skill'))
     toast(k.name+' is in the bin — restore it from there');renderLibrary()};
   r.appendChild(ed);r.appendChild(del);sl.appendChild(r)});
  $('#sk_add').onclick=async()=>{const n=$('#sk_name').value.trim();
   if(!n||!$('#sk_text').value.trim())return;
   await fetch('/api/skills/save',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({name:n,text:$('#sk_text').value})});renderLibrary()};
 }

 if(libTab==='agents'){
  const d=await (await fetch('/api/agents')).json();const ags=d.agents||{};
  body.innerHTML=`<div class=sec>Agents <small>— instructions plus a restricted tool set</small></div>
   <div id=alist></div>
   <div class=grid style="margin-top:12px">
    <label>Name</label><input type=text id=a_name placeholder="paper-reviewer">
    <label>Description</label><input type=text id=a_desc placeholder="critiques methods and stats"></div>
   <textarea class=ta id=a_ins style="min-height:130px;margin-top:8px"
     placeholder="Instructions this agent always follows."></textarea>
   <div class=sec>Tools it may use <small>— none checked = all tools</small></div>
   <div class=toolgrid id=a_tools></div>
   <button class=ghost id=a_add style="margin-top:10px">Save agent</button>`;
  const al=$('#alist');
  if(!Object.keys(ags).length)al.innerHTML='<div class=note>No agents yet.</div>';
  Object.entries(ags).forEach(([n,a])=>{const r=el('<div class=memrow></div>');
   r.appendChild(el(`<b>${esc(n)}</b>`));
   r.appendChild(el(`<span>${esc(a.desc||'')} · ${(a.tools||[]).length||'all'} tools</span>`));
   const ed=el('<button class=ghost>edit</button>');
   ed.onclick=()=>{$('#a_name').value=n;$('#a_desc').value=a.desc||'';$('#a_ins').value=a.instructions||'';
    const t=a.tools||[];document.querySelectorAll('#a_tools input').forEach(c=>c.checked=t.includes(c.dataset.at))};
   const del=el('<button class=ghost>delete</button>');
   del.onclick=async()=>{await fetch('/api/agents/delete',{method:'POST',
     headers:{'Content-Type':'application/json'},body:JSON.stringify({name:n})});
    renderLibrary();loadAgents()};
   r.appendChild(ed);r.appendChild(del);al.appendChild(r)});
  const at=$('#a_tools');
  (info.all_tools||info.tools||[]).forEach(n=>{const l=document.createElement('label');
   const c=document.createElement('input');c.type='checkbox';c.dataset.at=n;l.appendChild(c);
   const sp=document.createElement('span');sp.textContent=n;l.appendChild(sp);at.appendChild(l)});
  $('#a_add').onclick=async()=>{const n=$('#a_name').value.trim();if(!n)return;
   const tools=[...document.querySelectorAll('#a_tools input')].filter(c=>c.checked).map(c=>c.dataset.at);
   await fetch('/api/agents/save',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({name:n,desc:$('#a_desc').value,instructions:$('#a_ins').value,tools})});
   renderLibrary();loadAgents()};
 }

 if(libTab==='prompts'){
  PROMPTS=await (await fetch('/api/prompts')).json();
  body.innerHTML=`<div class=sec>Saved prompts <small>— become slash commands</small></div>
   <div id=plist></div>
   <div class=grid style="margin-top:12px">
    <label>Command name</label><input type=text id=p_name placeholder="review">
    <label>Description</label><input type=text id=p_desc placeholder="critique a result"></div>
   <textarea class=ta id=p_text style="min-height:130px;margin-top:8px"
     placeholder="The prompt inserted when you type the command."></textarea>
   <button class=ghost id=p_add style="margin-top:8px">Save prompt</button>`;
  const pl=$('#plist');
  if(!Object.keys(PROMPTS).length)pl.innerHTML='<div class=note>No saved prompts yet.</div>';
  Object.keys(PROMPTS).forEach(n=>{const r=el('<div class=memrow></div>');
   r.appendChild(el(`<b>/${esc(n)}</b>`));r.appendChild(el(`<span>${esc(PROMPTS[n].desc||'')}</span>`));
   const ed=el('<button class=ghost>edit</button>');
   ed.onclick=()=>{$('#p_name').value=n;$('#p_desc').value=PROMPTS[n].desc||'';
    $('#p_text').value=PROMPTS[n].text||''};
   const del=el('<button class=ghost>delete</button>');
   del.onclick=async()=>{await fetch('/api/prompts/delete',{method:'POST',
     headers:{'Content-Type':'application/json'},body:JSON.stringify({name:n})});renderLibrary()};
   r.appendChild(ed);r.appendChild(del);pl.appendChild(r)});
  $('#p_add').onclick=async()=>{const n=$('#p_name').value.trim().replace(/^\//,'');
   if(!n||!$('#p_text').value.trim())return;
   await fetch('/api/prompts/save',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({name:n,desc:$('#p_desc').value,text:$('#p_text').value})});renderLibrary()};
 }
}

/* ---------------- scheduler ---------------- */
// the model picker's choices, grouped, for a scheduled task ("" = the chat's / the default)
function modelOptions(cur,emptyLabel,only){
 const groups={};(MODELS.models||[]).filter(m=>!m.switch&&(!only||only(m.id))).forEach(m=>{(groups[m.provider_label]=groups[m.provider_label]||[]).push(m)});
 const known=(MODELS.models||[]).some(m=>m.id===cur);
 return `<option value="">${esc(emptyLabel||'default model')}</option>`+(cur&&!known?`<option value="${esc(cur)}" selected>${esc(cur)}</option>`:'')+Object.entries(groups).map(([g,list])=>
  `<optgroup label="${esc(g)}">${list.map(m=>`<option value="${esc(m.id)}"${m.id===cur?' selected':''}>${esc(m.label||m.model)}${m.ready===false?' — needs a key':''}${esc(opSuffix(m.offpeak))}</option>`).join('')}</optgroup>`).join('')}
// Cheaper hours (bin/offpeak.py): a model's discount window, as a coloured mark in menus
function opLive(op){
 // the server's state may be minutes old: flip it by the window's own times
 if(!op)return null;const now=Date.now()/1000;
 if(op.active&&op.ends_at&&now>=op.ends_at)return {...op,active:false,stale:true};
 if(!op.active&&op.starts_at&&typeof op.starts_at==='number'&&now>=op.starts_at)return {...op,active:true,stale:true};
 return op}
function opTime(ts){return new Date(ts*1000).toLocaleTimeString([], {hour:'numeric',minute:'2-digit'})}
// "3:00 AM", or "Mon 3:00 AM" when it is not today
function opWhen(ts){const d=new Date(ts*1000);return (d.toDateString()===new Date().toDateString()?'':d.toLocaleDateString([], {weekday:'short'})+' ')+opTime(ts)}
function opSuffix(op){op=opLive(op);if(!op)return '';
 return op.active?` · 🟢 ${op.what} now`:` · 🟠 ${op.what}${op.starts_at&&typeof op.starts_at==='number'?' from '+opWhen(op.starts_at):' at set hours'}`}
function drawOffpeak(){
 const b=$('#opbadge');if(!b)return;
 const cur=MODELS.current||MODELS.default||'';
 const m=(MODELS.models||[]).find(x=>x.id===cur);
 const op=opLive(m&&m.offpeak);
 if(!op){b.style.display='none';return}
 b.style.display='';b.className='opbadge '+(op.active?'on':'later');
 b.textContent=op.active?`🟢 ${op.what}${op.ends_at?' · until '+opWhen(op.ends_at):''}`:`🟠 ${op.quota?'full rate':'peak price'}${op.starts_at&&typeof op.starts_at==='number'?' · '+op.what+' from '+opWhen(op.starts_at):''}`;
 b.title=`Cheaper hours for ${m.label||m.model}: ${(op.windows_local||[]).join(', ')} your time (${(op.windows||[]).join(', ')}) — click for details`;
 if(op.stale&&!drawOffpeak._reloading){drawOffpeak._reloading=true;setTimeout(async()=>{await loadModels();drawOffpeak._reloading=false},1500)}}
setInterval(drawOffpeak,60000);
async function showOffpeak(){
 let d;try{d=await (await fetch('/api/offpeak')).json()}catch(e){return}
 const cur=MODELS.current||MODELS.default||'';const m=(MODELS.models||[]).find(x=>x.id===cur);
 openSheet('Cheaper hours',body=>{
  const pols=d.policies||[];
  const frac=v=>typeof v==='number'?`${Math.round((1-v)*100)}% off`:'';
  const parts=disc=>Object.entries(disc||{}).map(([k,v])=>k==='quota_multiplier'?`requests count ${v}× against the plan`:`${k.replace(/_/g,' ')}: ${frac(v)}`).join(' · ');
  body.innerHTML=`<div class=note style="margin-bottom:8px">Some providers charge less at certain hours, and some plans count less of your allowance then. It depends on <b>where</b> you use a model: DeepSeek through its own API or through OpenCode Go follows DeepSeek's hours, while the same model elsewhere may not. Models in the pickers are marked 🟢 while it is cheaper and 🟠 when it is cheaper at other hours. Times are shown in the provider's time zone and in yours.${m&&m.offpeak?'':' The model this chat uses has no cheaper hours.'}</div>`+
   (pols.length?'':'<div class=note>No provider in Orbit\'s list has time-based pricing on record.</div>');
  pols.forEach(p=>{const st=p.status||{};
   const box=el(`<details class=jobrow ${m&&m.id&&m.id.includes(':'+p.provider+'/')?'open':''}><summary style="cursor:pointer;display:flex;gap:8px;align-items:center"><span class="opdot ${st.active?'on':'later'}"></span><b></b><span class=sub style="margin-left:auto"></span></summary><div class=grid style="margin-top:8px"></div></details>`);
   box.querySelector('b').textContent=p.provider+(p.applies_to?' · '+p.applies_to:'');
   box.querySelector('.sub').textContent=st.label||'';
   // the next 24 hours: green while it is cheaper, with a countdown to the next change
   {const now=Date.now()/1000,H=86400;
    const bar=el('<div style="position:relative;height:14px;border-radius:7px;background:color-mix(in srgb,#d69a2a 30%,transparent);margin:8px 0 2px;overflow:hidden"></div>');
    (st.spans||[]).forEach(([a,b])=>{const seg=document.createElement('div');
     seg.style.cssText=`position:absolute;top:0;bottom:0;left:${Math.max(0,(a-now)/H*100)}%;width:${Math.max(0.5,(b-a)/H*100)}%;background:#2d9d5a`;bar.appendChild(seg)});
    const ticks=el('<div style="display:flex;justify-content:space-between;font-size:10.5px;color:var(--dim)"></div>');
    [0,6,12,18,24].forEach(h=>{const t=document.createElement('span');t.textContent=h===0?'now':opTime(now+h*3600);ticks.appendChild(t)});
    const next=st.active?st.ends_at:st.starts_at;
    const cd=el('<div class=note style="font-size:12px"></div>');
    if(typeof next==='number'){const mins=Math.max(0,Math.round((next-now)/60));
     cd.textContent=(st.active?'cheaper for another ':'full rate for another ')+(mins>=60?Math.floor(mins/60)+' h ':'')+(mins%60)+' min — '+(st.active?'until ':'cheaper from ')+opWhen(next)}
    box.insertBefore(cd,box.querySelector('.grid'));box.insertBefore(ticks,cd);box.insertBefore(bar,ticks)}
   const g=box.querySelector('.grid');
   const row=(k,v)=>{if(!v)return;const l=el('<label></label>');l.textContent=k;const x=el('<div></div>');x.textContent=v;g.appendChild(l);g.appendChild(x)};
   row('Peak',(st.peak||'').replace(/^peak:\s*/,''));row('Cheaper hours (provider)',(st.windows||[]).join(', '));row('Cheaper hours (your time, this week)',(st.windows_local||[]).join(', '));
   row('What you pay then',parts(p.discount));row('Models',(p.models||['*']).map(x=>x==='*'?'all':x.replace(/\*$/,'…')).join(', ')+((p.exclude||[]).length?' — except '+p.exclude.join(', '):''));
   row('In force',[p.effective?'from '+p.effective:'',p.ends?'until '+p.ends:''].filter(Boolean).join(' ')||'no end date announced');
   row('Notes',p.note);row('Their words',p.quote?'“'+p.quote+'”':'');row('Checked',p.checked_at);
   if((p.sources||[]).length){const l=el('<label>Source</label>');const x=el('<div></div>');
    p.sources.forEach(u=>{const a=document.createElement('a');a.href=u;a.target='_blank';a.rel='noopener noreferrer';a.textContent=u;a.style.display='block';x.appendChild(a)});g.appendChild(l);g.appendChild(x)}
   body.appendChild(box)})},{sub:'what providers charge by the hour'})}
function modelName(id){if(!id)return '';const m=(MODELS.models||[]).find(x=>x.id===id);return m?(m.label||m.model):id}
const WD=['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];
function jobWhen(j){
 if(j.every==='once')return 'once, '+(j.at_ts?new Date(j.at_ts*1000).toLocaleString([], {weekday:'short',month:'short',day:'numeric',hour:'numeric',minute:'2-digit'}):'?');
 if(j.every==='daily')return 'every day at '+(j.at||'09:00');
 if(j.every==='weekly')return 'every '+WD[j.weekday||0]+' at '+(j.at||'09:00');
 return 'every '+(+j.n||'?')+' '+(j.every==='hours'?'hours':'minutes')}
// The Scheduled tab: messages waiting to be sent in any chat, and tasks that run on
// their own — all of it editable in place (text, time, repeat, model…).
async function renderTasks(){
 const box=$('#tasks');
 if(!(MODELS.models||[]).length)await loadModels();
 let d;try{d=await (await fetch('/api/scheduled',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'})).json()}
 catch(e){box.innerHTML='<div class=pane><div class=note>could not load the schedule</div></div>';return}
 const keepOpen=box._open||{};
 box.innerHTML=`<div class=pane>
  <div class=sec style="display:flex;align-items:center;gap:8px">Scheduled messages <small>— sent in their chat at the time set, as if you sent them</small></div>
  <div id=smlist></div>
  <div class=sec style="display:flex;align-items:center;gap:8px">Scheduled tasks <small>— prompts that run on their own; each result lands in a chat</small><button class=ghost id=j_new style="margin-left:auto">＋ New task</button></div>
  <div id=jobnew></div><div id=joblist></div>
  <div class=sec id=h2sec>Cluster jobs <small>— live from qstat</small></div>
  <div id=h2box><div class=note>checking…</div></div></div>`;
 // ---- messages
 const sm=$('#smlist');
 if(!(d.messages||[]).length)sm.innerHTML='<div class=note>Nothing scheduled. In any chat, write a message and press ⏱ beside Send (or type /later 9am …).</div>';
 (d.messages||[]).forEach(it=>{
  const r=el(`<div class=jobrow><div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
    <span class="qwhen${it.missed?' missed':''}" title="change when it goes out"></span>
    <a class=chatlink href="#" title="open the chat"></a>${it.attachments?`<span class=sub>+${it.attachments} attached</span>`:''}
    <span style="margin-left:auto;display:flex;gap:5px"><button class=ghost data-a=now>send now</button><button class=ghost data-a=rm>remove</button></span></div>
   <textarea class="ta smtext" rows=2></textarea>
   <div class=row2 style="align-items:center"><span class=sub>model</span><select class=smmodel style="max-width:340px"></select><span class="sub smsaved"></span></div></div>`);
  const when=r.querySelector('.qwhen');when.textContent=it.missed?'missed · was '+whenLabel(it.at):whenLabel(it.at,it.repeat);
  const link=r.querySelector('.chatlink');link.textContent=it.title||'(untitled chat)';
  link.onclick=e=>{e.preventDefault();showPane('log');openSession(it.sid)};
  const upd=async(fields,msg)=>{const res=await apiPost('/api/queue',{sid:it.sid,op:'update',id:it.id,...fields},'save');
   if(res){const x=r.querySelector('.smsaved');x.textContent=msg||'saved';setTimeout(()=>x.textContent='',1800);if(fields.at!==undefined||fields.repeat!==undefined)renderTasks()}
   return res};
  when.onclick=e=>{e.stopPropagation();schedPopover(when,{at:it.at,repeat:it.repeat,title:'When it goes out',
   onPick:(at,repeat)=>upd({at,repeat})})};
  const ta=r.querySelector('.smtext');ta.value=it.text;ta.style.height=Math.min(200,Math.max(44,ta.scrollHeight+2))+'px';
  ta.onchange=()=>{const v=ta.value.trim();if(!v){ta.value=it.text;return toast('a message cannot be empty — remove it instead')}upd({text:v}).then(x=>{if(x)it.text=v})};
  const ms=r.querySelector('.smmodel');ms.innerHTML=modelOptions(it.model||'',"the chat's model — "+(modelName(it.chat_model)||'default'));
  ms.onchange=()=>upd({model:ms.value},ms.value?'will send on '+modelName(ms.value):"will use the chat's model");
  r.querySelector('[data-a=now]').onclick=async()=>{const x=await apiPost('/api/queue',{sid:it.sid,op:'now',id:it.id},'send');if(x){toast('sending in '+(it.title||'the chat'));renderTasks();loadSessions()}};
  r.querySelector('[data-a=rm]').onclick=async()=>{if(it.repeat&&!confirm('Stop this repeating message?'))return;
   if(await apiPost('/api/queue',{sid:it.sid,op:'remove',id:it.id},'remove')){renderTasks();loadSessions()}};
  sm.appendChild(r)});
 // ---- tasks
 const jl=$('#joblist');
 const jobs=(d.tasks||[]);
 if(!jobs.length)jl.innerHTML='<div class=note>No scheduled tasks yet.</div>';
 jobs.forEach(j=>{
  const r=el('<div class=jobrow></div>');
  const head=el(`<div style="display:flex;gap:8px;align-items:baseline;flex-wrap:wrap"><h4 style="margin:0"></h4><span class=sub></span></div>`);
  head.querySelector('h4').textContent=j.name||j.id;
  const nxt=j.next_ts?new Date(j.next_ts*1000):null;
  head.querySelector('.sub').textContent=[jobWhen(j),j.enabled===false?'paused':(nxt?'next '+whenLabel(j.next_ts):'finished'),
   j.stop_at?'stops by '+j.stop_at:'',j.until_done?(j.done_at?'done':'until it is done'):'','on '+(modelName(j.model)||(j.sid?"its chat's model":'the default model')),
   j.sid?'in its chat':'new chat each run',j.agent?'agent '+j.agent:''].filter(Boolean).join(' · ');
  r.appendChild(head);
  const pr=el('<div class=sub style="margin-top:4px;white-space:pre-wrap;max-height:3.2em;overflow:hidden"></div>');pr.textContent=j.prompt||'';r.appendChild(pr);
  if(j.last_run){const res=el(`<div class=res><b>${j.last_ok?'ok':'failed'}</b> ${esc(new Date(j.last_run*1000).toLocaleString())} · </div>`);
   res.appendChild(document.createTextNode(String(j.last_result||'').slice(0,220)));r.appendChild(res)}
  const row=el('<div class=row2></div>');
  const b=(label,fn)=>{const x=el(`<button class=ghost>${label}</button>`);x.onclick=fn;row.appendChild(x);return x};
  const form=el('<div></div>');
  b('edit',()=>{if(form.firstChild){form.innerHTML='';delete box._open[j.id];return}box._open=box._open||{};box._open[j.id]=1;form.appendChild(jobForm(j))});
  b('run now',async()=>{if(!confirm('Run “'+(j.name||j.id)+'” now?'))return;toast('running…');
   await apiPost('/api/schedule/run',{id:j.id},'run');setTimeout(renderTasks,3000)});
  b(j.enabled===false?'enable':'pause',async()=>{if(await apiPost('/api/schedule/save',{job:{id:j.id,enabled:j.enabled===false}},'pause'))renderTasks()});
  b('open result',()=>{if(j.last_sid){showPane('log');openSession(j.last_sid)}else toast('no run yet')});
  b('delete',async()=>{if(!confirm('Delete the task “'+(j.name||j.id)+'”?'))return;
   await apiPost('/api/schedule/delete',{id:j.id},'delete');renderTasks()});
  r.appendChild(row);r.appendChild(form);
  if(keepOpen[j.id]){box._open=keepOpen;form.appendChild(jobForm(j))}
  jl.appendChild(r)});
 $('#j_new').onclick=()=>{const nb=$('#jobnew');if(nb.firstChild){nb.innerHTML='';return}
  nb.appendChild(el('<div class=jobrow></div>')).appendChild(jobForm(null))};
 (async()=>{
   const hb=$('#h2box'); if(!hb)return;
   try{
    const r=await (await fetch('/api/h2/jobs',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'})).json();
    if(r.off){hb.remove();$('#h2sec')?.remove();return}   // no cluster set up
    if(r.error){hb.innerHTML=`<div class=note style="color:var(--err)">${esc(r.error.slice(0,140))}</div>`;return}
    if(!r.jobs.length){hb.innerHTML='<div class=note>No jobs queued or running.</div>';return}
    hb.innerHTML='';
    r.jobs.forEach(j=>{
     const row=el('<div class=jobrow></div>');
     const state={r:'running',qw:'queued',Eqw:'error'}[j.state]||j.state;
     row.appendChild(el(`<h4>${esc(j.name)} <span class=sub>#${esc(j.id)}</span></h4>`));
     row.appendChild(el(`<div class=sub>${esc(state)} · ${esc(j.since)} · ${esc(j.slots||'?')} slots</div>`));
     const r2=el('<div class=row2></div>');
     const lg=el('<button class=ghost>tail log</button>');
     lg.onclick=async()=>{lg.textContent='loading…';
      const d=await (await fetch('/api/h2/log',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:j.id})})).json();
      lg.textContent='tail log';
      const pre=row.querySelector('pre')||el('<pre style="background:var(--panel);padding:9px;border-radius:8px;font-size:11.5px;max-height:240px;overflow:auto;margin-top:8px"></pre>');
      pre.textContent=d.log||'(no log found)';row.appendChild(pre)};
     const est=el('<button class=ghost>estimate</button>');
     est.onclick=async()=>{const d=await (await fetch('/api/h2/estimate',{method:'POST',headers:{'Content-Type':'application/json'},
       body:JSON.stringify({name:j.name.slice(0,8)})})).json();
      toast(d.runs?`median ${d.median_min} min over ${d.runs} past runs`:'no history for this job name')};
     r2.appendChild(lg);r2.appendChild(est);row.appendChild(r2);hb.appendChild(row)});
   }catch(e){hb.innerHTML='<div class=note>cluster unreachable</div>'}
  })();
}
// the edit form for a task (j = null: a new one)
function jobForm(j){
 const isNew=!j;j=j||{every:'daily',at:'09:00',enabled:true};
 const agents=Object.keys((INFO.agents)||{});
 const pad=n=>String(n).padStart(2,'0');
 const dtl=ts=>{const x=ts?new Date(ts*1000):new Date(Date.now()+36e5);return `${x.getFullYear()}-${pad(x.getMonth()+1)}-${pad(x.getDate())}T${pad(x.getHours())}:${pad(x.getMinutes())}`};
 const chats=SESSIONS.filter(s=>!s.external&&s.n).slice(0,60);
 if(j.sid&&!chats.some(s=>s.id===j.sid))chats.unshift({id:j.sid,title:'(this task’s chat)'});
 const f=el(`<div class=grid style="margin-top:10px">
   <label>Name</label><input type=text data-f=name>
   <label>Prompt</label><textarea class=ta data-f=prompt style="min-height:110px"></textarea>
   <label>Repeat</label><select data-f=every><option value=once>once</option><option value=daily>every day</option><option value=weekly>every week</option><option value=hours>every N hours</option><option value=minutes>every N minutes</option></select>
   <label class=fx-time>Time</label><input class=fx-time type=time data-f=at>
   <label class=fx-wd>Day</label><select class=fx-wd data-f=weekday>${WD.map((w,i)=>`<option value=${i}>${w}</option>`).join('')}</select>
   <label class=fx-n>Every N</label><input class=fx-n type=number min=1 data-f=n>
   <label class=fx-once>Date and time</label><input class=fx-once type=datetime-local data-f=at_ts>
   <label>Stop by</label><input type=time data-f=stop_at><div class=hint2>optional: the run paces itself to finish by then</div>
   <label>Model</label><select data-f=model>${modelOptions(j.model||'',j.sid?"the chat's model":'the default model')}</select>
   <label>Runs in</label><select data-f=sid><option value="">a new chat each time</option>${chats.map(c=>`<option value="${esc(c.id)}">${esc((c.title||'(untitled)').slice(0,70))}</option>`).join('')}</select>
   <label>Project</label><select data-f=project><option value="">none</option>${Object.entries(PROJECTS||{}).map(([pid,p])=>`<option value="${esc(pid)}">${esc(p.name)}</option>`).join('')}</select>
   <label>Agent</label><select data-f=agent><option value="">none</option>${agents.map(a=>`<option>${esc(a)}</option>`).join('')}</select>
   <label>Until it's done</label><div><input type=checkbox data-f=until_done> <span class=hint2>after each run, check the prompt against what happened, and stop repeating once it is met — "every night, until the tests pass"</span></div>
   <label>Enabled</label><input type=checkbox data-f=enabled style="justify-self:start">
   <div></div><div style="display:flex;gap:7px"><button class=sendbtn style="height:32px;padding:0 14px" data-a=save>${isNew?'Add task':'Save'}</button><button class=ghost data-a=cancel>Cancel</button><span class="sub fsaved"></span></div></div>`);
 const F=k=>f.querySelector(`[data-f=${k}]`);
 F('name').value=j.name||'';F('prompt').value=j.prompt||'';F('every').value=j.every||'daily';F('at').value=j.at||'09:00';
 F('weekday').value=String(j.weekday||0);F('n').value=j.n||(j.every==='hours'?6:30);F('at_ts').value=dtl(j.at_ts);
 F('stop_at').value=j.stop_at||'';F('sid').value=j.sid||'';F('project').value=j.project||'';F('agent').value=j.agent||'';F('enabled').checked=j.enabled!==false;F('until_done').checked=!!j.until_done;
 const show=()=>{const e=F('every').value;
  f.querySelectorAll('.fx-time').forEach(x=>x.style.display=['daily','weekly'].includes(e)?'':'none');
  f.querySelectorAll('.fx-wd').forEach(x=>x.style.display=e==='weekly'?'':'none');
  f.querySelectorAll('.fx-n').forEach(x=>x.style.display=['hours','minutes'].includes(e)?'':'none');
  f.querySelectorAll('.fx-once').forEach(x=>x.style.display=e==='once'?'':'none')};
 F('every').onchange=show;show();
 f.querySelector('[data-a=cancel]').onclick=()=>{if(isNew)f.closest('.jobrow').remove();else{f.remove();if($('#tasks')._open)delete $('#tasks')._open[j.id]}};
 f.querySelector('[data-a=save]').onclick=async()=>{
  const e=F('every').value;
  const job={name:F('name').value.trim(),prompt:F('prompt').value.trim(),every:e,model:F('model').value||null,
   sid:F('sid').value||null,project:F('project').value||null,agent:F('agent').value||null,stop_at:F('stop_at').value||null,enabled:F('enabled').checked,
   until_done:F('until_done').checked};
  if(!isNew)job.id=j.id;
  if(e==='daily'||e==='weekly')job.at=F('at').value;
  if(e==='weekly')job.weekday=+F('weekday').value;
  if(e==='hours'||e==='minutes')job.n=+F('n').value;
  if(e==='once'){const v=F('at_ts').value;if(!v)return toast('choose the date and time');job.at_ts=new Date(v).getTime()/1000;
   if(job.at_ts<Date.now()/1000&&(isNew||job.at_ts!==j.at_ts))return toast('that time has passed')}
  if(!job.prompt)return toast('a task needs a prompt — what should it do each time?');
  const res=await apiPost('/api/schedule/save',{job},'save task');
  if(res){toast(isNew?'task added':'task saved');if($('#tasks')._open)delete $('#tasks')._open[j.id];renderTasks()}};
 return f}

/* ---------------- trash ---------------- */
async function renderTrash(){
 const box=$('#trash');
 const list=await (await fetch('/api/trash')).json();
 box.innerHTML=`<div class=pane><div class=sec>Recycle bin
   <small>— items are permanently removed after the retention period (Settings → General)</small></div>
  <div id=trashlist></div>
  <button class=ghost id=purgeall style="margin-top:12px">Empty bin now</button></div>`;
 const tl=$('#trashlist');
 if(!list.length){tl.innerHTML='<div class=note>Bin is empty.</div>'}
 list.forEach(t=>{
  const r=el('<div class=memrow></div>');
  r.appendChild(el(`<b>${esc(t.title||t.original.split('/').pop())}</b>`));
  r.appendChild(el(`<span>${t.kind} · deleted ${t.age_days}d ago · purges in ${t.purges_in_days}d</span>`));
  const rest=el('<button class=ghost>restore</button>');
  rest.onclick=async()=>{
   if(await apiPost('/api/trash/restore',{name:t.name},'restore'))toast('restored');
   renderTrash();loadSessions()};
  const perm=el('<button class=ghost style="color:var(--err)">delete forever</button>');
  perm.onclick=async()=>{if(!confirm('Permanently delete? This cannot be undone.'))return;
   await apiPost('/api/trash/purge',{name:t.name},'permanent delete');renderTrash()};
  r.appendChild(rest);r.appendChild(perm);tl.appendChild(r)});
 $('#purgeall').onclick=async()=>{if(!confirm('Permanently delete everything in the bin?'))return;
  for(const t of list){await fetch('/api/trash/purge',{method:'POST',
   headers:{'Content-Type':'application/json'},body:JSON.stringify({name:t.name})})}
  renderTrash()};
}

/* ---------------- temporary chat ---------------- */
let tempMode=false;
$('#tempbtn').onclick=async()=>{
 if(tempMode)clearDraft(sid);
 tempMode=!tempMode;
 const d=await (await fetch('/api/temp',{method:'POST',headers:{'Content-Type':'application/json'},
  body:JSON.stringify({on:tempMode})})).json();
 stopLive(); sid=d.sid; chatChanged(null); syncBusy();   // without this the next message went to the OLD
 wrap.innerHTML='';$('#title').textContent=tempMode?'Temporary chat':'New chat';
 $('#tempbtn').style.borderColor=tempMode?'var(--err)':'';
 $('#tempbtn').style.color=tempMode?'var(--err)':'';
 $('#burnbtn').style.display=tempMode?'':'none';
 if(tempMode)sysline('Temporary chat: nothing is written to disk. Closing or burning leaves no trace.');
 loadSessions()};
$('#burnbtn').onclick=async()=>{
 if(!confirm('Erase this conversation completely? It cannot be recovered.'))return;
 clearDraft(sid);
 const d=await (await fetch('/api/burn',{method:'POST',headers:{'Content-Type':'application/json'},
  body:JSON.stringify({sid})})).json();
 if(!d.ok){toast(d.error||'nothing erased');return}
 stopLive(); sid=d.sid; chatChanged(null); syncBusy();
 wrap.innerHTML='';sysline('erased');loadSessions()};
addEventListener('beforeunload',()=>{
 // names the chat, so the server can refuse if it isn't the temporary one
 if(tempMode&&sid)navigator.sendBeacon('/api/burn',new Blob([JSON.stringify({sid})],{type:'application/json'}))});

/* ---------------- command palette ---------------- */
let pal=null,palSel=0,palItems=[];
function closePal(){if(pal){pal.remove();pal=null}}
// What the palette searched last, so an empty box is not an empty page.
function palHistory(){try{return JSON.parse(PREF.get('palhist','[]'))}catch(e){return []}}
function palRemember(term){
 if(!term||term.length<2)return;
 const h=[term].concat(palHistory().filter(x=>x!==term)).slice(0,6);
 PREF.set('palhist',JSON.stringify(h))}
/// The matched part of a result, marked. Escapes everything: these are file names and
/// message text, and one of them will contain a < sooner or later.
function palMark(text,term){
 const t=String(text||'');
 if(!term)return esc(t);
 const i=t.toLowerCase().indexOf(term);
 if(i<0)return esc(t);
 return esc(t.slice(0,i))+'<mark>'+esc(t.slice(i,i+term.length))+'</mark>'+esc(t.slice(i+term.length));
}

const PAL_SECTIONS=['cmd','chat','in chat','file'];
const PAL_CAP=5;            // per kind, so one noisy kind cannot crowd out the others

async function openPal(){
 closePal();
 pal=el(`<div class=palette><input placeholder="Search chats, files, commands..."><div class=res></div></div>`);
 document.body.appendChild(pal);
 const inp=pal.querySelector('input'),res=pal.querySelector('.res');
 let shown=[], expanded={};
 const draw=()=>{
  res.innerHTML='';
  const term=inp.value.trim().toLowerCase();
  shown=[];
  // grouped by kind and capped per kind: one flat list of 40 meant ten chat titles
  // could push every command and every file off the end
  PAL_SECTIONS.forEach(kind=>{
   const all=palItems.filter(x=>x.kind===kind);
   if(!all.length)return;
   const cap=expanded[kind]?all.length:PAL_CAP;
   res.appendChild(el(`<div class=palsec>${esc(kind)}<span>${all.length}</span></div>`));
   all.slice(0,cap).forEach(it=>{
    const i=shown.length;shown.push(it);
    const d=el(`<div class="it${i===palSel?' sel':''}"><span class=k></span><span class=t></span><span class=s></span></div>`);
    d.querySelector('.k').textContent=it.kind;
    d.querySelector('.t').innerHTML=palMark(it.label,term);
    d.querySelector('.s').textContent=it.sub||'';
    d.onclick=()=>{palRemember(term);closePal();it.go()};res.appendChild(d)});
   if(all.length>cap){
    const more=el(`<div class="it more">show all ${all.length} ${esc(kind)}</div>`);
    more.onclick=e=>{e.stopPropagation();expanded[kind]=true;draw()};
    res.appendChild(more)}});
  if(!shown.length&&!term){
   const hist=palHistory();
   if(hist.length){
    res.appendChild(el('<div class=palsec>recent searches</div>'));
    hist.forEach(h=>{const d=el('<div class="it"><span class=k>again</span><span class=t></span></div>');
     d.querySelector('.t').textContent=h;
     d.onclick=e=>{e.stopPropagation();inp.value=h;build(h)};res.appendChild(d)})}}
  palItems.shown=shown};
 // Each build fills its own list and shows it only if it is still the newest: an older
 // search that answered late used to push its rows into the newer one's list.
 let palGen=0,palT=null;
 const build=async term=>{
  const gen=++palGen,items=[];
  const publish=()=>{if(gen!==palGen)return false;palItems=items;expanded={};return true};
  CMDS.filter(c=>!term||c.c.includes(term)).forEach(c=>items.push(
   {kind:'cmd',label:c.c,sub:c.d,go:()=>runCmd(c.c,'')}));
  SESSIONS.filter(s=>!term||(s.title||'').toLowerCase().includes(term)).slice(0,40)
   .forEach(s=>items.push({kind:'chat',label:s.title||'(untitled)',sub:s.n+' msgs',
    go:()=>{showPane('log');openSession(s.id)}}));
  if(!publish())return;palSel=0;draw();          // what is known at once, shown at once
  if(term&&term.length>2){
   try{const hits=await (await fetch('/api/searchchats?q='+encodeURIComponent(term))).json();
    hits.slice(0,40).forEach(h=>items.push({kind:'in chat',label:h.snippet.trim().slice(0,70),
     sub:h.title,go:()=>{showPane('log');openSession(h.sid)}}))}catch(e){}
   try{const fd=await (await fetch('/api/files?limit=200')).json();
    (fd.items||[]).filter(f=>f.name.toLowerCase().includes(term)).slice(0,40)
     .forEach(f=>items.push({kind:'file',label:f.name,sub:f.area,
      // it used to switch to the Files pane and leave you to find it again
      go:()=>previewFile(f)}))}catch(e){}}
  if(gen!==palGen)return;palItems=items;draw()};
 // the full-text search waits for a pause in typing, not a server scan per keystroke
 inp.oninput=()=>{const v=inp.value.trim().toLowerCase();clearTimeout(palT);
  if(v.length<=2)build(v);else palT=setTimeout(()=>build(v),180)};
 inp.onkeydown=e=>{
  const rows=palItems.shown||[];
  if(e.key==='Escape')return closePal();
  if(e.key==='ArrowDown'){e.preventDefault();palSel=Math.min(palSel+1,rows.length-1);draw()}
  if(e.key==='ArrowUp'){e.preventDefault();palSel=Math.max(palSel-1,0);draw()}
  if(e.key==='Enter'){e.preventDefault();const it=rows[palSel];
   if(it){palRemember(inp.value.trim().toLowerCase());closePal();it.go()}}};
 await build('');inp.focus();
 pal.addEventListener('click',e=>e.stopPropagation());
 setTimeout(()=>document.addEventListener('click',closePal,{once:true}),0);
}



/* ---------------- checkpoints ---------------- */
async function showCheckpoints(rel,name){
 const d=await (await fetch('/api/checkpoints?rel='+encodeURIComponent(rel))).json();
 const cps=d.checkpoints||[];
 $('#modalhost').innerHTML=`<div class=modal><div class="sheet auto" style="max-width:520px">
  <header><b>Earlier versions — ${esc(name)}</b><button class=ghost style="margin-left:auto" id=cpx>close</button></header>
  <div class=body id=cpbody></div></div></div>`;
 $('#cpx').onclick=closeModal;
 $('#modalhost').querySelector('.modal').onclick=e=>{if(e.target.classList.contains('modal'))closeModal()};
 const b=$('#cpbody');
 if(!cps.length){b.innerHTML='<div class=note>No earlier versions saved yet — one is kept automatically each time this file is overwritten.</div>';return}
 cps.forEach(ts=>{const r=el('<div class=memrow></div>');
  const sp=document.createElement('span');sp.textContent=ts.replace('.bak','').replace(/^(\d{4})(\d\d)(\d\d)-(\d\d)(\d\d)(\d\d)/,'$1-$2-$3 $4:$5:$6');
  r.appendChild(sp);
  const rb=el('<button class=ghost>restore</button>');
  rb.onclick=async()=>{if(!confirm('Replace the current file with this version? (the current version is saved first, so this can be undone too)'))return;
   const res=await (await fetch('/api/checkpoints/restore',{method:'POST',headers:{'Content-Type':'application/json'},
     body:JSON.stringify({rel,name:ts})})).json();
   toast(res.message||(res.ok?'restored':'failed'));closeModal();renderFiles()};
  r.appendChild(rb);b.appendChild(r)})}

/* ---------------- health ---------------- */
async function showHealth(){
 const rows=await (await fetch('/api/health')).json();
 $('#modalhost').innerHTML=`<div class=modal><div class="sheet auto" style="max-width:620px">
  <header><b>Health check</b><button class=ghost style="margin-left:auto" id=hx>close</button></header>
  <div class=body id=hbody></div></div></div>`;
 $('#hx').onclick=closeModal;
 $('#modalhost').querySelector('.modal').onclick=e=>{if(e.target.classList.contains('modal'))closeModal()};
 const b=$('#hbody');
 rows.forEach(r=>{
  const mark=r.info?'·':(r.ok?'✓':'✗');
  const col=r.info?'var(--mut)':(r.ok?'var(--ok)':'var(--err)');
  const d=el(`<div class=memrow><b style="color:${col};min-width:16px">${mark}</b></div>`);
  const n=document.createElement('b');n.textContent=r.name;n.style.minWidth='150px';d.appendChild(n);
  const t=document.createElement('span');t.textContent=r.detail;d.appendChild(t);
  b.appendChild(d);
  if(!r.ok&&!r.info&&r.fix){const f=el('<div class=note style="margin:-4px 0 8px 26px"></div>');
   f.textContent=r.fix;b.appendChild(f)}})}

/* ---------------- appearance: theme, font size, sidebar width ---------------- */
// 'qq_' was the old prefix; read it once so existing preferences survive.
const PREF={get:(k,d)=>{try{return localStorage.getItem('orbit_'+k)
                            ??localStorage.getItem('qq_'+k)??d}catch(e){return d}},
            set:(k,v)=>{try{localStorage.setItem('orbit_'+k,v)}catch(e){}}};
function applyTheme(t){
 document.documentElement.dataset.theme=t==='system'?'':t;
 // Orbit for Mac paints its window (behind the page, and while it loads) the same way
 try{const W=window.orbitDesktop;if(W&&W.setTitleBarDark)W.setTitleBarDark(t==='dark'||(t!=='light'&&matchMedia('(prefers-color-scheme: dark)').matches))}catch(e){}
 // highlight.js ships one sheet per scheme, switched by media query: pin them for a chosen theme
 document.querySelectorAll('link[href*="highlight/styles"]').forEach(l=>{
  const dark=l.href.includes('github-dark');
  l.media=t==='system'?(dark?'(prefers-color-scheme: dark)':'(prefers-color-scheme: light)'):
   ((t==='dark')===dark?'all':'not all')});
 if(t==='light')document.documentElement.style.colorScheme='light';
 else if(t==='dark')document.documentElement.style.colorScheme='dark';
 else document.documentElement.style.colorScheme='';
 PREF.set('theme',t)}
function applyFont(px){
 // the one size everything else is derived from. It used to set the html font-size,
 // which nothing in the stylesheet followed, so the slider changed nothing at all
 document.documentElement.style.setProperty('--ui',px+'px');
 PREF.set('font',px)}
function applySidebar(w){document.documentElement.style.setProperty('--sidew',w+'px');
 const a=$('#side');
 if(a&&!matchMedia('(max-width:820px)').matches){a.style.width=w+'px';a.style.flexBasis=w+'px'}
 PREF.set('sidew',w)}
applyTheme(PREF.get('theme','system'));
applyFont(Number(PREF.get('font',15)));
applySidebar(Number(PREF.get('sidew',256)));

/* drag the sidebar edge */
(function(){
 const grip=el('<div style="position:absolute;top:0;right:-3px;width:6px;height:100%;cursor:col-resize;z-index:5"></div>');
 const a=$('#side'); if(!a)return; a.style.position='relative'; a.appendChild(grip);
 let start=0,w0=0,drag=false;
 grip.onmousedown=e=>{drag=true;start=e.clientX;w0=a.offsetWidth;document.body.style.userSelect='none'};
 addEventListener('mousemove',e=>{if(!drag)return;
  applySidebar(Math.max(190,Math.min(460,w0+(e.clientX-start))))});
 addEventListener('mouseup',()=>{if(drag){drag=false;document.body.style.userSelect=''}});
})();

/* ---------------- message timestamps ---------------- */
// ts: seconds since the epoch the message was written. Omitted for a message
// being written right now; null for one from before times were kept — those
// get no time at all rather than the moment the page happened to draw them.
function stamp(node,ts){
 if(ts===null)return;
 const d=ts?new Date(ts*1000):new Date();
 const t=document.createElement('span');t.className='ts';
 // always shown, not just on hover: when each step was written is part of reading it
 t.style.cssText='margin-left:auto;color:var(--dim);font-size:10.5px;opacity:.8';
 const hm=d.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'});
 t.textContent=d.toDateString()===new Date().toDateString()?hm
  :d.toLocaleDateString([], {month:'short',day:'numeric'})+', '+hm;
 t.title=d.toLocaleString();
 node.querySelector('.who').appendChild(t)}

/* ---------------- projects ---------------- */
let PROJECTS={}, projFilter=null;
const PCOLORS=['#6b5bd6','#2d7d4f','#a8721c','#c0392b','#2b7a9b','#8e44ad'];
async function loadProjects(){
 if(loadProjects._local)loadProjects._local=false;      // just reordered here: draw what we have
 else PROJECTS=await (await fetch('/api/projects')).json();
 const pc=$('#projct');if(pc)pc.textContent=Object.keys(PROJECTS).length||'';
 const wrap=$('#projwrap');wrap.innerHTML='';
 const counts={};SESSIONS.forEach(s=>{if(s.project)counts[s.project]=(counts[s.project]||0)+1});
 const all=el(`<div class="projrow${projFilter===null?' on':''}">
   <span class=sw style="background:var(--dim)"></span><span class=nm>All chats</span>
   <span class=ct>${SESSIONS.length}</span></div>`);
 all.onclick=()=>{projFilter=null;loadProjects();renderSessions()};
 wrap.appendChild(all);
 Object.entries(PROJECTS).sort((a,b)=>(a[1].order||0)-(b[1].order||0)).forEach(([pid,pr])=>{
  const r=el(`<div class="projrow${projFilter===pid?' on':''}">
    <span class=sw style="background:${pr.color||PCOLORS[0]}"></span>
    <span class=nm></span>${pr.source==='claude'?'<span class=pclaude title="a group from the Claude app\'s sidebar — its Claude Code chats are filed here by themselves">✻</span>':''}<span class=ct>${counts[pid]||0}</span>
    <span class=a title="project menu">⋮</span></div>`);
  r.querySelector('.nm').textContent=pr.name;
  r.onclick=e=>{if(e.target.classList.contains('a'))return;
   projFilter=projFilter===pid?null:pid;loadProjects();renderSessions()};
  r.querySelector('.a').onclick=e=>{e.stopPropagation();editProject(pid)};
  r.oncontextmenu=e=>{e.preventDefault();ctxMenu(e,[
   {icon:'＋',label:'New chat in this project',run:()=>{projFilter=pid;loadProjects();renderSessions();newChat()}},
   {icon:'\u270E',label:'Edit project',run:()=>editProject(pid)},
   {icon:'\u{1F50D}',label:'Show only this',run:()=>{projFilter=pid;loadProjects();renderSessions()}},
   '-',
   {icon:'\u{1F5D1}',label:'Delete project',danger:true,run:async()=>{
     if(!confirm('Delete project? Chats are kept.'))return;
     await fetch('/api/projects/delete',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({id:pid})});projFilter=null;loadSessions()}}])};
  // drag a project to put it where you want it; drag a chat onto it to move the chat
  r.draggable=true;
  r.ondragstart=e=>{e.dataTransfer.setData('pid',pid);e.dataTransfer.effectAllowed='move';
   r.classList.add('dragging')};
  r.ondragend=()=>{r.classList.remove('dragging');
   wrap.querySelectorAll('.projrow.over').forEach(x=>x.classList.remove('over'));dropLineOff()};
  // "over", not "drop": .drop is the full-screen file overlay, and a row wearing that
  // class became one -- a page-sized orange sheet that swallowed the drop it was
  // supposed to receive, so the project never moved.
  // A project being dragged is being reordered, so it gets the line; a chat being
  // dragged is going INTO this project, so the row is outlined. The dashed outline
  // used to mean both, which is why it read as neither.
  r.ondragover=e=>{e.preventDefault();e.dataTransfer.dropEffect='move';
   const kind=[...(e.dataTransfer.types||[])];
   if(kind.includes('pid')){r.classList.remove('over');dropLine(r,aboveHalf(r,e.clientY))}
   else{dropLineOff();r.classList.add('over')}};
  r.ondragleave=()=>{r.classList.remove('over')};
  r.ondrop=async e=>{e.preventDefault();e.stopPropagation();r.classList.remove('over');dropLineOff();
   const moved=e.dataTransfer.getData('pid');
   // where the line was drawn: the lower half of a row means after it (last place too)
   if(moved&&moved!==pid){await reorderProject(moved,pid,!aboveHalf(r,e.clientY));return}
   const sid=e.dataTransfer.getData('sid'); if(!sid)return;
   await fetch('/api/session/assign',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({id:sid,project:pid})});
   toast('moved to '+pr.name);loadSessions()};
  wrap.appendChild(r)})}
// Put a project where it was dropped, and keep every project's place by saving the new order.
async function reorderProject(moved,target,after){
 const ids=Object.entries(PROJECTS).sort((a,b)=>(a[1].order||0)-(b[1].order||0)).map(([id])=>id);
 const from=ids.indexOf(moved);if(from<0)return;
 ids.splice(from,1);
 const to=ids.indexOf(target);
 ids.splice(to<0?ids.length:to+(after?1:0),0,moved);
 ids.forEach((id,i)=>{if(PROJECTS[id])PROJECTS[id].order=i});
 loadProjects._local=true;await loadProjects();       // the new order shows at once
 // one call: saving each project in turn raced the Claude-group sync, which reads the
 // list and writes it back, and the order came out as it was before the drag
 const d=await apiPost('/api/projects/reorder',{ids},'saving the order');
 if(d&&d.projects)PROJECTS=d.projects;
 loadProjects._local=true;await loadProjects();
 if(GROUP_BY==='project')renderSessions(true)}
function editProject(pid){
 const pr=PROJECTS[pid]||{};
 $('#modalhost').innerHTML=`<div class=modal><div class="sheet auto" style="max-width:620px">
  <header><b>${pid?'Edit project':'New project'}</b>
   <button class=ghost style="margin-left:auto" id=px>close</button></header>
  <div class=body>
   <div class=grid>
    <label>Name</label><input type=text id=pr_name>
    <label>Colour</label><div id=pr_colors style="display:flex;gap:7px"></div>
    <label>Description</label><input type=text id=pr_desc placeholder="what this project is about">
    <label>Folder</label><input type=text id=pr_folder placeholder="/absolute/path (optional)" spellcheck=false>
    <div class=hint2>A rules file there (ORBIT.md or AGENTS.md) and a .orbit/tools folder apply to this project's chats.</div>
    <label>Trust tools</label><label style="display:flex;gap:8px;align-items:center;font-weight:normal"><input type=checkbox id=pr_trust>
     <span class=note>let this folder's .orbit/tools run without asking when they declare themselves safe</span></label>
   </div>
   <div class=sec>Project instructions <small>— added to every chat in this project</small></div>
   <textarea class=ta id=pr_ins style="min-height:150px" placeholder="e.g. This project is the kinase phylogenomics work. Always use gene IDs, cite DOIs, and prefer the knowledge base over the web."></textarea>
  </div>
  <footer><button class=primary id=pr_save>Save</button>
   ${pid?'<button class=ghost id=pr_del style="color:var(--err)">Delete project</button>':''}
   <span class=note>chats stay, they just lose the project</span></footer></div></div>`;
 $('#px').onclick=closeModal;
 $('#modalhost').querySelector('.modal').onclick=e=>{if(e.target.classList.contains('modal'))closeModal()};
 $('#pr_name').value=pr.name||'';$('#pr_desc').value=pr.description||'';
 $('#pr_ins').value=pr.instructions||'';$('#pr_folder').value=pr.folder||'';$('#pr_trust').checked=!!pr.trust_tools;
 let color=pr.color||PCOLORS[0];
 PCOLORS.forEach(c=>{const b=el(`<span style="width:22px;height:22px;border-radius:6px;background:${c};
   cursor:pointer;border:2px solid ${c===color?'var(--fg)':'transparent'}"></span>`);
  b.onclick=()=>{color=c;[...$('#pr_colors').children].forEach((x,i)=>
   x.style.borderColor=PCOLORS[i]===c?'var(--fg)':'transparent')};
  $('#pr_colors').appendChild(b)});
 $('#pr_save').onclick=async()=>{
  if(!$('#pr_name').value.trim())return toast('name required');
  const folder=$('#pr_folder').value.trim();
  if(folder&&!/^(\/|~\/)/.test(folder))return toast('the folder needs an absolute path, e.g. /Users/…/project');
  const saved=await apiPost('/api/projects/save',{id:pid||null,name:$('#pr_name').value.trim(),
    description:$('#pr_desc').value,instructions:$('#pr_ins').value,color,folder,
    trust_tools:$('#pr_trust').checked},'saving the project');
  if(!saved)return;
  if(saved.project&&saved.project.folder_missing)toast('saved — but that folder does not exist yet');
  closeModal();loadSessions()};
 if(pid&&$('#pr_del'))$('#pr_del').onclick=async()=>{
  if(!confirm('Delete this project? Chats are kept.'))return;
  await fetch('/api/projects/delete',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({id:pid})});closeModal();projFilter=null;loadSessions()};
}
$('#addproj').onclick=()=>editProject(null);

/* ---------------- about ---------------- */
async function showAbout(){
 const a=await (await fetch('/api/about')).json();
 const c=a.counts||{};
 $('#modalhost').innerHTML=`<div class=modal><div class=sheet style="max-width:760px">
  <header><img src="/icons/orbit-64.png?v=2" alt="" width=22 height=22
    style="border-radius:6px;margin-right:8px;vertical-align:-5px"><b>Orbit · v${a.version}${a.release?` · release ${esc(a.release)}`:''}</b>
   <button class=ghost style="margin-left:auto" id=ax>close</button></header>
  <div class=body>
   <p style="color:var(--mut);margin-top:0">A private research assistant that lives on this Mac.
    Your chats, notes, papers and files stay here. On the local model nothing leaves the machine
    except the web and database lookups you ask for; pick a hosted or CLI model and that turn's
    conversation goes to that provider instead — the picker always shows which one is answering.</p>
   <div class=aboutgrid>
    <div><b>${c.sessions||0}</b><small>chats</small></div>
    <div><b>${c.projects||0}</b><small>projects</small></div>
    <div><b>${(a.tools||[]).length}</b><small>tools</small></div>
    <div><b>${c.knowledge||0}</b><small>documents</small></div>
    <div><b>${c.memories||0}</b><small>memories</small></div>
    <div><b>${c.skills||0}</b><small>skills</small></div>
    <div><b>${c.agents||0}</b><small>agents</small></div>
    <div><b>${c.files||0}</b><small>files</small></div>
   </div>
   <div class=sec>How to use it</div>
   <div class=howto>
    <b>Just ask</b><span>It searches the web, reads your papers, runs Python, and queries NCBI/UniProt when it needs to — you don't have to name the tool.</span>
    <b>Models</b><span>The picker at the top of a chat chooses per conversation: the local
     MLX model, or Claude / Codex / OpenCode / Qwen through the CLIs you are already signed
     into (no API key), or a hosted API once you add a key in Settings → Models &amp; keys.
     A CLI model brings its own tools and does not use Orbit's.</span>
    <b>Projects</b><span>Group related chats. Project instructions are added to every chat inside it. Drag a chat onto a project to move it.</span>
    <b>Knowledge</b><span>Drop your papers in Settings → Knowledge. It searches them before the web and cites the file.</span>
    <b>Memory</b><span>Durable facts about you and your work, injected into every chat. <code>/remember</code> or the "save memories" button.</span>
    <b>Skills</b><span>Written procedures it loads on demand. Turn any good conversation into one with "save as skill".</span>
    <b>Agents</b><span>A preset instruction set plus a restricted tool list — fewer tools means fewer mistakes.</span>
    <b>Scheduled</b><span>Messages scheduled in any chat, and prompts that run on their own — all editable, with their models.</span>
    <b>Temp chat</b><span>The <code>temp</code> button starts a chat that is never written to disk. <code>burn</code> erases it instantly.</span>
   </div>
   <div class=sec>Safety</div>
   <p style="color:var(--mut);font-size:13.5px;margin:0">A short list of actions — wiping a disk, a fork
    bomb, a reverse shell, piping a download into a shell, killing every process, or anything aimed at a
    protected path like your home directory — is <b>blocked outright</b>, in every mode; nothing in
    Settings turns that off. Anything else destructive needs your approval in the chat, unless you have
    turned on <b>Auto-approve safe actions</b> or <b>Full computer access</b> in Settings → Tools →
    Autonomy — even then, a handful of machine-wide actions (sudo, shutting down, the keychain,
    publishing a package, rewriting git history) still always ask. Everything the model reads from the
    web or a file is fenced as untrusted data and scanned for prompt-injection attempts — matches raise a
    banner and are logged to <code>logs/safety.log</code>, along with every approval, denial and
    auto-approval.</p>
   <div class=sec>Slash commands</div>
   <div class=howto>${CMDS.map(c=>`<b><code>${c.c}</code></b><span>${esc(c.d)}</span>`).join('')}
    <b><code>/&lt;prompt&gt;</code></b><span>any saved prompt becomes its own command (Library → Prompts)</span></div>
   <div class=sec>Tools</div>
   <div>${(a.tools||[]).map(t=>`<span class=pill>${t}</span>`).join('')}</div>
   <div class=sec>Where things live</div>
   <pre style="background:var(--panel);padding:11px;border-radius:9px;font-size:12px;overflow-x:auto">${a.root}/
  config/     settings, agents, projects, schedule, secrets, MCP
  memory/     durable facts        skills/     procedures
  knowledge/  your documents       sessions/   chats
  workspace/  files it creates     trash/      recycle bin
  logs/       server, safety, ledger</pre>
   <div class=sec>Made by</div>
   <div class=credit>
    <img src="/icons/orbit-128.png?v=2" alt="" width=44 height=44>
    <div><b>Runtian Wu</b>
     <span>Built on MTPLX and Apple&nbsp;Silicon MLX, with optional hosted and CLI models. Runs on your own machine.</span>
     <span class=links><a href="https://runtianwu.com" target=_blank rel=noopener>runtianwu.com</a>
      <a href="https://github.com/Micropeptide" target=_blank rel=noopener>github.com/Micropeptide</a>
      <a href="${a.github}" target=_blank rel=noopener>Orbit's source</a></span></div></div>
   <p class=note style="margin:10px 0 0">Model now: <code>${esc(a.model)}</code> · press <span class=kbd>?</span> for shortcuts</p>
  </div></div></div>`;
 $('#ax').onclick=closeModal;
 $('#modalhost').querySelector('.modal').onclick=e=>{if(e.target.classList.contains('modal'))closeModal()};
}

/* ---------------- notifications ---------------- */
let AC=null;
function beep(){try{AC=AC||new (window.AudioContext||window.webkitAudioContext)();
 const o=AC.createOscillator(),g=AC.createGain(),t=AC.currentTime;
 o.frequency.value=880;g.gain.setValueAtTime(.06,t);g.gain.exponentialRampToValueAtTime(.0001,t+.22);
 o.connect(g);g.connect(AC.destination);o.start(t);o.stop(t+.24)}catch(e){}}
// called from go(): the permission prompt and audio both need a user gesture
function primeAlerts(){
 try{if(window.Notification&&Notification.permission==='default'&&!PREF.get('notifasked')){
  PREF.set('notifasked','1');const p=Notification.requestPermission();if(p&&p.catch)p.catch(()=>{})}}catch(e){}
 if(PREF.get('beep','0')==='1')try{AC=AC||new (window.AudioContext||window.webkitAudioContext)();
  if(AC.state==='suspended')AC.resume()}catch(e){}}
function syncUnseen(){const n=Object.values(UNSEEN).reduce((a,b)=>a+b,0);
 document.title=(n?`(${n}) `:'')+'Orbit'}
function seen(){if(sid&&!document.hidden&&document.hasFocus()){
 const row=SESSIONS.find(v=>v.id===sid);if(row&&row.unread)markSeenOnMac(sid);
 if(UNSEEN[sid]){delete UNSEEN[sid];syncUnseen();renderSessions()}}}
// looked at here: the phone and other windows stop showing it as new too
function markSeenOnMac(s){
 if(!s||tempMode)return;
 const row=SESSIONS.find(v=>v.id===s);if(row&&row.unread){row.unread=false;renderSessions()}
 fetch('/api/session/seen',{method:'POST',headers:{'Content-Type':'application/json'},
  body:JSON.stringify({id:s})}).catch(()=>{})}
addEventListener('focus',seen);document.addEventListener('visibilitychange',seen);
function notify(s,kind,body){
 if(!s||(!document.hidden&&document.hasFocus()&&sid===s))return;   // you are looking at it
 UNSEEN[s]=(UNSEEN[s]||0)+1;syncUnseen();renderSessions();
 if(PREF.get('beep','0')==='1')beep();
 try{if(!window.Notification||Notification.permission!=='granted')return;
  const x=SESSIONS.find(v=>v.id===s);
  const n=new Notification(kind+(x&&x.title?' — '+x.title:''),
   {body:String(body||'').slice(0,160),tag:'orbit-'+s,icon:'/icons/orbit-192.png?v=2'});
  n.onclick=()=>{try{window.focus()}catch(e){}n.close();showPane('log');
   if(sid!==s)openSession(s);else seen()}}catch(e){}}

/* ---------------- hook notices ----------------
   "hook PreToolUse:Bash ran" arrives for every hook on every step. One folded line per
   answer says how many ran ("Ran 12 hooks · 1 failed") and opens to the list. */
let HOOKBOX=null;
function hookNote(forSid,msg){
 if(!HOOKBOX||!HOOKBOX.isConnected||HOOKBOX._sid!==forSid||HOOKBOX._turn!==statusT0){
  HOOKBOX=el('<details class=hookbox><summary><span class=tarr>⎿</span> <span class=hn></span></summary><div class=hl></div></details>');
  HOOKBOX._sid=forSid;HOOKBOX._turn=statusT0;HOOKBOX._n=0;HOOKBOX._bad=0;HOOKBOX._kinds={};
  wrap.appendChild(HOOKBOX)}
 const b=HOOKBOX;b._n++;
 if(/exit [1-9]|fail|error|block/i.test(msg))b._bad++;
 const kind=(String(msg).match(/^hook\s+([A-Za-z]+)/)||[])[1]||'hook';
 b._kinds[kind]=(b._kinds[kind]||0)+1;
 const line=el('<div></div>');line.textContent=msg;b.querySelector('.hl').appendChild(line);
 b.querySelector('.hn').textContent='Ran '+plural(b._n,'hook','hooks')+
  (b._bad?' · '+b._bad+' reported a problem':'')+' — '+
  Object.entries(b._kinds).map(([k,n])=>k+(n>1?' ×'+n:'')).join(', ')}

/* ---------------- the status line ----------------
   While an answer runs, one line says what is happening: a spinner, a word for the
   work, how long it has taken, roughly how much has come back, and how to stop it --
   the shape Claude Code uses. */
const SPIN=['·','✢','✳','✶','✻','✽'];
const SPINSEQ=SPIN.concat(SPIN.slice(1,-1).reverse());
const VERBS=['Working','Pondering','Brewing','Churning','Cooking','Crunching','Percolating',
 'Puzzling','Simmering','Spelunking','Synthesising','Tinkering','Wrangling','Orbiting',
 'Noodling','Whirring','Mulling','Sifting','Assembling','Unravelling','Untangling','Composing'];
// how thinking is described as it goes on, the way Claude Code escalates it
const THINK_LADDER=[[45,'deep in thought'],[30,'thinking some more'],[20,'thinking more'],
 [10,'still thinking'],[0,'thinking']];
let STATUS_SID=null,statusTimer=null,statusT0=0,statusVerb='',statusFrame=0,statusNote='',statusChars=0,statusThinkT0=0;
function startStatus(){
 document.body.classList.add('statuson');
 STATUS_SID=sid;statusT0=Date.now();statusVerb=VERBS[Math.floor(Math.random()*VERBS.length)];
 statusNote='';statusChars=0;statusThinkT0=0;statusFrame=0;
 const n=$('#statusline');if(!n)return;
 n.style.display='';drawStatus();
 if(!statusTimer)statusTimer=setInterval(drawStatus,140)}
function stopStatus(forSid){
 if(forSid&&STATUS_SID&&forSid!==STATUS_SID)return;     // another chat's answer owns the line now
 STATUS_SID=null;
 document.body.classList.remove('statuson');
 if(statusTimer){clearInterval(statusTimer);statusTimer=null}
 const n=$('#statusline');if(n){n.style.display='none';n.innerHTML=''}}
function statusSay(note){statusNote=String(note||'')}
function statusGrew(text,thinking){
 statusChars+=String(text||'').length;
 if(thinking){if(!statusThinkT0)statusThinkT0=Date.now()}else statusThinkT0=0}
function fmtTok(n){return n>=1000?(n/1000).toFixed(1).replace(/\.0$/,'')+'k':String(n)}
function drawStatus(){
 const n=$('#statusline');if(!n)return;
 if(STATUS_SID&&sid!==STATUS_SID){n.style.visibility='hidden';return}
 n.style.visibility='';
 if(n.style.display==='none')return;
 const secs=(Date.now()-statusT0)/1000;
 let verb=statusVerb;
 if(statusThinkT0){const t=(Date.now()-statusThinkT0)/1000;
  verb=(THINK_LADDER.find(([s])=>t>=s)||[0,'thinking'])[1];
  verb=verb.charAt(0).toUpperCase()+verb.slice(1)}
 const tok=Math.round(statusChars/4);
 const meta=[fmtSecs(secs)];
 if(tok>=30)meta.push('↓ ~'+fmtTok(tok)+' tokens');
 if(statusNote)meta.push(statusNote);
 if(!n.firstChild)n.innerHTML='<span class=sspin></span><span class=sverb></span>'+
  '<span class=smeta></span><span class=sint>esc to interrupt</span>';
 n.querySelector('.sspin').textContent=SPINSEQ[(statusFrame++)%SPINSEQ.length];
 n.querySelector('.sverb').textContent=verb+'…';
 n.querySelector('.smeta').textContent='('+meta.join(' · ')+')';
 const x=n.querySelector('.sint');if(!x._wired){x._wired=true;x.onclick=()=>stopRun()}}
// one place that stops the running answer, for the Stop button, Esc and the status line
function stopRun(){const b=$('#stopgen');if(b&&b.style.display!=='none')b.click()}

/* ---------------- tool rows, answer stats ---------------- */
let toolTick=null;
let VERBOSE=false;            // ctrl+o: every tool row opened, arguments and output in full
function fmtSecs(s){s=+s||0;
 if(s<9.95)return s.toFixed(1)+'s';
 const r=Math.round(s);if(r<60)return r+'s';
 if(r<3600)return Math.floor(r/60)+'m '+String(r%60).padStart(2,'0')+'s';
 const m=Math.round(r/60);return Math.floor(m/60)+'h '+String(m%60).padStart(2,'0')+'m'}
function toolLabel(args){args=args||{};
 const k=['description','query','url','path','pattern','name','command'].find(k=>args[k]!=null&&String(args[k]).trim());
 return k?String(args[k]).replace(/\s+/g,' ').trim().slice(0,90):''}
/* Every tool a model can call -- Orbit's own, Claude Code's, Codex's -- said the
   same way: what it is doing (Read, Update, Bash…), to what, and what came back.
   Names follow Claude Code so the two read alike. */
const TOOLNAME={read_file:'Read',Read:'Read',NotebookRead:'Read',read_chat:'Read chat',
 chat_create:'New chat',chat_send:'Message chat',chat_wait:'Wait for chat',chat_list:'List chats',
 write_file:'Write',Write:'Write',edit_file:'Update',Edit:'Update',MultiEdit:'Update',
 multi_edit:'Update',NotebookEdit:'Edit notebook',apply_patch:'Update',
 run_shell:'Bash',Bash:'Bash',shell:'Bash',BashOutput:'Bash output',KillShell:'Kill shell',
 run_shell_background:'Bash (background)',check_background:'Background',list_background:'Background',
 python:'Python',glob:'Search',Glob:'Search',grep_files:'Search',Grep:'Search',
 search_knowledge:'Search',search_chats:'Search chats',search_agent_memory:'Search memory',
 list_dir:'List',LS:'List',web_search:'Web Search',WebSearch:'Web Search',
 fetch_url:'Fetch',WebFetch:'Fetch',fetch_paper_pdf:'Fetch paper',http_json:'Fetch',
 task:'Agent',Task:'Agent',Agent:'Agent',TodoWrite:'Todos',plan:'Plan',
 TaskCreate:'Todos',TaskUpdate:'Todos',remember:'Remember',use_skill:'Skill',
 cluster_run:'Cluster',cluster_submit:'Cluster',cluster_status:'Cluster',cluster_ls:'Cluster',
 cluster_read:'Cluster',cluster_qdel:'Cluster',ask_user:'Ask',
 // the tools Claude Code has added since: named as the CLI names them
 TaskList:'Todos',TaskGet:'Todos',TaskStop:'Stop task',TaskOutput:'Task output',SendMessage:'Message agent',
 ScheduleWakeup:'Schedule',ToolSearch:'Find tools',Monitor:'Monitor',AskUserQuestion:'Ask',
 ExitPlanMode:'Plan',EnterPlanMode:'Plan',Skill:'Skill',SendUserFile:'Send file',Artifact:'Artifact',
 ListAgents:'List agents',CronCreate:'Schedule',CronDelete:'Schedule',CronList:'Schedule',
 EnterWorktree:'Worktree',ExitWorktree:'Worktree',PushNotification:'Notify'};
// what it says while the call is still running
const TOOLVERB={Read:'Reading',Write:'Writing',Update:'Editing','Edit notebook':'Editing',
 Bash:'Running',Python:'Running',Search:'Searching','Search chats':'Searching',
 'Search memory':'Searching','Web Search':'Searching',List:'Listing',Fetch:'Fetching',
 'Fetch paper':'Fetching',Agent:'Running task',Cluster:'Running',Plan:'Planning',Todos:'Updating todos'};
// calls that only look things up: several in a row collapse into one line
const TOOLFAM={Read:'read',Search:'search','Search chats':'search','Search memory':'search',
 'Web Search':'search',List:'list',Fetch:'fetch','Fetch paper':'fetch'};
const FAMWORD={read:['Read','file','files'],search:['Searched for','pattern','patterns'],
 list:['Listed','directory','directories'],fetch:['Fetched','page','pages']};
function toolName(n){n=String(n||'tool');
 if(TOOLNAME[n])return TOOLNAME[n];
 if(n.startsWith('mcp__')){const p=n.split('__'),last=p[p.length-1];
  return TOOLNAME[last]||last.replace(/_/g,' ')}
 if(n.includes('.'))return n.split('.').pop().replace(/_/g,' ');
 return n.replace(/_/g,' ')}
function shortPath(s){s=String(s||'');const p=s.split('/').filter(Boolean);
 return p.length>2?p.slice(-2).join('/'):s.replace(/^~\//,'')}
// the target, the way Claude Code writes it: a path for file tools, the command for a
// shell call, the pattern for a search
function toolTarget(name,args){args=args||{};
 const disp=toolName(name);
 const fp=args.file_path||args.notebook_path||args.path||args.file;
 if(fp&&['Read','Write','Update','Edit notebook','List'].includes(disp))return shortPath(fp);
 if(disp==='Bash'||disp==='Python'){
  let c=args.command||args.code||args.script||'';
  if(Array.isArray(c))c=(c.length===3&&/^-l?c$/.test(c[1])&&/sh$/.test(c[0]))?c[2]:c.join(' ');
  c=String(c).replace(/\s+/g,' ').trim();
  // Codex wraps every command in a login shell: show the command itself
  const w=c.match(/^(?:\/(?:usr\/)?bin\/)?(?:ba|z)?sh -l?c (['"])([\s\S]*)\1$/);
  if(w)c=w[2];
  return c.slice(0,120)}
 if(disp==='Search')return String(args.pattern||args.query||args.glob||'').slice(0,90)+
   (args.path?' in '+shortPath(args.path):'');
 if(disp==='Fetch'||disp==='Web Search')return String(args.url||args.query||'').slice(0,90);
 if(disp==='Agent')return String(args.description||args.prompt||'').replace(/\s+/g,' ').slice(0,90);
 if(disp==='New chat')return String(args.title||'')+(args.model?' · '+args.model:'');
 if(disp==='Message chat')return chatLabel(args.chat)+': '+String(args.message||'').replace(/\s+/g,' ').slice(0,80);
 if(disp==='Wait for chat')return chatLabel(args.chat);
 return toolLabel(args)}
// p: a live 'tool' event {id,name,args}, or a saved run {id,name,label,secs,ok} with done=true
// Chats talking to chats: another chat named by id or title, as the sidebar knows it
function chatLabel(c){c=String(c||'');const r=SESSIONS.find(x=>x.id===c);return r?'“'+(r.title||c)+'”':'“'+c+'”'}
function chatRef(c){c=String(c||'');
 const r=SESSIONS.find(x=>x.id===c)||SESSIONS.find(x=>(x.title||'').toLowerCase()===c.toLowerCase());return r?r.id:null}
document.addEventListener('click',e=>{const a=e.target.closest&&e.target.closest('.chatlink');if(!a)return;
 e.preventDefault();e.stopPropagation();const id=a.dataset.chat;
 if(id){showPane('log');openSession(id)}else toast('that chat is not in the list yet')});
function toolRow(p,done){
 const d=el('<details class=tool><summary><div class=thead>'+
  '<span class=ttrigger><span class=tdot>⏺</span><span class=tn></span></span>'+
  '<span class=tl></span><span class=tt></span></div></summary></details>');
 // The summary carries the whole shell command and the path, and a click anywhere in a
 // <summary> toggles it — so none of that could be selected or copied. A drag selects
 // (it fires no click), a double click selects the word, and everything else still opens
 // the row, so it does not feel dead.
 d.querySelector('summary').addEventListener('click',e=>{
  if(e.target.closest('.toolopen'))return;          // the "open" link is its own thing
  e.preventDefault();
  const inText=e.target.closest('.tl');
  if(inText&&(e.detail>1||!window.getSelection().isCollapsed))return;
  d.open=!d.open});
 d.dataset.id=p.id||'';
 const disp=toolName(p.name);
 d.dataset.fam=TOOLFAM[disp]||'';
 d.dataset.disp=disp;
 d.querySelector('.tn').textContent=done?disp:(TOOLVERB[disp]||disp);
 d.querySelector('.tl').textContent=p.label!=null?p.label:toolTarget(p.name,p.args);
 if(p.args){d.querySelector('summary').title=Object.entries(p.args)
   .map(([k,v])=>k+': '+String(typeof v==='object'?JSON.stringify(v):v).slice(0,200)).join('\n');
  d._args=p.args}
 const fp=p.args&&(p.args.file_path||p.args.notebook_path||p.args.path);
 if(fp&&typeof fp==='string'&&/^(~|\/)/.test(fp)){
  const o=el('<span class="pathlink toolopen">open</span>');o.dataset.path=fp;o.title='open '+fp;
  d.querySelector('.thead').appendChild(o)}
 if((disp==='Message chat'||disp==='Wait for chat')&&p.args&&p.args.chat){
  const o=el('<span class="chatlink toolopen">open chat</span>');o.dataset.chat=chatRef(p.args.chat)||'';
  d.querySelector('.thead').appendChild(o)}
 if(done)finishTool(d,p);
 else{d.classList.add('live');d._t0=Date.now();
  // a spinner per row means one animated element and one DOM write a second for every
  // call in a parallel fan-out, on top of streaming markdown. The glyph stays where it
  // is and the name sweeps instead: same "it is working", no per-row animation budget.
  d.querySelector('.tt').textContent='0.0s';
  if(!toolTick)toolTick=setInterval(tickTools,1000);
  // a command still running in the foreground can go to the background and the answer carries
  // on (Ctrl+B in the CLI): offered once it has run a few seconds, in Claude Code mode
  if(p.id&&disp==='Bash'&&MODELS.harness_mode){
   const b=el('<span class="toolopen bgbtn" title="Run this in the background and carry on — Ctrl+B in the Claude Code CLI" style="display:none">to background</span>');
   b.onclick=async e=>{e.preventDefault();e.stopPropagation();b.textContent='moving…';
    const ok=await apiPost('/api/tasks/background',{sid,tool_id:p.id},'background');
    if(ok)setTimeout(pollBg,1200);else b.textContent='to background'};
   d.querySelector('.thead').insertBefore(b,d.querySelector('.tt'));
   setTimeout(()=>{if(b.isConnected&&d.classList.contains('live'))b.style.display=''},8000)}}
 return d}
function tickTools(){                       // one timer for every running row on screen
 const live=document.querySelectorAll('details.tool.live');
 if(!live.length){clearInterval(toolTick);toolTick=null;return}
 if(document.hidden)return;                 // nobody is reading it
 const now=Date.now();
 live.forEach(d=>{
  const t=d.querySelector('.tt'), v=fmtSecs((now-d._t0)/1000);
  if(t.textContent!==v)t.textContent=v})}   // only write what actually changed
// p.stopped = it never reported back (the answer ended or was stopped);
// ok==null on a saved run just means an older chat that didn't record it
// What came back, in one phrase -- "Wrote 32 lines to notes.md", "Added 4 lines, removed 1",
// "Found 12 matches". The same shapes Claude Code uses, so a call reads at a glance.
function nLines(s){s=String(s||'');if(!s.trim())return 0;
 return s.replace(/\n+$/,'').split('\n').length}
function plural(n,one,many){return n+' '+(n===1?one:many)}
function resultSummary(disp,p){
 let out=p.output==null?'':String(p.output);
 const args=p.args||{};
 if(p.stopped)return 'stopped before it came back';
 // Orbit's shell tools answer "exit=N\nstdout:\n…\nstderr:\n…": lead with what it printed
 const sh=out.match(/^exit=(-?\d+)\nstdout:\n([\s\S]*?)(?:\nstderr:\n([\s\S]*))?$/);
 if(sh){const printed=(sh[2]||'').trim()?sh[2]:(sh[3]||'');
  const first=printed.split('\n').find(l=>l.trim())||'(No output)';
  const rest=Math.max(0,nLines(printed)-1);
  return (sh[1]!=='0'?'exit '+sh[1]+' \u00b7 ':'')+first.replace(/\s+/g,' ').slice(0,150)+
   (rest?'  +'+plural(rest,'line','lines'):'')}
 if(p.ok===false){const first=out.split('\n').find(l=>l.trim())||'failed';
  return first.replace(/\s+/g,' ').slice(0,160)}
 if(p.diff&&(p.diff.added!=null||p.diff.removed!=null))
  return 'Added '+plural(+p.diff.added||0,'line','lines')+', removed '+plural(+p.diff.removed||0,'line','lines');
 if(p.background||(disp==='Bash'&&args.run_in_background))return 'Running in the background';
 if(!out.trim())return disp==='Bash'||disp==='Python'?'(No output)':'(No content)';
 switch(disp){
  case 'Read':return 'Read '+plural(nLines(out),'line','lines');
  case 'Write':{const m=out.match(/(\d+)\s+lines?/);
   const n=m?+m[1]:nLines(args.content||args.text||'');
   const to=args.file_path||args.path;
   return 'Wrote '+plural(n||nLines(out),'line','lines')+(to?' to '+shortPath(to):'')}
  case 'Update':case 'Edit notebook':{const m=out.match(/(\d+)\s+(?:insertions?|additions?)[^\d]+(\d+)/);
   if(m)return 'Added '+plural(+m[1],'line','lines')+', removed '+plural(+m[2],'line','lines');
   return out.split('\n').find(l=>l.trim()).replace(/\s+/g,' ').slice(0,160)}
  case 'Search':case 'Search chats':case 'Search memory':{
   if(/^\s*(no matches|nothing found|\[\]|none)/i.test(out))return 'No matches found';
   const m=out.match(/(\d+)\s+(?:match|hit|result)/i);
   return m?'Found '+plural(+m[1],'match','matches'):'Found '+plural(nLines(out),'result','results')}
  case 'List':return plural(nLines(out),'entry','entries');
  case 'Web Search':case 'Fetch':case 'Fetch paper':
   return plural(nLines(out)>1?nLines(out):Math.max(1,Math.round(out.length/1000)),'line','lines')+' back';
  case 'Todos':case 'Plan':return 'Todos updated';
  case 'Agent':if(p.subagent){const a=p.subagent;
   if(a.background)return 'Running in the background';
   return (a.status&&!/^(completed|done)$/.test(a.status)?a.status.charAt(0).toUpperCase()+a.status.slice(1):'Done')+' ('+plural(+a.tools||0,'tool use','tool uses')+
    (a.tokens?' \u00b7 '+fmtTok(+a.tokens)+' tokens':'')+(a.secs!=null&&!a.background?' \u00b7 '+fmtSecs(+a.secs):'')+')'}
   break;
 }
 // JSON back: say what is in it on one line rather than "{ +40 lines"
 const tr=out.trim();
 if(/^[\[{]/.test(tr)){try{const j=JSON.parse(tr);return jsonSummary(j)}catch(e){
   const pairs=[...tr.slice(0,800).matchAll(/"([\w .-]{1,30})"\s*:\s*("(?:[^"\\]|\\.){0,40}"|-?[\d.]+|true|false|null|\[|\{)/g)]
    .slice(0,6).map(m=>m[1]+': '+(m[2]==='['?'[…]':m[2]==='{'?'{…}':m[2].replace(/^"|"$/g,'')));
   if(pairs.length)return pairs.join(' \u00b7 ')}}
 const first=out.split('\n').find(l=>l.trim())||'';
 const rest=nLines(out)-1;
 return first.replace(/\s+/g,' ').slice(0,160)+(rest>0?'  +'+plural(rest,'line','lines'):'')}
function jsonSummary(j){
 if(Array.isArray(j))return j.length?plural(j.length,'item','items'):'(empty list)';
 if(j&&typeof j==='object'){
  if(j.error)return String(j.error).slice(0,160);
  const parts=[];
  for(const [k,v] of Object.entries(j)){
   let val;
   if(Array.isArray(v))val=v.length+(v.length===1?' item':' items');
   else if(v&&typeof v==='object')val='{…}';
   else val=String(v).replace(/\s+/g,' ').slice(0,40);
   parts.push(k+': '+val);
   if(parts.join(' · ').length>150)break}
  return parts.join(' \u00b7 ')||'(empty)'}
 return String(j).slice(0,160)}
// p.stopped = it never reported back (the answer ended or was stopped);
// ok==null on a saved run just means an older chat that didn't record it
function finishTool(d,p){
 d.classList.remove('live');d.classList.add('done');
 d.querySelectorAll('.bgbtn').forEach(x=>x.remove());
 // a chat it started: a link to it, once the id is known
 const made=String(p.output||'').match(/^Started the chat .*?\(id ([\w-]+)\)/);
 if(made&&!d.querySelector('.chatlink')){const o=el('<span class="chatlink toolopen">open chat</span>');
  o.dataset.chat=made[1];d.querySelector('.thead').appendChild(o)}
 const ok=p.ok!==false&&!p.stopped;
 if(!ok)d.classList.add('bad');
 const sp=d.querySelector('.spin');
 if(sp)sp.replaceWith(el('<span class=tdot>⏺</span>'));
 const disp=d.dataset.disp||toolName(p.name);
 const tn=d.querySelector('.tn');if(tn)tn.textContent=disp;
 const tt=d.querySelector('.tt');
 const secs=typeof p.secs==='number'?p.secs:(d._t0?(Date.now()-d._t0)/1000:null);
 tt.className='tt';tt.textContent=secs!=null&&secs>=0.5?fmtSecs(secs):'';
 if(secs!=null)d.dataset.secs=secs;
 if(p.args&&!d._args)d._args=p.args;
 d.querySelectorAll('.tsubs,.tsubmeta').forEach(x=>x.remove());     // the live view gives way to "Done (…)"
 const res=el('<div class=tres><span class=tarr>⎿</span><span class=tsum></span></div>');
 if(!ok)res.classList.add('bad');
 res.querySelector('.tsum').textContent=resultSummary(disp,{...p,args:p.args||d._args});
 d.querySelector('summary').appendChild(res);
 const out=p.output==null?'':String(p.output);
 // the arguments in full, then everything that came back -- open the row to read them
 if(d._args&&Object.keys(d._args).length){
  const a=document.createElement('div');a.className='targs';
  a.textContent=Object.entries(d._args)
   .map(([k,v])=>k+': '+String(typeof v==='object'?JSON.stringify(v):v).slice(0,600)).join('\n');
  d.appendChild(a)}
 // what a subagent did, step by step (Claude Code's ctrl+o view of it)
 const sub=p.subagent||(d._steps&&d._steps.length?{steps:d._steps,tools:d._steps.length}:null);
 if(sub&&(sub.steps||[]).length)d.appendChild(subStepsBox(sub));
 if(sub&&sub.background)d.classList.add('bgrun');
 if((sub&&sub.background)||p.background||(d._args&&d._args.run_in_background)){
  // started in the background: its output is a click away, as in Claude's task list
  const o=el('<span class="pathlink toolopen">output</span>');o.title='what it has written so far';
  o.onclick=e=>{e.preventDefault();e.stopPropagation();
   showTaskOutput({sid:d.closest('.msg')&&d.closest('.msg').dataset.sid||sid,id:d.dataset.id,
    title:toolTarget(p.name,d._args||{})||'Background task'})};
  d.querySelector('.thead').insertBefore(o,d.querySelector('.tt'))}
 if(!out)return;
 const pre=document.createElement('pre');pre.textContent=out;d.appendChild(pre);
 const cp=el('<span class=more>copy output</span>');cp.onclick=e=>{e.stopPropagation();copy(out)};
 d.appendChild(cp);
 if(VERBOSE)d.open=true}
/* ---------------- subagents and background tasks ----------------
   As Claude Code shows them. An Agent row lists what its subagent is doing under it
   ("⎿ Read src/app.py", "+5 more tool uses") and ends "Done (12 tool uses · 34k tokens ·
   1m 5s)"; open the row for every step. Shells and agents sent to the background are
   counted under the box ("2 background tasks") and listed in /tasks. */
function subStepsBox(sub){
 const box=el('<div class=tsubsteps><div class=tsubhd></div></div>');
 const steps=(sub.steps||[]).filter(x=>x.name!=='tool'||x.args);
 box.firstChild.textContent=(sub.type||'subagent')+' \u00b7 '+plural(+sub.tools||steps.length,'tool use','tool uses')+
  (steps.length&&(+sub.tools||0)>steps.length?' (last '+steps.length+' shown)':'');
 steps.forEach(st=>{const l=el('<div class=tsubl><span class=tarr>⏺</span><span></span></div>');
  l.lastChild.textContent=subStepLine(st);l.lastChild.title=subStepLine(st);box.appendChild(l)});
 if(sub.summary){const pr=document.createElement('pre');pr.className='tsubsum';pr.textContent=sub.summary;box.appendChild(pr)}
 return box}
// a subagent that ran in the background has finished: its row now reads "Done (…)"
function subagentDone(row,sub){
 if(!row||!sub)return;
 row.classList.remove('bgrun');
 row.querySelectorAll('.tsubs,.tsubmeta,.tsubsteps').forEach(x=>x.remove());
 const t=row.querySelector('.tsum');if(t)t.textContent=resultSummary('Agent',{subagent:sub,output:'.'});
 const tt=row.querySelector('.tt');if(tt&&sub.secs)tt.textContent=fmtSecs(+sub.secs);
 row.appendChild(subStepsBox(sub))}
function subStepLine(s){const t=toolTarget(s.name,s.args||{});return toolName(s.name)+(t?' '+t:'')}
function subagentLive(row,p){
 if(!row)return;
 row._steps=row._steps||[];row._steps.push({name:p.name,args:p.args});drawSub(row,p)}
function drawSub(row,p){
 let box=row.querySelector('.tsubs');
 if(!box){box=el('<div class=tsubs></div>');row.querySelector('summary').appendChild(box)}
 box.innerHTML='';
 const last=row._steps.slice(-3);
 last.forEach((st,i)=>{const l=el('<div class=tsubl><span class=tarr></span><span></span></div>');
  l.firstChild.textContent=i===0?'\u23bf':'';l.lastChild.textContent=subStepLine(st);box.appendChild(l)});
 const more=row._steps.length-last.length;
 if(more>0){const l=el('<div class="tsubl dim"><span class=tarr></span><span></span></div>');
  l.lastChild.textContent='+'+plural(more,'more tool use','more tool uses');box.appendChild(l)}
 let meta=row.querySelector('.tsubmeta');
 if(!meta){meta=el('<span class=tsubmeta></span>');row.querySelector('.thead').insertBefore(meta,row.querySelector('.tt'))}
 meta.textContent=plural(+p.tools||row._steps.length,'tool use','tool uses')+(p.tokens?' \u00b7 '+fmtTok(+p.tokens)+' tokens':'')}
// background tasks by chat, from the stream and from /api/tasks
let BGT={};
function bgNote(forSid,p){if(!forSid||!p||!p.id)return;
 BGT[forSid]=BGT[forSid]||{};BGT[forSid][p.id]={...(BGT[forSid][p.id]||{}),...p};drawBgChip()}
function drawBgChip(){
 let c=$('#bgchip');
 if(!c){const h=$('#modehint');if(!h)return;c=el('<span id=bgchip title="Claude Code\'s background tasks — /tasks"></span>');
  h.after(c);c.onclick=()=>showTasks()}
 const n=Object.values(BGT[sid]||{}).filter(x=>/^(running|pending)/.test(x.status||'')).length;
 c.textContent=n?'\u29d7 '+plural(n,'background task','background tasks'):'';c.style.display=n?'inline':'none';
 drawPlanDock()}          // the dock lists the same work, and only learned of it on a redraw
async function pollBg(){
 if(document.hidden)return;
 try{const d=await (await fetch('/api/tasks')).json();
  const next={};
  (d.items||[]).filter(x=>x.kind==='background'&&x.sid).forEach(x=>{
   (next[x.sid]=next[x.sid]||{})[x.id]={id:x.id,title:x.title,description:x.title,
     secs:x.secs,status:x.running?'running':(x.status||'ended'),item:x}});
  BGT=next;drawBgChip();
  // a background subagent that finished after its answer: its row on screen says so now
  (d.items||[]).filter(x=>x.kind==='background'&&x.subkind==='agent'&&!x.running&&x.tool_id).forEach(x=>{
   const row=wrap.querySelector('details.tool.bgrun[data-id="'+CSS.escape(x.tool_id)+'"]')||
    [...wrap.querySelectorAll('details.tool[data-id="'+CSS.escape(x.tool_id)+'"]')].find(r=>/background/i.test((r.querySelector('.tsum')||{}).textContent||''));
   if(row)subagentDone(row,{description:x.title,tools:+x.tools||(row._steps||[]).length,tokens:+x.tokens||0,
    secs:x.secs,status:(x.status||'').split(' ')[0],summary:x.summary||'',
    steps:(row._steps||[]).concat(x.steps||[])})})}catch(e){}}
setInterval(pollBg,8000);setTimeout(pollBg,1500);
// the git line in the dock: it only ever refreshed when you left the window and came
// back, so a repo could sit there all session showing the state it had on open
setInterval(()=>{if(!document.hidden&&sid)pollGit()},15000);
/* Reading three files in a row is one thought, not three rows: finished look-ups fold
   into a single line ("Read 3 files, Searched for 1 pattern") you can open. */
function famLabel(g){const counts={};
 g.querySelectorAll('.tgbody>details.tool').forEach(r=>{
  const f=r.dataset.fam;if(f)counts[f]=(counts[f]||0)+1});
 return Object.entries(counts).map(([f,n])=>{
  const w=FAMWORD[f]||['Ran','call','calls'];return w[0]+' '+plural(n,w[1],w[2])}).join(', ')}
function updateGroup(g){
 const n=g.querySelectorAll('.tgbody>details.tool').length;
 if(!n){g.remove();return}
 if(n===1){const only=g.querySelector('.tgbody>details.tool');g.replaceWith(only);return}
 g.querySelector('.tn').textContent=famLabel(g);
 // "Read 3 files" says how many and not which, so scanning a transcript for "did it
 // touch config.py?" meant opening every fold. Name a few of them.
 const head=g.querySelector('.thead');
 let chips=head.querySelector('.tgchips');
 if(!chips){chips=el('<span class=tgchips></span>');
  head.insertBefore(chips,head.querySelector('.tt'))}
 chips.innerHTML='';
 const names=[];
 g.querySelectorAll('.tgbody>details.tool').forEach(r=>{
  const t=(r.querySelector('.tl')||{}).textContent||'';
  const nm=shortPath(t.split(/\s/)[0]);
  if(nm&&!names.includes(nm))names.push(nm)});
 names.slice(0,3).forEach(nm=>{const c=document.createElement('span');
  c.className='tgchip';c.textContent=nm;chips.appendChild(c)});
 if(names.length>3){const c=document.createElement('span');
  c.className='tgchip more';c.textContent='+'+(names.length-3);chips.appendChild(c)}
 const secs=[...g.querySelectorAll('.tgbody>details.tool')]
   .reduce((a,r)=>a+(parseFloat(r.dataset.secs)||0),0);
 g.querySelector('.tt').textContent=secs>=0.5?fmtSecs(secs):''}
function groupTool(row,_depth,live){
 if(!row||!row.dataset.fam||row.classList.contains('bad')||row.classList.contains('live'))return;
 // calls made in parallel finish in any order: once this one is done, the one after it
 // (already done, and waiting on this one) may fold in too
 let after=row.nextElementSibling;
 while(after&&after.classList.contains('vonly'))after=after.nextElementSibling;
 if(!_depth&&after&&after.matches('details.tool.done'))setTimeout(()=>groupTool(after,1,live),0);
 // notes shown only with Ctrl+O (auto-approvals) sit between calls without splitting them
 let prev=row.previousElementSibling;
 while(prev&&prev.classList.contains('vonly'))prev=prev.previousElementSibling;
 // first call of a step that has said nothing yet: it carries on the step before, so it
 // may fold into that step's last look-up (the same as a reopened chat draws it)
 if(!prev&&live){
  const blk=row.closest('.msg.a'),pb=blk&&blk.previousElementSibling;
  const quiet=blk&&blk._a&&(!blk._a.bub.textContent.trim()||blk._a.bub.querySelector('.working'))
   &&blk._a.think.style.display==='none';
  if(quiet&&pb&&pb.classList.contains('a')&&pb._a){
   let last=pb._a.tools.lastElementChild;
   while(last&&last.classList.contains('vonly'))last=last.previousElementSibling;
   if(last&&(last.matches('details.tgroup')||(last.matches('details.tool.done')&&last.dataset.fam&&!last.classList.contains('bad')))){
    pb._a.tools.appendChild(row);prev=last}}}
 if(!prev)return;
 if(prev.matches('details.tgroup')){prev.querySelector('.tgbody').appendChild(row);updateGroup(prev);return}
 if(prev.matches('details.tool.done')&&prev.dataset.fam&&!prev.classList.contains('bad')){
  const g=el('<details class=tgroup><summary><span class=tdot>⏺</span><span class=tn></span>'+
   '<span class=tt></span></summary><div class=tgbody></div></details>');
  if(VERBOSE)g.open=true;
  prev.before(g);const body=g.querySelector('.tgbody');body.appendChild(prev);body.appendChild(row);
  updateGroup(g)}}
// A forty-minute run leaves hundreds of tool rows in the transcript, and scrolling back
// through it means scrolling past all of them. Once the turn is done they fold behind one
// line saying how long it took and what it did; the turn you care about opens with a click.
// In a Claude Code chat every tool call is its own assistant block, so folding each
// block on its own achieves nothing -- the unit that matters is the turn: everything
// between your message and the answer it ended with. That run folds behind one line,
// and the answer stays where it is.
// Find in this conversation. The browser's own find cannot see inside a collapsed turn
// or a closed thinking block, which is most of a long run — this opens what it has to.
const FIND={hits:[],at:-1,bar:null,opened:[],timer:null};
function findClose(){
 clearTimeout(FIND.timer);FIND.timer=null;
 FIND.hits.forEach(m=>{const t=document.createTextNode(m.textContent);
  const par=m.parentNode; if(par){par.replaceChild(t,m);par.normalize()}});
 FIND.opened.forEach(d=>{d.open=false});
 FIND.hits=[];FIND.at=-1;FIND.opened=[];
 if(FIND.bar){FIND.bar.remove();FIND.bar=null}}

function findRun(q){
 FIND.hits.forEach(m=>{const t=document.createTextNode(m.textContent);
  const par=m.parentNode; if(par){par.replaceChild(t,m);par.normalize()}});
 FIND.hits=[];FIND.at=-1;
 if(!q)return findDraw();
 const low=q.toLowerCase();
 const walk=document.createTreeWalker(wrap,NodeFilter.SHOW_TEXT,{acceptNode:n=>
   n.nodeValue&&n.nodeValue.toLowerCase().includes(low)&&!/^(SCRIPT|STYLE|MARK)$/.test(n.parentNode.nodeName)
     ?NodeFilter.FILTER_ACCEPT:NodeFilter.FILTER_REJECT});
 const targets=[];let n;
 while((n=walk.nextNode()))targets.push(n);
 targets.slice(0,400).forEach(node=>{
  const text=node.nodeValue;const frag=document.createDocumentFragment();
  let i=0,j;
  while((j=text.toLowerCase().indexOf(low,i))>=0){
   if(j>i)frag.appendChild(document.createTextNode(text.slice(i,j)));
   const mk=document.createElement('mark');mk.className='findhit';
   mk.textContent=text.substr(j,q.length);frag.appendChild(mk);FIND.hits.push(mk);
   i=j+q.length}
  if(i<text.length)frag.appendChild(document.createTextNode(text.slice(i)));
  node.parentNode.replaceChild(frag,node)});
 findDraw();
 if(FIND.hits.length)findGo(0)}

function findGo(k){
 if(!FIND.hits.length)return;
 FIND.at=(k+FIND.hits.length)%FIND.hits.length;
 FIND.hits.forEach(m=>m.classList.remove('on'));
 const m=FIND.hits[FIND.at];m.classList.add('on');
 // open whatever it is hiding inside, and remember to close it again
 let p=m.parentElement;
 while(p&&p!==wrap){if(p.tagName==='DETAILS'&&!p.open){p.open=true;FIND.opened.push(p)}p=p.parentElement}
 m.scrollIntoView({block:'center'});
 findDraw()}

function findDraw(){
 if(!FIND.bar)return;
 const c=FIND.bar.querySelector('.findcount');
 c.textContent=FIND.hits.length?`${FIND.at+1}/${FIND.hits.length}`:(FIND.bar.querySelector('input').value?'none':'')}

function openFind(){
 if(FIND.bar){FIND.bar.querySelector('input').select();return}
 const bar=el(`<div class=findbar><input type=search placeholder="Find in this chat" spellcheck=false>
   <span class=findcount></span><button class=ghost data-a=prev>↑</button>
   <button class=ghost data-a=next>↓</button><button class=ghost data-a=x>✕</button></div>`);
 FIND.bar=bar;document.body.appendChild(bar);
 const inp=bar.querySelector('input');
 // the debounce has to die with the bar: typing and pressing Escape inside 160ms used
 // to leave a highlighted chat with no bar left to clear it
 inp.addEventListener('input',()=>{clearTimeout(FIND.timer);
  FIND.timer=setTimeout(()=>{if(FIND.bar)findRun(inp.value.trim())},160)});
 inp.addEventListener('keydown',e=>{
  if(e.key==='Enter'){e.preventDefault();findGo(FIND.at+(e.shiftKey?-1:1))}
  if(e.key==='Escape'){e.preventDefault();findClose()}});
 bar.querySelector('[data-a=next]').onclick=()=>findGo(FIND.at+1);
 bar.querySelector('[data-a=prev]').onclick=()=>findGo(FIND.at-1);
 bar.querySelector('[data-a=x]').onclick=findClose;
 inp.focus()}

// Folding moves the earlier blocks of a turn inside a <details> that is not itself a
// .msg, so removing the messages (retry, regenerate, edit) leaves the summary line
// behind -- "worked for 41s · 5 steps" opening onto nothing.
function dropEmptyFolds(){
 wrap.querySelectorAll('details.toolfold').forEach(d=>{
  if(!d.querySelector('.msg'))d.remove()})}

function foldTurns(){
 const kids=[...wrap.children];
 let run=[];
 const flush=()=>{
  if(run.length>1){
   const steps=run.reduce((n,b)=>n+(b._a&&b._a.tools?[...b._a.tools.children]
     .filter(x=>x.classList&&(x.classList.contains('tool')||x.tagName==='DETAILS')).length:0),0);
   const bad=run.reduce((n,b)=>n+b.querySelectorAll('.bad').length,0);
   const last=run[run.length-1];
   const hide=run.slice(0,-1);                 // keep the block that carries the answer
   if(steps>=3&&hide.length&&!hide.some(b=>b.closest('.toolfold'))){
    const d=el('<details class="think toolfold"></details>');
    const secs=(last._a&&last._a._secs)||0;
    d.appendChild(el(`<summary>worked for ${fmtSecs(secs)} · ${steps} step${steps===1?'':'s'}`
      +(bad?` · ${bad} failed`:'')+`</summary>`));
    const body=el('<div class=foldbody></div>');
    hide[0].before(d);
    hide.forEach(b=>body.appendChild(b));
    d.appendChild(body);
    if(bad)d.open=true;
    d.querySelector('summary').addEventListener('click',()=>{d._user=true})}}
  run=[]};
 kids.forEach(k=>{
  if(!k.classList)return;
  if(k.classList.contains('a')){run.push(k);return}
  flush()});
 flush()}

function answerStats(a,secs,usage){
 a._secs=secs;
 const who=a.m.querySelector('.who');let s=who.querySelector('.bystat');
 if(!s){s=el('<span class=bystat></span>');who.querySelector('.byline').after(s)}
 const out=usage&&+usage.completion_tokens,parts=[];
 if(secs!=null&&isFinite(secs))parts.push(fmtSecs(secs));
 if(out){parts.push(out.toLocaleString()+' tok');if(secs>0)parts.push((out/secs).toFixed(1)+' tok/s')}
 s.textContent=parts.length?'· '+parts.join(' · '):'';
 if(usage&&usage.prompt_tokens)s.title=(+usage.prompt_tokens).toLocaleString()+' prompt tokens'}
function savedAssistant(m,merge){
 const prev=wrap.lastElementChild;
 if(merge&&prev&&prev._a&&prev.classList.contains('a')&&!m.text&&!m.thinking&&!(m.plots||[]).length
    &&(m.tool_runs||[]).length&&!(m.changes||[]).length&&m.secs==null&&!m.usage){
  m.tool_runs.forEach(r=>{const row=toolRow(r,true);prev._a.tools.appendChild(row);groupTool(row)});
  return prev._a}
 const a=addAssistant(m.model,m.t??null);
 if((m.tool_runs||[]).length)m.tool_runs.forEach(r=>{const row=toolRow(r,true);a.tools.appendChild(row);groupTool(row)});
 else (m.tools||[]).forEach(t=>{const c=el('<div class=tool></div>');c.textContent='* '+t;a.tools.appendChild(c)});
 if((m.plots||[]).length){const box=el('<div class=imgs></div>');
  m.plots.forEach(u=>{const i=document.createElement('img');i.src=u;i.style.cursor='zoom-in';
   i.onclick=()=>window.open(u,'_blank');box.appendChild(i)});a.tools.appendChild(box)}
 a.bub.dataset.raw=m.text;a.bub._changes=(m.changes||[]).map(c=>c.path).filter(Boolean);a.bub.innerHTML=md(m.text);decorate(a.bub);
 if(m.thinking)showSavedThinking(a,m.thinking,m.t,m.thinking_marks);
 if(!m.text&&!m.thinking&&!(m.tool_runs||[]).length&&!(m.tools||[]).length)
  a.bub.innerHTML='<span style="color:var(--mut)">(stopped before it wrote anything)</span>';
 (m.tool_summaries||[]).forEach(t=>toolSummaryLine(t.ids,t.text,a.tools));
 if(m.secs!=null||m.usage)answerStats(a,m.secs,m.usage);

 if((m.changes||[]).length&&!m.changes_undone&&m.t)undoButton(a,m.t,m.changes.length);
 if((m.changes||[]).length&&m.changes_undone&&m.can_redo&&m.t)redoButton(a,m.t,m.changes.length);
 return a}
// The part of a changed line that actually changed: what is left between the prefix and
// suffix the old and new line share. A one-character edit in a long line was otherwise
// a whole red line and a whole green one to compare by eye.
function wordSpan(a,b){
 let i=0;while(i<a.length&&i<b.length&&a[i]===b[i])i++;
 let j=0;while(j<a.length-i&&j<b.length-i&&a[a.length-1-j]===b[b.length-1-j])j++;
 return [[i,a.length-j],[i,b.length-j]]}
// Comments on diff lines, for the model: written against a line, gathered in a chip
// above the box, and put into your message together when you are done reading.
let DIFF_NOTES=[];
function diffCommentBox(after,path,r){
 if(after.nextElementSibling&&after.nextElementSibling.classList.contains('dnote'))return after.nextElementSibling.querySelector('input').focus();
 const box=el('<span class=dnote><input placeholder="What should change here? Enter to add, Esc to cancel"></span>');
 after.after(box);const inp=box.querySelector('input');inp.focus();
 inp.onkeydown=e=>{e.stopPropagation();
  if(e.key==='Escape'){box.remove();return}
  if(e.key==='Enter'&&inp.value.trim()){
   DIFF_NOTES.push({sid,path,line:r.num,side:r.kind==='d'?'removed':r.kind==='a'?'added':'',code:r.text.trim().slice(0,200),text:inp.value.trim()});
   box.replaceWith(Object.assign(el('<span class=dnote done></span>'),{textContent:'💬 '+inp.value.trim()}));
   drawDiffNotes()}}}
function drawDiffNotes(){
 document.querySelectorAll('#chips .notechip').forEach(x=>x.remove());
 const mine=DIFF_NOTES.filter(n=>n.sid===sid);if(!mine.length)return;
 const c=el(`<div class="chip notechip"><b>💬 ${mine.length} comment${mine.length>1?'s':''} on the changes</b>
  <button class=ghost data-n=add>add to message</button><span class=x title="discard them">&times;</span></div>`);
 c.querySelector('[data-n=add]').onclick=()=>{
  const lines=mine.map(n=>`- ${n.path.split('/').slice(-2).join('/')}:${n.line}${n.side?' ('+n.side+')':''} \`${n.code}\` — ${n.text}`);
  q.value=(q.value.trim()?q.value.trim()+'\n\n':'')+'Comments on your changes:\n'+lines.join('\n');
  DIFF_NOTES=DIFF_NOTES.filter(n=>n.sid!==sid);drawDiffNotes();closeModal();q.focus();fitQ()};
 c.querySelector('.x').onclick=()=>{DIFF_NOTES=DIFF_NOTES.filter(n=>n.sid!==sid);drawDiffNotes()};
 $('#chips').appendChild(c)}
function diffBlock(D,label,opts){
 opts=opts||{};
 const box=el('<div class=diff></div>');
 box.appendChild(el(`<div class=dh><b>${esc((D.path||'').split('/').pop())}</b>
   <span class=add>+${+D.added||0}</span><span class=del>−${+D.removed||0}</span>
   <span style="margin-left:auto;color:var(--dim)">${esc(label||(D.existed?'updated':'new file'))}</span></div>`));
 const lines=String(D.diff||'').split('\n');
 // a very large diff waits to be asked for: drawing thousands of rows froze the page
 if(lines.length>500&&!opts.all){
  const more=el(`<div class=sheetnote style="padding:8px 10px">A large change — ${lines.length.toLocaleString()} diff lines. <a style="cursor:pointer;color:var(--acc)">Show it</a></div>`);
  more.querySelector('a').onclick=()=>box.replaceWith(diffBlock(D,label,{all:true}));
  box.appendChild(more);return box}
 // each line with its number in the file, as Claude Code shows an edit: the new
 // number for added and unchanged lines, the old one for removed lines
 const rows=[];
 let oldN=0,newN=0,inHunk=false;
 lines.forEach(l=>{
  // the file headers come before the first hunk; inside one, a removed "-- comment" or
  // an added "++i" is a real line and used to vanish from the diff
  if(!inHunk&&(l.startsWith('+++')||l.startsWith('---')))return;
  const hunk=l.match(/^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
  if(hunk){inHunk=true;oldN=+hunk[1];newN=+hunk[2];rows.push({kind:'h',text:l});return}
  // a diff too long to show says so at its end
  if(/^\.\.\. \d+ more diff lines not shown/.test(l)){rows.push({kind:'h',text:l});return}
  const kind=l.startsWith('+')?'a':l.startsWith('-')?'d':'';
  let num='';
  if(kind==='a')num=newN++;
  else if(kind==='d')num=oldN++;
  else if(l.length||oldN||newN){num=newN;oldN++;newN++}
  rows.push({kind,num,text:l.slice(kind||l.startsWith(' ')?1:0)})});
 // a run of removed lines followed by as many added ones: pair them up, line by line
 for(let i=0;i<rows.length;){
  if(rows[i].kind!=='d'){i++;continue}
  let d=i;while(d<rows.length&&rows[d].kind==='d')d++;
  let a=d;while(a<rows.length&&rows[a].kind==='a')a++;
  if(a-d===d-i&&d-i<=12)for(let k=0;k<d-i;k++){
   const o=rows[i+k],n=rows[d+k];if(o.text.length>400||n.text.length>400)continue;
   const [so,sn]=wordSpan(o.text,n.text);
   if(so[1]-so[0]<o.text.length||sn[1]-sn[0]<n.text.length){o.w=so;n.w=sn}}
  i=Math.max(a,i+1)}
 const pre=document.createElement('pre');
 rows.forEach(r=>{
  const sp=document.createElement('span');
  if(r.kind==='h'){sp.className='h';sp.textContent=r.text;pre.appendChild(sp);return}
  sp.className=r.kind;
  const num=el('<i class=ln title="comment on this line"></i>');num.textContent=r.num;sp.appendChild(num);
  if(r.num!==''&&D.path)num.onclick=e=>{e.stopPropagation();diffCommentBox(sp,D.path,r)};
  const sign=el('<i class=sg></i>');sign.textContent=r.kind==='a'?'+':r.kind==='d'?'-':' ';sp.appendChild(sign);
  if(r.w&&r.w[1]>r.w[0]){
   sp.appendChild(document.createTextNode(r.text.slice(0,r.w[0])));
   const m=document.createElement('mark');m.className='wd';m.textContent=r.text.slice(r.w[0],r.w[1]);sp.appendChild(m);
   sp.appendChild(document.createTextNode(r.text.slice(r.w[1])))}
  else sp.appendChild(document.createTextNode(r.text));
  pre.appendChild(sp)});
 box.appendChild(pre);return box}
if(PREF.get('hidetools','0')==='1')log.classList.add('hidedone');
VERBOSE=PREF.get('verbose','0')==='1';log.classList.toggle('verbose',VERBOSE);
if(PREF.get('plandock','1')==='0'){const _pd=$('#plandock');if(_pd)_pd.dataset.hidden='1'}

/* ---------------- /tasks ----------------
   Claude Code's background-task list: every chat answering now (and what it is doing),
   messages waiting in a queue, and shell commands a model left running -- each with a
   way to open or stop it. */
async function showTasks(){
 let d;try{d=await (await fetch('/api/tasks')).json()}catch(e){toast('could not read the tasks');return}
 const items=d.items||[];
 openSheet('Background tasks',body=>{
  if(!items.length){body.appendChild(el('<div class=sheetnote>Nothing is running in the background.</div>'));return}
  const label={answer:'answering',queued:'queued',shell:'shell',background:'background'};
  items.forEach(it=>{
   const r=el('<div class=taskrow><span class=tkind></span><div class=tmain><div class=ttitle></div><div class=tsub></div></div><div class=tacts></div></div>');
   r.querySelector('.tkind').textContent=label[it.kind]||it.kind;
   r.querySelector('.tkind').classList.add('k-'+it.kind);
   r.querySelector('.ttitle').textContent=it.title||it.id;
   const sub=[it.status];
   if(it.since)sub.push(it.ended?'took '+fmtSecs(it.ended-it.since):'for '+fmtSecs(d.now-it.since));
   if(it.text)sub.push('“'+it.text+'”');
   if(it.kind==='background'&&it.chat)sub.push('in “'+it.chat+'”');
   r.querySelector('.tsub').textContent=sub.filter(Boolean).join(' · ');
   const acts=r.querySelector('.tacts');
   if(it.kind==='background'){
    // Claude desktop's task list: open one to see what it has done so far
    const o=el('<button class=ghost>open</button>');o.title='what it has written so far';
    o.onclick=()=>showTaskOutput(it);acts.appendChild(o);
    r.style.cursor='pointer';r.onclick=e=>{if(!e.target.closest('button'))showTaskOutput(it)}}
   else if(it.sid){const o=el('<button class=ghost>open</button>');
    o.onclick=()=>{closeModal();showPane('log');openSession(it.sid)};acts.appendChild(o)}
   if(it.can_stop){const x=el(`<button class=ghost>${it.kind==='queued'?'remove':'stop'}</button>`);
    x.onclick=async()=>{
     let ok;
     if(it.kind==='answer')ok=await apiPost('/api/cancel',{sid:it.sid},'stopping');
     else if(it.kind==='queued')ok=await apiPost('/api/queue',{sid:it.sid,op:'remove',id:it.id},'removing');
     else ok=await apiPost('/api/tasks/stop',{kind:it.kind,id:it.id,sid:it.sid},'stopping');
     if(ok){x.disabled=true;x.textContent=it.kind==='queued'?'removed':'stopped';refreshRunning()}};
    acts.appendChild(x)}
   body.appendChild(r)})})}
// One background task: a shell's output as it grows, or a subagent's steps and words;
// kept current while it runs, with a way to its chat.
async function showTaskOutput(it){
 const url='/api/tasks/output?sid='+encodeURIComponent(it.sid||'')+'&id='+encodeURIComponent(it.id);
 let timer=null;
 openSheet(it.title||'Background task',async body=>{
  body.style.padding='12px 18px 16px';
  body.innerHTML='<div class=sheetnote>loading…</div>';
  const draw=async()=>{
   if(!body.isConnected){clearInterval(timer);return}
   let d;try{const r=await fetch(url);d=await r.json();if(!r.ok)throw new Error(d.error||r.status)}
   catch(e){body.innerHTML='';const x=el('<div class=sheetnote></div>');x.textContent='Its output is no longer available ('+(e.message||e)+').';body.appendChild(x);clearInterval(timer);return}
   const running=/^(running|pending)/.test(d.status||'');
   const stick=!body.querySelector('pre')||body.querySelector('pre').scrollTop+body.querySelector('pre').clientHeight>=body.querySelector('pre').scrollHeight-8;
   body.innerHTML='';
   const head=el('<div class=taskhead></div>');
   head.textContent=[(d.kind==='agent'?'subagent':'shell'),running?'running':(d.status||'ended'),
    d.since?(running?'for ':'took ')+fmtSecs(((d.ended||Date.now()/1000)-d.since)):'',
    d.tools?plural(+d.tools,'tool use','tool uses'):'',d.tokens?fmtTok(+d.tokens)+' tokens':''].filter(Boolean).join(' \u00b7 ');
   body.appendChild(head);
   if(d.command){const c=el('<div class=taskcmd></div>');c.textContent='$ '+d.command;body.appendChild(c)}
   if((d.steps||[]).length&&!d.output){const b=subStepsBox({steps:d.steps,tools:d.tools,type:'steps'});body.appendChild(b)}
   const pre=el('<pre class=taskout></pre>');
   pre.textContent=d.output||d.summary||(running?'(nothing written yet)':'(no output)');
   body.appendChild(pre);if(stick)pre.scrollTop=pre.scrollHeight;
   if(d.summary&&d.output){const sm=el('<div class=sheetnote></div>');sm.textContent='Reported: '+d.summary;body.appendChild(sm)}
   const acts=el('<div class=row2 style="margin-top:8px"></div>');
   if(d.output){const cp=el('<button class=ghost>copy output</button>');cp.onclick=()=>copy(d.output);acts.appendChild(cp)}
   if(it.sid&&d.chat_saved&&it.sid!==sid){const g=el('<button class=ghost>go to its chat</button>');
    g.onclick=()=>{closeModal();showPane('log');openSession(it.sid)};acts.appendChild(g)}
   body.appendChild(acts);
   if(!running&&timer){clearInterval(timer);timer=null}};
  await draw();
  timer=setInterval(draw,2000)},{sub:it.chat?'in “'+it.chat+'”':'background task'})}
$('#runbadge').style.cursor='pointer';$('#runbadge').title='what is running — /tasks';
$('#runbadge').addEventListener('click',showTasks);

/* ---------------- what fills the context, copying, diffs, the command list ---------------- */
// Claude Code's /context: the window as a grid of squares, one part per colour
async function showContext(){
 let d;try{d=await (await fetch('/api/context?full=1'+(sid?'&sid='+encodeURIComponent(sid):''))).json()}
 catch(e){toast('could not read the context');return}
 openSheet('Context window',body=>{
  const max=d.max||1,used=d.used||0;
  const parts=Object.entries(d.parts||{}).sort((a,b)=>b[1]-a[1]);
  const colours=['var(--acc)','var(--tool)','var(--think)','var(--ok)','var(--warn)','var(--err)','var(--dim)'];
  body.appendChild(el(`<div class=sheetnote>${Math.round(100*used/max)}% used —
   ${used.toLocaleString()} of ${max.toLocaleString()} tokens, ${(d.free||0).toLocaleString()} free
   ${d.basis==='measured'?'(measured)':'(estimated)'}.
   ${d.autocompact_at?'Orbit compacts by itself at '+d.autocompact_at+'%.':''}</div>`));
  // 100 squares, each one per cent of the window
  const grid=el('<div class=ctxgrid></div>');
  let cell=0;const cells=[];
  parts.forEach(([name,tok],i)=>{
   const n=Math.round(100*tok/max);
   for(let k=0;k<n&&cell<100;k++,cell++)cells.push([colours[i%colours.length],name+' — '+tok.toLocaleString()+' tokens'])});
  while(cell<100){cells.push(['var(--line)','free']);cell++}
  cells.forEach(([c,t])=>{const sq=el('<span class=ctxcell></span>');
   sq.style.background=c;sq.title=t;grid.appendChild(sq)});
  body.appendChild(grid);
  const list=el('<div class=ctxlist></div>');
  parts.forEach(([name,tok],i)=>{
   const r=el('<div class=ctxrow></div>');
   const dot=el('<span class=ctxdot></span>');dot.style.background=colours[i%colours.length];
   r.appendChild(dot);
   const nm=el('<span class=ctxname></span>');nm.textContent=name;r.appendChild(nm);
   const v=el('<span class=ctxval></span>');
   v.textContent=tok.toLocaleString()+' · '+Math.round(100*tok/max)+'%';r.appendChild(v);
   list.appendChild(r)});
  const foot=el('<div class=ctxrow></div>');
  foot.appendChild(el('<span class=ctxdot style="background:var(--line)"></span>'));
  foot.appendChild(el('<span class=ctxname>free</span>'));
  const fv=el('<span class=ctxval></span>');
  fv.textContent=(d.free||0).toLocaleString()+' · '+Math.round(100*(d.free||0)/max)+'%';
  foot.appendChild(fv);list.appendChild(foot);
  body.appendChild(list);
  body.appendChild(el(`<div class=sheetnote>${d.messages||0} messages${d.images?' · '+d.images+' image'+(d.images>1?'s':''):''}</div>`));
  const act=el('<button class=primary>Compact now</button>');
  act.onclick=()=>{closeModal();doCompact()};body.appendChild(act)})}
// /copy — the last answer, or the Nth from the end, as Markdown
function copyAnswer(n){
 const bubs=[...wrap.querySelectorAll('.msg.a .bub')].filter(b=>(b.dataset.raw||b.textContent).trim());
 const b=bubs[bubs.length-(n||1)];
 if(!b){toast('no answer to copy');return}
 const text=b.dataset.raw||b.textContent;
 navigator.clipboard.writeText(text).then(()=>toast('copied '+(n>1?'answer '+n+' back':'the last answer')),
  ()=>toast('could not copy'))}
// /diff — every file change this chat has shown, newest first
/* ---------------- goals ----------------
   What a chat keeps working toward across answers. The Mac drives it (checks the work
   after each answer, carries on or stops); this shows where it stands and its controls. */
const GOALS={}, GOAL_OFFERS={};
let GOAL_HIST_OPEN=false, OFFER_TICK=null;
// An answer that left work undone: the Mac offers to keep going until it is done, and
// takes the offer on its own when the countdown runs out (Settings -> General).
function setGoalOffer(s,p){
 GOAL_OFFERS[s]=p?{...p,deadline:p.remaining!=null?Date.now()+p.remaining*1000:null}:null;
 if(s===sid)drawGoal();
 if(p)notify(s,"Keep going until it's done?",p.why||'')}
const GOAL_WORD={active:'working toward',paused:'paused',blocked:'needs you',budget:'over budget',complete:'done'};
async function loadGoal(s){
 try{const d=await (await fetch('/api/goal',{method:'POST',headers:{'Content-Type':'application/json'},
  body:JSON.stringify({sid:s,op:'get'})})).json();GOALS[s]=d.goal||null;if(s===sid)drawGoal()}catch(e){}}
// After an answer the Mac checks the goal, which takes a few seconds and can end in a
// verdict that changes nothing else on screen: keep asking until it settles, or the
// next answer it starts takes over.
async function followGoal(s){
 if(followGoal.busy&&followGoal.busy[s])return;(followGoal.busy=followGoal.busy||{})[s]=true;
 try{for(let i=0;i<20;i++){
  await loadGoal(s);const g=GOALS[s];
  if(!g||g.status!=='active'||RUNNING.has(s))break;
  await new Promise(r=>setTimeout(r,3000))}}
 finally{delete followGoal.busy[s];if(s===sid)loadSessions()}}
function drawOffer(bar,o){
 bar.className='goalbar g-offer';bar.style.display='';
 bar.innerHTML=`<span class=gst>◎ Keep going until it's done?</span><span class=gobj></span>
  <button class=primary data-o=accept>Keep going until done</button><button class=ghost data-o=decline>No thanks</button>
  <span class=greason></span>`;
 bar.querySelector('.gobj').textContent=o.objective;bar.querySelector('.gobj').title=o.objective;
 const why=bar.querySelector('.greason');
 const tick=()=>{if(!bar.isConnected||GOAL_OFFERS[sid]!==o){clearInterval(OFFER_TICK);return}
  const left=o.deadline?Math.max(0,Math.round((o.deadline-Date.now())/1000)):null;
  why.textContent=(o.why?o.why[0].toUpperCase()+o.why.slice(1):'')+(left!=null?
   (left>0?` · it carries on by itself in ${Math.floor(left/60)}:${String(left%60).padStart(2,'0')}`:' · carrying on…'):'');
  if(left===0){clearInterval(OFFER_TICK);const s=sid;
   setTimeout(async()=>{delete GOAL_OFFERS[s];await loadGoal(s);if(GOALS[s])afterTurn(s)},2500)}};
 clearInterval(OFFER_TICK);tick();OFFER_TICK=setInterval(tick,1000);
 bar.querySelectorAll('[data-o]').forEach(b=>b.onclick=async()=>{
  const s=sid,op=b.dataset.o;
  const d=await apiPost('/api/goal',{sid:s,op},'the offer');
  delete GOAL_OFFERS[s];
  if(d){GOALS[s]=d.goal||GOALS[s]||null;if(d.started){toast('carrying on toward the goal');setTimeout(()=>afterTurn(s),600)}}
  if(s===sid)drawGoal();loadSessions()})}
function drawGoal(){
 const bar=$('#goalbar');if(!bar)return;
 const g=sid&&GOALS[sid], o=sid&&GOAL_OFFERS[sid];
 if(o&&(!g||g.status==='complete'))return drawOffer(bar,o);
 if(!g){bar.style.display='none';bar.innerHTML='';return}
 bar.className='goalbar g-'+g.status;bar.style.display='';
 const meta=[`${g.turns_used||0}/${g.max_turns} turns`];
 if(g.token_budget)meta.push(`${(g.tokens_used||0).toLocaleString()}/${g.token_budget.toLocaleString()} tokens`);
 else if(g.tokens_used)meta.push(`${g.tokens_used.toLocaleString()} tokens`);
 bar.innerHTML=`<span class=gst>◎ ${esc(GOAL_WORD[g.status]||g.status)}</span><span class=gobj></span>
  <span class=gmeta>${esc(meta.join(' · '))}</span>
  ${g.status==='active'?'<button class=ghost data-g=pause>pause</button>':''}
  ${g.status!=='active'&&g.status!=='complete'?'<button class=ghost data-g=resume>resume</button>':''}
  <button class=ghost data-g=edit>edit</button><button class=ghost data-g=clear>clear</button>
  ${(g.history||[]).length>1?`<button class=ghost data-g=history>${GOAL_HIST_OPEN?'hide':'history'}</button>`:''}
  ${g.reason?'<span class=greason></span>':''}
  ${GOAL_HIST_OPEN&&(g.history||[]).length?'<div class=ghist></div>':''}`;
 bar.querySelector('.gobj').textContent=g.objective;bar.querySelector('.gobj').title=g.objective;
 if(g.reason)bar.querySelector('.greason').textContent=g.reason;
 // what each check said, newest first: why it carried on, and why it stopped
 const hist=bar.querySelector('.ghist');
 if(hist)(g.history||[]).slice().reverse().forEach(h=>{
  const r=el('<div class=ghrow><span class=ght></span><b></b><span></span></div>');
  r.querySelector('.ght').textContent=new Date(h.t*1000).toLocaleTimeString([],{hour:'numeric',minute:'2-digit'});
  r.querySelector('b').textContent=h.verdict;r.querySelector('span:last-child').textContent=h.reason||'';
  hist.appendChild(r)});
 bar.querySelectorAll('[data-g]').forEach(b=>b.onclick=()=>{
  if(b.dataset.g==='history'){GOAL_HIST_OPEN=!GOAL_HIST_OPEN;drawGoal();return}goalOp(b.dataset.g)})}
async function goalOp(op,extra){
 const s=sid;
 if(op==='edit')return editGoal();
 if(op==='clear'&&!confirm('Stop keeping this goal? The chat stays as it is.'))return;
 let body={sid:s,op,...(extra||{})};
 if(op==='resume'){const g=GOALS[s]||{};
  if(g.token_budget&&g.tokens_used>=g.token_budget){
   const nb=prompt('It has used its budget. New token budget:',String(g.token_budget*2));if(!nb)return;
   body.token_budget=parseInt(nb,10)||0}}
 const d=await apiPost('/api/goal',body,'the goal');if(!d)return;
 GOALS[s]=d.goal||null;if(s===sid)drawGoal();
 if(d.started){toast('carrying on toward the goal');setTimeout(()=>afterTurn(s),600)}
 loadSessions()}
function editGoal(){
 if(!sid){toast('open a chat first');return}
 const g=GOALS[sid];
 openSheet(g?'Goal':'Set a goal',body=>{
  body.appendChild(el(`<div class=sheetnote>The chat keeps working until this is done: after each answer the Mac checks the work against it and carries on, or stops and says why — done, stuck three times running, over its budget, or after its turn limit. Stop pauses it.</div>`));
  const ta=el('<textarea class=ta style="min-height:110px" placeholder="What done looks like — e.g. every test in tests/ passes and the README documents the new flag"></textarea>');
  ta.value=g?g.objective:'';body.appendChild(ta);
  const row=el(`<div class=grid style="margin-top:8px"><label>Token budget</label><input type=number min=0 step=1000 id=gb placeholder="none"><label>Turn limit</label><input type=number min=1 max=200 id=gt></div>`);
  body.appendChild(row);
  row.querySelector('#gb').value=g&&g.token_budget?g.token_budget:'';row.querySelector('#gt').value=g?g.max_turns:20;
  const go_=el(`<button class=primary style="margin-top:10px">${g?'Save':'Set and start'}</button>`);body.appendChild(go_);
  go_.onclick=async()=>{const obj=ta.value.trim();if(!obj){toast('say what done looks like');return}
   const tb=parseInt(row.querySelector('#gb').value,10)||0, mt=parseInt(row.querySelector('#gt').value,10)||20;
   const d=await apiPost('/api/goal',{sid,op:g?'edit':'set',objective:obj,token_budget:tb,max_turns:mt},'the goal');
   if(!d)return;GOALS[sid]=d.goal;closeModal();drawGoal();
   if(!g)goalOp('resume')}})}
function showTurnDiff(){
 // what the last answer changed, as the command says; the whole chat only if it changed nothing
 const all=[...wrap.querySelectorAll('.diff')];
 if(!all.length){toast('no file changes in this chat yet');return}
 const us=[...wrap.querySelectorAll('.msg.u:not(.note)')], lastU=us[us.length-1];
 const mine=lastU?all.filter(b=>lastU.compareDocumentPosition(b)&Node.DOCUMENT_POSITION_FOLLOWING):all;
 const blocks=mine.length?mine:all;
 openSheet('Changes',body=>{
  body.appendChild(el('<div class=sheetnote>'+(mine.length?'What the last answer changed, in order.'
   :'The last answer changed no files — every change in this chat, newest first.')+'</div>'));
  (mine.length?blocks:blocks.slice().reverse()).forEach(b=>body.appendChild(b.cloneNode(true)))})}
// /help — the commands, with what each does
function showCommandHelp(){
 openSheet('Commands',body=>{
  body.appendChild(el('<div class=sheetnote>Type / in the box to filter these. '+
   'Saved prompts and, in a Claude Code chat, Claude’s own commands appear there too.</div>'));
  allCmds().forEach(c=>{
   const r=el('<div class=cmdrow></div>');
   const n=el('<code></code>');n.textContent=c.c;r.appendChild(n);
   const dd=el('<span></span>');dd.textContent=c.d||'';r.appendChild(dd);
   r.onclick=()=>{closeModal();q.value=c.c+' ';q.focus();q.dispatchEvent(new Event('input'))};
   body.appendChild(r)})})}

/* ---------------- the outline of a long chat ----------------
   The desktop app keeps a floating table of contents; here it lists your messages
   once a chat has a few, and jumps to one when you pick it. */
// The button sits just under the top bar, whatever that is: the chat-tab strip above it comes and goes, and the bar's own
// height changes with the window, so a fixed offset had it lying over the last toolbar button ("settings").
function placeOutline(){
 const o=$('#outline'),top=document.querySelector('main > .top'),m=$('main');
 if(top&&m){const y=top.getBoundingClientRect().bottom-m.getBoundingClientRect().top;
  if(o)o.style.top=Math.round(y+8)+'px';
  const r=$('#turnrail');if(r)r.style.top=Math.round(y+6)+'px'}}
addEventListener('resize',()=>placeOutline());
try{const ro=new ResizeObserver(()=>placeOutline());
 [document.querySelector('main > .top'),$('#tabstrip')].forEach(e=>e&&ro.observe(e))}catch(_){}
function drawOutline(){
 let o=$('#outline');
 const us=[...wrap.querySelectorAll('.msg.u:not(.note)')];
 if(us.length<3||$('#log').style.display==='none'){if(o)o.style.display='none';drawTurnRail();return}
 if(!o){o=el('<div id=outline class=outline><button class=olbtn title="outline of this chat">☰</button><div class=ollist></div></div>');
  $('main').appendChild(o);
  o.querySelector('.olbtn').onclick=e=>{e.stopPropagation();o.classList.toggle('open');fillOutline()};
  document.addEventListener('click',e=>{if(!o.contains(e.target))o.classList.remove('open')})}
 o.style.display='';placeOutline();
 if(o.classList.contains('open'))fillOutline();
 drawTurnRail()}

// A minimap of the conversation down the right edge: one bar per turn, as tall as that
// turn is long, the one you are reading lit. The outline behind the ☰ button answers
// "what did I ask", which is a different question from "how long is this and where am
// I in it" — and that one had no answer at all in a 60-turn chat.
let railSpy=null;
function drawTurnRail(){
 let r=$('#turnrail');
 const us=[...wrap.querySelectorAll('.msg.u:not(.note)')];
 if(us.length<4||$('#log').style.display==='none'||narrow()){
  if(railSpy){railSpy.disconnect();railSpy=null}    // the last chat's rows are gone
  if(r)r.style.display='none';return}
 if(!r){r=el('<div id=turnrail class=turnrail></div>');$('main').appendChild(r)}
 r.style.display='';
 placeOutline();
 r.innerHTML='';
 if(railSpy)railSpy.disconnect();
 railSpy=new IntersectionObserver(es=>{
  es.forEach(e=>{const b=r.children[+e.target.dataset.turn];
   if(b)b.classList.toggle('on',e.isIntersecting)})},{root:log,threshold:0});
 const heights=us.map((u,i)=>{
  const next=us[i+1];
  return Math.max(10,(next?next.offsetTop:wrap.scrollHeight)-u.offsetTop)});
 const tall=Math.max(...heights,1);
 us.forEach((u,i)=>{
  u.dataset.turn=i;
  const b=el('<div class=trbar></div>');
  b.style.height=Math.max(6,Math.round(26*heights[i]/tall))+'px';
  const t=((u.querySelector('.bub,.bangcmd')||{}).textContent||'').replace(/\s+/g,' ').trim();
  b.title=(i+1)+'. '+(t.slice(0,90)||'(image)');
  if(i===us.length-1&&RUNNING.has(sid))b.classList.add('busy');
  b.onclick=()=>{u.scrollIntoView({block:'start',behavior:'smooth'});
   u.classList.add('flash');setTimeout(()=>u.classList.remove('flash'),1500)};
  r.appendChild(b);railSpy.observe(u)})}
function fillOutline(){
 const o=$('#outline');if(!o)return;
 const list=o.querySelector('.ollist');list.innerHTML='';
 [...wrap.querySelectorAll('.msg.u:not(.note)')].forEach((u,i)=>{
  const t=((u.querySelector('.bub,.bangcmd')||{}).textContent||'').replace(/\s+/g,' ').trim();
  const r=el('<div class=olrow><span class=oln></span><span class=olt></span></div>');
  r.querySelector('.oln').textContent=i+1;r.querySelector('.olt').textContent=t.slice(0,90)||'(image)';
  r.onclick=()=>{u.scrollIntoView({block:'start',behavior:'smooth'});u.classList.add('flash');
   setTimeout(()=>u.classList.remove('flash'),1500);o.classList.remove('open')};
  list.appendChild(r)})}
new MutationObserver(()=>{clearTimeout(drawOutline._t);drawOutline._t=setTimeout(drawOutline,200)})
 .observe(wrap,{childList:true});

/* ---------------- an empty chat: the home page ----------------
   A new chat opens on a short greeting with what you can do from the box -- the way
   Claude Code opens -- and, around it, what you would otherwise go looking for: what
   is running or waiting on you, what is coming up, what is left of each allowance,
   how much you have used Orbit lately, and the chats you were last in. */
let HOME=null, HOME_AT=0, HOME_LOADING=false;
async function loadHome(force){
 if(HOME_LOADING||(!force&&Date.now()-HOME_AT<15000))return;
 HOME_LOADING=true;
 try{const r=await fetch('/api/home');if(r.ok){HOME=await r.json();HOME_AT=Date.now()}}
 catch(e){}
 finally{HOME_LOADING=false}
 drawHero(true)}
function heroVisible(){const h=$('#hero');return !!(h&&h.style.display!=='none')}
setInterval(()=>{if(heroVisible()&&!document.hidden)loadHome()},20000);
document.addEventListener('visibilitychange',()=>{if(!document.hidden&&heroVisible())loadHome()});
function fmtTok(n){n=+n||0;return n>=1e9?(n/1e9).toFixed(1)+'B':n>=1e6?(n/1e6).toFixed(1)+'M':n>=1e4?Math.round(n/1e3)+'k':n>=1e3?(n/1e3).toFixed(1)+'k':String(n)}
function inTime(t){const s=t-Date.now()/1000;
 if(s<=60)return s<-60?'overdue':'now';const m=Math.round(s/60);
 if(m<60)return 'in '+m+'m';const h=Math.floor(m/60);
 if(h<24)return 'in '+h+'h'+(m%60&&h<6?' '+(m%60)+'m':'');
 return new Date(t*1000).toLocaleString([], {weekday:'short',hour:'numeric',minute:'2-digit'})}
function heroCard(title,link,onLink,extra){
 const c=el(`<div class="hcard${extra?' '+extra:''}"><div class=hch><span class=hct></span></div></div>`);
 c.querySelector('.hct').textContent=title;
 if(link){const b=el('<button class=hcl></button>');b.textContent=link;b.onclick=e=>{e.stopPropagation();onLink()};c.querySelector('.hch').appendChild(b)}
 return c}
function heroRow(icon,title,side,onclick,sub){
 const r=el('<div class=hrow><span class=hri></span><span class=hrt></span><span class=hrs></span></div>');
 r.querySelector('.hri').textContent=icon;
 const t=r.querySelector('.hrt');t.textContent=title;t.title=title;
 if(sub){const x=el('<span class=hrsub></span>');x.textContent=sub;t.appendChild(x)}
 r.querySelector('.hrs').textContent=side||'';
 if(onclick)r.onclick=onclick;else r.style.cursor='default';
 return r}
function openChatFromHome(id){if(!id)return;showPane('log');openSession(id)}
function drawHero(fromData){
 const h=$('#hero');if(!h)return;
 const empty=!wrap.querySelector('.msg,.sysline,.approve');
 if(!empty||$('#log').style.display==='none'){h.style.display='none';return}
 if(!fromData)loadHome();
 // the mutation observer calls this on every change to the chat; skip redrawing an
 // unchanged page (it would reset hover and flicker)
 const key=[sid,HOME_AT,(SESSIONS||[]).length,(SESSIONS||[])[0]&&SESSIONS[0].mtime,MODELS.current,
  isClaudeChat(),isCodexChat(),[...(RUNNING||[])].join()].join('|');
 if(h._key===key&&h.style.display!=='none')return;
 const arriving=h.style.display==='none'||(h._key||'').split('|')[0]!==sid;
 h._key=key;
 // six bands rather than the usual three: "Good afternoon" at 17:50 and "Good evening"
 // at 18:00 is a cliff, and 5am and midnight are not the same kind of late
 const hr=new Date().getHours();
 const when=hr<5?'Still up':hr<9?'Early start':hr<12?'Good morning':hr<14?'Good afternoon':
   hr<18?'Good afternoon':hr<23?'Good evening':'Late one';
 const engine=isClaudeChat()?'Claude Code':isCodexChat()?'Codex':'Orbit';
 h.innerHTML='';
 h.appendChild(el(`<div class=heromark aria-hidden=true><i></i></div>`));
 h.appendChild(el(`<div class=herot>${esc(when)} — what's next?</div>`));
 const sub=el('<div class=herosub></div>');
 sub.appendChild(document.createTextNode(engine+' · '));
 const ms=el('<span class=hsm title="change the model"></span>');ms.textContent=modelLabel();
 ms.onclick=()=>{const b=$('#hmodel')&&$('#hpick').style.display!=='none'?$('#hmodel'):$('#modelsel');
  if(b){b.focus();try{b.showPicker()}catch(e){}}};
 sub.appendChild(ms);h.appendChild(sub);
 const tips=el('<div class=herotips></div>');
 [['/','commands'],['@','mention a file'],['!','run a shell command'],['#','save to memory'],
  ['⇧Tab','permission mode'],['⌘P','find a chat'],['?','shortcuts']].forEach(([k,t])=>{
  const c=el('<span class=herotip><b></b> </span>');c.querySelector('b').textContent=k;
  c.appendChild(document.createTextNode(t));
  c.onclick=()=>{if(k==='?'){showShortcuts();return}if(k==='⇧Tab'){cycleMode();return}
   if(k==='⌘P'){openPal();return}
   q.value=k==='#'?'# ':k;q.focus();q.dispatchEvent(new Event('input'))};
  tips.appendChild(c)});
 h.appendChild(tips);
 // What this chat could be asked, for the case the recent-chats list does not cover:
 // the first one. They fill the box and stop there — nothing is sent for you.
 const SUGG={
  'Claude Code':['Explain what this repository does and how it is laid out',
                 'Find the bug behind this failing test and fix it',
                 'Review my uncommitted changes',
                 'Add tests for the file I changed last'],
  'Codex':['Explain what this repository does and how it is laid out',
           'Refactor this file and keep every test passing',
           'Write the commit message for what is staged'],
  'Orbit':['Search my knowledge base and summarise what it says about…',
           'Read this paper and tell me whether its method fits my data',
           'Plot this CSV and say what stands out',
           'Check whether this citation supports the claim']};
 const sg=el('<div class=sugg></div>');
 (SUGG[engine]||SUGG.Orbit).forEach(t=>{
  const b=el('<button class=suggp></button>');b.textContent=t;
  b.onclick=()=>{q.value=t;q.focus();fitQ();q.dispatchEvent(new Event('input'))};
  sg.appendChild(b)});
 h.appendChild(sg);
 const d=HOME;
 const tasks=(d&&d.tasks)||[];
 // ---- things that want you now
 const alerts=el('<div class=heroalerts></div>');
 const alert=(icon,text,side,fn,bad)=>{const a=el(`<div class="halert${bad?' bad':''}"><span class=hai></span><span class=hat></span><span class=hago></span></div>`);
  a.querySelector('.hai').textContent=icon;a.querySelector('.hat').textContent=text;a.querySelector('.hago').textContent=side||'';a.onclick=fn;alerts.appendChild(a)};
 const waiting=tasks.filter(t=>t.kind==='answer'&&t.status==='waiting for you');
 waiting.forEach(t=>alert('⏸',`“${t.title}” is waiting for your answer`,'open →',()=>openChatFromHome(t.sid)));
 ((d&&d.problems)||[]).forEach(pb=>alert('⚠',pb.name+': '+pb.detail,pb.fix?'fix →':'',()=>showHealth(),true));
 ((d&&d.failed)||[]).forEach(f=>alert('✕',`Scheduled task “${f.title}” failed${f.result?': '+f.result:''}`,f.at?relTime(f.at):'',()=>f.sid?openChatFromHome(f.sid):showPane('tasks'),true));
 ((d&&d.allowances)||[]).forEach(a=>{
  const lim=(a.windows||[]).find(w=>w.limited)||(a.exhausted&&{name:'',resets:a.exhausted.until*1000});
  const low=!lim&&(a.windows||[]).find(w=>w.left<=15);
  if(lim)alert('⛔',`${a.label}${a.account?' ('+a.account+')':''}: limit reached`+(lim.resets?' — back '+inTime((typeof lim.resets==='number'?lim.resets:Date.parse(lim.resets))/1000):''),'',()=>{},true);
  else if(low)alert('◔',`${a.label}${a.account?' ('+a.account+')':''}: only ${low.left}% of the ${low.name} allowance left`,low.resets?'resets '+inTime(Date.parse(low.resets)/1000):'',()=>{})});
 if(alerts.children.length)h.appendChild(alerts);
 const grid=el('<div class=herogrid></div>');
 const skel=c=>{for(let i=0;i<3;i++){const x=el('<div class=hskel></div>');x.style.width=(90-i*18)+'%';c.appendChild(x)}};
 // ---- running now
 {const live=tasks.filter(t=>t.kind==='answer'||(t.kind==='shell'&&t.can_stop)||(t.kind==='background'&&t.running));
  const queued=tasks.filter(t=>t.kind==='queued'&&!/^at /.test(t.status||''));
  const c=heroCard('Running now',tasks.length?'all tasks':'',showTasks);
  const dot=el(`<span class="hdot${live.length?' live':''}"></span>`);c.querySelector('.hch').prepend(dot);
  const list=el('<div class=hlist></div>');
  if(!d)skel(list);
  else if(!live.length&&!queued.length)list.appendChild(el('<div class=hempty>Nothing running — Orbit is idle.</div>'));
  live.slice(0,4).forEach(t=>{
   const el_=heroRow(t.kind==='shell'?'$':t.kind==='background'?'\u29d7':t.status==='waiting for you'?'⏸':'⏺',t.title,
    t.since?fmtSecs(d.now-t.since):'',t.kind==='background'?()=>showTaskOutput(t):t.sid?()=>openChatFromHome(t.sid):null,
    t.kind==='background'?t.status:t.kind==='answer'&&t.status&&t.status!=='answering'?t.status:'');
   if(t.status==='waiting for you')el_.classList.add('wait');
   if(t.can_stop){const x=el('<button class=hrx>stop</button>');x.title=t.kind==='answer'?'stop this answer':'stop this command';
    x.onclick=async e=>{e.stopPropagation();x.disabled=true;
     const ok=t.kind==='answer'?await apiPost('/api/cancel',{sid:t.sid},'stopping'):await apiPost('/api/tasks/stop',{kind:t.kind,id:t.id},'stopping');
     x.textContent=ok?'stopped':'stop';refreshRunning();setTimeout(()=>loadHome(true),800)};
    el_.appendChild(x)}
   list.appendChild(el_)});
  if(queued.length){const by={};queued.forEach(t=>{by[t.sid]=by[t.sid]||{t,n:0};by[t.sid].n++});
   Object.values(by).slice(0,3).forEach(({t,n})=>list.appendChild(heroRow('↳',t.title,n+' queued',()=>openChatFromHome(t.sid),t.text?'next: '+t.text:'')))}
  c.appendChild(list);grid.appendChild(c)}
 // ---- coming up
 {const up=(d&&d.upcoming)||[];
  const c=heroCard('Coming up','scheduled',()=>showPane('tasks'));
  const list=el('<div class=hlist></div>');
  if(!d)skel(list);
  else if(!up.length){const x=el('<div class=hempty>Nothing scheduled. <a>Schedule a task</a> or press ⏱ beside Send.</div>');
   x.querySelector('a').onclick=()=>showPane('tasks');list.appendChild(x)}
  up.slice(0,4).forEach(u=>{
   const icon=u.kind==='limit_resume'?'↻':u.kind==='message'?'✉':u.repeat?'⟳':'⏱';
   const title=u.kind==='limit_resume'?'Resume “'+u.title.replace(/^.*?:\s*/,'')+'” after the limit':u.title;
   list.appendChild(heroRow(icon,title,u.missed?'missed':inTime(u.at),
    u.kind==='message'&&u.sid?()=>openChatFromHome(u.sid):()=>showPane('tasks'),u.text||''))});
  c.appendChild(list);grid.appendChild(c)}
 // ---- shared projects (only when there are any)
 if(typeof SH!=='undefined'&&SH.on&&(SH.projects||[]).length){
  const c=heroCard('Shared projects','settings',()=>{try{openSettings('collab')}catch(x){openSettings()}});const list=el('<div class=hlist></div>');
  SH.projects.slice(0,4).forEach(p=>list.appendChild(heroRow('▣',p.name,`${p.members} ${p.members===1?'person':'people'}`,()=>openShared(p.id),
   (SH.chats[p.id]||[]).slice(0,4).map(x=>'#'+x.name).join('  ')+(p.frozen?'  · frozen':''))));
  c.appendChild(list);grid.appendChild(c)}
 // ---- activity
 {const c=heroCard('Activity','details',()=>showStats(7));
  if(!d){skel(c)}
  else{
   const w=d.week,lw=d.last_week;
   const delta=lw.turns?Math.round((w.turns-lw.turns)/lw.turns*100):null;
   const nums=el(`<div class=hnums title="usage by model">
     <div class=hnum><b>${(+d.today.turns).toLocaleString()}</b><small>answers today</small></div>
     <div class=hnum><b>${(+w.turns).toLocaleString()}${delta===null?'':`<span class="hdelta ${delta>=0?'up':'down'}">${delta>=0?'▲':'▼'}${Math.abs(delta)}%</span>`}</b><small>this week</small></div>
     <div class=hnum><b>${fmtTok(w.tokens)}</b><small>tokens · 7 days</small></div>
     <div class=hnum><b>${fmtSecs(w.seconds)}</b><small>model time</small></div></div>`);
   nums.onclick=()=>showStats(7);c.appendChild(nums);
   const max=Math.max(1,...d.days.map(x=>x.turns+x.tool_runs/10));
   const bars=el('<div class=hbars></div>');
   d.days.forEach((x,i)=>{const b=el('<div class=hb></div>');const v=x.turns+x.tool_runs/10;
    b.style.height=Math.max(3,v/max*100)+'%';
    if(i===d.days.length-1)b.classList.add('today');else if(!v)b.classList.add('zero');
    const dt=new Date(x.day+'T12:00');
    b.title=`${dt.toLocaleDateString([], {weekday:'short',month:'short',day:'numeric'})}: ${x.turns} answers · ${fmtTok(x.tokens)} tokens · ${x.tool_runs} tool calls`;
    bars.appendChild(b)});
   bars.onclick=()=>showStats(14);c.appendChild(bars);
   const ax=el('<div class=hbaxis><span>2 weeks ago</span><span>today</span></div>');c.appendChild(ax);
   if(d.streak>1){const s=el('<div class=hstreak></div>');s.textContent=`${d.streak}-day streak`;c.appendChild(s)}}
  grid.appendChild(c)}
 // ---- allowances (or, with none to track, what this week went to)
 {const al=((d&&d.allowances)||[]).filter(a=>(a.windows||[]).length||a.exhausted);
  const c=heroCard(al.length?'Allowance left':'This week',al.length?'models':'',()=>openSettings&&openSettings('models'));
  if(!d)skel(c);
  al.slice(0,3).forEach(a=>{
   const box=el('<div class=hacct><div class=han><b style="font-weight:500"></b><span></span></div></div>');
   box.querySelector('b').textContent=a.label+(a.account&&a.account!=='Main'?' · '+a.account:'');
   if(a.spent&&a.spent.month)box.querySelector('.han span').textContent='~$'+(+a.spent.month).toFixed(2)+' this month';
   (a.windows||[]).forEach(wn=>{
    const m=el('<div class=hmeter><span></span><div class=hmt><div class=hmf></div></div><span class=hmv></span></div>');
    m.children[0].textContent=wn.name;
    const f=m.querySelector('.hmf');f.style.width=wn.left+'%';
    if(wn.left<=15||wn.limited)f.classList.add('low');else if(wn.left<=40)f.classList.add('mid');
    m.querySelector('.hmv').textContent=wn.limited?'0%':wn.left+'%';
    const rs=wn.resets?(typeof wn.resets==='number'?wn.resets:Date.parse(wn.resets)/1000):0;
    m.title=`${wn.left}% of the ${wn.name} allowance left${rs?' · resets '+new Date(rs*1000).toLocaleString([], {weekday:'short',month:'short',day:'numeric',hour:'numeric',minute:'2-digit'}):''}`;
    box.appendChild(m)});
   c.appendChild(box)});
  if(d){
   const models=(d.models||[]);
   if(models.length){
    if(al.length)c.appendChild(el('<div class=hch style="margin:10px 0 4px">Most used · 7 days</div>'));
    const mx=Math.max(...models.map(m=>m.turns),1);
    const mm=el('<div class=hmodels></div>');
    models.slice(0,al.length?3:4).forEach(m=>{const r=el('<div class=hmrow><span></span><i></i><em></em></div>');
     r.children[0].textContent=m.model.replace(/ · your subscription$/,'');r.children[0].title=m.model;
     r.querySelector('i').style.width=Math.max(6,m.turns/mx*100)+'%';r.querySelector('em').textContent=m.turns;mm.appendChild(r)});
    c.appendChild(mm)}
   if(!al.length&&(d.tools||[]).length){const t=el('<div class=htools></div>');
    d.tools.forEach(x=>{const s_=el('<span></span>');s_.textContent=toolName(x.tool)+' ×'+x.calls;t.appendChild(s_)});c.appendChild(t)}
   if(!models.length&&!al.length)c.appendChild(el('<div class=hempty>Nothing used this week yet.</div>'))}
  grid.appendChild(c)}
 // ---- chats to go back to: pinned first, then the most recent
 {const pool=(SESSIONS||[]).filter(x=>x.id!==sid&&!x.archived);
  const pinned=pool.filter(x=>x.pinned).slice(0,3);
  const recent=pinned.concat(pool.filter(x=>!x.pinned).slice(0,6-pinned.length));
  if(recent.length){
   const c=heroCard('Pick up where you left off','all chats',()=>openPal(),'wide herorecent');
   const list=el('<div class=hlist></div>');
   recent.forEach((x,i)=>{
    const r=heroRow(x.pinned?'★':RUNNING&&RUNNING.has&&RUNNING.has(x.id)?'⏺':'›',x.title||'untitled',x.mtime?relTime(x.mtime):'',()=>openSession(x.id));
    const ml=x.model?modelLabel(x.model):'';
    if(ml&&ml!=='orbit'){const m=el('<span class=hrm></span>');m.textContent=ml.replace(/ · .*$/,'');m.title=ml;r.insertBefore(m,r.querySelector('.hrs'))}
    if(x.queued){const qd=el('<span class=hrm></span>');qd.textContent=x.queued+' queued';r.insertBefore(qd,r.querySelector('.hrs'))}
    list.appendChild(r)});
   const n=pool.length+(pool.some(x=>x.id===sid)?0:1);
   const pj=Object.keys(PROJECTS.projects||PROJECTS||{}).length;
   const foot=el('<div class=hfoot></div>');
   foot.textContent=[n+' chat'+(n===1?'':'s'),pj?pj+' project'+(pj===1?'':'s'):'',
    d&&d.week.tool_runs?d.week.tool_runs+' tool calls this week':''].filter(Boolean).join(' · ');
   c.appendChild(list);c.appendChild(foot);grid.appendChild(c)}}
 h.appendChild(grid);
 h.style.display='';
 // opening an empty chat should start at the greeting, not where the last chat was scrolled to
 if(arriving)$('#log').scrollTop=0}
function relTime(t){const s=Date.now()/1000-t;
 if(s<90)return 'just now';if(s<3600)return Math.round(s/60)+'m ago';
 if(s<86400)return Math.round(s/3600)+'h ago';return Math.round(s/86400)+'d ago'}
new MutationObserver(()=>drawHero()).observe(wrap,{childList:true});
setTimeout(drawHero,1200);

/* ---------------- the mode line under the box ----------------
   Claude Code keeps the permission mode in view under the prompt ("⏵⏵ accept edits on")
   and Shift+Tab cycles it. Same here, for every kind of chat. */
const MODE_GLYPH={default:'',acceptEdits:'⏵⏵ accept edits on',plan:'⏸ plan mode on',
 auto:'⏵⏵ auto mode on',dontAsk:"⏵⏵ don't ask on",bypassPermissions:'⏵⏵ bypass permissions on'};
function currentMode(){
 const sel=$('#cqbar select');
 if((isClaudeChat()||isCodexChat())&&sel&&$('#cqbar').style.display!=='none')return sel.value;
 return (typeof PLAN_MODE!=='undefined'&&PLAN_MODE)?'plan':'default'}
function drawModeHint(){
 const h=$('#modehint');if(!h)return;
 const m=currentMode(),txt=MODE_GLYPH[m]||'';
 h.textContent=txt?txt+' (shift+tab to cycle)':'';
 h.className=txt?'mode-'+m:''}
async function cycleMode(){
 const sel=$('#cqbar select');
 if((isClaudeChat()||isCodexChat())&&sel&&$('#cqbar').style.display!=='none'){
  const order=isCodexChat()?['auto','acceptEdits','plan','default']:['default','acceptEdits','plan','auto'];
  const have=[...sel.options].map(o=>o.value);
  const cyc=order.filter(x=>have.includes(x));
  sel.value=cyc[(cyc.indexOf(sel.value)+1)%cyc.length];
  await sel.onchange({target:sel});drawModeHint();return}
 if(!sid){toast('start a chat first');return}
 await setPlanMode(!PLAN_MODE);drawModeHint()}
$('#qhelp').onclick=()=>showShortcuts();

/* ---------------- ! shell mode and # memory ---------------- */
// the box shows which mode a leading ! or # puts it in
function syncComposerMode(){
 const v=q.value;
 const mode=/^!/.test(v)?'bang':(/^#\s/.test(v)&&!v.includes('\n'))?'mem':'';
 q.classList.toggle('bangmode',mode==='bang');q.classList.toggle('memmode',mode==='mem');
 const kh=$('#keyhint');if(!kh)return;
 if(mode==='bang'){kh.dataset.was=kh.dataset.was||kh.textContent;
  kh.textContent='! shell mode — runs in this chat’s folder; the output joins the conversation'}
 else if(mode==='mem'){kh.dataset.was=kh.dataset.was||kh.textContent;
  kh.textContent='# memory — Enter saves this line to memory'}
 else if(kh.dataset.was){kh.textContent=kh.dataset.was;delete kh.dataset.was}}
q.addEventListener('input',syncComposerMode);
function bangNode(b,ts){
 const m=el('<div class="msg u bang"><div class=who>you ran<span class=acts></span></div></div>');
 const box=el('<div class=bangbox><div class=bangcmd></div><pre class=bangout></pre>'+
  '<div class=bangmeta></div></div>');
 box.querySelector('.bangcmd').textContent='! '+b.cmd;
 box.querySelector('.bangout').textContent=(b.out||'').trimEnd()||'(no output)';
 box.querySelector('.bangmeta').textContent=(b.rc===0?'exit 0':'exit '+b.rc)+
  (b.secs!=null?' · '+fmtSecs(b.secs):'')+(b.host?' · on '+b.host:'')+
  ' · the model sees this with your next message';
 if(b.rc!==0)box.classList.add('bad');
 const c=el('<button>copy</button>');c.onclick=()=>copy('$ '+b.cmd+'\n'+(b.out||''));
 m.querySelector('.acts').appendChild(c);
 m.appendChild(box);stamp(m,ts);wrap.appendChild(m);bottom();return m}
async function runBang(cmd,confirmed){
 if(!sid){toast('start a chat first');return}
 const hold=bangNode({cmd,out:'running…',rc:0},Date.now()/1000);
 hold.querySelector('.bangmeta').textContent='running…';
 const d=await apiPost('/api/bang',{sid,command:cmd,confirmed:!!confirmed},'running that');
 hold.remove();
 if(!d)return;
 if(d.confirm){
  if(confirm('Run this?\n\n'+cmd+'\n\n'+d.confirm))return runBang(cmd,true);
  q.value='! '+cmd;syncComposerMode();return}
 bangNode({cmd,out:d.output,rc:d.rc,secs:d.secs,host:d.host},Date.now()/1000);
 histPush('! '+cmd)}
async function rememberNote(text){
 const name=text.toLowerCase().split(/\s+/).slice(0,5).join('-').replace(/[^a-z0-9-]/g,'')||'note';
 const d=await apiPost('/api/memory/save',{name,text},'saving to memory');
 if(d)toast('saved to memory: '+name)}

/* ---------------- verbose, todos, rewind, history search ----------------
   The four things Claude Code gives you over a transcript: see everything (ctrl+o),
   see the todo list (ctrl+t), go back to an earlier point (esc esc), and find
   something you typed before (ctrl+r). */
function setVerbose(v){
 VERBOSE=!!v;PREF.set('verbose',VERBOSE?'1':'0');log.classList.toggle('verbose',VERBOSE);
 document.querySelectorAll('#wrap details.tool,#wrap details.tgroup').forEach(d=>{d.open=VERBOSE});
 toast(VERBOSE?'showing every tool call in full (ctrl+o)':'tool calls folded again (ctrl+o)')}
function togglePlanDock(){
 const d=$('#plandock');if(!d)return;
 const hide=d.dataset.hidden!=='1';
 d.dataset.hidden=hide?'1':'0';PREF.set('plandock',hide?'0':'1');
 drawPlanDock();
 if(hide)toast('todo list hidden (ctrl+t)')}
// the messages you can go back to, newest last, with what each one would undo
function rewindPoints(){
 const out=[];
 [...wrap.querySelectorAll('.msg.u')].forEach(node=>{
  const i=userIndex(node);if(i<0)return;
  let files=0;
  for(let n=node.nextElementSibling;n;n=n.nextElementSibling)
   if(n.classList&&n.classList.contains('a')){
    const b=n.querySelector('.undobtn');if(b&&!b.disabled)files++}
  out.push({index:i,text:(node.querySelector('.bub')||{}).textContent||'',files,node})});
 return out}
function openRewind(){
 const pts=rewindPoints();
 if(!sid||!pts.length){toast('nothing to rewind to yet');return}
 openSheet('Rewind',body=>{
  body.appendChild(el('<div class=sheetnote>Put the chat back to just before one of your '+
   'messages. Files an answer changed after that point can go back too.</div>'));
  pts.slice().reverse().forEach(pt=>{
   const r=el('<div class=rewrow></div>');
   const t=el('<div class=rewtext></div>');
   t.textContent=pt.text.replace(/\s+/g,' ').trim().slice(0,110)||'(no text)';
   r.appendChild(t);
   const acts=el('<div class=rewacts></div>');
   const one=el('<button class=ghost>chat only</button>');
   one.onclick=()=>doRewind(pt.index,false);
   acts.appendChild(one);
   if(pt.files){const both=el('<button class=ghost>chat + files…</button>');
    both.title='also put back the files those answers changed';
    // "chat + files" after a long run is the scariest button in the app. Say what it
    // would touch, and which files it would refuse to touch, before it touches anything.
    both.onclick=async()=>{
     const look=await apiPost('/api/rewind/preview',{sid,index:pt.index},'checking');
     if(!look)return;
     const safe=(look.safe||[]).length, unsafe=look.unsafe||[], gone=(look.gone||[]).length;
     let msg=`Put back ${safe} file${safe===1?'':'s'} and drop ${look.messages} message`
            +`${look.messages===1?'':'s'}.`;
     if(gone)msg+=`\n${gone} file(s) have no snapshot (they live outside the workspace) and stay as they are.`;
     if(unsafe.length){
      msg+='\n\nThese have changed since the answer wrote them, so your own edits would be lost:\n'
         +unsafe.slice(0,8).map(x=>'  • '+x.path).join('\n')
         +(unsafe.length>8?`\n  …and ${unsafe.length-8} more`:'')
         +'\n\nOK puts everything back anyway. Cancel to leave the files alone.';
      if(!confirm(msg))return;
      return doRewind(pt.index,true,true)}
     if(!confirm(msg))return;
     doRewind(pt.index,true)};
    acts.appendChild(both)}
   r.appendChild(acts);body.appendChild(r)})})}
async function doRewind(index,files,force){
 const d=await apiPost('/api/rewind',{sid,index,files,force:!!force},'rewinding');
 if(!d)return;
 closeModal();await openSession(sid);
 // "undone" is every line it had to say, refusals included: count what was restored
 const put=(d.restored||[]).length, no=(d.refused||[]).length;
 let line='rewound '+d.dropped+' message'+(d.dropped===1?'':'s');
 if(files)line+=' · '+put+' file'+(put===1?'':'s')+' put back'
   +(no?' · '+no+' left alone (changed since)':'');
 toast(line);
 if(files&&no&&!put)sysline((d.undone||[]).join('; '))}
// ctrl+r: what you have typed before, newest first
function openPromptSearch(){
 const hist=(()=>{try{return JSON.parse(PREF.get('hist','[]'))}catch(e){return []}})();
 if(!hist.length){toast('no earlier messages yet');return}
 openSheet('Earlier messages',body=>{
  const f=el('<input class=sfilter placeholder="filter — Enter to use the first">');
  body.appendChild(f);
  const list=el('<div></div>');body.appendChild(list);
  const draw=()=>{const term=f.value.toLowerCase();list.innerHTML='';
   hist.slice().reverse().filter(t=>!term||t.toLowerCase().includes(term)).slice(0,40)
    .forEach(t=>{const r=el('<div class=histrow></div>');
     r.textContent=t.replace(/\s+/g,' ').slice(0,160);
     r.onclick=()=>{q.value=t;closeModal();q.focus();q.dispatchEvent(new Event('input'))};
     list.appendChild(r)})};
  f.oninput=draw;
  f.onkeydown=e=>{if(e.key==='Enter'){const first=list.firstElementChild;if(first)first.click()}};
  draw();setTimeout(()=>f.focus(),30)})}

/* ---------------- fork ---------------- */
// index among the saved chat's user messages; older ones may not be drawn
function userIndex(node){
 const us=[...wrap.querySelectorAll('.msg.u:not(.pending)')],i=us.indexOf(node);if(i<0)return -1;
 for(let j=i;j>=0;j--)if(us[j].dataset.ui!=null)return +us[j].dataset.ui+(i-j);
 return i}
async function forkAt(node,text){
 if(!sid)return;
 const idx=userIndex(node);if(idx<0)return;
 const d=await apiPost('/api/branch',{id:sid,index:idx},'fork');
 if(!d||!d.sid)return;
 showPane('log');await openSession(d.sid);
 q.value=text;q.focus();fitQ();
 saveDraft(d.sid);toast('forked — edit it and send')}

/* ---------------- prompt history, drafts, pastes ---------------- */
// '/name words': $ARGUMENTS is the words, $1.. (or ${1}) each one, quotes
// grouping -- only for as many words as given, so '$5 cap' stays; same as the server
function expandPrompt(body,rest){body=String(body||'');rest=rest||'';
 const pos=(rest.match(/"[^"]*"|\S+/g)||[]).map(x=>x.replace(/^"|"$/g,''));
 let used=false;
 if(body.includes('$ARGUMENTS')){body=body.split('$ARGUMENTS').join(rest);used=true}
 body=body.replace(/\$\{(\d)\}|\$(\d)(?!\d|[.,]\d)/g,(m,a,b)=>{const n=+(a||b);
  if(n>0&&n<=pos.length){used=true;return pos[n-1]}return m});
 if(rest&&!used)body=body.replace(/\s+$/,'')+'\n\n'+rest;
 return body}
function histLoad(){try{return JSON.parse(PREF.get('hist','[]'))||[]}catch(e){return []}}
function histPush(t){if(!t||t.length>20000||tempMode)return;const h=histLoad();
 if(h[h.length-1]!==t)h.push(t);PREF.set('hist',JSON.stringify(h.slice(-50)));histPos=-1}
function histWalk(dir){
 const h=histLoad();if(!h.length)return false;
 if(!(q.value===''||(histPos>=0&&q.value===h[histPos])))return false;
 // a recalled prompt of several lines: the arrows move through its lines first
 if(dir<0&&q.value.lastIndexOf('\n',q.selectionStart-1)!==-1)return false;
 if(dir>0&&q.value.indexOf('\n',q.selectionEnd)!==-1)return false;
 if(dir<0)histPos=histPos<0?h.length-1:Math.max(0,histPos-1);
 else{if(histPos<0)return false;
  if(++histPos>=h.length){histPos=-1;q.value='';return true}}
 q.value=h[histPos];fitQ();
 q.selectionStart=q.selectionEnd=q.value.length;return true}
const PASTE_RE=/\[Pasted #(\d+) · ~\d+ lines\]/g;
function pasteToken(n,lines){return `[Pasted #${n} · ~${lines} lines]`}
function expandPastes(t){return t.replace(PASTE_RE,(m,n)=>PASTES[n]!=null?PASTES[n]:m)}
function saveDraft(s){if(!s||tempMode)return;try{const k='orbit_draft_'+s,t=q.value;
 if(!t.trim()){localStorage.removeItem(k);return}
 const p={};t.replace(PASTE_RE,(m,n)=>{if(PASTES[n]!=null)p[n]=PASTES[n]});
 localStorage.setItem(k,JSON.stringify({t,p}))}catch(e){}}
function clearDraft(s){try{localStorage.removeItem('orbit_draft_'+s)}catch(e){}}
function loadDraft(s){let d=null;
 try{d=JSON.parse(localStorage.getItem('orbit_draft_'+s)||'null')}catch(e){}
 document.querySelectorAll('#chips [data-paste]').forEach(x=>x.remove());
 q.value=(d&&d.t)||'';histPos=-1;
 if(d&&d.p)Object.entries(d.p).forEach(([n,t])=>{PASTES[n]=t;pasteN=Math.max(pasteN,+n);pasteChip(n,t)});
 fitQ()}
function pasteChip(n,t){
 const lines=t.split('\n').length;
 const c=el(`<div class=chip data-paste="${n}"><b>Pasted #${n}</b><span>~${lines} lines · ${
   t.length.toLocaleString()} chars</span><span class=x title="remove">&times;</span></div>`);
 c.querySelector('.x').onclick=()=>{q.value=q.value.split(pasteToken(n,lines)).join('');
  delete PASTES[n];c.remove();saveDraft(sid)};
 $('#chips').appendChild(c)}
function pasteBubble(b,raw){
 const re=new RegExp(PASTE_RE.source,'g');let last=0,mm;
 while((mm=re.exec(raw))){const body=PASTES[mm[1]];if(body==null)continue;
  b.appendChild(document.createTextNode(raw.slice(last,mm.index)));
  const d=el('<details class=paste><summary></summary><pre></pre></details>');
  d.querySelector('summary').textContent=`pasted text · ~${body.split('\n').length} lines`;
  d.querySelector('pre').textContent=body;b.appendChild(d);last=re.lastIndex}
 b.appendChild(document.createTextNode(raw.slice(last)))}
q.addEventListener('paste',e=>{
 const cd=e.clipboardData;if(!cd||(cd.files&&cd.files.length))return;
 const t=cd.getData('text/plain')||'',lines=t.split('\n').length;
 if(lines<15&&t.length<1500)return;
 e.preventDefault();
 const n=++pasteN,tok=pasteToken(n,lines);PASTES[n]=t;
 const s=q.selectionStart,en=q.selectionEnd;
 q.value=q.value.slice(0,s)+tok+q.value.slice(en);q.selectionStart=q.selectionEnd=s+tok.length;
 pasteChip(n,t);q.dispatchEvent(new Event('input'));
 clearTimeout(draftT);saveDraft(sid)});      // now, not debounced: a chat reload must not lose it

/* ---------------- plan dock ---------------- */
function parsePlan(out){
 const steps=String(out||'').split('\n').filter(l=>/^\d+\. \[/.test(l))
  .map(l=>({done:/^\d+\. \[x\]/.test(l),active:/^\d+\. \[>\]/.test(l),t:l.replace(/^\d+\. \[.\]\s*/,'')}));
 // no step marked as in hand: it is the first one not done, as in Claude Code's list
 if(steps.length&&!steps.some(x=>x.active)){const f=steps.find(x=>!x.done);if(f)f.active=true}
 return steps}
// Claude Code's todo marks: ☒ done, ◼ in hand, ☐ still to do
function todoMark(x){return x.done?'\u2612':x.active?'\u25fc':'\u2610'}
// During a long run the three questions are "what is it doing", "what else is still
// running" and "what has it touched" — which lived in a dock, a chip and a modal. One
// dock, one section each, every section showing its digest while collapsed.
let GITSTATE=null,GITSID=null,GITAT=0;
async function pollGit(force){
 // per chat: the answer is about the folder THIS chat works in, so it is thrown away
 // when the chat changes rather than shown under the next one
 if(!sid){GITSTATE=null;GITSID=null;return}
 if(sid!==GITSID){GITSTATE=null;GITSID=sid;GITAT=0;drawPlanDock()}
 if(!force&&Date.now()-GITAT<15000)return;
 const forSid=sid;GITAT=Date.now();
 try{const g=await (await fetch('/api/git?sid='+encodeURIComponent(forSid))).json();
  if(forSid!==sid)return;                       // you moved on while it answered
  GITSTATE=g;GITSID=forSid}catch(e){}
 drawPlanDock()}

// How tall each section may get before it scrolls inside itself. Six two-line todos is
// about 320px; beyond that the dock would push the message box off the screen. The cap
// goes on the body, never the section, so the header stays where it is.
const DOCK_CAP={plan:320,work:200,git:160};
// who each chat talks to (chat_create / chat_send), kept fresh while any of them work
const LINKS={};
async function loadLinks(s){
 if(!s)return;
 try{const d=await (await fetch('/api/links?sid='+encodeURIComponent(s))).json();
  const was=JSON.stringify(LINKS[s]||null);LINKS[s]={links:d.links||[],talking_to:d.talking_to||null};
  if('goal' in d&&JSON.stringify(GOALS[s]||null)!==JSON.stringify(d.goal||null)){GOALS[s]=d.goal||null;if(s===sid)drawGoal()}
  if(s===sid&&was!==JSON.stringify(LINKS[s]))drawPlanDock()}catch(e){}}
setInterval(()=>{if(document.hidden||!sid)return;const l=LINKS[sid];
 // while it, or any chat it talks to, is at work -- or it has a goal going
 if(RUNNING.has(sid)||(l&&(l.talking_to||l.links.some(x=>x.state)))||(GOALS[sid]&&GOALS[sid].status==='active'))loadLinks(sid)},4000);
function dockSection(d,key,title,digest,fill){
 const openKey='_sec_'+key;
 if(d[openKey]===undefined)d[openKey]=(key==='plan');
 const h=el('<div class=pdsec></div>');
 h.appendChild(el(`<b>${title}</b>`));
 const dg=document.createElement('span');dg.className='pddig';dg.textContent=digest;h.appendChild(dg);
 h.appendChild(el(`<span class=pdcar>${d[openKey]?'▾':'▸'}</span>`));
 h.onclick=()=>{d[openKey]=!d[openKey];drawPlanDock()};
 d.appendChild(h);
 if(d[openKey]){
  const body=el('<div class=pdl></div>');
  if(!(key in DOCK_CAP))console.warn('dock section with no height cap:',key);
  body.style.maxHeight=(DOCK_CAP[key]||200)+'px';
  fill(body);d.appendChild(body)}}

function drawPlanDock(){
 // The dock is decoration, but syncBusy() calls it on the path that opens a chat and
 // the path that sends a message: a throw in here used to stop both, and the composer
 // stuck on "Queue" until a reload. It may fail; it may not take anything with it.
 try{drawPlanDockInner()}catch(e){console.warn('plan dock:',e)}}

function drawPlanDockInner(){
 const d=$('#plandock');if(!d)return;
 const steps=PLANS[sid]||[],open=steps.filter(x=>!x.done);
 const running=[...RUNNING].length;
 // QUEUE is {items,paused,running} for ONE chat, and BGT is keyed by chat: neither
 // has a .length, so both counts used to be a silent zero
 const qitems=(QUEUE_SID===sid&&QUEUE&&QUEUE.items)?QUEUE.items:[];
 const bgjobs=Object.values((BGT&&BGT[sid])||{})
   .filter(x=>/^(running|pending)/.test(x.status||'running'));
 const queued=qitems.length, bg=bgjobs.length;
 const git=GITSTATE&&GITSID===sid&&GITSTATE.repo?GITSTATE:null;
 const lk=LINKS[sid]||{links:[],talking_to:null};
 const anything=open.length||running||queued||bg||(git&&git.dirty)||lk.links.length||lk.talking_to;
 d.innerHTML='';
 if(!anything||d.dataset.hidden==='1'){d.style.display='none';return}
 d.style.display='';

 if(open.length){
  const cur=open.find(x=>x.active)||open[0];
  dockSection(d,'plan',`todos ${steps.length-open.length}/${steps.length}`,'\u25fc '+cur.t,body=>{
   steps.forEach(x=>{
    const r=el(`<div class="st${x.done?' done':''}${x.active&&!x.done?' active':''}"><span class=bx>${todoMark(x)}</span></div>`);
    const sp=document.createElement('span');sp.textContent=x.t;r.appendChild(sp);body.appendChild(r)})})}

 // the chats this one talks to: which, what each is doing, and whom it waits on now
 if(lk.links.length||lk.talking_to){
  const busy=lk.links.filter(l=>l.state).length;
  const digest=lk.talking_to?'⇄ waiting for “'+(lk.talking_to.title||'')+'”'
   :lk.links.slice(0,3).map(l=>'“'+(l.title||'')+'”').join(', ')+(busy?' · '+busy+' busy':'');
  dockSection(d,'chats',`chats ${lk.links.length}`,digest,body=>{
   lk.links.forEach(l=>{
    const r=el('<div class=st style="gap:6px"><span class=lrole></span><a class=chatlink href="#"></a><span class=lstate></span></div>');
    r.querySelector('.lrole').textContent={started:'started',messaged:'asked','works for':'works for'}[l.role]||l.role;
    const a=r.querySelector('a');a.dataset.chat=l.sid;a.textContent=l.title||l.sid;
    r.querySelector('.lstate').textContent=[l.state,l.goal&&l.goal!=='complete'?'goal: '+(GOAL_WORD[l.goal]||l.goal):l.goal==='complete'?'goal done':'']
     .filter(Boolean).join(' · ');
    if(lk.talking_to&&lk.talking_to.sid===l.sid)r.classList.add('active');
    body.appendChild(r)})})}

 if(running||queued||bg){
  const bits=[];
  if(running)bits.push(running+' answering');
  if(queued)bits.push(queued+' queued');
  if(bg)bits.push(bg+' in the background');
  dockSection(d,'work','work',bits.join(' · '),body=>{
   bgjobs.slice(0,6).forEach(t=>{
    const r=el('<div class=st></div>');
    const sp=document.createElement('span');
    sp.textContent=(t.title||t.command||t.name||'task')
      +(t.secs?' · '+fmtSecs(t.secs):'');
    r.appendChild(sp);
    // as the CLI's task list: open one to read what it has written, or stop it
    if(t.item){
     sp.style.cursor='pointer';sp.title='what it has written so far';sp.onclick=()=>showTaskOutput(t.item);
     if(t.item.can_stop){const x=el('<button class=ghost style="margin-left:8px;padding:0 7px">stop</button>');
      x.onclick=async e=>{e.stopPropagation();x.disabled=true;
       const ok=await apiPost('/api/tasks/stop',{kind:'background',id:t.item.id,sid:t.item.sid},'stopping');
       x.textContent=ok?'stopped':'stop';if(ok)setTimeout(pollBg,600);else x.disabled=false};
      r.appendChild(x)}}
    body.appendChild(r)});
   qitems.slice(0,4).forEach(it=>{
    const r=el('<div class=st></div>');
    const sp=document.createElement('span');
    sp.textContent='waiting to send: '+String(it.text||'').split('\n')[0].slice(0,70);
    r.appendChild(sp);body.appendChild(r)})})}

 if(git){
  const bits=[git.branch];
  if(git.op)bits.push('⚠ '+git.op+' in progress'+(git.conflicts?' · '+git.conflicts+' conflict'+(git.conflicts>1?'s':''):''));
  if(git.dirty)bits.push(git.dirty+' changed');
  if(git.ahead)bits.push('↑'+git.ahead);
  if(git.behind)bits.push('↓'+git.behind);
  dockSection(d,'git','git',bits.join(' · '),body=>{
   [[git.diff||'nothing uncommitted'],[git.untracked?git.untracked+' untracked':''],
    [git.last?'last: '+git.last:'']].forEach(([t])=>{
    if(!t)return;const r=el('<div class=st></div>');
    const sp=document.createElement('span');sp.textContent=t;r.appendChild(sp);body.appendChild(r)});
   // each changed file, and its diff on a click
   const files=git.files||[];
   files.slice(0,40).forEach(f=>{
    const r=el('<div class="st gitfile" style="cursor:pointer" title="show the diff"></div>');
    const mark={M:'M',A:'A',D:'D',R:'R','?':'new',U:'conflict'}[f.status]||f.status;
    r.innerHTML=`<code style="min-width:3.2em;display:inline-block;color:var(--${f.status==='U'?'err':f.status==='?'||f.status==='A'?'ok':'mut'})">${esc(mark)}</code><span class=gp></span>`+
     (f.added!=null?` <span class=add>+${f.added}</span> <span class=del>−${f.removed||0}</span>`:'');
    r.querySelector('.gp').textContent=f.path;
    r.onclick=()=>showGitDiff(f.path);body.appendChild(r)});
   if(files.length>40)body.appendChild(el(`<div class=st><span>and ${files.length-40} more</span></div>`));
   if(git.op&&git.conflicts){const b=el('<button class=ghost style="margin-top:4px">ask Orbit to resolve the conflicts</button>');
    b.onclick=()=>{q.value=`A ${git.op} is in progress with ${git.conflicts} conflicted file(s). Look at each conflict, resolve it sensibly, and tell me what you chose — do not commit or continue the ${git.op} until I say so.`;q.focus();fitQ()};
    body.appendChild(b)}})}}
async function showGitDiff(path){
 try{const r=await fetch('/api/git/diff?sid='+encodeURIComponent(sid)+'&path='+encodeURIComponent(path));
  const d=await r.json();if(!r.ok||d.error){toast(d.error||'no diff');return}
  openSheet(path,body=>{body.appendChild(d.diff?diffBlock(d,d.existed?'changed':'new file'):el('<div class=sheetnote>No changes to show (a binary file, or it matches the last commit).</div>'))})}
 catch(e){toast('could not read the diff')}}

/* ---------------- jump between your messages ---------------- */
function jumpTo(n,block){
 n.scrollIntoView({block:block||'center'});
 n.classList.remove('flash');void n.offsetWidth;n.classList.add('flash');
 setTimeout(()=>n.classList.remove('flash'),1500)}
function jumpRel(dir){
 const us=[...wrap.querySelectorAll('.msg.u')];if(!us.length)return;
 const top=log.getBoundingClientRect().top;
 let i=-1;
 if(dir<0)us.forEach((n,k)=>{if(n.getBoundingClientRect().top<top-4)i=k});
 else i=us.findIndex(n=>n.getBoundingClientRect().top>top+4);
 if(i>=0)jumpTo(us[i],'start')}
function openJump(){
 closePal();showPane('log');
 const all=[...wrap.querySelectorAll('.msg.u')].map((n,i)=>{
  const b=n.querySelector('.bub'),ts=n.querySelector('.who .ts');
  return {n,i,label:(b?b.textContent:'').replace(/\s+/g,' ').trim().slice(0,80)||'(image)',sub:ts?ts.textContent:''}});
 if(!all.length){toast('nothing of yours in this chat yet');return}
 pal=el(`<div class=palette><input placeholder="Jump to one of your messages…"><div class=res></div></div>`);
 document.body.appendChild(pal);
 const inp=pal.querySelector('input'),res=pal.querySelector('.res');
 let items=all;palSel=items.length-1;
 const pick=it=>{closePal();jumpTo(it.n)};
 const draw=()=>{res.innerHTML='';
  items.forEach((it,i)=>{
   const d=el(`<div class="it${i===palSel?' sel':''}"><span class=k>#${it.i+1}</span><span class=t></span><span class=s></span></div>`);
   d.querySelector('.t').textContent=it.label;d.querySelector('.s').textContent=it.sub;
   d.onclick=()=>pick(it);res.appendChild(d)});
  const s=res.children[palSel];if(s)s.scrollIntoView({block:'nearest'})};
 inp.oninput=()=>{const t=inp.value.trim().toLowerCase();
  items=all.filter(x=>!t||x.label.toLowerCase().includes(t));palSel=items.length-1;draw()};
 inp.onkeydown=e=>{
  if(e.key==='Escape')return closePal();
  if(e.key==='ArrowDown'){e.preventDefault();palSel=Math.min(palSel+1,items.length-1);draw()}
  if(e.key==='ArrowUp'){e.preventDefault();palSel=Math.max(palSel-1,0);draw()}
  if(e.key==='Enter'){e.preventDefault();const it=items[palSel];if(it)pick(it)}};
 draw();inp.focus();
 pal.addEventListener('click',e=>e.stopPropagation());
 setTimeout(()=>document.addEventListener('click',closePal,{once:true}),0)}

/* ---------------- usage stats ---------------- */
async function showStats(days){
 days=days||7;
 const opts=[[1,'last day'],[7,'last 7 days'],[30,'last 30 days'],[36500,'all time']];
 $('#modalhost').innerHTML=`<div class=modal><div class="sheet auto" style="max-width:760px">
  <header><b>Usage</b><select id=st_days class=ghost style="max-width:140px">${
   opts.map(([v,l])=>`<option value=${v}${v===days?' selected':''}>${l}</option>`).join('')}</select>
   <button class=ghost style="margin-left:auto" id=stx>close</button></header>
  <div class=body id=stbody><div class=note>loading…</div></div></div></div>`;
 $('#stx').onclick=closeModal;
 $('#modalhost').querySelector('.modal').onclick=e=>{if(e.target.classList.contains('modal'))closeModal()};
 $('#st_days').onchange=e=>showStats(+e.target.value);
 const body=$('#stbody');let d;
 try{const r=await fetch('/api/stats?days='+days);d=await r.json().catch(()=>({}));
  if(!r.ok||d.error)throw new Error(d.error||('the server answered '+r.status))}
 catch(e){body.innerHTML='';const x=el('<div class=err></div>');
  x.textContent='Could not load usage stats: '+(e.message||e);body.appendChild(x);return}
 const n=v=>(+v||0).toLocaleString();
 const models=Object.entries(d.models||{}).sort((a,b)=>(b[1].turns||0)-(a[1].turns||0));
 const tot=models.reduce((t,[,m])=>({p:t.p+(+m.prompt_tokens||0),c:t.c+(+m.completion_tokens||0),
   s:t.s+(+m.seconds||0)}),{p:0,c:0,s:0});
 const tools=Object.entries(d.tools||{}).sort((a,b)=>b[1]-a[1]).slice(0,15);
 const byDay=Object.entries(d.by_day||{}).sort((a,b)=>b[0].localeCompare(a[0]));
 const tbl=(head,rows)=>rows.length?`<table class=stbl><thead><tr>${
   head.map((h,i)=>`<th${i?' class=n':''}>${h}</th>`).join('')}</tr></thead><tbody>${
   rows.map(r=>`<tr>${r.map((c,i)=>`<td${i?' class=n':''}>${c}</td>`).join('')}</tr>`).join('')}</tbody></table>`
  :'<div class=note>nothing in this period</div>';
 body.innerHTML=`<div class=stat>
   <div><b>${n(d.turns)}</b><small>turns</small></div>
   <div><b>${n(tot.p+tot.c)}</b><small>tokens · ${n(tot.c)} out</small></div>
   <div><b>${fmtSecs(tot.s)}</b><small>model time</small></div></div>
  <div class=sec style="margin-top:18px;padding-top:14px;border-top:1px solid var(--line)">By model</div>${
   tbl(['model','turns','prompt tok','output tok','time','tok/s'],models.map(([k,m])=>[esc(k),n(m.turns),
    n(m.prompt_tokens),n(m.completion_tokens),fmtSecs(m.seconds),
    m.seconds>0&&m.completion_tokens?(m.completion_tokens/m.seconds).toFixed(1):'—']))}
  <div class=sec>Top tools</div>${tbl(['tool','calls'],tools.map(([k,v])=>[esc(k),n(v)]))}
  <div class=sec>By day</div>${tbl(['day','turns','tokens'],byDay.map(([k,v])=>[esc(k),n(v.turns),n(v.tokens)]))}`}

$('#send').onclick=go;
$('#crewbtn').onclick=()=>openCrew();
$('#clusterbtn').onclick=()=>openCluster();
$('#newchat').onclick=newChat;
$('#newwith').onclick=()=>newChatWith();
$('#compact').onclick=doCompact;
// Easy mode: only the ticked tools are offered. Switchable from here because the point
// of it is to try a model with less on its bench and see if it does better.
async function setEasy(on){
 // per chat: a chat on a small local model keeps easy mode on while the one next to
 // it does not, and switching between them should not mean setting it again
 if(sid){
  const d=await apiPost('/api/chat/setting',{sid,key:'easy_mode',value:!!on},'easy mode');
  if(!d)return;
  CHATPREFS.easy_mode=!!on;
  const info=await (await fetch('/api/info?sid='+encodeURIComponent(sid))).json().catch(()=>null);
  if(info&&info.tools)INFO.tools=info.tools;
  drawEasyBtn();
  sysline(on?`easy mode on for this chat — ${(INFO.tools||[]).length} tools offered`
            :`easy mode off for this chat — ${(INFO.tools||[]).length} tools offered`);
  return}
 const d=await apiPost('/api/settings',{settings:{easy_mode:!!on}},'easy mode');
 if(!d)return;
 INFO.settings=Object.assign(INFO.settings||{},{easy_mode:!!on});
 if(d.tools)INFO.tools=d.tools;
 drawEasyBtn();
 sysline(on?`easy mode on — ${(INFO.tools||[]).length} tools offered (Settings → Tools to choose which)`
           :`easy mode off — ${(INFO.tools||[]).length} tools offered`)}

let CHATPREFS={};           // the settings this chat keeps for itself
// Everything on this page that belongs to one chat rather than to Orbit. A chat can
// change without openSession -- a new chat, the temporary one, burning it -- and each
// of those used to leave the last chat's easy mode and branch on screen.
// Which Claude account this chat runs on: shown when there is more than one
function drawAcctPick(){
 const s=$('#hacct');if(!s)return;
 const accs=(HPROV_CACHE.claude||{}).accounts||[];
 if(codexMode()||!$('#hprov')||$('#hprov').value!=='claude'||accs.length<2){s.style.display='none';return}
 s.innerHTML='<option value="">Auto account</option>'+accs.map(a=>`<option value="${esc(a.id)}">${esc(a.label)}${a.exhausted?' · limit':''}${a.home?' ★':''}</option>`).join('');
 s.title='Which Claude account this chat runs on. Auto: the main account (★), and the next one when its limit is reached.';
 s.value=(CHATPREFS||{}).claude_account||'';
 s.style.display='';
 s.onchange=async()=>{const v=s.value;
  const d=await apiPost('/api/chat/setting',{sid,key:'claude_account',value:v||null},'account');
  if(d){CHATPREFS=d.prefs||CHATPREFS;drawEngineUI();
   toast(v?'This chat runs on '+((accs.find(a=>a.id===v)||{}).label||v)+' (it moves to another if that one runs out)':'Automatic: the main account, then the next')}}}

// How hard this chat thinks: chosen next to the model, kept per chat. Claude Code gets it as
// --effort, Codex as the turn's effort, and Orbit's own agent as its reasoning effort.
var EFFORTS=[['','Effort: default'],['low','Effort: low'],['medium','Effort: medium'],['high','Effort: high'],['xhigh','Effort: extra high'],['max','Effort: max']];
async function setChatEffort(v){
 const d=await apiPost('/api/chat/setting',{sid,key:'reasoning_effort',value:v||null},'effort');
 if(d){CHATPREFS=d.prefs||CHATPREFS;drawEffortPick();drawEngineUI();
  toast(v?'This chat now thinks at '+((EFFORTS.find(e=>e[0]===v)||[])[1]||v).replace('Effort: ','')+' effort':'Effort back to the default')}
 return d}
function drawEffortPick(){
 const s=$('#heffort');if(!s)return;
 const cur=(CHATPREFS||{}).reasoning_effort||'';
 s.innerHTML=EFFORTS.map(([v,l])=>`<option value="${v}"${v===cur?' selected':''}>${l}</option>`).join('');
 s.value=cur;
 s.title='How hard this chat thinks. Default: '+(codexMode()?"Codex's own":MODELS.harness_mode?"Claude's own":"Orbit's setting")+'. Higher is slower and uses more of your allowance.';
 s.onchange=async()=>{const v=s.value;
  setChatEffort(v)}}

function chatChanged(prefs,fresh){
 CHATPREFS=prefs||{};
 drawAcctPick();drawEffortPick();drawEngineUI();
 GITSTATE=null;GITSID=null;GITAT=0;
 findClose();
 drawEasyBtn();drawStayBtn();drawPlanDock();drawWtBadge();
 tabsNote(!!fresh);
 if(sid)pollGit(true)}

function easyOn(){
 if('easy_mode' in CHATPREFS)return !!CHATPREFS.easy_mode;
 return !!(INFO.settings&&INFO.settings.easy_mode)}

// "stay": this chat never moves to another model. When the one it uses drops out (the cluster
// Qwen, a lost connection) it waits and asks again until the model is back. Per chat; Settings
// → Fallback sets the default for every chat.
function stayOn(){
 if('no_fallback' in CHATPREFS)return !!CHATPREFS.no_fallback;
 return !!(INFO.settings&&INFO.settings.no_fallback)}
function drawStayBtn(){
 const b=$('#staybtn');if(!b)return;
 const on=stayOn();
 b.classList.toggle('on',on);
 b.textContent=on?'stay on model':'stay';
 b.title=on?'No fallback: this chat keeps its model and, if the connection drops, waits and retries until it is back. Click to allow switching to a fallback model again.'
           :'Fallback is allowed: after repeated failures this chat carries on with another model (Settings → Fallback). Click to keep this chat on its model and retry until it answers.'}
async function setStay(v){
 if(!sid){toast('open a chat first');return null}
 const d=await apiPost('/api/chat/setting',{sid,key:'no_fallback',value:v},'no fallback');
 if(d){CHATPREFS=d.prefs||CHATPREFS;drawStayBtn();
  toast(v===null?'Fallback follows Settings for this chat':v?'This chat stays on its model and retries until it answers':'This chat may switch to a fallback model')}
 return d}
if($('#staybtn'))$('#staybtn').onclick=()=>setStay(!stayOn());

function drawEasyBtn(){
 const b=$('#easybtn'); if(!b)return;
 const on=easyOn(), n=(INFO.tools||[]).length;
 b.classList.toggle('on',on);
 b.textContent=on?`easy · ${n}`:'easy';
 b.title=on?`easy mode is on — ${n} tools offered. Click to give the model all of them again `
            +`(Settings → Tools to choose which are kept).`
           :`easy mode is off — ${n} tools offered. Click to hand the model only the essential ones, `
            +`which a small model chooses from better (Settings → Tools to choose which).`;
 b.onclick=()=>setEasy(!on)}

$('#more').onclick=e=>{e.stopPropagation();
 const r=$('#more').getBoundingClientRect();
 ctxMenu({clientX:r.left-90,clientY:r.bottom+4},[
  {icon:'⤓',label:'Export markdown',run:()=>location.href='/api/export?id='+encodeURIComponent(sid||'')},
  {icon:'⤓',label:'Export HTML (with figures)',run:()=>exportHTML()},
  {icon:'☑',label:'Pick turns to export or copy…',run:startPicking},
  ...(DESK&&DESK.exportPDF?[{icon:'⤓',label:'Export as PDF…',run:()=>DESK.exportPDF()}]:[]),
  '-',
  {icon:'▭',label:'Terminal in this chat\'s folder  (Ctrl+`)',run:()=>toggleTerm(true)},
  {icon:'⑂',label:wtOf()?'Separate copy: '+wtOf().branch+'…':'Work in a separate copy (git worktree)…',run:openWorktree},
  {icon:'◌',label:tempMode?'Temporary chat (on)':'Temporary chat — nothing is saved',run:()=>$('#tempbtn').click()},
  {icon:'⇲',label:'Compact this chat',run:()=>$('#compact').click()},
  '-',
  {icon:easyOn()?'☑':'☐',
   label:'Easy mode — essential tools only (this chat)',
   run:()=>setEasy(!easyOn())},
  {icon:'⚙',label:'Choose what easy mode keeps…',run:()=>openSettings('tools')},
  {icon:'✎',label:'System prompt for this chat',run:chatPromptDlg},
  {icon:'★',label:'Save memories from this chat',run:suggestMem},
  '-',
  {icon:'▤',label:'Usage stats',run:showLedger},
  {icon:'▦',label:'Usage by model…',run:()=>showStats(7)},
  {icon:'↧',label:'Jump to a message…',run:openJump},
  {icon:'✓',label:'Health check',run:showHealth},
 ])};
async function chatPromptDlg(){
 // THIS chat's, not whichever chat the Mac happens to have open: on a phone, or in a
 // second window, the dialog pre-filled another chat's prompt and then saved it onto
 // this one
 const st=await (await fetch('/api/state'+(sid?'?sid='+encodeURIComponent(sid):''))).json();
 if(st.error)return toast('could not read this chat — '+st.error);
 const t=prompt('Extra system prompt for THIS chat only (blank to clear):',st.sys_override||'');
 if(t===null)return;
 await fetch('/api/sysprompt',{method:'POST',headers:{'Content-Type':'application/json'},
  body:JSON.stringify({text:t,sid})});
 sysline(t.trim()?'chat prompt set':'chat prompt cleared')}
async function showLedger(){
 const d=await (await fetch('/api/ledger')).json();
 sysline(`this chat: ${d.session.turns} turns · ${d.session.completion_tokens} out tokens · `
  +`${d.session.seconds}s · ${d.session.tok_per_s} tok/s   |   all time: ${d.all.turns} turns · `
  +`${d.all.completion_tokens} tokens`)}
async function suggestMem(){
 sysline('looking for durable facts...');
 const d=await (await fetch('/api/memory/suggest',{method:'POST'})).json();
 if(!d.items||!d.items.length)return sysline('nothing worth remembering from this chat');
 const box=el('<div class=msg></div>');
 box.appendChild(el('<div class=who>suggested memories</div>'));
 d.items.forEach(it=>{
  const r=el('<div class=memrow style="margin:6px 0"><b></b><span></span><button class=ghost>save</button><button class=ghost>skip</button></div>');
  r.querySelector('b').textContent=it.name;r.querySelector('span').textContent=it.content;
  const [sv,sk]=r.querySelectorAll('button');
  sv.onclick=async()=>{await fetch('/api/memory/save',{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify({name:it.name,text:it.content})});
   r.querySelector('span').textContent='saved';sv.remove();sk.remove()};
  sk.onclick=()=>r.remove();
  box.appendChild(r)});
 wrap.appendChild(box);bottom()}
$('#filtersel').onchange=e=>{filterMode=e.target.value;renderSessions(true)};
GROUP_BY=PREF.get('groupby','date');
$('#groupsel').value=GROUP_BY;
$('#groupsel').onchange=e=>{GROUP_BY=e.target.value;PREF.set('groupby',GROUP_BY);renderSessions(true)};
$('#groupsel').onclick=e=>e.stopPropagation();
$('#filtersel').onclick=e=>e.stopPropagation();
// sections fold, and stay folded next time
document.querySelectorAll('.sechead[data-sec]').forEach(h=>{
 const name=h.dataset.sec,body=document.querySelector(`.secbody[data-sec="${name}"]`);
 const apply=open=>{h.classList.toggle('closed',!open);body.classList.toggle('closed',!open)};
 apply(sideOpenSec(name,true));
 h.onclick=e=>{if(e.target.closest('button,select'))return;
  const open=h.classList.contains('closed');apply(open);PREF.set('sec_'+name,open?'1':'0')}});
$('#srvmenu').onclick=e=>{e.stopPropagation();const b=$('#srvbar');b.style.display=b.style.display==='none'?'':'none'};
$('#sidehide').onclick=cycleSide;    // full -> rail -> gone, the same as ☰
$('#searchbtn').onclick=e=>{e.stopPropagation();openPal()};
$('#footmore').onclick=e=>{e.stopPropagation();const r=e.target.getBoundingClientRect();
 ctxMenu({clientX:r.left,clientY:r.top-190},[
  {icon:'\u{1F9E0}',label:'Memory & instructions',run:()=>openSettings('memory')},
  {icon:'\u270E',label:'Saved prompts',run:()=>{libTab='prompts';showPane('lib')}},
  {icon:'\u2695',label:'Doctor',run:()=>showHealth()},
  {icon:'\u{1F4D6}',label:'User guide',run:()=>openGuide()},
  {icon:'\u2726',label:'Welcome',run:()=>showOnboarding()},
  {icon:'\u2328',label:'Keyboard shortcuts',run:()=>showShortcuts()},
  {icon:'\u2139',label:'About & help',run:()=>showAbout()}])};
// Sending a colleague the three turns where you worked something out used to mean
// exporting the whole chat or copying one answer: there was nothing in between.
let PICKING=false;
function startPicking(){
 if(PICKING)return stopPicking();
 PICKING=true;log.classList.add('picking');
 wrap.querySelectorAll('.msg').forEach(m=>{
  if(m.querySelector(':scope > .pick'))return;
  const l=el('<label class=pick><input type=checkbox></label>');
  l.onclick=ev=>ev.stopPropagation();
  l.querySelector('input').onchange=drawPickBar;
  m.insertBefore(l,m.firstChild)});
 drawPickBar()}
function stopPicking(){
 PICKING=false;log.classList.remove('picking');
 wrap.querySelectorAll('.pick').forEach(x=>x.remove());
 const b=$('#pickbar');if(b)b.remove()}
function pickedMsgs(){
 return [...wrap.querySelectorAll('.msg')].filter(m=>{
  const c=m.querySelector(':scope > .pick input');return c&&c.checked})}
function drawPickBar(){
 let b=$('#pickbar');
 if(!b){b=el(`<div id=pickbar class=pickbar><span class=pn></span>
   <button class=ghost data-a=all>all</button><button class=ghost data-a=none>none</button>
   <button data-a=html>Export</button><button class=ghost data-a=copy>Copy</button>
   <button class=ghost data-a=x>done</button></div>`);
  document.body.appendChild(b);
  b.querySelector('[data-a=all]').onclick=()=>{
   wrap.querySelectorAll('.pick input').forEach(c=>c.checked=true);drawPickBar()};
  b.querySelector('[data-a=none]').onclick=()=>{
   wrap.querySelectorAll('.pick input').forEach(c=>c.checked=false);drawPickBar()};
  b.querySelector('[data-a=x]').onclick=stopPicking;
  b.querySelector('[data-a=html]').onclick=()=>{const p=pickedMsgs();
   if(!p.length)return toast('nothing picked');exportHTML(p);stopPicking()};
  b.querySelector('[data-a=copy]').onclick=()=>{const p=pickedMsgs();
   if(!p.length)return toast('nothing picked');
   copy(p.map(m=>(m.classList.contains('u')?'You: ':'Orbit: ')+
     ((m.querySelector('.bub')||{}).textContent||'').trim()).join('\n\n'));
   stopPicking()}}
 const p=pickedMsgs();
 const bytes=p.reduce((n,m)=>n+((m.querySelector('.bub')||m).innerHTML||'').length,0);
 b.querySelector('.pn').textContent=p.length?
   `${p.length} of ${wrap.querySelectorAll('.msg').length} · ${fmtBytes(bytes)}`
   :'pick the turns you want';
 b.querySelectorAll('[data-a=html],[data-a=copy]').forEach(x=>x.disabled=!p.length)}
function fmtBytes(n){return n>=1048576?(n/1048576).toFixed(1)+' MB'
 :n>=1024?Math.round(n/1024)+' KB':n+' B'}

function exportHTML(only){
 const html=`<!doctype html><meta charset=utf-8><title>${esc($('#title').textContent)}</title>`
  +`<style>body{font:15px/1.6 -apple-system,sans-serif;max-width:800px;margin:40px auto;padding:0 20px}
    .u{background:#f4f3f0;border-radius:10px;padding:10px 14px;margin:14px 0}
    pre{background:#f4f3f0;padding:10px;border-radius:8px;overflow-x:auto}
    img{max-width:100%;border-radius:8px}h1{font-size:20px}</style>`
  +`<h1>${esc($('#title').textContent)}</h1>`
  +(only&&only.length?only:[...wrap.querySelectorAll('.msg')]).map(m=>{
     const who=m.classList.contains('u')?'You':'Orbit';
     const b=m.querySelector('.bub');
     return `<h3>${who}</h3><div class="${m.classList.contains('u')?'u':''}">${b?b.innerHTML:''}</div>`
    }).join('');
 const blob=new Blob([html],{type:'text/html'});
 const a=document.createElement('a');a.href=URL.createObjectURL(blob);
 a.download=($('#title').textContent||'chat').slice(0,40)+'.html';a.click();
 setTimeout(()=>URL.revokeObjectURL(a.href),4000)}
$('#settings2').onclick=()=>openSettings();
$('#opensettings').onclick=()=>openSettings();
$('#openmem').onclick=()=>openSettings('memory');
$('#openprompts').onclick=()=>{libTab='prompts';showPane('lib')};
$('#opendoctor').onclick=showHealth;
$('#openkeys').onclick=showShortcuts;
$('#openabout').onclick=showAbout;
$('#openkeys').ondblclick=showOnboarding;
// innerWidth is 0 while the window is hidden; that is not a phone
const narrow=()=>innerWidth>0&&matchMedia('(max-width:820px)').matches;
function sideOpen(on,rail){
 const a=$('#side'); if(!a)return;
 const railed=!!rail&&!!on&&!narrow();
 a.classList.toggle('rail',railed);
 a.classList.toggle('hide',!on);
 // applySidebar writes an inline width for the drag-to-resize grip, and an inline
 // width beats a class: the rail would have kept the full width it was given
 if(railed){a.style.width='';a.style.flexBasis=''}
 else if(on&&!narrow()){const w=Number(PREF.get('sidew',256));
  a.style.width=w+'px';a.style.flexBasis=w+'px'}
 let sc=document.querySelector('.scrim');
 if(on&&narrow()){
  if(!sc){sc=el('<div class=scrim></div>');sc.onclick=()=>sideOpen(false);document.body.appendChild(sc)}
 } else if(sc) sc.remove();
 PREF.set('sidestate',!on?'hidden':(a.classList.contains('rail')?'rail':'open'));
}
// Three states on a wide screen — full, a rail of icons, gone — because "gone" alone
// threw away the running indicators along with the width. A phone keeps the two it had.
function cycleSide(){
 const a=$('#side');
 if(narrow())return sideOpen(a.classList.contains('hide'));
 if(a.classList.contains('hide'))return sideOpen(true,false);
 if(a.classList.contains('rail'))return sideOpen(false);
 return sideOpen(true,true);
}
$('#toggle').onclick=cycleSide;
const WIDE_PLACEHOLDER=q.placeholder;
function applyWidth(){
 const n=narrow();
 const want=PREF.get('sidestate','open');
 sideOpen(n?false:want!=='hidden', want==='rail');   // a phone starts on the conversation
 q.placeholder=n?'Ask anything…':WIDE_PLACEHOLDER;
}
applyWidth();
addEventListener('resize',applyWidth);
$('#srv_start').onclick=async()=>{toast('starting...');
 const d=await (await fetch('/api/server/start',{method:'POST'})).json();toast(d.msg);refreshStatus()};
$('#srv_stop').onclick=async()=>{const d=await (await fetch('/api/server/stop',{method:'POST'})).json();
 toast(d.msg);refreshStatus()};
$('#srv_restart').onclick=async()=>{toast('restarting...');
 const d=await (await fetch('/api/server/restart',{method:'POST'})).json();toast(d.msg);refreshStatus()};
// Which physical key was pressed, not which character it produces: ⌘K on a Dvorak or a
// Cyrillic layout sends a different e.key and matched nothing. `e.code` alone, not
// "code OR key" — that gave every shortcut two triggers, so on Dvorak the key that
// produces `l` also fired ⌘L and took the browser's address bar with it. Where there is
// no code (a synthetic event, some remote keyboards) fall back to the character.
const keyIs=(e,letter)=>e.code?e.code===('Key'+letter.toUpperCase())
  :(e.key||'').toLowerCase()===letter;
addEventListener('keydown',e=>{
 // Escape is not a shortcut, it is the way out, and a modal that cannot be dismissed
 // while an IME session is open is worse than one closed a keystroke early
 if(e.key==='Escape'&&$('#modalhost').innerHTML){closeModal();return}
 // the rest must not fire out of the middle of composing Japanese or Chinese
 if(composing(e))return;
 // and a held-down ⌘K must open one new chat, not forty. Arrows are the exception:
 // holding one to walk through your messages is what it is for.
 if(e.repeat&&e.key!=='ArrowUp'&&e.key!=='ArrowDown')return;
 if(e.key==='Escape')closeModal();
 if((e.metaKey||e.ctrlKey)&&(e.key===','||e.code==='Comma')){e.preventDefault();openSettings()}
 if((e.metaKey||e.ctrlKey)&&e.shiftKey&&keyIs(e,'k')){e.preventDefault();newChatWith();return}
 if((e.metaKey||e.ctrlKey)&&keyIs(e,'k')){e.preventDefault();newChat();return}
 if((e.metaKey||e.ctrlKey)&&keyIs(e,'f')){e.preventDefault();
  if(e.shiftKey||!sid||!wrap.children.length)$('#search').focus(); else openFind()}
 if((e.metaKey||e.ctrlKey)&&keyIs(e,'j')){e.preventDefault();showPane('files')}
 if((e.metaKey||e.ctrlKey)&&keyIs(e,'p')){e.preventDefault();openPal()}
 const dialog=!!$('#modalhost').innerHTML;
 if(!dialog&&(e.metaKey||e.ctrlKey)&&!e.shiftKey&&keyIs(e,'g')){e.preventDefault();openJump()}
 if(!dialog&&e.altKey&&!e.metaKey&&!e.ctrlKey&&(e.key==='ArrowUp'||e.key==='ArrowDown')&&log.style.display!=='none'){
  const ae=document.activeElement;           // leave Alt+arrows alone while editing text
  if(!(ae&&/input|textarea|select/i.test(ae.tagName)&&ae.value)){
   e.preventDefault();jumpRel(e.key==='ArrowUp'?-1:1)}}
 if(e.key==='?'&&document.activeElement!==q&&!/input|textarea/i.test(document.activeElement.tagName)){
  e.preventDefault();showShortcuts()}});
// ---- tabs: the chats you have open, along the top (in the desktop app, its title bar).
// Opening a chat gives it a tab; ⌘W closes one and ⌘⇧T brings it back. A brand-new chat
// you leave without writing in loses its tab, as it is never saved.
const DESK=window.orbitDesktop&&window.orbitDesktop.isDesktop?window.orbitDesktop:null;
if(DESK)document.documentElement.classList.add('desktop');
const TAB_MAX=12;
let TABS=[],TAB_USED={},TAB_TITLES={},CLOSED_TABS=[],FRESH_TABS=new Set(),TAB_LAST=null,DESK_SENT='';
try{const t=JSON.parse(localStorage.getItem('orbit.tabs')||'{}');
 TABS=(t.open||[]).filter(x=>typeof x==='string').slice(0,TAB_MAX);TAB_TITLES=t.titles||{};TAB_USED=t.used||{}}catch(e){}
function saveTabs(){try{const keep={};TABS.forEach(id=>{if(TAB_TITLES[id])keep[id]=TAB_TITLES[id]});
 const used={};TABS.forEach(id=>{if(TAB_USED[id])used[id]=TAB_USED[id]});
 localStorage.setItem('orbit.tabs',JSON.stringify({open:TABS,titles:keep,used}))}catch(e){}}
function tabTitle(id){
 const s=SESSIONS.find(x=>x.id===id);
 if(s&&s.title)TAB_TITLES[id]=s.title;
 if(id===sid){const t=$('#title').textContent;if(t&&t!=='New chat')TAB_TITLES[id]=t}
 return TAB_TITLES[id]||(FRESH_TABS.has(id)||id===sid?($('#title').textContent||'New chat'):'Chat')}
let TABS_CHECKED=false;
async function pruneTabs(){
 if(TABS_CHECKED)return;TABS_CHECKED=true;
 if(sid&&!TABS.includes(sid))tabsNote(!SESSIONS.some(s=>s.id===sid));
 const unknown=TABS.filter(id=>id!==sid&&!SESSIONS.some(s=>s.id===id)&&!RUNNING.has(id));
 for(const id of unknown){
  // a chat the list does not show may simply be older than the page of it loaded
  try{const r=await fetch('/api/session/'+encodeURIComponent(id));const d=await r.json();
   if(!r.ok||d.error||!(d.messages||[]).some(m=>m.role==='user'))TABS=TABS.filter(x=>x!==id);
   else if(d.title)TAB_TITLES[id]=d.title}catch(e){}}
 saveTabs();drawTabs()}
function tabSaved(id){return !FRESH_TABS.has(id)||SESSIONS.some(s=>s.id===id)||RUNNING.has(id)}
// every chat switch passes through chatChanged, which calls this
function tabsNote(fresh){
 if(!sid)return;
 if(fresh)FRESH_TABS.add(sid);
 // the new chat you just left, never written in, goes
 if(TAB_LAST&&TAB_LAST!==sid&&!tabSaved(TAB_LAST))TABS=TABS.filter(x=>x!==TAB_LAST);
 if(!TABS.includes(sid)){
  const at=TABS.indexOf(TAB_LAST);TABS.splice(at<0?TABS.length:at+1,0,sid);
  while(TABS.length>TAB_MAX){       // the one you used longest ago makes room
   const old=TABS.filter(x=>x!==sid).sort((a,b)=>(TAB_USED[a]||0)-(TAB_USED[b]||0))[0];
   TABS=TABS.filter(x=>x!==old)}}
 TAB_USED[sid]=Date.now();TAB_LAST=sid;saveTabs();drawTabs()}
function drawTabs(){
 const bar=$('#tabstrip');if(!bar)return;
 const show=DESK?TABS.length>0:TABS.length>1;
 bar.classList.toggle('off',!show);
 if(DESK){const title=sid?tabTitle(sid):'';const key=sid+'\n'+title;
  if(key!==DESK_SENT&&DESK.setActiveChat){DESK_SENT=key;try{DESK.setActiveChat(sid||null,title)}catch(e){}}}
 if(!show){bar.innerHTML='';return}
 const sig=JSON.stringify([TABS,sid,TABS.map(id=>[tabTitle(id),RUNNING.has(id),WAITING.has(id),!!UNSEEN[id]])]);
 if(bar.dataset.sig===sig)return;bar.dataset.sig=sig;
 bar.innerHTML='';
 TABS.forEach((id,i)=>{
  const st=WAITING.has(id)?'wait':RUNNING.has(id)?'run':UNSEEN[id]?'new':'';
  const b=el(`<button class="tab${id===sid?' on':''}" draggable=true><span class="td ${st}"></span><span class=tt></span><span class=tx title="close tab (⌘W)"><svg viewBox="0 0 10 10" width="9" height="9" aria-hidden="true"><path d="M2 2l6 6M8 2l-6 6" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg></span></button>`);
  b.querySelector('.tt').textContent=tabTitle(id);
  b.title=tabTitle(id)+(st==='wait'?' — waiting for you':st==='run'?' — answering':st==='new'?' — new since you looked':'')+(i<9?`  ·  ${DESK?'⌘':'Alt+'}${i+1}`:'');
  b.onclick=e=>{if(e.target.closest('.tx')){e.stopPropagation();closeTab(id);return}
   if(id!==sid){showPane('log');openSession(id)}};
  b.onauxclick=e=>{if(e.button===1){e.preventDefault();closeTab(id)}};
  b.ondragstart=e=>{e.dataTransfer.setData('text/orbit-tab',id);e.dataTransfer.effectAllowed='move';b.classList.add('drag')};
  b.ondragend=()=>b.classList.remove('drag');
  b.ondragover=e=>{if(e.dataTransfer.types.includes('text/orbit-tab'))e.preventDefault()};
  b.ondrop=e=>{const from=e.dataTransfer.getData('text/orbit-tab');if(!from||from===id)return;e.preventDefault();
   TABS=TABS.filter(x=>x!==from);TABS.splice(TABS.indexOf(id)+(e.offsetX>b.offsetWidth/2?1:0),0,from);saveTabs();drawTabs()};
  bar.appendChild(b)});
 const add=el(`<button class=tabnew title="new chat (${DESK?'⌘N':'⌘K'})">+</button>`);add.onclick=()=>newChat();bar.appendChild(add);
 const on=bar.querySelector('.tab.on');if(on)on.scrollIntoView({block:'nearest',inline:'nearest'})}
async function closeTab(id){
 id=id||sid;const i=TABS.indexOf(id);if(i<0)return;
 TABS.splice(i,1);
 if(tabSaved(id)){CLOSED_TABS.push(id);if(CLOSED_TABS.length>20)CLOSED_TABS.shift()}
 saveTabs();
 if(id!==sid){drawTabs();return}
 const next=TABS[i]||TABS[i-1];
 TAB_LAST=null;                      // what is left is already a tab; nothing to place it after
 if(next){showPane('log');await openSession(next)}else await newChat();
 drawTabs()}
function reopenTab(){
 const id=CLOSED_TABS.pop();if(!id)return toast('no closed tab to bring back');
 showPane('log');openSession(id)}
function gotoTab(n){
 // ⌘9 is the last tab, as in a browser
 const id=n===9?TABS[TABS.length-1]:TABS[n-1];
 if(id&&id!==sid){showPane('log');openSession(id)}}
function stepTab(d){
 if(TABS.length<2)return;const i=TABS.indexOf(sid);
 gotoTab(((i<0?0:i)+d+TABS.length)%TABS.length+1)}
addEventListener('keydown',e=>{
 // in a browser: Alt+1…9 (⌘1…9 belong to the browser's own tabs); the desktop app's
 // menu sends ⌘1…9 itself
 if(e.altKey&&!e.metaKey&&!e.ctrlKey&&/^Digit[1-9]$/.test(e.code)&&!DESK){
  e.preventDefault();gotoTab(+e.code.slice(5))}});
// Settings → General in Orbit for Mac: how it updates itself. The app keeps these (they
// are about the app, not Orbit's server), so they apply the moment they change.
async function drawDeskUpdates(body){
 const U=DESK&&DESK.updates;if(!U||!body)return;
 let st;try{st=await U.getState()}catch(e){return}
 const box=el(`<div><div class=sec>Orbit for Mac</div><div class=grid>
  <label>Updates</label><select id=du_mode><option value=auto>Install automatically</option>
   <option value=notify>Tell me, I install</option><option value=off>Don't check by itself</option></select>
  <div class=hint2>Automatic updates install when no chat is answering and you are away, or when you quit.</div>
  <label>Check every</label><select id=du_every><option value=1>hour</option><option value=6>6 hours</option>
   <option value=24>day</option><option value=168>week</option></select>
  <label>Beta versions</label><div class=sw><input type=checkbox id=du_beta><span class=note style="margin-left:0">include them</span></div>
  <label>Version</label><div class=sw><span id=du_state></span><button class=ghost id=du_check>Check now</button>
   <button class=primary id=du_install style="display:none">Install and relaunch</button></div>
 </div></div>`);
 body.prepend(box);
 const draw=s=>{st=s||st;const p=st.prefs||{};
  $('#du_mode').value=p.autoUpdate||'notify';$('#du_every').value=String(p.updateCheckEvery||24);$('#du_beta').checked=p.updateChannel==='beta';
  const when=st.lastCheck?new Date(st.lastCheck).toLocaleString([], {dateStyle:'medium',timeStyle:'short'}):'never';
  $('#du_state').textContent=st.checking?'checking…':st.downloading?`downloading ${Math.round((st.progress||0)*100)}%`:
   st.error?st.error:st.available&&st.latest?`${st.current} — ${st.latest.version} is available`:`${st.current} — up to date · checked ${when}`;
  $('#du_install').style.display=st.available?'':'none'};
 draw(st);
 const off=U.onState(s=>{if(!document.body.contains(box)){off&&off();return}draw(s)});
 const set=async patch=>{try{draw(await U.setPrefs(patch))}catch(e){toast('could not change that: '+(e.message||e))}};
 $('#du_mode').onchange=e=>set({autoUpdate:e.target.value});
 $('#du_every').onchange=e=>set({updateCheckEvery:+e.target.value});
 $('#du_beta').onchange=e=>set({updateChannel:e.target.checked?'beta':'stable'});
 $('#du_check').onclick=async()=>{try{draw(await U.check())}catch(e){toast(e.message||String(e))}};
 $('#du_install').onclick=async()=>{try{draw(await U.install())}catch(e){toast(e.message||String(e))}}}
// Settings → Shared projects: switch the feature on, say where members reach this Mac and which models they may talk to, make a project, invite
// people, open it as its owner, freeze it. Every change is saved at once through /api/collabhost; the owner's token never comes to this page.
async function renderCollab(body,gen){
 const call=async d=>{try{const r=await fetch('/api/collabhost',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(d)});const j=await r.json().catch(()=>({}));
  if(!r.ok||j.error){toast((j.error||('error '+r.status)).toString().slice(0,140));return null}return j}catch(e){toast('could not reach Orbit');return null}};
 let st=await call({op:'status'}),models=[],chats={},dash={};
 const loadDash=async()=>{const d=await call({op:'dashboard'});dash={};for(const p of (d&&d.projects)||[])dash[p.id]=p};
 const loadChats=async()=>{for(const p of (st&&st.projects)||[]){const r=await call({op:'project_chats',project:p.id});chats[p.id]=r?r.chats:[]}};
 try{const m=await (await fetch('/api/models')).json();models=(m.models||m||[]).filter(x=>x&&x.id)}catch(e){}
 if(!st||gen!==RENDER_GEN)return;
 await loadChats();await loadDash();
 const reach={web:{t:'Orbit web link',tag:'recommended',d:'People open a link on the Orbit service and sign in. Your Mac makes one outgoing connection to it, so nothing on this Mac is opened to the internet and nobody needs a VPN. The service passes each request through while it happens and keeps no messages.',x:'Exposes: nothing on this Mac. The service sees traffic as it passes (not end-to-end encrypted yet).'},
  local:{t:'This Mac only',d:'Only browsers on this Mac can open it. Good for trying a project out, or when you are the only person.',x:'Exposes: nothing beyond this Mac.'},
  tailscale:{t:'Tailscale',d:'People on your Tailscale network reach this Mac directly over an encrypted link. Both sides need Tailscale.',x:'Exposes: the sharing door, to your tailnet only. Everyone still needs an invitation.'},
  lan:{t:'Local network',d:'Anyone on the same Wi-Fi or office network can reach the door, as long as they have an invitation. The link is not encrypted.',x:'Exposes: the sharing door, to everyone on this network. Use only on a network you trust.'}};
 const ago=t=>{if(!t)return 'no activity yet';const s=Math.max(0,Date.now()/1000-t);return s<90?'just now':s<5400?Math.round(s/60)+' min ago':s<172800?Math.round(s/3600)+' h ago':Math.round(s/86400)+' days ago'};
 let rel=await call({op:'relay_status'});const webOn=()=>!!(rel&&rel.projects&&Object.keys(rel.projects).length);
 const draw=()=>{
  const proj=(st.projects||[]).map(p=>{const d=dash[p.id]||{},a=d.activity||{},web=d.web;
   const chip=(t,c)=>`<span class="pchip ${c||''}">${esc(t)}</span>`;
   const models=(a.models_24h||[]).map(m=>`${esc(m.model)} ${m.turns}`).join(', ');
   return `<div class=pcard data-pid="${esc(p.id)}"><div class=ph><b>${esc(p.name)}</b>${p.frozen?chip('Frozen','bad'):''}${web?(web.state==='connected'?chip('On the web','ok'):chip('Web link: '+(web.state||'off'),'warn')):chip('Not on the web')}${a.approvals_waiting?chip(a.approvals_waiting+' waiting for an approver','warn'):''}</div>
    <div class=pstats><div><b>${p.members}</b><span>${p.members===1?'person':'people'}${d.here?' · '+d.here+' here now':''}</span></div><div><b>${a.messages_24h||0}</b><span>messages in 24 h</span></div><div><b>${a.turns_24h||0}</b><span>model questions in 24 h</span></div><div><b>${d.open_invites||0}</b><span>open invitations</span></div></div>
    <div class=note>${esc(p.working_dir)}<br>Last activity ${ago(a.last_activity)}${models?' · models used: '+models:''}</div>
    <div class=pbtns><button class=primary data-a=quickinvite data-p="${esc(p.id)}">Invite someone</button><button class=ghost data-a=open data-p="${esc(p.id)}">Open it</button><button class=ghost data-a=psettings data-p="${esc(p.id)}">Settings…</button><button class=ghost data-a=${p.frozen?'resume':'panic'} data-p="${esc(p.id)}"${p.frozen?'':' style="color:var(--err)"'}>${p.frozen?'Lift the freeze':'Freeze everything'}</button><button class=ghost data-a=backup data-p="${esc(p.id)}">Back up</button></div>
    <div class=invbox id="inv_${esc(p.id)}" hidden></div>
    <details class=pmore><summary>More for this project</summary>
    <div class=note style="margin-top:6px">Chats in this project</div>
    ${(chats[p.id]||[]).map(c=>`<div style="display:flex;gap:8px;align-items:center;margin:2px 0">• ${esc(c.name)}${c.imported?` <span class=note>shared from this Mac (${c.imported} messages)</span>`:''}${c.id==='main'?'':` <button class=ghost data-a=rmchat data-p="${esc(p.id)}" data-c="${esc(c.id)}" data-n="${esc(c.name)}">Remove from project</button>`} <button class=ghost data-a=copychat data-p="${esc(p.id)}" data-c="${esc(c.id)}">Copy to my chats</button></div>`).join('')}
    <div style="margin-top:6px"><button class=primary data-a=psettings data-p="${esc(p.id)}">Project settings…</button> <button class=ghost data-a=guard data-p="${esc(p.id)}">Guard model and rules…</button> <button class=ghost data-a=changes data-p="${esc(p.id)}">Recent file changes…</button> <button class=ghost data-a=backup data-p="${esc(p.id)}">Back up this project</button> <button class=ghost data-a=people data-p="${esc(p.id)}">People and invitations…</button> <button class=ghost data-a=check data-p="${esc(p.id)}">Check this project</button> <button class=ghost data-a=relay data-p="${esc(p.id)}">Share on the web…</button></div>
    <label style="display:block;margin-top:6px"><input type=checkbox data-a=allowexport data-p="${esc(p.id)}"${p.allow_export!==false?' checked':''}> Members may save copies of chats <span class=note>(it cannot stop a screenshot)</span></label>
    <div style="margin-top:6px;display:flex;gap:6px;flex-wrap:wrap"><button class=ghost data-a=sharechat data-p="${esc(p.id)}">Share a chat from this Mac…</button><button class=ghost data-a=open data-p="${esc(p.id)}">Open as owner</button><button class=ghost data-a=invite data-p="${esc(p.id)}">Invite someone…</button>
    <button class=ghost data-a=${p.frozen?'resume':'panic'} data-p="${esc(p.id)}">${p.frozen?'Lift the freeze':'Freeze everything'}</button>
    </details></div>`}).join('')||'<div class=note>No projects yet. Create one below, then invite people.</div>';
  const mrows=(st.models||[]).map((m,i)=>`<div class=grid style="margin:4px 0"><input data-m=handle data-i=${i} value="${esc(m.handle)}" placeholder="handle (@name)" style="max-width:130px">
    <select data-m=id data-i=${i}>${[...new Set([m.id,...models.map(x=>x.id)])].map(id=>`<option value="${esc(id)}"${id===m.id?' selected':''}>${esc((models.find(x=>x.id===id)||{}).label||id)}</option>`).join('')}</select>
    <input data-m=label data-i=${i} value="${esc(m.label)}" placeholder="label" style="max-width:140px"><input data-m=payer data-i=${i} value="${esc(m.payer)}" placeholder="who pays" style="max-width:150px">
    <label style="white-space:nowrap" title="People in the project see how much of this model's allowance is left (and when it resets), never the account itself"><input type=checkbox data-m=share_usage data-i=${i}${m.share_usage?' checked':''}> show what is left</label>
    <button class=ghost data-a=delmodel data-i=${i}>Remove</button></div>`).join('')||'<div class=note>No models yet: without one, nobody can ask a model anything in a shared project.</div>';
  const cur=st.mode==='local'&&webOn()?'web':st.mode;
  body.innerHTML=`<div class=sec>Shared projects</div><div class=grid>
   <label>Allow shared projects</label><div class=sw><input type=checkbox id=cl_on${st.enabled?' checked':''}><span class=note>${st.running?'on: '+(webOn()&&st.mode==='local'?'through the Orbit web link':'open at '+esc(st.public_url||'')):'off: nothing is listening'}</span></div>
   <div class=hint2>People you invite work in a project with you: a group chat with models, every message labelled with who wrote it. Models run on this Mac (or the server you choose) with only the rights of the person who asked. Off by default.</div></div>
  <div class=sec>Your projects</div>${proj}
  <div class=sec>Who can reach your projects</div><div class=reachgrid role=radiogroup aria-label="Who can reach your projects">${Object.keys(reach).map(k=>`<label class="reach${cur===k?' on':''}"><input type=radio name=cl_mode value=${k}${cur===k?' checked':''}><span class=rt>${esc(reach[k].t)}${reach[k].tag?` <span class="pchip ok">${reach[k].tag}</span>`:''}</span><span class=rd>${esc(reach[k].d)}</span><span class=rx>${esc(reach[k].x)}</span></label>`).join('')}</div>
  <details class=pmore><summary>Port and public address</summary><div class=grid style="margin-top:8px">
   <label>Port</label><input type=number id=cl_port value="${esc(st.port)}" min=1024 max=65535 style="max-width:120px">
   <label>Public address</label><input id=cl_url value="${esc(st.public_url||'')}" placeholder="optional: https://… the address people will use">
   <div class=hint2>Leave empty to use Tailscale's own address. Invitation links are built from it.</div></div></details>
  <div class=sec>Models people may ask</div>${mrows}
  <div style="margin:6px 0"><button class=ghost data-a=addmodel>Add a model</button> <button class=primary data-a=savemodels>Save models</button></div>
  <div class=sec>Restore a project backup</div><div class=note>A backup holds the project's record and its people, but nobody's login: you open it again from here, and they come back with a new invitation or their Orbit account. A project that already exists is never overwritten.</div>
  <div class=grid><label>Backup file</label><input id=rs_path placeholder="~/…/Lab-notebook-p_….orbit-project.zip"><label></label><div><button class=primary id=rs_go>Restore</button></div></div>
  <div class=sec>Join someone else's project</div><div class=note>Paste the invitation link you were given. If you are signed in to your Orbit account, the host is shown that account, and only for that host; otherwise you join as a guest. The project opens in Chrome.</div>
  <div class=grid><label>Link</label><input id=jn_link placeholder="https://… or orbit://join?…"><label>Your name</label><input id=jn_name value="Me" maxlength=40><label></label><div><button class=primary id=jn_go>Join</button></div></div>
  <div class=sec>Import a saved shared chat</div><div class=note>Someone saved a chat from a shared project as an Orbit file: this makes it a new chat of your own. Nothing you already have is changed.</div>
  <div style="margin:6px 0"><input type=file id=cl_file accept=".json,application/json"></div>
  <div class=sec>New project</div><div class=grid>
   <label>Name</label><input id=cl_name placeholder="e.g. Methylation notebook">
   <label>Your name</label><input id=cl_me placeholder="shown to the others" value="Me">
   <label>Working folder</label><input id=cl_dir placeholder="/absolute/path/to/the/folder the models work in">
   <label></label><div><button class=primary data-a=create>Create project</button></div></div>
  <div id=cl_out></div>`;
  wire()};
 const wire=()=>{
  $('#cl_on').onchange=async e=>{const r=await call({op:'configure',enabled:e.target.checked});if(r){st=r;draw()}else e.target.checked=!e.target.checked};
  body.querySelectorAll('input[name=cl_mode]').forEach(r=>r.onchange=async e=>{
   if(e.target.value==='web'){
    const r=await call({op:'configure',mode:'local'});if(!r){draw();return}st=r;let fail=0;
    for(const p of st.projects||[]){if(rel&&rel.projects&&rel.projects[p.id])continue;if(!await call({op:'relay_publish',project:p.id}))fail++}
    rel=await call({op:'relay_status'})||rel;draw();toast(fail?'Could not switch the web link on for '+fail+' project(s): sign in to your Orbit account in Settings, General':'The web link is on for your projects');try{loadShared()}catch(x){}return}
   const r=await call({op:'configure',mode:e.target.value});if(r){st=r;draw()}});
  $('#cl_port').onchange=async e=>{const r=await call({op:'configure',port:+e.target.value});if(r){st=r;draw()}};
  $('#cl_url').onchange=async e=>{const r=await call({op:'configure',public_url:e.target.value.trim()});if(r){st=r;draw()}};
  body.querySelectorAll('button[data-a]').forEach(b=>b.onclick=()=>act(b.dataset.a,b));
  body.querySelectorAll('input[data-a=allowexport]').forEach(c=>c.onchange=async()=>{const r=await call({op:'project_settings',project:c.dataset.p,allow_export:c.checked});if(!r)c.checked=!c.checked;else toast(c.checked?'members may save copies':'members cannot save copies')});
  $('#rs_go').onclick=async()=>{const r=await call({op:'restore_project',path:$('#rs_path').value.trim()});if(r){st=await call({op:'status'})||st;await loadChats();draw();toast('restored '+r.name+' ('+r.events+' events)')}};
  $('#jn_go').onclick=async()=>{const r=await call({op:'join_link',link:$('#jn_link').value.trim(),name:$('#jn_name').value.trim()});if(r)toast(r.signed_in?'joined with your Orbit account; opening it':'joined as a guest; opening it')};
  $('#cl_file').onchange=async e=>{const f=e.target.files[0];if(!f)return;let payload;
   try{payload=JSON.parse(await f.text())}catch(x){toast('that file is not a saved Orbit chat');return}
   const d=await apiPost('/api/chat/import',{payload},'the import');if(d){toast('imported as a new chat: '+d.title);try{loadSessions()}catch(x){}}e.target.value=''}};
 const readModels=()=>[...body.querySelectorAll('[data-m=handle]')].map(h=>{const i=h.dataset.i,g=k=>body.querySelector(`[data-m=${k}][data-i="${i}"]`).value.trim();return{handle:h.value.trim(),id:g('id'),label:g('label'),payer:g('payer'),share_usage:!!body.querySelector(`[data-m=share_usage][data-i="${i}"]`).checked}});
 const act=async(a,b)=>{
  const out=$('#cl_out');
  if(a==='psettings'){openProjectSettings(b.dataset.p,'overview');return}
  if(a==='addmodel'){st.models=readModels().filter(m=>m.handle||m.id);const have=new Set(st.models.map(m=>m.id));const opts=models.filter(m=>!have.has(m.id));
   out.innerHTML=`<div class=sec>Add a model</div><div class=note>Pick one of Orbit's ready models. People then ask it in a shared chat by typing @ and choosing it from the list.</div><input id=am_q placeholder="search the models" style="width:100%"><div id=am_list style="max-height:260px;overflow:auto;margin:6px 0"></div>`;
   const show=()=>{const q=$('#am_q').value.toLowerCase();$('#am_list').innerHTML=opts.filter(m=>!q||(m.label||m.id).toLowerCase().includes(q)||m.id.toLowerCase().includes(q)).slice(0,60).map(m=>`<div class=row style="margin:2px 0"><button class=ghost data-pick="${esc(m.id)}">Add</button> ${esc(m.label||m.id)} <span class=note>${esc(m.id)}</span></div>`).join('')||'<div class=note>No model matches.</div>';
    $('#am_list').querySelectorAll('[data-pick]').forEach(b=>b.onclick=async()=>{const m=opts.find(x=>x.id===b.dataset.pick);let base=(m.label||m.id).toLowerCase().replace(/[^a-z0-9]+/g,' ').trim().split(' ')[0]||'model';if(!/^[a-z]/.test(base))base='m'+base;base=base.slice(0,16);let h=base,n=2;const used=new Set(st.models.map(x=>x.handle.toLowerCase()));while(used.has(h))h=base+n++;
     st.models.push({handle:h,id:m.id,label:m.label||m.id,payer:'the host'});const r=await call({op:'configure',models:st.models});if(r){st=r;draw();toast('added: people can ask it with @'+h)}else{st.models.pop()}})};
   $('#am_q').oninput=show;show();$('#am_q').focus();return}
  if(a==='delmodel'){st.models=readModels();st.models.splice(+b.dataset.i,1);draw();return}
  if(a==='savemodels'){const r=await call({op:'configure',models:readModels()});if(r){st=r;draw();toast('saved')}return}
  if(a==='create'){const r=await call({op:'create',name:$('#cl_name').value,owner_name:$('#cl_me').value,working_dir:$('#cl_dir').value.trim()});if(r){if(webOn()&&st.mode==='local'){await call({op:'relay_publish',project:r.project.id});rel=await call({op:'relay_status'})||rel}st=await call({op:'status'})||st;await loadChats();draw();toast('project created')}return}
  if(a==='guard'){
   const r=await call({op:'guard',project:b.dataset.p});if(!r)return;const g=r.guard;
   out.innerHTML=`<div class=sec>Guard for this project</div><div class=note>A second model reads every risky action before it runs, with the instructions you write below, and can refuse it or send it to a person. It can only make a decision stricter: it can never allow what a person's permissions forbid. If it cannot answer, a person decides.</div>
    <div class=grid><label>Guard</label><div class=sw><input type=checkbox id=gd_on${g.enabled?' checked':''}><span class=note>review actions before they run</span></div>
    <label>Model</label><select id=gd_model>${(r.models.length?r.models:[{id:g.model_id,label:g.model_id||'(no model available)'}]).map(m=>`<option value="${esc(m.id)}"${m.id===g.model_id?' selected':''}>${esc(m.label)}</option>`).join('')}</select>
    <div class=hint2>Pick a model that is not the one doing the work. A model on another machine is better: the local one answers one request at a time.</div>
    <label>Reviews</label><select id=gd_scope><option value=risky${g.scope==='risky'?' selected':''}>risky actions (commands, edits, network, cluster, schedules)</option><option value=all${g.scope==='all'?' selected':''}>every action, reads included</option></select>
    <label>Your rules</label><textarea id=gd_text rows=7 maxlength=4000 style="width:100%">${esc(g.instructions)}</textarea>
    <label></label><div><button class=primary id=gd_save>Save the guard</button></div></div>
    <div class=sec>How questions to a model are taken</div><div class=note>First come first served is the default. Taking turns lets the member who has waited longest go first. Approver says yes first holds every member's question until an approver (you, or anyone you made an approver) agrees; your own questions are never held.</div>
    <select id=tm_mode><option value=free${r.turn_mode==='free'?' selected':''}>First come, first served</option><option value=round_robin${r.turn_mode==='round_robin'?' selected':''}>Take turns between members</option><option value=approve_each${r.turn_mode==='approve_each'?' selected':''}>An approver says yes to each question</option></select> <button class=primary id=tm_save>Save</button>
    <div class=sec>Needs two approvers</div><div class=note>For these kinds of action, one approver is not enough: two different people must say yes, and anyone's no stops it. Only applies to actions that ask for approval in a person's permissions.</div>
    <div id=tp style="margin:6px 0">${[['delete','Deleting files'],['git_push','Pushing to git'],['install','Installing software'],['network','Using the network'],['run_code','Running programs and scripts']].map(([k,l])=>`<label style="display:block"><input type=checkbox data-tp=${k}${(r.two_person||[]).includes(k)?' checked':''}> ${l}</label>`).join('')}</div>
    <button class=primary id=tp_save>Save</button>`;
   $('#tm_save').onclick=async()=>{const d=await call({op:'set_turn_mode',project:b.dataset.p,mode:$('#tm_mode').value});if(d)toast('saved')};
   $('#tp_save').onclick=async()=>{const d=await call({op:'set_two_person',project:b.dataset.p,flags:[...document.querySelectorAll('#tp input:checked')].map(x=>x.dataset.tp)});if(d)toast(d.two_person.length?'two approvers needed for: '+d.two_person.join(', '):'one approver is enough for everything')};
   $('#gd_save').onclick=async()=>{const d=await call({op:'set_guard',project:b.dataset.p,guard:{enabled:$('#gd_on').checked,model_id:$('#gd_model').value,scope:$('#gd_scope').value,instructions:$('#gd_text').value}});if(d)toast(d.guard.enabled?'guard is on':'guard is off')};return}
  if(a==='relay'){
   const show=async()=>{const r=await call({op:'relay_status'});if(!r)return;const pr=r.projects[b.dataset.p];
    out.innerHTML=`<div class=sec>Share on the web</div><div class=note>Normally people need an address of this Mac (Tailscale or the same network). Sharing on the web uses the Orbit service instead: your Orbit opens one outgoing connection to it, and people open a link on <code>${esc(r.service)}</code> and sign in. Nothing on this Mac is opened to the internet, and every permission, approval and sandbox rule still applies. The service passes the traffic along and can see it while it does (it is not end-to-end encrypted yet), and it keeps only the project's id, name and a hash of a secret.</div>`+
     (pr?`<div style="margin:8px 0">${pr.state==='connected'?'<b style="color:var(--ok,#2e9e5b)">Connected</b>':pr.state==='connecting'?'Connecting…':'<b style="color:var(--bad,#c33)">'+esc(pr.state)+'</b>'}${pr.error?' · '+esc(pr.error):''} <span class=note>${pr.served} requests served</span><div style="margin-top:6px"><code style="word-break:break-all">${esc(pr.link)}</code> <button class=ghost id=rl_copy>Copy the link</button></div><div class=note>Invitations you make now are links on this address.</div>
       <button class=ghost id=rl_off style="margin-top:6px">Stop sharing on the web</button></div>`:`<div style="margin:8px 0"><button class=primary id=rl_on>Share this project on the web</button> <span class=note>needs you to be signed in to your Orbit account (Settings > General)</span></div>`);
    const on=$('#rl_on');if(on)on.onclick=async()=>{const x=await call({op:'relay_publish',project:b.dataset.p});if(x){toast('shared on the web');setTimeout(show,1500)}};
    const off=$('#rl_off');if(off)off.onclick=async()=>{if(!confirm('Stop sharing on the web? Links on the service stop working; people who used them lose access through them.'))return;const x=await call({op:'relay_unpublish',project:b.dataset.p});if(x){toast('stopped');show()}};
    const cp_=$('#rl_copy');if(cp_)cp_.onclick=()=>navigator.clipboard.writeText(pr.link).then(()=>toast('link copied'),()=>toast('select it and copy by hand'))};
   await show();return}
  if(a==='check'){const r=await call({op:'check',project:b.dataset.p});if(!r)return;
   out.innerHTML=`<div class=sec>Check</div>`+r.checks.map(c=>`<div style="margin:4px 0"><b style="color:${c.ok?'var(--ok,#2e9e5b)':'var(--bad,#c33)'}">${c.ok?'✓':'✗'}</b> ${esc(c.name)} <span class=note>${esc(c.detail)}</span></div>`).join('');return}
  if(a==='people'){
   const r=await call({op:'people',project:b.dataset.p});if(!r)return;const P0=b.dataset.p;
   const act=async(m,action,value)=>{const d=await call({op:'member_action',project:P0,member:m,action,value});if(d){toast('done');act2()}};
   const act2=()=>b.click();
   out.innerHTML=`<div class=sec>People</div>`+r.members.map(m=>`<div class=card style="margin:6px 0;padding:8px"><b>${esc(m.name)}</b> <span class=note>${m.owner?'host':esc(m.role)}${m.state==='muted'?' · muted':''}${m.account?' · Orbit account':''}</span>
     ${m.owner?'':`<div style="margin-top:4px;display:flex;gap:6px;flex-wrap:wrap;align-items:center"><select data-role="${esc(m.id)}">${r.roles.map(x=>`<option${x===m.role?' selected':''}>${esc(x)}</option>`).join('')}</select>
      <button class=ghost data-mm="${esc(m.id)}" data-act=${m.state==='muted'?'unmute':'mute'}>${m.state==='muted'?'Unmute':'Mute'}</button>
      <input type=number min=0 data-hr="${esc(m.id)}" style="width:90px" placeholder="per hour" value="${m.budget.turns_per_hour??''}" title="questions to models per hour (empty = no limit)"><button class=ghost data-save-hr="${esc(m.id)}">Set limit</button>
      <button class=ghost data-mm="${esc(m.id)}" data-act=remove style="color:var(--bad,#c33)">Remove</button></div>
      <details style="margin-top:6px"><summary class=note>Files this person may use…</summary><div style="margin:6px 0" data-fp="${esc(m.id)}">
       ${[['files_download','Download files the models make in chats, and files attached to chats'],['files_browse','See and download files in the project folder (only the folders below)'],['files_edit','Edit text files in the project folder (only where they may write)'],['files_upload_chat','Attach files to chats'],['files_upload_dir','Put files into the project folder (only where they may write)']].map(([k,l])=>`<label style="display:block"><input type=checkbox data-ff=${k}${m.files[k]?' checked':''}> ${l}</label>`).join('')}
       <div class=note style="margin-top:6px">Folders they may read (one per line; a relative one is inside the project folder):</div><textarea data-fr rows=2 style="width:100%">${esc((m.read_paths||[]).join('\n'))}</textarea>
       <div class=note>Folders they may write to:</div><textarea data-fw rows=2 style="width:100%">${esc((m.write_paths||[]).join('\n'))}</textarea>
       <div class=note>Folders they may never touch:</div><textarea data-fd rows=1 style="width:100%">${esc((m.deny_paths||[]).join('\n'))}</textarea>
       <button class=primary data-save-files="${esc(m.id)}" style="margin-top:6px">Save file settings</button></div></details>`}</div>`).join('')
    +`<div class=sec>Open invitations</div>`+(r.invites.length?r.invites.map(i=>`<div class=row style="margin:4px 0">${esc(i.role)} · ${i.uses_left==null?'any number of uses':i.uses_left+' use'+(i.uses_left===1?'':'s')+' left'}${i.account_required?' · needs an Orbit account':''} <button class=ghost data-revoke="${esc(i.id)}">Cancel it</button></div>`).join(''):'<div class=note>None.</div>');
   out.querySelectorAll('[data-role]').forEach(x=>x.onchange=()=>act(x.dataset.role,'role',x.value));
   out.querySelectorAll('[data-mm]').forEach(x=>x.onclick=()=>{if(x.dataset.act==='remove'&&!confirm('Remove this person? They lose access at once and anything they started stops.'))return;act(x.dataset.mm,x.dataset.act)});
   out.querySelectorAll('[data-save-hr]').forEach(x=>x.onclick=()=>{const v=out.querySelector(`[data-hr="${x.dataset.saveHr}"]`).value;act(x.dataset.saveHr,'budget',{turns_per_hour:v===''?null:+v})});
   out.querySelectorAll('[data-save-files]').forEach(x=>x.onclick=()=>{const fp=out.querySelector(`[data-fp="${x.dataset.saveFiles}"]`),lines=sel=>fp.querySelector(sel).value.split('\n').map(v=>v.trim()).filter(Boolean),v={read_paths:lines('[data-fr]'),write_paths:lines('[data-fw]'),deny_paths:lines('[data-fd]')};fp.querySelectorAll('[data-ff]').forEach(c=>v[c.dataset.ff]=c.checked);act(x.dataset.saveFiles,'files',v)});
   out.querySelectorAll('[data-revoke]').forEach(x=>x.onclick=()=>act(x.dataset.revoke,'revoke_invite'));return}
  if(a==='backup'){const r=await call({op:'backup_project',project:b.dataset.p});if(r)toast('backed up ('+r.events+' events): '+r.path.split('/').slice(-3).join('/'));return}
  if(a==='changes'){
   const r=await call({op:'recent_changes',project:b.dataset.p});if(!r)return;
   const line=c=>[['created','created'],['modified','changed'],['deleted','removed']].filter(([k])=>(c[k]||[]).length).map(([k,w])=>w+' '+c[k].map(esc).join(', ')).join('; ');
   out.innerHTML=`<div class=sec>Recent file changes</div><div class=note>Which answers changed files in the project folder, and who asked for them. Undo puts back what Orbit's file tools edited or created in one answer; it does not reverse what a command did, and it is only kept while Orbit stays open. It refuses if a file has changed since.</div>`+(r.changes.length?r.changes.map(c=>`<div class=row style="margin:8px 0"><div><b>${esc(c.model||'model')}</b> for ${esc(c.asked_by_name||'someone')}: ${line(c)||'files'}${c.more?` (and ${c.more} more)`:''}</div>${c.can_undo?`<button class=ghost data-undo="${esc(String(c.turn))}">Undo this answer's edits</button>`:'<span class=note>cannot be undone</span>'}</div>`).join(''):'<div class=note>No answer has changed files yet.</div>');
   out.querySelectorAll('[data-undo]').forEach(x=>x.onclick=async()=>{const d=await call({op:'undo_turn',project:b.dataset.p,turn:+x.dataset.undo});if(!d)return;if(d.undone){toast('undone');act('changes',b)}else toast(d.lines.join(' · ')||'nothing was undone')});return}
  if(a==='copychat'){const r=await call({op:'copy_chat',project:b.dataset.p,chat:b.dataset.c});if(r){toast('copied into a new chat of yours: '+r.title);try{loadSessions()}catch(x){}}return}
  if(a==='rmchat'){if(!confirm(`Remove "${b.dataset.n}" from the project?\n\nNobody in the project can read it afterwards and anything answering in it stops. Your own chat on this Mac is not touched.`))return;
   const r=await call({op:'remove_chat',project:b.dataset.p,chat:b.dataset.c});if(r){await loadChats();draw();toast('removed from the project')}return}
  if(a==='sharechat'){
   const r=await call({op:'local_chats'});if(!r)return;
   out.innerHTML=`<div class=sec>Share a chat from this Mac</div><div class=grid><label>Chat</label><select id=sc_pick>${r.chats.map(c=>`<option value="${esc(c.id)}">${esc(c.title)}${c.n?` (${c.n} messages)`:''}</option>`).join('')||'<option value="">no chats</option>'}</select>
    <label></label><div><button class=ghost id=sc_prev>Preview what would be shared</button></div></div><div id=sc_res></div>`;
   $('#sc_prev').onclick=async()=>{const sid=$('#sc_pick').value;if(!sid)return;const v=await call({op:'share_preview',project:b.dataset.p,chat:sid});if(!v)return;
    const warn=(v.warnings||[]);const kinds=[...new Set(warn.map(w=>w.kind))];
    $('#sc_res').innerHTML=`<div class=card style="padding:10px;margin:8px 0"><b>${esc(v.title)}</b>
     <div class=note>${v.user} of your messages and ${v.assistant} answers will be copied into the project as a new chat marked "shared from this Mac". Everyone in the project will be able to read all of it, and the models there will see it as the conversation so far.</div>
     <div class=note>Not copied: ${v.tools_skipped} tool calls and results${v.images_skipped?`, ${v.images_skipped} images`:''}. Your chat on this Mac stays as it is, and you can remove the shared copy from the project at any time.${v.dropped_oldest?` Only the latest ${v.messages} messages are shared (${v.dropped_oldest} older ones are left out).`:''}</div>
     ${warn.length?`<div class=err style="margin-top:6px">This chat looks like it contains ${esc(kinds.join(', '))} (in ${warn.length} place${warn.length===1?'':'s'}). Everyone in the project could read it.<label style="display:block;margin-top:4px"><input type=checkbox id=sc_ok> Share it anyway</label></div>`:''}
     <div style="margin-top:8px"><button class=primary id=sc_go>Share this chat</button></div></div>`;
    $('#sc_go').onclick=async()=>{if(warn.length&&!$('#sc_ok').checked){toast('tick "Share it anyway" first, or pick another chat');return}
     const d=await call({op:'share_chat',project:b.dataset.p,chat:sid,confirm_secrets:!!warn.length});if(d){await loadChats();draw();toast('shared: '+d.messages+' messages')}}};return}
  if(a==='open'){const r=await call({op:'open',project:b.dataset.p,launch:true});if(r)toast(r.opened?'opened in Chrome':'could not open Chrome: use Copy link below');return}
  if(a==='panic'){if(!confirm('Stop every running answer and stop everyone but you from writing until you lift the freeze?'))return;const r=await call({op:'panic',project:b.dataset.p});if(r){st=await call({op:'status'})||st;await loadChats();await loadDash();draw()}return}
  if(a==='resume'){const r=await call({op:'resume',project:b.dataset.p});if(r){st=await call({op:'status'})||st;await loadDash();draw()}return}
  if(a==='quickinvite'){
   const pid=b.dataset.p,box=document.getElementById('inv_'+pid);
   if(box.dataset.open==='1'){box.hidden=true;box.dataset.open='0';return}
   box.hidden=false;box.dataset.open='1';let prev=null;
   box.innerHTML=`<div class=invrow><label>They can <select class=iq_role><option value=viewer>only read</option><option value=commenter>read and write in the chat</option><option value=editor selected>work with the models</option><option value=admin>also manage people</option></select></label><label>Works for <select class=iq_days><option value=1>1 day</option><option value=7 selected>7 days</option><option value=30>30 days</option></select></label><label class=sw><input type=checkbox class=iq_acc> Orbit account only</label></div><div class=iq_res aria-live=polite></div>`;
   const res=box.querySelector('.iq_res');
   const make=async()=>{
    res.innerHTML='<div class=note>Making the link…</div>';
    if(prev){await call({op:'member_action',project:pid,member:prev,action:'revoke_invite'});prev=null}
    const days=+box.querySelector('.iq_days').value;
    const r=await call({op:'invite',project:pid,role:box.querySelector('.iq_role').value,uses:1,account_required:box.querySelector('.iq_acc').checked,expires_in:days*86400});
    if(!r){res.innerHTML='';return}
    prev=r.id;const local=/127\.0\.0\.1|localhost/.test(r.link);
    res.innerHTML=`<div class=note>Send this link to one person. It works once, for ${days} day${days===1?'':'s'}, and you can see and remove anyone who joins.</div><div class=linkrow><input readonly value="${esc(r.link)}" aria-label="Invitation link"><button class=primary data-k=copy>Copy link</button><button class=ghost data-k=revoke>Cancel this link</button></div><div class=qrbox></div>${local?'<div class=note style="color:var(--warn)">This link only works on this Mac. Choose the Orbit web link, Tailscale or the local network under "Who can reach your projects" for other people.</div>':''}`;
    const c=window.orbitQRCanvas&&window.orbitQRCanvas(r.link,200);const qb=res.querySelector('.qrbox');
    if(c){qb.append(c);const t=document.createElement('div');t.className='note';t.textContent='Scan with a phone camera to open it there.';qb.append(t)}
    res.querySelector('[data-k=copy]').onclick=()=>{navigator.clipboard.writeText(r.link).then(()=>toast('invitation link copied'),()=>{res.querySelector('input').select();toast('select the link and copy it')})};
    res.querySelector('[data-k=revoke]').onclick=async()=>{if(await call({op:'member_action',project:pid,member:prev,action:'revoke_invite'})){prev=null;res.innerHTML='<div class=note>That link no longer works.</div>';await loadDash()}};
    await loadDash()};
   box.querySelectorAll('select,input').forEach(x=>x.onchange=make);await make();return}
  if(a==='invite'){
   out.innerHTML=`<div class=sec>Invite someone</div><div class=grid><label>Can</label><select id=iv_role><option value=viewer>only read</option><option value=commenter>read and write in the chat</option><option value=editor selected>work with the models and edit the project's files</option><option value=admin>also manage people</option></select>
    <label>Link works</label><select id=iv_uses><option value=1>once</option><option value=5>5 times</option></select>
    <label>Questions to models</label><div class=sw><input type=number id=iv_hr min=0 style="width:80px" placeholder="no limit"><span class=note>at most this many per hour for this person (leave empty for no limit)</span></div>
    <label>Files</label><div><label style="display:block"><input type=checkbox id=iv_fd checked> download what the models make</label><label style="display:block"><input type=checkbox id=iv_fb> browse and download the project folder</label><label style="display:block"><input type=checkbox id=iv_fe> edit text files there</label><label style="display:block"><input type=checkbox id=iv_fc checked> attach files to chats</label><label style="display:block"><input type=checkbox id=iv_fu> put files into the project folder</label><div class=hint2>The role sets these to start with; this overrides them for this link. You can change them later under People.</div></div>
    <label>Account</label><div class=sw><input type=checkbox id=iv_acc><span class=note>only people signed in with an Orbit account (Orbit on their Mac shows it for them; a guest in a browser cannot join)</span></div>
    <label></label><div><button class=primary id=iv_go>Make the link</button></div></div><div id=iv_res></div>`;
   $('#iv_go').onclick=async()=>{const r=await call({op:'invite',project:b.dataset.p,role:$('#iv_role').value,uses:+$('#iv_uses').value,account_required:$('#iv_acc').checked,files:{files_download:$('#iv_fd').checked,files_browse:$('#iv_fb').checked,files_edit:$('#iv_fe').checked,files_upload_chat:$('#iv_fc').checked,files_upload_dir:$('#iv_fu').checked},budget:$('#iv_hr').value===''?undefined:{turns_per_hour:+$('#iv_hr').value},expires_in:7*86400});if(!r)return;
    const box=$('#iv_res');box.innerHTML=`<div class=note>Send this to them. It works for 7 days, as many times as you chose, and you can see and remove anyone who joins.</div>
     <input readonly value="${esc(r.link)}" style="width:100%"><div style="margin-top:6px"><button class=ghost id=iv_copy>Copy link</button></div>
     <div class=note style="margin-top:6px">Reachable at ${esc(r.link.split('/join')[0])}. ${/127\.0\.0\.1|localhost/.test(r.link)?'This is this Mac only: switch "Who can reach it" to Tailscale or the local network for other people.':''}</div>`;
    $('#iv_copy').onclick=()=>{navigator.clipboard.writeText(r.link).then(()=>toast('copied'),()=>toast('select the link and copy it'))}}}};
 draw()}
// Settings → Helpers: other agents (Claude Science, Claude Code, Codex, anything that speaks MCP) hand work to Orbit's cheaper models, watch HPC jobs through Orbit and
// hold conversations with an Orbit chat. Everything they send lands in the inbox here, and changes wait for your yes. Off until turned on.
async function renderHelpers(body,gen){
 const call=async d=>{try{const r=await fetch('/api/sciencebridge',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(d)});const j=await r.json().catch(()=>({}));if(!r.ok){toast((j.error||'error '+r.status).toString().slice(0,140));return null}return j}catch(e){return null}};
 let st=await call({op:'status'});if(!st||gen!==RENDER_GEN)return;
 let timer=null;const live=()=>document.body.contains(body)&&body.querySelector('#hp_root');
 const ago=t=>{if(!t)return '';const s=Math.max(0,Date.now()/1000-t);return s<90?'just now':s<5400?Math.round(s/60)+' min ago':s<172800?Math.round(s/3600)+' h ago':Math.round(s/86400)+' days ago'};
 const cp=(t,m)=>navigator.clipboard.writeText(t).then(()=>toast(m),()=>toast('select it and copy by hand'));
 const pill=x=>`<span class=note style="border:1px solid var(--line,#ccc);border-radius:10px;padding:0 6px">${esc(x)}</span>`;
 body.innerHTML=`<div id=hp_root><div class=sec>Helpers</div><div class=note>Other agents (Claude Science, Claude Code, Codex, any app that speaks MCP) can hand Orbit work to do on cheaper models, have Orbit watch HPC jobs, and hold a conversation with an Orbit chat. Everything they send shows up below, and anything that changes files waits for your yes. It answers only on this Mac and only with an app's own token.</div>
  <label style="display:block;margin:8px 0"><input type=checkbox id=hp_on${st.enabled?' checked':''}> Turn it on <span class=note>${st.enabled?(st.running?'· running at '+esc(st.url):'· not running'):''}</span></label>
  <div id=hp_main></div></div>`;
 $('#hp_on').onchange=async e=>{const r=await call({op:'configure',enabled:e.target.checked});if(r){st=r;main()}else e.target.checked=!e.target.checked};
 const main=async()=>{
  const box=$('#hp_main');if(!box)return;
  if(!st.enabled){box.innerHTML='<div class=note>Turn it on to see the inbox and connect an app.</div>';return}
  box.innerHTML=`<div class=sec>Inbox <span id=hp_badge></span></div><div id=hp_inbox class=note>Loading…</div>
   <div class=sec>Apps</div><div id=hp_apps></div>
   <div class=sec>Connect an app</div><div id=hp_connect></div>`;
  apps();connect();await inbox();
  clearInterval(timer);timer=setInterval(()=>{if(!live()){clearInterval(timer);return}inbox()},4000)};
 // ---- the inbox
 let open={};
 const inbox=async()=>{
  const r=await call({op:'inbox'});const box=$('#hp_inbox');if(!r||!box)return;
  const jobs=r.jobs||[],threads=(r.threads||[]).filter(t=>t.state==='open'),wait=jobs.filter(j=>j.state==='waiting');
  $('#hp_badge').innerHTML=wait.length?`<b style="color:var(--bad,#c33)">${wait.length} waiting for your yes</b>`:'';
  const stats=Object.entries(r.stats||{}),tok=stats.reduce((a,[,v])=>a+v.tokens,0),n=stats.reduce((a,[,v])=>a+v.jobs,0);
  let h='';
  h+=wait.map(j=>`<div class=card style="margin:6px 0;padding:8px;border:1px solid var(--bad,#c33)"><b>${esc(j.app)}</b> wants a helper to change files${j.workdir?' in <code>'+esc(j.workdir)+'</code>':''}<div style="margin:4px 0;white-space:pre-wrap">${esc(j.task)}</div>
    <button class=primary data-yes="${esc(j.id)}">Allow</button> <button class=ghost data-no="${esc(j.id)}">Don't allow</button> <span class=note>${ago(j.created)}</span></div>`).join('');
  h+=threads.length?`<div class=note style="margin-top:8px">Conversations</div>`+threads.map(t=>`<div class=row style="margin:4px 0;display:flex;gap:8px;align-items:center;flex-wrap:wrap"><b>${esc(t.app)}</b> · ${esc(t.name)} ${pill(t.role)} <span class=note>${esc(t.model||'')} · ${t.rounds}/${t.max_rounds} messages${t.unread?' · <b>'+t.unread+' unread</b>':''} · ${ago(t.last)}</span>
    <button class=ghost data-chat="${esc(t.sid)}">Open the chat</button>${t.rounds>=t.max_rounds?` <button class=ghost data-more="${esc(t.id)}">Allow 30 more</button>`:''} <button class=ghost data-end="${esc(t.id)}">End</button></div>`).join(''):'';
  const rest=jobs.filter(j=>j.state!=='waiting');
  h+=`<div class=note style="margin-top:8px">Jobs${n?` · last 7 days: ${n} handled by Orbit's models, ${tok.toLocaleString()} tokens (${stats.map(([m,v])=>esc(m)+' '+v.jobs).join(', ')})`:''}</div>`;
  h+=rest.length?rest.slice(0,40).map(j=>{const o=open[j.id],dur=j.ended&&(j.started||j.created)?Math.max(1,Math.round(j.ended-(j.started||j.created)))+' s':'';
   return `<div style="margin:4px 0"><div style="display:grid;grid-template-columns:auto auto minmax(0,1fr) auto;gap:8px;align-items:baseline;cursor:pointer" data-tog="${esc(j.id)}">${pill(j.state)} <b>${esc(j.app)}</b> <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(j.label||j.task)}</span> <span class=note style="white-space:nowrap">${esc(j.model||j.tier)}${dur?' · '+dur:''}${j.tokens?' · '+j.tokens.toLocaleString()+' tokens':''}${j.confidence?' · confidence '+esc(j.confidence):''} · ${ago(j.created)}</span></div>
    ${o?`<div style="margin:4px 0 8px 12px"><div class=note style="white-space:pre-wrap">${esc(j.task)}</div>${j.answer?`<pre style="white-space:pre-wrap;max-height:240px;overflow:auto">${esc(j.answer)}</pre>`:''}${j.note?`<div class=note>${esc(j.note)}</div>`:''}
     ${j.state==='running'?`<button class=ghost data-cancel="${esc(j.id)}">Stop</button> `:''}${j.sid?`<button class=ghost data-chat="${esc(j.sid)}">Open the chat</button> `:''}${j.answer?`<button class=ghost data-copy="${esc(j.id)}">Copy the answer</button>`:''}</div>`:''}</div>`}).join(''):'<div class=note>Nothing yet. When an app hands Orbit work, it appears here.</div>';
  h+=rest.length?`<div style="margin-top:6px"><button class=ghost id=hp_forget>Clear finished</button></div>`:'';
  box.innerHTML=h;
  box.querySelectorAll('[data-yes]').forEach(b=>b.onclick=async()=>{const d=await call({op:'decide',job:b.dataset.yes,approve:true});if(d&&d.ok===false)toast(d.error||'could not start');inbox()});
  box.querySelectorAll('[data-no]').forEach(b=>b.onclick=async()=>{await call({op:'decide',job:b.dataset.no,approve:false});inbox()});
  box.querySelectorAll('[data-tog]').forEach(b=>b.onclick=()=>{open[b.dataset.tog]=!open[b.dataset.tog];inbox()});
  box.querySelectorAll('[data-cancel]').forEach(b=>b.onclick=async()=>{await call({op:'cancel',job:b.dataset.cancel});inbox()});
  box.querySelectorAll('[data-chat]').forEach(b=>b.onclick=()=>{closeModal();openChatFromHome(b.dataset.chat)});
  box.querySelectorAll('[data-copy]').forEach(b=>b.onclick=()=>{const j=jobs.find(x=>x.id===b.dataset.copy);if(j)cp(j.answer,'copied')});
  box.querySelectorAll('[data-more]').forEach(b=>b.onclick=async()=>{await call({op:'thread_more',thread:b.dataset.more});inbox()});
  box.querySelectorAll('[data-end]').forEach(b=>b.onclick=async()=>{if(confirm('End this conversation? The chat stays in Orbit, archived.')){await call({op:'thread_end',thread:b.dataset.end});inbox()}});
  const f=$('#hp_forget');if(f)f.onclick=async()=>{await call({op:'forget'});inbox()}};
 // ---- the apps
 const apps=()=>{
  const box=$('#hp_apps');if(!box)return;
  box.innerHTML=st.clients.map(c=>`<div class=card style="margin:8px 0;padding:10px" data-app="${esc(c.id)}"><div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap"><input data-f=name value="${esc(c.name)}" maxlength=40 style="width:170px"> <span class=note>${c.last_seen?'last heard '+ago(c.last_seen):'not connected yet'} · ${c.jobs} jobs</span></div>
    <div class=grid style="margin-top:6px">
     <label>Changes</label><select data-f=approval><option value=writes${c.approval==='writes'?' selected':''}>ask me before anything that changes files</option><option value=all${c.approval==='all'?' selected':''}>ask me before every job</option><option value=none${c.approval==='none'?' selected':''}>never ask (only in the folders below)</option></select>
     <label>Orbit actions</label><div><select data-f=actions><option value=off${c.actions!=='ask'?' selected':''}>off: it cannot touch my chats, Crew, shared projects or cluster models</option><option value=ask${c.actions==='ask'?' selected':''}>on: it may ask, and nothing happens until I say yes here</option></select><div class=hint2>Lets this app look at the names of your chats, Crew runs, shared projects and cluster models, and ask to read or write a chat, start a Crew run, invite someone or start a cluster model. Every change, and every read of a chat's text, appears in the inbox above and waits for you.</div></div>
     <label>Tell me</label><select data-f=notify><option value=long${c.notify==='long'?' selected':''}>when a long job finishes</option><option value=always${c.notify==='always'?' selected':''}>when every job finishes</option><option value=never${c.notify==='never'?' selected':''}>never</option></select>
     <label>Folders</label><div><textarea data-f=workdirs rows=2 style="width:100%" placeholder="one folder per line: where its helpers may work">${esc((c.workdirs||[]).join('\n'))}</textarea>${st.suggest_workdir?`<div class=hint2><a href=# data-ws="${esc(c.id)}">add ${esc(st.suggest_workdir)}</a></div>`:''}</div>
     <label>Limits</label><div class=hplim>${[['max_running','running at once',60],['max_per_day','jobs a day',70],['max_thread_messages_per_day','conversation messages a day',70],['thread_rounds','messages in one conversation before you allow more',60]].map(([k,t,w])=>`<div style="margin:3px 0">at most <input type=number data-f=${k} min=1 value="${c[k]||''}" ${c[k]===0?'disabled':''} style="width:${w}px"> ${t} <label style="white-space:nowrap;margin-left:6px"><input type=checkbox data-nl=${k} ${c[k]===0?'checked':''}> no limit</label></div>`).join('')}</div>
     <label>Conversation model</label><input data-f=thread_model value="${esc(c.thread_model||'')}" placeholder="empty: a standard model of yours" style="width:100%"></div>
    <div style="margin-top:6px;display:flex;gap:6px;flex-wrap:wrap"><button class=primary data-save="${esc(c.id)}">Save</button><button class=ghost data-ctok="${esc(c.id)}">Copy token</button><button class=ghost data-ctoken-url="${esc(c.id)}">Copy address with token</button><button class=ghost data-newtok="${esc(c.id)}">New token</button>${st.clients.length>1?`<button class=ghost data-rm="${esc(c.id)}" style="color:var(--bad,#c33)">Remove</button>`:''}</div></div>`).join('')+
   `<div style="margin:6px 0"><input id=hp_new placeholder="Another app's name, e.g. Claude Code" maxlength=40 style="width:260px"> <button class=ghost id=hp_add>Add an app</button></div>`;
  const cl=id=>st.clients.find(c=>c.id===id);
  box.querySelectorAll('[data-nl]').forEach(cb=>cb.onchange=()=>{const n=cb.closest('div').querySelector(`[data-f=${cb.dataset.nl}]`);n.disabled=cb.checked;if(!cb.checked&&!n.value)n.value=1});
  box.querySelectorAll('[data-save]').forEach(b=>b.onclick=async()=>{const el_=box.querySelector(`[data-app="${b.dataset.save}"]`),g=k=>el_.querySelector(`[data-f=${k}]`).value;
   const r=await call({op:'configure',client:b.dataset.save,settings:{name:g('name'),approval:g('approval'),actions:g('actions'),notify:g('notify'),workdirs:g('workdirs').split('\n').map(x=>x.trim()).filter(Boolean),...Object.fromEntries(['max_running','max_per_day','max_thread_messages_per_day','thread_rounds'].map(k=>[k,el_.querySelector(`[data-nl=${k}]`).checked?0:Math.max(1,+g(k)||1)])),thread_model:g('thread_model').trim()}});
   if(r){st=r;apps();connect();toast('saved')}});
  box.querySelectorAll('[data-ctok]').forEach(b=>b.onclick=()=>cp(cl(b.dataset.ctok).token,'token copied'));
  box.querySelectorAll('[data-ctoken-url]').forEach(b=>b.onclick=()=>cp(st.url+'/'+cl(b.dataset.ctokenUrl).token,'address with token copied (keep it private)'));
  box.querySelectorAll('[data-newtok]').forEach(b=>b.onclick=async()=>{if(!confirm('Make a new token? The old one stops working and that app needs the new one.'))return;const r=await call({op:'configure',new_token:b.dataset.newtok});if(r){st=r;apps();toast('new token')}});
  box.querySelectorAll('[data-rm]').forEach(b=>b.onclick=async()=>{if(!confirm('Remove this app? Its token stops working. Its past jobs stay in the inbox.'))return;const r=await call({op:'configure',remove_client:b.dataset.rm});if(r){st=r;apps();connect()}});
  box.querySelectorAll('[data-ws]').forEach(a=>a.onclick=e=>{e.preventDefault();const t=box.querySelector(`[data-app="${a.dataset.ws}"] [data-f=workdirs]`);t.value=(t.value.trim()+'\n'+st.suggest_workdir).trim()});
  $('#hp_add').onclick=async()=>{const n=$('#hp_new').value.trim();if(!n)return;const r=await call({op:'configure',add_client:n});if(r){st=r;apps();connect()}}};
 // ---- how to connect
 const connect=()=>{
  const box=$('#hp_connect');if(!box)return;
  const rm=st.remote||{on:false};
  box.innerHTML=`<div class=note><b>Claude Science's sandbox cannot reach this Mac's local addresses</b>, so a local command or a 127.0.0.1 address does not work from it. Use <b>Remote</b> with an address on the Orbit service instead: Orbit opens one outgoing connection to the service (as shared projects do), and the service passes the app's calls to it. The address holds the app's own token, so keep it private; "New token" under the app replaces it.</div>
   <div style="margin:6px 0">${rm.on?`<b style="color:${rm.state==='connected'?'var(--ok,#2e9e5b)':'var(--bad,#c33)'}">${rm.state==='connected'?'Connected to the service':esc(rm.state)}</b>${rm.error?' · '+esc(rm.error):''} <button class=ghost id=hp_roff>Stop allowing access through the service</button>`:`<button class=primary id=hp_ron>Allow access through the Orbit service</button> <span class=note>needs you signed in to your Orbit account (Settings > General)</span>`}</div>
   ${rm.on?`<div class=note>In Claude Science: Customize, Connectors, add, <b>Remote</b>, name it <code>orbit</code>, paste the address for that app (button below), leave the other boxes empty, Add, then start a new chat. Tool calls through the service wait at most about 85 seconds at a time, so long waits come back and are called again.</div>
   <div style="margin:6px 0">${st.clients.map(c=>`<div style="margin:3px 0"><button class=ghost data-rurl="${esc(c.id)}">Copy the remote address for ${esc(c.name)}</button></div>`).join('')}</div>`:''}
   <div class=note style="margin-top:8px">Other ways, for agents whose sandbox allows them: a local command on this Mac, <code>${esc(st.stdio_command)}</code> (with the environment variables <code>ORBIT_HELPERS_URL</code> and <code>ORBIT_HELPERS_TOKEN</code> if it cannot read Orbit's settings), or the local address <code>${esc(st.url)}</code> with the header <code>Authorization: Bearer &lt;its token&gt;</code>. ${st.launcher&&st.launcher.can_install?'<button class=ghost id=hp_inst>'+(st.launcher.installed?'Update the installed launcher':'Install the launcher in '+esc(st.launcher.path))+'</button>':''}</div>
   <div class=note>For a second app, add <code>--app "Its name"</code> to the end of the command. Claude Code: <code>claude mcp add orbit -- ${esc(st.stdio_command)} --app "Claude Code"</code>. An agent that does accept a local address can use <code>${esc(st.url)}</code> with the header <code>Authorization: Bearer &lt;its token&gt;</code> ("Copy token" above).</div>
   <div style="margin:6px 0"><button class=ghost id=hp_cu>Copy the address</button> <button class=ghost id=hp_test>Show the models it would use</button><pre id=hp_out class=note style="white-space:pre-wrap"></pre></div>
   <div class=note style="margin-top:8px"><b>Recommended: give the app the skill.</b> It is a small folder (instructions plus a few reference pages the agent reads only when it needs them) with no token in it. Install it where the agent keeps its skills, then start a new chat in that app.</div>
   <div id=hp_skill style="margin:6px 0" class=note>Looking for installed agents…</div>
   <div class=note>Or, for an agent without skills, the same instructions as one block to paste into its custom instructions:</div>
   <textarea rows=8 style="width:100%" readonly>${esc(st.instructions||'')}</textarea><div><button class=primary id=hp_ci>Copy the instructions</button></div>`;
  const ron=$('#hp_ron');if(ron)ron.onclick=async()=>{const r=await call({op:'relay_on'});if(r){st=r;connect();setTimeout(async()=>{st=await call({op:'status'})||st;connect()},2500);toast('allowed; connecting')}};const roff=$('#hp_roff');if(roff)roff.onclick=async()=>{if(!confirm('Stop allowing access through the service? Anything connected that way stops working.'))return;const r=await call({op:'relay_off'});if(r){st=r;connect()}};box.querySelectorAll('[data-rurl]').forEach(b=>b.onclick=()=>{const c=st.clients.find(x=>x.id===b.dataset.rurl);cp(st.remote.base+'/'+c.token,'address copied (it holds the token: keep it private)')});const hi=$('#hp_inst');if(hi)hi.onclick=async()=>{const r=await call({op:'install_launcher'});if(r){st=await call({op:'status'})||st;connect();toast('installed in '+r.path)}};$('#hp_cu').onclick=()=>cp(st.url,'address copied');$('#hp_ci').onclick=()=>cp(st.instructions,'instructions copied');
  (async()=>{const sk=await call({op:'skill_status'});const h=$('#hp_skill');if(!h)return;if(!sk){h.textContent='';return}
   h.innerHTML=(sk.targets.length?sk.targets.map(t=>`<div style="margin:3px 0"><button class=primary data-inst="${esc(t.id)}">${t.ours?'Update':t.installed?'Already a folder named orbit-helpers':'Install'} for ${esc(t.name)}</button> <span class=note>${esc(t.dir)}${t.ours?' · installed v'+esc(t.version):''}</span></div>`).join(''):'<div class=note>No agent with a skills folder was found on this Mac.</div>')+
    `<div style="margin:3px 0"><button class=ghost id=hp_zip>Save as a zip (for another agent or computer)</button> <span class=note>v${esc(sk.version)} · ${sk.files.length} files</span></div>`;
   h.querySelectorAll('[data-inst]').forEach(b=>b.onclick=async()=>{const r=await call({op:'skill_install',target:b.dataset.inst});if(r)toast('installed in '+r.path+'; start a new chat in that app')});
   $('#hp_zip').onclick=async()=>{const r=await call({op:'skill_zip'});if(r)toast('saved '+r.path)}})();
  $('#hp_test').onclick=async()=>{const r=await call({op:'test'});$('#hp_out').textContent=r?r.models:''}};
 main()}
// Settings → General: chats from the Claude Science app on this Mac, copied into Orbit as new chats to carry on in (read-only on its side)
async function drawScience(body){
 if(!body)return;
 const get=async d=>{try{const r=await fetch('/api/claudescience',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(d)});const j=await r.json().catch(()=>({}));if(!r.ok){toast((j.error||'error '+r.status).toString().slice(0,140));return null}return j}catch(e){return null}};
 const st=await get({op:'list'});if(!st||!st.found||!document.body.contains(body))return;
 const box=el(`<div><div class=sec>Claude Science chats</div><div class=note>Claude Science is installed on this Mac. Pick chats to copy into Orbit as new chats you can carry on in. Only what you asked and what Claude answered is copied (not its tool calls or hidden reasoning), and nothing in Claude Science is changed.</div>
  <div id=cs_list style="max-height:240px;overflow:auto;margin:6px 0"></div><div><button class=primary id=cs_go>Copy the chosen chats into Orbit</button></div></div>`);
 body.appendChild(box);
 $('#cs_list').innerHTML=st.chats.length?st.chats.map(c=>`<label style="display:block;margin:2px 0"><input type=checkbox data-cs="${esc(c.id)}"> ${esc(c.title)} <span class=note>${new Date(c.created*1000).toLocaleDateString()} · ${c.messages} messages${c.imported?' · already copied':''}</span></label>`).join(''):'<div class=note>No chats found.</div>';
 $('#cs_go').onclick=async()=>{const ids=[...box.querySelectorAll('[data-cs]:checked')].map(x=>x.dataset.cs);if(!ids.length)return toast('choose at least one chat');
  const r=await get({op:'import',ids});if(r){toast('copied '+r.imported.length+' chat'+(r.imported.length===1?'':'s')+' into Orbit');try{loadSessions()}catch(x){}}}}
// Settings → General: the person's Orbit account (optional: needed only to join or host a shared project). Signing in opens the account page
// in Chrome and waits here; the tokens stay in the server and never reach this page.
async function drawAccount(body){
 if(!body)return;
 const get=async()=>{try{const r=await fetch('/api/account',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});return r.ok?await r.json():null}catch(e){return null}};
 let st=await get();if(!st)return;
 const box=el(`<div><div class=sec>Orbit account</div><div class=grid>
  <label>Account</label><div class=sw><span id=ac_state></span><button class=primary id=ac_in>Sign in</button><button class=ghost id=ac_out style="display:none">Sign out</button></div>
  <label id=ac_datal style="display:none">Your data</label><div id=ac_dataw class=sw style="display:none"><button class=ghost id=ac_exp>Download what the service holds</button><button class=ghost id=ac_del>Delete my account…</button></div>
  <label id=ac_idl style="display:none">Account id</label><div id=ac_idw style="display:none"><code id=ac_id></code> <button class=ghost id=ac_idcp>Copy</button> <span class=note style="margin-left:6px">send it to a host who wants to add you to a project</span></div>
  <div class=hint2 id=ac_note>An account lets you join shared projects. It stores a random id, the name you pick and a passkey, never your chats or files. Sign-in opens in Chrome.</div>
 </div></div>`);
 body.prepend(box);
 let timer=null;
 const draw=s=>{st=s||st;
  $('#ac_state').textContent=st.signed_in?`Signed in as ${st.name||'a member'}`:st.pending?'Waiting for you to finish in the browser…':st.error||'Not signed in';
  $('#ac_idl').style.display=$('#ac_idw').style.display=st.signed_in&&st.id?'':'none';$('#ac_id').textContent=st.id||'';
  $('#ac_datal').style.display=$('#ac_dataw').style.display=st.signed_in?'':'none';
  $('#ac_in').style.display=st.signed_in?'none':'';$('#ac_in').textContent=st.pending?'Open again':'Sign in';$('#ac_out').style.display=st.signed_in?'':'none'};
 const post=async op=>{const d=await apiPost('/api/account',{op},'that');return d};
 const poll=()=>{clearInterval(timer);timer=setInterval(async()=>{if(!document.body.contains(box)){clearInterval(timer);return}
  const s=await get();if(s){draw(s);if(!s.pending)clearInterval(timer)}},1500)};
 draw(st);if(st.pending)poll();
 $('#ac_idcp').onclick=async()=>{try{await navigator.clipboard.writeText(st.id||'');toast('account id copied')}catch(e){prompt('Copy this:',st.id||'')}};
 $('#ac_in').onclick=async()=>{const d=await post('start');if(!d)return;if(!d.opened){$('#ac_note').innerHTML='Open this address in Chrome to sign in: ';const a=el('<a target=_blank rel=noopener></a>');a.href=d.url;a.textContent='the sign-in page';$('#ac_note').appendChild(a)}
  draw(await get());poll()};
 $('#ac_out').onclick=async()=>{const d=await post('signout');if(d)draw(d)};
 $('#ac_exp').onclick=async()=>{const d=await post('export');if(!d)return;
  if(!d.ok){toast(d.error||'could not download it');return}
  const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([JSON.stringify(d.data,null,2)],{type:'application/json'}));
  a.download='orbit-account-export.json';document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(a.href),4000);toast('saved orbit-account-export.json')};
 $('#ac_del').onclick=async()=>{
  if(!confirm('Delete your Orbit account?\n\nThis erases the account, its sign-in methods and its devices on the Orbit service. You leave every shared project you joined. Your chats and files on this Mac are not touched. It cannot be undone.'))return;
  const d=await apiPost('/api/account',{op:'delete',confirm:'delete'},'deleting');
  if(!d)return;if(!d.ok){toast(d.error||'could not delete it');return}
  draw(await get());toast('your Orbit account was deleted')}}
// Settings → General in a browser or a copy run from source: is a newer Orbit out? One read of the public
// release list (bin/updatecheck.py); nothing is downloaded or installed from here. Orbit for Mac has its own, above.
async function drawWebUpdates(body){
 if(DESK||!body)return;
 const get=async()=>{try{const r=await fetch('/api/update');return r.ok?await r.json():null}catch(e){return null}};
 let st=await get();if(!st)return;
 const box=el(`<div><div class=sec>Updates</div><div class=grid>
  <label>Version</label><div class=sw><span id=wu_state></span><button class=ghost id=wu_check>Check now</button></div>
  <div id=wu_news class=hint2 style="display:none"></div>
  <label>Checking</label><select id=wu_mode><option value=notify>Tell me when a new version is out</option>
   <option value=off>Don't check by itself</option></select>
  <label>Check every</label><select id=wu_every><option value=1>hour</option><option value=6>6 hours</option>
   <option value=24>day</option><option value=168>week</option></select>
  <label>Beta versions</label><div class=sw><input type=checkbox id=wu_beta><span class=note style="margin-left:0">include them</span></div>
  <div class=hint2>Checking reads the public list of releases and sends nothing about you or this Mac.</div>
 </div></div>`);
 body.prepend(box);
 const draw=s=>{st=s||st;const p=st.prefs||{},L=st.latest;
  $('#wu_mode').value=p.mode||'notify';$('#wu_every').value=String(p.every_h||24);$('#wu_beta').checked=p.channel==='beta';
  const when=st.checked?relTime(st.checked):'never';
  $('#wu_state').textContent=st.checking?'checking…':(st.current?'v'+st.current:'version unknown')+
   (st.error?' — '+st.error:st.newer?' — v'+L.version+' is out':L?' — up to date · checked '+when:' — not checked yet');
  const n=$('#wu_news');
  if(st.newer&&!st.skipped){
   const how=st.kind==='app'?'Orbit › Check for Updates… in the menu bar installs it.':
    'This copy runs from a folder, so update it yourself: download the new release, or pull the new code.';
   n.innerHTML=`<b>Orbit ${esc(L.version)} is out</b> (you have ${esc(st.current||'?')}). ${esc(how)}
    <a href="${esc(L.page)}" target=_blank rel=noopener>What's new and download</a> · <button class=ghost id=wu_skip>Skip this version</button>
    ${L.notes?`<div class=note style="white-space:pre-wrap;margin-top:6px;max-height:9em;overflow:auto">${esc(L.notes)}</div>`:''}`;
   n.style.display='';const sk=$('#wu_skip');if(sk)sk.onclick=async()=>{const d=await apiPost('/api/update',{op:'skip',version:L.version},'skipping');if(d)draw(d)}}
  else n.style.display='none'};
 draw(st);
 // a check that started by itself when this opened: look again once it has had time
 if(st.checking)setTimeout(async()=>{if(document.body.contains(box)){const s=await get();if(s)draw(s)}},2500);
 const set=async patch=>{const d=await apiPost('/api/update',Object.assign({op:'config'},patch),'saving');if(d)draw(d)};
 $('#wu_mode').onchange=e=>set({mode:e.target.value});
 $('#wu_every').onchange=e=>set({every_h:+e.target.value});
 $('#wu_beta').onchange=e=>set({channel:e.target.checked?'beta':'stable'});
 $('#wu_check').onclick=async()=>{$('#wu_state').textContent='checking…';const d=await apiPost('/api/update',{op:'check'},'the check');draw(d||st)}}
// The user guide (web/guide.md, also read by the iPhone app): its sections down the left,
// the text on the right, and a search that narrows the sections to the ones that match.
let GUIDE_MD=null;
async function openGuide(section){
 $('#modalhost').innerHTML=`<div class=modal><div class="sheet guide">
  <header><b>User guide</b><input type=search id=gfind placeholder="Search the guide" autocomplete=off>
   <button class=ghost style="margin-left:auto" id=gx>Close</button></header>
  <div class=setgrid><nav class="tabs vnav" id=gnav></nav><div class="body bub guidebody" id=gbody><div class=note>Loading…</div></div></div></div></div>`;
 $('#gx').onclick=closeModal;
 $('#modalhost').querySelector('.modal').onclick=e=>{if(e.target.classList.contains('modal'))closeModal()};
 try{if(GUIDE_MD==null){const r=await fetch('/guide.md');if(!r.ok)throw new Error('the server answered '+r.status);GUIDE_MD=await r.text()}}
 catch(e){$('#gbody').innerHTML=`<div class=note>Could not load the guide — ${esc(e.message)}</div>`;return}
 const body=$('#gbody'),nav=$('#gnav');
 body.innerHTML=md(GUIDE_MD);
 const heads=[...body.querySelectorAll('h2')];
 heads.forEach((h,i)=>{h.id='g-'+i;
  const b=el('<button></button>');b.textContent=h.textContent;b.dataset.g=i;
  b.onclick=()=>{h.scrollIntoView({block:'start',behavior:'smooth'})};nav.appendChild(b)});
 // the section you are reading lights up as you scroll
 const mark=()=>{let cur=0;heads.forEach((h,i)=>{if(h.offsetTop-body.offsetTop<=body.scrollTop+40)cur=i});
  nav.querySelectorAll('button').forEach(b=>b.classList.toggle('on',+b.dataset.g===cur))};
 body.addEventListener('scroll',mark);mark();
 $('#gfind').oninput=e=>{const t=e.target.value.trim().toLowerCase();
  heads.forEach((h,i)=>{let n=h.nextElementSibling,txt=h.textContent;
   while(n&&n.tagName!=='H2'){txt+=' '+n.textContent;n=n.nextElementSibling}
   nav.querySelector(`[data-g="${i}"]`).style.display=!t||txt.toLowerCase().includes(t)?'':'none'});
  const first=[...nav.querySelectorAll('button')].find(b=>b.style.display!=='none');
  if(t&&first)heads[+first.dataset.g].scrollIntoView({block:'start'})};
 if(section){const h=heads.find(x=>x.textContent.toLowerCase().includes(String(section).toLowerCase()));if(h)h.scrollIntoView({block:'start'})}}
// a question typed into the desktop app's Quick Ask: a new chat, in front or behind
async function quickAsk(a){
 const text=String(a&&a.text||'').trim();if(!text)return;
 if(a.draft){await newChat();showPane('log');q.value=text;fitQ();q.focus();return}
 if(!a.background){await newChat();showPane('log');q.value=text;fitQ();go();return}
 // behind: its own chat, started and left to run; the app says when the answer is in
 try{
  const d=await (await fetch('/api/new',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'})).json();
  if(!d.sid)throw new Error(d.error||'no chat');
  const ac=new AbortController();
  const r=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},signal:ac.signal,
   body:JSON.stringify({sid:d.sid,message:text})});
  // the answer carries on on the Mac without this page listening
  setTimeout(()=>ac.abort(),400);
  if(!r.ok)throw new Error('the server answered '+r.status);
  toast('Asked in a new chat — you will be told when the answer is in');
  setTimeout(loadSessions,1500)}
 catch(e){if(e.name!=='AbortError')toast('could not ask: '+(e.message||e))}}
if(DESK&&DESK.onCommand)DESK.onCommand((name,arg)=>{
 const dialog=!!$('#modalhost').innerHTML;
 switch(name){
  case 'settings':openSettings();break;
  case 'new-chat':if(dialog)closeModal();showPane('log');newChat();break;
  case 'new-chat-with':newChatWith();break;
  case 'close-tab':if(dialog)closeModal();else if(document.querySelector('.palette'))closePal();else closeTab(sid);break;
  case 'reopen-tab':reopenTab();break;
  case 'find':if(!sid||!wrap.children.length)$('#search').focus();else openFind();break;
  case 'palette':openPal();break;
  case 'jump':openJump();break;
  case 'guide':openGuide();break;
  case 'toggle-sidebar':{const a=$('#side');sideOpen(a.classList.contains('hide'),false);break}
  case 'toggle-terminal':toggleTerm();break;
  case 'files':showPane('files');break;
  case 'stop':stopRun();break;
  case 'next-tab':stepTab(1);break;
  case 'prev-tab':stepTab(-1);break;
  case 'tab':if(arg&&+arg.n>=1&&+arg.n<=9)gotoTab(+arg.n);break;
  case 'open-chat':if(arg&&typeof arg.sid==='string'&&arg.sid){if(dialog)closeModal();showPane('log');openSession(arg.sid)}break;
  case 'new-chat-send':quickAsk(arg||{});break;
 }});
// ---- a chat in a copy of its own: a git worktree on a branch of its own (OpenCode v2's
// workspaces). Your checkout stays as it is; merge the work back, or throw the copy away.
function wtOf(){return (CHATPREFS&&CHATPREFS.worktree)||null}
function drawWtBadge(){
 const b=$('#wtbadge');if(!b)return;const wt=wtOf();
 b.style.display=wt?'':'none';
 if(wt){b.textContent='⑂ '+(wt.branch||'copy');b.title='This chat works in a copy of '+(wt.repo||'its repository')+
  ' on branch '+wt.branch+' — click to merge it back or throw it away'}}
async function wtCall(body){
 const r=await fetch('/api/worktree',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
 const d=await r.json().catch(()=>({}));if(!r.ok)throw new Error(d.error||('the server answered '+r.status));return d}
async function openWorktree(){
 const forSid=sid;if(!forSid)return;
 $('#modalhost').innerHTML=`<div class=modal><div class="sheet auto" style="max-width:560px">
  <header><b>Separate copy</b><button class=ghost style="margin-left:auto" id=wtx>close</button></header>
  <div class=body id=wtbody><div class=note>Looking…</div></div><footer id=wtfoot></footer></div></div>`;
 $('#wtx').onclick=closeModal;
 $('#modalhost').querySelector('.modal').onclick=e=>{if(e.target.classList.contains('modal'))closeModal()};
 let d;try{d=await wtCall({sid:forSid,op:'status'})}catch(e){$('#wtbody').innerHTML=`<div class=note>${esc(e.message)}</div>`;return}
 const body=$('#wtbody'),foot=$('#wtfoot'),wt=d.worktree;
 const act=(label,cls,fn)=>{const b=el(`<button class="${cls}">${label}</button>`);b.onclick=async()=>{
  b.disabled=true;try{await fn()}catch(e){toast(e.message);b.disabled=false}};foot.appendChild(b);return b};
 if(!wt){
  const started=!!wrap.querySelector('.msg');
  body.innerHTML=`<p style="margin-top:0">Work in a <b>copy of this chat's repository</b>, on a branch of its own. The chat can change files
   freely while your checkout stays exactly as it is — and two chats can work on one repository without treading on each other.
   When it is done, merge the branch back, or throw the copy away.</p>
   <p class=note>Only what is committed goes into the copy. ${started?'This chat has already started in its folder, so the copy opens in a <b>new chat</b>.':''}</p>
   <label class=note>Branch name <input id=wtname placeholder="from the chat's title" style="width:100%;margin-top:4px"></label>`;
  act(started?'Open a new chat in a copy':'Work in a copy','sendbtn',async()=>{
   const name=$('#wtname').value.trim();
   let target=forSid;
   if(started){await newChat();target=sid}
   const r=await wtCall({sid:target,op:'create',name,from_sid:started?forSid:undefined});
   CHATPREFS=Object.assign({},CHATPREFS,{worktree:r.worktree,cwd:r.worktree.cwd});drawWtBadge();closeModal();
   toast('This chat now works in '+r.worktree.branch+(r.worktree.left_behind?' — uncommitted changes in your checkout stayed there':''));
   pollGit(true)});
  return}
 if(!wt.exists){
  body.innerHTML=`<p style="margin-top:0">The copy for <b>${esc(wt.branch)}</b> is gone (deleted outside Orbit?).</p>`;
  act('Forget it','ghost',async()=>{await wtCall({sid:forSid,op:'discard'});CHATPREFS.worktree=null;drawWtBadge();closeModal()});return}
 body.innerHTML=`<div style="display:grid;grid-template-columns:auto 1fr;gap:4px 12px;font-size:var(--fs-sm)">
   <span class=note>branch</span><b class=wtv></b><span class=note>from</span><span class=wtv></span>
   <span class=note>copy</span><span class=wtv style="font-family:var(--mono);font-size:var(--fs-xs);word-break:break-all"></span>
   <span class=note>state</span><span class=wtv></span></div>
  <div id=wtlog style="margin-top:10px"></div>`;
 const v=body.querySelectorAll('.wtv');
 v[0].textContent=wt.branch;v[1].textContent=wt.base+' in '+wt.repo;v[2].textContent=wt.path;
 v[3].textContent=`${wt.ahead} commit${wt.ahead===1?'':'s'} of its own · ${wt.dirty} file${wt.dirty===1?'':'s'} not committed`+
  (wt.behind?` · ${wt.base} has ${wt.behind} newer commit${wt.behind===1?'':'s'}`:'');
 const lg=$('#wtlog');
 (wt.commits||[]).forEach(c=>{const r=el('<div class=note style="font-family:var(--mono);font-size:var(--fs-xs)"></div>');r.textContent=c;lg.appendChild(r)});
 (wt.files||[]).slice(0,12).forEach(f=>{const r=el('<div class=note style="font-family:var(--mono);font-size:var(--fs-xs)"></div>');r.textContent='● '+f;lg.appendChild(r)});
 act('Merge back into '+esc(wt.base),'sendbtn',async()=>{
  if(!confirm(`Commit what is left in the copy, merge ${wt.branch} into ${wt.base} in your checkout, then remove the copy?`))return;
  const r=await wtCall({sid:forSid,op:'merge'});CHATPREFS.worktree=null;drawWtBadge();closeModal();
  toast(r.merged?`Merged ${r.commits} commit${r.commits===1?'':'s'} into ${wt.base}`:(r.why||'nothing to merge'));pollGit(true)});
 act('Terminal there','ghost',async()=>{closeModal();newTerm(wt.cwd)});
 act('Throw the copy away','ghost',async()=>{
  if(!confirm(`Delete the copy and branch ${wt.branch}, with everything in it? This cannot be undone.`))return;
  await wtCall({sid:forSid,op:'discard'});CHATPREFS.worktree=null;drawWtBadge();closeModal();toast('The copy is gone')}).style.color='var(--err)'}
// ---- paths in answers: what you can do with them, in plain sight. A path was a dotted
// underline you had to know to click (open) or right-click (everything else); hovering one
// now shows its main actions, and one the answer had not made yet keeps checking.
function tildify(p){const h=(FILE_CTX&&FILE_CTX.home)||'';return h&&p.startsWith(h)?'~'+p.slice(h.length):String(p).replace(/^\/Users\/[^/]+/,'~')}
async function recheckMissing(root,loud){
 const miss=[...(root||wrap).querySelectorAll('.pathlink.missing[data-path]')];
 if(!miss.length){if(loud)toast('nothing missing here');return}
 const cache=RESOLVED[sid||'']||{};miss.forEach(m=>{delete cache[m.dataset.path]});
 const res=await resolveNames(miss.map(m=>m.dataset.path));let found=0;
 miss.forEach(c=>{const f=res[c.dataset.path];if(!f||!f.exists)return;found++;
  c.classList.remove('missing');c.dataset.path=f.path;if(c.tagName==='CODE')c.classList.add('pathcode');
  c.title=`${f.path}${f.kind==='file'?' · '+fmtBytes(f.size):' · folder'}`});
 if(loud)toast(found?`found ${found} that ${found===1?'is':'are'} there now`:'still not there')}
let PATHBAR=null,PATHBAR_T=null;
function hidePathBar(){clearTimeout(PATHBAR_T);if(PATHBAR){PATHBAR.remove();PATHBAR=null}}
document.addEventListener('mouseover',e=>{
 const p=e.target.closest&&e.target.closest('#wrap .pathlink:not(.toolopen)');
 if(!p){if(PATHBAR&&!(e.target.closest&&e.target.closest('.pathbar'))){clearTimeout(PATHBAR_T);PATHBAR_T=setTimeout(hidePathBar,350)}return}
 if(PATHBAR&&PATHBAR._for===p){clearTimeout(PATHBAR_T);return}
 clearTimeout(PATHBAR_T);
 PATHBAR_T=setTimeout(async()=>{
  hidePathBar();
  if(p.classList.contains('missing'))await recheckMissing(p.parentElement);   // made since?
  const f=pathInfo(p),miss=p.classList.contains('missing'),remote=!!f.host;
  const bar=el('<div class=pathbar role=toolbar></div>');bar._for=p;
  const add=(label,run,title)=>{const b=el(`<button>${label}</button>`);if(title)b.title=title;
   b.onclick=ev=>{ev.stopPropagation();hidePathBar();run(ev)};bar.appendChild(b)};
  if(miss){
   bar.appendChild(el('<span class=pbnote>not there yet</span>'));
   if(f.nearest&&!remote)add('Show nearest folder',()=>fileAction('reveal',{path:f.nearest,kind:'folder',category:'folder'}),tildify(f.nearest));
  }else{
   add(f.kind==='folder'?'Open':'Open',()=>fileAction('open',f));
   if(PREVIEWABLE.has(f.category||''))add('Preview',()=>previewFile(f));
   add(remote?'Show in Finder':'Show in Finder',()=>fileAction('reveal',f));
  }
  add('Copy path',()=>copy(f.path));
  add('⋯',ev=>fileMenu({clientX:ev.clientX,clientY:ev.clientY,preventDefault(){}},pathInfo(p)),'everything you can do with it');
  document.body.appendChild(bar);PATHBAR=bar;
  const r=p.getBoundingClientRect(),bw=bar.offsetWidth;
  bar.style.left=Math.max(8,Math.min(innerWidth-bw-8,r.left))+'px';
  bar.style.top=(r.top>48?r.top-bar.offsetHeight-6:r.bottom+6)+'px';
  bar.onmouseleave=()=>{PATHBAR_T=setTimeout(hidePathBar,300)};bar.onmouseenter=()=>clearTimeout(PATHBAR_T);
 },420)});
document.addEventListener('scroll',hidePathBar,true);
// ---- the terminal: a shell in this chat's folder, at the foot of the window. The shells
// live on the Mac, not in the page: reload (or open another window) and they are still there.
const TERMS={list:[],active:null,lib:null};
function termLib(){
 if(TERMS.lib)return TERMS.lib;
 TERMS.lib=new Promise((ok,bad)=>{
  const l=document.createElement('link');l.rel='stylesheet';l.href='/vendor/xterm/xterm.css';document.head.appendChild(l);
  let n=0;const files=['xterm.js','addon-fit.js','addon-web-links.js'];
  files.forEach(f=>{const e=document.createElement('script');e.src='/vendor/xterm/'+f;
   e.onload=()=>{if(++n===files.length)ok()};e.onerror=()=>{TERMS.lib=null;bad(new Error('the terminal did not load'))};
   document.head.appendChild(e)})});
 return TERMS.lib}
function termTheme(){
 const c=getComputedStyle(document.documentElement),v=k=>c.getPropertyValue(k).trim();
 return {background:v('--card')||'#fff',foreground:v('--fg')||'#141413',cursor:v('--acc'),cursorAccent:v('--card'),
  selectionBackground:/^#[0-9a-f]{6}$/i.test(v('--acc'))?v('--acc')+'4d':'rgba(107,91,214,.3)',
  ...(termDark(v('--card'))?TERM_DARK:TERM_LIGHT)}}
function termDark(hex){const m=/^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex||'');
 if(!m)return matchMedia('(prefers-color-scheme: dark)').matches;
 return (0.299*parseInt(m[1],16)+0.587*parseInt(m[2],16)+0.114*parseInt(m[3],16))<128}
// calm palettes in the page's own warm greys, readable on its card colour
const TERM_LIGHT={black:'#3b3a36',red:'#c0392b',green:'#2d7d4f',yellow:'#a8721c',blue:'#3d6fb6',magenta:'#7a5bd6',
 cyan:'#1f7f86',white:'#d9d6cc',brightBlack:'#8a8880',brightRed:'#d9534f',brightGreen:'#3c9a63',brightYellow:'#c08a2b',
 brightBlue:'#5687cc',brightMagenta:'#8f74e0',brightCyan:'#2f98a0',brightWhite:'#f0eee6'};
const TERM_DARK={black:'#1f1e1d',red:'#ec6a5e',green:'#7fc89a',yellow:'#e0b866',blue:'#7aa7e6',magenta:'#b39ef5',
 cyan:'#6cc4c9',white:'#d6d3c9',brightBlack:'#6b6a64',brightRed:'#f28b80',brightGreen:'#9fdcb4',brightYellow:'#ecc985',
 brightBlue:'#9cc0f0',brightMagenta:'#c9b8fa',brightCyan:'#8fd6da',brightWhite:'#faf9f5'};
function termShown(){return $('#termdock').style.display!=='none'}
async function toggleTerm(open){
 const dock=$('#termdock');
 if(termShown()&&open!==true){dock.style.display='none';
  if(!matchMedia('(pointer:coarse)').matches)q.focus();return}
 dock.style.display='';
 try{const h=localStorage.getItem('orbit.termh');if(h)dock.style.setProperty('--termh',h)}catch(e){}
 try{await termLib()}catch(e){$('#termbody').innerHTML=`<div class=termmsg>${esc(e.message)}</div>`;return}
 // the shells already running on the Mac, opened from another window or before a reload
 try{const d=await (await fetch('/api/term/list')).json();
  (d.terms||[]).filter(v=>v.alive&&!TERMS.list.some(t=>t.id===v.id)).forEach(v=>termAttach(v,false))}
 catch(e){}
 if(!TERMS.list.length){await newTerm();return}
 termShow(TERMS.active||TERMS.list[TERMS.list.length-1].id)}
async function newTerm(cwd){
 if(!termShown()){$('#termdock').style.display=''}
 try{await termLib()}catch(e){toast(e.message);return}
 const r=await fetch('/api/term/open',{method:'POST',headers:{'Content-Type':'application/json'},
  body:JSON.stringify({sid,cwd:cwd||undefined,cols:100,rows:24})});
 const v=await r.json().catch(()=>({}));
 if(!r.ok){toast(v.error||'could not open a terminal');if(!TERMS.list.length)$('#termdock').style.display='none';return}
 termAttach(v,true);return v}
// Open Orbit's own terminal with a command in it: run at once (a sign-in), or typed and left for you
// to read and press Enter (an installer)
async function terminalDo(cmd,run){
 try{closeModal()}catch(e){}
 const v=await newTerm();
 if(!v||!v.id)return;
 await new Promise(r=>setTimeout(r,700));                 // the shell has started
 await fetch('/api/term/input',{method:'POST',headers:{'Content-Type':'application/json'},
  body:JSON.stringify({id:v.id,data:cmd+(run?'\n':'')})})}
function termAttach(v,show){
 const pane=el('<div class=termpane></div>');$('#termbody').appendChild(pane);
 const css=getComputedStyle(document.documentElement);
 // prompts drawn with Nerd Font glyphs (powerlevel10k and the like) find them in the font they ship
 const term=new Terminal({fontFamily:'"IBM Plex Mono","MesloLGS NF","MesloLGS Nerd Font","Symbols Nerd Font Mono","Hack Nerd Font",Menlo,monospace',fontSize:12.5,
  lineHeight:1.15,cursorBlink:true,scrollback:8000,allowProposedApi:false,theme:termTheme(),macOptionIsMeta:true});
 const fit=new FitAddon.FitAddon();term.loadAddon(fit);
 try{term.loadAddon(new WebLinksAddon.WebLinksAddon((ev,uri)=>window.open(uri,'_blank','noopener')))}catch(e){}
 term.open(pane);
 const t={id:v.id,title:v.title,cwd:v.cwd,host:v.host,term,fit,pane,off:0,ended:false,es:null,out:''};
 TERMS.list.push(t);
 // typing goes out in one request per burst, not one per key
 let flushT=null;
 term.onData(d=>{t.out+=d;if(flushT)return;flushT=setTimeout(()=>{const data=t.out;t.out='';flushT=null;
  fetch('/api/term/input',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:t.id,data})})},8)});
 term.onResize(({cols,rows})=>{if(!t.ended)fetch('/api/term/resize',{method:'POST',headers:{'Content-Type':'application/json'},
  body:JSON.stringify({id:t.id,cols,rows})})});
 termListen(t);
 if(show||!TERMS.active)termShow(t.id);else drawTermBar()}
function termListen(t){
 if(t.es)t.es.close();
 const es=new EventSource('/api/term/stream?id='+encodeURIComponent(t.id)+'&from='+t.off);t.es=es;
 es.onmessage=ev=>{let m;try{m=JSON.parse(ev.data)}catch(e){return}
  if(m.d){const b=atob(m.d),u=new Uint8Array(b.length);for(let i=0;i<b.length;i++)u[i]=b.charCodeAt(i);t.term.write(u)}
  if(m.o!=null)t.off=m.o;
  if('exit' in m){t.ended=true;es.close();t.es=null;
   t.term.write('\r\n\x1b[2m[the shell ended'+(m.exit!=null?' with code '+m.exit:'')+' — close this tab or open a new one]\x1b[0m\r\n');
   drawTermBar()}};
 // EventSource would reconnect from where it first started and print everything twice:
 // reconnect by hand, from what has been printed so far
 es.onerror=()=>{es.close();if(t.es!==es)return;t.es=null;
  if(!t.ended&&TERMS.list.includes(t))setTimeout(()=>{if(!t.es&&!t.ended&&TERMS.list.includes(t))termListen(t)},1500)}}
function termShow(id){
 TERMS.active=id;
 TERMS.list.forEach(t=>t.pane.classList.toggle('on',t.id===id));
 drawTermBar();
 const t=TERMS.list.find(x=>x.id===id);
 if(t)requestAnimationFrame(()=>{try{t.fit.fit()}catch(e){}t.term.focus()})}
async function closeTerm(id){
 const t=TERMS.list.find(x=>x.id===id);if(!t)return;
 if(t.es)t.es.close();t.es=null;
 TERMS.list=TERMS.list.filter(x=>x!==t);
 fetch('/api/term/close',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id})});
 try{t.term.dispose()}catch(e){}t.pane.remove();
 if(TERMS.active===id)TERMS.active=null;
 if(!TERMS.list.length){$('#termdock').style.display='none';drawTermBar();return}
 termShow(TERMS.active||TERMS.list[TERMS.list.length-1].id)}
function drawTermBar(){
 const bar=$('#termbar');bar.innerHTML='';
 TERMS.list.forEach(t=>{
  const b=el(`<button class="ttab${t.id===TERMS.active?' on':''}${t.ended?' ended':''}"><span class=tt></span><span class=tx title="close this terminal"><svg viewBox="0 0 10 10" width="9" height="9" aria-hidden="true"><path d="M2 2l6 6M8 2l-6 6" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg></span></button>`);
  b.querySelector('.tt').textContent=(t.host?'⇄ ':'')+t.title;b.title=(t.host?t.host+':':'')+t.cwd;
  b.onclick=e=>{if(e.target.closest('.tx'))closeTerm(t.id);else termShow(t.id)};
  b.onauxclick=e=>{if(e.button===1)closeTerm(t.id)};
  bar.appendChild(b)});
 const add=el('<button class=tbtn title="a new terminal in this chat\'s folder">+</button>');add.onclick=()=>newTerm();bar.appendChild(add);
 bar.appendChild(el('<span class=tsp></span>'));
 const max=el(`<button class=tbtn title="taller / shorter">${$('#termdock').classList.contains('max')?'▾':'▴'}</button>`);
 max.onclick=()=>{$('#termdock').classList.toggle('max');drawTermBar();termFit()};bar.appendChild(max);
 const hide=el('<button class=tbtn title="hide (Ctrl+`) — the shells keep running">✕</button>');hide.onclick=()=>toggleTerm(false);
 bar.appendChild(hide)}
function termFit(){const t=TERMS.list.find(x=>x.id===TERMS.active);if(t&&termShown())requestAnimationFrame(()=>{try{t.fit.fit()}catch(e){}})}
new ResizeObserver(()=>termFit()).observe($('#termbody'));
// the theme follows the page's: light, dark, or whatever the Mac says
function termRetheme(){TERMS.list.forEach(t=>{t.term.options.theme=termTheme()})}
new MutationObserver(termRetheme).observe(document.documentElement,{attributes:true,attributeFilter:['data-theme','style','class']});
matchMedia('(prefers-color-scheme: dark)').addEventListener('change',()=>setTimeout(termRetheme,50));
$('#termgrip').onpointerdown=e=>{
 const dock=$('#termdock'),y0=e.clientY,h0=dock.getBoundingClientRect().height;dock.classList.remove('max');
 e.target.setPointerCapture(e.pointerId);
 const mv=ev=>{const h=Math.max(120,Math.min(innerHeight*0.8,h0+(y0-ev.clientY)));dock.style.setProperty('--termh',h+'px')};
 const up=()=>{e.target.removeEventListener('pointermove',mv);e.target.removeEventListener('pointerup',up);
  try{localStorage.setItem('orbit.termh',dock.style.getPropertyValue('--termh'))}catch(_){}termFit()};
 e.target.addEventListener('pointermove',mv);e.target.addEventListener('pointerup',up)};
// Ctrl+` from anywhere, the terminal included (it would otherwise take the key itself)
addEventListener('keydown',e=>{if(e.ctrlKey&&!e.metaKey&&!e.altKey&&e.code==='Backquote'){
 e.preventDefault();e.stopPropagation();toggleTerm()}},true);
fetch('/api/info').then(r=>r.json()).then(d=>{
 // this lands whenever it lands, and on a slow first load that can be after you have
 // already clicked a chat: it may not drag the page back to the Mac's current one
 const first=!sid;
 INFO=Object.assign(d,first?{}:{tools:INFO.tools||d.tools});
 if(first)sid=d.sid;
 $('#tools').dataset.orbit=d.tools.length+' tools ready';if(!MODELS.harness_mode)$('#tools').textContent=d.tools.length+' tools ready';
 drawEasyBtn();refreshStatus()});
fetch('/api/prompts').then(r=>r.json()).then(d=>PROMPTS=d);
async function loadAgents(){
 const d=await (await fetch('/api/agents'+(sid?'?sid='+encodeURIComponent(sid):''))).json();
 const sel=$('#agentsel');sel.innerHTML='<option value="">no agent</option>';
 Object.keys(d.agents||{}).forEach(n=>{const o=document.createElement('option');
  o.value=n;o.textContent=n;if(n===d.active)o.selected=true;sel.appendChild(o)})}
$('#agentsel').onchange=async e=>{
 const r=await (await fetch('/api/agent/select',{method:'POST',
  headers:{'Content-Type':'application/json'},body:JSON.stringify({name:e.target.value,sid})})).json();
 INFO.tools=r.tools;$('#tools').dataset.orbit=r.tools.length+' tools ready';if(!MODELS.harness_mode)$('#tools').textContent=r.tools.length+' tools ready';
 toast(e.target.value?('agent: '+e.target.value):'agent cleared')};
loadAgents();
// The first time Orbit opens in a browser or in Orbit for Mac: what it is, four things worth
// knowing, and the way into the user guide. Reopened from ⋯ More → Welcome.
function showOnboarding(){
 const done=()=>{PREF.set('onboarded','1');closeModal()};
 $('#modalhost').innerHTML=`<div class=modal><div class="sheet auto welcome" style="max-width:640px">
  <div class=body>
   <div class=wtop><img src="/icons/orbit-128.png?v=2" alt="" width=72 height=72>
    <h2>Welcome to Orbit</h2>
    <p>Your own research assistant. It runs on this Mac — your chats, files and models stay here —
     and answers with whichever model you choose.</p></div>
   <div class=wgrid>
    <div><i><svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z"/></svg></i><b>Just ask</b><span>It decides when to search the web, read your papers, run code or query NCBI. You don't name tools.</span></div>
    <div><i><svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="5" y="5" width="14" height="14" rx="2"/><path d="M9 9h6v6H9zM9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3"/></svg></i><b>Choose who answers</b><span>Above the message box: Orbit's own agent, Claude Code or Codex — a local model, a hosted key or your subscription.</span></div>
    <div><i><svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2z"/><path d="M4 19V5"/></svg></i><b>Give it context</b><span><b>Library → Knowledge</b> for your papers, <b>Memory</b> for facts about you, <b>Projects</b> for shared instructions.</span></div>
    <div><i><svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3l8 3v6c0 4.5-3.4 8.3-8 9-4.6-.7-8-4.5-8-9V6z"/><path d="M9 12l2 2 4-4"/></svg></i><b>It asks first</b><span>Anything that matters — deleting, publishing, pushing — waits for your yes. Web content is fenced and checked.</span></div>
   </div>
   <p class=wfoot>The user guide covers everything, step by step. It is always under <b>⋯ More → User guide</b>,
    <code>/guide</code>${window.orbitDesktop?', and <b>Help → Orbit Guide</b>':''}.</p>
  </div>
  <footer><button class=ghost id=ob_guide>Read the user guide</button>
   <button class=primary id=ob_done style="margin-left:auto">Get started</button></footer></div></div>`;
 $('#ob_done').onclick=done;
 $('#ob_guide').onclick=()=>{PREF.set('onboarded','1');openGuide()};
}
try{if(!PREF.get('onboarded'))setTimeout(showOnboarding,700)}catch(e){}
const PAGE_LOADED=Date.now()/1000;
async function checkCode(){
 try{const c=await (await fetch('/api/code')).json();
  // the page itself changed on disk since this tab loaded it: fixes to the
  // page only arrive with a reload, and nothing used to say so
  if(c.page_mtime&&c.page_mtime>PAGE_LOADED+2&&!document.querySelector('.reloadBar')){
   const b=el('<div class="staleBar reloadBar"><span>Orbit\'s page was updated — reload to get the new version.</span></div>');
   const btn=el('<button>Reload</button>');btn.onclick=()=>location.reload();b.appendChild(btn);
   document.body.appendChild(b)}
  const bar=document.querySelector('.staleBar:not(.reloadBar)');   // not the page-reload bar
  if(c.stale&&!bar){
   const b=el(`<div class=staleBar><span>Code changed on disk (${c.files.join(', ')}) — `
     +`the running interface is out of date.</span></div>`);
   const btn=el('<button>Restart interface</button>');
   btn.onclick=async()=>{
    btn.disabled=true;btn.textContent='restarting…';
    const rr=await fetch('/api/restart_ui',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'})
      .then(r=>r.json()).catch(()=>({}));
    if(rr.deferred){btn.textContent=rr.msg||'restarting when answers finish';toast(rr.msg||'waiting for running answers');return}
    // wait for it to actually come back instead of reloading into a dead server
    const t0=Date.now();
    const poll=async()=>{
     try{const r=await fetch('/api/code',{cache:'no-store'});
      if(r.ok){location.reload();return}}catch(e){}
     const secs=Math.round((Date.now()-t0)/1000);
     btn.textContent=`restarting… ${secs}s`;
     if(secs>60){btn.textContent='still down — check logs';btn.disabled=false;return}
     setTimeout(poll,700)};
    setTimeout(poll,700)};
   b.appendChild(btn);document.body.appendChild(b)}
  else if(!c.stale&&bar)bar.remove();
 }catch(e){}}
checkCode(); setInterval(checkCode,15000);
loadSessions();refreshStatus();loadModels();setInterval(refreshStatus,20000);q.focus();
// Adopt the server's current chat. Without this the browser started with sid=null
// and the server quietly kept using whatever chat it was on -- including a
// temporary one, so the next answer was discarded without a word.
(async()=>{try{
 const st=await (await fetch('/api/state')).json();
 sid=st.sid;
 if(!st.temp&&st.title)await openSession(st.sid);   // and show what is in it
 if(st.temp){tempMode=true;
  $('#title').textContent='Temporary chat';
  $('#tempbtn').style.borderColor='var(--err)';$('#tempbtn').style.color='var(--err)';
  $('#burnbtn').style.display='';
  sysline('Still in a temporary chat: nothing here is written to disk.')}

}catch(e){}})();
