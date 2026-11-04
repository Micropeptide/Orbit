/* Claude Code tools: the subagents it can hand work to (each on a model you choose), the hooks it runs, and the
   options Orbit passes on. Opened with /subagents, /hooks or /claude-options, or from the Claude panel. */
(function(){
const J=(u,b)=>fetch(u,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)}).then(r=>r.json().then(d=>({ok:r.ok,d})));
async function chatCwd(){
 try{const d=await (await fetch('/api/claude/info?sid='+encodeURIComponent(sid||''))).json();return d.cwd||''}catch(e){return ''}}
const MODEL_HINT={inherit:'the same model as this chat',haiku:'small and cheap — searching, summarising',sonnet:'balanced',opus:'strongest — review and hard problems'};

async function openSubagents(){
 const cwd=await chatCwd();
 const host=$('#modalhost');
 host.innerHTML=`<div class=modal><div class="sheet" style="max-width:760px"><header><b>Subagents</b>
  <small style="margin-left:10px;color:var(--mut)">Claude hands work to these, each on the model you give it</small>
  <button class=ghost style="margin-left:auto" id=sa_x>close</button></header><div class=body>
  <div id=sa_list></div>
  <div class=sec>Add one</div>
  <div class=chips id=sa_tpl style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px"></div>
  <div class=kv style="grid-template-columns:110px 1fr">
   <span>Name</span><input id=sa_name placeholder="searcher" spellcheck=false>
   <span>For</span><input id=sa_desc placeholder="what it is for — Claude decides when to use it from this">
   <span>Model</span><span><select id=sa_model></select> <span class=note id=sa_mh></span></span>
   <span>Tools</span><input id=sa_tools placeholder="Read, Grep, Glob — empty means all" spellcheck=false>
   <span>Where</span><select id=sa_scope><option value=user>every project (~/.claude/agents)</option>${cwd?'<option value=project>this chat\'s folder only</option>':''}</select>
   <span>Instructions</span><textarea id=sa_prompt rows=5 placeholder="what it does and how it answers"></textarea></div>
  <div style="margin-top:10px"><button class=primary id=sa_save>Save subagent</button> <span class=note id=sa_msg></span></div>
  </div></div></div>`;
 host.querySelector('.modal').onclick=e=>{if(e.target.classList.contains('modal'))closeModal()};
 $('#sa_x').onclick=closeModal;
 let meta={models:[],templates:[]};
 const model=$('#sa_model');
 const hint=()=>{$('#sa_mh').textContent=MODEL_HINT[model.value]||'a model id'};model.onchange=hint;
 const draw=async()=>{
  const {d}=await J('/api/ccfeatures',{op:'agents',cwd});meta=d;
  if(!model.options.length){d.models.forEach(m=>{const o=document.createElement('option');o.value=o.textContent=m;model.appendChild(o)});hint()}
  const L=$('#sa_list');L.innerHTML='';
  if(!d.agents.length)L.appendChild(el('<div class=note style="padding:6px 0">None yet. Start from one below.</div>'));
  d.agents.forEach(a=>{
   const r=el(`<div class=memrow style="align-items:center;gap:10px"><b style="flex:0 0 120px"></b><span class=note style="flex:0 0 150px"></span><span style="flex:1;color:var(--mut);overflow:hidden;text-overflow:ellipsis;white-space:nowrap"></span><button class=ghost data-a=edit>edit</button><button class=ghost data-a=rm>remove</button></div>`);
   r.querySelector('b').textContent=a.name;
   r.children[1].textContent=a.model+' · '+(a.scope==='user'?'everywhere':'this folder');
   r.children[2].textContent=a.description;
   r.querySelector('[data-a=edit]').onclick=()=>{$('#sa_name').value=a.name;$('#sa_desc').value=a.description;$('#sa_tools').value=a.tools;
    $('#sa_prompt').value=a.prompt;if(![...model.options].some(o=>o.value===a.model)){const o=document.createElement('option');o.value=o.textContent=a.model;model.appendChild(o)}
    model.value=a.model;$('#sa_scope').value=a.scope;hint();$('#sa_name').focus()};
   r.querySelector('[data-a=rm]').onclick=async()=>{if(!confirm('Remove subagent “'+a.name+'”?'))return;
    await J('/api/ccfeatures',{op:'agent_delete',cwd,scope:a.scope,name:a.name});draw()};
   L.appendChild(r)});
  const T=$('#sa_tpl');T.innerHTML='';
  d.templates.forEach(t=>{const b=el('<button class=suggp></button>');b.textContent=t.name+' · '+t.model;
   b.onclick=()=>{$('#sa_name').value=t.name;$('#sa_desc').value=t.description;$('#sa_tools').value=t.tools;$('#sa_prompt').value=t.prompt;model.value=t.model;hint()};
   T.appendChild(b)})};
 $('#sa_save').onclick=async()=>{
  const {ok,d}=await J('/api/ccfeatures',{op:'agent_save',cwd,scope:$('#sa_scope').value,name:$('#sa_name').value,description:$('#sa_desc').value,
   prompt:$('#sa_prompt').value,model:model.value,tools:$('#sa_tools').value});
  $('#sa_msg').textContent=ok?'saved — new chats and the next message use it':(d.error||'could not save');
  $('#sa_msg').style.color=ok?'var(--ok)':'var(--err)';if(ok)draw()};
 draw()}

async function openHooks(){
 const cwd=await chatCwd();
 const {d}=await J('/api/ccfeatures',{op:'hooks',cwd});
 const host=$('#modalhost');
 host.innerHTML=`<div class=modal><div class="sheet" style="max-width:760px"><header><b>Hooks</b>
  <small style="margin-left:10px;color:var(--mut)">commands Claude Code runs on events, from your settings files</small>
  <button class=ghost style="margin-left:auto" id=hk_x>close</button></header><div class=body><div id=hk_list></div>
  <p class=note style="margin-top:10px">To add or change one, edit settings.json in Settings → Claude → Raw settings.</p></div></div></div>`;
 host.querySelector('.modal').onclick=e=>{if(e.target.classList.contains('modal'))closeModal()};
 $('#hk_x').onclick=closeModal;
 const L=$('#hk_list');
 if(!d.hooks.length)L.appendChild(el('<div class=note>No hooks are set.</div>'));
 d.hooks.forEach(h=>{const r=el('<div class=memrow style="gap:10px;align-items:baseline"><b style="flex:0 0 150px"></b><span class=note style="flex:0 0 110px"></span><code style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"></code></div>');
  r.querySelector('b').textContent=h.event;r.children[1].textContent=(h.matcher||'any tool')+' · '+h.source;
  r.querySelector('code').textContent=h.command;r.querySelector('code').title=h.command;L.appendChild(r)})}

async function openClaudeOptions(){
 const cur=(await (await fetch('/api/claude/info?sid='+encodeURIComponent(sid||''))).json()).settings||{};
 const host=$('#modalhost');
 host.innerHTML=`<div class=modal><div class="sheet" style="max-width:640px"><header><b>Claude Code options</b>
  <button class=ghost style="margin-left:auto" id=co_x>close</button></header><div class=body><div class=kv style="grid-template-columns:200px 1fr">
   <span>Model for subagents</span><span><input id=co_sub list=co_models placeholder="empty = follow Delegation settings" value="${esc(cur.subagent_model||'')}">
    <datalist id=co_models><option value=haiku><option value=sonnet><option value=opus></datalist></span>
   <span>Stop a run after (US$)</span><input id=co_budget type=number min=0 step=0.5 value="${esc(cur.max_budget_usd||0)}">
   <span>Show what subagents say</span><span><input type=checkbox id=co_fwd ${cur.forward_subagent_text?'checked':''}> <span class=note>their words and thinking under each subagent card</span></span>
   <span>Keep the chat warm for</span><span><select id=co_cache><option value="1h" ${(cur.prompt_cache_ttl??'1h')==='1h'?'selected':''}>1 hour</option><option value="5m" ${cur.prompt_cache_ttl==='5m'?'selected':''}>5 minutes</option><option value="" ${cur.prompt_cache_ttl===''?'selected':''}>Claude's own choice</option></select>
    <span class=note>a reply inside this time reads the chat from a cache; later, Claude reads all of it again</span></span>
   <span>Status line</span><span><input type=checkbox id=co_sl ${cur.show_statusline===false?'':'checked'}> <span class=note>show the line your Claude Code <code>statusLine</code> command prints</span></span>
   <span>Thinking budget (tokens)</span><span><input id=co_think type=number min=0 step=1000 value="${esc(cur.max_thinking_tokens||0)}"> <span class=note>most it thinks per step; 0 = Claude's own</span></span>
   <span>Sandbox shell commands</span><span><input type=checkbox id=co_sb ${cur.sandbox?'checked':''}> <span class=note>Bash runs inside Claude Code's sandbox: writes stay in the folder, no network unless allowed</span></span>
   <span>Compact at (tokens)</span><span><input id=co_ac placeholder="auto" value="${esc(cur.autocompact||'')}"> <span class=note>“auto” or a number</span></span>
  </div><div style="margin-top:12px"><button class=primary id=co_ok>Save</button> <span class=note id=co_msg></span></div>
  <p class=note>These apply from the next message. Empty and 0 leave Claude Code's own behaviour.</p></div></div></div>`;
 host.querySelector('.modal').onclick=e=>{if(e.target.classList.contains('modal'))closeModal()};
 $('#co_x').onclick=closeModal;
 $('#co_ok').onclick=async()=>{
  const {ok,d}=await J('/api/claude/settings',{settings:{subagent_model:$('#co_sub').value.trim(),max_budget_usd:parseFloat($('#co_budget').value)||0,
   forward_subagent_text:$('#co_fwd').checked,prompt_cache_ttl:$('#co_cache').value,max_thinking_tokens:parseInt($('#co_think').value)||0,sandbox:$('#co_sb').checked,show_statusline:$('#co_sl').checked,autocompact:$('#co_ac').value.trim()}});
  $('#co_msg').textContent=ok?'saved':'could not save';$('#co_msg').style.color=ok?'var(--ok)':'var(--err)'}}

/* The plan card: Claude's plan as a document, with the three ways Claude Code itself answers it. */
function planCard(p){
 const box=el('<div class="approve ccask plancard" tabindex=0></div>');
 box.appendChild(el('<div class=ccttl>Plan</div>'));
 const body=el('<div class="bub planbody"></div>');body.innerHTML=md(String(p.args.plan||''));try{decorate(body)}catch(e){}
 box.appendChild(body);
 box.appendChild(el('<div class=ccq>Do you want to carry out this plan?</div>'));
 const finish=async(allow,extra,label)=>{
  if(box._done)return;box._done=true;box.querySelectorAll('button,input').forEach(b=>b.disabled=true);
  let r;try{r=await fetch('/api/approve',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:p.id,allow,...extra})})}
  catch(e){box._done=false;box.querySelectorAll('button,input').forEach(b=>b.disabled=false);toast('could not reach Orbit — try again');return}
  box.classList.add('answered');box.innerHTML='';
  const d=el('<div class=ccdone></div>');d.textContent=r.ok?'⏺ Plan — '+label:'already answered — in another window, or it timed out';box.appendChild(d)};
 const feedback=()=>{
  if(box.querySelector('.whyrow'))return box.querySelector('.whyrow input').focus();
  const row=el('<div class="alwaysrow whyrow"></div>');const inp=document.createElement('input');inp.type='text';
  inp.placeholder='what should change in the plan? (Enter with nothing keeps planning)';
  const ok=el('<button>Keep planning</button>'),no=el('<button>Cancel</button>');
  ok.onclick=()=>{const m=inp.value.trim();finish(false,{message:m||'Keep planning: do not start yet. Revise the plan.'},'kept planning'+(m?': '+m:''))};
  inp.onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();ok.click()}if(e.key==='Escape'){e.preventDefault();row.remove()}};
  no.onclick=()=>row.remove();row.append(inp,ok,no);box.appendChild(row);inp.focus()};
 const opts=[
  {label:'Yes, and accept file edits without asking',act:()=>finish(true,{always:true,pattern:'mode:acceptEdits',note:'plan approved: accept edits'},'approved, edits accepted')},
  {label:'Yes, and ask me before each edit',act:()=>finish(true,undefined,'approved')},
  {label:'No, keep planning',hint:'esc',act:feedback}];
 const list=el('<div class=ccopts></div>');let sel=0;
 const draw=()=>[...list.children].forEach((r,i)=>r.classList.toggle('sel',i===sel));
 opts.forEach((o,i)=>{const r=el('<div class=ccopt><span class=ccptr>❯</span><span class=ccn></span><span class=ccl></span></div>');
  r.querySelector('.ccn').textContent=(i+1)+'.';r.querySelector('.ccl').textContent=o.label;
  if(o.hint)r.appendChild(el('<span class=cch>(esc)</span>'));
  r.onmouseenter=()=>{sel=i;draw()};r.onclick=()=>o.act();list.appendChild(r)});
 box.appendChild(list);draw();
 box._keys=e=>{
  if(box._done||!box.isConnected)return false;
  if(e.target&&e.target.closest&&e.target.closest('.alwaysrow'))return false;
  if(/^[1-3]$/.test(e.key)){opts[+e.key-1].act();return true}
  if(e.key==='ArrowDown'){sel=(sel+1)%opts.length;draw();return true}
  if(e.key==='ArrowUp'){sel=(sel+opts.length-1)%opts.length;draw();return true}
  if(e.key==='Enter'){opts[sel].act();return true}
  if(e.key==='Escape'){feedback();return true}
  return false};
 return box}
window.planCard=planCard;
/* Background sessions: Claude Code sessions that run on their own, with no window, and carry on if Orbit is closed. */
async function openBackground(){
 let cwd=await chatCwd();
 const host=$('#modalhost');
 host.innerHTML=`<div class=modal><div class="sheet" style="max-width:820px"><header><b>Background sessions</b>
  <small style="margin-left:10px;color:var(--mut)">Claude Code works on its own; close Orbit if you like</small>
  <button class=ghost style="margin-left:auto" id=bg_x>close</button></header><div class=body>
  <div id=bg_list></div><label class=note style="display:block;margin:6px 0"><input type=checkbox id=bg_open> also show sessions open in a window (read only)</label>
  <pre id=bg_logs style="display:none;max-height:260px;overflow:auto"></pre>
  <div class=sec>Start one</div>
  <div class=kv style="grid-template-columns:110px 1fr">
   <span>Task</span><textarea id=bg_prompt rows=3 placeholder="what it should do, in full — it cannot ask you questions"></textarea>
   <span>Folder</span><input id=bg_cwd spellcheck=false value="${esc(cwd)}">
   <span>Model</span><input id=bg_model list=bg_models placeholder="your Claude default"><datalist id=bg_models><option value=haiku><option value=sonnet><option value=opus></datalist>
   <span>Permissions</span><select id=bg_mode><option value="">Claude's own setting</option><option value=acceptEdits>accept file edits</option><option value=auto>auto</option><option value=plan>plan only (read, no changes)</option><option value=dontAsk>do not ask, deny what is not allowed</option></select></div>
  <div style="margin-top:10px"><button class=primary id=bg_go>Start in the background</button> <span class=note id=bg_msg></span></div>
  </div></div></div>`;
 host.querySelector('.modal').onclick=e=>{if(e.target.classList.contains('modal'))closeModal()};
 let timer=null;const stop=()=>{clearInterval(timer);timer=null};
 $('#bg_x').onclick=()=>{stop();closeModal()};
 const ago=t=>{const s=Math.max(0,Date.now()/1000-t);return s<90?Math.round(s)+'s':s<5400?Math.round(s/60)+'m':Math.round(s/3600)+'h'};
 let drawing=false,first=true;
 const draw=async()=>{
  if(!$('#bg_list')){stop();return}
  if(drawing)return;drawing=true;                       // a slow listing is waited for, not asked again behind itself
  if(first){$('#bg_list').innerHTML='<div class=note style="padding:6px 0">Looking…</div>';first=false}
  let res;try{res=await J('/api/ccfeatures',{op:'bg_list',all:true})}finally{drawing=false}
  const {ok,d}=res;
  const L=$('#bg_list');if(!L)return;L.innerHTML='';
  if(!ok){L.appendChild(el('<div class=note style="color:var(--err)"></div>')).textContent=d.error||'could not list';return}
  const showOpen=$('#bg_open').checked;
  const rows=d.sessions.filter(s=>showOpen||s.kind!=='interactive');
  if(!rows.length)L.appendChild(el('<div class=note style="padding:6px 0">Nothing running in the background.</div>'));
  rows.forEach(s=>{
   const r=el('<div class=memrow style="align-items:center;gap:10px"><span class=hdot></span><b style="flex:0 0 160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"></b><span class=note style="flex:0 0 130px"></span><span style="flex:1;color:var(--mut);overflow:hidden;text-overflow:ellipsis;white-space:nowrap"></span></div>');
   r.children[0].className='hdot'+(s.status==='busy'?' live':'');
   r.children[1].textContent=s.name||s.id;r.children[1].title=s.id;
   r.children[2].textContent=(s.kind==='interactive'?'open · ':'')+s.status+(s.started?' · '+ago(s.started):'');
   r.children[3].textContent=s.cwd;r.children[3].title=s.cwd;
   if(s.kind!=='interactive'){
    const btn=(t,fn)=>{const b=el('<button class=ghost></button>');b.textContent=t;b.onclick=fn;r.appendChild(b)};
    btn('logs',async()=>{const x=await J('/api/ccfeatures',{op:'bg_logs',id:s.id});const p=$('#bg_logs');p.style.display='';p.textContent=x.ok?(x.d.output||'(nothing yet)'):x.d.error;p.scrollTop=p.scrollHeight});
    btn('stop',async()=>{const x=await J('/api/ccfeatures',{op:'bg_stop',id:s.id});toast(x.ok?'stopped — its conversation is kept':x.d.error);draw()});
    btn('respawn',async()=>{const x=await J('/api/ccfeatures',{op:'bg_respawn',id:s.id});toast(x.ok?'restarted':x.d.error);draw()});
    btn('remove',async()=>{if(!confirm('Delete “'+(s.name||s.id)+'” and its worktree?'))return;const x=await J('/api/ccfeatures',{op:'bg_rm',id:s.id});toast(x.ok?'removed':x.d.error);draw()})}
   L.appendChild(r)})};
 $('#bg_open').onchange=draw;
 $('#bg_go').onclick=async()=>{
  const b=$('#bg_go');b.disabled=true;
  const {ok,d}=await J('/api/ccfeatures',{op:'bg_start',cwd:$('#bg_cwd').value.trim(),prompt:$('#bg_prompt').value,model:$('#bg_model').value.trim(),mode:$('#bg_mode').value});
  b.disabled=false;$('#bg_msg').textContent=ok?'started'+(d.id?' · '+d.id:''):(d.error||'could not start');$('#bg_msg').style.color=ok?'var(--ok)':'var(--err)';
  if(ok){$('#bg_prompt').value='';draw()}};
 draw();timer=setInterval(draw,6000)}
async function startBackground(prompt){
 const cwd=await chatCwd();
 const {ok,d}=await J('/api/ccfeatures',{op:'bg_start',cwd,prompt});
 toast(ok?'started in the background'+(d.id?' · '+d.id:'')+' — /background shows it':(d.error||'could not start it'))}
window.openBackground=openBackground;window.startBackground=startBackground;
/* MCP servers: which are connected, signing in to the ones that need it, and reloading plugins and skills. */
async function reloadPlugins(){
 const {ok,d}=await J('/api/ccfeatures',{op:'reload_plugins',sid});
 toast(ok?(d.note||'plugins and skills reloaded'):(d.error||'could not reload'))}
async function openMcp(){
 const cwd=await chatCwd();
 const host=$('#modalhost');
 host.innerHTML=`<div class=modal><div class="sheet" style="max-width:760px"><header><b>MCP servers</b>
  <small style="margin-left:10px;color:var(--mut)">the tools Claude Code can reach, and signing in to those that need it</small>
  <button class=ghost style="margin-left:auto" id=mcp_x>close</button></header><div class=body>
  <div style="margin-bottom:8px"><button class=ghost id=mcp_reload>Reload plugins and skills</button> <button class=ghost id=mcp_again>Check again</button></div>
  <div id=mcp_list class=note>Checking each server — a few seconds…</div><div id=mcp_paste></div></div></div></div>`;
 host.querySelector('.modal').onclick=e=>{if(e.target.classList.contains('modal'))closeModal()};
 let polls=[];const clearPolls=()=>{polls.forEach(clearInterval);polls=[]};
 $('#mcp_x').onclick=()=>{clearPolls();closeModal()};
 $('#mcp_reload').onclick=reloadPlugins;
 const NEEDS=s=>/auth/i.test(s||'');
 const draw=async()=>{
  const L=$('#mcp_list');if(!L)return;L.className='note';L.textContent='Checking each server — a few seconds…';
  const {ok,d}=await J('/api/ccfeatures',{op:'mcp_list',cwd});
  if(!$('#mcp_list'))return;L.className='';L.innerHTML='';
  if(!ok){L.className='note';L.style.color='var(--err)';L.textContent=d.error||'could not check';return}
  if(!d.servers.length)L.appendChild(el('<div class=note>No MCP servers are set up.</div>'));
  d.servers.forEach(s=>{
   const r=el('<div class=memrow style="align-items:center;gap:10px"><span class=hdot></span><b style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"></b><span class=note style="flex:0 0 110px"></span></div>');
   r.children[0].className='hdot'+(s.status==='connected'?' live':'');
   r.children[1].textContent=s.name;r.children[2].textContent=s.status;
   if(NEEDS(s.status)){const b=el('<button class=primary>Sign in</button>');b.onclick=()=>signIn(s.name,b);r.appendChild(b)}
   else if(s.status==='connected'&&s.config&&s.config.type&&/http|sse/.test(s.config.type)){
    const b=el('<button class=ghost>Sign out</button>');b.onclick=async()=>{if(!confirm('Sign out of '+s.name+'?'))return;const x=await J('/api/ccfeatures',{op:'mcp_clear',server:s.name,cwd});toast(x.ok?'signed out':x.d.error);draw()};r.appendChild(b)}
   L.appendChild(r)})};
 const signIn=async(name,btn)=>{
  btn.disabled=true;btn.textContent='Opening…';
  const {ok,d}=await J('/api/ccfeatures',{op:'mcp_auth',server:name,cwd});
  if(!ok){btn.disabled=false;btn.textContent='Sign in';toast(d.error||'could not start signing in');return}
  window.open(d.url,'_blank');btn.textContent='Waiting for you…';
  const P=$('#mcp_paste');P.innerHTML='<div class=note style="margin-top:10px">Finish signing in in the browser tab that opened. If it ends on a page that cannot be reached, paste that page\'s address here:</div><div class=alwaysrow><input id=mcp_cb placeholder="http://localhost:…/callback?code=…" spellcheck=false><button id=mcp_cbgo>Send</button></div>';
  $('#mcp_cbgo').onclick=async()=>{const x=await J('/api/ccfeatures',{op:'mcp_auth_callback',server:name,url:$('#mcp_cb').value.trim(),cwd});toast(x.ok?'sent':x.d.error);if(x.ok){clearPolls();P.innerHTML='';draw()}};
  const t=setInterval(async()=>{
   if(!$('#mcp_list')){clearInterval(t);return}
   const {d:st}=await J('/api/ccfeatures',{op:'mcp_auth_state',server:name});
   if(st.state==='done'){clearPolls();P.innerHTML='';toast('signed in to '+name);draw()}
   else if(st.state==='failed'){clearPolls();toast(st.error||'sign-in failed');btn.disabled=false;btn.textContent='Sign in'}
   else if(st.state==='none'){clearPolls();btn.disabled=false;btn.textContent='Sign in'}},2000);
  polls.push(t)};
 $('#mcp_again').onclick=draw;
 draw()}
window.openMcp=openMcp;window.reloadPlugins=reloadPlugins;
/* The status line: what your Claude Code statusLine command prints, in the footer. */
let _slAt=0;
async function drawStatusLine(info){
 let n=document.querySelector('#ccstatus');
 if(!n){const bar=document.querySelector('#enginebar');if(!bar)return;n=el('<span id=ccstatus class=ccstatus></span>');
  const at=bar.querySelector('.ebsp');bar.insertBefore(n,at)}
 if(!info||!isClaudeChat()||!sid){n.style.display='none';return}
 const now=Date.now();if(now-_slAt<4000)return;_slAt=now;
 try{const {d}=await J('/api/ccfeatures',{op:'statusline',cwd:info.cwd||'',session:info.session||'',
   model:(MODELS.current||MODELS.default||''),model_name:(document.querySelector('#engmodel,.engmodel')||{}).textContent||'',cost:(info.prefs||{}).cost_usd||0});
  n.textContent=d.text||'';n.title=d.text||'';n.style.display=d.text?'':'none'}catch(e){n.style.display='none'}}
window.drawStatusLine=drawStatusLine;

/* Shortcuts: your own key for an action, added to the built-in ones; and Claude Code's own keybindings.json for the terminal. */
const ACTIONS={
 newchat:['New chat',()=>newChat()],find:['Search chats',()=>openPal()],settings:['Settings',()=>openSettings()],
 terminal:['Terminal',()=>toggleTerm(true)],verbose:['Show every tool call',()=>setVerbose(!VERBOSE)],todos:['Todo list',()=>togglePlanDock()],
 mode:['Cycle permission mode',()=>cycleMode()],shortcuts:['Keyboard shortcuts',()=>showShortcuts()],jump:['Jump to a message',()=>openJump()],
 background:['Background sessions',()=>openBackground()],subagents:['Subagents',()=>openSubagents()],mcp:['MCP servers',()=>openMcp()],
 compact:['Compact this chat',()=>doCompact()]};
const combo=e=>{const k=e.key;if(!k||['Control','Shift','Alt','Meta'].includes(k))return '';
 return [e.metaKey?'Cmd':'',e.ctrlKey?'Ctrl':'',e.altKey?'Alt':'',e.shiftKey?'Shift':'',k.length===1?k.toUpperCase():k].filter(Boolean).join('+')};
const myKeys=()=>{try{return JSON.parse(PREF.get('mykeys','{}'))||{}}catch(e){return {}}};
addEventListener('keydown',e=>{
 if(e.repeat||(typeof composing==='function'&&composing(e)))return;
 const c=combo(e);if(!c||!/Cmd|Ctrl|Alt/.test(c))return;       // a bare key is never a shortcut: it is typing
 const m=myKeys();const act=Object.keys(m).find(k=>m[k]===c);
 if(act&&ACTIONS[act]){e.preventDefault();e.stopImmediatePropagation();ACTIONS[act][1]()}},true);
async function openKeys(){
 const kb=(await J('/api/ccfeatures',{op:'keybindings'})).d;
 const host=$('#modalhost');
 host.innerHTML=`<div class=modal><div class="sheet" style="max-width:700px"><header><b>Shortcuts</b>
  <small style="margin-left:10px;color:var(--mut)">yours, added to the built-in ones</small>
  <button class=ghost style="margin-left:auto" id=ky_x>close</button></header><div class=body>
  <div id=ky_list></div>
  <p class=note>Click a box and press the keys (with ⌘, Ctrl or Alt). Esc in the box clears it. Built-in shortcuts stay as they are: <a style="cursor:pointer;color:var(--acc)" id=ky_all>see them all</a>.</p>
  <div class=sec>Claude Code's own keybindings <small>(the terminal's — ${esc(kb.path||'')})</small></div>
  <textarea id=ky_json rows=8 spellcheck=false style="width:100%;font-family:var(--mono);font-size:var(--fs-code-sm)" placeholder='{ "bindings": [ ... ] } — empty means Claude Code's own'>${esc(kb.text||'')}</textarea>
  <div style="margin-top:8px"><button class=primary id=ky_save>Save keybindings.json</button> <span class=note id=ky_msg></span></div>
  </div></div></div>`;
 host.querySelector('.modal').onclick=e=>{if(e.target.classList.contains('modal'))closeModal()};
 $('#ky_x').onclick=closeModal;$('#ky_all').onclick=()=>showShortcuts();
 const m=myKeys(),L=$('#ky_list');
 Object.entries(ACTIONS).forEach(([k,[label]])=>{
  const r=el('<div class=memrow style="align-items:center;gap:10px"><span style="flex:1"></span><input readonly style="width:170px;text-align:center;cursor:pointer" placeholder="not set"></div>');
  r.firstChild.textContent=label;const inp=r.querySelector('input');inp.value=m[k]||'';
  inp.onkeydown=e=>{e.preventDefault();e.stopPropagation();
   if(e.key==='Escape'){const cur=myKeys();delete cur[k];PREF.set('mykeys',JSON.stringify(cur));inp.value='';return}
   const c=combo(e);if(!c)return;
   if(!/Cmd|Ctrl|Alt/.test(c)){toast('add ⌘, Ctrl or Alt — a plain key is for typing');return}
   const cur=myKeys();Object.keys(cur).forEach(o=>{if(cur[o]===c&&o!==k)delete cur[o]});cur[k]=c;PREF.set('mykeys',JSON.stringify(cur));
   [...L.querySelectorAll('input')].forEach(i=>{if(i!==inp&&i.value===c)i.value=''});inp.value=c};
  L.appendChild(r)});
 $('#ky_save').onclick=async()=>{const {ok,d}=await J('/api/ccfeatures',{op:'keybindings_save',text:$('#ky_json').value});
  $('#ky_msg').textContent=ok?'saved (the old file is kept as keybindings.json.orbit-bak)':(d.error||'could not save');$('#ky_msg').style.color=ok?'var(--ok)':'var(--err)'}}
window.openKeys=openKeys;

/* Cloud sessions and pull requests: Claude Code's own interactive pickers, opened in Orbit's terminal. */
async function runInTerminal(cmd){
 await toggleTerm(true);
 for(let i=0;i<30&&!(typeof TERMS!=='undefined'&&TERMS.active);i++)await new Promise(r=>setTimeout(r,150));
 const id=typeof TERMS!=='undefined'?TERMS.active:null;
 if(id){await fetch('/api/term/input',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id,data:cmd})});
  toast('typed into the terminal — press Enter to run it')}
 else{try{await navigator.clipboard.writeText(cmd)}catch(e){}toast('copied: '+cmd+' — paste it into a terminal')}}
function openCloud(){
 const host=$('#modalhost');
 host.innerHTML=`<div class=modal><div class="sheet" style="max-width:600px"><header><b>Cloud sessions and pull requests</b>
  <button class=ghost style="margin-left:auto" id=cl_x>close</button></header><div class=body>
  <p class=note>These are Claude Code's own pickers and need a terminal, so Orbit types the command into its terminal for you. Run it in this chat's folder.</p>
  <div class=kv style="grid-template-columns:150px 1fr">
   <span>Cloud session</span><span><input id=cl_tp placeholder="session id or name (empty: pick from a list)"> <button class=ghost id=cl_tpgo>Continue here</button></span>
   <span>Pull request</span><span><input id=cl_pr placeholder="PR number or URL (empty: pick from a list)"> <button class=ghost id=cl_prgo>Resume its session</button></span>
   <span>Remote control</span><span><input id=cl_rc placeholder="name (optional)"> <button class=ghost id=cl_rcgo>Start</button> <span class=note>drive this session from your phone or claude.ai</span></span>
  </div></div></div></div>`;
 host.querySelector('.modal').onclick=e=>{if(e.target.classList.contains('modal'))closeModal()};
 $('#cl_x').onclick=closeModal;
 const safe=v=>/^[\w@%+=:,./#?&~ -]*$/.test(v)&&!/^\s*-/.test(v);
 const go=cmd=>{closeModal();runInTerminal(cmd)};
 $('#cl_tpgo').onclick=()=>{const v=$('#cl_tp').value.trim();if(!safe(v))return toast('that does not look like a session id');go('claude --teleport'+(v?" '"+v+"'":''))};
 $('#cl_prgo').onclick=()=>{const v=$('#cl_pr').value.trim();if(!safe(v))return toast('that does not look like a pull request');go('claude --from-pr'+(v?" '"+v+"'":''))};
 $('#cl_rcgo').onclick=()=>{const v=$('#cl_rc').value.trim();if(!safe(v))return toast('use letters, digits and dashes');go('claude --remote-control'+(v?" '"+v+"'":''))}}
window.openCloud=openCloud;
/* The side panel (wide screens): besides this chat's own status, what is going on in your other chats. */
const wide=()=>matchMedia('(min-width:1640px)').matches&&PREF.get('rail','1')!=='0';
async function drawRailTasks(){
 const n=document.querySelector('#railtasks');if(!n)return;
 if(!wide()||document.hidden){n.style.display='none';return}
 let d;try{d=await (await fetch('/api/tasks')).json()}catch(e){return}
 const mine=sid,items=(d.items||[]).filter(t=>t.sid!==mine&&(t.kind==='answer'||(t.kind==='background'&&t.running)||t.kind==='shell'||t.kind==='queued'&&!/^at /.test(t.status||'')));
 if(!items.length){n.style.display='none';n.innerHTML='';return}
 n.style.display='';n.innerHTML='<div class=rthead><b>Elsewhere</b><span class=note>your other chats</span><button class=ghost title="hide the side panel (/side brings it back)">×</button></div>';
 n.querySelector('button').onclick=()=>{PREF.set('rail','0');drawRailTasks();toast('side panel hidden — /side brings it back')};
 const by={};items.forEach(t=>{(by[t.sid||t.id]=by[t.sid||t.id]||[]).push(t)});
 Object.values(by).slice(0,6).forEach(ts=>{
  const t=ts[0],title=t.chat||t.title||'chat';
  const bits=[];const a=ts.find(x=>x.kind==='answer');if(a)bits.push('answering'+(a.since?' '+fmtSecs(d.now-a.since):''));
  const bg=ts.filter(x=>x.kind==='background');if(bg.length)bits.push(bg.length+' in the background');
  const q=ts.filter(x=>x.kind==='queued');if(q.length)bits.push(q.length+' queued');
  const r=el('<div class=rtrow><span class=hdot></span><b></b><span class=note></span></div>');
  r.children[0].className='hdot'+(a?' live':'');r.children[1].textContent=title;r.children[2].textContent=bits.join(' · ');
  if(t.sid)r.onclick=()=>openSession(t.sid);n.appendChild(r)})}
setInterval(drawRailTasks,7000);setTimeout(drawRailTasks,1500);
window.drawRailTasks=drawRailTasks;
window.toggleSide=()=>{PREF.set('rail',PREF.get('rail','1')==='0'?'1':'0');
 document.querySelector('#rail').classList.toggle('off',PREF.get('rail','1')==='0');drawRailTasks();
 toast(PREF.get('rail','1')==='0'?'side panel hidden':'side panel on (wide screens)')};
document.querySelector('#rail')&&document.querySelector('#rail').classList.toggle('off',PREF.get('rail','1')==='0');
/* Text width: the reading column, normal / wide / full. The side panel steps aside when there is no room left for it. */
const WIDTHS={normal:760,wide:980,full:1240};
function applyWidth(){
 const k=PREF.get('colw','normal');const w=WIDTHS[k]||760;
 document.documentElement.style.setProperty('--colw',w+'px');
 const rail=document.querySelector('#rail');
 if(rail){const gutter=(innerWidth-300-w-20)/2-12;rail.classList.toggle('noroom',gutter<240)}}
addEventListener('resize',applyWidth);applyWidth();
window.cycleWidth=()=>{const ks=Object.keys(WIDTHS),cur=PREF.get('colw','normal');const next=ks[(ks.indexOf(cur)+1)%ks.length];
 PREF.set('colw',next);applyWidth();toast('text width: '+next+' ('+WIDTHS[next]+' px)')};
window.setNotifyLong=async rest=>{
 if(rest===''||rest==null){const {d}=await J('/api/ccfeatures',{op:'notify_get'});toast(d.minutes?'notifying when an answer takes over '+d.minutes+' min (/notify 0 turns it off)':'long-answer notifications are off (/notify 5 turns them on)');return}
 const {ok,d}=await J('/api/ccfeatures',{op:'notify_set',minutes:rest});
 toast(ok?(d.minutes?'will notify when something takes over '+d.minutes+' min':'notifications for long answers are off'):d.error)};
/* Is the chat still warm? Claude keeps what it has read for a while after each answer; replying inside that time is quick
   and cheap, replying after it makes Claude read the whole conversation again. Shown for Claude subscription chats. */
function drawCacheChip(info){
 const bar=document.querySelector('#cqbar');if(!bar)return;
 let n=bar.querySelector('.cqcache');
 if(!n){n=el('<span class=cqcache style="display:none"></span>');const at=bar.querySelector('.cqcost')||bar.querySelector('.cqdir');at.after(n)}
 const model=(MODELS.current||MODELS.default||'');
 const row=(SESSIONS||[]).find(s=>s.id===sid),answered=row&&row.answered;
 if(!info||!answered||RUNNING.has(sid)||!model.startsWith('harness:claude/')){n.style.display='none';return}
 const set=(info.settings||{}).prompt_cache_ttl;
 const ttl=set==='5m'?300:3600;                 // "" (Claude's own choice) is an hour on a subscription
 const left=ttl-(Date.now()/1000-answered);
 n.style.display='';
 if(left>0){const m=Math.ceil(left/60);n.textContent='warm · '+(m>=60?Math.round(m/60*10)/10+' h':m+' min');n.className='cqcache warm';
  n.title='Claude still has this chat cached: a reply now is fast and cheap. The cache stays warm for '+(ttl/60)+' minutes after each answer.'}
 else{n.textContent='cold';n.className='cqcache cold';
  n.title='The cache has run out: your next message makes Claude read the whole chat again (slower, and it counts for more of your usage). /compact first if the chat is long.'}}
window.drawCacheChip=drawCacheChip;setInterval(()=>{try{drawCacheChip(CQ_INFO)}catch(e){}},30000);
window.openSubagents=openSubagents;window.openHooks=openHooks;window.openClaudeOptions=openClaudeOptions;
})();
