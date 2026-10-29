
const $=s=>document.querySelector(s), wrap=$('#wrap'), q=$('#q'), log=$('#log');
// the box grows with what you type, up to 200px; an empty box goes back to one line (its
// placeholder wraps when the box is briefly narrow, and used to set a tall height)
function fitQ(){q.style.height='auto';if(!q.value){q.style.height='';return}
 q.style.height=Math.min(q.scrollHeight,200)+'px'}
let GROUP_BY='date';            // the chat list by date, or by project
let atts=[], sid=null, busy=false, stoppedSid=null, RUNNING=new Set(), INFO={tools:[],settings:{}}, SESSIONS=[], PROMPTS={}, filterMode='active';
// Chats this TAB is actively streaming right now, kept independently of RUNNING —
// RUNNING is refreshed from the server every couple of seconds and a stale
// response landing right as a send begins could otherwise report "not busy" for
// a fraction of a second, which was enough for the watcher below to reload the
// page mid-answer and orphan the real stream behind a wiped transcript.
let SENDING=new Set();
// chats with news you have not looked at (an answer, an approval, an error)
const UNSEEN={};
let PASTES={}, pasteN=0, PLANS={}, histPos=-1, draftT=null;

const CMDS=[
 {c:'/new',d:'start a fresh chat'},
 {c:'/rename',d:'rename this chat: /rename <title>'},
 {c:'/handoff',d:'a note to carry this chat on in Claude desktop, or another Claude session'},
 {c:'/crew',d:'a builder and a reviewer that keep improving a project until you stop them'},
 {c:'/cluster',d:'your jobs, the queue, the disk, the GPUs and what went wrong on the cluster'},
 {c:'/delegate',d:'let this chat hand small tasks to cheaper models: on, off, or auto (follow Settings)'},
 {c:'/compact',d:'summarise history to free context'},
 {c:'/easy',d:'easy mode on/off — only the essential tools'},
 {c:'/settings',d:'open settings'},
 {c:'/memory',d:'memory and instructions'},
 {c:'/prompts',d:'saved prompts'},
 {c:'/knowledge',d:'your document library'},
 {c:'/agents',d:'agent presets'},
 {c:'/skills',d:'saved procedures'},
 {c:'/tools',d:'list active tools'},
 {c:'/status',d:'server, memory, speed'},
 {c:'/doctor',d:'check deps, disk, server, config for problems'},
 {c:'/remember',d:'save a note to memory: /remember <text>'},
 {c:'/export',d:'download this chat as markdown'},
 {c:'/later',d:'send later: /later 21:30 <message>, /later tomorrow 9am …, /later daily 8:00 …'},
 {c:'/scheduled',d:'messages scheduled to send, in every chat'},
 {c:'/files',d:'every file this chat mentions or wrote — open, preview, copy'},
 {c:'/jump',d:'jump to one of your messages in this chat (⌘G)'},
 {c:'/stats',d:'usage: turns, tokens and time per model'},
 {c:'/plan',d:'plan mode: it may read and think but change nothing'},
 {c:'/build',d:'leave plan mode: it may make changes again'},
 {c:'/sound',d:'toggle a short beep when an answer finishes while you are away'},
 {c:'/find',d:'find text in this chat (⌘F)'},
 {c:'/foldtools',d:'fold a finished turn\'s steps behind one line'},
 {c:'/hidetools',d:'hide or show finished tool rows'},
 {c:'/clear',d:'clear the screen only'},
 {c:'/start',d:'start the model server'},
 {c:'/restart',d:'restart the server (applies settings)'},
 {c:'/stop',d:'stop the model server (frees ~15 GB)'},
 {c:'/rewind',d:'go back to an earlier message — chat only, or files too (Esc Esc)'},
 {c:'/context',d:'what is filling the context window right now'},
 {c:'/copy',d:'copy the last answer (/copy 2 for the one before)'},
 {c:'/diff',d:'every file this answer changed, as a diff'},
 {c:'/goal',d:'keep working until it is done — /goal <what done looks like>; alone, shows the goal'},
 {c:'/guide',d:'the user guide: everything Orbit does and how to use it'},
 {c:'/worktree',d:'work in a copy of the repository on a branch of its own — merge it back or throw it away'},
 {c:'/terminal',d:'a shell in this chat\'s folder, at the foot of the window (Ctrl+`)'},
 {c:'/verbose',d:'show every tool call in full, or fold them again (Ctrl+O)'},
 {c:'/todos',d:'show or hide the todo list (Ctrl+T)'},
 {c:'/usage',d:'how much of your Claude plan is used (in Claude Code mode) · cost, tokens and time'},
 {c:'/model',d:'switch the model for this chat'},
 {c:'/permissions',d:'what it may do without asking'},
 {c:'/theme',d:'light, dark or follow the system'},
 {c:'/fork',d:'copy this chat into a new one and carry on there'},
 {c:'/shortcuts',d:'every keyboard shortcut'},
 {c:'/tasks',d:'everything running in the background — answers, queued messages, shell jobs'},
 {c:'/help',d:'show these commands'}];

function esc(s){return String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
/* ---------------- rendering answers ----------------
 Markdown the way models write it: GitHub-flavoured (tables with alignment, task
 lists, strikethrough, nested lists, autolinks), math ($…$, $$…$$, \(…\), \[…\]),
 callouts (> [!NOTE]), footnotes, ==highlights==, Mermaid, highlighted code, and a
 little safe HTML (<details>, <kbd>, <sub>, <br> in tables…). Everything is
 sanitised: an answer can format itself but never run script in Orbit's page. */
function attr(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
const MATH_CACHE=new Map();
function katexHtml(tex,display){
 if(!window.katex)return null;
 const k=(display?'D':'I')+tex;
 if(MATH_CACHE.has(k))return MATH_CACHE.get(k);
 let h=null;
 try{h=katex.renderToString(tex,{displayMode:display,throwOnError:false,output:'htmlAndMathml',strict:'ignore',trust:false})}catch(e){}
 if(h!==null){if(MATH_CACHE.size>1500)MATH_CACHE.clear();MATH_CACHE.set(k,h)}
 return h}
// math and footnote references are lifted out before Markdown sees them, so `_`, `*`
// and `|` inside a formula are never read as emphasis or table cells; code is left alone
function mdProtect(src){
 const maths=[],notes={},order=[];
 const lines=String(src).split('\n'),out=[];let fence=null,buf=[];
 const flush=()=>{if(buf.length){out.push(mdInline(buf.join('\n'),maths,notes,order));buf=[]}};
 for(const line of lines){
  const f=line.match(/^\s{0,3}(`{3,}|~{3,})/);
  if(fence){out.push(line);
   if(f&&f[1][0]===fence[0]&&f[1].length>=fence.length&&/^\s{0,3}(`{3,}|~{3,})\s*$/.test(line))fence=null;continue}
  if(f){flush();fence=f[1];out.push(line);continue}
  const def=line.match(/^\[\^([^\]\s]{1,40})\]:\s+(.*)$/);
  if(def){notes[def[1]]=(notes[def[1]]||'')+def[2];continue}
  buf.push(line)}
 flush();
 return {text:out.join('\n'),maths,notes,order}}
function mdInline(s,maths,notes,order){
 let res='',last=0,m;const re=/(`+)(?:[\s\S]*?[^`])\1(?!`)/g;
 while((m=re.exec(s))){res+=mdMathSeg(s.slice(last,m.index),maths,order)+m[0];last=m.index+m[0].length}
 return res+mdMathSeg(s.slice(last),maths,order)}
function mdMathSeg(s,maths,order){
 const put=(tex,disp,raw)=>{maths.push({tex,disp,raw});return '\u2063M'+(maths.length-1)+'\u2063'};
 s=s.replace(/\$\$([\s\S]+?)\$\$/g,(m,x)=>put(x,true,m));
 s=s.replace(/\\\[([\s\S]+?)\\\]/g,(m,x)=>put(x,true,m));
 s=s.replace(/\\\(([\s\S]+?)\\\)/g,(m,x)=>put(x,false,m));
 // $x$ — but not prices: "$5 and $10", "$5-$10", "US$3"
 s=s.replace(/(^|[^\\$\w])\$(?![\s$])([^$\n]{1,400}?)(?<![\s\\])\$(?![\w$])/g,(m,pre,x)=>
  /^[\d.,\s]+$/.test(x)?m:pre+put(x,false,m.slice(pre.length)));
 s=s.replace(/\[\^([^\]\s]{1,40})\](?!:)/g,(m,id)=>{if(!order.includes(id))order.push(id);return '\u2063F'+id+'\u2063'});
 return s}
const CALLOUT_RE=/^\s*\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION|INFO|SUCCESS|DANGER|QUESTION|EXAMPLE|BUG|ABSTRACT|SUMMARY|TODO|QUOTE|FAILURE|ERROR|HINT|ATTENTION)\]([+-]?)[ \t]*([^\n]*)\n?/i;
const CALLOUT_KIND={note:'note',info:'note',todo:'note',abstract:'note',summary:'note',quote:'note',tip:'tip',hint:'tip',success:'tip',example:'tip',
 important:'important',question:'important',warning:'warning',attention:'warning',caution:'caution',danger:'caution',failure:'caution',error:'caution',bug:'caution'};
const SHELL_LANGS=new Set(['bash','sh','zsh','shell','console','terminal','shellsession','fish','ksh','command','cmd-mac']);
let MD_READY=false;
function mdSetup(){
 if(MD_READY)return true;
 if(!window.marked||!window.DOMPurify)return false;
 const base=new marked.Renderer();
 marked.use({gfm:true,breaks:true,
  renderer:{
   code(tok){return codeHtml(tok.text||'',tok.lang||'')},
   table(tok){return '<div class=tblwrap>'+base.table.call(this,tok)+'</div>'},
   blockquote(tok){
    const m=CALLOUT_RE.exec(tok.text||'');if(!m)return false;
    const kind=m[1].toLowerCase(),cls=CALLOUT_KIND[kind]||'note';
    const inner=this.parser.parse(marked.Lexer.lex((tok.text||'').slice(m[0].length),this.options));
    const title=m[3]?marked.parseInline(m[3]):kind[0].toUpperCase()+kind.slice(1);
    return `<div class="callout c-${cls}"><div class=ctitle>${title}</div>${inner}</div>`},
   link(tok){
    const text=this.parser.parseInline(tok.tokens),href=String(tok.href||''),ttl=tok.title?` title="${attr(tok.title)}"`:'';
    if(/^(https?:|mailto:|tel:)/i.test(href))return `<a href="${attr(href)}" target=_blank rel="noopener noreferrer"${ttl}>${text}</a>`;
    if(href.startsWith('#'))return `<a href="${attr(href)}"${ttl}>${text}</a>`;
    if(/^(file:|\/|~\/|\.{1,2}\/)/.test(href)||/^[\w@+.-]+(\/[\w@ +.%-]+)*\.[A-Za-z0-9]{1,10}(:\d+(:\d+)?|#L\d+)?$/.test(href)||/^[\w@+.-]+(\/[\w@+.%-]+)+\/?$/.test(href)){
     let p=href;try{p=decodeURI(href)}catch(e){}
     return `<span class="pathlink pathcand" data-path="${attr(p)}" title="${attr(p)}">${text}</span>`}
    return text},
   image(tok){
    const src=String(tok.href||''),alt=attr(tok.text||''),ttl=tok.title?` title="${attr(tok.title)}"`:'';
    if(/^(https?:|data:image\/)/i.test(src))return `<img class=mdimg src="${attr(src)}" alt="${alt}"${ttl} loading=lazy>`;
    let p=src;try{p=decodeURI(src)}catch(e){}
    return `<img class="mdimg localimg" data-localsrc="${attr(p)}" alt="${alt}"${ttl}>`},
   checkbox(tok){return `<input type=checkbox disabled${tok.checked?' checked':''}> `}},
  extensions:[{name:'mark',level:'inline',start(src){const i=src.indexOf('==');return i<0?undefined:i},
   tokenizer(src){const m=/^==(?=[^\s=])([^\n]*?[^\s=])==(?!=)/.exec(src);
    if(m)return {type:'mark',raw:m[0],tokens:this.lexer.inlineTokens(m[1])}},
   renderer(t){return '<mark>'+this.parser.parseInline(t.tokens)+'</mark>'}}]});
 DOMPurify.addHook('afterSanitizeAttributes',n=>{
  if(n.tagName==='A'&&/^https?:/i.test(n.getAttribute('href')||'')){n.setAttribute('target','_blank');n.setAttribute('rel','noopener noreferrer')}});
 MD_READY=true;return true}
const PURIFY={ADD_ATTR:['target','loading','data-path','data-localsrc','data-lang','data-src','data-fn','data-line'],
 FORBID_TAGS:['style','form','iframe','object','embed','link','meta','base','textarea','select','option','script','frame','frameset','applet'],
 FORBID_ATTR:['srcset','action','formaction','autofocus']};
function md(t){
 t=String(t??'');
 if(!mdSetup())return legacyMd(t);
 const P=mdProtect(t);
 let html;
 try{html=marked.parse(P.text)}catch(e){return legacyMd(t)}
 if(P.order.length||Object.keys(P.notes).length){
  const ids=P.order.filter(id=>P.notes[id]!=null).concat(Object.keys(P.notes).filter(id=>!P.order.includes(id)));
  if(ids.length)html+='<section class=footnotes><ol>'+ids.map(id=>
   `<li data-fn="${attr(id)}">${marked.parseInline(mdProtectInline(P.notes[id],P))}</li>`).join('')+'</ol></section>'}
 html=DOMPurify.sanitize(html,PURIFY);
 if(html.includes('\u2063')&&/=["'][^"']*\u2063/.test(html)){
  // a formula inside an attribute (a link title, an image's alt text) stays plain text
  const tpl=document.createElement('template');tpl.innerHTML=html;
  tpl.content.querySelectorAll('*').forEach(n=>[...n.attributes].forEach(a=>{if(a.value.includes('\u2063'))
   n.setAttribute(a.name,a.value.replace(/\u2063M(\d+)\u2063/g,(m,i)=>(P.maths[+i]||{}).raw||'').replace(/\u2063F([^\u2063]{1,40})\u2063/g,'[$1]'))}));
  html=tpl.innerHTML}
 html=html.replace(/\u2063M(\d+)\u2063/g,(m,i)=>{const x=P.maths[+i];if(!x)return '';
  const h=katexHtml(x.tex,x.disp);return h!==null?(x.disp?`<span class=mathblock>${h}</span>`:h):esc(x.raw)});
 html=html.replace(/\u2063F([^\u2063]{1,40})\u2063/g,(m,id)=>{
  const n=P.order.indexOf(id)+1;return `<sup class=fnref data-fn="${attr(id)}">${n||esc(id)}</sup>`});
 return html}
function mdProtectInline(s,P){return mdMathSeg(String(s),P.maths,P.order)}
// the renderer before marked was loaded (kept for a page whose scripts failed to load)
function legacyMd(t){
 const blocks=[];
 t=String(t).replace(/```(\w*)\n([\s\S]*?)```/g,(m,l,b)=>{blocks.push([l,b]);return `@@CB${blocks.length-1}@@`});
 t=esc(t);
 t=t.replace(/^### (.*)$/gm,'<h3>$1</h3>').replace(/^## (.*)$/gm,'<h2>$1</h2>').replace(/^# (.*)$/gm,'<h1>$1</h1>');
 t=t.replace(/\*\*([^*]+)\*\*/g,'<b>$1</b>').replace(/`([^`]+)`/g,'<code>$1</code>');
 t=t.replace(/\[([^\]]+)\]\((https?:[^)\s"]+)\)/g,'<a href="$2" target=_blank rel=noopener>$1</a>');
 t=t.split(/\n{2,}/).map(p=>`<p>${p.replace(/\n/g,'<br>')}</p>`).join('');
 return t.replace(/@@CB(\d+)@@/g,(m,i)=>codeHtml(blocks[i][1],blocks[i][0]))}
const MERMAID_RE=/^\s*(graph\s|flowchart\s|sequenceDiagram|classDiagram|erDiagram|gantt|pie(\s|$)|stateDiagram|journey|gitGraph|mindmap|timeline|quadrantChart|xychart-beta|sankey-beta|block-beta|C4Context|requirementDiagram|kanban|architecture-beta)/;
function codeHtml(text,lang){
 const info=String(lang||'').trim(), l=info.split(/[\s{:,]/)[0].toLowerCase().replace(/^\./,'');
 const title=(info.match(/(?:title|file(?:name)?)=["']?([^"'\s}]+)/)||[])[1]||(/[./]/.test(l)&&/\.\w+$/.test(l)?l:'');
 const lang_=title&&title===l?(l.split('.').pop()):l;
 if(lang_==='mermaid'||(!lang_&&MERMAID_RE.test(text)))
  return `<div class=mermaid data-src="${attr(text)}">${esc(text)}</div>`;
 let body=esc(text),hl='';
 if(window.hljs&&text.length<80000&&lang_){
  const alias={shell:'bash',sh:'bash',zsh:'bash',console:'bash',terminal:'bash',py:'python',js:'javascript',ts:'typescript',
   yml:'yaml',md:'markdown',rmd:'markdown',jsonl:'json',ipynb:'json',html:'xml',svg:'xml',htm:'xml',csv:'plaintext',tsv:'plaintext',
   text:'plaintext',txt:'plaintext',snakemake:'python',smk:'python',nextflow:'groovy',nf:'groovy',tex:'latex',r:'r',jl:'julia'}[lang_]||lang_;
  try{if(hljs.getLanguage(alias)){body=hljs.highlight(text,{language:alias,ignoreIllegals:true}).value;hl=' hljs'}}catch(e){}}
 return `<div class=codeblk data-lang="${attr(lang_)}"${title?` data-title="${attr(title)}"`:''}><div class=codehead><span class=lang>${esc(title||lang_||'text')}</span><span class=cacts></span></div><pre><code class="${hl?'hljs':''}${lang_?' language-'+attr(lang_):''}">${body}</code></pre></div>`}

/* ---------------- after an answer is written ---------------- */
function decorate(node){
 if(!node)return;
 mathify(node);meridify(node);tableTools(node);codeTools(node);calloutFallback(node);footnoteLinks(node);
 todoify(node);imageTools(node);
 // files this answer wrote count as its files even if the text never names them
 const msg=node.closest&&node.closest('.msg'),extra=[...(node._changes||[])];
 if(msg)msg.querySelectorAll('details.tool').forEach(t=>{
  const n=(t.querySelector('.tn')||{}).textContent||'',o=t.querySelector('.toolopen');
  if(o&&/^(Write|Edit|MultiEdit|NotebookEdit|write_file|edit_file|create_file|str_replace|apply_patch|save_file)/i.test(n))extra.push(o.dataset.path)});
 pathify(node,{strip:!!msg&&msg.classList.contains('a'),extra})}
function mathify(node){
 // math the renderer could not typeset yet (KaTeX still loading)
 if(!window.renderMathInElement||!node)return;
 if(!/\$|\\\(|\\\[/.test(node.textContent))return;
 try{renderMathInElement(node,{delimiters:[
  {left:'$$',right:'$$',display:true},{left:'\\[',right:'\\]',display:true},
  {left:'\\(',right:'\\)',display:false}],ignoredTags:['script','noscript','style','textarea','pre','code','option'],
  ignoredClasses:['codeblk','katex'],throwOnError:false})}catch(e){}}
function calloutFallback(node){}
function footnoteLinks(node){
 node.querySelectorAll('sup.fnref:not([data-t])').forEach(s=>{s.dataset.t='1';s.title='footnote';
  const li=node.querySelector(`.footnotes li[data-fn="${CSS.escape(s.dataset.fn)}"]`);
  if(li)s.title=li.textContent.slice(0,300);
  s.onclick=()=>{if(li){li.scrollIntoView({block:'center',behavior:'smooth'});li.classList.add('flash');setTimeout(()=>li.classList.remove('flash'),1200)}}})}
function meridify(node){
 if(!window.mermaid||!node)return;
 const els=[...node.querySelectorAll('.mermaid:not([data-done])')];
 if(!els.length)return;
 try{mermaid.initialize({startOnLoad:false,securityLevel:'strict',theme:matchMedia('(prefers-color-scheme:dark)').matches?'dark':'default'});
  els.forEach(async(e,i)=>{e.dataset.done='1';const src=e.dataset.src||e.textContent;
   try{const {svg}=await mermaid.render('mm'+Date.now()+i,src);e.innerHTML=svg;diagramTools(e,src)}
   catch(err){e.innerHTML='';const c=el(codeHtml(src,'mermaid-src'));e.appendChild(el('<div class=err style="font-size:12px">diagram could not be drawn: '+esc(String(err.message||err).slice(0,160))+'</div>'));e.appendChild(c);codeTools(e)}})}catch(e){}}
function diagramTools(box,src){
 const bar=el('<div class=blktools><button data-a=svg>copy SVG</button><button data-a=png>copy image</button><button data-a=save>save SVG</button><button data-a=savepng>save PNG</button><button data-a=src>source</button><button data-a=zoom title="enlarge">⤢</button></div>');
 const svg=()=>box.querySelector('svg');
 bar.onclick=async ev=>{const a=ev.target.dataset.a;if(!a)return;ev.stopPropagation();
  const s=svg();const xml=s?new XMLSerializer().serializeToString(s):'';
  if(a==='svg')copy(xml);
  if(a==='save')saveBlob(new Blob([xml],{type:'image/svg+xml'}),'diagram.svg');
  if(a==='png'){await copyImageBlob(svgToPng(xml))}
  if(a==='savepng'){saveBlob(await svgToPng(xml),'diagram.png')}
  if(a==='src'){copy(src)}
  if(a==='zoom')lightbox({html:xml,name:'diagram'})};
 box.prepend(bar)}
async function svgToPng(xml,scale=2){
 const url=URL.createObjectURL(new Blob([xml],{type:'image/svg+xml'}));
 try{const img=await loadImg(url);return await drawPng(img,scale)}finally{URL.revokeObjectURL(url)}}
function loadImg(src){return new Promise((ok,bad)=>{const i=new Image();i.crossOrigin='anonymous';i.onload=()=>ok(i);i.onerror=()=>bad(new Error('image did not load'));i.src=src})}
function drawPng(img,scale=1){
 const w=Math.max(1,Math.round((img.naturalWidth||img.width||800)*scale)),h=Math.max(1,Math.round((img.naturalHeight||img.height||600)*scale));
 const c=document.createElement('canvas');c.width=w;c.height=h;const g=c.getContext('2d');
 g.drawImage(img,0,0,w,h);return new Promise((ok,bad)=>c.toBlob(b=>b?ok(b):bad(new Error('could not draw the image')),'image/png'))}
function saveBlob(blob,name){
 const u=URL.createObjectURL(blob);const a=document.createElement('a');a.href=u;a.download=name||'download';
 document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(u),4000)}
async function copyImageBlob(blobOrPromise){
 try{await navigator.clipboard.write([new ClipboardItem({'image/png':Promise.resolve(blobOrPromise)})]);toast('image copied');return true}
 catch(e){toast('could not copy the image: '+(e.message||e));return false}}
// rich copy: formatted for Word, Pages, Google Docs, Mail, Notes; plain text for everything else
async function copyRich(html,text){
 try{await navigator.clipboard.write([new ClipboardItem({'text/html':new Blob([html],{type:'text/html'}),
   'text/plain':new Blob([text],{type:'text/plain'})})]);toast('copied with formatting');return}
 catch(e){}
 const d=document.createElement('div');d.contentEditable='true';d.style.cssText='position:fixed;left:-9999px;top:0';
 d.innerHTML=html;document.body.appendChild(d);const r=document.createRange();r.selectNodeContents(d);
 const sel=getSelection();sel.removeAllRanges();sel.addRange(r);
 const ok=document.execCommand('copy');sel.removeAllRanges();d.remove();toast(ok?'copied with formatting':'copy failed')}

/* ---------------- tables ---------------- */
function tableRows(tb){return [...tb.querySelectorAll('tr')].map(r=>[...r.children].map(c=>cellText(c)))}
function cellText(c){const x=c.cloneNode(true);x.querySelectorAll('.katex').forEach(k=>{const a=k.querySelector('annotation');k.replaceWith(a?'$'+a.textContent+'$':k.textContent)});
 x.querySelectorAll('br').forEach(b=>b.replaceWith(' '));return x.textContent.replace(/\s+/g,' ').trim()}
function csvCell(v,sep){v=String(v);return (v.includes(sep)||/["\n\r]/.test(v))?'"'+v.replace(/"/g,'""')+'"':v}
function tableCSV(tb,sep=','){return tableRows(tb).map(r=>r.map(v=>csvCell(v,sep)).join(sep)).join('\n')}
function tableTSV(tb){return tableRows(tb).map(r=>r.map(v=>v.replace(/\t/g,' ')).join('\t')).join('\n')}
function tableMarkdown(tb){
 const rows=tableRows(tb);if(!rows.length)return '';
 const head=tb.querySelector('thead tr')||tb.querySelector('tr');
 const aligns=[...head.children].map(c=>{const a=(c.getAttribute('align')||c.style.textAlign||'').toLowerCase();
  return a==='center'?':---:':a==='right'?'---:':a==='left'?':---':'---'});
 const line=r=>'| '+r.map(v=>v.replace(/\|/g,'\\|')).join(' | ')+' |';
 return [line(rows[0]),'| '+aligns.join(' | ')+' |',...rows.slice(1).map(line)].join('\n')}
function tableHtmlForCopy(tb){
 const t=tb.cloneNode(true);t.removeAttribute('class');t.setAttribute('style','border-collapse:collapse;font-family:-apple-system,Helvetica,Arial,sans-serif;font-size:11pt');
 t.querySelectorAll('th,td').forEach(c=>{const al=c.getAttribute('align')||c.style.textAlign||'';
  c.setAttribute('style',`border:1px solid #bfbfbf;padding:4px 8px;vertical-align:top;${al?'text-align:'+al+';':''}${c.tagName==='TH'?'background:#f2f2f2;font-weight:600;':''}`);
  c.removeAttribute('title')});
 t.querySelectorAll('.katex').forEach(k=>{const m=k.querySelector('math');k.replaceWith(m?m.cloneNode(true):k.textContent)});
 return t.outerHTML}
function tableTools(node){
 node.querySelectorAll('table:not([data-t])').forEach(tb=>{tb.dataset.t='1';
  let wrap=tb.parentElement;
  if(!wrap||!wrap.classList.contains('tblwrap')){wrap=el('<div class=tblwrap></div>');tb.before(wrap);wrap.appendChild(tb)}
  const rows=tb.querySelectorAll('tr').length,cols=(tb.querySelector('tr')||{children:[]}).children.length;
  const bar=el(`<div class=blktools><span class=tmeta>${Math.max(0,rows-1)} × ${cols}</span><button data-a=copy title="copy with formatting — pastes as a table in Word, Excel, Numbers, Google Docs">copy</button><button data-a=md>markdown</button><button data-a=csv>CSV</button><button data-a=tsv title="tab-separated: pastes into a spreadsheet">TSV</button><button data-a=save title="download as CSV">⤓ CSV</button><button data-a=xls title="download for Excel">⤓ Excel</button><button data-a=big title="full screen">⤢</button></div>`);
  bar.onclick=ev=>{const a=ev.target.dataset.a;if(!a)return;ev.stopPropagation();
   if(a==='copy')copyRich(tableHtmlForCopy(tb),tableTSV(tb));
   if(a==='md')copy(tableMarkdown(tb));
   if(a==='csv')copy(tableCSV(tb));
   if(a==='tsv')copy(tableTSV(tb));
   if(a==='save')saveBlob(new Blob(['\ufeff'+tableCSV(tb)],{type:'text/csv'}),'table.csv');
   if(a==='xls')saveBlob(new Blob([`<html><head><meta charset="utf-8"></head><body>${tableHtmlForCopy(tb)}</body></html>`],{type:'application/vnd.ms-excel'}),'table.xls');
   if(a==='big'){const c=tb.cloneNode(true);c.removeAttribute('data-t');openSheet('Table',box=>{box.classList.add('bub');box.appendChild(c);tableTools(box)})}};
  wrap.before(bar);
  if(rows>26&&!tb.closest('.pvbody')){wrap.classList.add('tbllong');
   const more=el(`<div class=codemore>Show all ${rows-1} rows</div>`);
   more.onclick=()=>{const c=wrap.classList.toggle('tbllong');more.textContent=c?`Show all ${rows-1} rows`:'Show fewer'};wrap.after(more)}
  if(tb.closest('.pvbody')&&rows>8){const fi=el('<input class=tblfilter placeholder="filter rows…">');
   fi.oninput=()=>{const t=fi.value.toLowerCase();[...(tb.querySelector('tbody')||tb).querySelectorAll('tr')].forEach(r=>{if(r.querySelector('td'))r.style.display=!t||r.textContent.toLowerCase().includes(t)?'':'none'})};
   bar.prepend(fi)}
  // numbers line up on the right; a click on a header sorts
  const body=tb.querySelector('tbody')||tb;
  const dataRows=[...body.querySelectorAll('tr')].filter(r=>r.querySelector('td'));
  const ths=[...tb.querySelectorAll('th')];
  ths.forEach((th,i)=>{
   const vals=dataRows.map(r=>r.children[i]&&r.children[i].textContent.trim()).filter(Boolean);
   const numeric=vals.length&&vals.every(v=>/^[-+−]?[$€£¥]?\s?[\d,]*\.?\d+(e[-+]?\d+)?\s?(%|[kKMBx×]|ms|s|GB|MB|KB|bp|kb)?$/.test(v));
   if(numeric&&!th.getAttribute('align')&&!th.style.textAlign){th.style.textAlign='right';dataRows.forEach(r=>{if(r.children[i])r.children[i].style.textAlign='right'})}
   th.style.cursor='pointer';th.title='sort';
   th.onclick=()=>{const dir=th.dataset.d==='1'?-1:1;ths.forEach(x=>{delete x.dataset.d;x.classList.remove('sorted-asc','sorted-desc')});
    th.dataset.d=dir===1?'1':'';th.classList.add(dir===1?'sorted-asc':'sorted-desc');
    const num=v=>parseFloat(String(v).replace(/[,$€£¥%\s]/g,'').replace('−','-'));
    dataRows.sort((a,b)=>{const x=(a.children[i]||{}).textContent?.trim()||'',y=(b.children[i]||{}).textContent?.trim()||'';
     const nx=num(x),ny=num(y);
     return (isNaN(nx)||isNaN(ny))?dir*x.localeCompare(y,undefined,{numeric:true}):dir*(nx-ny)});
    dataRows.forEach(r=>body.appendChild(r))}})})}

/* ---------------- code blocks ---------------- */
const OPEN_LINE=/^\s*(?:\$\s*)?(open|xdg-open|code|cursor|zed|subl|qlmanage\s+-p)\s+(.+?)\s*$/;
function shellWords(s){const out=[];let m;const re=/"((?:\\.|[^"\\])*)"|'([^']*)'|(\S+)/g;
 while((m=re.exec(s)))out.push(m[1]!=null?m[1].replace(/\\(.)/g,'$1'):m[2]!=null?m[2]:m[3].replace(/\\ /g,' '));return out}
function openTargets(text){
 const out=[];String(text).split('\n').forEach(line=>{const m=line.match(OPEN_LINE);if(!m)return;
  const w=shellWords(m[2]);for(let i=0;i<w.length;i++){
   if(/^-(a|b|-args)$/.test(w[i])){i++;continue}
   if(w[i].startsWith('-')||/^[a-z]+:\/\//.test(w[i]))continue;out.push(w[i])}});
 return out.slice(0,8)}
const CMD_START=/^\s*(?:\$\s+)?(open|cd|ls|cat|less|head|tail|python3?|pip3?|uv|npm|npx|bun|node|git|brew|conda|mamba|Rscript|R|sbatch|qsub|squeue|qstat|ssh|scp|rsync|curl|wget|make|claude|codex|opencode|docker|kubectl|chmod|mkdir|cp|mv|rm|echo|export|source|java|go|cargo|swift|xcodebuild|jupyter|pytest|tar|unzip|grep|find|sed|awk|sort|wc|du|df|ps|kill|top|htop|module|srun|salloc|snakemake|nextflow|bash|zsh|sh)\b/;
function codeIsShell(blk,text){
 const l=blk.dataset.lang||'';
 if(SHELL_LANGS.has(l))return true;
 if(l)return false;
 const lines=text.trim().split('\n').filter(x=>x.trim()&&!x.trim().startsWith('#'));
 return lines.length>0&&lines.length<=6&&lines.every(x=>CMD_START.test(x))}
function stripPrompts(text,lang){
 const lines=String(text).split('\n');
 if(lang==='console'||lines.some(x=>/^\s*\$ /.test(x))){
  const cmds=lines.filter(x=>/^\s*\$ /.test(x));if(cmds.length)return cmds.map(x=>x.replace(/^\s*\$ /,'')).join('\n')}
 return text}
const EXT_FOR_LANG={python:'py',py:'py',javascript:'js',js:'js',typescript:'ts',ts:'ts',tsx:'tsx',jsx:'jsx',bash:'sh',sh:'sh',zsh:'sh',shell:'sh',
 json:'json',yaml:'yaml',yml:'yml',html:'html',xml:'xml',svg:'svg',css:'css',markdown:'md',md:'md',r:'R',julia:'jl',sql:'sql',swift:'swift',
 rust:'rs',go:'go',java:'java',c:'c',cpp:'cpp','c++':'cpp',csv:'csv',tsv:'tsv',tex:'tex',latex:'tex',toml:'toml',ruby:'rb',php:'php',
 perl:'pl',lua:'lua',kotlin:'kt',dockerfile:'Dockerfile',makefile:'Makefile',diff:'diff',patch:'patch',ini:'ini',text:'txt',txt:'txt',plaintext:'txt'};
function codeTools(node){
 node.querySelectorAll('.codeblk:not([data-t])').forEach(blk=>{blk.dataset.t='1';
  const codeEl=blk.querySelector('code'),text=codeEl.textContent,l=blk.dataset.lang||'';
  const acts=blk.querySelector('.cacts');
  const btn=(label,title,fn,cls)=>{const b=el(`<button class="${cls||''}">${label}</button>`);b.title=title||'';
   b.onclick=ev=>{ev.stopPropagation();fn(b)};acts.appendChild(b);return b};
  const shell=codeIsShell(blk,text);
  // `open figure.html`: the file itself, one click away
  const targets=shell?openTargets(text):[];
  if(targets.length)resolveNames(targets).then(res=>{
   targets.forEach(t=>{const f=res[t];if(!f||!f.exists)return;
    const b=el(`<button class=primary title="${attr(f.path)}">${fileIcon(f)} Open ${esc(f.name)}</button>`);
    b.onclick=ev=>{ev.stopPropagation();fileAction('open',f)};
    b.oncontextmenu=ev=>{ev.preventDefault();fileMenu(ev,f)};
    acts.prepend(b)})});
  if(shell&&!isRemoteChat())btn('▶ Run','run it in Terminal, in this chat’s folder',async()=>{
   const cmd=stripPrompts(text,l).trim();
   if(!confirm('Run this in Terminal'+(FILE_CTX.cwd?' (in '+FILE_CTX.cwd+')':'')+'?\n\n'+cmd.slice(0,1500)))return;
   const d=await apiPost('/api/run_in_terminal',{sid,command:cmd},'run');if(d)toast(d.why||'running in Terminal')});
  else if(shell&&isRemoteChat())btn('▶ Run','run it on '+(CQ_INFO&&CQ_INFO.host)+' in a Terminal window (over SSH)',async()=>{
   const cmd=stripPrompts(text,l).trim();
   if(!confirm('Run this on '+CQ_INFO.host+' in a Terminal window?\n\n'+cmd.slice(0,1500)))return;
   const d=await apiPost('/api/run_in_terminal',{sid,command:cmd},'run');if(d)toast(d.why||'running in Terminal')});
  if(['html','htm','xml','svg'].includes(l)&&/<(html|body|div|svg|head|!doctype|table|canvas|script)/i.test(text))
   btn('Preview','render it here, sandboxed',()=>lightbox({html:text,name:blk.dataset.title||('preview.'+(l==='svg'?'svg':'html')),sandbox:l!=='svg'}));
  if(l==='markdown'||l==='md')btn('Rendered','show it rendered',()=>openSheet(blk.dataset.title||'Markdown',box=>{box.classList.add('bub');box.innerHTML=md(text);decorate(box)}));
  if(['csv','tsv'].includes(l)||(!l&&/^([^,\n]+,){2,}[^,\n]+\n([^,\n]*,){2,}/.test(text)))
   btn('Table','show it as a table',()=>openSheet(blk.dataset.title||'Table',box=>{box.classList.add('bub');box.appendChild(csvTable(text,l==='tsv'||(!l&&text.includes('\t'))?'\t':','));tableTools(box)}));
  if(['json','jsonl'].includes(l))btn('Format','pretty-print',b=>{
   try{const pretty=l==='jsonl'?text.trim().split('\n').map(x=>JSON.stringify(JSON.parse(x),null,2)).join('\n'):JSON.stringify(JSON.parse(text),null,2);
    const alt=codeEl.dataset.alt!=null?codeEl.dataset.alt:null;
    if(alt!=null){codeEl.innerHTML=alt;delete codeEl.dataset.alt;b.textContent='Format'}
    else{codeEl.dataset.alt=codeEl.innerHTML;codeEl.innerHTML=window.hljs?hljs.highlight(pretty,{language:'json'}).value:esc(pretty);b.textContent='Original'}}
   catch(e){toast('not valid JSON: '+e.message.slice(0,60))}});
  if(blk.dataset.title)resolveNames([blk.dataset.title]).then(res=>{const f=res[blk.dataset.title];if(!f||!f.exists||f.kind!=='file')return;
   const b=el(`<button class=primary title="${attr(f.path)}">${fileIcon(f)} ${esc(f.name)}</button>`);
   b.onclick=ev=>{ev.stopPropagation();fileAction('open',f)};b.oncontextmenu=ev=>{ev.preventDefault();fileMenu(ev,f)};acts.prepend(b)});
  btn('Insert','put it in your message, to ask about it or change it',()=>insertAtCursor('\n```'+(l||'')+'\n'+text.replace(/\n$/,'')+'\n```\n'));
  if(PREF.get('codewrap','0')==='1')blk.classList.add('wrap');
  btn('Wrap','wrap long lines (remembered)',b=>{const on=blk.classList.toggle('wrap');b.classList.toggle('on',on);PREF.set('codewrap',on?'1':'0')}).classList.toggle('on',blk.classList.contains('wrap'));
  btn('Save','download as a file',()=>{const nm=blk.dataset.title||('snippet.'+(EXT_FOR_LANG[l]||l||'txt'));
   saveBlob(new Blob([text],{type:'text/plain'}),nm.split('/').pop())});
  btn('Copy','copy the code'+(shell?' (without $ prompts)':''),b=>{copy(shell?stripPrompts(text,l):text);b.textContent='Copied';setTimeout(()=>b.textContent='Copy',1400)},'cpy');
  const n=text.split('\n').length;
  if(n>45){blk.classList.add('collapsed');
   const more=el(`<div class=codemore>Show all ${n} lines</div>`);
   more.onclick=()=>{const c=blk.classList.toggle('collapsed');more.textContent=c?`Show all ${n} lines`:'Show less'};
   blk.appendChild(more)}
})}
function csvTable(text,sep){
 const rows=[];let row=[],cur='',q_=false;
 for(let i=0;i<text.length;i++){const c=text[i];
  if(q_){if(c==='"'){if(text[i+1]==='"'){cur+='"';i++}else q_=false}else cur+=c;continue}
  if(c==='"'&&cur==='')q_=true;else if(c===sep){row.push(cur);cur=''}
  else if(c==='\n'||c==='\r'){if(c==='\r'&&text[i+1]==='\n')i++;row.push(cur);rows.push(row);row=[];cur='';if(rows.length>=5000)break}
  else cur+=c}
 if(cur!==''||row.length){row.push(cur);rows.push(row)}
 const tb=document.createElement('table');const th=document.createElement('thead'),tbd=document.createElement('tbody');
 rows.forEach((r,i)=>{const tr=document.createElement('tr');r.forEach(v=>{const c=document.createElement(i?'td':'th');c.textContent=v;tr.appendChild(c)});(i?tbd:th).appendChild(tr)});
 tb.appendChild(th);tb.appendChild(tbd);const w=el('<div class=tblwrap></div>');w.appendChild(tb);
 if(rows.length>=5000)w.appendChild(el('<div class=note>first 5000 rows</div>'));return w}

/* ---------------- images ---------------- */
function imageTools(node){
 node.querySelectorAll('img:not([data-e])').forEach(img=>{img.dataset.e='1';
  const broken=()=>{if(img.classList.contains('localimg')&&!img.getAttribute('src'))return;
   const s=img.getAttribute('src')||'';const a=document.createElement(/^https?:/.test(s)?'a':'span');
   a.textContent='🖼 '+(img.alt||s.split('/').pop()||'image')+' (did not load)';a.className='brokenimg';
   if(a.tagName==='A'){a.href=s;a.target='_blank';a.rel='noopener noreferrer'}img.replaceWith(a)};
  img.addEventListener('error',broken,{once:true});
  if(img.complete&&img.getAttribute('src')&&img.naturalWidth===0)broken()});
 node.querySelectorAll('img.localimg:not([data-t])').forEach(img=>{img.dataset.t='1';
  const name=img.dataset.localsrc;resolveNames([name]).then(res=>{const f=res[name];
   if(f&&f.exists&&f.url){img.src=f.url;img.dataset.path=f.path}
   else{const s=el(`<span class="pathlink missing" title="image not found: ${attr(name)}">🖼 ${esc(img.alt||name)}</span>`);s.dataset.path=name;img.replaceWith(s)}})})}
let IMGBAR=null,IMGBAR_FOR=null;
function imgInfo(img){
 const path=img.dataset.path||(img.closest('.afile')&&img.closest('.afile').dataset.path)||'';
 return {src:img.currentSrc||img.src,path,name:(path||img.alt||'image').split('/').pop()||'image'}}
function showImgBar(img){
 if(!IMGBAR){IMGBAR=el('<div class=imgbar><button data-a=copy title="copy image">⧉</button><button data-a=save title="save image">⤓</button><button data-a=zoom title="view larger">⤢</button><button data-a=more title="more">⋯</button></div>');
  document.body.appendChild(IMGBAR);
  IMGBAR.onmouseleave=e=>{if(e.relatedTarget!==IMGBAR_FOR)hideImgBar()};
  IMGBAR.onclick=ev=>{const a=ev.target.dataset.a;if(!a||!IMGBAR_FOR)return;ev.stopPropagation();imgAct(a,IMGBAR_FOR,ev)}}
 IMGBAR_FOR=img;const r=img.getBoundingClientRect();
 IMGBAR.style.display='flex';IMGBAR.style.top=(r.top+6)+'px';IMGBAR.style.left=Math.max(6,r.right-IMGBAR.offsetWidth-6)+'px'}
function hideImgBar(){if(IMGBAR)IMGBAR.style.display='none';IMGBAR_FOR=null}
async function imgAct(a,img,ev){
 const I=imgInfo(img);
 if(a==='copy'){
  const blob=(async()=>{const b=await (await fetch(I.src)).blob();if(b.type==='image/png')return b;return drawPng(await loadImg(URL.createObjectURL(b)))})();
  if(!(await copyImageBlob(blob))&&I.path)fileAction('copy_file',{path:I.path})}
 if(a==='save'){try{const b=await (await fetch(I.src)).blob();saveBlob(b,I.name.includes('.')?I.name:I.name+'.'+((b.type.split('/')[1]||'png').replace('svg+xml','svg')))}catch(e){toast('could not save: '+e.message)}}
 if(a==='zoom')lightbox({src:I.src,name:I.name,path:I.path});
 if(a==='more')imgMenu(ev,img)}
function imgMenu(e,img){
 const I=imgInfo(img);
 const items=[{icon:'⧉',label:'Copy image',run:()=>imgAct('copy',img)},{icon:'⤓',label:'Save image…',run:()=>imgAct('save',img)},
  {icon:'⤢',label:'View larger',run:()=>imgAct('zoom',img)}];
 if(I.path)items.push('-',{icon:'↗',label:'Open',run:()=>fileAction('open',{path:I.path})},
  {icon:'🔍',label:'Show in Finder',run:()=>fileAction('reveal',{path:I.path})},
  {icon:'⎘',label:'Copy path',run:()=>copy(I.path)},{icon:'📎',label:'Copy file (to paste in Finder, Mail…)',run:()=>fileAction('copy_file',{path:I.path})});
 else if(/^https?:/.test(I.src))items.push('-',{icon:'↗',label:'Open in browser',run:()=>window.open(I.src,'_blank','noopener')},{icon:'⎘',label:'Copy image address',run:()=>copy(I.src)});
 ctxMenu(e,items)}
document.addEventListener('mouseover',e=>{
 const img=e.target.closest&&e.target.closest('.bub img,.imgs img,.afile img.thumb,.lbimg');
 if(img&&img.naturalWidth>24&&!img.closest('.ctxmenu'))showImgBar(img);
 else if(IMGBAR&&IMGBAR_FOR&&!(e.target.closest&&e.target.closest('.imgbar')))hideImgBar()});
addEventListener('scroll',hideImgBar,true);
document.addEventListener('contextmenu',e=>{const img=e.target.closest&&e.target.closest('.bub img,.imgs img,.lbimg');
 if(!img||img.closest('.pathlink'))return;e.preventDefault();imgMenu(e,img)});
document.addEventListener('click',e=>{const img=e.target.closest&&e.target.closest('.bub img.mdimg');
 if(!img)return;e.preventDefault();imgAct('zoom',img)});

/* ---------------- sheets and previews ---------------- */
function openSheet(title,fill,opts){
 opts=opts||{};
 const host=$('#modalhost');
 host.innerHTML=`<div class="modal pvmodal"><div class="sheet pvsheet"><header><span class=pvicon></span><div class=pvtitle><b></b><span class=pvsub></span></div><span class=pvacts></span><button class="ghost pvclose" title="close (Esc)">✕</button></header><div class=pvbody></div></div></div>`;
 const m=host.querySelector('.modal');
 m.querySelector('.pvtitle b').textContent=title;
 if(opts.sub)m.querySelector('.pvsub').textContent=opts.sub;
 if(opts.icon)m.querySelector('.pvicon').innerHTML=opts.icon;
 m.onclick=e=>{if(e.target===m)closeSheet()};
 m.querySelector('.pvclose').onclick=closeSheet;
 const body=m.querySelector('.pvbody');
 fill(body,m.querySelector('.pvacts'));
 return m}
let LB_NAV=null;
function closeSheet(){closeModal();LB_NAV=null}
addEventListener('keydown',e=>{if(LB_NAV&&document.querySelector('#modalhost .pvmodal')&&(e.key==='ArrowRight'||e.key==='ArrowLeft')&&!/INPUT|TEXTAREA/.test(document.activeElement.tagName)){e.preventDefault();LB_NAV(e.key==='ArrowRight'?1:-1)}});
addEventListener('keydown',e=>{if(e.key==='Escape'&&document.querySelector('#modalhost .pvmodal')){e.preventDefault();closeSheet()}});
function lightbox(o){
 if(o.src&&!o.list){const box=[...document.querySelectorAll('#log .msg img')].find(i=>i.src===o.src)?.closest('.msg')||null;
  const imgs=box?[...box.querySelectorAll('.bub img,.imgs img,.afile img.thumb')].filter(i=>i.naturalWidth>24):[];
  const seen=new Set();o.list=imgs.map(i=>imgInfo(i)).filter(x=>!seen.has(x.src)&&seen.add(x.src));o.index=Math.max(0,o.list.findIndex(x=>x.src===o.src))}
 if(o.list&&o.list.length>1){
  LB_NAV=d=>{const i=(o.index+d+o.list.length)%o.list.length,x=o.list[i];lightbox({...x,list:o.list,index:i})}}
 else LB_NAV=null;
 openSheet((o.name||'preview')+(o.list&&o.list.length>1?`  (${o.index+1}/${o.list.length})`:''),(body,acts)=>{
  body.classList.add('pvcenter');
  if(o.html!=null){
   if(o.sandbox===false||/^\s*<svg/i.test(o.html)){const img=document.createElement('img');img.className='lbimg fit';
    img.src='data:image/svg+xml;charset=utf-8,'+encodeURIComponent(o.html);body.appendChild(img);img.onclick=()=>img.classList.toggle('fit')}
   else{body.classList.remove('pvcenter');body.classList.add('pvflush');const f=document.createElement('iframe');f.className='pvframe';f.setAttribute('sandbox','allow-scripts allow-popups allow-modals allow-forms');f.srcdoc=o.html;body.appendChild(f)}}
  else{const img=document.createElement('img');img.className='lbimg fit';img.src=o.src;img.dataset.path=o.path||'';
   img.title='click to switch between fit and actual size';img.onclick=()=>img.classList.toggle('fit');body.appendChild(img)}
  if(o.path){const f={path:o.path,name:o.name};
   [['Open',()=>fileAction('open',f)],['Show in Finder',()=>fileAction('reveal',f)],['Copy path',()=>copy(o.path)]]
    .forEach(([l,fn])=>{const b=el(`<button class=ghost>${l}</button>`);b.onclick=fn;acts.appendChild(b)})}},{sub:o.path||''})}

/* ---------------- files a chat names ---------------- */
// Names are looked up where the chat works (a Claude Code chat's folder, its project,
// Orbit's workspace; or the SSH host it runs on). Found ones become links, and the
// files an answer wrote or points to are listed under it, ready to open.
let FILE_CTX={sid:null,cwd:null,host:null};
const RESOLVED={};              // sid -> name -> {info, at}
let RESOLVE_WAIT={},RESOLVE_T=null;
function isRemoteChat(){return !!(CQ_INFO&&CQ_INFO.host&&CQ_INFO.sid_for===sid)}
function resolveNames(names,forSid){
 const s_=forSid||sid||'';
 const cache=RESOLVED[s_]=RESOLVED[s_]||{};
 const now=Date.now(),need=[],out={};
 [...new Set(names.filter(Boolean))].forEach(n=>{const c=cache[n];
  if(c&&(c.info.exists?now-c.at<120000:now-c.at<20000))out[n]=c.info;else need.push(n)});
 if(!need.length)return Promise.resolve(out);
 return new Promise(res=>{
  const w=RESOLVE_WAIT[s_]=RESOLVE_WAIT[s_]||{names:new Set(),cbs:[]};
  need.forEach(n=>w.names.add(n));w.cbs.push(()=>{need.forEach(n=>{if(cache[n])out[n]=cache[n].info});res(out)});
  clearTimeout(RESOLVE_T);RESOLVE_T=setTimeout(flushResolve,40)})}
async function flushResolve(){
 const waits=RESOLVE_WAIT;RESOLVE_WAIT={};
 for(const [s_,w] of Object.entries(waits)){
  const cache=RESOLVED[s_]=RESOLVED[s_]||{};
  const names=[...w.names];
  for(let i=0;i<names.length;i+=250){
   try{const r=await fetch('/api/paths/resolve',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({sid:s_,paths:names.slice(i,i+250)})});
    const d=await r.json();
    if(s_===sid)FILE_CTX={sid:s_,cwd:d.cwd,host:d.host};
    Object.entries(d.items||{}).forEach(([n,info])=>{cache[n]={info,at:Date.now()}})}catch(e){}}
  w.cbs.forEach(cb=>{try{cb()}catch(e){}})}}
const FILE_EXTS='png|jpe?g|gif|webp|svg|pdf|html?|md|markdown|mdx|csv|tsv|xlsx?|xlsm|docx?|pptx?|numbers|pages|key|json|jsonl|ndjson|ya?ml|toml|xml|txt|log|py|ipynb|[rR]|[rR]md|qmd|js|mjs|cjs|ts|tsx|jsx|css|scss|sh|bash|zsh|c|h|cc|cpp|hpp|rs|go|java|kt|swift|rb|php|pl|jl|lua|sql|tex|bib|bed|bam|sam|vcf|fa|fasta|fq|fastq|gff3?|gtf|bw|bigwig|pdb|cif|nwk|zip|tar|gz|tgz|bz2|xz|7z|mp4|mov|m4v|webm|mkv|mp3|wav|m4a|flac|parquet|feather|h5|hdf5|npy|npz|pkl|rds|RData|sqlite|db|smk|nf|wdl|diff|patch|heic|tiff?|bmp|avif|ico|ini|cfg|conf|rst|org|srt|vtt|epub|rtf|odt|ods|lock|env|dockerfile|Dockerfile|Makefile|Snakefile';
const ABS_ROOTS='Users|private|tmp|Volumes|opt|Applications|var|etc|Library|System|usr|home|u|scratch|data|mnt|srv|project|lustre|gpfs|work|nfs|storage|groups';
const PATH_RE=new RegExp(`(^|[\\s(\\[{"'\`“‘:=>])((?:~|/(?:${ABS_ROOTS}))/[^\\s'"\`<>()\\[\\]{},;|]*[^\\s'"\`<>()\\[\\]{},;|.:!?])`,'g');
const REL_RE=new RegExp(`(^|[\\s(\\[{"'“‘:=>*])((?:\\.{1,2}/)?(?:[\\w@+.-]+/)*[\\w@+-][\\w@+.-]*\\.(?:${FILE_EXTS})(?::\\d+(?::\\d+)?)?)(?=$|[\\s)\\]}"'”’,;:!?*]|\\.(?:\\s|$))`,'g');
const INLINE_FILE_RE=new RegExp(`^(?:(?:~|\\.{1,2})?/)?(?:[\\p{L}\\p{N}_@+.,()' -]+/)*[\\p{L}\\p{N}_@+() -][\\p{L}\\p{N}_@+.,()' -]*(?:\\.(?:${FILE_EXTS})|/)(?::\\d+(?::\\d+)?)?$|^(?:~|/(?:${ABS_ROOTS}))(?:/[^\\s]*)?$|^[\\w@+.-]+(?:/[\\w@+.-]+)+/?$`,'u');
function pathify(node,opts){
 if(!node)return;opts=opts||{};
 const skip='a,.pathlink,textarea,.katex,.codehead,.blktools,button,.mermaid,.filestrip,.imgbar';
 const walker=document.createTreeWalker(node,NodeFilter.SHOW_TEXT,{acceptNode:t=>
  t.parentElement&&t.parentElement.closest(skip)?NodeFilter.FILTER_REJECT:
  (/[/.]/.test(t.nodeValue)?NodeFilter.FILTER_ACCEPT:NodeFilter.FILTER_REJECT)});
 const texts=[];while(walker.nextNode())texts.push(walker.currentNode);
 texts.forEach(t=>{
  const inCode=!!t.parentElement.closest('code,pre');
  if(inCode&&t.parentElement.closest('code')&&!t.parentElement.closest('pre')&&t.parentElement.closest('code').textContent.trim()===t.nodeValue.trim())return;   // whole inline code: handled below
  const v=t.nodeValue;const hits=[];let m;
  const furl=/file:\/\/(\/[^\s'"`<>()\[\]{},;|]*[^\s'"`<>()\[\]{},;|.:!?])/g;
  while((m=furl.exec(v))){let p=m[1];try{p=decodeURI(p)}catch(e){}hits.push([m.index,m[0],true,p])}
  PATH_RE.lastIndex=0;while((m=PATH_RE.exec(v))){const st=m.index+m[1].length;if(!hits.some(h=>st>=h[0]&&st<h[0]+h[1].length))hits.push([st,m[2],true])}
  if(!inCode){REL_RE.lastIndex=0;while((m=REL_RE.exec(v))){const st=m.index+m[1].length;
   if(!hits.some(h=>st<h[0]+h[1].length&&h[0]<st+m[2].length)&&!/^\d+(\.\d+)+$/.test(m[2])&&!/^[\w-]+\.(com|org|net|io|edu|gov|ai|dev|app)$/i.test(m[2]))hits.push([st,m[2],false])}}
  if(!hits.length)return;
  hits.sort((a,b)=>a[0]-b[0]);
  const frag=document.createDocumentFragment();let last=0;
  hits.forEach(([st,p,abs,real])=>{if(st<last)return;
   frag.appendChild(document.createTextNode(v.slice(last,st)));
   const a=document.createElement('span');a.className=abs?'pathlink pathcand':'pathcand';a.textContent=p;a.dataset.path=real||p;
   frag.appendChild(a);last=st+p.length});
  frag.appendChild(document.createTextNode(v.slice(last)));t.replaceWith(frag)});
 node.querySelectorAll('code:not(pre code):not([data-pc])').forEach(c=>{c.dataset.pc='1';
  const v=c.textContent.trim();if(v.length<2||v.length>600||c.closest(skip))return;
  if(/^https?:|^[a-z]+:\/\/|\s{2}|^[-.]+$/.test(v))return;
  if(INLINE_FILE_RE.test(v)||/^(open|code)\s+\S/.test(v)&&openTargets(v).length){c.classList.add('pathcand');c.dataset.path=/^(open|code)\s/.test(v)?openTargets(v)[0]:v}});
 const cands=[...node.querySelectorAll('.pathcand')];
 const extra=opts.extra||[];
 if(!cands.length&&!extra.length){if(opts.strip)fileStrip(node,[]);return}
 const names=cands.map(c=>c.dataset.path).concat(extra);
 resolveNames(names).then(res=>{
  cands.forEach(c=>{const f=res[c.dataset.path];c.classList.remove('pathcand');
   if(f&&f.exists){c.classList.add('pathlink');c.classList.remove('missing');c.dataset.path=f.path;if(f.line)c.dataset.line=f.line;
    if(f.host)c.dataset.host=f.host;
    c.title=`${f.host?f.host+': ':''}${f.path}${f.kind==='file'?' · '+fmtBytes(f.size):' · folder'}\nclick to ${f.category==='folder'?'open':'open'} · right-click for more`;
    if(c.tagName==='CODE')c.classList.add('pathcode')}
   else if(f&&/^(~|\/)/.test(c.textContent.trim())||c.classList.contains('pathlink')){
    c.classList.add('pathlink','missing');c.title=`not found${f&&f.host?' on '+f.host:' on this Mac'}: ${f?f.path:c.dataset.path}`}
   else if(c.tagName==='SPAN'&&!c.classList.contains('pathlink'))c.replaceWith(document.createTextNode(c.textContent))});
  if(opts.strip)fileStrip(node,names.map(n=>res[n]).filter(f=>f&&f.exists))})}
function fmtBytes(n){n=+n||0;if(n<1024)return n+' B';const u=['KB','MB','GB','TB'];let i=-1;do{n/=1024;i++}while(n>=1024&&i<3);return (n<10?n.toFixed(1):Math.round(n))+' '+u[i]}
const CAT_ICON={image:'🖼️',pdf:'📕',html:'🌐',markdown:'📝',table:'📊',sheet:'📊',doc:'📄',notebook:'📓',data:'🧬',audio:'🎵',video:'🎞️',archive:'🗜️',code:'📜',text:'📄',folder:'📁',app:'⚙️',other:'📄'};
function fileIcon(f){return CAT_ICON[f&&f.category]||'📄'}
const PREVIEWABLE=new Set(['image','pdf','html','markdown','table','notebook','data','audio','video','code','text','doc','sheet','archive']);
const BINARY_DATA=/\.(parquet|feather|h5|hdf5|npy|npz|pkl|rds|rdata|sqlite|db|bam|bw|bigwig)$/i;
function fileStrip(bub,files){
 const msg=bub.closest('.msg');if(!msg||!msg.classList.contains('a'))return;
 const old=msg.querySelector(':scope > .filestrip');
 const seen=new Set(),list=[];
 (files||[]).forEach(f=>{if(f&&f.exists&&f.kind!=='folder'&&!seen.has(f.path)){seen.add(f.path);list.push(f)}});
 if(old)old.remove();
 if(!list.length)return;
 const strip=el(`<div class=filestrip><div class=fshead><span>${list.length===1?'1 file':list.length+' files'} in this answer</span><button class=fsall title="show or hide">${list.length>6?'show all':''}</button></div><div class=fscards></div></div>`);
 const cards=strip.querySelector('.fscards');
 // images first, then what was likely made for you (html, pdf, tables), then the rest
 const rank={image:0,html:1,pdf:1,table:2,sheet:2,doc:2,notebook:2,markdown:3,video:3,audio:3};
 list.sort((a,b)=>(rank[a.category]??5)-(rank[b.category]??5));
 list.forEach((f,i)=>{const c=fileCard(f);if(i>=6)c.classList.add('extra');cards.appendChild(c)});
 if(list.length>6){strip.classList.add('clipped');strip.querySelector('.fsall').onclick=()=>{const on=strip.classList.toggle('clipped');strip.querySelector('.fsall').textContent=on?'show all':'show fewer'}}
 bub.after(strip)}
function fileCard(f){
 const img=f.category==='image'&&f.url&&f.size<25e6;
 const c=el(`<div class=afile tabindex=0>${img?`<img class=thumb loading=lazy alt="">`:`<span class=ficon>${fileIcon(f)}</span>`}<div class=fmeta><b></b><span></span></div><div class=facts><button data-a=open title="open">Open</button><button data-a=reveal title="${f.host?'download and show in Finder':'show in Finder'}">⌕</button><button data-a=more title="more">⋯</button></div></div>`);
 if(img){const im=c.querySelector('img');im.src=f.url;im.dataset.path=f.path}
 c.dataset.path=f.path;
 c.querySelector('b').textContent=f.name;
 const dir=(f.dir||'').replace(/^\/Users\/[^/]+/,'~');
 c.querySelector('.fmeta span').textContent=(f.kind==='folder'?'folder':fmtBytes(f.size))+' · '+(f.host?f.host+':':'')+(dir.length>42?'…'+dir.slice(-41):dir);
 c.title=(f.host?f.host+': ':'')+f.path;
 c.onclick=ev=>{const a=ev.target.dataset.a;ev.stopPropagation();
  if(a==='open')return fileAction('open',f);
  if(a==='reveal')return fileAction('reveal',f);
  if(a==='more')return fileMenu(ev,f);
  if(PREVIEWABLE.has(f.category))previewFile(f);else fileAction('open',f)};
 c.oncontextmenu=ev=>{ev.preventDefault();fileMenu(ev,f)};
 c.onkeydown=ev=>{if(ev.key==='Enter')c.click();if(ev.key===' '){ev.preventDefault();fileAction('quicklook',f)}};
 c.draggable=true;
 c.ondragstart=e=>{
  const dl=f.url?location.origin+f.url:location.origin+'/api/file?download=1&sid='+encodeURIComponent(sid||'')+'&path='+encodeURIComponent(f.path);
  if(!f.host)e.dataTransfer.setData('DownloadURL',`${f.category==='image'?'image/'+(f.ext||'.png').slice(1):'application/octet-stream'}:${f.name}:${dl}`);
  e.dataTransfer.setData('text/plain',f.path);e.dataTransfer.setData('text/orbit-file',JSON.stringify(f));e.dataTransfer.effectAllowed='copy'};
 return c}
async function fileAction(action,f,extra){
 const path=f.path||f;
 const remote=f.host||(isRemoteChat()&&!String(path).startsWith('/Users/'));
 if(remote&&['open','reveal','quicklook','copy_file','preview','open_with'].includes(action))toast('fetching from '+(f.host||CQ_INFO.host)+'…');
 const d=await apiPost('/api/file/action',{sid,path,action,line:f.line||null,...(extra||{})},action.replace('_',' '));
 if(!d)return null;
 if(action==='open')toast(d.why&&d.why!=='opened'?d.why:'opened '+String(d.path||path).split('/').pop());
 else if(['reveal','copy_file','open_with','quicklook','terminal'].includes(action)&&d.why)toast(d.why);
 return d}
async function openPath(path,reveal){return fileAction(reveal?'reveal':'open',{path})}
function relPath(p){const c=FILE_CTX.cwd;if(c&&p.startsWith(c+'/'))return p.slice(c.length+1);return p}
async function findNamed(e,f){
 const d=await apiPost('/api/file/find',{sid,name:f.path},'search');if(!d)return;
 if(!(d.items||[]).length){toast('no file named '+String(f.path).split('/').pop()+' found');return}
 ctxMenu(e,d.items.map(x=>({icon:fileIcon(x),label:x.home||x.path,run:()=>fileMenu(e,x)})))}
function fileMenu(e,f){
 const path=f.path,remote=!!f.host,cat=f.category||'other';
 if(f.exists===false||(!f.kind&&document.querySelector(`.pathlink.missing[data-path="${CSS.escape(path)}"]`)))
  return ctxMenu(e,[
   ...(f.nearest&&!remote?[{icon:'🔍',label:'Show '+tildify(f.nearest)+' in Finder',sub:'nearest folder that exists',
      run:()=>fileAction('reveal',{path:f.nearest,kind:'folder',category:'folder',name:f.nearest.split('/').pop()})},
     {icon:'>_',label:'Terminal in '+tildify(f.nearest),run:()=>newTerm(f.nearest)},'-']:[]),
   {icon:'↻',label:'Check again',sub:'it may have been made since',run:()=>recheckMissing(null,true)},
   {icon:'🔎',label:'Find files named '+String(path).split('/').pop(),run:()=>findNamed(e,f)},
   {icon:'⎘',label:'Copy path',run:()=>copy(path)},{icon:'✎',label:'Insert path in message',run:()=>insertAtCursor(path)}]);
 const items=[{icon:'↗',label:remote?'Download and open':(f.line?'Open at line '+f.line:'Open'),run:()=>fileAction('open',f)}];
 if(PREVIEWABLE.has(cat))items.push({icon:'👁',label:'Preview in Orbit',run:()=>previewFile(f)});
 if(!remote){items.push({icon:'␣',label:'Quick Look',run:()=>fileAction('quicklook',f)});
  items.push({icon:'▸',label:'Open with…',run:()=>openWithMenu(e,f)})}
 items.push({icon:'🔍',label:remote?'Download and show in Finder':'Show in Finder',run:()=>fileAction('reveal',f)});
 if(!remote){const dir=f.kind==='folder'?path:path.replace(/\/[^/]*$/,'')||'/';
  items.push({icon:'▭',label:'Terminal here, in Orbit',sub:tildify(dir),run:()=>newTerm(dir)});
  if(f.kind==='folder')items.push({icon:'>_',label:'Open in Terminal',run:()=>fileAction('terminal',f)})}
 items.push('-',{icon:'⎘',label:'Copy path',sub:remote?f.host:'',run:()=>copy(path)});
 const rel=relPath(path);if(rel!==path)items.push({icon:'⎘',label:'Copy relative path',sub:rel.length>30?'…'+rel.slice(-29):rel,run:()=>copy(rel)});
 if(remote)items.push({icon:'⎘',label:'Copy scp command',run:()=>copy(`scp ${f.host}:${shq(path)} .`)});
 items.push({icon:'🔗',label:'Copy as Markdown link',run:()=>copy(`[${f.name||path.split('/').pop()}](${remote?path:encodeURI(path)})`)});
 if(!remote&&f.kind!=='folder')items.push({icon:'📎',label:cat==='image'?'Copy image':'Copy file (paste in Finder, Mail…)',run:()=>cat==='image'&&f.url?copyImageFromUrl(f):fileAction('copy_file',f)});
 if(f.kind!=='folder'&&['text','code','markdown','table','data','html','notebook'].includes(cat)&&(f.size||0)<2e6)
  items.push({icon:'≣',label:'Copy contents',run:async()=>{const t=await fileText(f);if(t!=null)copy(t)}});
 if(!remote&&f.kind!=='folder')items.push({icon:'⤓',label:'Download',run:()=>{location.href='/api/file?download=1&sid='+encodeURIComponent(sid||'')+'&path='+encodeURIComponent(path)}});
 items.push('-',{icon:'＋',label:'Attach to your next message',run:()=>attachExisting(f)},
  {icon:'✎',label:'Insert path in message',run:()=>insertAtCursor(remote?path:(rel!==path?rel:path))});
 ctxMenu(e,items)}
function shq(s){return /^[\w@%+=:,./-]+$/.test(s)?s:"'"+String(s).replace(/'/g,"'\\''")+"'"}
async function copyImageFromUrl(f){
 const blob=(async()=>{const b=await (await fetch(f.url)).blob();if(b.type==='image/png')return b;return drawPng(await loadImg(URL.createObjectURL(b)))})();
 if(!(await copyImageBlob(blob)))fileAction('copy_file',f)}
async function openWithMenu(e,f){
 const d=await apiPost('/api/file/action',{sid,path:f.path,action:'apps'},'apps');if(!d)return;
 const items=(d.apps||[]).map(a=>({icon:'◦',label:a.name,run:()=>fileAction('open_with',f,{app:a.app})}));
 if(!items.length)items.push({icon:'',label:'No other apps found',run:()=>{}});
 ctxMenu(e,items)}
function insertAtCursor(text){
 const s=q.selectionStart??q.value.length,e_=q.selectionEnd??s;
 const pad=(s>0&&!/\s$/.test(q.value.slice(0,s))?' ':'');
 q.value=q.value.slice(0,s)+pad+text+q.value.slice(e_);q.focus();
 q.selectionStart=q.selectionEnd=s+pad.length+text.length;q.dispatchEvent(new Event('input'))}
async function attachExisting(f){
 if(f.host){toast('that file is on '+f.host+' — insert its path instead');return insertAtCursor(f.path)}
 const forSid=sid;
 let att={kind:'file',name:f.name,path:f.path};
 if(f.category==='image'&&f.url&&f.size<15e6){
  try{const b=await (await fetch(f.url)).blob();const du=await new Promise(r=>{const fr=new FileReader();fr.onload=()=>r(fr.result);fr.readAsDataURL(b)});
   att={kind:'image',name:f.name,data_url:du}}catch(e){}}
 if(att.kind!=='image')ATT_LABEL.set(att,fmtBytes(f.size));
 if(forSid===sid)atts.push(att);else(ATTS_BY_SID[forSid]=ATTS_BY_SID[forSid]||[]).push(att);
 drawChips();q.focus();toast('attached '+f.name)}
async function fileText(f,limit){
 let url=f.url;
 if(!url){const d=await fileAction('preview',f);if(!d)return null;url=d.url}
 const r=await fetch(url,{headers:{Range:'bytes=0-'+((limit||4e6)-1)}});
 if(!r.ok){toast('could not read it');return null}
 return await r.text()}
async function previewFile(f){
 let info=f,url=f.url;
 if(!url||f.host){const d=await fileAction('preview',f);if(!d)return;url=d.url;info={...f,...(d.info||{}),host:f.host}}
 const cat=info.category;
 openSheet(info.name||'file',async(body,acts)=>{
  const addAct=(label,fn,title)=>{const b=el(`<button class=ghost>${label}</button>`);b.title=title||'';b.onclick=fn;acts.appendChild(b);return b};
  const local={path:info.path,name:info.name,category:cat,url};
  addAct('Open',()=>fileAction('open',f.host?f:local));
  addAct('Show in Finder',()=>fileAction('reveal',f.host?f:local));
  addAct('Copy path',()=>copy(f.path));
  addAct('⋯',ev=>fileMenu(ev,{...f,url}));
  const big=(info.size||0)>4e6;
  // documents, spreadsheets, archives, HEIC/TIFF photos: converted on the Mac first
  if(['doc','sheet','archive'].includes(cat)||/\.(heic|heif|tiff?|psd|dng)$/i.test(info.path||'')||(cat==='data'&&BINARY_DATA.test(info.path||''))){
   body.innerHTML='<div class=note>preparing a preview…</div>';
   const r=await apiPost('/api/file/action',{sid,path:info.path,action:'render'},'preview');
   if(!r){body.innerHTML='<div class=note>No preview for this file — use Open or Quick Look.</div>';return}
   body.innerHTML='';
   if(r.kind==='image'){const img=document.createElement('img');img.className='lbimg fit';img.src=r.url;img.dataset.path=info.path;img.onclick=()=>img.classList.toggle('fit');body.classList.add('pvcenter');body.appendChild(img)}
   else{const fr=document.createElement('iframe');fr.className='pvframe';fr.setAttribute('sandbox','allow-popups');fr.src=r.url;body.classList.add('pvflush');body.appendChild(fr)}
   return}
  if(cat==='image'){const img=document.createElement('img');img.className='lbimg fit';img.src=url;img.dataset.path=info.path;img.onclick=()=>img.classList.toggle('fit');body.classList.add('pvcenter');body.appendChild(img);return}
  if(cat==='pdf'){const fr=document.createElement('iframe');fr.className='pvframe';fr.src=url;body.classList.add('pvflush');body.appendChild(fr);return}
  if(cat==='html'){const fr=document.createElement('iframe');fr.className='pvframe';fr.setAttribute('sandbox','allow-scripts allow-popups allow-modals allow-forms allow-downloads');fr.src=url;body.classList.add('pvflush');body.appendChild(fr);
   addAct('Source',async()=>{const t=await fileText(local);if(t==null)return;body.classList.remove('pvflush');body.innerHTML='';const b=el(codeHtml(t,'html'));body.appendChild(b);codeTools(body)});return}
  if(cat==='audio'||cat==='video'){const m_=document.createElement(cat);m_.controls=true;m_.src=url;m_.className='pvmedia';body.classList.add('pvcenter');body.appendChild(m_);return}
  const text=await fileText(local,big?1e6:4e6);if(text==null){body.textContent='could not read it';return}
  const note=big?`<div class=note>showing the first 1 MB of ${fmtBytes(info.size)}</div>`:'';
  body.classList.add('bub');
  if(cat==='markdown'){body.innerHTML=note+md(text);decorate(body);return}
  if(cat==='table'){body.innerHTML=note;body.appendChild(csvTable(text,info.ext==='.csv'?',':'\t'));tableTools(body);return}
  if(cat==='notebook'){try{body.innerHTML=note;body.appendChild(notebookView(JSON.parse(text)));decorate(body)}catch(e){body.innerHTML=codeHtml(text,'json');codeTools(body)}return}
  const langFor={'.py':'python','.r':'r','.js':'javascript','.ts':'typescript','.json':'json','.jsonl':'json','.yaml':'yaml','.yml':'yaml','.sh':'bash','.bash':'bash','.zsh':'bash',
   '.css':'css','.xml':'xml','.svg':'xml','.sql':'sql','.swift':'swift','.rs':'rust','.go':'go','.java':'java','.c':'c','.h':'c','.cpp':'cpp','.tex':'latex','.toml':'ini','.ini':'ini',
   '.rb':'ruby','.pl':'perl','.lua':'lua','.jl':'julia','.kt':'kotlin','.m':'objectivec','.diff':'diff','.patch':'diff','.smk':'python','.nf':'groovy','.scala':'scala','.hs':'haskell','.php':'php'};
  const ext=info.ext||'';
  body.innerHTML=note+codeHtml(text,(langFor[ext]||'')+(info.name?` title=${info.name.replace(/\s/g,'_')}`:''));
  codeTools(body)},{sub:(f.host?f.host+': ':'')+f.path+(info.size!=null?' · '+fmtBytes(info.size):''),icon:fileIcon(info)})}
function notebookView(nb){
 const box=el('<div class=nbview></div>');
 const lang=((nb.metadata||{}).language_info||{}).name||((nb.metadata||{}).kernelspec||{}).language||'python';
 const src=x=>Array.isArray(x)?x.join(''):String(x||'');
 (nb.cells||[]).forEach((c,i)=>{
  const cell=el(`<div class="nbcell ${c.cell_type}"><div class=nbin></div></div>`);
  if(c.cell_type==='markdown'){cell.querySelector('.nbin').innerHTML=md(src(c.source))}
  else if(c.cell_type==='code'){cell.querySelector('.nbin').innerHTML=`<div class=nbnum>[${esc(c.execution_count??' ')}]</div>`+codeHtml(src(c.source),lang);
   (c.outputs||[]).forEach(o=>{const out=el('<div class=nbout></div>');
    const data=o.data||{};
    if(data['image/png']||data['image/jpeg']){const i=document.createElement('img');i.className='mdimg';
     const kind=data['image/png']?'png':'jpeg';i.src=`data:image/${kind};base64,`+src(data['image/'+kind]).replace(/[^A-Za-z0-9+/=]/g,'');out.appendChild(i)}
    else if(data['image/svg+xml']){const i=document.createElement('img');i.className='mdimg';i.src='data:image/svg+xml;charset=utf-8,'+encodeURIComponent(src(data['image/svg+xml']));out.appendChild(i)}
    else if(data['text/markdown'])out.innerHTML=md(src(data['text/markdown']));
    else if(data['text/html'])out.innerHTML=DOMPurify.sanitize(src(data['text/html']),PURIFY);
    else if(data['text/plain']!=null||o.text!=null){const pre=document.createElement('pre');pre.textContent=src(data['text/plain']??o.text);out.appendChild(pre)}
    else if(o.output_type==='error'){const pre=document.createElement('pre');pre.className='err';pre.textContent=(o.ename||'')+': '+(o.evalue||'');out.appendChild(pre)}
    cell.appendChild(out)})}
  else{const pre=document.createElement('pre');pre.textContent=src(c.source);cell.querySelector('.nbin').appendChild(pre)}
  box.appendChild(cell)});
 return box}
document.addEventListener('click',e=>{const p=e.target.closest&&e.target.closest('.pathlink');
 if(!p||p.closest('.ctxmenu'))return;e.preventDefault();e.stopPropagation();
 const f=pathInfo(p);
 if(p.classList.contains('missing'))return fileMenu(e,f);
 if(e.altKey||e.metaKey)return fileAction('reveal',f);
 if(e.shiftKey&&PREVIEWABLE.has(f.category))return previewFile(f);
 fileAction('open',f)},true);
document.addEventListener('contextmenu',e=>{const p=e.target.closest&&e.target.closest('.pathlink');
 if(!p)return;e.preventDefault();fileMenu(e,pathInfo(p))});
function pathInfo(p){
 const path=p.dataset.path||p.textContent;
 const c=(RESOLVED[sid||'']||{})[path]||Object.values(RESOLVED[sid||'']||{}).find(x=>x.info.path===path);
 return {...(c?c.info:{}),path,name:path.split('/').pop(),line:+p.dataset.line||(c&&c.info.line)||null,host:p.dataset.host||(c&&c.info.host)||null}}

/* ---------------- copying answers ---------------- */
function cleanForCopy(root){
 const x=root.cloneNode(true);
 x.querySelectorAll('.codehead,.blktools,.codemore,.filestrip,.imgbar,button,.tmeta').forEach(n=>n.remove());
 x.querySelectorAll('.pathlink,.pathcand').forEach(n=>{n.removeAttribute('title');n.removeAttribute('class')});
 x.querySelectorAll('.codeblk').forEach(b=>{b.removeAttribute('class');b.setAttribute('style','margin:6px 0')});
 x.querySelectorAll('pre').forEach(p=>p.setAttribute('style','font-family:Menlo,Consolas,monospace;font-size:10pt;background:#f5f5f5;padding:8px;border-radius:4px;white-space:pre-wrap'));
 x.querySelectorAll('code').forEach(c=>{if(!c.closest('pre'))c.setAttribute('style','font-family:Menlo,Consolas,monospace;background:#f2f2f2;padding:0 3px;border-radius:3px')});
 x.querySelectorAll('table').forEach(t=>{const h=tableHtmlForCopy(t);const w=document.createElement('div');w.innerHTML=h;t.replaceWith(w.firstChild)});
 x.querySelectorAll('.callout').forEach(c=>c.setAttribute('style','border-left:3px solid #888;padding:4px 10px;margin:6px 0'));
 x.querySelectorAll('.mathblock').forEach(k=>{const m=k.querySelector('math');const d=document.createElement('div');d.appendChild(m?m.cloneNode(true):document.createTextNode(k.textContent));k.replaceWith(d)});
 x.querySelectorAll('.katex').forEach(k=>{const m=k.querySelector('math');k.replaceWith(m?m.cloneNode(true):k.textContent)});
 x.querySelectorAll('img').forEach(i=>{if(i.getAttribute('src')&&!/^(data:|https?:)/.test(i.getAttribute('src')))i.src=new URL(i.getAttribute('src'),location.href).href});
 x.querySelectorAll('*').forEach(n=>[...n.attributes].forEach(a=>{if(a.name.startsWith('data-'))n.removeAttribute(a.name)}));
 return x}
function plainForCopy(root){
 const x=root.cloneNode(true);
 x.querySelectorAll('.codehead,.blktools,.codemore,.filestrip,.imgbar,button,.tmeta').forEach(n=>n.remove());
 x.querySelectorAll('.katex').forEach(k=>{const a=k.querySelector('annotation');k.replaceWith(a?(k.closest('.mathblock')?'$$'+a.textContent+'$$':'$'+a.textContent+'$'):k.textContent)});
 x.querySelectorAll('table').forEach(t=>{const pre=document.createElement('pre');pre.textContent=tableTSV(t);t.replaceWith(pre)});
 x.style.cssText='position:fixed;left:-99999px;top:0;white-space:normal;width:700px';document.body.appendChild(x);
 const s=x.innerText;x.remove();return s.replace(/\n{3,}/g,'\n\n').trim()}
function printAnswer(bub){
 const w=window.open('','_blank');if(!w){toast('allow pop-ups to print');return}
 w.document.write(`<!doctype html><meta charset="utf-8"><title>${esc($('#title').textContent||'Answer')}</title><body style="font-family:-apple-system,Helvetica,sans-serif;max-width:760px;margin:24px auto;line-height:1.5;font-size:11pt">${cleanForCopy(bub).innerHTML}</body>`);
 w.document.close();setTimeout(()=>{w.focus();w.print()},400)}
function copyMenu(e,bub){
 const raw=bub.dataset.raw||bub.textContent;
 ctxMenu(e,[{icon:'Ⓜ',label:'Copy as Markdown',run:()=>copy(raw)},
  {icon:'¶',label:'Copy with formatting',sub:'Word, Docs, Mail',run:()=>copyRich(cleanForCopy(bub).innerHTML,plainForCopy(bub))},
  {icon:'T',label:'Copy as plain text',run:()=>copy(plainForCopy(bub))},
  '-',
  {icon:'⤓',label:'Save as Markdown…',run:()=>saveBlob(new Blob([raw],{type:'text/markdown'}),(($('#title').textContent||'answer').replace(/[^\w -]+/g,'').trim().slice(0,60)||'answer')+'.md')},
  {icon:'⎙',label:'Print or save as PDF…',run:()=>printAnswer(bub)},
  {icon:'⤓',label:'Save as HTML…',run:()=>saveBlob(new Blob([`<!doctype html><meta charset="utf-8"><title>${esc($('#title').textContent||'Answer')}</title><body style="font-family:-apple-system,Helvetica,sans-serif;max-width:780px;margin:30px auto;line-height:1.55">${cleanForCopy(bub).innerHTML}</body>`],{type:'text/html'}),'answer.html')}])}
document.addEventListener('contextmenu',e=>{const k=e.target.closest&&e.target.closest('.bub .katex');if(!k)return;
 e.preventDefault();const tex=(k.querySelector('annotation')||{}).textContent||'',disp=!!k.closest('.katex-display');
 ctxMenu(e,[{icon:'∑',label:'Copy LaTeX',run:()=>copy(disp?'$$'+tex+'$$':'$'+tex+'$')},{icon:'∑',label:'Copy LaTeX (no delimiters)',run:()=>copy(tex)},
  {icon:'⟨⟩',label:'Copy MathML (Word)',run:()=>{const m=k.querySelector('math');if(m)copyRich(m.outerHTML,tex)}}])});
// select words in a chat: a button quotes them into your reply
let QUOTE_BTN=null;
document.addEventListener('mouseup',e=>{setTimeout(()=>{
 const sel=getSelection();const t=sel&&!sel.isCollapsed?sel.toString().trim():'';
 if(QUOTE_BTN&&(!t||(e.target&&QUOTE_BTN.contains(e.target)))){if(!t){QUOTE_BTN.remove();QUOTE_BTN=null}return}
 if(!t||t.length>8000)return;
 const anc=sel.getRangeAt(0).commonAncestorContainer;const bub=(anc.nodeType===1?anc:anc.parentElement).closest('#log .bub');if(!bub)return;
 const r=sel.getRangeAt(0).getBoundingClientRect();
 if(QUOTE_BTN)QUOTE_BTN.remove();
 QUOTE_BTN=el('<div class=quotebtn><button data-a=q>❝ Quote</button><button data-a=c>Copy</button></div>');
 QUOTE_BTN.style.top=Math.max(8,r.top-36)+'px';QUOTE_BTN.style.left=Math.min(innerWidth-160,Math.max(8,r.left+r.width/2-60))+'px';
 QUOTE_BTN.onmousedown=ev=>ev.preventDefault();
 QUOTE_BTN.onclick=ev=>{const a=ev.target.dataset.a;if(!a)return;
  if(a==='q'){const quoted=t.split('\n').map(x=>'> '+x).join('\n')+'\n\n';q.value=(q.value&&!q.value.endsWith('\n')?q.value+'\n\n':q.value)+quoted;q.focus();q.selectionStart=q.selectionEnd=q.value.length;q.dispatchEvent(new Event('input'))}
  else document.execCommand('copy');
  QUOTE_BTN.remove();QUOTE_BTN=null;getSelection().removeAllRanges()};
 document.body.appendChild(QUOTE_BTN)},10)});
addEventListener('scroll',()=>{if(QUOTE_BTN){QUOTE_BTN.remove();QUOTE_BTN=null}},true);
// a selection copied from an answer keeps its formatting, minus Orbit's buttons,
// with formulas as LaTeX in plain text
document.addEventListener('copy',e=>{
 const sel=getSelection();if(!sel||sel.isCollapsed||!sel.rangeCount)return;
 const r=sel.getRangeAt(0),anc=r.commonAncestorContainer;
 const bub=(anc.nodeType===1?anc:anc.parentElement)?.closest?.('.bub');if(!bub)return;
 const frag=r.cloneContents();const box=document.createElement('div');box.appendChild(frag);
 if(!box.querySelector('.katex,.codehead,.blktools,table,.filestrip,button'))return;
 e.preventDefault();
 e.clipboardData.setData('text/html',cleanForCopy(box).innerHTML);
 e.clipboardData.setData('text/plain',plainForCopy(box))});

function todoify(node){
 node.querySelectorAll('ul:not([data-todo])').forEach(ul=>{
  const items=[...ul.querySelectorAll('li')];
  if(!items.length)return;
  const boxy=items.filter(li=>/^\s*\[( |x|X)\]\s/.test(li.textContent));
  if(boxy.length<items.length||!boxy.length)return;
  ul.dataset.todo='1';ul.style.listStyle='none';ul.style.paddingLeft='2px';
  items.forEach(li=>{
   const done=/^\s*\[(x|X)\]/.test(li.textContent);
   const text=li.textContent.replace(/^\s*\[( |x|X)\]\s*/,'');
   li.innerHTML='';
   const cb=document.createElement('input');cb.type='checkbox';cb.checked=done;
   cb.style.marginRight='8px';cb.style.accentColor='var(--acc)';
   const sp=document.createElement('span');sp.textContent=text;
   if(done){sp.style.textDecoration='line-through';sp.style.color='var(--dim)'}
   cb.onchange=()=>{sp.style.textDecoration=cb.checked?'line-through':'';
    sp.style.color=cb.checked?'var(--dim)':''};
   li.appendChild(cb);li.appendChild(sp);li.style.margin='3px 0'})})}
function el(h){const d=document.createElement('div');d.innerHTML=h.trim();return d.firstElementChild}
// Where a dragged thing would land: a line between two rows for "put it here", and the
// row itself outlined for "put it inside this". One indicator, one place to change it.
let _dropline=null;
function dropLine(row,above){
 if(!_dropline){_dropline=el('<div id=dropline></div>');document.body.appendChild(_dropline)}
 const r=row.getBoundingClientRect();
 _dropline.style.display='';
 _dropline.style.left=r.left+'px';
 _dropline.style.width=r.width+'px';
 _dropline.style.top=(above?r.top:r.bottom)-1+'px'}
function dropLineOff(){if(_dropline)_dropline.style.display='none';
 document.querySelectorAll('.dropinto').forEach(x=>x.classList.remove('dropinto'))}
/// Which half of the row the cursor is in — "before this one" or "after it".
function aboveHalf(row,clientY){const r=row.getBoundingClientRect();return clientY < r.top+r.height/2}
addEventListener('dragend',dropLineOff);
addEventListener('drop',dropLineOff);
// Whether to keep following the answer as it writes. This says what YOU want, not
// where the scrollbar happens to be: an image finishing loading, a tool block opening,
// a long message expanding and the dock appearing all fire scroll events, and reading
// them as "the user scrolled" is what yanks you back to the bottom mid-sentence.
// Following an answer as it writes: only your own input decides it. Going up -- the
// wheel or trackpad, a finger, the scrollbar, the keys -- stops it at once, however
// small the move; going down by your own hand to the end starts it again. Orbit's own
// scrolling, content growing, an image loading or a block opening never change it.
// (It used to count the scrolls it caused and ignore that many: following an answer
// already at the bottom fires no scroll event, so the count only grew and your scrolls
// were taken for its own. Then "within reach of the end" counted as following, and a
// trackpad's small steps never got out of reach before the next token pulled you back.)
function followBox(box,reach,get,set){
 const atEnd=()=>box.scrollHeight-box.scrollTop-box.clientHeight<reach;
 const checkEnd=()=>setTimeout(()=>{if(atEnd())set(true)},140);
 box.addEventListener('wheel',e=>{if(e.deltaY<0)set(false);else if(e.deltaY>0&&!get())checkEnd()},{passive:true});
 let ty=null;
 box.addEventListener('touchstart',e=>{ty=e.touches[0].clientY},{passive:true});
 box.addEventListener('touchmove',e=>{const y=e.touches[0].clientY;
  if(ty!=null){if(y>ty+3)set(false);else if(y<ty-3&&!get())checkEnd()}ty=y},{passive:true});
 box.addEventListener('touchend',()=>{if(!get())checkEnd()},{passive:true});
 let dragging=false,last=0;
 box.addEventListener('pointerdown',e=>{if(e.target===box){dragging=true;last=box.scrollTop}});
 addEventListener('pointerup',()=>{if(dragging){dragging=false;if(atEnd())set(true)}});
 box.addEventListener('scroll',()=>{if(dragging&&box.scrollTop<last-1)set(false);last=box.scrollTop});
 return {atEnd,checkEnd}}
let stickToBottom=true;
function nearBottom(){return log.scrollHeight-log.scrollTop-log.clientHeight < 120}
const LOGFOLLOW=followBox(log,120,()=>stickToBottom,v=>{stickToBottom=v});
addEventListener('keydown',e=>{
 if(/input|textarea|select/i.test((document.activeElement||{}).tagName||'')||e.metaKey||e.ctrlKey)return;
 if(/^(PageUp|ArrowUp|Home)$/.test(e.key))stickToBottom=false;
 else if(/^(PageDown|ArrowDown|End)$/.test(e.key)||e.key===' ')LOGFOLLOW.checkEnd()});
// Where you were in each chat, so it opens there again: the newest message, or the first one in view and how far
// down it sat. Kept in this browser only.
const POS=(()=>{try{return JSON.parse(localStorage.getItem('orbit.pos')||'{}')||{}}catch(e){return {}}})();
let POS_READY=false, POS_T=null;
function savePos(){
 if(!POS_READY||!sid)return;
 let e={t:Date.now()};
 if(nearBottom())e.b=1;
 else{
  const top=log.getBoundingClientRect().top;
  const nd=[...wrap.querySelectorAll('[data-mi]')].find(n=>n.getBoundingClientRect().bottom>top+1);
  if(!nd)return;
  e.mi=+nd.dataset.mi;e.off=Math.round(nd.getBoundingClientRect().top-top)}
 POS[sid]=e;
 clearTimeout(POS_T);POS_T=setTimeout(()=>{try{
  const keys=Object.keys(POS);
  if(keys.length>200)keys.sort((a,b)=>(POS[a].t||0)-(POS[b].t||0)).slice(0,keys.length-200).forEach(k=>delete POS[k]);
  localStorage.setItem('orbit.pos',JSON.stringify(POS))}catch(_){}},800)}
let POS_RAF=0;
log.addEventListener('scroll',()=>{if(!POS_RAF)POS_RAF=requestAnimationFrame(()=>{POS_RAF=0;savePos()})},{passive:true});
function bottom(force){            // only auto-scroll if the user is already at the end
 if(!(force||stickToBottom))return;
 log.scrollTop=log.scrollHeight;
 if(force)stickToBottom=true}
function sysline(t){const n=el(`<div class=sysline>${esc(t)}</div>`);
 wrap.appendChild(n);bottom();return n}
// POST that tells you when it did not work. Several actions used to fail in
// silence: the list simply redrew unchanged and you were left guessing.
async function apiPost(path, body, what){
 try{
  const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},
                            body:JSON.stringify(body||{})});
  const d=await r.json().catch(()=>({}));
  if(!r.ok||d.error||d.ok===false){
   toast((what||'that')+' failed'+(d.error?': '+String(d.error).slice(0,80):''));
   return null}
  return d;
 }catch(e){toast((what||'that')+' failed: '+e); return null}}
function toast(t,ms){const x=el(`<div class=toast>${esc(t)}</div>`);document.body.appendChild(x);
 setTimeout(()=>x.remove(),ms||2200)}
function copy(text){navigator.clipboard.writeText(text).then(()=>toast('copied'))}


// raw: the composer text with [Pasted #n] tokens, so the paste shows collapsed
// Long text shows its first lines with a "Show all" under it; the choice is kept per block.
function clampLong(node,text,lines){
 if(!node)return;
 text=String(text||'');
 const n=text.split('\n').length, long=n>lines+2||text.length>lines*140;
 let btn=node.nextElementSibling&&node.nextElementSibling.classList.contains('clampbtn')?node.nextElementSibling:null;
 if(!long){node.classList.remove('clamped');if(btn)btn.remove();return}
 const label=()=>node._expanded?'Show less':'Show all \u00b7 '+plural(n,'line','lines');
 if(!btn){btn=el('<button class=clampbtn></button>');node.after(btn);
  btn.onclick=e=>{e.preventDefault();e.stopPropagation();node._expanded=!node._expanded;
   node.classList.toggle('clamped',!node._expanded);btn.textContent=label()}}
 node.style.setProperty('--clampl',lines);
 node.classList.toggle('clamped',!node._expanded);btn.textContent=label();
 // on screen, the drawn height decides (wrapped or joined lines differ from the text's)
 requestAnimationFrame(()=>{if(node._expanded||!node.isConnected||!node.offsetParent)return;
  if(node.scrollHeight<=node.clientHeight+4){node.classList.remove('clamped');btn.remove()}})}
function addUser(text,images,ts,raw){
 const m=el('<div class="msg u"><div class=who>you<span class=acts></span></div></div>');
 const acts=m.querySelector('.acts');
 const c=el('<button>copy</button>');c.onclick=()=>copy(text);acts.appendChild(c);
 const r=el('<button>retry</button>');r.onclick=()=>regenerate(m,text);acts.appendChild(r);
 const f=el('<button>fork</button>');f.title='new chat from just before this message';
 f.onclick=()=>forkAt(m,text);acts.appendChild(f);
 const rw=el('<button>rewind</button>');rw.title='put the chat back to just before this message (Esc Esc lists them all)';
 rw.onclick=()=>{const i=userIndex(m);if(i<0)return;
  const pt=rewindPoints().find(x=>x.index===i);
  if(pt&&pt.files){openRewind();return}
  if(confirm('Rewind the chat to just before this message? Later messages are removed.'))doRewind(i,false)};
 acts.appendChild(rw);
 if(images&&images.length){const b=el('<div class=imgs></div>');
  images.forEach(u=>{const i=document.createElement('img');i.src=u;b.appendChild(i)});m.appendChild(b)}
 const b=el('<div class=bub></div>');
 if(raw&&raw!==text)pasteBubble(b,raw);else{b.textContent=text;pathify(b)}m.appendChild(b);
 stamp(m,ts);wrap.appendChild(m);clampLong(b,text,14);bottom();return m}
function modelLabel(id){
 const want=id||MODELS.current||MODELS.default;
 const m=(MODELS.models||[]).find(x=>x.id===want)||(MODELS.harness_recent||[]).find(x=>x.id===want);
 if(m)return m.label||m.model;
 // a Claude Code / Codex model this page has not listed yet: the picker in the header knows its name
 const opt=!id&&$('#hmodel')&&$('#hmodel').selectedOptions[0];
 return (opt&&opt.value&&opt.textContent.split(' · ')[0])||'orbit'}
function addAssistant(who,ts,live){
 const m=el('<div class="msg a"><div class=who><span class=byline></span><span class=acts></span></div></div>');
 m.querySelector('.byline').textContent=who||modelLabel();
 // a rejoined live answer is named before this chat's models have loaded: loadModels() names it again (see relabelLive)
 if(live)m.querySelector('.byline').dataset.live='1';
 // a step reads in the order it happened: what it said, then the tools it called
 const b=el('<div class=bub></div>');m.appendChild(b);
 const tools=el('<div></div>');m.appendChild(tools);
 // thinking sits BELOW the answer so it never pushes the reply off screen
 const th=el('<details class=think><summary>thinking</summary><div class=body></div></details>');
 th.style.display='none';m.appendChild(th);
 // once you open or close it yourself, nothing changes it back -- a live
 // update used to re-collapse it moments after you clicked
 th.querySelector('summary').addEventListener('click',()=>{th._user=true});
 // The thinking box scrolls itself, independently of the page. Track
 // whether you are near ITS bottom so a live update only follows along
 // when you have not deliberately scrolled up to read what came before —
 // otherwise every token yanked you back down mid-read.
 const thBody=th.querySelector('.body');
 thBody._stick=true;
 followBox(thBody,24,()=>thBody._stick,v=>{thBody._stick=v});
 const acts=m.querySelector('.acts');
 const c=el('<button title="copy as Markdown, with formatting, or as plain text">copy ▾</button>');c.onclick=e=>{e.stopPropagation();copyMenu(e,b)};acts.appendChild(c);
 const ck=el('<button>check DOIs</button>');
 ck.onclick=async()=>{const t=b.dataset.raw||b.textContent;
  const r=await (await fetch('/api/citations',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({text:t})})).json();
  const rows=r.rows||[];
  if(!rows.length)return toast('no DOIs in this answer');
  const box=el('<div class=res style="margin-top:7px;font-size:12.5px"></div>');
  rows.forEach(x=>box.appendChild(el(`<div style="color:${x.ok?'var(--ok)':'var(--err)'}">${
   x.ok?'\u2713':'\u2717'} ${esc(x.doi)} ${esc(x.ok?(x.title||'').slice(0,70):x.why)}</div>`)));
  m.appendChild(box)};
 acts.appendChild(ck);
 const sk=el('<button>save as skill</button>');
 sk.onclick=async()=>{const n=prompt('Skill name','captured-'+Date.now().toString().slice(-4));
  if(!n)return;toast('capturing...');
  const r=await (await fetch('/api/skill/capture',{method:'POST',
   headers:{'Content-Type':'application/json'},body:JSON.stringify({name:n,sid})})).json();
  toast(r.ok?('saved skill: '+r.name):'capture failed')};
 acts.appendChild(sk);
 const hard=el('<button>retry deeper</button>');
 hard.title='ask again with maximum reasoning effort';
 hard.onclick=async()=>{
  if(busy)return;
  const r=await (await fetch('/api/retry_harder',{method:'POST',
   headers:{'Content-Type':'application/json'},body:JSON.stringify({sid})})).json();
  if(!r.ok)return toast('nothing to retry');
  const msgs=[...wrap.querySelectorAll('.msg')];
  for(let i=msgs.length-1;i>=0;i--){msgs[i].remove();if(msgs[i].classList.contains('u'))break}
  dropEmptyFolds();
  q.value=r.content; go({effort:'xhigh'})};
 acts.appendChild(hard);
 stamp(m,ts);wrap.appendChild(m);markCont(m);bottom();const ret={m,think:th,tools,bub:b};m._a=ret;return ret}
// a step that follows another step of the same answer (notes and hook lines between them
// do not count) carries on under the first step's heading
function markCont(m){
 let p=m.previousElementSibling;
 while(p&&!p.classList.contains('msg'))p=p.previousElementSibling;
 m.classList.toggle('cont',!!(p&&p.classList.contains('a')))}
// A thinking trace recovered from a reopened chat -- a completed answer, or
// one you stopped mid-stream. Shown collapsed, same as a live one once the
// answer began; click to read it.
function showSavedThinking(a,text,ts,marks){
 a.think.style.display='';a.think.open=false;
 if(marks&&marks.length)a.think._at=clockTime(marks[0][1]);else if(ts)a.think._at=clockTime(ts);
 // how long it thought, when the paragraph times say (first mark to the answer)
 let took='';
 if(marks&&marks.length&&ts&&ts>marks[0][1])took=' for '+fmtSecs(ts-marks[0][1]);
 thinkLabel(a,'thought'+took);
 renderThink(a.think.querySelector('.body'),text,marks);
 clampLong(a.think.querySelector('.body'),text,12)}
// Thinking with the time each paragraph began, where it began after a pause:
// marks are [[offset, seconds], ...]; a label shows when 10s+ passed since the last.
function renderThink(body,text,marks){
 text=text||'';
 if(!marks||!marks.length){body.textContent=text;return}
 let html='',from=0,shown=null;
 const ms=marks.filter(m=>m[0]<=text.length).sort((a,b)=>a[0]-b[0]);
 ms.forEach((m,i)=>{
  const at=m[0],t=m[1];
  if(at>from){html+=esc(text.slice(from,at));from=at}
  if(shown===null||t-shown>=10){html+=`<span class=tstamp>${clockTime(t)}</span>`;shown=t}});
 html+=esc(text.slice(from));
 body.innerHTML=html}
// the same bookkeeping as the server's para_marks, for a live answer
function paraMarks(marks,prev,chunk){
 const now=Date.now()/1000;
 if(!prev.length&&chunk)marks.push([0,now]);
 const tail=prev.slice(-2),combo=tail+chunk;let i=combo.indexOf('\n\n');
 while(i!==-1){const pos=prev.length-tail.length+i+2;
  if(pos<prev.length+chunk.length&&(!marks.length||pos>marks[marks.length-1][0]))marks.push([pos,now]);
  i=combo.indexOf('\n\n',i+1)}}
// when a thinking block began, shown on its label
function clockTime(ts){const d=ts?new Date(ts*1000):new Date();
 return d.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit'})}
// "✻ Thinking…" while it thinks, "✻ Thought for 12s" after -- Claude Code's wording
function thinkLabel(a,txt){
 let t=String(txt||'');
 t=t.charAt(0).toUpperCase()+t.slice(1);
 if(/^Thinking$/.test(t))t='Thinking\u2026';
 a.think.querySelector('summary').textContent='\u273b '+t+(a.think._at?' \u00b7 '+a.think._at:'')}
// thinking opens by itself while it is written and stays open; only you close it
function openThink(a){if(!a.think._user)a.think.open=true}

let ctxEl=null;
function closeCtx(){if(ctxEl){ctxEl.remove();ctxEl=null}}
addEventListener('click',closeCtx);
addEventListener('scroll',e=>{if(ctxEl&&e.target instanceof Node&&ctxEl.contains(e.target))return;closeCtx()},true);   // scrolling the menu itself keeps it
function ctxMenu(e,items){
 closeCtx();
 ctxEl=el('<div class=ctxmenu></div>');
 items.forEach(it=>{
  if(it==='-'){ctxEl.appendChild(el('<div class=sep></div>'));return}
  const d=el(`<div class="${it.danger?'danger':''}${it.sub==='current'?' cur':''}"><span class=ic>${it.icon||''}</span><span></span>${
    it.sub?`<span class=sub>${esc(it.sub)}</span>`:''}</div>`);
  d.querySelector('span:nth-child(2)').textContent=it.label;
  d.onclick=ev=>{ev.stopPropagation();closeCtx();it.run()};
  ctxEl.appendChild(d)});
 document.body.appendChild(ctxEl);
 const w=ctxEl.offsetWidth,h=Math.min(ctxEl.offsetHeight,innerHeight-16);
 ctxEl.style.left=Math.max(8,Math.min(e.clientX,innerWidth-w-8))+'px';
 ctxEl.style.top=Math.max(8,Math.min(e.clientY,innerHeight-h-8))+'px';
 ctxEl.querySelector('.cur')?.scrollIntoView({block:'nearest'});
}
async function flagSession(id,patch){
 await fetch('/api/session/flag',{method:'POST',headers:{'Content-Type':'application/json'},
  body:JSON.stringify({id,...patch})});
 await loadSessions();
 if('pinned' in patch)  toast(patch.pinned?'pinned to top':'unpinned');
 if('archived' in patch)toast(patch.archived?'archived':'restored to active');
 const row=[...document.querySelectorAll('.sitem')].find(x=>x.dataset.sid===id);
 if(row){row.style.transition='background .5s';row.style.background='color-mix(in srgb,var(--acc) 22%,transparent)';
  setTimeout(()=>{row.style.background=''},550)}}
function chatMenu(e,s){
 const projItems=Object.entries(PROJECTS).map(([pid,pr])=>({
   icon:'\u25CF',label:pr.name,sub:s.project===pid?'current':'',
   run:async()=>{await fetch('/api/session/assign',{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify({id:s.id,project:pid})});
    loadSessions()}}));
 ctxMenu(e,[
  {icon:'\u2934',label:'Open',run:()=>openSession(s.id)},
  {icon:'\u21BB',label:'Sort by most recent',run:async()=>{
    await fetch('/api/session/sort_recent',{method:'POST'});toast('sorted by recent');loadSessions()}},
  {icon:s.pinned?'\u2606':'\u2605',label:s.pinned?'Unpin':'Pin to top',
   run:()=>flagSession(s.id,{pinned:!s.pinned})},
  {icon:'\u270E',label:'Rename',run:async()=>{
    const t=prompt('Rename chat',s.title||'');if(t===null||!t.trim())return;
    await fetch('/api/session/rename',{method:'POST',headers:{'Content-Type':'application/json'},
     body:JSON.stringify({id:s.id,title:t.trim()})});
    if(s.id===sid)$('#title').textContent=t.trim();loadSessions()}},
  {icon:'\u{1F3F7}',label:'Tags…',run:async()=>{
    const t=prompt('Tags (comma separated)',(s.tags||[]).join(', '));if(t===null)return;
    await fetch('/api/tag',{method:'POST',headers:{'Content-Type':'application/json'},
     body:JSON.stringify({id:s.id,tags:t.split(',').map(x=>x.trim()).filter(Boolean)})});
    loadSessions()}},
  '-',
  // a long list of projects used to run the menu off the screen: it is a menu of its own
  ...(projItems.length?[{icon:'\u{1F4C1}',label:'Move to project…',
     sub:s.project&&PROJECTS[s.project]?PROJECTS[s.project].name:'',
     run:()=>setTimeout(()=>ctxMenu(e,[{icon:'\u2190',label:'Back',run:()=>chatMenu(e,s)},'-',...projItems]),0)}]
   :[{icon:'\u25CB',label:'No projects yet',run:()=>editProject(null)}]),
  ...(s.project?[{icon:'\u2716',label:'Remove from project',run:async()=>{
    await fetch('/api/session/assign',{method:'POST',headers:{'Content-Type':'application/json'},
     body:JSON.stringify({id:s.id,project:null})});loadSessions()}}]:[]),
  '-',
  ...(typeof SH!=='undefined'&&SH.on&&SH.projects.length&&!s.external?[{icon:'\u25A3',label:'Add to a shared project…',run:()=>setTimeout(()=>addChatToShared(e,s),0)}]:[]),
  {icon:'\u21C4',label:'Hand off to Claude desktop…',run:()=>openHandoff(s.id)},
  ...(s.id.startsWith('cq-')||s.source==='claude-qwen'?[{icon:'\u2328',label:'Copy command to continue in a terminal',run:async()=>{
    const i=await (await fetch('/api/claude/info?sid='+encodeURIComponent(s.id))).json().catch(()=>({}));
    if(i.resume){copy(i.resume);toast('copied — run it in a terminal to carry on with this same session')}
    else toast('this chat has no Claude session yet')}}]:[]),
  {icon:'\u2913',label:'Export markdown',
   run:()=>location.href='/api/export?id='+encodeURIComponent(s.id)},
  {icon:'\u25A2',label:s.archived?'Unarchive':'Archive',
   run:()=>flagSession(s.id,{archived:!s.archived})},
  {icon:'\u{1F5D1}',label:'Move to bin',danger:true,run:async()=>{
    await fetch('/api/delete',{method:'POST',headers:{'Content-Type':'application/json'},
     body:JSON.stringify({id:s.id})});
    await loadSessions();
    const t=await (await fetch('/api/trash')).json();
    const item=t[0];
    const bar=el('<div class=toast></div>');
    bar.innerHTML=`moved to bin · <span style="color:var(--acc);cursor:pointer;text-decoration:underline">undo</span>`;
    bar.querySelector('span').onclick=async()=>{
     if(item)await fetch('/api/trash/restore',{method:'POST',
      headers:{'Content-Type':'application/json'},body:JSON.stringify({name:item.name})});
     bar.remove();loadSessions();toast('restored')};
    document.body.appendChild(bar);setTimeout(()=>bar.remove(),7000)}},
 ])}
function dayLabel(ts){
 const d=new Date(ts*1000), now=new Date();
 const day=(a,b)=>a.toDateString()===b.toDateString();
 const y=new Date(now);y.setDate(y.getDate()-1);
 if(day(d,now))return 'Today'; if(day(d,y))return 'Yesterday';
 const diff=(now-d)/86400000;
 if(diff<7)return 'Previous 7 days'; if(diff<30)return 'Previous 30 days';
 return d.toLocaleDateString(undefined,{month:'long',year:'numeric'})}
// "5m", "3h", "2d": how long ago a chat was last active
let RUN_SINCE={}, TALKING={};
function fmtElapsed(sec){sec=Math.max(0,Math.floor(sec));
 if(sec<60)return sec+'s';const m=Math.floor(sec/60),s_=sec%60;
 if(m<60)return m+'m '+String(s_).padStart(2,'0')+'s';return Math.floor(m/60)+'h '+(m%60)+'m'}
// one tick for every counter on screen, without redrawing the list
setInterval(()=>{if(document.hidden)return;
 document.querySelectorAll('.sitem .ago.elapsed[data-since]').forEach(x=>{
  x.textContent=fmtElapsed(Date.now()/1000-(+x.dataset.since))})},1000);
function agoShort(ts){
 const s=Math.max(0,Date.now()/1000-(ts||0));
 if(s<60)return 'now';if(s<3600)return Math.floor(s/60)+'m';if(s<86400)return Math.floor(s/3600)+'h';
 if(s<86400*7)return Math.floor(s/86400)+'d';if(s<86400*60)return Math.floor(s/604800)+'w';
 return new Date(ts*1000).toLocaleDateString(undefined,{month:'short',day:'numeric'})}
function sideOpenSec(name,def){return PREF.get('sec_'+name,def?'1':'0')==='1'}
// ---------------- the chat list ----------------
// Like Claude Code's session list: one row per chat, in a stable order (the last
// message you sent), with its state on the left -- answering, waiting for you,
// queued, or new since you looked. A chat keeps its place while it answers, and the
// list is only redrawn when something in it changed, keeping your scroll position.
let WAITING=new Set(), PENDING_ROWS={}, LIST_SIG='', TITLE_N={};
function rowState(s){
 if(WAITING.has(s.id))return {cls:'wait',icon:'!',tip:'waiting for you — an approval or a question'};
 if(TALKING[s.id])return {cls:'run',icon:'⇄',tip:'waiting for “'+(TALKING[s.id].title||'')+'”'};
 if(RUNNING.has(s.id))return {cls:'run',icon:'<span class=spin></span>',tip:'answering'};
 if(s.queued)return {cls:'queue',icon:String(s.queued),tip:s.queued+' queued message'+(s.queued>1?'s':'')};
 // new here, or an answer that landed since you last looked on any device (the Mac keeps that)
 if(UNSEEN[s.id]||s.unread)return {cls:'new',icon:'<span class=dotnew></span>',tip:'new since you last looked'};
 if(s.scheduled)return {cls:'sched',icon:'<span class=schedmark>⏱</span>',tip:'a message is scheduled: '+whenLabel(s.scheduled)};
 return {cls:'',icon:'',tip:''}}
function chatRow(s,box){
 const st=rowState(s);
 const src=extSource(s);
 const d=el(`<div class="sitem${s.id===sid?' on':''}${st.cls?' st-'+st.cls:''}${s.external?' external':''}" title="${esc(s.title||'')}">
   <span class=stc title="${esc(st.tip)}">${st.icon}</span><span class=t></span>${
   s.goal&&s.goal!=='complete'?`<span class=goalmark title="goal: ${esc(s.goal)}">◎</span>`:''}${
   s.parent?`<span class=goalmark title="started by “${esc(s.parent.title||'')}”">↳</span>`:''}${
   s.pinned?'<span class=pinmark title="pinned">★</span>':''}${
   (TITLE_N[String(s.title||'').trim().toLowerCase()]||0)>1?`<span class=dupmark title="Other chats have this same name. This one has ${s.n||0} messages and was last active ${esc(new Date((s.mtime||0)*1000).toLocaleString())}.">${(s.n||0)>=1000?((s.n/1000).toFixed(1)+'k'):(s.n||0)} msgs</span>`:''}${
   s.host?`<span class=hostmark title="runs on ${esc(s.host)} over SSH">${esc(s.host)}</span>`:''}<span class=ago title="${esc(new Date((s.mtime||0)*1000).toLocaleString())} · ${s.n||0} messages">${agoShort(s.mtime)}</span><button class=more title="Actions">⋯</button></div>`);
 d.querySelector('.t').textContent=s.title||'(untitled)';
 // answering: how long it has been at it, counting up
 if(RUNNING.has(s.id)&&RUN_SINCE[s.id]){const ag=d.querySelector('.ago');ag.classList.add('elapsed');
  ag.dataset.since=RUN_SINCE[s.id];ag.textContent=fmtElapsed(Date.now()/1000-RUN_SINCE[s.id]);ag.title='answering'}
 d.dataset.sid=s.id; d.dataset.pinned=s.pinned?'1':'';
 d.onclick=ev=>{
  if(ev.target.closest('.more')){ev.stopPropagation();const r=ev.target.getBoundingClientRect();
   chatMenu({clientX:r.left,clientY:r.bottom},s);return}
  showPane('log');openSession(s.id)};
 d.oncontextmenu=e=>{e.preventDefault();chatMenu(e,s)};
 // drag a chat onto a project to move it there
 if(!s.external){d.draggable=true;
  d.ondragstart=e=>{e.dataTransfer.setData('sid',s.id);d.classList.add('dragging')};
  d.ondragend=()=>d.classList.remove('dragging')}
 box.appendChild(d);return d}
const EXT_SOURCES=[
 {key:'claude',label:'From Claude Code',tip:"Sessions from the Claude CLI and Claude's desktop app — open one to continue it here, in the same Claude session"},
 {key:'codex',label:'From Codex',tip:'Codex sessions — open one to continue it here; Orbit runs Codex resuming that same session'},
 {key:'opencode',label:'From OpenCode',tip:'OpenCode sessions — open one to continue it here; Orbit runs OpenCode resuming that same session'}];
function extSource(s){
 const id=String(s.id||'');
 if(s.source==='codex'||id.startsWith('cx-'))return 'codex';
 if(s.source==='opencode'||id.startsWith('oc-'))return 'opencode';
 if(s.external||id.startsWith('cq-'))return 'claude';
 return null}
// rows under date headings that fold (older months start folded)
function projectLabel(s){
 const p=s.project&&PROJECTS[s.project];
 return p?(p.name||'Project'):'No project'}
// The list in project order (projects as the sidebar shows them, then chats with none),
// each project's chats newest first.
function byProject(list){
 const order={};Object.entries(PROJECTS).sort((a,b)=>(a[1].order||0)-(b[1].order||0))
  .forEach(([pid],i)=>order[pid]=i);
 return [...list].sort((a,b)=>{
  const oa=a.project&&order[a.project]!=null?order[a.project]:1e6;
  const ob=b.project&&order[b.project]!=null?order[b.project]:1e6;
  return oa-ob||(!!b.pinned-!!a.pinned)||(b.mtime||0)-(a.mtime||0)})}
function groupedRows(list,box,prefix,term){
 let lastGroup=null, groupBody=null;
 const byProj=GROUP_BY==='project';
 if(byProj)list=byProject(list);
 list.forEach(s=>{
  const g=byProj?projectLabel(s):(s.pinned&&filterMode!=='archived'?'Pinned':dayLabel(s.mtime));
  if(g!==lastGroup){
   lastGroup=g;
   const recent=byProj||['Pinned','Today','Yesterday','Previous 7 days','Previous 30 days'].includes(g);
   const open=term?true:PREF.get(prefix+g,recent?'1':'0')==='1';
   const h=el(`<div class="daygroup${open?'':' closed'}"><span class=caret>▾</span>${
     byProj&&s.project&&PROJECTS[s.project]?`<span class=gsw style="background:${esc(PROJECTS[s.project].color||PCOLORS[0])}"></span>`:''
    } ${esc(g)} <span class=gct></span></div>`);
   groupBody=el(`<div class=grpbody${open?'':' style="display:none"'}></div>`);
   const gb=groupBody;
   h.onclick=()=>{const now=gb.style.display==='none';gb.style.display=now?'':'none';
    h.classList.toggle('closed',!now);PREF.set(prefix+g,now?'1':'0')};
   box.appendChild(h);box.appendChild(groupBody)}
  chatRow(s,groupBody);
  groupBody.previousSibling.querySelector('.gct').textContent=groupBody.children.length})}
function listRows(){
 // chats you have just started, before the server lists them
 const have=new Set(SESSIONS.map(s=>s.id));
 Object.keys(PENDING_ROWS).forEach(k=>{if(have.has(k))delete PENDING_ROWS[k]});
 return Object.values(PENDING_ROWS).concat(SESSIONS)}
function renderSessions(force){
 const term=($('#search').value||'').trim().toLowerCase();
 const rows=listRows();
 // chats that share a name (forks, sessions branched in a terminal or the desktop app): told apart by size
 TITLE_N={};rows.forEach(s=>{const k=String(s.title||'').trim().toLowerCase();if(k)TITLE_N[k]=(TITLE_N[k]||0)+1});
 const sig=JSON.stringify([filterMode,GROUP_BY,term,projFilter,tagFilter,sid,[...RUNNING],[...WAITING],Object.keys(UNSEEN),
  rows.map(s=>[s.id,s.title,s.mtime,s.pinned,s.archived,s.queued,s.scheduled,s.host,s.n,s.project,s.unread,TITLE_N[String(s.title||'').trim().toLowerCase()]>1]),sessTotal,
  Object.entries(typeof PROJECTS==='object'&&PROJECTS||{}).map(([k,v])=>[k,v&&v.name,v&&v.color]),
  PREF.get('sec_ext_claude','0')]);
 if(!force&&sig===LIST_SIG)return;
 LIST_SIG=sig;
 const sc=$('#sidescroll'), keep=sc?sc.scrollTop:0;
 const box=$('#slist');box.innerHTML='';
 // what is going on, at a glance: answering, waiting for you, queued
 const runN=rows.filter(s=>RUNNING.has(s.id)).length, waitN=rows.filter(s=>WAITING.has(s.id)).length,
       queueN=rows.filter(s=>s.queued).length;
 const bar=$('#sidestatus');
 bar.innerHTML=(runN||waitN||queueN)?[
   waitN?`<button class="stchip wait" data-f=attention>! ${waitN} waiting for you</button>`:'',
   runN?`<button class="stchip run" data-f=attention><span class=spin></span> ${runN} answering</button>`:'',
   queueN?`<button class="stchip queue" data-f=attention>${queueN} with queued messages</button>`:''].join(''):'';
 bar.querySelectorAll('button').forEach(b=>b.onclick=()=>{
  const on=filterMode!=='attention';filterMode=on?'attention':'active';$('#filtersel').value=filterMode;renderSessions(true)});
 bar.classList.toggle('on',filterMode==='attention');
 const pass=s=>{
  // an empty chat you left is not worth a row -- but one that is answering is
  if(!s.n && s.id!==sid && !RUNNING.has(s.id) && !PENDING_ROWS[s.id] && !s.queued && !s.scheduled) return false;
  if(filterMode==='active')   return !s.archived;
  if(filterMode==='pinned')   return !!s.pinned;
  if(filterMode==='archived') return !!s.archived;
  if(filterMode==='attention')return RUNNING.has(s.id)||WAITING.has(s.id)||!!s.queued||!!UNSEEN[s.id]||!!s.unread;
  return true};
 const all_=rows.filter(s=>pass(s)&&(!projFilter||s.project===projFilter)
   &&(!tagFilter||(s.tags||[]).includes(tagFilter))
   &&(!term||(s.title||'').toLowerCase().includes(term)));
 const list=all_.filter(s=>!extSource(s)||(!s.external&&RUNNING.has(s.id)));
 const inList=new Set(list.map(s=>s.id));
 $('#chatct').textContent=list.length||'';
 $('#chatslbl').textContent=projFilter&&PROJECTS[projFilter]?PROJECTS[projFilter].name:(filterMode==='attention'?'Needs attention':'Chats');
 if(!list.length)box.innerHTML=`<div class=note style="padding:10px 8px;font-size:12.5px">${
   term?'No titles match — ⌘P searches inside chats too.':filterMode==='archived'?'No archived chats.':
   filterMode==='attention'?'Nothing is answering or waiting for you.':'No chats here yet.'}</div>`;
 else groupedRows(list,box,'grp_',term);
 // conversations that began outside Orbit: each agent in its own section, folded until opened
 const ext=$('#extsecs');ext.innerHTML='';
 EXT_SOURCES.forEach(src=>{
  const rs=all_.filter(s=>extSource(s)===src.key&&!inList.has(s.id));if(!rs.length)return;
  // opened by you, or by itself while something there moved in the last ten minutes (a chat
  // you are carrying on in that agent's own window), so its newest messages are in view
  const newest=Math.max(...rs.map(s=>s.mtime||0));
  const pref=PREF.get('sec_ext_'+src.key,'0');          // "1" open, "0" never touched, "x" folded by you
  const hot=Date.now()/1000-newest<600&&pref!=='x';
  const open=term?true:(pref==='1'||hot);
  const h=el(`<div class="sechead${open?'':' closed'}" title="${esc(src.tip)}"><span class=caret>▾</span><span class=lbl>${esc(src.label)}</span><span class=ct>${rs.length}</span><span class=ct style="margin-left:6px;opacity:.7" title="its newest chat">${esc(agoShort(newest))}</span></div>`);
  const body=el(`<div class="secbody${open?'':' closed'}"><div class=slist></div></div>`);
  h.onclick=()=>{const now=h.classList.contains('closed');PREF.set('sec_ext_'+src.key,now?'1':'x');renderSessions(true)};
  ext.appendChild(h);ext.appendChild(body);
  if(open)groupedRows(rs,body.firstChild,src.key+'_',term)});
 // the list is the newest 500: past that, older chats (archived ones too) just were not
 // there, with nothing to say so
 if(sessTotal>SESSIONS.length){
  const more=el(`<div class=sysline style="cursor:pointer;color:var(--acc);padding:8px 12px">show ${Math.min(500,sessTotal-SESSIONS.length)} older chats</div>`);
  more.onclick=()=>{sessLimit+=500;LIST_SIG=null;loadSessions()};ext.appendChild(more)}
 if(sc)sc.scrollTop=keep}
let sessTotal=0, sessLimit=500;
let tagFilter=null;
async function loadTags(){
 const t=await (await fetch('/api/tags')).json();const row=$('#tagrow');row.innerHTML='';
 // the other agents' own tags are their sidebar sections already
 Object.entries(t).filter(([name])=>!['claude-qwen','codex','opencode'].includes(name)).slice(0,12).forEach(([name,n])=>{
  const b=el(`<button class="tag${tagFilter===name?' on':''}">${esc(name)} ${n}</button>`);
  b.onclick=()=>{tagFilter=tagFilter===name?null:name;loadTags();renderSessions()};
  row.appendChild(b)})}
let SRC_SHORT={};
async function loadSessions(){
 let d;try{d=await (await fetch(`/api/sessions?limit=${sessLimit}`)).json()}catch(e){return}
 let items=d.items||d||[];
 // the other agents' sessions are scanned in the background on the Mac: a refresh that
 // comes back with a whole source missing keeps the rows it had, once, rather than
 // making a section vanish and reappear
 ['claude','codex','opencode'].forEach(k=>{
  const had=SESSIONS.filter(s=>s.external&&extSource(s)===k), got=items.filter(s=>s.external&&extSource(s)===k);
  if(!got.length&&had.length&&!SRC_SHORT[k]){SRC_SHORT[k]=true;items=items.concat(had)}
  else if(got.length)SRC_SHORT[k]=false});
 SESSIONS=items; sessTotal=d.total??SESSIONS.length; renderSessions(); loadTags(); loadProjects(); drawTabs(); pruneTabs();
 if(!wrap.querySelector('.msg'))drawHero()}
$('#search').oninput=renderSessions;

// Send is disabled per chat, not globally: another chat generating must not
// stop you from asking this one.
const Q_PLACEHOLDER=q.placeholder;
function syncBusy(){
 busy=RUNNING.has(sid);
 // while it works, Send becomes Steer: a note it reads at its next step,
 // without stopping — Stop is still right beside it
 $('#send').disabled=false;
 $('#send').textContent=busy?'Queue':'Send';
 $('#send').title=busy?'Queue this message: it starts when the answer running now is done. ⌘/Ctrl+Enter puts it in right away instead.':'';
 q.placeholder=busy?'Queue a message · ⌘Enter sends it in now':Q_PLACEHOLDER;
 if(QUEUE_SID!==sid){QUEUE={items:[],paused:false,running:false};drawQueue();if(sid)loadQueue(sid)}
 $('#stopgen').style.display=busy?'':'none';
 const kh=$('#keyhint');if(kh)kh.textContent=busy?'Enter queue · ⌘Enter send in now · Shift+Enter newline':'Enter send · Shift+Enter newline';
 $('#dot').classList.toggle('busy',RUNNING.size>0);
 drawPlanDock();drawModeHint();drawTabs()}      // every chat switch passes through here
/* ---------------- model picker ---------------- */
let MODELS={models:[],current:'',default:''};
function relabelLive(){document.querySelectorAll('#log .byline[data-live]').forEach(b=>{b.textContent=modelLabel()})}
async function loadModels(){
 try{MODELS=await (await fetch('/api/models'+(sid?'?sid='+encodeURIComponent(sid):''))).json()}catch(e){return}
 relabelLive();
 drawModelPicker();
 // the folder and permission bar needs to know the mode: on the page's first load it was
 // drawn before this arrived, and stayed missing until you switched chats
 if(sid)drawClaudeBar()}
function drawModelPicker(){
 document.body.classList.toggle('harness',!!MODELS.harness_mode);
 document.body.classList.toggle('codexmode',!!MODELS.codex_mode&&!MODELS.harness_mode);
 // the composer says which harness it is talking to
 q.placeholder=MODELS.harness_mode?'Ask Claude Code — / for commands and skills, drop to attach'
  :'Ask anything — / for commands, @ for files, drop to attach';
 const tl=$('#tools');
 if(tl&&MODELS.harness_mode){tl.dataset.orbit=tl.dataset.orbit||tl.textContent;tl.textContent='Claude Code harness · its own tools, skills and MCP servers'}
 else if(tl&&tl.dataset.orbit&&/Claude Code harness/.test(tl.textContent)){tl.textContent=tl.dataset.orbit}
 if(MODELS.codex_mode&&!MODELS.harness_mode){
  q.placeholder='Ask Codex — / for commands, drop to attach';
  if(tl){tl.dataset.orbit=tl.dataset.orbit||tl.textContent;tl.textContent='Codex harness · its own tools, sandbox, skills and MCP servers'}
  drawHarnessPicker()}
 else if(tl&&tl.dataset.orbit&&/Codex harness/.test(tl.textContent)){tl.textContent=tl.dataset.orbit}
 if(MODELS.harness_mode)drawHarnessPicker();
 drawOffpeak();drawEffortPick();drawEngineUI();
 const sel=$('#modelsel'); if(!sel)return;
 const cur=MODELS.current||MODELS.default||'';
 sel.innerHTML='';
 const groups={};
 MODELS.models.forEach(m=>{(groups[m.provider_label]=groups[m.provider_label]||[]).push(m)});
 Object.entries(groups).forEach(([label,list])=>{
  const g=document.createElement('optgroup');g.label=label;
  list.forEach(m=>{
   const o=document.createElement('option');
   o.value=m.id;
   o.textContent=(m.label||m.model)+(m.ready?'':' — needs a key')
    +(m.tools===false?' — no tool use':'')+opSuffix(m.offpeak);
   o.selected=(m.id===cur);
   g.appendChild(o)});
  sel.appendChild(g)});
 if(!cur&&sel.options.length)sel.selectedIndex=0}
$('#engchip').onclick=e=>{e.stopPropagation();openEnginePop()};
$('#modelsel').onchange=async()=>{setTimeout(drawClaudeBar,400);
 const id=$('#modelsel').value;
 const r=await fetch('/api/model/select',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({id,sid})});
 const d=await r.json();
 if(d.switch){
  const nm=(MODELS.models.find(x=>x.id===id)||{}).label||d.switch;
  if(!confirm('That model is not loaded. Restart the local server with '+nm+'? '
             +'This takes a minute and stops anything running.')){drawModelPicker();return}
  toast('loading '+nm+'…');
  const res=await apiPost('/api/model/local_switch',{name:d.switch},'switching model');
  if(res&&res.error){toast(res.error.slice(0,160));drawModelPicker();return}
  if(res&&res.serving)toast('now serving '+res.serving);
  if(res&&res.note)sysline(res.note);
  await loadModels();refreshStatus();return}
 if(d.error){toast(d.error);drawModelPicker();return}
 MODELS.current=id;drawOffpeak();
 const m=MODELS.models.find(x=>x.id===id);
 if(m&&!m.ready)sysline('This model needs an API key — add one in Settings → Models.');
 else if(m)sysline('this chat now uses '+(m.label||m.model));
 refreshStatus()};

let livePoll=null;
function stopLive(){if(livePoll){clearInterval(livePoll);livePoll=null}}
function attachLive(theSid, initial){
 stopLive();
 const note=sysline('still generating — reconnected to it');
 let a=addAssistant(modelLabel(),null,true);
 a.bub.innerHTML='<span class=working>rejoining this answer<span class=dots></span></span>';
 startStatus();let seenChars=0,seenThink=0,sinceSet=false;
 // shownTools counts lv.tools already drawn -- not a.tools' children, which
 // also hold approval boxes, so one approval used to swallow the next tool
 let thinkStarted=false, shownApproval=null, shownTools=0, step=null;
 let lrows=[];
 const paint=lv=>{
  // the server keeps only the step being written; when it moves on to the
  // next one, close this block and start another, as a live answer does
  if(step!==null&&lv.step!=null&&lv.step!==step){
   lrows.forEach(r=>{if(r.classList.contains('live'))finishTool(r,{})});
   if(thinkStarted)thinkLabel(a,'thought');
   if(a.bub.dataset.raw)decorate(a.bub);else a.bub.remove();
   a=addAssistant(modelLabel(),null,true);thinkStarted=false;shownTools=0;lrows=[];seenChars=0;seenThink=0}
  if(lv.step!=null)step=lv.step;
  // the status line counts from when the answer began, not from when this window joined
  if(!sinceSet&&lv.since){sinceSet=true;statusT0=lv.since*1000}
  if(!lv.content&&!lv.thinking&&lv.status)
   a.bub.innerHTML='<span class=working>'+esc(lv.status)+'<span class=dots></span></span>';
  // the status line counts what has come back since you rejoined
  if(lv.status)statusSay(lv.status);
  {const c=(lv.content||'').length,th=(lv.thinking||'').length;
   if(th>seenThink){statusGrew('',true);statusChars+=th-seenThink;seenThink=th}
   if(c>seenChars){statusGrew('',false);statusChars+=c-seenChars;seenChars=c}
}
  const tl=lv.tools||[];
  tl.slice(shownTools).forEach(t=>{
   const auto=(t.name||'').startsWith('✓ auto-approved: ');
   let c;
   if(t.id&&!auto){c=toolRow(t,t.ok!=null);if(t.t&&c.classList.contains('live'))c._t0=t.t*1000}
   else{const name=auto?t.name.slice('✓ auto-approved: '.length):t.name;
    const args='('+Object.entries(t.args||{}).map(([k,v])=>k+'='+String(v).slice(0,60)).join(', ')+')';
    c=el(auto?'<div class=autoappr></div>':'<div class=tool></div>');
    c.textContent=(auto?'✓ auto-approved — ':'* ')+name+args}
   lrows.push(c);a.tools.appendChild(c);if(c.classList.contains('done'))groupTool(c,0,true)});
  shownTools=tl.length;
  tl.forEach((t,i)=>{const r=lrows[i];if(r&&r.classList.contains('live')&&t.ok!=null){finishTool(r,t);groupTool(r,0,true)}});
  // subagents at work, as the answering tab shows them (their last few steps)
  Object.entries(lv.subagents||{}).forEach(([pid,sa])=>{
   const i=tl.findIndex(t=>t.id===pid);const r=lrows[i];
   if(!r||!r.classList.contains('live')||r._seenSub===sa.tools)return;
   r._seenSub=sa.tools;
   const last=(sa.last||[]).map(st=>({name:st.name,args:st.args}));
   r._steps=Array(Math.max(0,(+sa.tools||0)-last.length)).fill({name:'tool'}).concat(last);
   drawSub(r,sa)});
  Object.values(lv.bgtasks||{}).forEach(b=>bgNote(theSid,b));
  if(lv.question&&lv.question.id!==a._q){a._q=lv.question.id;a.tools.appendChild(questionBox(lv.question))}
  // an approval waiting in this chat, raised by a stream some other tab owns
  if(lv.approval&&lv.approval.id!==shownApproval){
   shownApproval=lv.approval.id;a.tools.appendChild(approvalBox(lv.approval));
   notify(theSid,'Needs your approval',lv.approval.name||'')}
  if(lv.thinking){
   const body=a.think.querySelector('.body');
   if(!thinkStarted){thinkStarted=true;body._stick=true;a.think.style.display='';a.think._at=clockTime();
    thinkLabel(a,'thinking');openThink(a)}
   // while it is written it keeps to a small box (the newest lines), as in a live answer;
   // once text follows it folds like any finished thinking
   if(lv.content||(lv.tools||[]).length){if(a.think.classList.contains('live')){a.think.classList.remove('live');
     thinkLabel(a,'thought')}clampLong(body,lv.thinking,12)}
   else a.think.classList.add('live');
   renderThink(body,lv.thinking,lv.thinking_marks);
   if(body._stick)body.scrollTop=body.scrollHeight}        // only if you're not reading back
  if(lv.content){a.bub.innerHTML=md(lv.content);a.bub.dataset.raw=lv.content}
  bottom()};
 paint(initial||{});
 // One request at a time, and never an older snapshot over a newer one: on a slow link
 // the 800 ms polls used to pile up and land out of order. And one failed poll is a
 // blip, not the end -- it used to stop following the answer for good.
 let inflight=false, fails=0, lastSeq=-1, lastSince=null;
 const poll=setInterval(async()=>{
  if(livePoll!==poll)return clearInterval(poll);
  if(sid!==theSid){stopLive();stopStatus(theSid);return}          // user moved on again
  if(inflight)return;inflight=true;
  try{
   const r=await fetch('/api/live/'+theSid);
   if(!r.ok)throw new Error(r.status);
   const lv=await r.json();fails=0;
   if(livePoll!==poll)return;
   if(!lv.known){stopLive();stopStatus(theSid);return}
   if(lv.since!==lastSince){lastSince=lv.since;lastSeq=-1}    // the next answer counts from 0 again
   if(lv.running&&typeof lv.seq==='number'){if(lv.seq<lastSeq)return;lastSeq=lv.seq}
   paint(lv);
   if(!lv.running){
    stopLive(); note.remove(); stopStatus(theSid);
    lrows.forEach(r=>{if(r.classList.contains('live'))finishTool(r,{stopped:true})});
    if(lv.content){a.bub.innerHTML=md(lv.content);decorate(a.bub)}
    if(sid===theSid&&!document.hidden&&document.hasFocus())markSeenOnMac(theSid);
    loadLinks(theSid).then(()=>{if(GOALS[theSid]&&GOALS[theSid].status==='active')followGoal(theSid)});
    RUNNING.delete(theSid);renderSessions();loadSessions();

    setTimeout(()=>afterTurn(theSid),300);
   }
  }catch(e){if(++fails>=20){stopLive();stopStatus(theSid);WATCH_N=null}}   // the chat watcher takes over
  finally{inflight=false}
 },800);
 livePoll=poll;
}

// Which open is the current one. Clicking a 2,000-message chat and then a small one
// used to leave the big one's answer to land last and replace the small one on screen,
// with the sidebar still highlighting the small one.
let OPEN_GEN=0;
async function openSession(id){
 const gen=++OPEN_GEN;
 stopLive();
 findClose();                                  // its hits belong to the chat leaving
 if(tempMode){tempMode=false;$('#tempbtn').style.borderColor='';$('#tempbtn').style.color='';
  $('#burnbtn').style.display='none'}          // a saved chat is never temporary
 const d=await (await fetch('/api/session/'+id)).json();
 if(gen!==OPEN_GEN)return;                     // you opened something else while it loaded
 if(d.error)return sysline('could not open: '+d.error);
 if(sid&&sid!==d.sid){clearTimeout(draftT);saveDraft(sid)}
 switchAtts(sid,d.sid);closeAt();closeMenu();
 POS_READY=false;                              // clearing the chat scrolls the page: that is not where you left it
 sid=d.sid;setTimeout(drawDiffNotes,0);$('#title').textContent=d.title||'(untitled)';wrap.innerHTML='';
 PLAN_MODE=!!d.plan_mode;drawPlanMode();drawModeHint();
 WATCH_SID=d.sid;WATCH_N=(typeof d.n==='number')?d.n:null;   // what this page now shows
 if(UNSEEN[d.sid]){delete UNSEEN[d.sid];syncUnseen()}
 markSeenOnMac(d.sid);
 if(d.parent&&d.parent.sid){const pl=el('<div class="sysline parentline">started by <a class=chatlink href="#"></a> — messages marked “from” it are its work for you; you can talk here too</div>');
  pl.querySelector('a').dataset.chat=d.parent.sid;pl.querySelector('a').textContent=d.parent.title||'another chat';
  wrap.insertBefore(pl,wrap.firstChild)}
 GOALS[d.sid]=d.goal||null;
 LINKS[d.sid]={links:d.links||[],talking_to:d.talking_to||null};
 GOAL_OFFERS[d.sid]=d.goal_offer?{...d.goal_offer,deadline:d.goal_offer.remaining!=null?Date.now()+d.goal_offer.remaining*1000:null}:null;
 drawGoal();
 loadDraft(d.sid);
 // the plan tool's last output, if the server kept it with the message
 // -- only since your last message: each new request starts a fresh plan
 let lastPlan=null;
 d.messages.forEach(m=>{if(m.role==='user'&&!m.note&&!/^continue\b/i.test(m.text||'')){lastPlan=null;return}
  if(m.plan)lastPlan=m.plan;
  (m.tool_runs||[]).forEach(r=>{if(r.name==='plan'&&r.output)lastPlan=r.output})});
 if(lastPlan){const st=parsePlan(lastPlan);if(st.length)PLANS[d.sid]=st}else delete PLANS[d.sid];
 syncBusy();
 if(d.running)setTimeout(()=>{
  // The message this answer is for may not be in the saved chat yet: a queued one has just left the queue, and the
  // engine writes it into the chat a moment later. Without this it vanished from the list until the answer ended.
  const lu=((d.live||{}).user||'').trim(), lastSaved=((d.messages.filter(m=>m.role==='user'&&!m.note).pop()||{}).text||'').trim();
  if(lu&&sid===d.sid&&lu!==lastSaved&&!(lastSaved&&lastSaved.startsWith(lu.slice(0,200))))userNode({text:lu,t:(d.live||{}).since||Date.now()/1000});
  attachLive(d.sid,d.live||{})},60);
 else if(STATUS_SID===d.sid&&!SENDING.has(d.sid))stopStatus(d.sid);     // it finished while you were away
 // user-message index in the saved chat, for fork (earlier ones may not be drawn)
 let ui=0;const uix=d.messages.map(m=>m.role==='user'?ui++:-1);
 const drawMsg=(m,i,merge)=>{let n;
  if(m.role==='notice')n=sysline(m.text||'');
  else if(m.role!=='user')n=savedAssistant(m,merge).m;
  else{n=userNode(m);n.dataset.ui=uix[i]}
  if(n&&n.dataset)n.dataset.mi=i;return n};
 // The newest messages are drawn first and older ones are added as you scroll up, without moving what you are reading
 // (like Claude's desktop app): no "load earlier" button, and no jump to the top.
 const CAP=60, CHUNK=50;
 // ...but when you left this chat part-way up, the window starts just above where you were
 const left=POS[d.sid], target=(left&&!left.b&&Number.isInteger(left.mi)&&left.mi<d.messages.length&&d.messages.length-left.mi<=400)?left:null;
 let older=Math.max(0,d.messages.length-CAP), loadingOlder=false;
 if(target)older=Math.min(older,Math.max(0,target.mi-20));
 const loadEarlier=()=>{
  if(!older||loadingOlder||gen!==OPEN_GEN)return;
  loadingOlder=true;
  const from=Math.max(0,older-CHUNK), prevH=log.scrollHeight, prevTop=log.scrollTop;
  const first=wrap.querySelector('.parentline')?wrap.querySelector('.parentline').nextSibling:wrap.firstChild;
  for(let i=from;i<older;i++){const n=drawMsg(d.messages[i],i);wrap.insertBefore(n,first&&first.parentNode===wrap?first:wrap.firstChild)}
  older=from;
  wrap.querySelectorAll('.msg.a').forEach(markCont);
  log.scrollTop=prevTop+(log.scrollHeight-prevH);        // keep the same message under your eyes
  loadingOlder=false};
 if(log._older)log.removeEventListener('scroll',log._older);
 log._older=()=>{if(log.scrollTop<400)loadEarlier()};
 if(older)log.addEventListener('scroll',log._older,{passive:true});
 d.messages.forEach((m,i)=>{if(i>=older)drawMsg(m,i,i>older)});
 if(PREF.get('foldtools','1')==='1')foldTurns();
 chatChanged(d.prefs);                        // easy mode, the branch, the find bar
 {const sel=$('#agentsel');if(sel&&[...sel.options].some(o=>o.value===(d.agent||'')))sel.value=d.agent||''}
 try{const i=await (await fetch('/api/info?sid='+encodeURIComponent(id))).json();
  if(gen!==OPEN_GEN)return;                    // this chat's tool list, not the last one's
  if(i&&i.tools){INFO.tools=i.tools;drawEasyBtn()}}catch(e){}
 loadSessions();
 // Open where you left off (the newest message if you were at the end). The old call only scrolled when the page
 // thought you were following the end, so after reading back in another chat it opened at the very top.
 {const nd=target&&wrap.querySelector('[data-mi="'+target.mi+'"]');
  if(nd){stickToBottom=false;log.scrollTop=nd.getBoundingClientRect().top-log.getBoundingClientRect().top+log.scrollTop-(target.off||0)}
  else bottom(true);
  setTimeout(()=>{if(gen===OPEN_GEN)POS_READY=true},400)}
 refreshStatus();loadModels().then(drawClaudeBar);
 if(typeof sideOpen==='function'&&matchMedia('(max-width:820px)').matches)sideOpen(false)}

$('#title').onclick=async()=>{
 const t=prompt('Rename chat',$('#title').textContent);if(t===null||!t.trim())return;
 await fetch('/api/session/rename',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({id:sid,title:t.trim()})});
 $('#title').textContent=t.trim();loadSessions()};

// Attachments belong to the chat they were added in, as its draft does. They used to be
// one list for the page: files attached in one chat went out with the next message in
// another, and an upload still running when you pressed Enter joined a later message.
const ATTS_BY_SID={}, ATT_LABEL=new WeakMap();
let UPLOADS=[];                                // {sid, name} still on their way up
function uploadingHere(){return UPLOADS.some(u=>u.sid===sid)}
function drawChips(){
 const box=$('#chips');if(!box)return;
 box.querySelectorAll('.chip:not([data-paste]):not(.notechip)').forEach(x=>x.remove());
 atts.forEach(a=>{
  const chip=el('<div class=chip></div>');
  if(a.kind==='image'&&a.data_url){const i=document.createElement('img');i.src=a.data_url;chip.appendChild(i)}
  const b=document.createElement('b');b.textContent=a.name||'file';chip.appendChild(b);
  const s=document.createElement('span');
  s.textContent=ATT_LABEL.get(a)||(a.kind==='image'?'image':a.chars!=null?a.chars+' chars':'file');chip.appendChild(s);
  const x=el('<span class=x title="remove">&times;</span>');x.onclick=()=>{atts=atts.filter(y=>y!==a);drawChips()};
  chip.appendChild(x);box.appendChild(chip)});
 UPLOADS.filter(u=>u.sid===sid).forEach(u=>{
  const chip=el('<div class=chip><b></b><span>uploading…</span></div>');
  chip.querySelector('b').textContent=u.name;box.appendChild(chip)})}
function switchAtts(from,to){
 if(from===to)return;
 if(from){if(atts.length)ATTS_BY_SID[from]=atts;else delete ATTS_BY_SID[from]}
 atts=ATTS_BY_SID[to]||[];delete ATTS_BY_SID[to];drawChips()}
async function upload(f){
 const fd=new FormData();fd.append('file',f);
 const up={sid,name:f.name};UPLOADS.push(up);drawChips();
 let d=null;
 try{const r=await fetch('/api/upload',{method:'POST',body:fd});d=await r.json();
  if(!r.ok||d.error)throw new Error(d.error||r.status)}
 catch(e){d=null;toast('could not attach '+f.name+(e&&e.message?' — '+e.message:''))}
 finally{UPLOADS=UPLOADS.filter(x=>x!==up)}
 // into the chat it was attached in, wherever you are now
 if(d){if(up.sid===sid)atts.push(d);else(ATTS_BY_SID[up.sid]=ATTS_BY_SID[up.sid]||[]).push(d)}
 drawChips()}
$('#attach').onclick=()=>$('#file').click();
$('#file').onchange=e=>{[...e.target.files].forEach(upload);e.target.value=''};
let dropEl=null;
const isFileDrag=e=>{
 const t=e.dataTransfer&&e.dataTransfer.types;
 return !!t&&[...t].includes('Files')};      // ignore internal chat/project drags
// The overlay goes when the drag does. A drag gives no reliable "left the window" event
// (it only fired at 0,0), so one cancelled with Esc or dragged out elsewhere left it on
// screen for good: it now also goes once drag events stop coming, and on any mouse move,
// click or key -- none of which happen while something is being dragged.
let dropT=null;
function clearDrop(){clearTimeout(dropT);dropT=null;if(dropEl){dropEl.remove();dropEl=null}}
// A folder is not an attachment. Orbit has a first-class idea of the folder a chat
// works in, and dropping one used to upload nothing useful and say "attached" about it.
function dragIsFolder(e){
 const it=(e.dataTransfer&&e.dataTransfer.items)||[];
 for(const x of it){
  if(x.kind!=='file')continue;
  try{const en=x.webkitGetAsEntry&&x.webkitGetAsEntry();if(en&&en.isDirectory)return true}catch(_){}
  // during dragover the entry is often unavailable; a file with no type is the hint
  if(x.type==='')return true}
 return false}
addEventListener('dragover',e=>{
 if(!isFileDrag(e))return;                    // let chat reordering work normally
 e.preventDefault();
 const folder=dragIsFolder(e);
 if(!dropEl){dropEl=el('<div class=drop></div>');document.body.appendChild(dropEl);
  dropEl.onclick=clearDrop}
 dropEl.textContent=folder?'drop to work in this folder':'drop to attach';
 dropEl.dataset.kind=folder?'folder':'files';
 clearTimeout(dropT);dropT=setTimeout(clearDrop,400)});   // dragover repeats while it is over the page
addEventListener('dragleave',e=>{if(e.clientX<=0||e.clientY<=0||e.clientX>=innerWidth||e.clientY>=innerHeight)clearDrop()});
addEventListener('dragend',clearDrop);
['mousemove','mousedown','keydown','blur'].forEach(k=>addEventListener(k,()=>{if(dropEl)clearDrop()},true));
addEventListener('drop',async e=>{
 clearDrop();
 if(!isFileDrag(e))return;
 e.preventDefault();
 // a folder sets where this chat works; files are attached to the next message
 const items=[...(e.dataTransfer.items||[])];
 for(const it of items){
  if(it.kind!=='file')continue;
  let en=null;try{en=it.webkitGetAsEntry&&it.webkitGetAsEntry()}catch(_){}
  if(en&&en.isDirectory){
   const f=it.getAsFile();
   const path=(f&&f.path)||'';
   // the browser only gives a real path for a directory in some cases; without one
   // there is nothing to set, so say so rather than setting the wrong folder
   if(!path){toast('Dropped a folder, but the browser did not say where it is — '+
                   'set it from the bar under the title.');return}
   if(!confirm('Work in '+path+' from now on in this chat?'))return;
   const d=await apiPost('/api/claude/cwd',{sid,cwd:path},'working folder');
   if(d){toast('this chat works in '+path);drawClaudeBar();pollGit(true)}
   return}}
 [...e.dataTransfer.files].forEach(upload)});
addEventListener('paste',e=>{const f=[...(e.clipboardData&&e.clipboardData.files||[])];
 // an image pasted into Settings, the find bar or a queued message's editor is not an
 // attachment for the next chat message
 const t=e.target;
 if(t!==q&&t&&t.closest&&t.closest('input,textarea,[contenteditable],#modalhost'))return;
 if(f.length){e.preventDefault();f.forEach(upload)}});

let menu=null,msel=0,menuTerm=null;
function closeMenu(){if(menu){menu.remove();menu=null}}
function allCmds(){return CMDS.concat(Object.keys(PROMPTS).map(n=>({c:'/'+n,d:PROMPTS[n].desc||'saved prompt',p:1})))
 .concat(isClaudeChat()?CQ_CMDS.filter(x=>!CMDS.some(c=>c.c===x.c)):[])}
function showMenu(){
 closeMenu();const t=q.value;if(!t.startsWith('/'))return;
 // commands that start with what you typed first, then ones that contain it, then ones
 // whose description does -- so /ctx still finds /context, as Claude Code's menu does
 if(t.includes(' '))return;
 const w=t.toLowerCase(),all=allCmds();
 const seen=new Set(),hits=[];
 const add=c=>{if(!seen.has(c.c)){seen.add(c.c);hits.push(c)}};
 all.filter(c=>c.c.toLowerCase().startsWith(w)).forEach(add);
 if(w.length>1){all.filter(c=>c.c.toLowerCase().includes(w.slice(1))).forEach(add);
  all.filter(c=>(c.d||'').toLowerCase().includes(w.slice(1))).forEach(add);
  // letters in order: /ctx -> /context
  const re=new RegExp('^/'+w.slice(1).split('').map(ch=>ch.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')).join('.*'));
  all.filter(c=>re.test(c.c.toLowerCase())).forEach(add)}
 if(!hits.length)return;
 hits.splice(14);
 if(t!==menuTerm){msel=0;menuTerm=t}
 msel=Math.min(msel,hits.length-1);
 menu=el('<div class=menu></div>');
 hits.forEach((c,i)=>{const d=el(`<div class="${i===msel?'sel':''}"><code>${c.c}</code><small>${esc(c.d)}</small></div>`);
  d.onclick=()=>{if(c.p){q.value=PROMPTS[c.c.slice(1)].text;closeMenu();q.focus();return}
   if(c.cc){q.value=c.c+' ';closeMenu();q.focus();return}      // Claude Code's own command or skill
   q.value=c.c+' ';closeMenu();q.focus();
   if(!['/remember','/rename'].includes(c.c))runCmd(c.c,'')};
  menu.appendChild(d)});
 $('.row').appendChild(menu)}

async function runCmd(cmd,rest){
 q.value='';closeMenu();saveDraft(sid);
 if(cmd==='/help'){showCommandHelp();return true}
 if(cmd==='/guide'){openGuide();return true}
 if(cmd==='/rewind'){openRewind();return true}
 if(cmd==='/context'){showContext();return true}
 if(cmd==='/copy'){copyAnswer(parseInt(rest,10)||1);return true}
 if(cmd==='/diff'){showTurnDiff();return true}
 if(cmd==='/goal'){if(!rest){editGoal();return true}
  q.value=rest;setTimeout(()=>go({goal:true}),0);return true}
 if(cmd==='/terminal'){toggleTerm(true);return true}
 if(cmd==='/worktree'){openWorktree();return true}
 if(cmd==='/verbose'){setVerbose(!VERBOSE);return true}
 if(cmd==='/todos'){togglePlanDock();return true}
 if(cmd==='/usage'){if(MODELS.harness_mode)showClaudeUsage();else showStats(7);return true}
 if(cmd==='/model'){openEnginePop(true);return true}
 if(cmd==='/permissions'){openSettings('tools');return true}
 if(cmd==='/theme'){const order=['system','light','dark'],cur=PREF.get('theme','system');
  const next=order[(order.indexOf(cur)+1)%order.length];
  PREF.set('theme',next);applyTheme(next);toast('theme: '+next);return true}
 if(cmd==='/fork'){const last=[...wrap.querySelectorAll('.msg.u')].pop();
  if(!last){toast('nothing to fork yet');return true}
  forkAt(last,'');return true}
 if(cmd==='/shortcuts'){showShortcuts();return true}
 if(cmd==='/tasks'){showTasks();return true}
 if(cmd==='/stats'){showStats(7);return true}
 if(cmd==='/plan'||cmd==='/build'){setPlanMode(cmd==='/plan');return true}
 if(cmd==='/jump'){openJump();return true}
 if(cmd==='/sound'){const on=PREF.get('beep','0')!=='1';PREF.set('beep',on?'1':'0');
  if(on)beep();toast(on?'beep on — when an answer finishes while you are away':'beep off');return true}
 if(cmd==='/find'){openFind();if(rest){const i=FIND.bar.querySelector('input');
   i.value=rest;findRun(rest)}return true}
 if(cmd==='/foldtools'){const on=PREF.get('foldtools','1')!=='1';
  PREF.set('foldtools',on?'1':'0');
  toast(on?'finished turns fold their steps away':'every step stays visible');return true}
 if(cmd==='/hidetools'){const on=!log.classList.contains('hidedone');log.classList.toggle('hidedone',on);
  PREF.set('hidetools',on?'1':'0');toast(on?'finished tool rows hidden':'tool rows shown');return true}
 if(cmd==='/clear'){wrap.innerHTML='';return true}
 if(cmd==='/scheduled'){showPane('tasks');return true}
 // Claude Code answers these only in a terminal ("isn't available in this environment"): Orbit's own screens
 if(cmd==='/handoff'){openHandoff();return true}
 if(cmd==='/crew'){openCrew();return true}
 if(cmd==='/cluster'){openCluster();return true}
 if(cmd==='/delegate'){const w=(rest||'').trim().toLowerCase();
  const val=w==='on'?true:w==='off'?false:(w==='auto'||w==='default')?null:undefined;
  if(val===undefined){toast('usage: /delegate on|off|auto');return true}
  const r=await fetch('/api/chat/setting',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({sid,key:'delegation',value:val})}).then(x=>x.json()).catch(()=>({}));
  toast(r.ok?('delegation '+(val===null?'follows Settings':val?'on for this chat':'off for this chat')+' — from the next message'):(r.error||'failed'));return true}
 if(cmd==='/stay'||cmd==='/nofallback'){const w=(rest||'').trim().toLowerCase();
  const val=(w===''||w==='on')?true:w==='off'?false:(w==='auto'||w==='default')?null:undefined;
  if(val===undefined){toast('usage: /stay on|off|auto');return true}
  await setStay(val);return true}
 if(cmd==='/resume'){showPane('log');const sb=$('#search')||$('#sq');if(sb)sb.focus();toast('open any chat in the list to carry on with it — Claude Code sessions from the terminal are listed too');return true}
 if(cmd==='/hooks'||cmd==='/config'||cmd==='/mcp'||cmd==='/release-notes'||cmd==='/ide'){claudePanel();return true}
 if(cmd==='/effort'){const w=(rest||'').trim().toLowerCase();
  if(!w){openEnginePop(true);const e=$('#heffort');if(e)e.focus();return true}
  if(w==='auto'||w==='default'){await setChatEffort(null);return true}
  if(['low','medium','high','xhigh','max'].includes(w)){await setChatEffort(w);return true}
  toast('usage: /effort low|medium|high|xhigh|max|auto');return true}
 if(cmd==='/add-dir'){
  const dir=(rest||'').trim();if(!dir){toast('usage: /add-dir <folder>');return true}
  const info=await (await fetch('/api/claude/info?sid='+encodeURIComponent(sid))).json().catch(()=>({}));
  const add=[...(info.add_dirs||[])];if(!add.includes(dir))add.push(dir);
  const d=await apiPost('/api/claude/cwd',{sid,cwd:info.cwd_pref||'',add_dirs:add,host:info.host||''},'add folder');
  if(d){toast('Claude may also use '+dir+' in this chat');drawClaudeBar()}
  return true}
 if(cmd==='/files'){showChatFiles();return true}
 if(cmd==='/later'){const p=parseLater(rest);
  if(!p||!p.text){q.value='/later '+rest;toast('usage: /later 21:30 <message> · /later tomorrow 9am <message> · /later in 2h <message> · /later daily 8:00 <message>');return true}
  q.value=p.text;await scheduleSend(p.at,p.repeat);return true}
 if(cmd==='/tools'){sysline('active tools: '+INFO.tools.join(', '));return true}
 if(cmd==='/easy'){const w=(rest||'').trim().toLowerCase();
  await setEasy(w==='on'?true:w==='off'?false:!(INFO.settings&&INFO.settings.easy_mode));return true}
 if(cmd==='/new'){newChat();return true}
 if(cmd==='/compact'){doCompact();return true}
 if(cmd==='/settings'){openSettings();return true}
 if(cmd==='/memory'){openSettings('memory');return true}
 if(cmd==='/prompts'){libTab='prompts';showPane('lib');return true}
 if(cmd==='/knowledge'){libTab='knowledge';showPane('lib');return true}
 if(cmd==='/agents'){libTab='agents';showPane('lib');return true}
 if(cmd==='/skills'){libTab='skills';showPane('lib');return true}
 if(cmd==='/export'){location.href='/api/export';return true}
 if(cmd==='/rename'){const t=rest||prompt('Rename chat',$('#title').textContent);
  if(!t)return true;
  await fetch('/api/session/rename',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({id:sid,title:t})});$('#title').textContent=t;loadSessions();return true}
 if(cmd==='/status'){const s=await (await fetch('/api/status')).json();
  sysline(`${s.running?'running':'stopped'} · ${s.model||''} · ${s.memory_gb||'?'} GB · ctx ${s.context_used||0}/${s.context_max||'?'}`);
  return true}
 if(cmd==='/doctor'){showHealth();return true}
 if(cmd==='/remember'){if(!rest){sysline('usage: /remember <text>');return true}
  const name=rest.toLowerCase().split(/\s+/).slice(0,4).join('-').replace(/[^a-z0-9-]/g,'');
  await fetch('/api/memory/save',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({name:name||'note',text:rest})});
  sysline('saved to memory: '+(name||'note'));return true}
 if(cmd==='/start'||cmd==='/restart'||cmd==='/stop'){
  const ep=cmd==='/stop'?'stop':(cmd==='/start'?'start':'restart');
  sysline(ep+'ing server...');
  const d=await (await fetch('/api/server/'+ep,{method:'POST'})).json();
  sysline(d.msg);refreshStatus();return true}
 return false}

let switching=null;                        // a chat switch still in flight
async function newChat(){
 if(sid){clearTimeout(draftT);saveDraft(sid)}      // keep what you were typing with its chat
 const typed=q.value;
 switching=(async()=>{
  // a failed request used to do nothing at all -- the old chat just stayed put
  // in the project the sidebar is showing, or none from "All chats"
  let d;try{const r=await fetch('/api/new',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({project:projFilter||null})});
   d=await r.json();if(!r.ok||!d.sid)throw new Error(d.error||('the server answered '+r.status))}
  catch(e){toast('could not start a new chat — '+(e.message||e)+'. Orbit may be restarting; try again in a moment.');return}
  stopLive(); switchAtts(sid,d.sid);closeAt();closeMenu();
  sid=d.sid;if(q.value===typed)loadDraft(d.sid);   // typed while it opened? keep that
  PLAN_MODE=false;drawPlanMode();wrap.innerHTML='';$('#title').textContent='New chat';drawGoal();
  tempMode=false;$('#tempbtn').style.borderColor='';$('#tempbtn').style.color='';
  $('#burnbtn').style.display='none';
  chatChanged(null,true);                // a new chat keeps nothing from the last one
  syncBusy();
  $('#ctxbox').style.display='none';loadSessions();drawClaudeBar()})();
 try{await switching}finally{switching=null}}
async function doCompact(){
 sysline('compacting...');
 const d=await (await fetch('/api/compact',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({sid})})).json();
 sysline(`compacted ${d.before} to ${d.after} messages`);
 if(d.summary){const a=addAssistant();a.think.style.display='';
  a.think.querySelector('summary').textContent='compacted summary';
  a.think.querySelector('.body').textContent=d.summary;a.bub.remove()}
 refreshStatus()}
// Retry sends the message you clicked again, from where it was. It used to drop the
// chat's LAST exchange and send the clicked text as a new turn -- so retry on an older
// message destroyed the newest answer; and after a send that never arrived, the
// previous, good one.
async function regenerate(node,text){
 if(busy)return;
 const users=[...wrap.querySelectorAll('.msg.u')];
 const idx=users.indexOf(node);if(idx<0)return;
 const head=((node.querySelector('.bub')||{}).textContent||'').trim().slice(0,80);
 if(!await apiPost('/api/truncate',{index:idx,id:sid,check:head},'retry'))return;
 let cur=node;while(cur){const nx=cur.nextElementSibling;cur.remove();cur=nx}
 dropEmptyFolds();
 q.value=text;go()}

async function editFrom(node,text){
 if(busy)return;
 const users=[...wrap.querySelectorAll('.msg.u')];
 const idx=users.indexOf(node); if(idx<0)return;
 // say what that message starts with: the server refuses rather than cutting the
 // wrong turn if this page is looking at a stale copy of the chat
 const head=((node.querySelector('.bub')||{}).textContent||'').trim().slice(0,80);
 if(!await apiPost('/api/truncate',{index:idx,id:sid,check:head},'edit'))return;
 let cur=node; while(cur){const nx=cur.nextElementSibling;cur.remove();cur=nx}
 q.value=text;q.focus();fitQ()}

let FILECACHE=[];
async function refreshFileCache(){
 try{const d=await (await fetch('/api/files?limit=300')).json();FILECACHE=d.items||d}catch(e){}
 try{const k=await (await fetch('/api/knowledge')).json();
  FILECACHE=FILECACHE.concat(k.map(x=>({name:x.name,rel:'knowledge/'+x.name,area:'knowledge'})))}catch(e){}}
refreshFileCache();
let atMenu=null,atSel=0,atTerm=null;
function closeAt(){if(atMenu){atMenu.remove();atMenu=null}}
function showAt(){
 closeAt();
 // an @ that starts a word: "bob@example" is an address, not a file
 // the word being typed where the caret is -- not only at the end of the box
 const cur=q.selectionStart??q.value.length, v=q.value.slice(0,cur), m=v.match(/(^|\s)@([^\s@]*)$/);
 if(!m){atTerm=null;return}
 const term=m[2].toLowerCase();
 if(term!==atTerm){atSel=0;atTerm=term}         // a new list starts at its top
 // chats too: "@" a chat to tell this one which chat to hand work to
 const chatHits=SESSIONS.filter(c=>!c.external&&c.id!==sid&&(!term||(c.title||'').toLowerCase().includes(term)))
  .slice(0,4).map(c=>({name:c.title||'(untitled)',rel:`chat “${(c.title||'').replace(/[“”]/g,'')}” (${c.id})`,area:'chat'}));
 const hits=chatHits.concat(FILECACHE.filter(f=>!term||f.name.toLowerCase().includes(term))).slice(0,8);
 if(!hits.length)return;
 atSel=Math.min(atSel,hits.length-1);
 atMenu=el('<div class=menu></div>');
 const forSid=sid;
 hits.forEach((f,i)=>{
  const d=el(`<div class="${i===atSel?'sel':''}"><code>@${esc(f.name)}</code><small>${esc(f.area||'')}</small></div>`);
  // the box as it is now, in the chat it was opened for
  d.onclick=()=>{closeAt();if(sid!==forSid)return;
   const at=Math.min(cur,q.value.length),head=q.value.slice(0,at).replace(/(^|\s)@[^\s@]*$/,(mm,pre)=>pre+f.rel+' ');
   q.value=head+q.value.slice(at);q.selectionStart=q.selectionEnd=head.length;q.focus();q.dispatchEvent(new Event('input'))};
  atMenu.appendChild(d)});
 $('.row').appendChild(atMenu)}
q.addEventListener('input',()=>{fitQ();
 showMenu(); showAt(); histPos=-1;
 const s=sid;clearTimeout(draftT);draftT=setTimeout(()=>saveDraft(s),400)});
let lastEsc=0;
// An input method turns keystrokes into candidates, and Enter chooses one. Firing on
// that Enter sends the message mid-word — and a held key repeating is never a shortcut.
const composing=e=>e.isComposing||e.keyCode===229||e.key==='Process'||e.key==='Dead';
q.addEventListener('keydown',e=>{
 if(composing(e))return;
 // Esc stops the answer that is running; Esc twice opens the rewind list, as in Claude Code
 if(e.key==='Escape'&&e.repeat)return;        // held down is one press, not two
 if(e.key==='Escape'&&!menu&&!atMenu&&!$('#modalhost').innerHTML){
  const now=Date.now(), dbl=now-lastEsc<600; lastEsc=now;
  if(dbl){e.preventDefault();lastEsc=0;openRewind();return}
  if(busy){e.preventDefault();stopRun();return}
  if(q.value){e.preventDefault();histPush(q.value);q.value='';q.style.height='auto';clearDraft(sid);return}}
 // ctrl+o: every tool row open, arguments and output in full
 if(e.ctrlKey&&!e.metaKey&&(e.key==='o'||e.key==='O')){e.preventDefault();setVerbose(!VERBOSE);return}
 if(e.ctrlKey&&!e.metaKey&&(e.key==='t'||e.key==='T')){e.preventDefault();togglePlanDock();return}
 if(e.ctrlKey&&!e.metaKey&&(e.key==='l'||e.key==='L')){e.preventDefault();q.value='';q.style.height='auto';clearDraft(sid);return}
 if(e.ctrlKey&&!e.metaKey&&(e.key==='j'||e.key==='J')){e.preventDefault();
  const i=q.selectionStart;q.value=q.value.slice(0,i)+'\n'+q.value.slice(q.selectionEnd);
  q.selectionStart=q.selectionEnd=i+1;q.dispatchEvent(new Event('input'));return}
 if(e.ctrlKey&&!e.metaKey&&(e.key==='r'||e.key==='R')){e.preventDefault();openPromptSearch();return}
 // Shift+Tab cycles the permission mode, as in Claude Code: a Claude Code or Codex chat
 // through its modes, one of Orbit's own chats in and out of plan mode
 if(e.key==='Tab'&&e.shiftKey&&!menu&&!atMenu){e.preventDefault();cycleMode();return}
 if(atMenu){const items=[...atMenu.children];
  if(e.key==='ArrowDown'){e.preventDefault();atSel=(atSel+1)%items.length;showAt();return}
  if(e.key==='ArrowUp'){e.preventDefault();atSel=(atSel-1+items.length)%items.length;showAt();return}
  if(e.key==='Escape'){closeAt();return}
  if(e.key==='Tab'||(e.key==='Enter'&&!e.shiftKey)){e.preventDefault();items[atSel].click();return}}
 if(menu){const items=[...menu.children];
  if(e.key==='ArrowDown'){e.preventDefault();msel=(msel+1)%items.length;showMenu();return}
  if(e.key==='ArrowUp'){e.preventDefault();msel=(msel-1+items.length)%items.length;showMenu();return}
  if(e.key==='Escape'){closeMenu();return}
  if(e.key==='Tab'){e.preventDefault();items[msel].click();return}
  // Enter on a half-typed command takes the highlighted one, as Claude Code's menu does;
  // a command typed out in full is simply run
  if(e.key==='Enter'&&!e.shiftKey&&items[msel]){const typed=q.value.trim(),c=(items[msel].querySelector('code')||{}).textContent;
   if(c&&typed!==c){e.preventDefault();items[msel].click();return}}}
 if((e.key==='ArrowUp'||e.key==='ArrowDown')&&!e.shiftKey&&!e.altKey&&!e.metaKey&&!e.ctrlKey
    &&histWalk(e.key==='ArrowUp'?-1:1)){e.preventDefault();return}
 // on a phone's keyboard Enter is the only way to start a new line: the send button sends
 if(e.key==='Enter'&&!e.shiftKey&&!(matchMedia('(pointer:coarse)').matches&&!e.metaKey&&!e.ctrlKey)){
  e.preventDefault();go({now:e.metaKey||e.ctrlKey})}});

// An approval prompt — from this tab's own stream, or found waiting in a chat
// opened from another window, so it can be answered from wherever you are.
function approvalBox(p){
 // Claude Code's permission prompt: what it wants to do, "Do you want to proceed?",
 // and numbered choices you can pick with 1/2/3, the arrows and Enter, or Esc for "no".
 const box=el('<div class="approve ccask" tabindex=0 title="click here, then 1 / 2 / 3, arrows and Enter, or Esc"></div>');
 const disp=toolName(p.name);
 const title={Bash:'Bash command',Python:'Python',Update:'Edit file',Write:'Write file',
  'Edit notebook':'Edit notebook',Fetch:'Fetch',Agent:'Agent'}[disp]||disp;
 const h=el('<div class=ccttl></div>');h.textContent=title;box.appendChild(h);
 const hasDiff=!!(p.diff&&p.diff.diff);
 const what=el('<div class=ccwhat></div>');
 const tgt=toolTarget(p.name,p.args);
 const main=(p.args&&(p.args.command||p.args.code))||tgt||p.name;
 const mainEl=el('<pre class=ccmain></pre>');mainEl.textContent=String(main);what.appendChild(mainEl);
 const desc=p.args&&p.args.description;
 if(desc){const d=el('<div class=ccdesc></div>');d.textContent=desc;what.appendChild(d)}
 // everything else it passed, folded
 const rest=Object.entries(p.args||{}).filter(([k])=>!['command','code','description'].includes(k));
 if(rest.length){const det=el('<details class=ccargs><summary>details</summary><pre></pre></details>');
  det.querySelector('pre').textContent=p.name+'\n'+rest.map(([k,v])=>{v=typeof v==='object'?JSON.stringify(v):String(v);
   return k+': '+(hasDiff&&v.length>300?v.slice(0,300)+'…':v)}).join('\n');
  what.appendChild(det)}
 box.appendChild(what);
 if(hasDiff)box.appendChild(diffBlock(p.diff,'proposed change'));
 if(p.reason){const r=el('<div class=ccwhy></div>');r.textContent=p.reason;box.appendChild(r)}
 box.appendChild(el('<div class=ccq>Do you want to proceed?</div>'));
 const who=p.claude?'Claude':p.codex?'Codex':'it';
 const pat=p.suggested_pattern||'';
 const opts=[
  {label:'Yes',act:()=>send(true)},
  // "and stop asking" used to mean forever, written to settings. Most of the time it
  // means "for the next twenty minutes", and a grant you cannot mean loosely is one
  // people reach for the permanent version of instead.
  ...(p.claude||p.codex?[]:[{label:'Yes, and for the rest of this chat'+(pat?' ('+pat+')':''),
   // this once either way; the rule is only claimed when it was saved
   act:async()=>{const ok=await apiPost('/api/permissions/session',{sid,tool:p.name||'*',pattern:pat||'*'},'the rule for this chat');
    if(ok)toast('allowed for the rest of this chat'+(pat?': '+pat:''));send(true)}}]),
  // and the size between a chat and everywhere: "let pytest run here" belongs to
  // the project, beside its folder, and is only offered when the chat has one
  ...(p.claude||p.codex||!p.project?[]:[{label:'Yes, and allow it in '+p.project.name,
   act:async()=>{const ok=await apiPost('/api/permissions/project',{kind:'allow',project:p.project.id,tool:p.name||'*',
                          pattern:pat||'*',note:'allowed in '+p.project.name},'the project rule');
    if(ok)toast('allowed in '+p.project.name);send(true)}}]),
  {label:p.codex?'Yes, and allow this for the rest of the session'
   :p.claude?"Yes, and don't ask again"+(pat?' for '+pat:'')
   :'Yes, and always allow'+(pat?' '+pat:' this'),act:()=>alwaysRow()},
  {label:`No, and tell ${who} what to do differently`,hint:'esc',act:()=>whyRow()}];
 const list=el('<div class=ccopts></div>');
 let sel=0;
 const draw=()=>[...list.children].forEach((r,i)=>r.classList.toggle('sel',i===sel));
 opts.forEach((o,i)=>{
  const r=el('<div class=ccopt><span class=ccptr>❯</span><span class=ccn></span><span class=ccl></span></div>');
  r.querySelector('.ccn').textContent=(i+1)+'.';
  r.querySelector('.ccl').textContent=o.label;
  if(o.hint)r.appendChild(el(`<span class=cch>(${o.hint})</span>`));
  r.onmouseenter=()=>{sel=i;draw()};r.onclick=()=>o.act();
  list.appendChild(r)});
 box.appendChild(list);draw();
 const send=async(allow,extra)=>{
  if(box._done)return;box._done=true;                     // one answer, not a double-click's two
  box.querySelectorAll('button,input').forEach(b=>b.disabled=true);
  let r;
  try{r=await fetch('/api/approve',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({id:p.id,allow,...extra})})}
  catch(e){box._done=false;box.querySelectorAll('button,input').forEach(b=>b.disabled=false);
   toast('could not reach Orbit — try again');return}
  box.classList.add('answered');
  box.innerHTML='';
  const done=el('<div class=ccdone></div>');
  done.textContent=r.ok?(allow?'⏺ '+title+' — allowed'+(extra&&extra.always?' (and remembered)':'')
                              :'⏺ '+title+' — denied'+(extra&&extra.message?': '+extra.message:''))
                      :'already answered — in another window, or it timed out';
  box.appendChild(done)};
 const alwaysRow=()=>{
  if(p.codex)return send(true,{always:true});
  if(box.querySelector('.alwaysrow'))return box.querySelector('.alwaysrow input').focus();
  const row=el('<div class=alwaysrow></div>');
  const inp=document.createElement('input');inp.type='text';
  inp.value=pat||'*';inp.spellcheck=false;
  if(p.claude)inp.title='a Claude Code permission rule, e.g. Bash(git diff:*), Read, WebFetch(domain:nih.gov) — or mode:acceptEdits';
  const ok=el(p.claude?'<button>Don\'t ask again</button>':'<button>Always allow this</button>');
  const cancel=el('<button>Cancel</button>');
  ok.onclick=()=>send(true,{always:true,pattern:inp.value,note:`${p.name}: ${inp.value}`});
  inp.onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();ok.click()}if(e.key==='Escape'){e.preventDefault();row.remove()}};
  cancel.onclick=()=>row.remove();
  row.appendChild(inp);row.appendChild(ok);row.appendChild(cancel);
  if(p.claude&&(p.suggestions||[]).length){
   const hint=el('<div class=note style="width:100%;font-size:11.5px">Saved as a Claude Code permission rule. </div>');
   (p.suggestions||[]).filter(x=>x!==inp.value).forEach(sg=>{const b=el('<button class=ghost style="font-size:11px"></button>');
    b.textContent=sg;b.onclick=()=>{inp.value=sg};hint.appendChild(b)});
   row.appendChild(hint)}
  box.appendChild(row);inp.focus();inp.select()};
 const whyRow=()=>{
  if(box.querySelector('.whyrow'))return box.querySelector('.whyrow input').focus();
  const row=el('<div class="alwaysrow whyrow"></div>');
  const inp=document.createElement('input');inp.type='text';
  inp.placeholder=`what should ${who} do instead? (Enter with nothing just says no)`;
  const ok=el('<button>No</button>'),cancel=el('<button>Cancel</button>');
  ok.onclick=()=>{const m=inp.value.trim();send(false,m?{message:m}:undefined)};
  inp.onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();ok.click()}if(e.key==='Escape'){e.preventDefault();row.remove()}};
  cancel.onclick=()=>row.remove();
  row.appendChild(inp);row.appendChild(ok);row.appendChild(cancel);
  box.appendChild(row);inp.focus()};
 box._keys=e=>{
  if(box._done||!box.isConnected)return false;
  if(e.target&&e.target.closest&&e.target.closest('.alwaysrow'))return false;
  if(/^[1-9]$/.test(e.key)&&+e.key<=opts.length){opts[+e.key-1].act();return true}
  if(e.key==='ArrowDown'){sel=(sel+1)%opts.length;draw();return true}
  if(e.key==='ArrowUp'){sel=(sel+opts.length-1)%opts.length;draw();return true}
  if(e.key==='Enter'){opts[sel].act();return true}
  if(e.key==='Escape'){whyRow();return true}
  return false};
 return box}
// A prompt takes its numbers, the arrows, Enter and Esc only when it has the focus (click it, or
// Tab to it) or nothing else does -- never while the message box has it, where a "1" or an
// Enter meant for your own message would otherwise answer "yes" to a command.
addEventListener('keydown',e=>{
 if(composing(e))return;                      // never answer a prompt from a candidate pick
 if(e.metaKey||e.ctrlKey||e.altKey||$('#modalhost').innerHTML)return;
 const ae=document.activeElement;
 const inBox=ae&&ae.closest&&ae.closest('.ccask:not(.answered)');
 if(!inBox&&ae&&ae!==document.body)return;
 if(inBox&&/^(input|textarea|select|button|summary)$/i.test(ae.tagName))return;   // their own keys
 const open=inBox||[...document.querySelectorAll('#wrap .ccask:not(.answered)')].filter(b=>b._keys&&!b._done).pop();
 if(open&&open._keys&&open._keys(e)){e.preventDefault();e.stopImmediatePropagation()}},true);

// A question the model asks mid-task (ask_user): pick an option or type an answer.
function questionBox(p){
 // a question with choices, laid out as Claude Code asks one: numbered options you can
 // pick with the keys, a box for your own words, and ticks when several may apply
 const box=el('<div class="approve ccask ccqbox" tabindex=0></div>');
 const h=el('<div class=ccttl></div>');h.textContent=p.header||'Question';box.appendChild(h);
 const qq=el('<div class=ccq></div>');qq.textContent=p.question;box.appendChild(qq);
 const send=async ans=>{
  if(box._done)return;box._done=true;
  box.querySelectorAll('button,input').forEach(b=>b.disabled=true);
  let r;try{r=await fetch('/api/answer',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({id:p.id,answer:ans})})}catch(e){box._done=false;box.querySelectorAll('button,input').forEach(b=>b.disabled=false);
   toast('could not reach Orbit — try again');return}
  box.classList.add('answered');
  box.innerHTML='';const d=el('<div class=ccdone></div>');
  d.textContent=r.ok?'⏺ '+p.question.slice(0,80)+' — '+(Array.isArray(ans)?ans.join(', '):ans)
                   :'already answered — in another window, or it timed out';
  box.appendChild(d)};
 const opts=(p.options||[]).map(o=>typeof o==='object'&&o?{label:o.label||String(o),desc:o.description||''}:{label:String(o),desc:''});
 const list=el('<div class=ccopts></div>');
 const picked=new Set();let sel=0;
 const draw=()=>[...list.children].forEach((r,i)=>{r.classList.toggle('sel',i===sel);
  const bx=r.querySelector('.ccbx');if(bx)bx.textContent=picked.has(i)?'☒':'☐'});
 opts.forEach((o,i)=>{
  const r=el('<div class=ccopt><span class=ccptr>❯</span><span class=ccn></span>'+
   (p.multiple?'<span class=ccbx></span>':'')+'<span class=ccl></span></div>');
  r.querySelector('.ccn').textContent=(i+1)+'.';r.querySelector('.ccl').textContent=o.label;
  if(o.desc){const d=el('<span class=cch></span>');d.textContent=o.desc;r.appendChild(d)}
  r.onmouseenter=()=>{sel=i;draw()};
  r.onclick=()=>{if(p.multiple){picked.has(i)?picked.delete(i):picked.add(i);draw()}else send(o.label)};
  list.appendChild(r)});
 if(opts.length)box.appendChild(list);
 draw();
 const row=el('<div class=alwaysrow></div>');const inp=document.createElement('input');inp.type='text';
 inp.placeholder=opts.length?'or type your own answer':'type your answer';
 const go_=el('<button>Send</button>');
 go_.onclick=()=>{const own=inp.value.trim();
  if(p.multiple&&opts.length){const a=[...picked].sort().map(i=>opts[i].label);if(own)a.push(own);if(a.length)send(a);return}
  if(own)send(own)};
 inp.onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();go_.click()}};
 row.appendChild(inp);row.appendChild(go_);box.appendChild(row);
 box._keys=e=>{
  if(box._done||!box.isConnected||!opts.length)return false;
  const n=parseInt(e.key,10);
  if(n>=1&&n<=opts.length){list.children[n-1].click();return true}
  if(e.key==='ArrowDown'){sel=(sel+1)%opts.length;draw();return true}
  if(e.key==='ArrowUp'){sel=(sel+opts.length-1)%opts.length;draw();return true}
  if(e.key===' '&&p.multiple){list.children[sel].click();return true}
  if(e.key==='Enter'){if(p.multiple)go_.click();else list.children[sel].click();return true}
  if(e.key==='Escape'){inp.focus();return true}
  return false};
 return box}
// Claude Code · local Qwen: this chat's permission mode (live while it answers),
// and what Claude Code reports about the session.
const CQ_MODES={default:'Ask',acceptEdits:'Accept edits',plan:'Plan',auto:'Auto',dontAsk:"Don't ask",bypassPermissions:'Bypass'};
let CQ_INFO=null, CQ_CMDS=[];
function isClaudeModelId(m){m=m||MODELS.default||'';return m.startsWith('claude-qwen-cli')||m.startsWith('harness:')}
function isClaudeChat(){const m=MODELS.current||MODELS.default||'';return m.startsWith('claude-qwen-cli')||m.startsWith('harness:')}
function isCodexChat(){return (MODELS.current||MODELS.default||'').startsWith('codex:')}
async function drawClaudeBar(){
 let b=$('#cqbar');
 if(!(isClaudeChat()||isCodexChat())||!sid){if(b)b.style.display='none';return}
 if(!b){b=el(`<span id=cqbar><select title="Claude Code permission mode for this chat — changes a running answer too">${
   Object.entries(CQ_MODES).map(([k,v])=>`<option value=${k}>${v}</option>`).join('')}</select><span class=cqdir title="the folder this chat's Claude session works in"></span><span class=cqi title="Claude Code session">Claude Code</span></span>`);
  (($('#planmode'))||$('#title')).after(b);
  b.querySelector('select').onchange=async e=>{
   if(e.target.value==='bypassPermissions'&&!confirm('Bypass: Claude Code runs every tool — shell commands, edits, deletions — without asking. Use it only in a folder you can afford to lose. Switch?')){
    e.target.value=(CQ_INFO&&CQ_INFO.prefs||{}).permission_mode||'default';return}
   const d=await apiPost('/api/claude/mode',{sid,mode:e.target.value},'permission mode');
   if(d)toast('permission mode: '+CQ_MODES[d.mode]+(d.live?' — applied to the running answer':''))};
  b.querySelector('.cqi').onclick=()=>isCodexChat()?codexPanel():claudePanel();
  b.querySelector('.cqdir').onclick=()=>folderDialog()}
 b.style.display='';
 {const cx=isCodexChat();const ci=b.querySelector('.cqi');ci.textContent=cx?'Codex':'Claude Code';ci.title=cx?'Codex thread — click for details':'Claude Code session'}
 try{CQ_INFO=await (await fetch('/api/claude/info?sid='+encodeURIComponent(sid))).json();CQ_INFO.sid_for=sid}catch(e){return}
 b.querySelector('select').value=(CQ_INFO.prefs||{}).permission_mode||(CQ_INFO.settings||{}).permission_mode||CQ_INFO.claude_default_mode||'default';
 drawModeHint();
 const dir=CQ_INFO.cwd||CQ_INFO.cwd_pref||CQ_INFO.cwd_default;const chip=b.querySelector('.cqdir');
 const rh=CQ_INFO.host;
 chip.textContent=(rh?'🖥 '+rh+':':'📁 ')+(dir?dir.replace(/^\/Users\/[^/]+/,'~'):(rh?'~':'workspace'));
 chip.classList.toggle('remote',!!rh);
 chip.title=(rh?'on '+rh+' over SSH: ':'')+(dir||(rh?'home folder':'Orbit workspace (default)'))+(CQ_INFO.session?' — this chat\'s Claude session works here':' — click to choose where this chat starts');
 CQ_CMDS=(CQ_INFO.commands||[]).map(c=>({c:'/'+c.name,d:(c.description||'Claude Code').slice(0,120),cc:1}));
 if(!CQ_CMDS.length)fetch('/api/claude/commands').then(r=>r.json()).then(d=>{     // before its first answer too
  CQ_CMDS=(d.commands||[]).map(c=>({c:'/'+c.name,d:(c.description||'Claude Code').slice(0,120),cc:1}))}).catch(()=>{})}
async function codexPanel(){
 const i=await (await fetch('/api/codex/info')).json();
 openSheet('Codex',body=>{
  const rl=i.rate_limits||{};const pct=w=>w&&w.usedPercent!=null?`${Math.max(0,100-w.usedPercent)}% left`+(w.resetsAt?`, resets ${new Date(w.resetsAt*1000).toLocaleString([], {weekday:'short',hour:'numeric',minute:'2-digit'})}`:''):'';
  body.innerHTML=`<div class=grid>
   <label>Installed</label><div>${i.installed?esc(i.version||'yes'):'no — <code>brew install codex</code>'}</div>
   <label>Your account</label><div>${i.login==='chatgpt'?'signed in with ChatGPT':i.login==='api_key'?'an API key':'not signed in — run <code>codex login</code> in a terminal'}</div>
   <label>This chat</label><div>${CQ_INFO&&CQ_INFO.codex_thread?'Codex thread <code>'+esc(CQ_INFO.codex_thread)+'</code> — also in the Codex CLI and app (<code>codex resume '+esc(CQ_INFO.codex_thread)+'</code>)':'starts a Codex thread with its first message'}</div>
   <label>Where</label><div>${CQ_INFO&&CQ_INFO.host?'on <b>'+esc(CQ_INFO.host)+'</b> over SSH — Codex runs there, reaching your models through Orbit':'this Mac'} · ${esc((CQ_INFO&&(CQ_INFO.cwd||CQ_INFO.cwd_pref||CQ_INFO.cwd_default))||(CQ_INFO&&CQ_INFO.host?'home folder':'Orbit workspace'))} <span class=note>(the folder chip at the top changes it)</span></div>
   ${CQ_INFO&&CQ_INFO.host?`<label>On ${esc(CQ_INFO.host)}</label><div style="display:flex;gap:6px;flex-wrap:wrap"><button class=ghost id=cx_install>Install or check Codex there</button><button class=ghost id=cx_copylogin title="copies this Mac's ~/.codex/auth.json there (readable only by you) — only needed for your ChatGPT account's models">Copy this Mac's Codex sign-in there</button></div>`:''}
   ${rl.primary||rl.secondary?`<label>ChatGPT limits</label><div>${[pct(rl.primary)&&'5 hours: '+pct(rl.primary),pct(rl.secondary)&&'week: '+pct(rl.secondary)].filter(Boolean).join(' · ')}</div>`:''}
   <label>Permissions</label><div class=note>Auto and Accept edits: Codex works in the folder's sandbox and asks here before going outside it. Ask: every command is asked. Plan: read-only. Bypass: no sandbox, no questions.</div>
   <label>Models</label><div class=note>Your ChatGPT account's models use Codex's own sign-in. Every other provider in Settings → Models & keys runs through Orbit's gateway, with your key kept in Orbit.</div>
  </div>`;
  const h=CQ_INFO&&CQ_INFO.host;
  if(h){body.querySelector('#cx_install').onclick=async ev=>{ev.target.textContent='checking '+h+'…';
    const r=await apiPost('/api/codex/install',{host:h},'install');ev.target.textContent='Install or check Codex there';if(r)toast('Codex '+(r.version||'')+' on '+h+': '+r.path)};
   body.querySelector('#cx_copylogin').onclick=async()=>{if(!confirm('Copy your Codex sign-in (this Mac\'s ~/.codex/auth.json) to '+h+'? It is saved there readable only by your account. Other people with admin rights on that machine could still read it.'))return;
    const r=await apiPost('/api/codex/copy_login',{host:h},'copy sign-in');if(r)toast('signed in on '+h)}}
  },{sub:i.running?'Codex is running':'starts with the first Codex message'})}
// Claude Code mode: provider and model pickers in place of Orbit's model list.
let HPROV_CACHE={};
function fmtCtx(n){n=+n||0;return n>=1e6?(Math.round(n/1e5)/10+'M'):n>=1000?Math.round(n/1000)+'k':String(n||'')}
function providerOf(id){id=id||'';if(id.startsWith('claude-qwen-cli'))return 'local';
 if(id.startsWith('agy-cli:'))return 'agy';
 if(id.startsWith('muse-cli:'))return 'muse';
 const m=id.match(/^(?:harness|codex):([^/]+)\//);return m?m[1]:''}
const codexMode=()=>!!MODELS.codex_mode&&!MODELS.harness_mode;
// What runs on this Mac first, then your models on a server (custom providers), then the hosted ones: the order of the list.
function providerOrder(list){const rank=p=>p.id==='local'?0:p.custom?1:2;
 return list.map((p,i)=>[p,i]).sort((a,b)=>rank(a[0])-rank(b[0])||a[1]-b[1]).map(x=>x[0])}
async function drawHarnessPicker(force){
 const pv=$('#hprov'),ms=$('#hmodel');if(!pv)return;
 let view;try{view=await (await fetch('/api/harness')).json()}catch(e){return}
 const cur=MODELS.current||MODELS.default||'';
 const curProv=providerOf(cur);
 if(codexMode()){
  // Codex: your ChatGPT account first, then every provider with an API
  const cliProvs0=CLI_PROVIDERS.filter(c=>(MODELS.models||[]).some(m=>m.id.startsWith(c.prefix)))
   .map(c=>({id:c.id,label:c.label,ready:(MODELS.models||[]).some(m=>m.id.startsWith(c.prefix)&&m.ready),cli:true}));
  const provs=[{id:'chatgpt',label:'ChatGPT account (Codex)',ready:true}].concat(providerOrder((view.providers||[]).filter(p=>p.id!=='claude'))).concat(cliProvs0);
  const onCli=CLI_PROVIDERS.some(c=>c.id===curProv);
  pv.innerHTML=(((curProv&&cur.startsWith('codex:'))||onCli)?'':'<option value="">— pick a provider —</option>')+provs.map(p=>
   `<option value="${esc(p.id)}"${p.id===curProv&&(cur.startsWith('codex:')||onCli)?' selected':''}>${esc(p.label)}${p.ready?'':(p.cli?' — not signed in':' — add a key')}</option>`).join('');
  if(curProv&&(cur.startsWith('codex:')||onCli))await fillHarnessModels(curProv,cur,force);else ms.innerHTML='<option>—</option>';
  return}
 const cliProvs=CLI_PROVIDERS.filter(c=>(MODELS.models||[]).some(m=>m.id.startsWith(c.prefix)))
  .map(c=>({id:c.id,label:c.label,ready:(MODELS.models||[]).some(m=>m.id.startsWith(c.prefix)&&m.ready)}));
 pv.innerHTML=(curProv?'':'<option value="">— pick a provider —</option>')+providerOrder(view.providers||[]).concat(cliProvs).map(p=>
  `<option value="${esc(p.id)}"${p.id===curProv?' selected':''}>${esc(p.label)}${p.ready?'':(p.auth==='subscription'?' — not signed in':' — add a key')}${liveShort(((p.accounts||[]).find(a=>a.key_set&&!a.exhausted)||(p.accounts||[])[0]||{}).live)}</option>`).join('');
 if(curProv)await fillHarnessModels(curProv,cur,force);else ms.innerHTML='<option>—</option>'}
// The engines a chat can run on, as one row of pills in the popover under the chip. A new harness (ZCode, ...)
// is one more line here: `mode` ones are Orbit's own, Claude Code and Codex (a switch on the Mac); `cli` ones
// are a signed-in CLI whose models share a prefix.
var ENGINES=[
 {id:'orbit',label:'Orbit',mode:'orbit',tip:"Orbit's own agent loop, on any model"},
 {id:'claude',label:'Claude Code',mode:'claude',tip:'Claude Code runs the chat — on your Claude plan or any provider'},
 {id:'codex',label:'Codex',mode:'codex',tip:"Codex runs the chat — on your ChatGPT account or any provider"},
 {id:'agy',label:'Antigravity',cli:'agy-cli:',tip:"Google's Antigravity CLI, on your Antigravity sign-in"},
 {id:'muse',label:'Muse Code',cli:'muse-cli:',tip:"Meta's Muse Code agent, on your Meta sign-in or API key"}];
function engineOfModel(id){id=id||'';
 const c=ENGINES.find(e=>e.cli&&id.startsWith(e.cli));if(c)return c.id;
 if(id.startsWith('codex:'))return 'codex';
 if(id.startsWith('harness:')||id.startsWith('claude-qwen-cli'))return 'claude';
 return MODELS.harness_mode?'claude':(MODELS.codex_mode&&!MODELS.harness_mode)?'codex':'orbit'}
function shortModelName(id){
 const m=(MODELS.models||[]).find(x=>x.id===id);
 let n=m?(m.label||m.model):(id||'pick a model');
 n=n.replace(/^(Claude Code|Antigravity|Gemini CLI|Codex|Muse Code) · /,'').split(' · ')[0].replace(/\s*\(latest\)/,'');
 return n.length>34?n.slice(0,33)+'…':n}
function drawEngineUI(){
 const chip=$('#engchip');if(!chip)return;
 const cur=MODELS.current||MODELS.default||'';
 const eid=engineOfModel(cur),eng=ENGINES.find(e=>e.id===eid)||ENGINES[0];
 chip.querySelector('.engname').textContent=eng.label;
 chip.querySelector('.engmodel').textContent=shortModelName(cur);
 // which Claude account, when there are several and this chat runs on the subscription; and its effort
 const extra=[];
 const accs=((HPROV_CACHE||{}).claude||{}).accounts||[];
 if(cur.startsWith('harness:claude/')&&accs.length>1){
  const id=(CHATPREFS||{}).claude_account,a=accs.find(x=>x.id===id)||accs.find(x=>x.home)||accs[0];
  if(a)extra.push(a.label)}
 const ef=(CHATPREFS||{}).reasoning_effort;if(ef)extra.push(ef==='xhigh'?'extra high':ef);
 chip.querySelector('.engextra').textContent=extra.length?'· '+extra.join(' · '):'';
 chip.title=eng.label+' · '+(shortModelName(cur))+(extra.length?' · '+extra.join(' · '):'')+' — click to change';
 const box=$('#engpills');if(!box)return;box.innerHTML='';
 ENGINES.forEach(e=>{
  const ready=!e.cli||(MODELS.models||[]).some(m=>m.id.startsWith(e.cli)&&m.ready);
  if(e.cli&&!(MODELS.models||[]).some(m=>m.id.startsWith(e.cli)))return;      // not installed here: not offered
  const b=el('<button class=engpill></button>');b.textContent=e.label;b.title=e.tip+(ready?'':' — not signed in');
  if(e.id===eid)b.classList.add('on');if(!ready)b.classList.add('off');
  b.onclick=()=>pickEngine(e);box.appendChild(b)})}
async function pickEngine(e){
 if(e.cli){
  const list=(MODELS.models||[]).filter(m=>m.id.startsWith(e.cli)&&m.ready);
  if(!list.length){toast(e.label+' is not signed in on this Mac — see Settings → Models & keys');return}
  if(!(MODELS.current||'').startsWith(e.cli)){await chooseHarnessModel(list[0].id);await loadModels()}
 }else{
  const now=MODELS.harness_mode?'claude':(MODELS.codex_mode?'codex':'orbit');
  if(now!==e.mode){
   if(e.mode==='claude')await $('#hmode').onclick();
   else if(e.mode==='codex')await $('#cmode').onclick();
   else if(now==='claude')await $('#hmode').onclick();
   else await $('#cmode').onclick()}}
 drawEngineUI()}
function openEnginePop(on){
 const pop=$('#engpop'),chip=$('#engchip');if(!pop||!chip)return;
 const open=on===undefined?!pop.classList.contains('open'):!!on;
 pop.classList.toggle('open',open);chip.setAttribute('aria-expanded',open?'true':'false');
 if(open)drawEngineUI()}
document.addEventListener('click',e=>{const pop=$('#engpop');
 if(pop&&pop.classList.contains('open')&&!e.target.closest('#engpop,#engchip'))openEnginePop(false)});
document.addEventListener('keydown',e=>{if(e.key==='Escape')openEnginePop(false)});
// Antigravity and Gemini CLI are not Claude Code or Codex providers: their models are the Mac's own signed-in
// CLIs. They sit in the same picker, so any chat can move to them from either mode.
const CLI_PROVIDERS=[{id:'agy',prefix:'agy-cli:',label:'Antigravity (CLI)',group:'Antigravity'},
 {id:'muse',prefix:'muse-cli:',label:'Muse Code (CLI)',group:'Muse Code'}];
async function fillHarnessModels(pid,cur,refresh){
 const ms=$('#hmodel');
 const cli=CLI_PROVIDERS.find(c=>c.id===pid);
 if(cli){
  const list=(MODELS.models||[]).filter(m=>m.id.startsWith(cli.prefix));
  const nm=m=>(m.label||m.model).replace(/^(Antigravity|Gemini CLI|Muse Code) · /,'').replace(/ · CLI$/,'');
  ms.innerHTML=(list.some(m=>m.id===cur)?'':'<option value="">— pick a model —</option>')+
   `<optgroup label="${esc(cli.group)}">`+list.map(m=>`<option value="${esc(m.id)}"${m.id===cur?' selected':''}>${esc(nm(m))}${m.ready?'':' — not signed in'}</option>`).join('')+'</optgroup>';
  ms.title=cli.label+': runs on its own sign-in on this Mac — '+list.length+' models';
  drawAcctPick();return}
 if(codexMode()){
  const key='codex:'+pid;
  if(refresh||!HPROV_CACHE[key])HPROV_CACHE[key]=await (await fetch('/api/codex/models?provider='+encodeURIComponent(pid))).json();
  const d=HPROV_CACHE[key]||{models:[]};
  const recent=[];       // (it listed models of every other provider here, under whichever provider was chosen: confusing)
  ms.innerHTML=(d.models.some(m=>m.id===cur)?'':'<option value="">— pick a model —</option>')+
   (recent.length?`<optgroup label="Recent">${recent.map(r=>`<option value="${esc(r.id)}">${esc(r.label)}</option>`).join('')}</optgroup>`:'')+
   `<optgroup label="${esc(d.label||pid)}">`+d.models.map(m=>`<option value="${esc(m.id)}"${m.id===cur?' selected':''}>${esc(m.label)}${m.context?' · '+fmtCtx(m.context):''}${m.ready?'':' — not ready'}${esc(opSuffix(m.offpeak))}</option>`).join('')+'</optgroup>';
  ms.title=`Codex · ${d.label}: ${d.models.length} models`;return}
 if(refresh||!HPROV_CACHE[pid]){
  if(refresh)await apiPost('/api/harness/refresh',{provider:pid},'refreshing models');
  HPROV_CACHE[pid]=await (await fetch('/api/harness/models?provider='+encodeURIComponent(pid))).json()}
 const d=HPROV_CACHE[pid]||{models:[]};
 const list=d.models.filter(m=>!m.hidden||m.id===cur);
 // This list is the chosen provider's models. It used to start with a "Recent" group of models from every other provider
 // (Claude, DeepSeek...) under whichever provider was chosen, and picking one silently switched the provider above.
 const recent=[];
 ms.innerHTML=(list.some(m=>m.id===cur)?'':'<option value="">— pick a model —</option>')+
  (recent.length?`<optgroup label="Recent">${recent.map(r=>`<option value="${esc(r.id)}">${esc(r.label)}</option>`).join('')}</optgroup>`:'')+
  `<optgroup label="${esc(d.label||pid)}">`+list.map(m=>
  `<option value="${esc(m.id)}"${m.id===cur?' selected':''}>${esc(m.label)}${m.context?' · '+fmtCtx(m.context):''}${usageShort(m.usage)?' · '+usageShort(m.usage):''}${esc(opSuffix(m.offpeak))}</option>`).join('')+'</optgroup>';
 drawAcctPick();
 ms.title=`${d.label}: ${d.models.length} models${d.fetched_at?' · list from '+new Date(d.fetched_at*1000).toLocaleDateString():''}`+
  (d.live&&!d.live.error?` · ${d.live.account}: ${liveLong(d.live)} (shared by all models)`:'')+
  (d.ready?'':' — add a key in Settings → Models & keys')}
// "5h 80% · wk 95% left": what is left of a model's allowance on the account in use,
// estimated from what went through Orbit (OpenCode Go publishes allowances, not balances)
function usageShort(u){
 if(!u||!u.windows||!u.requests)return '';          // nothing used through Orbit yet
 const w=u.windows;
 // the allowance is the account's, shared by all models (shown with the account); per model, what it used
 if(w.month&&w.month.spent)return `~$${w.month.spent.toFixed(2)} used this month via Orbit`;
 return ''}
// OpenCode Go's own figures for an account: what is left of the 5-hour, weekly and monthly allowance
function liveShort(l){
 if(!l||l.error||!(l.rolling||l.monthly))return '';
 // the windows an account has: a Claude plan has the 5-hour and the weekly one, no monthly
 const left=w=>Math.max(0,100-(l[w].percent||0));
 const parts=[['rolling','5h'],['weekly','wk'],['monthly','mo']].filter(([w])=>l[w]).map(([w,n])=>`${left(w)}% ${n}`);
 return ` — ${parts.join(' · ')} left`}
function liveLong(l){
 if(!l)return '';
 if(l.error)return 'usage unavailable ('+l.error+')';
 const row=(n,w)=>l[w]?`${n}: ${Math.max(0,100-(l[w].percent||0))}% left${l[w].status==='rate-limited'?' (limit reached)':''}, resets ${new Date(l[w].resetsAt).toLocaleString([], {month:'short',day:'numeric',hour:'numeric',minute:'2-digit'})}`:'';
 return [row('5 hours','rolling'),row('week','weekly'),row('month','monthly')].filter(Boolean).join(' · ')}
function usageLong(u){
 if(!u||!u.windows)return '';
 const w=u.windows,row=(n,k)=>w[k]?`${n}: $${w[k].spent.toFixed(2)}${w[k].allowance!=null?` of $${w[k].allowance} (${w[k].left_pct}% left)`:''}`:'';
 return [row('5 hours','5h'),row('week','week'),row('month','month')].filter(Boolean).join(' · ')+(u.account?` — ${u.account}`:'')}
async function chooseHarnessModel(id){
 if(!id)return;
 const d=await apiPost('/api/model/select',{id,sid},'model');if(!d)return;
 MODELS.current=id;drawClaudeBar();refreshStatus();drawOffpeak();
 const m=Object.values(HPROV_CACHE).flatMap(x=>x.models||[]).find(x=>x.id===id);
 if(codexMode()&&id.startsWith('codex:'))MODELS.codex_recent=[{id,label:(m&&m.label)||id}].concat((MODELS.codex_recent||[]).filter(r=>r.id!==id)).slice(0,6);
 if(m)toast(`this chat uses ${m.label}${m.context?' · '+fmtCtx(m.context)+' context':''}`)}
$('#hmode').onclick=async()=>{
 const on=!MODELS.harness_mode;
 const d=await apiPost('/api/harness/mode',{engine:on?'claude':'orbit'},'Claude Code mode');if(!d)return;
 HPROV_CACHE={};await loadModels();drawClaudeBar();
 toast(on?'Claude Code mode: new chats run through the Claude Code harness':'Claude Code mode off')};
$('#cmode').onclick=async()=>{
 const on=!codexMode();
 const d=await apiPost('/api/harness/mode',{engine:on?'codex':'orbit'},'Codex mode');if(!d)return;
 HPROV_CACHE={};await loadModels();drawClaudeBar();
 toast(on?'Codex mode: new chats run through Codex — pick the provider and model at the top':'Codex mode off')};
$('#hprov').onchange=async e=>{
 const pid=e.target.value;if(!pid)return;
 await fillHarnessModels(pid,'');
 if(CLI_PROVIDERS.some(c=>c.id===pid)){
  const c=CLI_PROVIDERS.find(c=>c.id===pid);
  const m=(MODELS.models||[]).find(m=>m.id.startsWith(c.prefix)&&m.ready);
  if(!m){toast(c.label+' is not signed in on this Mac — see Settings → Models & keys');return}
  $('#hmodel').value=m.id;chooseHarnessModel(m.id);return}
 if(codexMode()){const d=HPROV_CACHE['codex:'+pid]||{};const first=(d.models||[]).find(m=>m.ready)||(d.models||[])[0];
  if(!d.ready){toast(pid==='chatgpt'?'Codex is not signed in — run `codex login` in a terminal':`${d.label} needs a key — add it in Settings → Models & keys`);return}
  if(first){$('#hmodel').value=first.id;chooseHarnessModel(first.id)}return}
 const d=HPROV_CACHE[pid]||{};
 if(!d.ready){toast(pid==='claude'?'The claude command is not signed in — run `claude auth login` in a terminal (or it is not installed)':`${d.label} needs a key — add it in Settings → Models & keys`);if(pid!=='claude')openSettings('models');return}
 const first=(d.models||[]).find(m=>!m.hidden);
 if(first){$('#hmodel').value=first.id;chooseHarnessModel(first.id)}};
$('#hmodel').onchange=async e=>{const id=e.target.value;await chooseHarnessModel(id);
 const pid=providerOf(id);if(pid&&pid!==$('#hprov').value){$('#hprov').value=pid;await fillHarnessModels(pid,id)}};
$('#hrefresh').onclick=async()=>{const pid=$('#hprov').value;if(!pid||pid==='local'||CLI_PROVIDERS.some(c=>c.id===pid)){loadModels();return}
 $('#hrefresh').textContent='…';await fillHarnessModels(pid,$('#hmodel').value,true);$('#hrefresh').textContent='↻';
 toast(`${(HPROV_CACHE[pid]||{}).models?.length||0} models`)};
// New chat with…: model, working folder and permission mode chosen together,
// and saved as presets to start the same kind of chat again (bunshin's agents).
async function newChatWith(){
 await loadModels();
 const info=await (await fetch('/api/claude/info?sid=')).json();
 const presets=(info.settings||{}).presets||[];
 const fl=(await (await fetch('/api/claude/folders')).json()).folders||[];
 const host=$('#modalhost');
 host.innerHTML=`<div class=modal><div class="sheet cqpanel"><header><b>New chat with…</b>
   <button class=ghost style="margin-left:auto" id=nwx>close</button></header><div class=body>
   ${presets.length?`<div class=sec>Presets</div><div id=nw_presets></div>`:''}
   <div class=grid>
    <label>Model</label><select id=nw_model>${modelOptions(MODELS.default||'')}</select>
    <label>Where</label><select id=nw_where><option value="">This Mac</option></select>
    <label>Folder</label><div style="display:flex;gap:6px"><input type=text id=nw_cwd list=nw_dirs placeholder="Orbit workspace — type a path or choose" spellcheck=false style="flex:1"><button class=ghost id=nw_pick>Choose…</button></div>
    <div class=hint2 id=nw_probe></div><div id=nw_browse style="grid-column:1/-1"></div>
    <label>Permission mode</label><select id=nw_mode><option value="">Claude's default</option>${Object.entries(CQ_MODES).map(([k,v])=>`<option value=${k}>${v}</option>`).join('')}</select>
    <label>Save as preset</label><input type=text id=nw_name placeholder="name (optional), e.g. Lab analysis · DeepSeek">
   </div><datalist id=nw_dirs>${fl.map(f=>`<option value="${esc(f.path)}">`).join('')}</datalist>
   <div class=note style="margin-top:6px">Folder and permission mode apply to Claude Code models; any model can be picked.</div>
   <button class=primary id=nw_go style="margin-top:8px">Start chat</button></div></div></div>`;
 $('#nwx').onclick=closeModal;
 remoteHosts().then(hs=>{const sel=$('#nw_where');if(!sel)return;
  hs.forEach(h=>sel.appendChild(el(`<option value="${esc(h.host)}">${esc(h.host)} (SSH)</option>`)))});
 const nwPlaces=async()=>{const h=$('#nw_where').value;
  let d;try{d=await (await fetch('/api/claude/folders?host='+encodeURIComponent(h))).json()}catch(e){return}
  const dl=$('#nw_dirs');if(!dl)return;
  dl.innerHTML=[...(d.bookmarks||[]).map(p=>['★ bookmark',p]),...(d.recent||[]).map(p=>['recent',p]),...(d.folders||[]).map(f=>[f.why,f.path])]
   .map(([w,p])=>`<option value="${esc(p)}">${esc(w)}</option>`).join('');
  if(h&&!$('#nw_cwd').value&&(d.bookmarks||[])[0])$('#nw_cwd').value=d.bookmarks[0]};
 nwPlaces();
 $('#nw_where').onchange=async()=>{const h=$('#nw_where').value;$('#nw_browse').innerHTML='';$('#nw_cwd').value='';nwPlaces();
  if(!h){$('#nw_probe').innerHTML='';return}
  if(!$('#nw_cwd').value)$('#nw_cwd').value=((((REMOTE_HOSTS||[]).find(x=>x.host===h)||{}).saved)||{}).default_dir||'~';
  $('#nw_probe').innerHTML='checking '+esc(h)+'…';
  const pr=await apiPost('/api/remote/probe',{host:h},'checking the host');
  if($('#nw_where')&&$('#nw_where').value===h)$('#nw_probe').innerHTML=probeLine(pr)};
 const start=async({model,cwd,mode,host:where})=>{
  closeModal();await newChat();
  if(model)await apiPost('/api/model/select',{id:model,sid},'model');
  if(cwd||where)await apiPost('/api/claude/cwd',{sid,cwd,host:where||''},'folder');
  if(mode)await apiPost('/api/claude/mode',{sid,mode},'permission mode');
  await loadModels();drawClaudeBar();q.focus()};
 const box=$('#nw_presets');
 presets.forEach((p,i)=>{
  const r=el('<div class=memrow style="cursor:pointer"><b></b><span></span><button class=ghost>start</button><button class=ghost>delete</button></div>');
  const ml=((MODELS.models||[]).find(m=>m.id===p.model)||{}).label||p.model||'default model';
  r.querySelector('b').textContent=p.name;r.querySelector('span').textContent=[ml,(p.host?p.host+':':'')+(p.cwd||''),CQ_MODES[p.mode]].filter(Boolean).join(' · ');
  const [go,del]=r.querySelectorAll('button');
  go.onclick=()=>start(p);
  del.onclick=async e=>{e.stopPropagation();presets.splice(i,1);
   await apiPost('/api/claude/settings',{settings:{presets}},'presets');r.remove()};
  box.appendChild(r)});
 $('#nw_pick').onclick=async()=>{
  const h=$('#nw_where').value;
  if(h){const b=await remoteBrowser(h,$('#nw_cwd').value.trim()||'~',p=>{$('#nw_cwd').value=p;$('#nw_browse').innerHTML=''});
   $('#nw_browse').innerHTML='';$('#nw_browse').appendChild(b);return}
  const p=await pickFolder($('#nw_cwd').value.trim(),'Folder for the new chat');if(p)$('#nw_cwd').value=p};
 $('#nw_go').onclick=async()=>{
  const p={model:$('#nw_model').value,cwd:$('#nw_cwd').value.trim(),mode:$('#nw_mode').value,host:$('#nw_where').value};
  if(p.host&&!isClaudeModelId(p.model))return toast('a chat on another machine runs through Claude Code — pick a Claude Code model');
  const name=$('#nw_name').value.trim();
  if(name){presets.push({name,...p});await apiPost('/api/claude/settings',{settings:{presets}},'presets')}
  start(p)}}
// Settings → Models & keys: the providers both Claude Code mode and Orbit's own
// chat use — accounts and keys (typed by you, stored in Orbit's secrets), region,
// models with what is left of their allowance, and a test.
// When a model keeps failing: the next model to carry on with (qqcore.fallback_candidates)
async function renderFallback(box){
 const r=await apiPost('/api/settings',{settings:{}},'settings');if(!r)return;
 const S_=r.settings||{};
 let list=[...(S_.fallback_models||[])];
 box.innerHTML=`<div class=sec>When a model keeps failing</div>
  <div class=grid>
   <label>Fall back</label><div><label style="display:flex;gap:7px;align-items:center"><input type=checkbox id=fb_on> carry on with another model instead of stopping</label></div>
   <label>Stay on the model</label><div><label style="display:flex;gap:7px;align-items:center"><input type=checkbox id=fb_stay> never switch: wait for the model to come back and ask again</label>
    <div class=hint2 style="margin-top:4px">For a model you chose on purpose, such as Qwen on the cluster. When the connection drops the answer waits (every 30 s at most), picks up by itself as soon as the model answers, and keeps the same conversation. Stop cancels it. A wrong key still stops straight away. Each chat can override this with the <b>stay</b> button above the chat or <code>/stay on|off|auto</code>.</div>
    <div style="display:flex;gap:7px;align-items:center;margin-top:6px"><span class=note>Give up after</span><input type=number id=fb_hold min=1 max=168 style="width:70px"> <span class=note>hours of waiting</span></div></div>
   <label>Plan limit reached</label><div><label style="display:flex;gap:7px;align-items:center"><input type=checkbox id=fb_limit> carry on by itself when the allowance resets</label>
    <div class=hint2 style="margin-top:4px">When Claude's 5-hour or weekly limit, a ChatGPT limit or an OpenCode Go allowance stops an answer or a scheduled task, the chat continues a minute after the reset (read from the limit message or the account). It shows in Scheduled, where you can move or cancel it.</div></div>
   <label>After</label><div style="display:flex;gap:7px;align-items:center"><input type=number id=fb_after min=1 max=10 style="width:70px"> failed attempts <span class=note>(Claude Code and Codex retry on their own first)</span></div>
   <label>Same model first</label><div><label style="display:flex;gap:7px;align-items:center"><input type=checkbox id=fb_same> try the same model from another provider first (e.g. DeepSeek on OpenCode Zen when OpenCode Go is down)</label></div>
   <label>Then, in order</label><div><div id=fb_list></div><div style="display:flex;gap:6px;margin-top:6px"><select id=fb_add style="max-width:360px"></select><button class=ghost id=fb_addbtn>add</button></div>
   <div class=hint2 style="margin-top:4px">Each chat stays in its own harness: a Claude Code chat uses the Claude Code version of a model, a Codex chat the Codex one, an Orbit chat Orbit's. The answer says when it moves; the chat keeps its own model for the next message.</div></div>
  </div>`;
 $('#fb_on').checked=S_.fallback_enabled!==false;$('#fb_limit').checked=S_.resume_after_limit!==false;$('#fb_after').value=S_.fallback_after||3;$('#fb_same').checked=S_.fallback_same_model!==false;
 $('#fb_stay').checked=!!S_.no_fallback;$('#fb_hold').value=S_.hold_max_hours||12;
 const save=async()=>{const x=await apiPost('/api/settings',{settings:{fallback_enabled:$('#fb_on').checked,fallback_after:Math.max(1,+$('#fb_after').value||3),
  fallback_same_model:$('#fb_same').checked,no_fallback:$('#fb_stay').checked,hold_max_hours:Math.max(1,+$('#fb_hold').value||12),fallback_models:list,resume_after_limit:$('#fb_limit').checked}},'save');if(x)toast('saved')};
 const draw=()=>{const L=$('#fb_list');L.innerHTML=list.length?'':'<div class=note>none — only the same model elsewhere</div>';
  list.forEach((id,i)=>{const row=el(`<div class=memrow style="align-items:center"><span style="flex:1"></span><button class=ghost data-a=up>↑</button><button class=ghost data-a=dn>↓</button><button class=ghost data-a=rm>×</button></div>`);
   row.querySelector('span').textContent=(i+1)+'. '+modelName(id);
   row.onclick=ev=>{const a=ev.target.dataset.a;if(!a)return;
    if(a==='rm')list.splice(i,1);if(a==='up'&&i>0)[list[i-1],list[i]]=[list[i],list[i-1]];if(a==='dn'&&i<list.length-1)[list[i+1],list[i]]=[list[i],list[i+1]];
    draw();save()};L.appendChild(row)})};
 $('#fb_add').innerHTML=modelOptions('','choose a model…');
 $('#fb_addbtn').onclick=()=>{const v=$('#fb_add').value;if(!v||list.includes(v))return;list.push(v);draw();save()};
 ['fb_on','fb_after','fb_same','fb_limit','fb_stay','fb_hold'].forEach(id=>$('#'+id).onchange=save);
 draw()}
// Easy mode's two lists: Orbit's own tools, and the ones Claude Code says it has.
async function drawEasyTools(draft){
 const grid=$('#easygrid'), cbox=$('#easyclaude');
 if(!grid)return;
 const keep=new Set(draft.easy_tools||[]);
 // every tool that exists, not just the ones this chat is being offered: in easy mode
 // those are the short list, and you could not tick anything back on
 const all=[...new Set([...(INFO.all_tools||[]),...(INFO.tools||[])])].sort();
 grid.innerHTML='';
 all.forEach(n=>{const l=document.createElement('label');
  const c=document.createElement('input');c.type='checkbox';c.dataset.easy=n;c.checked=keep.has(n);
  l.appendChild(c);l.appendChild(document.createTextNode(' '+n));grid.appendChild(l)});
 $('#easycount').textContent=all.length?`${keep.size} of ${all.length} kept`:'';
 const load=async learn=>{
  cbox.innerHTML='<span class=note>'+(learn?'asking Claude Code…':'loading…')+'</span>';
  let d=null;
  try{d=await (await fetch('/api/claude/tools'+(learn?'?learn=1':''))).json()}catch(e){}
  cbox.innerHTML='';
  if(!d||!(d.known||[]).length){
   cbox.appendChild(el('<span class=note>Claude Code has not said yet what tools it has — send one message in Claude Code mode, or ask it again.</span>'));return}
  const ck=new Set(d.keep||[]);
  d.known.forEach(n=>{const l=document.createElement('label');
   const c=document.createElement('input');c.type='checkbox';c.dataset.ceasy=n;c.checked=ck.has(n);
   l.appendChild(c);l.appendChild(document.createTextNode(' '+n));cbox.appendChild(l)});
  const mbox=$('#easymcp'); if(mbox){
   const mk=new Set(d.mcp_keep||[]);
   mbox.innerHTML='';
   if(!(d.mcp||[]).length)mbox.appendChild(el('<span class=note>no MCP servers in your Claude config</span>'));
   (d.mcp||[]).forEach(n=>{const l=document.createElement('label');
    const c=document.createElement('input');c.type='checkbox';c.dataset.mcpeasy=n;c.checked=mk.has(n);
    l.appendChild(c);l.appendChild(document.createTextNode(' '+n));mbox.appendChild(l)})}};
 load(false);
 const b=$('#easylearn'); if(b)b.onclick=()=>load(true)}

async function renderHarnessModels(box){
 const h=await (await fetch('/api/harness')).json();
 const fmtName={messages:'native',chat:'via gateway',responses:'via gateway (Responses)'};
 box.innerHTML='';box.classList.remove('note');
 const gw=h.gateway||{};
 box.appendChild(el(`<div class=note style="margin-bottom:6px">One list for both modes: in Claude Code mode each model runs through the Claude Code harness; otherwise Orbit talks to it directly. Providers that speak Anthropic's API go straight to Claude Code; the rest — and any provider with several accounts — go through Orbit's gateway on 127.0.0.1:${esc(String(gw.port||'—'))}${gw.error?' — <b style="color:var(--err)">not running: '+esc(gw.error)+'</b>':''}, which adds your key (so it never reaches the Claude process), moves to your next account when one is used up, and counts usage.</div>`));
 const st=(gw.stats||{});
 if(st.requests)box.appendChild(el(`<div class=note>Gateway since Orbit started: ${st.requests} requests${st.errors?`, ${st.errors} failed`:''} · ${esc(Object.entries(st.by_provider||{}).map(([k,v])=>k+' '+v).join(', '))}</div>`));
 const pol=h.accounts_policy||{auto_switch:true,switch_back:true};
 const pc=el(`<div class=memrow style="display:block;margin:6px 0;padding:8px 10px;border:1px solid var(--line);border-radius:9px">
   <b>When an account runs out</b> <span class=note>— for any provider with more than one account: Claude, OpenCode Go…</span>
   <label style="display:block;margin:5px 0"><input type=checkbox id=pol_auto ${pol.auto_switch?'checked':''}> Move to the next account by itself, and say so in the chat</label>
   <label style="display:block;margin:5px 0"><input type=checkbox id=pol_back ${pol.switch_back?'checked':''}> Go back to the main account once its limit has reset</label>
   <div style="margin:5px 0"><span class=note>When every Claude account is used up: </span><select id=pol_fb style="max-width:300px">${modelOptions((INFO.settings||{}).limit_fallback_model||'','wait for the reset',id=>id.startsWith('harness:')&&!id.startsWith('harness:claude/'))}</select>
   <span class=note> (carries on in that chat with the model chosen)</span></div></div>`);
 const savePol=async()=>{const d=await apiPost('/api/harness/policy',{auto_switch:pc.querySelector('#pol_auto').checked,switch_back:pc.querySelector('#pol_back').checked},'saving');if(d)toast('saved')};
 pc.querySelector('#pol_auto').onchange=savePol;pc.querySelector('#pol_back').onchange=savePol;
 pc.querySelector('#pol_fb').onchange=async e=>{const d=await apiPost('/api/settings',{settings:{limit_fallback_model:e.target.value}},'saving');if(d){toast('saved');INFO=await (await fetch('/api/info')).json()}};
 box.appendChild(pc);
 // your Google plan: its own terminal agents sign in with your Google account
 const gc=el(`<div class=memrow style="display:block;margin:6px 0;padding:8px 10px;border:1px solid var(--line);border-radius:9px">
   <b>Sign in with Google</b> <span class=note>— the coding plan that comes with Google AI Pro / Ultra, through Google's own terminal agents</span>
   <div id=gcli class=note style="margin-top:4px">checking…</div>
   <div class=note>Each opens in Orbit's terminal; the first run asks you to sign in with your Google account in the browser.
    Their models then appear in the model picker. (An API key from Google AI Studio is the other way in: see <b>Gemini · Google AI</b> below.)</div></div>`);
 box.appendChild(gc);
 const drawG=async fresh=>{
  let d;try{d=await (await fetch('/api/google/cli'+(fresh?'?fresh=1':''))).json()}catch(e){return}
  const host=gc.querySelector('#gcli');host.innerHTML='';
  (d.clis||[]).forEach(c=>{
   const status=!c.installed?'not installed':c.signed_in===true?`✓ signed in${c.models?' · '+c.models+' models':''}`
    :c.signed_in===false?`sign-in not working yet${c.models?' · '+c.models+' models listed':''}`
    :`installed${c.models?' · '+c.models+' models':''} · press Test to check the sign-in`;
   const row=el(`<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:5px 0">
     <b style="min-width:130px">${esc(c.label)}</b><span class=note style="flex:1;min-width:180px">${esc(status)}</span>
     ${!c.installed?'<button class=ghost data-a=install title="types the install command; you press Enter">Install in the terminal</button>'
      :c.signed_in===true?'<button class=ghost data-a=login>Open in the terminal</button>'
      :'<button class=ghost data-a=login>Sign in in the terminal</button>'}
     ${c.installed?'<button class=ghost data-a=test title="a one-word question, to see that the sign-in works">Test</button>':''}
     <button class=ghost data-a=check>Check again</button></div>`);
   row.querySelector('[data-a=install]')&&(row.querySelector('[data-a=install]').onclick=()=>terminalDo(c.install,false));
   row.querySelector('[data-a=login]')&&(row.querySelector('[data-a=login]').onclick=()=>terminalDo(c.login,true));
   const tb=row.querySelector('[data-a=test]');
   if(tb)tb.onclick=async()=>{tb.textContent='…';tb.disabled=true;
    const r=await apiPost('/api/google/cli/test',{id:c.id},'testing');
    toast(r&&r.ok?`${c.label}: signed in and answering`:`${c.label}: ${(r&&r.detail)||'no answer'}`,r&&r.ok?undefined:7000);
    await drawG(true);delete HPROV_CACHE.models;loadModels()};
   row.querySelector('[data-a=check]').onclick=async()=>{await drawG(true);delete HPROV_CACHE.models;loadModels();toast('checked')};
   host.appendChild(row)})};
 drawG(false);

 // Meta: one key for Muse Wonder and Muse Spark (in Claude Code, Codex and Orbit's own agent), Muse Image and SAM 3.1 as tools,
 // Muse Code as an engine, and open-weight Muse Glimmer on this Mac
 const mc=el(`<div class=memrow style="display:block;margin:6px 0;padding:8px 10px;border:1px solid var(--line);border-radius:9px">
   <b>Meta · Muse</b> <span class=note>— Muse Wonder and Muse Spark in any chat, Muse Image and SAM 3.1 as tools, the Muse Code agent, and open-weight Muse Glimmer on this Mac</span>
   <div id=mcard style="margin-top:4px">checking…</div>
   <div class=note>One key (<code>MODEL_API_KEY</code>) runs all of it: add it in the <b>Meta Model API</b> card below. Muse Image costs about $0.01 an image and SAM 3.1 about $2.50 per 1,000 images.</div></div>`);
 box.appendChild(mc);
 const drawM=async fresh=>{
  let d;try{d=await (await fetch('/api/meta/status'+(fresh?'?fresh=1':''))).json()}catch(e){return}
  const host=mc.querySelector('#mcard');host.innerHTML='';
  const row=(name,status,btns)=>{const r=el(`<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:5px 0">
    <b style="min-width:130px">${esc(name)}</b><span class=note style="flex:1;min-width:180px">${status}</span></div>`);
   (btns||[]).forEach(([t,fn,tip])=>{const b=el('<button class=ghost></button>');b.textContent=t;if(tip)b.title=tip;
    b.onclick=async()=>{b.disabled=true;const was=b.textContent;b.textContent='…';try{await fn()}finally{b.disabled=false;b.textContent=was}};r.appendChild(b)});
   host.appendChild(r)};
  row('API key',d.key_set?'✓ saved — Muse Wonder and Muse Spark are in the model pickers':`needs a key — create one at <a href="${esc(d.keys_url)}" target=_blank rel=noopener>dev.meta.ai</a> (keys start with LLM_)`,
   d.key_set?[['Test the key',async()=>{const r=await apiPost('/api/meta/test',{what:'key'},'testing');
     toast(r&&r.ok?'Meta: key works · '+r.detail:'Meta: '+((r&&r.detail)||'no answer'),r&&r.ok?undefined:7000)}]]:[]);
  const m=d.muse||{};
  row('Muse Code',!m.installed?'not installed — Meta’s coding agent for the terminal':`✓ installed${m.version?' · '+esc(m.version):''} — it is an engine pill in the model popover`,
   [!m.installed?['Install in the terminal',()=>terminalDo(m.install,false),'types the install command; you press Enter']
     :['Sign in in the terminal',()=>terminalDo(m.login,true),'opens muse; /login signs in with your browser'],
    ...(m.installed?[['Test',async()=>{const r=await apiPost('/api/meta/test',{what:'muse'},'testing');
      toast(r&&r.ok?'Muse Code: answering':'Muse Code: '+((r&&r.detail)||'no answer'),r&&r.ok?undefined:7000);await drawM(true);delete HPROV_CACHE.models;loadModels()},'a one-word question']]:[])]);
  const t=d.tools||{};
  row('Muse Image',t.image?'✓ any Claude Code chat can make and edit images (asks as a tool: “make an image of …”)':'needs the key',[]);
  row('SAM 3.1',t.segment?('✓ finds objects in images with boxes'+(t.mask_decoder?' and masks':' — add the mask decoder for masks')):'needs the key',
   t.segment&&!t.mask_decoder?[['Add the mask decoder',async()=>{const r=await apiPost('/api/meta/sam_parser',{},'installing');
     toast(r&&r.ok?'mask decoder installed — restart Orbit to use it':'could not install: '+((r&&r.detail)||''),r&&r.ok?undefined:8000);await drawM(true)},'pip install meta-sam-parser (Meta’s own, Apache-2.0)']]:[]);
  const g=d.glimmer||{},run=(g.serving||[]);
  const cmds=g.commands||{},have=g.installed||{};
  row('Muse Glimmer',run.length?('✓ serving on this Mac: '+run.map(x=>esc(x.label)).join(', ')+' — in the pickers'):
    `open weights (Apache 2.0, 30B, about ${g.size_gb||17} GB at 4-bit). ${esc(g.advice||'')} Not running yet.`,
   run.length?[]:Object.keys(cmds).filter(k=>have[k]).map(k=>['Run with '+(k==='llama.cpp'?'llama.cpp':k==='ollama'?'Ollama':'LM Studio'),()=>terminalDo(cmds[k],false),'types the command (it downloads the model the first time); you press Enter']));
  if(!run.length&&!Object.keys(have).length)host.appendChild(el(`<div class=note style="margin:2px 0 2px 138px">No runtime found. Easiest: install Ollama (<code>brew install ollama</code>), then <code>ollama run muse-glimmer</code>.</div>`));
 };
 drawM(false);
 const hidden=new Set();(h.providers||[]).forEach(p=>p.models.forEach(m=>{if(m.hidden)hidden.add('harness:'+p.id+'/'+m.id)}));
 const saveReg=async patch=>apiPost('/api/harness/save',patch,'saving models');
 (h.providers||[]).forEach(p=>{
  const card=el('<details class=memrow style="display:block;margin:6px 0;padding:8px 10px;border:1px solid var(--line);border-radius:9px"></details>');
  card.open=p.id==='opencode-go'||p.id==='local'||p.id==='claude';
  const nAcc=(p.accounts||[]).filter(a=>a.key_set).length;
  const status=p.auth==='local'?'on this Mac':p.keyless?('on this Mac · server '+(p.server&&p.server.running?'on':'off'))
   :p.auth==='subscription'?(p.ready?'✓ uses your Claude login':p.login==='missing'?'Claude Code not installed':'not signed in — see below')
   :(p.key_set?(nAcc>1?`✓ ${nAcc} accounts`:'✓ key set'):'needs a key');
  card.appendChild(el(`<summary style="cursor:pointer"><b>${esc(p.label)}</b> <span class=note>${status} · ${p.models.length} models${p.auth==='subscription'?' · Claude Code mode only':''}</span></summary>`));
  if(p.docs)card.appendChild(el(`<div class=note style="margin:4px 0">${esc(p.docs)}</div>`));
  if(p.auth==='subscription'){
   // your Claude accounts: the Mac's own login, and any number of others signed in with a token each
   const accs=p.accounts||[];
   const refresh=async()=>{await fetch('/api/harness?fresh=1');delete HPROV_CACHE[p.id];loadModels();renderHarnessModels(box)};
   const ab=el('<div style="margin:6px 0"></div>');
   ab.appendChild(el(`<div class=note>${accs.length>1?'Runs use the main account. When Claude says its limit is reached, the next account takes over'+((h.accounts_policy||{}).switch_back===false?'':' and the main one is used again once its limit has reset')+'. ':''}Accounts share your <code>~/.claude</code>, so skills, plugins, MCP servers and every chat's history stay the same; only the account that is billed changes.</div>`));
   accs.forEach(a=>{
    const ex=a.exhausted;
    const how=a.token_set?'sign-in token saved ✓':(a.id==='main'?(p.login==='yes'?"the Mac's own Claude login ✓":'not signed in'):'needs a token');
    const r=el(`<div style="margin:5px 0;padding:6px 8px;border-radius:8px;${a.home&&accs.length>1?'background:var(--hover,rgba(127,127,127,.08))':''}">
      <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:baseline">
       <b>${esc(a.label)}</b>${a.home&&accs.length>1?'<span class=note style="flex:none;display:inline-block;border:1px solid var(--line);border-radius:9px;padding:0 7px">main</span>':''}
       <span class=note>${how}</span>
       ${ex?`<span style="color:var(--warn);font-size:12px">limit reached — back ${new Date(ex.until*1000).toLocaleString([], {weekday:'short',hour:'numeric',minute:'2-digit'})}</span>`:''}</div>
      <div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin-top:5px">
       <input type=password autocomplete=off spellcheck=false placeholder="${a.token_set?'replace the token':'paste the token from claude setup-token'}" style="flex:1;min-width:200px">
       <button class=ghost data-a=save>save token</button>
       ${a.home?'':'<button class=ghost data-a=home>make main</button>'}
       <button class=ghost data-a=test title="a one-word question to Claude on this account">test</button>
       ${ex?'<button class=ghost data-a=clear>not used up</button>':''}
       <button class=ghost data-a=rename>rename</button>
       ${a.id==='main'?(a.token_set?'<button class=ghost data-a=untoken>remove token</button>':''):'<button class=ghost data-a=remove>remove</button>'}</div></div>`);
    const inp=r.querySelector('input');
    r.querySelectorAll('[data-a]').forEach(b=>b.onclick=async()=>{
     const op=b.dataset.a;
     if(op==='save'){if(!inp.value.trim())return;
      const d=await apiPost('/api/secrets/save',{secrets:{[a.key]:inp.value.trim()}},'saving the token');
      inp.value='';if(d){toast('token saved — press test to check it')}}
     else if(op==='test'){b.textContent='…';b.disabled=true;
      const d=await apiPost('/api/claude/accounts',{op:'test',id:a.id},'testing the account');
      toast(d&&d.ok?`${a.label}: signed in and answering`:`${a.label}: ${(d&&d.detail)||'it did not answer'}`,d&&d.ok?undefined:6000);
      b.textContent='test';b.disabled=false;return}
     else if(op==='untoken'){if(!confirm('Remove the saved sign-in token? Claude Code then uses the Mac\'s own login.'))return;
      await apiPost('/api/secrets/save',{secrets:{[a.key]:''}},'removing the token')}
     else if(op==='rename'){const label=prompt('Name for this account',a.label);if(!label)return;
      await apiPost('/api/claude/accounts',{op:'rename',id:a.id,label},'renaming')}
     else if(op==='remove'){if(!confirm(`Remove ${a.label} and its token from Orbit?`))return;
      await apiPost('/api/claude/accounts',{op:'remove',id:a.id},'removing the account')}
     else await apiPost('/api/claude/accounts',{op,id:a.id},'account');
     refresh()});
    ab.appendChild(r)});
   const add=el(`<div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;margin:4px 0"><button class=ghost style="font-size:11.5px" data-a=add>+ add a Claude account</button>
     <button class=ghost style="font-size:11.5px" data-a=term title="opens Orbit's terminal and runs: claude setup-token">Sign in in the terminal</button>
     <button class=ghost style="font-size:11.5px" data-a=cmd title="copies: claude setup-token">copy the sign-in command</button></div>
     <div class=note>To add one (say a lab or work plan): sign in to that Claude account in your browser (a private window keeps it apart from your own), run <code>claude setup-token</code> in a terminal, approve it in the browser, and paste the token it prints on the new account's row above.</div>`);
   add.querySelector('[data-a=add]').onclick=async()=>{
    const label=prompt('A name for the new account (e.g. "Lab")','');if(!label)return;
    const d=await apiPost('/api/claude/accounts',{op:'add',label},'adding the account');
    if(d&&d.ok){toast('account added — paste its token');refresh()}};
   add.querySelector('[data-a=term]').onclick=()=>terminalDo('claude setup-token',true);
   add.querySelector('[data-a=cmd]').onclick=async()=>{
    try{await navigator.clipboard.writeText('claude setup-token');toast('copied — paste it in a terminal')}catch(e){toast('run: claude setup-token')}};
   ab.appendChild(add);
   card.appendChild(ab)}
  if(p.id==='opencode-go')card.appendChild(el(`<div class=note style="margin:4px 0">An OpenCode Go account has one allowance shared by all its models, in 5-hour, weekly and monthly windows; what is left comes from OpenCode itself and is shown with each account (and in the provider picker). Each model shows roughly what it has cost through Orbit.</div>`));
  if(p.keyless&&p.server){
   // Bionic: its models only answer while its own local server is on
   const sv=el(`<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:6px 0"><span class=note>${
     p.server.running?'Serving on port <b>'+esc(String(p.server.port))+'</b> — Orbit reaches it there.'
      :'Its local server is off. Orbit switches it on when you send a message to one of these models.'}</span>${
     p.server.running?'':'<button class=ghost style="font-size:11.5px">start it now</button>'}</div>`);
   const sb=sv.querySelector('button');
   if(sb)sb.onclick=async()=>{sb.textContent='starting…';sb.disabled=true;
    const d=await apiPost('/api/bionic/start',{},'starting Bionic');
    toast(d&&d.ok?'Bionic is serving':'could not start it'+(d&&d.detail?': '+d.detail:''));
    delete HPROV_CACHE[p.id];loadModels();renderHarnessModels(box)};
   card.appendChild(sv);
   // what it is holding in memory, and a way to have that memory back
   (p.server.loaded||[]).forEach(L=>{
    const gb=L.bytes?(L.bytes/1e9).toFixed(1)+' GB':'';
    const r=el(`<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:2px 0">
      <span class=note>in memory: <b>${esc(L.label||L.model)}</b>${gb?' · '+gb:''}${
        L.context?' · '+(L.context/1000|0)+'k context':''}</span>
      <button class=ghost style="font-size:11.5px">unload${gb?' ('+gb+' back)':''}</button></div>`);
    r.querySelector('button').onclick=async()=>{
     if(!confirm(`Unload ${L.label||L.model} from memory? Bionic will load it again when it is next used — here or in Bionic itself.`))return;
     const d=await apiPost('/api/bionic/unload',{model:L.model},'unloading');
     toast(d&&d.ok?'unloaded':'could not unload it'+(d&&d.detail?': '+d.detail:''));
     delete HPROV_CACHE[p.id];loadModels();renderHarnessModels(box)};
    card.appendChild(r)});
   // models it has but is not holding: put one in memory before you need it
   const cold=(p.models||[]).filter(m=>!(p.server.loaded||[]).some(L=>L.model===m.id));
   if(cold.length){
    const lr=el(`<div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;margin:2px 0">
      <span class=note>not in memory:</span><select style="max-width:260px">${
        cold.map(m=>`<option value="${esc(m.id)}">${esc(m.label||m.id)}</option>`).join('')}</select>
      <button class=ghost style="font-size:11.5px">load it now</button></div>`);
    lr.querySelector('button').onclick=async()=>{
     const b=lr.querySelector('button'), m=lr.querySelector('select').value;
     b.textContent='loading…';b.disabled=true;
     const d=await apiPost('/api/bionic/load',{model:m},'loading the model');
     toast(d&&d.ok?'in memory':'could not load it'+(d&&d.detail?': '+d.detail:''));
     delete HPROV_CACHE[p.id];loadModels();renderHarnessModels(box)};
    card.appendChild(lr)}
   // …and let it go again when nothing has used it for a while
   const idle=(INFO.settings&&INFO.settings.bionic_idle_min);
   const ir=el(`<div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;margin:6px 0">
     <span class=note>let a model go after</span>
     <input type=number min=0 style="width:70px" value="${idle===undefined||idle===null?
       ((INFO.settings&&INFO.settings.idle_min)||20):idle}">
     <span class=note>min in which nothing on this Mac used it — Orbit, Bionic itself or anything else. 0 keeps it loaded.</span></div>`);
   ir.querySelector('input').onchange=async e=>{
    const d=await apiPost('/api/settings',{settings:{bionic_idle_min:Number(e.target.value)||0}},'saving');
    if(d){toast('saved');INFO=await (await fetch('/api/info')).json()}};
   card.appendChild(ir)}
  if(p.auth!=='local'&&p.auth!=='subscription'&&!p.keyless){
   const rf=el(`<div class=note style="margin:2px 0">${p.fetched_at?'model list updated '+new Date(p.fetched_at*1000).toLocaleString():'preset model list'} <button class=ghost style="font-size:11px">refresh model list</button></div>`);
   rf.querySelector('button').onclick=async()=>{rf.querySelector('button').textContent='…';
    const d=await apiPost('/api/harness/refresh',{provider:p.id},'refreshing models');
    const r=d&&d.results&&d.results[p.id];toast(r?`${p.label}: ${r[0]} models${r[1]?' — '+r[1]:''}`:'refresh failed');
    delete HPROV_CACHE[p.id];renderHarnessModels(box)};
   card.appendChild(rf)}
  if(p.auth!=='local'&&p.auth!=='subscription'&&!p.keyless){
   // accounts: several keys for one provider (say two OpenCode Go subscriptions)
   const accs=p.accounts||[];
   const ab=el('<div style="margin:6px 0"></div>');
   if(accs.length>1||accs.some(a=>a.exhausted))ab.appendChild(el(`<div class=note>Accounts are tried in order: the one in use first; one that says its quota is used up is skipped until it resets.</div>`));
   accs.forEach((a,i)=>{
    const ex=a.exhausted,au=a.usage&&a.usage.windows&&a.usage.windows.month;
    const r=el(`<div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin:4px 0;padding:4px 6px;border-radius:7px;${a.active?'background:var(--hover,rgba(127,127,127,.08))':''}">
      <b style="min-width:90px">${esc(a.label)}</b>
      <span class=note>${esc(a.key)}${a.key_set?' ✓':''}${a.active&&a.key_set?' · in use':''}${a.live?' · <b>'+esc(liveLong(a.live))+'</b>':''}${ex?` · <span style="color:var(--warn)">used up until ${new Date(ex.until*1000).toLocaleString()}</span>`:''}${au&&au.spent?` · $${au.spent.toFixed(2)} this month via Orbit`:''}</span>
      <input type=password autocomplete=off spellcheck=false placeholder="${a.key_set?'replace the key':'paste the key'}" style="flex:1;min-width:180px">
      <button class=ghost>save key</button>
      ${a.active?'':'<button class=ghost data-a=use>use this</button>'}
      ${ex?'<button class=ghost data-a=clear>not used up</button>':''}
      <button class=ghost data-a=rename>rename</button>
      ${(accs.length>1||a.key_set)?'<button class=ghost data-a=remove>remove</button>':''}</div>`);
    const inp=r.querySelector('input');
    r.querySelector('button').onclick=async()=>{if(!inp.value.trim())return;
     const d=await apiPost('/api/secrets/save',{secrets:{[a.key]:inp.value.trim()}},'saving the key');
     inp.value='';if(d){toast('key saved');delete HPROV_CACHE[p.id];loadModels();renderHarnessModels(box)}};
    r.querySelectorAll('[data-a]').forEach(b=>b.onclick=async()=>{
     const op=b.dataset.a;
     if(op==='remove'){
      if(!confirm(`Remove ${a.label} (${a.key}) from Orbit?`))return;
      if(accs.length===1){await apiPost('/api/secrets/save',{secrets:{[a.key]:''}},'removing the key')}
      else await apiPost('/api/harness/account',{provider:p.id,op,id:a.id},'removing the account')}
     else if(op==='rename'){const label=prompt('Name for this account',a.label);if(!label)return;
      await apiPost('/api/harness/account',{provider:p.id,op,id:a.id,label},'renaming')}
     else await apiPost('/api/harness/account',{provider:p.id,op:op==='use'?'activate':'clear',id:a.id},'account');
     delete HPROV_CACHE[p.id];loadModels();renderHarnessModels(box)});
    ab.appendChild(r)});
   const add=el(`<div style="display:flex;gap:6px;align-items:center;margin:4px 0"><button class=ghost style="font-size:11.5px">+ add another account</button>
     ${p.keys_url?`<a href="${esc(p.keys_url)}" target=_blank class=note>get a key</a>`:''}</div>`);
   add.querySelector('button').onclick=async()=>{
    const label=prompt('A name for the new account (e.g. "Work")',`Account ${accs.length+1}`);if(label===null)return;
    const d=await apiPost('/api/harness/account',{provider:p.id,op:'add',label},'adding the account');
    if(d){toast('account added — paste its key');renderHarnessModels(box)}};
   ab.appendChild(add);
   card.appendChild(ab);
   if((p.alt_bases||[]).length){
    const br=el(`<div style="margin:4px 0"><span class=note>region </span><select>${[p.base,...p.alt_bases].filter((x,i,a)=>a.indexOf(x)===i)
      .map(b=>`<option>${esc(b)}</option>`).join('')}</select></div>`);
    br.querySelector('select').value=p.base;
    br.querySelector('select').onchange=async e=>{const cur=(await (await fetch('/api/harness')).json());
     await saveReg({providers:{[p.id]:{base:e.target.value}}});toast('region saved')};
    card.appendChild(br)}}
  const list=el('<div style="max-height:260px;overflow:auto"></div>');
  p.models.forEach(m=>{
   const mid='harness:'+p.id+'/'+m.id;
   const r=el(`<div style="display:flex;gap:8px;align-items:center;font-size:12.5px;padding:2px 0">
     <input type=checkbox title="show in the model picker"><span style="flex:1">${esc(m.label)} <span class=note>${esc(m.id)} · ${fmtName[m.format]||m.format} · ${Math.round((m.context||0)/1000)}k${usageShort(m.usage)?' · <b>'+esc(usageShort(m.usage))+'</b>':''}</span></span>
     <button class=ghost style="font-size:11px">test</button></div>`);
   if(m.usage)r.title=usageLong(m.usage)+' — estimated from requests through Orbit; use elsewhere is not counted';
   const cb=r.querySelector('input');cb.checked=!hidden.has(mid);
   cb.onchange=async()=>{cb.checked?hidden.delete(mid):hidden.add(mid);await saveReg({hidden:[...hidden]});loadModels()};
   const tb=r.querySelector('button');
   tb.onclick=async()=>{tb.textContent='…';const d=await apiPost('/api/harness/test',{id:mid},'test');
    tb.textContent='test';if(d)toast(d.ok?`${m.label}: replied in ${d.secs}s — ${String(d.reply).slice(0,40)}`:`${m.label}: ${String(d.error).slice(0,160)}`)};
   list.appendChild(r)});
  card.appendChild(list);box.appendChild(card)});
 // a provider of your own
 const cf=el(`<details style="margin:8px 0"><summary class=note style="cursor:pointer">Add your own provider</summary><div class=grid style="margin-top:6px">
   <label>Name</label><input type=text id=cp_label placeholder="My server">
   <label>Base URL</label><input type=text id=cp_base placeholder="https://example.com/v1 or …/anthropic">
   <label>API</label><select id=cp_fmt><option value=messages>Anthropic Messages (native)</option><option value=chat>OpenAI chat completions (gateway)</option><option value=responses>OpenAI Responses (gateway)</option></select>
   <label>Key name</label><input type=text id=cp_key placeholder="MY_SERVER_KEY (then save the key above)">
   <label>Models</label><input type=text id=cp_models placeholder="model-a, model-b">
   <label>Context</label><input type=number id=cp_ctx value=128000>
   </div><button class=ghost id=cp_add>Add provider</button></details>`);
 box.appendChild(cf);
 cf.querySelector('#cp_add').onclick=async()=>{
  const label=$('#cp_label').value.trim(),base=$('#cp_base').value.trim();
  const models=$('#cp_models').value.split(',').map(x=>x.trim()).filter(Boolean);
  if(!label||!base||!models.length)return toast('name, base URL and at least one model');
  const id=label.toLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/^-|-$/g,'')||'custom';
  const reg=await (await fetch('/api/harness')).json();
  const custom={};(reg.providers||[]).filter(x=>x.custom).forEach(x=>custom[x.id]={label:x.label,base:x.base,key:x.key,auth:x.auth,
    models:x.models.map(m=>({id:m.id,format:m.format,context:m.context}))});
  const fmt=$('#cp_fmt').value,key=($('#cp_key').value.trim()||id.toUpperCase().replace(/-/g,'_')+'_API_KEY').toUpperCase();
  custom[id]={label,base,key,auth:fmt==='messages'?'api_key':'gateway',
   models:models.map(m=>({id:m,format:fmt,context:+$('#cp_ctx').value||128000}))};
  if(await saveReg({custom})){toast('provider added — now save its key');renderHarnessModels(box)}};
 const px=el(`<div style="margin-top:6px"><span class=note>Proxy for model requests </span><input type=text placeholder="http://127.0.0.1:7890 (optional)" style="max-width:260px"> <button class=ghost>save</button></div>`);
 px.querySelector('input').value=h.proxy||'';
 px.querySelector('button').onclick=async()=>{if(await saveReg({proxy:px.querySelector('input').value.trim()}))toast('proxy saved')};
 box.appendChild(px)}
// Where a chat's Claude session works: chosen before its first message, like
// starting claude-qwen in a folder. A chat that has begun stays in its folder.
// the Mac's own folder chooser (it opens on the Mac's screen; typing a path works anywhere)
async function pickFolder(start,prompt){
 toast('choose a folder in the window that opened on the Mac');
 const d=await apiPost('/api/pick_folder',{start:start||'',prompt:prompt||'Choose a folder'},'folder chooser');
 if(!d||d.cancelled){if(d&&d.error)toast('folder chooser: '+d.error);return null}
 return d.path}
// Settings → Claude Code → Remote machines: the hosts in ~/.ssh/config, whether each has
// Claude Code, and the folder new chats there start in.
async function renderRemoteHosts(box){
 REMOTE_HOSTS=null;const hosts=await remoteHosts();
 box.classList.remove('note');box.innerHTML='';
 box.appendChild(el(`<div class=note style="margin-bottom:6px">A chat can run Claude Code on another machine: choose it under “Where” when you pick a chat's folder (the folder chip by the title) or in New chat with…. Claude Code runs there — editing files and running commands on that machine — in its own process group, ended whenever the answer stops or the connection drops, so nothing piles up on a login node. Models come from this Mac through an SSH tunnel to Orbit's gateway (it needs Orbit's token; keys stay here); your Claude login goes over the connection itself. Hosts are those in <code>~/.ssh/config</code>, with key-based login.</div>`));
 const ka=el(`<div style="display:flex;gap:6px;align-items:center;margin:4px 0 8px"><span class=note>Keep Claude Code running between messages for</span><input type=number min=0 max=1440 style="width:70px"><span class=note>minutes idle (0 = start it for every message)</span><button class=ghost>save</button></div>`);
 try{const c=(await (await fetch('/api/claude/info?sid=')).json()).settings||{};ka.querySelector('input').value=c.remote_keep_alive_min??30}catch(e){}
 ka.querySelector('button').onclick=async()=>{if(await apiPost('/api/claude/settings',{settings:{remote_keep_alive_min:+ka.querySelector('input').value||0}},'saving'))toast('saved — the next message on another machine starts in about a second instead of reconnecting')};
 box.appendChild(ka);
 if(!hosts.length){box.appendChild(el('<div class=note>No hosts in ~/.ssh/config yet.</div>'));return}
 hosts.forEach(h=>{
  const r=el(`<div class=memrow style="display:block;padding:6px 8px">
    <div style="display:flex;gap:6px;align-items:center"><b style="min-width:120px"></b><span class=note style="flex:1" data-p>${h.probe?probeLine(h.probe):'not checked yet'}</span><button class=ghost data-a=check>check</button></div>
    <div style="display:flex;gap:6px;align-items:center;margin-top:4px"><span class=note>new chats start in</span><input type=text style="flex:1;max-width:320px" placeholder="~ (home folder)"><button class=ghost data-a=save>save</button></div></div>`);
  r.querySelector('b').textContent=h.host;
  const inp=r.querySelector('input');inp.value=(h.saved||{}).default_dir||'';
  r.querySelector('[data-a=check]').onclick=async()=>{r.querySelector('[data-p]').innerHTML='checking…';
   const pr=await apiPost('/api/remote/probe',{host:h.host,refresh:true},'checking');r.querySelector('[data-p]').innerHTML=probeLine(pr)};
  r.querySelector('[data-a=save]').onclick=async()=>{if(await apiPost('/api/remote/save',{host:h.host,default_dir:inp.value.trim()},'saving'))toast('saved');REMOTE_HOSTS=null};
  box.appendChild(r)})}
// Where a chat's Claude session works: a folder on this Mac, or on another machine over
// SSH (a cluster's login node…) where it edits files and runs commands. Chosen before
// its first message; a chat that has begun stays where it is.
let REMOTE_HOSTS=null;
async function remoteHosts(){
 if(!REMOTE_HOSTS){try{REMOTE_HOSTS=(await (await fetch('/api/remote/hosts')).json()).hosts||[]}catch(e){REMOTE_HOSTS=[]}}
 return REMOTE_HOSTS}
function probeLine(pr){
 if(!pr)return '';
 if(!pr.ok)return `<span style="color:var(--err)">not reachable: ${esc(pr.error||'')}</span>`;
 if(!pr.claude)return `<span style="color:var(--warn)">${esc(pr.hostname||'')}: no Claude Code found — install it there (or open a Claude Code SSH session to it once)</span>`;
 const near=pr.proc_limit&&pr.procs>pr.proc_limit*0.8;
 return `✓ ${esc(pr.hostname||'')} · Claude Code ${esc(pr.claude_version||'')} · ${pr.logged_in?'signed in there':'uses your models from this Mac'} · ${pr.procs}/${pr.proc_limit||'?'} processes${near?' <b style="color:var(--warn)">— near the limit</b>':''} · ${pr.secs}s`}
async function remoteBrowser(hostName,startPath,onPick){
 // a small folder browser on the remote machine
 const box=el(`<div class=rbrowse><div class=note>loading…</div></div>`);
 const load=async path=>{
  box.innerHTML='<div class=note>listing '+esc(path)+' on '+esc(hostName)+'…</div>';
  const d=await apiPost('/api/remote/ls',{host:hostName,path},'listing');
  if(!d||d.error){box.innerHTML=`<div class=note style="color:var(--err)">${esc((d&&d.error)||'could not list it')}</div>`;return}
  box.innerHTML='';
  const head=el(`<div style="display:flex;gap:6px;align-items:center;margin-bottom:4px"><code style="flex:1;overflow:hidden;text-overflow:ellipsis"></code><button class=ghost data-a=up>↑ up</button><button class=primary data-a=use>use this folder</button></div>`);
  head.querySelector('code').textContent=d.path;
  head.querySelector('[data-a=up]').onclick=()=>load(d.path.replace(/\/[^/]+\/?$/,'')||'/');
  head.querySelector('[data-a=use]').onclick=()=>onPick(d.path);
  box.appendChild(head);
  const list=el('<div style="max-height:220px;overflow:auto"></div>');
  d.dirs.filter(x=>!x.startsWith('.')).concat(d.dirs.filter(x=>x.startsWith('.'))).forEach(n=>{
   const r=el('<div class=memrow style="cursor:pointer;padding:3px 8px">📁 <span></span></div>');r.querySelector('span').textContent=n;
   r.onclick=()=>load(d.path.replace(/\/$/,'')+'/'+n);list.appendChild(r)});
  if(!d.dirs.length)list.appendChild(el('<div class=note>no folders here</div>'));
  box.appendChild(list)};
 load(startPath||'~');
 return box}
// bookmarked and recent folders, kept per machine (this Mac, each SSH host)
let FOLDER_MARKS={};
async function folderPlaces(box,where,pick){
 let d;try{d=await (await fetch('/api/claude/folders?host='+encodeURIComponent(where||''))).json()}catch(e){return}
 FOLDER_MARKS[where||'']=d.bookmarks||[];
 box.innerHTML='';
 const tilde=p=>String(p).replace(/^\/Users\/[^/]+/,'~');
 const row=(path,why,marked)=>{
  const r=el(`<div class=memrow style="cursor:pointer;align-items:center"><button class=ghost style="padding:0 6px" title="${marked?'remove bookmark':'bookmark'}">${marked?'★':'☆'}</button><b style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"></b><span></span></div>`);
  r.querySelector('b').textContent=where?path:tilde(path);r.querySelector('b').title=path;r.querySelector('span').textContent=why||'';
  r.onclick=e=>{if(e.target.closest('button'))return;pick(path)};
  r.querySelector('button').onclick=async e=>{e.stopPropagation();
   const x=await apiPost('/api/folders/bookmark',{host:where||'',path,on:!marked},'bookmark');
   if(x){FOLDER_MARKS[where||'']=x.bookmarks;folderPlaces(box,where,pick)}};
  return r};
 const marks=d.bookmarks||[], recent=d.recent||[];
 const others=(d.folders||[]).filter(f=>!marks.includes(f.path)&&!recent.includes(f.path));
 if(marks.length){box.appendChild(el('<div class=sec>Bookmarks</div>'));marks.forEach(p=>box.appendChild(row(p,'',true)))}
 if(recent.length||others.length){box.appendChild(el(`<div class=sec>Recent${where?' on '+esc(where):''}</div>`));
  recent.forEach(p=>box.appendChild(row(p,'you chose it lately',false)));
  others.forEach(f=>box.appendChild(row(f.path,f.why,false)))}
 if(!box.children.length)box.appendChild(el(`<div class=note style="margin-top:8px">No bookmarks${where?' on '+esc(where):''} yet — choose a folder and press ☆ to keep it here.</div>`))}
async function folderDialog(){
 const info=await (await fetch('/api/claude/info?sid='+encodeURIComponent(sid))).json();
 const fl=(await (await fetch('/api/claude/folders')).json()).folders||[];
 const hosts=await remoteHosts();
 const started=!!info.session;
 const host=$('#modalhost');
 const where=info.host||'';
 host.innerHTML=`<div class=modal><div class="sheet cqpanel"><header><b>Where this chat works</b>
   <button class=ghost style="margin-left:auto" id=fdx>close</button></header><div class=body>
   ${started?`<div class=note>This chat's Claude session works in <code>${esc((where?where+':':'')+(info.cwd||''))}</code>. To work somewhere else, start a new chat there.</div>`:
    '<div class=note>Claude Code starts this chat in the folder you choose — on this Mac, or on another machine over SSH (it edits files and runs commands there; your models still come from this Mac).</div>'}
   <div class=grid style="margin-top:8px">
   <label>Where</label><select id=fd_where><option value="">This Mac</option>${hosts.map(h=>`<option value="${esc(h.host)}">${esc(h.host)} (SSH)</option>`).join('')}</select>
   <div class=hint2 id=fd_probe></div>
   <label>Folder</label><div style="display:flex;gap:6px"><input type=text id=fd_cwd spellcheck=false placeholder="type a path, or choose…" style="flex:1"><button class=ghost id=fd_star title="bookmark this folder">☆</button><button class=ghost id=fd_pick title="choose a folder">Choose…</button></div>
   <label>Also allow</label><div><textarea class=ta id=fd_add style="min-height:50px" placeholder="more folders, one per line (--add-dir)"></textarea><button class=ghost id=fd_pickadd style="font-size:11.5px">+ choose a folder…</button></div></div>
   <div id=fd_browse></div>
   <div id=fd_places></div>
   <div style="margin-top:10px"><button class=primary id=fd_ok>${started?'New chat there':'Use this folder'}</button>
   <span class=note id=fd_note></span></div></div></div></div>`;
 $('#fd_where').value=where;
 $('#fd_cwd').value=info.cwd||info.cwd_pref||info.cwd_default||'';$('#fd_add').value=(info.add_dirs||[]).join('\n');
 const places=()=>folderPlaces($('#fd_places'),$('#fd_where').value,p=>{$('#fd_cwd').value=p;starState()});
 const starState=async()=>{const h=$('#fd_where').value,v=$('#fd_cwd').value.trim();
  const marks=(FOLDER_MARKS[h]||[]);$('#fd_star').textContent=marks.includes(v)?'★':'☆';
  $('#fd_star').title=marks.includes(v)?'remove this bookmark':'bookmark this folder'};
 $('#fd_cwd').oninput=starState;
 $('#fd_star').onclick=async()=>{const h=$('#fd_where').value,v=$('#fd_cwd').value.trim();if(!v)return toast('type or choose a folder first');
  const on=!(FOLDER_MARKS[h]||[]).includes(v);
  const d=await apiPost('/api/folders/bookmark',{host:h,path:v,on},'bookmark');
  if(d){FOLDER_MARKS[h]=d.bookmarks;toast(on?'bookmarked':'bookmark removed');places();starState()}};
 places().then(starState);
 const syncWhere=async()=>{
  const h=$('#fd_where').value;
  await places();starState();
  $('#fd_browse').innerHTML='';
  if(!h){$('#fd_probe').innerHTML='';$('#fd_cwd').placeholder='type a path, or choose…';return}
  $('#fd_cwd').placeholder='a folder on '+h+' — e.g. ~/project, or choose…';
  const saved=((hosts.find(x=>x.host===h)||{}).saved)||{};
  const cur=$('#fd_cwd').value.trim();
  if(!cur||cur==='~'||cur.startsWith('/Users/'))$('#fd_cwd').value=saved.default_dir||(FOLDER_MARKS[h]||[])[0]||'~';
  starState();
  $('#fd_probe').innerHTML='checking '+esc(h)+'…';
  const pr=await apiPost('/api/remote/probe',{host:h},'checking the host');
  if($('#fd_where')&&$('#fd_where').value===h)$('#fd_probe').innerHTML=probeLine(pr)};
 $('#fd_where').onchange=syncWhere;if(where)syncWhere();
 $('#fdx').onclick=closeModal;
 $('#fd_pick').onclick=async()=>{
  const h=$('#fd_where').value;
  if(h){const b=await remoteBrowser(h,$('#fd_cwd').value.trim()||'~',p=>{$('#fd_cwd').value=p;$('#fd_browse').innerHTML=''});
   $('#fd_browse').innerHTML='';$('#fd_browse').appendChild(b);return}
  const p=await pickFolder($('#fd_cwd').value.trim(),'Working folder for this chat');if(p)$('#fd_cwd').value=p};
 $('#fd_pickadd').onclick=async()=>{
  const h=$('#fd_where').value;
  const add=p=>{const t=$('#fd_add');t.value=(t.value.trim()?t.value.trim()+'\n':'')+p;$('#fd_browse').innerHTML=''};
  if(h){const b=await remoteBrowser(h,$('#fd_cwd').value.trim()||'~',add);$('#fd_browse').innerHTML='';$('#fd_browse').appendChild(b);return}
  const p=await pickFolder($('#fd_cwd').value.trim(),'Another folder Claude may use');if(p)add(p)};
 $('#fd_ok').onclick=async()=>{
  const h=$('#fd_where').value;
  const cwd=$('#fd_cwd').value.trim(),add=$('#fd_add').value.split('\n').map(x=>x.trim()).filter(Boolean);
  if(started){await newChat();}
  const d=await apiPost('/api/claude/cwd',{sid,cwd,add_dirs:add,host:h},'working folder');
  if(d){closeModal();toast('this chat works in '+(h?h+':':'')+(cwd||'the workspace'));drawClaudeBar();loadSessions()}}}
async function claudePanel(){
 const d=await (await fetch('/api/claude/info?sid='+encodeURIComponent(sid))).json();
 const host=$('#modalhost');
 host.innerHTML=`<div class=modal><div class="sheet cqpanel"><header><b>Claude Code · local Qwen</b>
   <button class=ghost style="margin-left:auto" id=cqx>close</button></header><div class=body>
   <div class=kv><span>Claude session</span><code>${esc(d.session||'starts with the next message')}</code>
   <span>Folder</span><code>${esc(d.cwd||'—')}</code>
   <span>Permission mode</span><span>${esc(CQ_MODES[(d.prefs||{}).permission_mode||(d.settings||{}).permission_mode]||'Ask')}${d.running?' · answering now':''}</span>
   <span>Profile</span><span>${esc((d.settings||{}).profile||'')}</span>
   <span>Skills offered</span><span>${esc((d.skills||[]).join(', ')||'—')}</span>
   <span>Claude Code</span><span>${esc(d.version||(d.installed?'installed':'not installed'))}</span>
   <span>MCP servers</span><span>${esc((d.mcp||[]).map(m=>m.name+' ('+m.status+')').join(', ')||((d.settings||{}).mcp_servers||[]).join(', ')||'none')}</span></div>
   ${d.resume?`<div class=sec>Continue in a terminal</div><pre id=cqres></pre><button class=ghost id=cqcopy>copy command</button>`:''}
   <div class=sec>While it answers</div>
   <button class=ghost id=cqctx ${d.running?'':'disabled'}>context usage</button>
   <button class=ghost id=cqmcp ${d.running?'':'disabled'}>MCP status</button>
   <pre id=cqout style="display:none"></pre></div></div></div>`;
 if(d.resume){$('#cqres').textContent=d.resume;$('#cqcopy').onclick=()=>copy(d.resume)}
 $('#cqx').onclick=closeModal;
 const show=async sub=>{const r=await apiPost('/api/claude/control',{sid,subtype:sub},sub);const o=$('#cqout');
  o.style.display='';o.textContent=JSON.stringify(r,null,1).slice(0,6000)};
 $('#cqctx').onclick=()=>show('get_context_usage');$('#cqmcp').onclick=()=>show('mcp_status');
 host.querySelector('.modal').onclick=e=>{if(e.target.classList.contains('modal'))closeModal()}}
// Plan mode: it may read and think but change nothing, until switched off.
let PLAN_MODE=false;
function drawPlanMode(){let b=$('#planmode');
 if(!b){b=el('<span id=planmode title="plan mode: it may read and think but change nothing — /build to leave" style="margin-left:8px;font-size:11px;padding:1px 7px;border-radius:9px;background:var(--acc);color:#fff;cursor:pointer">plan mode</span>');
  b.onclick=()=>setPlanMode(false);$('#title').after(b)}
 b.style.display=PLAN_MODE?'':'none'}
async function setPlanMode(on){
 const d=await apiPost('/api/plan_mode',{sid,on},'plan mode');if(!d)return;
 PLAN_MODE=!!d.plan_mode;drawPlanMode();drawModeHint();
 toast(PLAN_MODE?'plan mode: it will read and propose, and change nothing':'plan mode off: it may make changes')}
// Undo the files one answer changed (each restore is itself checkpointed).
function undoButton(a,t,n){
 const acts=a.m.querySelector('.acts');if(!acts||acts.querySelector('.undo'))return;
 const b=el(`<button class="undo undobtn">undo ${n} file change${n>1?'s':''}</button>`);
 b.onclick=async()=>{if(!confirm('Put back the files this answer changed? (Files it created go to the bin.)'))return;
  const d=await apiPost('/api/undo_changes',{sid,t},'undo');if(!d)return;
  // a refusal is not a success: the button stays, and you are offered the way past it
  if(!d.undone){
   sysline((d.done||[]).join('; '));
   if((d.refused||[]).length&&confirm('Nothing was put back — '+d.refused.length+
     ' file(s) changed since this answer wrote them.\n\nPut them back anyway, '+
     'overwriting what you did to them since?')){
    const f=await apiPost('/api/undo_changes',{sid,t,force:true},'undo');
    if(f&&f.undone){b.remove();sysline('undone: '+(f.done||[]).join('; '));if(f.can_redo)redoButton(a,t,n)}
    else if(f)sysline((f.done||[]).join('; '))}
   return}
  b.remove();sysline('undone: '+(d.done||[]).join('; '));if(d.can_redo)redoButton(a,t,n)};
 acts.appendChild(b)}
// After an undo: put the answer's files back as it left them, in one click
function redoButton(a,t,n){
 const acts=a.m.querySelector('.acts');if(!acts||acts.querySelector('.redo'))return;
 const b=el(`<button class="redo undobtn">redo ${n} file change${n>1?'s':''}</button>`);
 b.onclick=async()=>{
  let d=await apiPost('/api/redo_changes',{sid,t},'redo');if(!d)return;
  if(!d.redone&&(d.refused||[]).length&&confirm('Nothing was redone — '+d.refused.length+
    ' file(s) changed since the undo.\n\nRedo anyway, overwriting those changes?'))
   d=await apiPost('/api/redo_changes',{sid,t,force:true},'redo');
  if(!d)return;
  sysline((d.redone?'redone: ':'')+(d.lines||[]).join('; '));
  if(d.redone){b.remove();undoButton(a,t,n)}};
 acts.appendChild(b)}
// Notes sent while an answer is running. The server hands each one to the
// model at its next step, and says when in the stream ('interjection').
let PENDING_NOTES=[];
function noteBubble(text,label){
 const u=addUser(text);u.classList.add('note');
 const tag=el('<div class=notetag></div>');tag.textContent=label;u.appendChild(tag);
 return {node:u,tag}}
function userNode(m){
 if(m.bang)return bangNode(m.bang,m.t??null);
 const u=addUser(m.text,m.images,m.t??null);
 if(m.from_chat){u.classList.add('fromchat');
  const who=u.querySelector('.who');
  if(who){who.childNodes[0].textContent='from ';
   const a=el('<a class=chatlink href="#"></a>');a.dataset.chat=m.from_chat.sid||'';
   a.textContent=m.from_chat.title||'another chat';who.insertBefore(a,who.childNodes[1]||null)}}
 if(m.note){u.classList.add('note');u.appendChild(el('<div class=notetag>sent while it was working</div>'))}
 return u}
async function steer(t){
 if(!t){toast('attachments go with a new message — stop it, or wait for it to finish');return}
 if(atts.length)toast('the note goes without the attachments — send those after');
 q.value='';q.style.height='auto';closeMenu();closeAt();clearDraft(sid);
 document.querySelectorAll('#chips [data-paste]').forEach(x=>x.remove());PASTES={};
 const n=noteBubble(t,'queued — it reads this at its next step');n.node.classList.add('pending');
 const rec={text:t,sid,...n,done:false};PENDING_NOTES.push(rec);
 try{
  const r=await (await fetch('/api/interject',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({sid,message:t})})).json();
  if(r.ok)return;
  // it finished between your keystroke and the note arriving: send it as an
  // ordinary message rather than dropping it
  PENDING_NOTES=PENDING_NOTES.filter(x=>x!==rec);n.node.remove();
  for(let i=0;i<40&&RUNNING.has(sid);i++)await new Promise(res=>setTimeout(res,150));
  RUNNING.delete(sid);syncBusy();q.value=t;go()
 }catch(e){n.tag.textContent='not sent: '+e}}

/* ---------------- message queue ----------------
   Messages sent while a chat is answering wait their turn on the server, in order:
   when an answer ends the next one starts, in this window or not. Drag to reorder,
   click to edit, "now" to put one into the running answer straight away. */
let QUEUE={items:[],paused:false,running:false}, QUEUE_SID=null;
function queuedHere(){return QUEUE_SID===sid&&(QUEUE.items||[]).some(it=>!it.at)}
// Is this chat really answering, or really holding messages? Asked before a message is
// queued rather than sent, and it corrects what this window believes either way.
async function stillBusy(){
 const s_=sid;
 let lv;
 try{lv=await (await fetch('/api/live/'+encodeURIComponent(s_))).json()}
 catch(e){return true}                       // the Mac is unreachable: keep it safe, queue it
 if(s_!==sid)return true;                    // you moved to another chat while it asked
 if(lv.running)RUNNING.add(s_);else RUNNING.delete(s_);
 syncBusy();
 if(!(lv.queue_n>0)&&QUEUE_SID===s_&&(QUEUE.items||[]).length){
  QUEUE={items:[],paused:false,running:false};drawQueue()}
 else if(lv.queue_n>0)await loadQueue(s_);
 return !!lv.running||queuedHere()}
async function queueOp(op,extra,forSid){
 const s_=forSid||sid;
 const d=await apiPost('/api/queue',{sid:s_,op,...(extra||{})},'queue');
 if(d&&d.queue&&s_===sid){QUEUE=d.queue;QUEUE_SID=s_;drawQueue()}
 return d}
async function loadQueue(forSid){
 const s_=forSid||sid;if(!s_)return;
 try{const d=await (await fetch('/api/queue',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({sid:s_,op:'get'})})).json();
  if(d&&d.queue&&s_===sid){QUEUE=d.queue;QUEUE_SID=s_;drawQueue()}return d&&d.queue}catch(e){}}
async function enqueue(t,raw){
 const sending=atts,pastes=PASTES,forSid=sid;atts=[];$('#chips').innerHTML='';
 q.value='';q.style.height='auto';closeMenu();closeAt();clearDraft(sid);PASTES={};
 const d=await queueOp('add',{text:t,attachments:sending});
 if(d&&d.ok)toast(busy?'queued — it starts when this answer is done (⌘Enter sends it in now)':'queued');
 else restoreComposer(forSid,raw||t,sending,pastes)}
// A send or a queue-add that did not get through: the text, its pasted blocks and its
// attachments go back where they were. The text used to come back with its [Pasted #n]
// tokens dead and the attachments invisible -- but still sent with the next message.
function restoreComposer(forSid,raw,sending,pastes){
 if(forSid!==sid){                       // you have moved on: it waits in its own chat
  (ATTS_BY_SID[forSid]=ATTS_BY_SID[forSid]||[]).push(...sending);
  try{const k='orbit_draft_'+forSid;if(!localStorage.getItem(k))localStorage.setItem(k,JSON.stringify({t:raw,p:pastes||{}}))}catch(e){}
  return}
 if(!q.value.trim())q.value=raw;
 Object.entries(pastes||{}).forEach(([n,body])=>{if(PASTES[n]==null){PASTES[n]=body;pasteChip(n,body)}});
 atts=sending.concat(atts);drawChips();fitQ();saveDraft(sid)}
// after an answer ends: the server may already have started the next queued message
async function afterTurn(forSid){
 if(GOALS[forSid]&&GOALS[forSid].status==='active')await new Promise(r=>setTimeout(r,1500)); // its check runs first
 const qd=await loadQueue(forSid);
 if(qd&&qd.running&&forSid===sid&&!SENDING.has(forSid)){
  RUNNING.add(forSid);syncBusy();renderSessions();
  const lv=await (await fetch('/api/live/'+forSid)).json();
  if(lv.running&&!livePoll&&sid===forSid){
   // draw the message it has just taken from the queue, then follow its answer
   if(lv.user)userNode({text:lv.user,t:Date.now()/1000});
   attachLive(forSid,lv)}}}
function whenLabel(ts,repeat){
 const d=new Date(ts*1000),now=new Date();
 const hm=d.toLocaleTimeString([],{hour:'numeric',minute:'2-digit'});
 const day=(x,y)=>x.toDateString()===y.toDateString();
 const tm=new Date(now);tm.setDate(tm.getDate()+1);
 let when=day(d,now)?'today '+hm:day(d,tm)?'tomorrow '+hm:
  ((d-now)/864e5<6&&d>now?d.toLocaleDateString([],{weekday:'short'})+' '+hm:d.toLocaleDateString([],{month:'short',day:'numeric'})+' '+hm);
 if(repeat==='daily')when='daily '+hm+' · next '+when.replace(' '+hm,'');
 if(repeat==='weekdays')when='weekdays '+hm+' · next '+when.replace(' '+hm,'');
 if(repeat==='weekly')when='weekly '+d.toLocaleDateString([],{weekday:'short'})+' '+hm;
 return when}
function drawQueue(){
 const box=$('#queuebox');if(!box)return;
 const all=QUEUE_SID===sid?(QUEUE.items||[]):[];
 const items=all.filter(it=>!it.at),sched=all.filter(it=>it.at).sort((a,b)=>a.at-b.at);
 if(!all.length){box.style.display='none';box.innerHTML='';return}
 box.style.display='';box.innerHTML='';
 let dragId=null;
 if(items.length){
 const head=el(`<div class=qhead><b>Queued · ${items.length}</b><span class=note>${QUEUE.paused?'paused after Stop':
   (QUEUE.running?'each starts when the one before it is answered':'starting…')}</span>
   <span style="margin-left:auto;display:flex;gap:4px">${QUEUE.paused?'<button class=ghost data-q=resume>resume</button>':''}<button class=ghost data-q=clear title="remove every queued message">clear</button></span></div>`);
 head.querySelectorAll('[data-q]').forEach(b=>b.onclick=async()=>{
  if(b.dataset.q==='clear'&&!confirm('Remove all queued messages? (Scheduled ones stay.)'))return;
  if(b.dataset.q==='clear'){for(const it of items)await queueOp('remove',{id:it.id});return}
  await queueOp(b.dataset.q);if(b.dataset.q==='resume')setTimeout(()=>afterTurn(sid),600)});
 box.appendChild(head)}
 const row=(it,i,isSched)=>{
  const r=el(`<div class="qitem${isSched?' sched':''}" ${isSched?'':'draggable=true'} data-id="${esc(it.id)}">${isSched?'':'<span class=grip title="drag to reorder">⋮⋮</span>'}
    <span class="qn ${isSched?'sch':(i===0?'next':'wait')}" title="${isSched?'scheduled':(i===0?'next to send':'waiting its turn')}">${isSched?'⏱':(i===0?'▸':'○')}</span>${isSched?`<span class="qwhen${it.missed?' missed':''}" title="change when it goes out">${it.missed?'missed · was '+esc(whenLabel(it.at)):esc(whenLabel(it.at,it.repeat))}</span>`:''}${it.model?`<span class=qa title="sends on this model">${esc(modelName(it.model))}</span>`:''}<span class=qt></span>${(it.attachments||[]).length?`<span class=qa title="${esc((it.attachments||[]).map(a=>a.name).join(', '))}">+${it.attachments.length}</span>`:''}
    <button class=ghost data-a=now title="${busy?'put it into the running answer now — it reads it at its next step':'send it now'}">now</button>
    ${isSched?'':'<button class=ghost data-a=when title="send it at a time you choose">⏱</button>'}
    <button class=ghost data-a=edit title="edit">✎</button><button class=ghost data-a=remove title="remove">×</button></div>`);
  r.querySelector('.qt').textContent=it.text;
  r.querySelector('.qt').onclick=()=>r.querySelector('[data-a=edit]').click();
  r.querySelector('[data-a=now]').onclick=async()=>{
   const d=await queueOp('now',{id:it.id});
   if(d&&d.interjected){noteBubble(it.text,'sent in — it reads this at its next step');bottom()}
   else if(d&&d.ok&&!busy)setTimeout(()=>afterTurn(sid),500)};
  r.querySelector('[data-a=remove]').onclick=()=>{if(isSched&&it.repeat&&!confirm('Stop this repeating message?'))return;queueOp('remove',{id:it.id})};
  const whenBtn=r.querySelector('.qwhen')||r.querySelector('[data-a=when]');
  whenBtn.onclick=ev=>{ev.stopPropagation();schedPopover(whenBtn,{at:it.at,repeat:it.repeat,clear:isSched,
   onPick:(at,repeat)=>queueOp('schedule',{id:it.id,at,repeat})})};
  r.querySelector('[data-a=edit]').onclick=()=>{
   const ta=el('<textarea class=qedit></textarea>');ta.value=it.text;
   const qt=r.querySelector('.qt');qt.replaceWith(ta);ta.focus();ta.style.height=Math.min(160,ta.scrollHeight+4)+'px';
   r.draggable=false;
   const save=async()=>{const v=ta.value.trim();if(v&&v!==it.text)await queueOp('edit',{id:it.id,text:v});else drawQueue()};
   ta.onkeydown=e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();ta.onblur=null;save()}
    if(e.key==='Escape'){ta.onblur=null;drawQueue()}};
   ta.onblur=save};
  if(!isSched){
  r.ondragstart=e=>{dragId=it.id;r.classList.add('dragging');e.dataTransfer.effectAllowed='move'};
  r.ondragend=()=>{r.classList.remove('dragging');dropLineOff()};
  r.ondragover=e=>{e.preventDefault();dropLine(r,aboveHalf(r,e.clientY))};
  r.ondrop=async e=>{e.preventDefault();dropLineOff();if(!dragId||dragId===it.id)return;
   const after=!aboveHalf(r,e.clientY);
   const ids=items.map(x=>x.id).filter(x=>x!==dragId);
   ids.splice(ids.indexOf(it.id)+(after?1:0),0,dragId);
   await queueOp('order',{ids:ids.concat(sched.map(x=>x.id))})}}
  box.appendChild(r)};
 items.forEach((it,i)=>row(it,i,false));
 if(items.length){
 // dropping below the last one puts it at the end
 const tail=el('<div class=qtail></div>');
 tail.ondragover=e=>e.preventDefault();
 tail.ondrop=async e=>{e.preventDefault();if(!dragId)return;
  const ids=items.map(x=>x.id).filter(x=>x!==dragId);ids.push(dragId);await queueOp('order',{ids:ids.concat(sched.map(x=>x.id))})};
 box.appendChild(tail)}
 if(sched.length){box.appendChild(el(`<div class=qsec>Scheduled · ${sched.length}</div>`));sched.forEach((it,i)=>row(it,i,true))}}
// "21:30", "9pm", "tomorrow 9am", "in 2h", "in 45m", "mon 8:00", "daily 8:00", "weekdays 9am"
function parseLater(s){
 s=String(s||'').trim();let m,repeat=null,at=null;
 const now=new Date();
 if((m=s.match(/^(daily|every\s*day|weekdays|weekly)\s+/i))){repeat=/week(ly)$/i.test(m[1])?'weekly':/weekdays/i.test(m[1])?'weekdays':'daily';s=s.slice(m[0].length)}
 if((m=s.match(/^in\s+(\d+(?:\.\d+)?)\s*(m|min|mins|minutes?|h|hr|hrs|hours?|d|days?)\b\s*/i))){
  const n=parseFloat(m[1]),u=m[2][0].toLowerCase();at=new Date(now.getTime()+n*(u==='m'?6e4:u==='h'?36e5:864e5));s=s.slice(m[0].length)}
 else{
  let day=null;
  if((m=s.match(/^(today|tonight|tomorrow|tmr|mon|tue|wed|thu|fri|sat|sun)[a-z]*\s+/i))){day=m[1].toLowerCase();s=s.slice(m[0].length)}
  if(!(m=s.match(/^(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b\s*/i)))return null;
  if(!m[2]&&!m[3])return null;
  let h=+m[1],mi=+(m[2]||0);const ap=(m[3]||'').toLowerCase();
  if(ap==='pm'&&h<12)h+=12;if(ap==='am'&&h===12)h=0;if(h>23||mi>59)return null;
  s=s.slice(m[0].length);
  at=new Date(now);at.setHours(h,mi,0,0);
  const wd=['sun','mon','tue','wed','thu','fri','sat'];
  if(day==='tomorrow'||day==='tmr')at.setDate(at.getDate()+1);
  else if(day&&wd.includes(day.slice(0,3))){const want=wd.indexOf(day.slice(0,3));let add=(want-at.getDay()+7)%7;if(add===0&&at<=now)add=7;at.setDate(at.getDate()+add)}
  else if(at<=now)at.setDate(at.getDate()+1)}
 return {at:at.getTime()/1000,repeat,text:s.trim()}}
function schedPopover(anchor,o){
 o=o||{};document.querySelectorAll('.schedpop').forEach(x=>x.remove());
 const now=new Date();
 const at=(d,h,mi)=>{const x=new Date(now);x.setDate(x.getDate()+d);x.setHours(h,mi||0,0,0);return x};
 const opts=[];
 opts.push(['In 30 minutes',new Date(now.getTime()+18e5)]);
 opts.push(['In 1 hour',new Date(now.getTime()+36e5)]);
 if(now.getHours()<21)opts.push(['This evening',at(0,21)]);
 opts.push(['Tomorrow morning',at(1,9)]);
 if(now.getDay()>=1&&now.getDay()<=5)opts.push(['Monday morning',(()=>{const x=at(0,9);x.setDate(x.getDate()+((8-x.getDay())%7||7));return x})()]);
 const pad=n=>String(n).padStart(2,'0');
 const local=d=>`${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
 const cur=o.at?new Date(o.at*1000):at(1,9);
 const pop=el(`<div class=schedpop><div style="font-weight:600;margin:0 0 6px 4px">${o.title||'Send later'}</div>
  ${opts.map((x,i)=>`<div class=opt data-i=${i}>${x[0]}<span>${esc(whenLabel(x[1].getTime()/1000))}</span></div>`).join('')}
  <div class=row2><input type=datetime-local value="${local(cur)}" style="flex:1"></div>
  <div class=row2><select><option value="">once</option><option value=daily>every day</option><option value=weekdays>every weekday</option><option value=weekly>every week</option></select>
   <button class="sendbtn" style="height:30px;padding:0 12px;margin-left:auto">Schedule</button></div>
  ${o.clear?'<div class=opt data-a=clear style="margin-top:6px;color:var(--mut)">Don’t schedule — just queue it</div>':''}
  <div class=note style="font-size:11px;margin:6px 4px 0">It goes out at that time even while Orbit is in the background. If the Mac was asleep, it goes when Orbit is back (up to ${6} h late; a repeating one then waits for its next time).</div></div>`);
 const sel=pop.querySelector('select');if(o.repeat)sel.value=o.repeat;
 const pick=async d=>{const t=d.getTime()/1000;
  if(t<Date.now()/1000+5&&!sel.value){toast('that time has passed');return}
  pop.remove();await o.onPick(t,sel.value||null)};
 pop.querySelectorAll('.opt[data-i]').forEach(x=>x.onclick=()=>pick(opts[+x.dataset.i][1]));
 pop.querySelector('.sendbtn').onclick=()=>{const v=pop.querySelector('input').value;if(!v)return;pick(new Date(v))};
 const cl=pop.querySelector('[data-a=clear]');if(cl)cl.onclick=async()=>{pop.remove();await o.onPick(null,null)};
 document.body.appendChild(pop);
 const r=anchor.getBoundingClientRect();
 pop.style.left=Math.max(8,Math.min(r.right-pop.offsetWidth,innerWidth-pop.offsetWidth-8))+'px';
 pop.style.top=Math.max(8,r.top-pop.offsetHeight-8)+'px';
 setTimeout(()=>{const off=e=>{if(!pop.contains(e.target)){pop.remove();removeEventListener('mousedown',off,true)}};addEventListener('mousedown',off,true)},0)}
async function scheduleSend(at,repeat){
 const raw=q.value.trim(),t=expandPastes(raw);
 if(!t&&!atts.length){toast('write the message first, then choose when it goes out');q.focus();return}
 if(tempMode){toast('a temporary chat cannot schedule messages');return}
 const sending=atts;
 const d=await apiPost('/api/queue',{sid,op:'add',text:t,attachments:sending,at,repeat},'schedule');
 if(!d)return;
 atts=[];$('#chips').innerHTML='';q.value='';q.style.height='auto';closeMenu();clearDraft(sid);PASTES={};
 QUEUE=d.queue;QUEUE_SID=sid;drawQueue();
 toast('scheduled — '+whenLabel(at,repeat));loadSessions()}
// a file card dropped on the message box is attached
q.addEventListener('drop',e=>{const d=e.dataTransfer&&e.dataTransfer.getData('text/orbit-file');
 if(!d)return;e.preventDefault();e.stopPropagation();try{attachExisting(JSON.parse(d))}catch(err){}});
$('#opbadge').onclick=()=>showOffpeak();
$('#later').onclick=e=>{e.stopPropagation();schedPopover($('#later'),{onPick:(at,repeat)=>scheduleSend(at,repeat)})};
// right-click (or long-press) Send: send later
$('#send').addEventListener('contextmenu',e=>{e.preventDefault();schedPopover($('#send'),{onPick:(at,repeat)=>scheduleSend(at,repeat)})});
async function showChatFiles(){
 const names=new Set();
 wrap.querySelectorAll('.pathlink[data-path],.afile[data-path]').forEach(x=>names.add(x.dataset.path));
 if(!names.size){toast('this chat names no files yet');return}
 const res=await resolveNames([...names]);
 const files=[],seen=new Set();Object.values(res).forEach(f=>{if(f&&f.exists&&!seen.has(f.path)){seen.add(f.path);files.push(f)}});
 files.sort((a,b)=>(b.mtime||0)-(a.mtime||0));
 openSheet('Files in this chat',body=>{
  body.innerHTML=`<div class=note style="margin-bottom:8px">${files.length} files and folders, newest first${FILE_CTX.cwd?' · this chat works in '+esc(FILE_CTX.cwd):''}</div>`;
  const grid=el('<div class=fscards></div>');files.forEach(f=>grid.appendChild(fileCard(f)));body.appendChild(grid)},{sub:$('#title').textContent})}
async function showScheduled(){
 const d=await (await fetch('/api/scheduled_sends',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'})).json();
 openSheet('Scheduled messages',(body)=>{
  const items=d.items||[];
  if(!items.length){body.innerHTML='<div class=note>Nothing scheduled. Write a message and press ⏱ beside Send, or type /later 9am …</div>';return}
  items.forEach(it=>{const r=el(`<div class=memrow style="align-items:center;gap:10px;cursor:pointer"><span class="qwhen${it.missed?' missed':''}" style="font-size:12px;color:var(--acc);white-space:nowrap"></span><b style="flex:0 0 auto;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"></b><span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--mut)"></span><button class=ghost data-a=now>send now</button><button class=ghost data-a=rm>remove</button></div>`);
   r.querySelector('.qwhen').textContent=it.missed?'missed · '+whenLabel(it.at):whenLabel(it.at,it.repeat);
   r.querySelector('b').textContent=it.title||'(untitled)';r.querySelector('span:nth-of-type(2)').textContent=it.text;
   r.onclick=async ev=>{const a=ev.target.dataset.a;ev.stopPropagation();
    if(a==='now'){await queueOp('now',{id:it.id},it.sid);toast('sending');r.remove();return}
    if(a==='rm'){await queueOp('remove',{id:it.id},it.sid);r.remove();return}
    closeSheet();showPane('log');openSession(it.sid)};
   body.appendChild(r)})})}
async function go(opts){
 opts=opts||{};
 primeAlerts();                            // before any await: needs the keypress/click
 if(switching)await switching;             // never send into the chat you just left
 const raw=q.value.trim(), t=expandPastes(raw);if(!t&&!atts.length)return;
 if(uploadingHere()){toast('still attaching — it can go once the upload is done');return}
 if(t)histPush(t);
 // while it answers (or has messages waiting), a new message joins the queue and
 // starts when the ones before it are answered; ⌘/Ctrl+Enter puts it in right away,
 // as a note the running answer reads at its next step
 let toQueue=(busy||queuedHere())&&!t.startsWith('/');
 if(toQueue){
  if(opts.now&&busy)return steer(t);
  // ask the Mac first: a "busy" or a queue left over from an answer that has since
  // finished (one another window or the phone ran) used to swallow the message quietly
  toQueue=await stillBusy()}
 if(toQueue)return enqueue(t,raw);
 if(t==='/'){showMenu();return}
 // "! command" runs it yourself; "# note" saves a memory -- Claude Code's two shortcuts
 if(/^!\s*\S/.test(t)&&!atts.length){q.value='';q.style.height='auto';closeMenu();clearDraft(sid);
  syncComposerMode();return runBang(t.replace(/^!\s*/,''))}
 if(/^#\s+\S/.test(t)&&!t.includes('\n')&&t.length<300&&!atts.length){
  q.value='';q.style.height='auto';clearDraft(sid);syncComposerMode();return rememberNote(t.replace(/^#\s+/,''))}
 // A Claude Code chat hands commands Orbit doesn't have (its skills, its own commands) to
 // Claude. /compact and /context are in both lists and belong to Claude there: its session
 // is the one holding the conversation, and compacting Orbit's copy of the transcript would
 // change nothing about what gets sent — while saying it had.
 const CLAUDE_OWN=['/compact','/context'];
 const orbitCmd=c0=>(CMDS.some(x=>x.c===c0)||!!PROMPTS[c0.slice(1)])
   && !(isClaudeChat()&&CLAUDE_OWN.includes(c0));
 if(t.startsWith('/')&&!(isClaudeChat()&&!orbitCmd(t.split(' ')[0]))){const c=t.split(' ')[0],rest=t.slice(c.length).trim();
  if(PROMPTS[c.slice(1)]){q.value=expandPrompt(PROMPTS[c.slice(1)].text,rest);return}
  if(await runCmd(c,rest))return;
  // unknown command — don't send it as a message
  const near=allCmds().filter(x=>x.c.startsWith(c)).slice(0,4).map(x=>x.c);
  toast(near.length?`unknown command — did you mean ${near.join(', ')}?`
                   :`unknown command ${c} — type / to see the list`);
  q.value=t;showMenu();return}
 q.value='';q.style.height='auto';closeMenu();clearDraft(sid);
 const ubub=addUser(t,atts.filter(a=>a.kind==='image').map(a=>a.data_url),undefined,raw);
 const sentPastes=PASTES;PASTES={};
 const sending=atts;atts=[];$('#chips').innerHTML='';drawDiffNotes();
 if(opts.effort)sysline('retrying with '+opts.effort+' reasoning effort');
 const sendSid=sid;                       // this answer belongs to THIS chat
 if(GOAL_OFFERS[sendSid]){delete GOAL_OFFERS[sendSid];drawGoal()}   // you moved on: the Mac withdraws it too
 if(stoppedSid===sendSid)stoppedSid=null;  // a Stop applies to the answer it stopped, not the next
 if(!/^continue\b/i.test(t)&&PLANS[sendSid]){delete PLANS[sendSid];drawPlanDock()}  // the server starts a new plan too
 // the chat moves to the top now (it is the one you used last), and a new chat has a
 // row at once, before the server has saved it
 {const row=SESSIONS.find(s=>s.id===sendSid);const now=Date.now()/1000;
  if(row){row.mtime=now;row.n=(row.n||0)+1;SESSIONS.sort((a,b)=>(!!b.pinned-!!a.pinned)||(b.mtime-a.mtime))}
  else PENDING_ROWS[sendSid]={id:sendSid,title:($('#title').textContent&&$('#title').textContent!=='New chat')?$('#title').textContent:t.replace(/\s+/g,' ').slice(0,60),mtime:now,n:1}}
 RUNNING.add(sendSid); SENDING.add(sendSid); renderSessions(); syncBusy();
 startStatus();
 let a=addAssistant(modelLabel());       // replaced at each new step, and when it reads a note
 // Each model step gets its own block -- its thinking, what it said, then the
 // tools it called -- so you can see which text went with which tools. They
 // all used to pile into one block, tools on top and every step's text below.
 const nextStep=()=>{
  if(!a.tools.querySelector('details.tool,div.tool,.autoappr,.blocked,.approve'))return false;
  if(pendingRender){clearTimeout(pendingRender);pendingRender=null}
  if(thinkPending){clearTimeout(thinkPending);thinkPending=null;renderThink(a.think.querySelector('.body'),thinking,tmarks)}
  if(answer){a.bub.innerHTML=md(answer);decorate(a.bub)}else a.bub.remove();
  a.think.classList.remove('live');if(thinking)thinkLabel(a,thoughtFor());
  a=addAssistant(modelLabel());thinking='';answer='';tmarks=[];return true};
 a.bub.innerHTML='<span class=working>working<span class=dots></span></span>';
 let thinking='',answer='',lastRender=0,pendingRender=null,thinkPending=null,tmarks=[];
 const t0=performance.now(), trows={}, autoTags=[];      // trows: live tool rows by call id
 let tThink=0, endP=null, errored=false, queuedBy=null, lost=false, dog=null, reached=false;
 const thoughtFor=()=>'thought for '+fmtSecs((performance.now()-tThink)/1000);
 try{
  const r=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({message:t,attachments:sending,effort:opts.effort,sid:sendSid,goal:!!opts.goal})});
  // a refusal or a crash on the Mac comes back as JSON, not a stream: reading it as one
  // found no events, showed "(no answer)" and announced "Answer ready"
  if(!r.ok||!r.body){let d={};try{d=await r.json()}catch(_){}
   throw new Error(d.error||('the Mac answered '+r.status))}
  reached=true;
  const mine=()=>sid===sendSid;   // user may have switched away
  // Once you open another chat this answer is off screen for good: every
  // drawing call below appends to the page's one message list, so its steps
  // used to land in whichever chat you were reading. It keeps running on the
  // server; opening its chat again rejoins it from the live buffer instead.
  let away=false;
  const rd=r.body.getReader(),dec=new TextDecoder();let buf='';
  // the Mac writes at least every 15 s; a minute of nothing is a connection that died
  // (a laptop that slept, a phone that left the network) and would say "working" for ever
  let lastByte=Date.now();
  dog=setInterval(()=>{if(Date.now()-lastByte>60000){clearInterval(dog);try{rd.cancel()}catch(_){}}},5000);
  while(true){const {value,done}=await rd.read();if(done)break;
   lastByte=Date.now();
   buf+=dec.decode(value,{stream:true});
   const parts=buf.split('\n\n');buf=parts.pop();
   for(const ln of parts){ if(!ln.startsWith('data: '))continue;
    let m;try{m=JSON.parse(ln.slice(6))}catch(_){continue}
    if(m.k==='queued_message'){
     // the server had it wait instead: this chat (or every slot) was busy
     queuedBy=m.p;if(ubub&&ubub.remove)ubub.remove();a.m.remove();
     if(m.p.queue){QUEUE=m.p.queue;QUEUE_SID=sendSid;if(sid===sendSid)drawQueue()}
     toast('queued — '+(m.p.why||'it starts when there is room'));continue}
    if(!away&&(!mine()||!a.m.isConnected))away=true;
    if(away){
     if(m.k==='end')endP=m.p||{};
     else if(m.k==='error')errored=true;
     else if(m.k==='tool')answer='';                 // the answer is the text after the last tools
     else if(m.k==='content_delta')answer+=m.p;
     else if(m.k==='approval_request')notify(sendSid,'Needs your approval',m.p.name||'');
     else if(m.k==='question')notify(sendSid,'Orbit has a question',m.p.question||'');
     else if(m.k==='goal_offer'){setGoalOffer(sendSid,m.p)}
     continue}
    // a finished call closes its row; the plan/diff/images branches below still run
    if(m.k==='tool_result'&&m.p&&m.p.id&&trows[m.p.id]){
     finishTool(trows[m.p.id],m.p);groupTool(trows[m.p.id],0,true);statusSay('')}
    if(m.k==='thinking_delta'||m.k==='content_delta')nextStep();
    if(m.k==='thinking_delta'){
     if(!thinking){                             // first reasoning token
      tThink=performance.now();a.think._at=clockTime();
      a.think.style.display='';openThink(a);a.think.classList.add('live');
      thinkLabel(a,'thinking…');
      a.bub.innerHTML='';                       // drop the "working" placeholder
      a.think.querySelector('.body')._stick=true;     // nothing to preserve yet
     }
     statusGrew(m.p,true);
     paraMarks(tmarks,thinking,m.p);thinking+=m.p;
     if(!thinkPending){thinkPending=setTimeout(()=>{thinkPending=null;
      const body=a.think.querySelector('.body');
      renderThink(body,thinking,tmarks);
      if(body._stick)body.scrollTop=body.scrollHeight;   // only if you're not reading back
      bottom()},90)}}
    else if(m.k==='content_delta'){
     statusGrew(m.p,false);
     if(!answer&&thinking){                     // answer begins — tuck thinking away
      if(thinkPending){clearTimeout(thinkPending);thinkPending=null}
      const tbody=a.think.querySelector('.body');
      renderThink(tbody,thinking,tmarks);
      a.think.classList.remove('live');clampLong(tbody,thinking,12);
      thinkLabel(a,thoughtFor());
      // the answer beginning is where thinking stops being the thing to read: a long
      // reasoning pass used to push the answer itself below the fold. Opened by hand,
      // it stays open -- your choice outranks the rule, as it does for openThink.
      if(!a.think._user)a.think.open=false;
     }
     if(!answer){a.bub.innerHTML='';a.m.querySelectorAll('.retrynote').forEach(x=>x.remove())}
     answer+=m.p;a.bub.dataset.raw=answer;
     const now=performance.now();
     if(now-lastRender>70){lastRender=now;a.bub.innerHTML=md(answer);bottom()}
     else if(!pendingRender){pendingRender=setTimeout(()=>{pendingRender=null;
       lastRender=performance.now();a.bub.innerHTML=md(answer);bottom()},80)}}
    else if(m.k==='tool'){
     {const d=toolName(m.p.name);
      statusSay((TOOLVERB[d]||d)+' '+toolTarget(m.p.name,m.p.args).slice(0,40))}
     if(m.p.id){const r=toolRow(m.p);trows[m.p.id]=r;a.tools.appendChild(r);
      const ai=autoTags.findIndex(x=>x.name===m.p.name);
      if(ai>=0){const x=autoTags.splice(ai,1)[0];const tg=el('<span class=autotag>auto</span>');
       tg.title='allowed without asking — '+x.reason+(x.rule?' (your rule: '+x.rule+')':'');
       r.querySelector('.thead').insertBefore(tg,r.querySelector('.tt'))}}
     else{const c=el('<div class=tool></div>');     // older server: no id, no result pairing
      c.textContent='* '+m.p.name+'('+Object.entries(m.p.args||{}).map(([k,v])=>k+'='+String(v).slice(0,60)).join(', ')+')';
      a.tools.appendChild(c)}
     bottom()}
    else if(m.k==='subagent'){
     subagentLive(trows[m.p.parent],m.p);
     statusSay((m.p.description||'subagent')+': '+subStepLine(m.p).slice(0,50));bottom()}
    else if(m.k==='tool_progress'){
     // Claude Code's own count of how long a tool has run: it keeps the row's clock honest
     const r=m.p&&trows[m.p.id];
     if(r&&r.classList.contains('live')&&m.p.elapsed!=null)r._t0=Date.now()-m.p.elapsed*1000}
    else if(m.k==='prompt_suggestion'){showSuggestion(sendSid,m.p&&m.p.text)}
    else if(m.k==='tool_summary'){toolSummaryLine(m.p&&m.p.ids,m.p&&m.p.text)}
    else if(m.k==='bgtask'){bgNote(sendSid,m.p)}
    else if(m.k==='subagent_done'){subagentDone(trows[m.p.parent],m.p.subagent);bottom()}
    else if(m.k==='approval_request'){a.tools.appendChild(approvalBox(m.p));bottom();
     notify(sendSid,'Needs your approval',m.p.name+(m.p.reason?' — '+m.p.reason:''))}
    else if(m.k==='auto_approved'){
     // Claude Code does not stop to say so: the call's own line gets a small "auto" tag
     // (why, in its tooltip); the full note shows only with Ctrl+O
     {const row=(m.p.call_id&&trows[m.p.call_id])||
       Object.values(trows).reverse().find(r=>r.classList.contains('live')&&toolName(m.p.name)===r.dataset.disp);
      if(row&&!row.querySelector('.autotag')){const tg=el('<span class=autotag>auto</span>');
       tg.title='allowed without asking — '+m.p.reason+(m.p.rule?' (your rule: '+m.p.rule+')':'');
       row.querySelector('.thead').insertBefore(tg,row.querySelector('.tt'))}
      else if(!row)autoTags.push(m.p)}
     const b=el('<div class="autoappr vonly"></div>');
     b.textContent='✓ auto-approved — '+m.p.reason+' ('+m.p.name+')'+
       (m.p.rule?' — matched your rule: '+m.p.rule:'');a.tools.appendChild(b);bottom()}
    else if(m.k==='blocked'){const b=el('<div class=blocked></div>');
     b.textContent='Blocked: '+m.p.reason+' ('+m.p.name+')';a.tools.appendChild(b);bottom()}
    else if(m.k==='injection'){const b=el('<div class=injwarn></div>');
     b.textContent='Possible prompt injection in '+m.p.name+' output: '+m.p.markers.join(' | ');
     a.tools.appendChild(b);bottom()}
    else if(m.k==='tool_result'&&m.p&&m.p.name==='plan'&&m.p.output){
     const steps=parsePlan(m.p.output);
     if(steps.length){
      PLANS[sendSid]=steps;drawPlanDock();
      let box=a.m.querySelector('.planbox');
      if(!box){box=el('<div class=planbox><b>plan</b></div>');a.tools.appendChild(box)}
      [...box.querySelectorAll('.st')].forEach(x=>x.remove());
      steps.forEach(x=>{const {done,t:txt}=x;
       const r=el(`<div class="st${done?' done':''}${x.active&&!done?' active':''}"><span class=bx>${todoMark(x)}</span></div>`);
       const sp=document.createElement('span');sp.textContent=txt;r.appendChild(sp);
       box.appendChild(r)});
      bottom()}}
    else if(m.k==='stagnation'){
     const w=el('<div class=injwarn></div>');
     w.textContent=`repeated ${m.p.tool} ${m.p.times}× with the same arguments — nudged to change approach`;
     a.tools.appendChild(w);bottom()}
    else if(m.k==='round_limit'){
     const b=el('<div class=limitbox></div>');
     b.appendChild(el(m.p.reason==='time'?'<b>Stopped at the time limit without finishing</b>'
                      :`<b>Stopped after ${m.p.rounds} tool rounds without finishing</b>`));
     if((m.p.pending||[]).length){
      b.appendChild(el('<div style="color:var(--mut);margin-bottom:4px">still outstanding:</div>'));
      m.p.pending.forEach(t=>{const d=document.createElement('div');
       d.style.color='var(--mut)';d.textContent='• '+t;b.appendChild(d)})}
     const btn=el('<button>Continue</button>');
     btn.onclick=async()=>{btn.disabled=true;
      // whatever you were typing while you read the outstanding list is yours: it used
      // to be overwritten by the canned prompt and sent in your name
      const typed=q.value;
      const r=await (await fetch('/api/continue',{method:'POST'})).json();
      q.value=r.message;go();
      if(typed){q.value=typed;fitQ();saveDraft(sid)}};
     b.appendChild(btn);a.m.appendChild(b);bottom()}
    else if(m.k==='tool_result'&&m.p&&m.p.diff&&m.p.diff.diff){
     a.tools.appendChild(diffBlock(m.p.diff));bottom()}
    else if(m.k==='tool_result'&&m.p&&m.p.images&&m.p.images.length){
     const box=el('<div class=imgs></div>');
     m.p.images.forEach(rel=>{const i=document.createElement('img');
      i.src='/api/ws/'+encodeURIComponent(rel);i.style.cursor='zoom-in';
      i.onclick=()=>window.open(i.src,'_blank');box.appendChild(i)});
     a.tools.appendChild(box);bottom()}
    else if(m.k==='server_starting'){
     const w=a.bub.querySelector('.working')||a.bub;
     const secs=m.p.elapsed?` · ${m.p.elapsed}s`:'';
     a.bub.innerHTML=`<span class=working>${esc(m.p.msg)}<span class=dots></span>`
      +`<span style="color:var(--dim)">${secs}</span></span>`
      +`<div class=note style="margin-top:5px">${m.p.note?esc(m.p.note)
        :`the server sleeps after ${(INFO.settings&&INFO.settings.idle_min)||20} min idle — `
         +`first message after that reloads ~15 GB of weights`}</div>`;
     bottom()}
    else if(m.k==='question'){a.tools.appendChild(questionBox(m.p));bottom();
     notify(sendSid,'Orbit has a question',m.p.question||'')}
    else if(m.k==='plan_nudge'||m.k==='fail_streak'||m.k==='ultrathink'){
     sysline(m.p.msg||m.k)}
    else if(m.k==='queued'){               // another chat has the model; this one waits in line
     a.bub.innerHTML='<span class=working>'+esc(m.p.msg||'waiting for another chat to finish')+'<span class=dots></span></span>';bottom()}
    else if(m.k==='dequeued'){
     a.bub.innerHTML='<span class=working>its turn — starting<span class=dots></span></span>'}
    else if(m.k==='server_ready'){
     a.bub.innerHTML=`<span class=working>ready in ${m.p.elapsed}s — thinking<span class=dots></span></span>`;
     bottom()}
    else if(m.k==='skill_hint'){
     const h=el('<div class=hintbar></div>');
     h.textContent=`matches your skill “${m.p.name}” — click to make it follow that procedure`;
     h.onclick=()=>{q.value=`Use the ${m.p.name} skill for this.`;q.focus();h.remove()};
     a.tools.appendChild(h);bottom()}
    else if(m.k==='sources'){
     const d=el('<details class=sources><summary>sources used</summary></details>');
     m.p.forEach(x=>{const r=el('<div class=s></div>');
      r.innerHTML=`<b>${esc(x.doc)}</b> <span style="color:var(--dim)">score ${x.score}</span>`;
      const sn=document.createElement('div');sn.style.opacity='.8';sn.textContent=x.snippet;
      r.appendChild(sn);d.appendChild(r)});
     a.m.appendChild(d);bottom()}
    else if(m.k==='verified'){
     if(m.p.passed&&m.p.fail_open){sysline('the check could not run: '+(m.p.reason||''))}
     else if(m.p.passed){sysline('checked against your request — looks done')}
     else{const d=el('<div class=hintbar></div>');
      d.textContent='not finished: '+(m.p.reason||'')+(m.p.next?' → '+m.p.next:'');
      a.tools.appendChild(d);bottom()}}
    else if(m.k==='goal_offer'){setGoalOffer(sendSid,m.p)}
    else if(m.k==='review'){
     const d=el('<details class=think style="margin-top:6px"></details>');
     d.appendChild(el(`<summary>Review of ${m.p.files} changed file${m.p.files===1?'':'s'} · ${esc(m.p.model||'')}</summary>`));
     const b=el('<div class=body></div>');b.textContent=m.p.text;d.appendChild(b);
     if((m.p.not_reviewed||[]).length){const n=el('<div class=note style="margin-top:6px"></div>');
      n.textContent='Not reviewed: '+m.p.not_reviewed.join('; ');d.appendChild(n)}
     a.tools.appendChild(d);bottom()}
    else if(m.k==='weak_claims'){
     const w=el('<div class=weak></div>');
     w.appendChild(el('<b>Claims with little support in the retrieved sources</b>'));
     m.p.forEach(x=>{const r=document.createElement('div');
      r.textContent=`(${Math.round(x.support*100)}% overlap) ${x.sentence}`;w.appendChild(r)});
     a.m.appendChild(w);bottom()}
    else if(m.k==='interjection'){
     const pn=PENDING_NOTES.find(x=>!x.done&&x.text===m.p.text);
     if(m.p.late){
      if(pn){pn.done=true;pn.tag.textContent='kept — it reads this with your next message'}}
     else{
      // it just read a note you sent mid-answer: close off what it said before
      // the note, and let what it says next start below it
      if(pendingRender){clearTimeout(pendingRender);pendingRender=null}
      if(thinkPending){clearTimeout(thinkPending);thinkPending=null;
       renderThink(a.think.querySelector('.body'),thinking,tmarks)}
      if(answer){a.bub.innerHTML=md(answer);decorate(a.bub)}
      else if(!thinking&&!a.tools.childElementCount)a.m.remove();
      else a.bub.innerHTML='';
      a.think.classList.remove('live');if(thinking)thinkLabel(a,thoughtFor());
      if(pn){pn.done=true;pn.tag.textContent='✓ read';pn.node.classList.remove('pending');wrap.appendChild(pn.node)}
      else noteBubble(m.p.text,'✓ read — sent from another window');
      a=addAssistant(modelLabel());
      a.bub.innerHTML='<span class=working>reading your note<span class=dots></span></span>';
      thinking='';answer='';tmarks=[];bottom()}}
    else if(m.k==='long_running'){
     // just a progress line: it carries on by itself, with no time limit.
     // This used to be a box with Stop / Keep going buttons, which read as
     // though it were waiting for an answer. Stop is always in the composer.
     document.querySelectorAll('.longrun').forEach(x=>x.remove());
     const b=el('<div class="sysline longrun"></div>');
     b.textContent=`still working — ${m.p.minutes} min, ${m.p.rounds} steps so far`+
      ((m.p.pending||[]).length?' · next: '+m.p.pending.slice(0,2).join(' · '):'')+' · no action needed';
     a.tools.appendChild(b);bottom()}
    else if(m.k==='fallback'){
     a.m.querySelectorAll('.retrynote').forEach(x=>x.remove());
     const w=el('<div class="injwarn fallbacknote"></div>');
     w.textContent=`${modelName(m.p.from)} kept failing${+m.p.after>1?' ('+m.p.after+'×)':''} — continuing on ${modelName(m.p.to)}`;
     if(m.p.why)w.title=String(m.p.why);
     a.tools.appendChild(w);a.m.querySelector('.byline').textContent=modelName(m.p.to);bottom()}
    else if(m.k==='retry'){
     a.m.querySelectorAll('.retrynote').forEach(x=>x.remove());   // one per answer, the latest
     const w=el('<div class="injwarn retrynote"></div>');
     if(m.p.hold){
      const t=+m.p.waited||0, ago=t>=3600?Math.floor(t/3600)+' h '+Math.floor(t%3600/60)+' min':t>=60?Math.floor(t/60)+' min':t+' s';
      w.textContent=`waiting for ${modelName(MODELS.current||MODELS.default)} to come back — trying again in ${Math.max(1,Math.round(+m.p.wait))}s `+
       `(waiting ${ago}; Stop to cancel)`;
      if(m.p.error)w.title=String(m.p.error);a.tools.appendChild(w);bottom();continue}
     w.textContent=(+m.p.wait>0?`model server error — retrying in ${Math.max(1,Math.round(+m.p.wait))}s `
      :(m.p.kind==='overflow'?'too long for the model — compacting, then retrying ':'model server error — retrying '))+
      `(attempt ${m.p.attempt} of ${m.p.of||5})`;
     if(m.p.error)w.title=String(m.p.error);
     a.tools.appendChild(w);bottom()}
    else if(m.k==='stream_error'){
     // shown by the retry note; an older server sends no retry event, so say it here
     if(m.p.of==null)sysline(`the model server errored (${m.p.error}) — retrying, attempt ${m.p.attempt}`)}
    else if(m.k==='notice'){
     // Claude Code's hooks report on every step; they fold into one line per answer
     if(/^hook\s/i.test(m.p.msg||'')){hookNote(sendSid,m.p.msg);continue}
     if(m.p.kind==='limit'){const b=el('<div class="injwarn limitnote"></div>');b.textContent='\u23f8 '+(m.p.msg||'');
      a.m.appendChild(b);bottom();notify(sendSid,'Usage limit',m.p.msg||'');continue}
     sysline(m.p.msg||'')}
    else if(m.k==='status'){const w=a.bub.querySelector('.working');
     statusSay(m.p.msg||'');
     if(w&&!answer)a.bub.innerHTML='<span class=working>'+esc(m.p.msg||'working')+'<span class=dots></span></span>'}
    else if(m.k==='squeezed'){
     sysline(`trimmed ${Math.round(m.p.chars/1000)}k of old tool output — context now ${m.p.pct}%`)}
    else if(m.k==='autocompact'){
     sysline(`context ${m.p.pct}% full — compacting automatically (threshold ${m.p.limit}%)`)}
    else if(m.k==='autocompact_done'){
     sysline(`compacted ${m.p.before} → ${m.p.after} messages`)}
    else if(m.k==='error'){const e=el('<div class=err></div>');e.textContent=m.p;a.m.appendChild(e);
     errored=true;notify(sendSid,'Error',String(m.p))}
    else if(m.k==='end'){endP=m.p||{};if(m.p&&m.p.title&&sid===sendSid){
     $('#title').textContent=m.p.title; if(m.p.sid)sid=m.p.sid}}
   }}
  clearInterval(dog);
  if(queuedBy){SENDING.delete(sendSid);stopStatus(sendSid);await refreshRunning();syncBusy();renderSessions();return}
  // No closing event: the connection broke, not the answer -- it carries on on the Mac
  lost=!endP;
  if(pendingRender){clearTimeout(pendingRender);pendingRender=null}
  // thinking that came after the answer's text is folded too, now that it is done
  a.m.querySelectorAll('details.think .body').forEach(b=>{if(!b.classList.contains('clamped'))clampLong(b,b.textContent,12)});
  setTimeout(pollBg,1200);             // background work it left running shows at once
 if(thinkPending){clearTimeout(thinkPending);thinkPending=null;
  renderThink(a.think.querySelector('.body'),thinking,tmarks)}
 if(thinking&&!answer){a.think.classList.remove('live');thinkLabel(a,thoughtFor())}
 if(!answer)a.bub.textContent=lost?'(the connection dropped — following the answer again)'
                              :(stoppedSid===sendSid)?'(stopped before it wrote anything)':'(no answer)';
 else {a.bub.innerHTML=md(answer);decorate(a.bub)}
 setTimeout(()=>recheckMissing(a.m),2500);          // files it said it would make, made since
 const took=endP&&endP.secs!=null?endP.secs:(performance.now()-t0)/1000;
 answerStats(a,took,endP&&endP.usage);
 // the turn is over: its steps fold away behind one line, as they do on reopening
 if(PREF.get('foldtools','1')==='1')foldTurns();
 if(endP&&(endP.changes||[]).length&&endP.t)undoButton(a,endP.t,endP.changes.length);
 if(lost)sysline('the connection to the Mac dropped — the answer goes on there; following it again');
 else if(stoppedSid!==sendSid&&!errored)
  notify(sendSid,'Answer ready',answer.replace(/\s+/g,' ').trim().slice(0,160)||'(no answer)');
 }catch(e){clearInterval(dog);
  // a network failure mid-answer is the connection, not the answer: the Mac carries on
  if(reached&&e instanceof TypeError){lost=true;a.bub.textContent='(the connection dropped — following the answer again)'}
  else if(!reached){
   // it never got there: nothing to show for it, and nothing you wrote is lost
   if(ubub&&ubub.remove)ubub.remove();a.m.remove();
   restoreComposer(sendSid,raw,sending,sentPastes);
   toast('not sent — '+(e&&e.message||e)+'. Your message is back in the box.')}
  else{a.bub.innerHTML='';const x=el('<div class=err></div>');x.textContent='Error: '+(e&&e.message||e);a.m.appendChild(x);
   notify(sendSid,'Error',String(e&&e.message||e))}}
 Object.values(trows).forEach(r=>{if(r.classList.contains('live')){finishTool(r,{stopped:true});groupTool(r)}});
 stopStatus(sendSid);
 RUNNING.delete(sendSid); SENDING.delete(sendSid); renderSessions(); syncBusy();
 PENDING_NOTES.filter(x=>!x.done&&x.sid===sendSid).forEach(x=>{x.done=true;
  x.tag.textContent='waiting — it reads this with your next message'});
 if($('#files').style.display!=='none')renderFiles(); refreshFileCache();
 if(!lost&&sid===sendSid&&!document.hidden&&document.hasFocus())markSeenOnMac(sendSid);   // you watched it land
 $('#dot').classList.remove('busy');loadSessions();refreshStatus();q.focus();
 if(lost&&sid===sendSid){WATCH_N=null;openSession(sendSid)}   // rejoins from the live buffer
 else afterTurn(sendSid);
 // the chat may have set itself a goal, or started other chats, during the answer
 loadLinks(sendSid).then(()=>{if(GOALS[sendSid]&&GOALS[sendSid].status==='active')followGoal(sendSid)})}
$('#stopgen').onclick=async()=>{
 stoppedSid=sid;
 await fetch('/api/cancel',{method:'POST',headers:{'Content-Type':'application/json'},
  body:JSON.stringify({sid})});toast('stopping…')};

/* ---------------- settings ---------------- */
function closeModal(){$('#modalhost').innerHTML=''}
// Settings → Memory & instructions in Claude Code mode: Claude's own files, as a
// terminal session sees them (CLAUDE.md for you and for the chat's folder, and the
// memory Claude keeps per folder). Orbit's memory stays for Orbit's own chats.
let MEM_ORBIT=false;
async function renderClaudeMemory(body,toOrbit,cwd){
 const url='/api/claude/memory?sid='+encodeURIComponent(sid||'')+(cwd?'&cwd='+encodeURIComponent(cwd):'');
 const d=await (await fetch(url)).json();
 const mem=d.memory||{}, ins=d.instructions||[];
 const tilde=p=>String(p||'').replace(/^\/Users\/[^/]+/,'~');
 body.innerHTML=`<div class=note style="margin-bottom:8px">Claude Code chats use Claude's own instructions and memory — the same files a terminal session reads, edited here in place (the previous version is backed up). Orbit adds none of its own. <a style="cursor:pointer;color:var(--acc)" id=cm_orbit>Orbit's own memory (for Orbit chats) →</a></div>
  <div class=grid><label>Folder</label><div style="display:flex;gap:6px"><select id=cm_folder style="flex:1"></select><button class=ghost id=cm_pick>Choose…</button></div></div>
  <div class=sec>Instructions <small>— CLAUDE.md files Claude reads in this folder</small></div><div id=cm_ins></div>
  <div class=sec>This chat's instructions <small>— added to Claude's system prompt for this chat only</small></div>
  <textarea class=ta id=cm_chat style="min-height:60px" placeholder="e.g. Answer in Chinese in this chat."></textarea>
  <button class=ghost id=cm_chatsave style="margin-top:6px">Save for this chat</button>
  <div class=sec>Claude's memory <small>— ${esc(tilde(mem.dir))} · ${(mem.items||[]).length} memories</small></div>
  <div id=cm_mem></div>
  <details style="margin-top:8px"><summary class=note style="cursor:pointer">+ Add a memory</summary>
   <div class=grid style="margin-top:6px"><label>File name</label><input type=text id=cm_file placeholder="lab-context.md"></div>
   <textarea class=ta id=cm_text style="min-height:110px;margin-top:6px">---\nname: \ndescription: \nmetadata:\n  type: user\n---\n\n</textarea>
   <button class=ghost id=cm_add style="margin-top:6px">Save memory</button></details>
  ${mem.index?`<details style="margin-top:8px"><summary class=note style="cursor:pointer">MEMORY.md (the index Claude loads)</summary><pre style="white-space:pre-wrap;font-size:12px">${esc(mem.index)}</pre></details>`:''}`;
 $('#cm_orbit').onclick=toOrbit;
 // folders: this chat's, then every folder Claude keeps memory for
 const sel=$('#cm_folder');
 const opts=[{path:d.cwd,count:(mem.items||[]).length,cur:true},...(d.folders||[]).filter(f=>f.path!==d.cwd)];
 sel.innerHTML=opts.map(f=>`<option value="${esc(f.path)}">${esc(tilde(f.path))}${f.cur?' (this chat)':''} · ${f.count} memories</option>`).join('');
 sel.onchange=()=>renderClaudeMemory(body,toOrbit,sel.value);
 $('#cm_pick').onclick=async()=>{const p=await pickFolder(d.cwd,'Folder whose Claude instructions and memory to show');if(p)renderClaudeMemory(body,toOrbit,p)};
 const insBox=$('#cm_ins');
 ins.forEach(f=>{
  const r=el(`<details class=memrow style="display:block;padding:6px 8px"><summary style="cursor:pointer"><b>${esc(f.label)}</b> <span class=note>${esc(tilde(f.path))}${f.exists?'':' · not created yet'}</span></summary>
    <textarea class=ta style="min-height:120px;margin-top:6px" placeholder="Nothing yet — what should Claude always know here?"></textarea>
    <button class=ghost style="margin-top:4px">Save</button></details>`);
  if(f.scope==='user'||f.exists)r.open=f.exists;
  const ta=r.querySelector('textarea');ta.value=f.text||'';
  r.querySelector('button').onclick=async()=>{const x=await apiPost('/api/claude/memory',{op:'instructions',scope:f.scope,cwd:d.cwd,text:ta.value},'saving');
   if(x)toast('saved '+tilde(x.path))};
  insBox.appendChild(r)});
 $('#cm_chat').value=d.chat_instructions||'';
 $('#cm_chatsave').onclick=async()=>{if(!sid)return toast('open a chat first');
  if(await apiPost('/api/claude/memory',{op:'chat',sid,text:$('#cm_chat').value},'saving'))toast('this chat\'s instructions saved')};
 const mb=$('#cm_mem');
 if(!(mem.items||[]).length)mb.innerHTML='<div class=note>No memories in this folder yet. Claude writes them as it works (when its memory is on), or add one below.</div>';
 (mem.items||[]).forEach(m=>{
  const r=el(`<details class=memrow style="display:block;padding:5px 8px"><summary style="cursor:pointer"><b></b> <span class=note></span></summary>
    <textarea class=ta style="min-height:120px;margin-top:6px"></textarea>
    <div style="display:flex;gap:6px;margin-top:4px"><button class=ghost data-a=save>Save</button><button class=ghost data-a=del>Delete</button><span class=note style="margin-left:auto">${esc(m.file)} · ${new Date(m.mtime*1000).toLocaleDateString()}</span></div></details>`);
  r.querySelector('b').textContent=m.name;r.querySelector('.note').textContent=(m.type?m.type+' · ':'')+m.description;
  const ta=r.querySelector('textarea');ta.value=m.text;
  r.querySelector('[data-a=save]').onclick=async()=>{if(await apiPost('/api/claude/memory',{op:'save',cwd:d.cwd,file:m.file,text:ta.value},'saving'))toast('saved')};
  r.querySelector('[data-a=del]').onclick=async()=>{if(!confirm('Move '+m.file+' to the Trash and remove it from MEMORY.md?'))return;
   if(await apiPost('/api/claude/memory',{op:'delete',cwd:d.cwd,file:m.file},'deleting'))renderClaudeMemory(body,toOrbit,d.cwd)};
  mb.appendChild(r)});
 $('#cm_add').onclick=async()=>{const f=$('#cm_file').value.trim(),t=$('#cm_text').value;
  if(!f)return toast('a file name, like lab-context.md');
  const x=await apiPost('/api/claude/memory',{op:'save',cwd:d.cwd,file:f,text:t},'saving');
  if(x){toast(x.new?'memory added (and listed in MEMORY.md)':'saved');renderClaudeMemory(body,toOrbit,d.cwd)}}}
// Settings -> Phone: each paired device, when it was last heard from, what it may do,
// and revoking it alone. "Chats only" keeps it out of settings, keys and pairing.
async function drawDevices(data){
 const box=$('#devlist');if(!box)return;
 let d=data;
 if(!d){try{const r=await fetch('/api/devices',{method:'POST',headers:{'Content-Type':'application/json'},body:'{"op":"list"}'});
  d=await r.json();if(!r.ok)throw 0}catch(e){box.textContent='This device cannot list devices.';return}}
 box.innerHTML='';
 const ago=t=>t?agoShort(t)+' ago':'never';
 (d.devices||[]).forEach(v=>{
  const r=el(`<div class=memrow style="align-items:center;gap:10px;flex-wrap:wrap"><b class=dn style="cursor:pointer" title="rename"></b>
   <span class=sub></span><select class=ds><option value=full>everything</option><option value=chat>chats only</option></select>
   <button class=ghost data-a=revoke>revoke</button></div>`);
  r.querySelector('.dn').textContent=v.name+(v.id===d.you?' (this one)':'');
  r.querySelector('.sub').textContent=`${v.via==='web'?'browser':'app'} · paired ${new Date(v.created*1000).toLocaleDateString()} · last seen ${ago(v.last_seen)}`;
  r.querySelector('.ds').value=v.scope||'full';
  const op=async(body,what)=>{const x=await apiPost('/api/devices',{id:v.id,...body},what);if(x)drawDevices(x)};
  r.querySelector('.ds').onchange=e=>op({op:'scope',scope:e.target.value},'changing what it may do');
  r.querySelector('.dn').onclick=()=>{const n=prompt('Name this device',v.name);if(n&&n.trim())op({op:'rename',name:n.trim()},'renaming')};
  r.querySelector('[data-a=revoke]').onclick=()=>{if(confirm('Revoke '+v.name+'? It must scan the QR again to come back.'))op({op:'revoke'},'revoking')};
  box.appendChild(r)});
 if(d.legacy){
  const r=el(`<div class=memrow style="align-items:center;gap:10px"><b>Paired before device tokens</b>
   <span class=sub>anything paired with the old shared token${d.you==='legacy'?' — including this one':''}</span>
   <button class=ghost>retire it</button></div>`);
  r.querySelector('button').onclick=async()=>{if(!confirm('Stop accepting the old shared token? Anything paired with it must scan the QR again.'))return;
   const x=await apiPost('/api/devices',{op:'retire_legacy'},'retiring the old token');if(x)drawDevices(x)};
  box.appendChild(r)}
 if(!(d.devices||[]).length&&!d.legacy)box.textContent='No devices paired.'}
// Settings' searchable names: section headings and field labels, taken from the tabs'
// own drawing code (this function's source), grouped by the tab that draws them.
// --- Settings -> Cluster models: the model servers of bin/modelserver.py
async function drawServers(gen){
 const box=$('#srvbox');if(!box)return;
 const api=async(op,extra)=>{const r=await fetch('/api/servers',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({op,...(extra||{})})});
  const j=await r.json().catch(()=>({}));if(!r.ok)throw new Error(j.error||('error '+r.status));return j};
 const dur=t=>{t=Math.max(0,Math.round(t||0));const h=Math.floor(t/3600),m=Math.floor(t%3600/60);return h?`${h} h ${m} min`:m?`${m} min`:`${t} s`};
 const num=n=>n==null?'—':Number(n).toLocaleString();
 const when=at=>{const d=new Date(at*1000),today=new Date(),tm=new Date(Date.now()+864e5);
  const day=d.toDateString()===today.toDateString()?'today':d.toDateString()===tm.toDateString()?'tomorrow':d.toLocaleDateString(undefined,{weekday:'long'});
  return day+' at '+d.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})};
 const NAMES={ready:'Ready',loading:'Loading the model',queued:'Waiting for a GPU',stopping:'Stopping',stopped:'Stopped',failed:'Failed',unreachable:'Cluster not reachable',unknown:'Checking…'};
 const DAYS=['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];
 let data;try{data=await api('list')}catch(e){box.textContent='Could not read the servers: '+e.message;return}
 if(gen!==RENDER_GEN||!$('#srvbox'))return;
 const live=sv=>{const st=sv.status||{};
  const ctx=(st.info&&st.info.max_model_len)||null;
  const note={queued:st.reason&&st.reason!=='None'?`waiting: ${st.reason}`:'waiting for a free GPU',
   loading:st.t_submit?`${dur(Date.now()/1000-st.t_submit)} since it was asked for; loading takes about 5–10 minutes`:'',
   ready:st.t_ready?`up for ${dur(Date.now()/1000-st.t_ready)}`:'',stopped:'',stopping:'cancelling the job…'}[st.state]||'';
  return `<div class=srvstate ${''}><i></i>${esc(NAMES[st.state]||st.state)}</div>
   <div class=note>${esc(note)}${st.error?` <span class=srverr>${esc(st.error)}</span>`:''}${st.mail_error?` <span class=srverr>e-mail failed: ${esc(st.mail_error)}</span>`:''}</div>
   <div class=stat>
    <div><b>${ctx?num(ctx):num(sv.settings.max_model_len)}</b><small>${ctx?'context length (tokens)':'context length when started'}</small></div>
    <div><b>${st.jid?'#'+esc(st.jid):'—'}</b><small>job${st.node?' on '+esc(st.node):''}</small></div>
    <div><b>${st.left!=null?dur(st.left):'—'}</b><small>time left on the job${st.renew&&st.renew.on?(st.renew.until?' · then renewed until '+esc(st.renew.until.replace('T',' ')):' · then renewed'):''}</small></div>
    <div><b>${st.next?esc(st.next.kind)+' '+esc(when(st.next.at)):'—'}</b><small>next on the schedule</small></div>
   </div>${placed(st)}${health(st)}${stats(st)}${bench(st)}`};
 const placed=st=>{const p=st.placement;if(!p||!p.chosen)return '';
  const mins=c=>{const m=Math.max(0,Math.round((c.start-p.at)/60));return m<90?m+' min':m<2880?Math.round(m/60)+' h':Math.round(m/1440)+' days'};
  const others=(p.options||[]).filter(o=>o.partition!==p.chosen.partition||o.mem_gb!==p.chosen.mem_gb);
  return `<div class=note>Placed on <b>${esc(p.chosen.partition)}</b> with ${p.chosen.mem_gb} GB (${p.how==='model'?'chosen by a model: '+esc(p.why||''):'the soonest the scheduler offered'}: estimated start in ${mins(p.chosen)}${others.length?'; others: '+others.slice(0,3).map(o=>esc(o.partition)+' '+o.mem_gb+' GB in '+mins(o)).join(', '):''}).</div>`};
 const ago=t=>{const d=Date.now()/1000-t;return d<90?'just now':d<5400?Math.round(d/60)+' min ago':Math.round(d/3600)+' h ago'};
 const health=st=>{if(st.state!=='ready'||!st.health)return '';const h=st.health;
  return h.ok?`<div class=note>Answers a test request in ${h.s} s (checked ${ago(h.at)}).</div>`
   :`<div class=note><span class=srverr>Not answering requests</span> — it is up, but a one-word test failed ${h.fails} time${h.fails>1?'s':''} (${esc(h.error||'')}).</div>`};
 const bench=st=>{const b=st.bench;if(!b)return '';
  return `<div class=note>Speed test, ${ago(b.at)}: writes <b>${b.decode_tps}</b> tokens/s · reads a ${num(b.prompt_tokens)}-token prompt at <b>${num(b.prefill_tps)}</b> tokens/s (${b.cold_s} s), and in ${b.warm_s} s when it has seen it before.</div>`};
 const pct=v=>v==null?'—':Math.round(v*100)+'%', f1=v=>v==null?'—':String(v);
 const stats=st=>{if(st.state!=='ready')return '';const x=st.stats;
  if(!x)return '<div class=note>Reading its statistics…</div>';
  if(x.off)return '<div class=note>This run has no statistics: it was started before they were switched on. Restart it to get them.</div>';
  return `<div class=sec style="margin:8px 0 2px">Speed and load <small>— from the model's own counters, no chat text in them</small></div>
   <div class=stat>
    <div><b>${f1(x.decode_tps)}</b><small>tokens per second, one answer</small></div>
    <div><b>${x.throughput_tps!=null?x.throughput_tps:'—'}</b><small>tokens per second, all answers, last minute</small></div>
    <div><b>${x.ttft_s!=null?x.ttft_s+' s':'—'}</b><small>until the first word</small></div>
    <div><b>${x.e2e_s!=null?x.e2e_s+' s':'—'}</b><small>a whole answer, on average</small></div>
    <div><b>${x.prefill_tps!=null?num(x.prefill_tps):'—'}</b><small>prompt tokens read per second</small></div>
    <div><b>${pct(x.cache_hit)}</b><small>of prompts found in its cache</small></div>
    <div><b>${pct(x.kv_used)}</b><small>of its context memory in use</small></div>
    <div><b>${x.accepted!=null?pct(x.accepted):'—'}</b><small>look-ahead guesses accepted</small></div>
    <div><b>${x.running!=null?num(x.running):'—'} · ${x.waiting!=null?num(x.waiting):'—'}</b><small>answering · waiting</small></div>
    <div><b>${num(x.finished)}</b><small>answers, since it started</small></div>
    <div><b>${num(x.prompt_tokens)}</b><small>tokens read</small></div>
    <div><b>${num(x.generated_tokens)}</b><small>tokens written</small></div>
   </div>`};
 const card=sv=>{const c=el(`<div class=srvcard data-id="${esc(sv.id)}"></div>`);
  const S=sv.settings,N=sv.notify||{},ev=N.events||{};
  c.innerHTML=`<div class=srvhead><input class=srvname value="" title="Rename"><span class="srvlive-pill"></span></div>
   <div class=srvlive></div>
   <div class=srvact>
    <button class=primary data-a=start>Start</button><button class=ghost data-a=restart>Restart with these settings</button>
    <button class=ghost data-a=stop>Stop</button><button class=ghost data-a=bench title="three short requests: writing speed, reading speed cold and cached">Run a speed test</button><button class=ghost data-a=log title="the end of the newest log kept on the cluster">Show server messages</button><span class=note data-r=msg></span></div>
   <div class=sec>Settings <small>— used the next time it starts</small></div>
   <div class=grid>
    <label>Context length</label><div class=sw><input type=number data-s=max_model_len min=1024 step=1024><span class=note>tokens it can hold at once. Longer needs more GPU memory and leaves room for fewer parallel requests</span></div>
    <label>Requests at once</label><div class=sw><input type=number data-s=max_num_seqs min=1 max=1024><span class=note>how many chats it will answer in parallel</span></div>
    <label>GPU memory share</label><div class=sw><input type=number data-s=gpu_mem_util min=0.3 max=0.98 step=0.01><span class=note>of the card's memory, 0.30–0.98</span></div>
    <label>Speculative tokens</label><div class=sw><input type=number data-s=mtp_tokens min=0 max=8><span class=note>the model's own look-ahead (MTP); 0 turns it off. Usually 1–3 is faster</span></div>
    <label>Quick start</label><div class=sw><input type=checkbox data-s=eager><span class=note>skip compiling and graph capture: starts in about 2 minutes instead of 8–10, answers more slowly. For testing</span></div>
    <label>Privacy</label><div class=sw><select data-s=keep_log><option value="false">Private — keep nothing on the cluster</option><option value="true">Keep a log of the server and of every request</option></select>
     <span class=note>a kept log has the text of your chats; it is in a folder only your cluster account can read, and logs older than 14 days are deleted. Neither choice changes the speed</span></div>
    <label>Server messages</label><div class=sw><input type=checkbox data-s=error_log><span class=note>keep the server's own messages from its START only (loading steps, warnings, errors), so you can see why a start failed. It stops writing the moment the server answers, before any chat can reach it, so no chat text can be in it. Not used when the full log above is kept</span></div>
    <label>Prompt reading</label><div class=sw><input type=number data-s=batched_tokens min=2048 max=262144 step=2048><span class=note>tokens read per step. Higher reads a long prompt sooner; every chat opens with about 35,000</span></div>
    <label>Context memory</label><div class=sw><select data-s=kv_cache_dtype><option value=auto>Normal</option><option value=fp8>Half size (fp8) — room for twice the context or answers, a little less exact</option></select></div>
    <label>Sampling</label><div class=sw><input type=number data-s=temperature min=0 max=2 step=0.05 style="width:80px"> <input type=number data-s=top_p min=0.05 max=1 step=0.05 style="width:80px"> <input type=number data-s=top_k min=0 max=1000 style="width:80px"><span class=note>temperature · top-p · top-k, for requests that do not set them. Qwen's advice when it thinks: 0.6 · 0.95 · 20</span></div>
    <label>Async scheduling</label><div class=sw><input type=checkbox data-s=async_scheduling><span class=note>overlaps scheduling with the GPU for more throughput. Newer; try it with Quick start first</span></div>
    <label>Job time limit</label><div class=sw><input type=number data-s=time_limit_h min=1 max=336><span class=note>hours. The job ends by itself after this</span></div>
    <label>Renew after the time limit</label><div class=sw><input type=checkbox data-s=renew><span class=note>when the job's time limit ends it, start it again. Until</span>
     <input type=datetime-local data-s=renew_until style="width:auto"><span class=note>— empty: until you switch this off</span></div>
    <label>Move off a stuck node</label><div class=sw><input type=number data-s=load_timeout_min min=0 max=1440 style="width:80px"><span class=note>minutes still loading, then cancel and start it on another node (at most twice). 0 = never</span></div>
    <label>Where it runs</label><div class=sw><select data-s=placement><option value=auto>Automatic — start where the scheduler says it starts soonest</option><option value=ask>Ask a model to choose among those</option><option value=fixed>Fixed — only the partition and memory set here</option></select>
     <input data-s=placement_model placeholder="model for 'ask' (empty: the helper model)" style="max-width:240px"><span class=note>Before each start, Orbit asks the scheduler where each choice (the default partition or <code>pi_shared</code>, with the full memory or the least below) would start, and picks one. Nothing is submitted for the estimates</span></div>
    <label>GPU memory it needs</label><div class=sw><input type=number data-s=min_vram_gb min=0 max=1000 style="width:80px"><span class=note>GB. Only nodes whose GPUs have at least this much are used, and a node that turns out to be too small or already busy is skipped and remembered. 0: no limit. (The 40 GB cards cannot hold this model.)</span></div>
    <label>Least memory</label><div class=sw><input type=number data-s=min_mem_gb min=8 max=2048 style="width:80px"><span class=note>GB of host memory it may be given when that starts it sooner. The model sits on the GPU; the server measured 6.4 GB in all</span></div>
    <label>Partition</label><div class=sw><input data-s=partition placeholder="(default)" style="max-width:200px"><span class=note>where the job may run. Empty: the cluster's default (campus). <code>pi_shared</code> reaches the larger shared GPU pool, often much sooner; <code>campus,pi_shared</code> takes whichever starts first (if the cluster allows it)</span></div>
    <label>Avoid nodes</label><div class=sw><input data-s=exclude_nodes placeholder="e.g. g33, g34" style="max-width:240px"><span class=note>compute nodes it must not run on, separated by commas; a node that did not finish loading is also avoided for 6 hours by itself</span></div>
    <label>Keep it running</label><div class=sw><input type=checkbox data-s=keep_alive><span class=note>start it again if it fails or stops answering — at most twice a day, and never after you stopped it</span></div>
    <label>Stop when idle</label><div class=sw><input type=number data-s=idle_stop_min min=0 max=1440><span class=note>minutes without a request, then stop it to free the GPU. 0 = never</span></div>
    <label>GPUs · CPUs · memory</label><div class=sw><input type=number data-s=gpus min=1 max=8 style="width:70px"> <input type=number data-s=cpus min=1 max=128 style="width:80px"> <input type=number data-s=mem_gb min=4 max=2048 style="width:90px"><span class=note>GPUs, CPU cores, GB of RAM asked of the cluster</span></div>
   </div>
   <div class=sec>Schedule <small>— start and stop by themselves, while Orbit is running</small></div>
   <div data-r=sched></div>
   <div class=srvact><button class=ghost data-a=addrow>Add a schedule</button>
    <span class=note>A start waits for a GPU, so it is ready some minutes after the time. A stop you do by hand is not undone the same day.</span></div>
   <div class=sec>Tell me</div>
   <div class=grid>
    <label>E-mail</label><div class=sw><input type=text data-n=email placeholder="empty: no e-mail" style="min-width:300px"><button class=ghost data-a=testmail>Send a test</button>
     <span class=note>sent by the cluster itself, not from your own mail account, so it arrives even when this Mac is off. Applies from the next start. The cluster delivers to user@mail.cluster.example.edu</span></div>
    <label>When it</label><div class=sw style="flex-wrap:wrap;gap:14px">
     <label><input type=checkbox data-e=ready> is ready</label><label><input type=checkbox data-e=stopped> stops</label><label><input type=checkbox data-e=failed> fails</label></div>
    <label>Also</label><div class=sw><input type=checkbox data-n=desktop><span class=note>a notification on this Mac, while Orbit is running</span></div>
   </div>
   <div class=srvact><button class=primary data-a=save>Save</button><button class=ghost data-a=remove style="margin-left:auto">Remove this server</button></div>
   <div class=hint2 style="grid-column:auto">Folder on the cluster: <code></code></div>`;
  c.querySelector('.srvname').value=sv.label;
  c.querySelector('code').textContent=sv.host+':'+sv.dir;
  c.querySelectorAll('[data-s]').forEach(i=>{const v=S[i.dataset.s];if(i.type==='checkbox')i.checked=!!v;else i.value=String(v)});
  c.querySelector('[data-n=email]').value=N.email||'';c.querySelector('[data-n=desktop]').checked=N.desktop!==false;
  c.querySelectorAll('[data-e]').forEach(i=>i.checked=ev[i.dataset.e]!==false);
  const rows=JSON.parse(JSON.stringify(sv.schedule||[]));
  const drawRows=()=>{const host=c.querySelector('[data-r=sched]');host.innerHTML='';
   if(!rows.length)host.innerHTML='<div class=note>No schedule. Start and stop it by hand above.</div>';
   rows.forEach((r,i)=>{const row=el(`<div class=srvsched><input type=checkbox title="on"><span><small>start</small> <input type=time data-k=start></span><span><small>stop</small> <input type=time data-k=stop></span><span class=days></span><button class=ghost title="remove">×</button></div>`);
    row.querySelector('input[type=checkbox]').checked=r.enabled!==false;row.querySelector('input[type=checkbox]').onchange=e=>r.enabled=e.target.checked;
    row.querySelectorAll('[data-k]').forEach(t=>{t.value=r[t.dataset.k]||'';t.onchange=()=>r[t.dataset.k]=t.value});
    const days=row.querySelector('.days');
    if(r.on){days.innerHTML='<span class=note>only on '+esc(r.on)+'</span>'}
    else DAYS.forEach((d,k)=>{const l=el(`<label><input type=checkbox hidden><span>${d}</span></label>`);const cb=l.querySelector('input');
     cb.checked=(r.days||[0,1,2,3,4,5,6]).includes(k);l.style.background=cb.checked?'var(--hover)':'';
     cb.onchange=()=>{const cur=new Set(r.days||[0,1,2,3,4,5,6]);cb.checked?cur.add(k):cur.delete(k);r.days=[...cur].sort();l.style.background=cb.checked?'var(--hover)':''};
     days.appendChild(l)});
    row.querySelector('button').onclick=()=>{rows.splice(i,1);drawRows()};host.appendChild(row)})};
  drawRows();
  const msg=t=>{const m=c.querySelector('[data-r=msg]');m.textContent=t||''};
  const form=()=>{const st={};c.querySelectorAll('[data-s]').forEach(i=>st[i.dataset.s]=i.type==='checkbox'?i.checked:i.tagName==='SELECT'?(i.value==='true'?true:i.value==='false'?false:i.value):i.type==='datetime-local'||i.dataset.s==='exclude_nodes'||i.dataset.s==='partition'||i.dataset.s==='placement_model'?i.value:(i.value===''?undefined:Number(i.value)));
   const events={};c.querySelectorAll('[data-e]').forEach(i=>events[i.dataset.e]=i.checked);
   return {id:sv.id,label:c.querySelector('.srvname').value,settings:st,schedule:rows,
    notify:{email:c.querySelector('[data-n=email]').value,desktop:c.querySelector('[data-n=desktop]').checked,events}}};
  const run=async(label,fn)=>{msg(label);try{const j=await fn();if(j&&j.servers)data=j;msg('');return j}catch(e){msg('');c.querySelector('[data-r=msg]').innerHTML='<span class=srverr></span>';c.querySelector('.srverr').textContent=e.message}};
  c.querySelector('[data-a=addrow]').onclick=()=>{rows.push({start:'08:00',stop:'22:00',enabled:true});drawRows()};
  c.querySelector('[data-a=save]').onclick=()=>run('saving…',async()=>{const j=await api('save',form());msg('saved');setTimeout(()=>msg(''),1800);return j});
  c.querySelector('[data-a=start]').onclick=()=>run('asking the cluster…',async()=>{await api('save',form());return api('start',{id:sv.id})}).then(refresh);
  c.querySelector('[data-a=restart]').onclick=()=>{if(!confirm('Restart '+sv.label+'? Chats using it are cut off for the 5–10 minutes it takes to come back.'))return;
   run('restarting… (this takes a minute)',async()=>{await api('save',form());return api('restart',{id:sv.id})}).then(refresh)};
  c.querySelector('[data-a=log]').onclick=()=>run('reading the log…',async()=>{const j=await api('log',{id:sv.id});let b=c.querySelector('[data-r=logbox]');
   if(!b){b=el('<pre data-r=logbox class=clres style="max-height:280px;overflow:auto;white-space:pre-wrap;margin:8px 0 0"></pre>');c.appendChild(b)}
   b.textContent=j.text?('['+j.name+']\n'+j.text):'Nothing is kept yet. Start messages are kept from the next start (Server messages above), unless the full log is on.';b.scrollTop=b.scrollHeight;return j});
  c.querySelector('[data-a=bench]').onclick=()=>run('testing… (about 20 seconds)',()=>api('speed_test',{id:sv.id})).then(refresh);
  c.querySelector('[data-a=stop]').onclick=()=>{if(!confirm('Stop '+sv.label+'? Chats using it will stop getting answers.'))return;run('stopping…',()=>api('stop',{id:sv.id})).then(refresh)};
  c.querySelector('[data-a=testmail]').onclick=()=>run('sending…',async()=>{await api('save',form());const j=await api('test_email',{id:sv.id});msg('sent to '+j.to);return j});
  c.querySelector('[data-a=remove]').onclick=()=>{if(!confirm('Remove '+sv.label+' from this list? The model and its files on the cluster stay.'))return;
   run('',()=>api('remove',{id:sv.id})).then(()=>paint())};
  return c};
 const KINDS={monitor:'Orbit looking at the cluster',tunnel:'tunnel to a model',chat:'chat running on the cluster',other:'another program'};
 const conn=$('#srvconn');
 conn.innerHTML=`<div class=srvcard><div class=sec style="margin-top:0">Logins to the cluster <small>— each one is a separate login on a HPC login node</small></div>
   <div id=srvconnlist class=note></div>
   <div class=srvact><button class=ghost id=sc_close>Close Orbit's logins</button>
    <label style="display:inline-flex;gap:5px;align-items:center;font-size:var(--fs-md)"><input type=checkbox id=sc_chats> also the chats running there</label>
    <span class=note id=sc_msg></span></div>
   <div class=hint2 style="grid-column:auto">Orbit looks at the cluster through one shared login, so a status check is not a new login. Closing the logins is safe: the next look
    opens a fresh one, and a model that is running on the cluster keeps running. A chat running on the cluster is cut off mid-answer, so that is a separate tick. Logins of other programs are listed but never touched.</div></div>`;
 const drawConn=()=>{const list=conn.querySelector('#srvconnlist'),cs=data.connections||[];
  list.innerHTML=cs.length?'':'No logins open from this Mac.';
  cs.forEach(c=>{const r=el('<div style="display:flex;gap:10px;padding:2px 0"><b style="min-width:70px"></b><span></span></div>');
   r.querySelector('b').textContent='open '+c.age;r.querySelector('span').textContent=KINDS[c.kind]+(c.mine?'':' (not Orbit\'s)');
   list.appendChild(r)})};
 conn.querySelector('#sc_close').onclick=async()=>{const m=conn.querySelector('#sc_msg');
  if(conn.querySelector('#sc_chats').checked&&!confirm('This also ends the chats running on the cluster, in the middle of their answers. Continue?'))return;
  m.textContent='closing…';
  try{const j=await api('close_connections',{id:data.servers[0].id,chats:conn.querySelector('#sc_chats').checked});data=j;m.textContent=j.closed?`closed ${j.closed}`:'nothing of Orbit\'s was open';drawConn()}
  catch(e){m.textContent=e.message}};
 const paint=()=>{box.innerHTML='';data.servers.forEach(sv=>box.appendChild(card(sv)));
  const add=el(`<div class=srvcard><div class=sec style="margin-top:0">Add another model <small>— one that is already on the cluster</small></div>
   <div class=grid><label>Name</label><input type=text id=sa_name placeholder="e.g. Llama 70B">
    <label>Folder on the cluster</label><input type=text id=sa_dir placeholder="/path/to/project/…/llama — holds model/; serve.sbatch is copied in">
    <label>Served as</label><input type=text id=sa_model placeholder="model name its API answers to (default: the name)"></div>
   <div class=srvact><button class=ghost id=sa_go>Add</button><span class=note id=sa_msg></span></div></div>`);
  add.querySelector('#sa_go').onclick=async()=>{try{data=await api('add',{label:add.querySelector('#sa_name').value,dir:add.querySelector('#sa_dir').value,model:add.querySelector('#sa_model').value});paint()}
   catch(e){add.querySelector('#sa_msg').textContent=e.message}};
  box.appendChild(add);fill()};
 // the live part (state, numbers) is redrawn every few seconds; the forms are left alone so typing is not lost
 const fill=()=>{drawConn();data.servers.forEach(sv=>{const c=box.querySelector(`.srvcard[data-id="${CSS.escape(sv.id)}"]`);if(!c)return;
  const st=sv.status||{};c.querySelector('.srvlive').innerHTML=live(sv);
  c.querySelector('.srvlive .srvstate').className='srvstate '+st.state;
  const busy=['queued','loading','ready','stopping'].includes(st.state);
  c.querySelector('[data-a=start]').disabled=busy;c.querySelector('[data-a=stop]').disabled=!busy||st.state==='stopping';
  c.querySelector('[data-a=restart]').disabled=!busy||st.state==='stopping';
  c.querySelector('[data-a=bench]').disabled=st.state!=='ready'})};
 const refresh=async()=>{try{data=await api('list')}catch(e){return}if($('#srvbox'))fill()};
 paint();
 const timer=setInterval(()=>{if(gen!==RENDER_GEN||!$('#srvbox')){clearInterval(timer);return}refresh()},4000)}
