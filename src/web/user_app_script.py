"""Client-side JS for the read-only user app (/app).

Two views: card list and per-meeting detail with segment audio player
(chunks load on demand, auto-advance), screenshot gallery with lightbox,
and the content blocks. No meeting-mutating action exists here.
"""

APP_JS = r"""
function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function fmtDate(v){if(!v)return ''; try{return new Date(v).toLocaleDateString([],{day:'numeric',month:'short'});}catch{return '';}}
function fmtTime(v){if(!v)return ''; try{return new Date(v).toLocaleTimeString([],{hour:'numeric',minute:'2-digit'});}catch{return '';}}
function fmtFull(v){if(!v)return ''; try{return new Date(v).toLocaleString([],{day:'numeric',month:'short',year:'numeric',hour:'numeric',minute:'2-digit'});}catch{return v;}}
function fmtDur(s){s=Math.max(0,Math.round(s||0)); const m=Math.floor(s/60); return `${m}:${String(s%60).padStart(2,'0')}`;}
function badge(s){const labels={delivered:'Done',failed:'Fail',scheduled:'Sched',joining:'Join',recording:'Rec',recorded:'Saved',processing:'Proc',no_one_joined:'Empty',cancelled:'Cancel'}; return `<span class="status ${esc(s)}">${esc(labels[s]||s)}</span>`;}
let debounceTimer=null;
function debouncedLoad(){clearTimeout(debounceTimer); debounceTimer=setTimeout(()=>loadMeetings(true),300);}
const PAGE_SIZE=10;
let feed={offset:0,total:null,busy:false};
function params(offset){const p=new URLSearchParams(); const q=document.getElementById('searchTitle').value.trim(); const from=document.getElementById('dateFrom').value; const to=document.getElementById('dateTo').value; const attendee=document.getElementById('attendeeFilter').value.trim(); if(q)p.set('q',q); if(from)p.set('from',from); if(to)p.set('to',to); if(attendee)p.set('attendee',attendee); p.set('limit',String(PAGE_SIZE)); p.set('offset',String(offset)); return p.toString();}
function cardHtml(m){return `<div class="mcard" onclick="openDetail('${esc(m.meet_code)}')">
<div class="mcard-top"><span class="mcard-title">${esc(m.title)}</span>${badge(m.status)}</div>
<div class="mcard-meta"><span>${fmtDate(m.scheduled_start_utc)} &middot; ${fmtTime(m.scheduled_start_utc)}${m.scheduled_end_utc?'-'+fmtTime(m.scheduled_end_utc):''}</span><span>${esc(m.organizer||'')}</span></div>
</div>`;}
async function loadMeetings(reset=true){if(feed.busy)return; feed.busy=true;
try{const offset=reset?0:feed.offset; const r=await fetch('/api/meetings?'+params(offset),{cache:'no-store'}); if(r.status===401){window.location='/login'; return;} const d=await r.json(); const el=document.getElementById('cards');
if(reset){el.innerHTML=''; feed={offset:0,total:null,busy:true};}
feed.total=d.pagination.total; feed.offset=offset+d.meetings.length;
if(!feed.offset){el.innerHTML='<div class="empty">No meetings.</div>';}
else{el.insertAdjacentHTML('beforeend',d.meetings.map(cardHtml).join(''));}
document.getElementById('moreStatus').textContent=feed.offset<feed.total?'':'';
}finally{feed.busy=false;}}
const sentinel=document.getElementById('moreSentinel');
new IntersectionObserver(entries=>{if(entries.some(e=>e.isIntersecting)&&feed.total!==null&&feed.offset<feed.total)loadMeetings(false);},{rootMargin:'300px'}).observe(sentinel);
const VIEWS=['listView','detailView','keysView','passwordView'];
function showView(id){stopAudio(); for(const v of VIEWS)document.getElementById(v).style.display=v===id?'':'none'; window.scrollTo(0,0);}
function showList(){showView('listView');}
function toggleMenu(event){event.stopPropagation(); const p=document.getElementById('menuPanel'); p.style.display=p.style.display==='none'?'':'none';}
document.addEventListener('click',e=>{const p=document.getElementById('menuPanel'); if(p.style.display!=='none'&&!e.target.closest('.menu'))p.style.display='none';});
function openPage(page,push=true){document.getElementById('menuPanel').style.display='none'; if(push)history.pushState({page},'','?page='+page); if(page==='keys'){showView('keysView'); loadKeys();} else if(page==='password'){showView('passwordView');} else showList();}
function openDetail(code,push=true){if(push)history.pushState({code},'','?meeting='+encodeURIComponent(code)); renderDetail(code);}
async function renderDetail(code){showView('detailView'); document.getElementById('detailCode').textContent=code; document.getElementById('detail').innerHTML='<div class="empty">Loading...</div>';
const r=await fetch('/api/meetings/'+encodeURIComponent(code),{cache:'no-store'}); if(r.status===401){window.location='/login'; return;} const d=await r.json(); if(d.error){document.getElementById('detail').innerHTML=`<div class="empty">${esc(d.error)}</div>`; return;} const m=d.meeting; currentDetail=m;
const row=(k,v)=>v?`<div><span class="muted">${k}</span><span>${v}</span></div>`:'';
const block=(title,content)=>content?`<div class="code-block"><div class="code-head"><h3>${title}</h3></div><pre>${esc(content)}</pre></div>`:'';
document.getElementById('detail').innerHTML=`<h2 style="margin:10px 0">${esc(m.title)}</h2>
<div class="detail-meta">
${row('Status',badge(m.status))}
${row('Start',esc(fmtFull(m.scheduled_start_utc)))}
${row('End',esc(fmtFull(m.scheduled_end_utc)))}
${row('Host',esc(m.organizer||''))}
${row('Attendees',(m.metadata.attendees||[]).map(esc).join(', '))}
</div>
${audioSection(m)}${screenshotSection(m)}
${block('Meeting Minutes',m.meeting_minutes)}${block('Summary',m.summary)}${block('Transcript',m.transcript)}
${!m.meeting_minutes&&!m.summary&&!m.transcript?'<div class="empty">No content yet.</div>':''}`;}
// ---- audio: segments stream on demand, one chunk at a time ----
let currentDetail=null, audioState=null;
function audioSegs(m){return (m.files?.audio_segments||[]).filter(f=>f?.exists&&f?.size>0);}
function audioSection(m){const segs=audioSegs(m); if(!segs.length)return ''; const total=segs.reduce((a,s)=>a+(s.duration_seconds||0),0);
return `<div class="code-block"><div class="code-head"><h3>Audio &middot; ${segs.length} part${segs.length>1?'s':''}${total?' &middot; '+fmtDur(total):''}</h3><button onclick="initAudio()">Load audio</button></div>
<div id="audioBox" style="display:none;padding:10px 12px">
<audio id="player" controls preload="none" style="width:100%"></audio>
<div id="segChips" class="chips"></div>
<div class="chips"><span class="muted" style="align-self:center">Speed</span>
<button class="chip rate active" onclick="setRate(1,this)">x1</button>
<button class="chip rate" onclick="setRate(1.5,this)">x1.5</button>
<button class="chip rate" onclick="setRate(2,this)">x2</button></div>
<div class="muted" style="font-size:12px">Each part streams only when played; parts continue automatically.</div>
</div></div>`;}
function initAudio(){const m=currentDetail; if(!m)return; const segs=audioSegs(m); audioState={code:m.meet_code,segs,idx:-1,rate:1};
document.getElementById('audioBox').style.display=''; const chips=document.getElementById('segChips');
chips.innerHTML=segs.map((s,i)=>`<button class="chip seg" onclick="playSeg(${i})">P${i+1}${s.duration_seconds?`<span>${fmtDur(s.duration_seconds)}</span>`:''}</button>`).join('');
const player=document.getElementById('player');
player.onended=()=>{if(audioState&&audioState.idx+1<audioState.segs.length)playSeg(audioState.idx+1,true);};
playSeg(0,false);}
function playSeg(i,autoplay=true){if(!audioState)return; const seg=audioState.segs[i]; if(!seg)return; audioState.idx=i;
const player=document.getElementById('player');
player.src=`/api/meetings/${encodeURIComponent(audioState.code)}/audio?index=${seg.index??i}`;
player.playbackRate=audioState.rate; player.load(); if(autoplay)player.play().catch(()=>{});
document.querySelectorAll('.chip.seg').forEach((b,k)=>b.classList.toggle('active',k===i));}
function setRate(rate,btn){if(audioState)audioState.rate=rate; const player=document.getElementById('player'); if(player)player.playbackRate=rate; document.querySelectorAll('.chip.rate').forEach(b=>b.classList.toggle('active',b===btn));}
function stopAudio(){const player=document.getElementById('player'); if(player){player.pause(); player.removeAttribute('src');} audioState=null;}
// ---- screenshots: lazy strip + lightbox ----
function shots(m){return (m.files?.screenshots||[]).filter(f=>f?.exists&&f?.size>0);}
function shotSrc(code,index){return `/api/meetings/${encodeURIComponent(code)}/screenshots?index=${encodeURIComponent(index)}`;}
function screenshotSection(m){const list=shots(m); if(!list.length)return '';
return `<div class="code-block"><div class="code-head"><h3>Screenshots &middot; ${list.length}</h3></div>
<div class="shots">${list.map((s,i)=>`<button class="shot" onclick="openShot(${i})"><img loading="lazy" src="${shotSrc(m.meet_code,s.index??i)}" alt="Screenshot ${i+1}"><span>${i+1}</span></button>`).join('')}</div></div>`;}
let shotState=null;
function openShot(i){const m=currentDetail; const list=shots(m); if(!list.length)return; shotState={code:m.meet_code,list,idx:Math.min(i,list.length-1)}; renderShot(); document.body.classList.add('lightbox-open');}
function renderShot(){let root=document.getElementById('shotBox'); if(!root){root=document.createElement('div'); root.id='shotBox'; root.className='lightbox'; root.onclick=e=>{if(e.target===root)closeShot();}; document.body.appendChild(root);}
const s=shotState.list[shotState.idx];
root.innerHTML=`<div class="lightbox-top"><span class="lightbox-count">${shotState.idx+1} / ${shotState.list.length}</span><button class="lightbox-close" onclick="closeShot()">x</button></div>
<button class="lightbox-prev" onclick="moveShot(-1)">&lt;</button>
<img class="lightbox-img" src="${shotSrc(shotState.code,s.index??shotState.idx)}" alt="Screenshot">
<button class="lightbox-next" onclick="moveShot(1)">&gt;</button>`;
root.classList.add('open');}
function moveShot(delta){if(!shotState)return; const n=shotState.list.length; shotState.idx=(shotState.idx+delta+n)%n; renderShot();}
function closeShot(){document.getElementById('shotBox')?.classList.remove('open'); document.body.classList.remove('lightbox-open'); shotState=null;}
// ---- API key self-management (session-only endpoints) ----
async function loadKeys(){const r=await fetch('/api/keys',{cache:'no-store'}); const d=await r.json(); const el=document.getElementById('keysList'); if(d.error){el.innerHTML=`<div class="empty">${esc(d.error)}</div>`; return;}
if(!d.keys.length){el.innerHTML='<div class="empty">No API keys yet. Create one below.</div>'; return;}
el.innerHTML=d.keys.map(k=>`<div class="keyrow"><div><strong>${esc(k.name)}</strong><div class="muted" style="font-size:11px">created ${esc(String(k.created_at||'').slice(0,10))} &middot; ${k.expires_at?'expires '+esc(String(k.expires_at).slice(0,10)):'never expires'}</div></div><button class="danger" onclick="revokeKey(${k.id})">Revoke</button></div>`).join('');}
async function createKey(){const name=document.getElementById('keyName').value.trim(); const days=document.getElementById('keyExpiry').value;
const r=await fetch('/api/keys',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name,expires_days:days?Number(days):null})});
const d=await r.json(); if(d.error){alert(d.error); return;}
document.getElementById('keyName').value='';
const mcpUrl=location.origin+'/mcp';
document.getElementById('newKeyOut').innerHTML=[
 keyBlock('API key (shown once, copy now)',d.api_key),
 keyBlock('Claude Code',`claude mcp add --transport http meeting-assistant ${mcpUrl} --header "Authorization: Bearer ${d.api_key}"`),
 keyBlock('Codex (~/.codex/config.toml)',`[mcp_servers.meeting-assistant]\nurl = "${mcpUrl}"\nbearer_token = "${d.api_key}"`),
].join('');
loadKeys();}
function keyBlock(title,content){return `<div class="code-block"><div class="code-head"><h3>${esc(title)}</h3><button onclick="copyKeyText(this)">Copy</button></div><pre style="max-height:120px">${esc(content)}</pre></div>`;}
async function copyKeyText(btn){const text=btn.closest('.code-block').querySelector('pre').textContent; try{await navigator.clipboard.writeText(text);}catch{const ta=document.createElement('textarea'); ta.value=text; document.body.appendChild(ta); ta.select(); document.execCommand('copy'); ta.remove();} btn.textContent='Copied'; setTimeout(()=>btn.textContent='Copy',1500);}
async function revokeKey(id){if(!confirm('Revoke this key? Clients using it stop working immediately.'))return; const r=await fetch(`/api/keys/${id}/revoke`,{method:'POST'}); const d=await r.json(); if(d.error){alert(d.error); return;} loadKeys();}
// ---- boot ----
function clearFilters(){for(const id of ['searchTitle','dateFrom','dateTo','attendeeFilter'])document.getElementById(id).value=''; loadMeetings(true);}
function route(){const params=new URLSearchParams(location.search); const code=params.get('meeting'); const page=params.get('page'); if(code)renderDetail(code); else if(page)openPage(page,false); else showList();}
window.addEventListener('popstate',route);
loadMeetings(true).then(route);
"""
