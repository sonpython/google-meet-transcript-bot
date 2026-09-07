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
function debouncedLoad(){clearTimeout(debounceTimer); debounceTimer=setTimeout(loadMeetings,300);}
function params(){const p=new URLSearchParams(); const q=document.getElementById('searchTitle').value.trim(); const from=document.getElementById('dateFrom').value; const to=document.getElementById('dateTo').value; const attendee=document.getElementById('attendeeFilter').value.trim(); if(q)p.set('q',q); if(from)p.set('from',from); if(to)p.set('to',to); if(attendee)p.set('attendee',attendee); p.set('limit','200'); return p.toString();}
async function loadMeetings(){const r=await fetch('/api/meetings?'+params(),{cache:'no-store'}); if(r.status===401){window.location='/login'; return;} const d=await r.json(); const el=document.getElementById('cards'); if(!d.meetings.length){el.innerHTML='<div class="empty">No meetings.</div>'; return;}
el.innerHTML=d.meetings.map(m=>`<div class="mcard" onclick="openDetail('${esc(m.meet_code)}')">
<div class="mcard-top"><span class="mcard-title">${esc(m.title)}</span>${badge(m.status)}</div>
<div class="mcard-meta"><span>${fmtDate(m.scheduled_start_utc)} &middot; ${fmtTime(m.scheduled_start_utc)}${m.scheduled_end_utc?'-'+fmtTime(m.scheduled_end_utc):''}</span><span>${esc(m.organizer||'')}</span></div>
</div>`).join('');}
function showList(){stopAudio(); document.getElementById('detailView').style.display='none'; document.getElementById('listView').style.display='';}
function openDetail(code,push=true){if(push)history.pushState({code},'','?meeting='+encodeURIComponent(code)); renderDetail(code);}
async function renderDetail(code){document.getElementById('listView').style.display='none'; document.getElementById('detailView').style.display=''; document.getElementById('detailCode').textContent=code; document.getElementById('detail').innerHTML='<div class="empty">Loading...</div>'; window.scrollTo(0,0);
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
// ---- boot ----
function clearFilters(){for(const id of ['searchTitle','dateFrom','dateTo','attendeeFilter'])document.getElementById(id).value=''; loadMeetings();}
window.addEventListener('popstate',()=>{const code=new URLSearchParams(location.search).get('meeting'); if(code)renderDetail(code); else showList();});
const initial=new URLSearchParams(location.search).get('meeting');
loadMeetings().then(()=>{if(initial)openDetail(initial,false);});
"""
