"""HTML for the regular-user pages: login form and the read-only meeting app.

The app is a two-view mobile-first page: a card list of meetings, and a
detail view opened per meeting (history-aware so the phone back button
works). It must never render meeting-mutating controls (delete, rejoin,
force-out, regenerate) and reads the existing /api/* endpoints with the
session cookie.
"""

import html

from src.web.styles import CSS

# Overrides the shared admin stylesheet for the user app: single-column,
# card-based, no fixed grid columns that overflow on narrow screens.
_APP_CSS = """<style>
main{max-width:760px;margin:0 auto;padding:14px;display:flex;flex-direction:column;gap:12px}
header{position:sticky;top:0;z-index:5}
.filters-stack{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.filters-stack input{min-width:0;width:100%}
.filters-stack .full{grid-column:1/-1}
.mcard{background:#0f172a;border:1px solid #263244;border-radius:10px;padding:12px 14px;cursor:pointer}
.mcard:active,.mcard:hover{background:#141d2d;border-color:#38bdf8}
.mcard-top{display:flex;align-items:flex-start;justify-content:space-between;gap:10px}
.mcard-title{font-size:15px;font-weight:700;color:#f3f4f6;overflow-wrap:anywhere}
.mcard-meta{margin-top:6px;color:#94a3b8;font-size:12px;display:flex;flex-wrap:wrap;gap:4px 10px}
.detail-meta{display:flex;flex-direction:column;gap:6px;font-size:13px}
.detail-meta div{display:flex;gap:8px;flex-wrap:wrap}
.detail-meta .muted{min-width:84px}
#detailView h2{overflow-wrap:anywhere}
pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:60vh}
.backbar{display:flex;align-items:center;gap:10px}
.empty{color:#94a3b8;padding:20px;text-align:center}
@media(min-width:700px){.filters-stack{grid-template-columns:2fr 1fr 1fr auto}}
</style>"""


def login_html(error: str = "") -> str:
    error_html = f'<p class="error">{html.escape(error)}</p>' if error else ""
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Meeting Assistant Login</title>{CSS}</head>
<body><div class="login"><form class="login-box" method="post" action="/login">
<h1>Meeting Assistant</h1>
{error_html}
<label class="sr-only" for="email">Email</label>
<input id="email" name="email" type="email" placeholder="Email" autocomplete="username" required autofocus>
<label class="sr-only" for="password">Password</label>
<input id="password" name="password" type="password" placeholder="Password" autocomplete="current-password" required>
<button type="submit">Sign in</button>
</form></div></body></html>"""


def app_html(user_email: str) -> str:
    email = html.escape(user_email)
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Meeting Assistant</title>{CSS}{_APP_CSS}</head>
<body><header><h1>Meetings</h1><div class="header-actions"><span class="muted" id="whoami">{email}</span>
<button onclick="const b=document.getElementById('pwBox'); b.style.display=b.style.display==='none'?'':'none'">Password</button>
<form method="post" action="/logout-user" style="margin:0"><button class="danger" type="submit">Logout</button></form></div></header>

<main id="listView">
<section id="pwBox" class="panel" style="display:none;padding:12px 14px">
<form method="post" action="/account/password" style="display:flex;flex-direction:column;gap:8px">
<strong>Change password</strong>
<input name="current_password" type="password" placeholder="Current password" autocomplete="current-password" required>
<input name="new_password" type="password" placeholder="New password (min 10 chars)" autocomplete="new-password" minlength="10" required>
<button type="submit">Change password</button>
</form></section>
<div class="filters-stack">
<input id="searchTitle" class="full" placeholder="Search title..." autocomplete="off" oninput="debouncedLoad()">
<input id="dateFrom" type="date" onchange="loadMeetings()">
<input id="dateTo" type="date" onchange="loadMeetings()">
<button onclick="clearFilters()">Clear</button>
<input id="attendeeFilter" class="full" placeholder="Filter by attendee email (empty = all meetings)" value="{email}" autocomplete="off" oninput="debouncedLoad()">
</div>
<div id="cards"><div class="empty">Loading...</div></div>
</main>

<main id="detailView" style="display:none">
<div class="backbar"><button onclick="history.back()">&#8592; Back</button><span id="detailCode" class="muted"></span></div>
<div id="detail"></div>
</main>
<script>{_APP_JS}</script></body></html>"""


_APP_JS = r"""
function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function fmtDate(v){if(!v)return ''; try{const d=new Date(v); return d.toLocaleDateString([],{day:'numeric',month:'short'});}catch{return '';}}
function fmtTime(v){if(!v)return ''; try{return new Date(v).toLocaleTimeString([],{hour:'numeric',minute:'2-digit'});}catch{return '';}}
function fmtFull(v){if(!v)return ''; try{const d=new Date(v); return d.toLocaleString([],{day:'numeric',month:'short',year:'numeric',hour:'numeric',minute:'2-digit'});}catch{return v;}}
function badge(s){const labels={delivered:'Done',failed:'Fail',scheduled:'Sched',joining:'Join',recording:'Rec',recorded:'Saved',processing:'Proc',no_one_joined:'Empty',cancelled:'Cancel'}; return `<span class="status ${esc(s)}">${esc(labels[s]||s)}</span>`;}
let debounceTimer=null;
function debouncedLoad(){clearTimeout(debounceTimer); debounceTimer=setTimeout(loadMeetings,300);}
function params(){const p=new URLSearchParams(); const q=document.getElementById('searchTitle').value.trim(); const from=document.getElementById('dateFrom').value; const to=document.getElementById('dateTo').value; const attendee=document.getElementById('attendeeFilter').value.trim(); if(q)p.set('q',q); if(from)p.set('from',from); if(to)p.set('to',to); if(attendee)p.set('attendee',attendee); p.set('limit','200'); return p.toString();}
async function loadMeetings(){const r=await fetch('/api/meetings?'+params(),{cache:'no-store'}); if(r.status===401){window.location='/login'; return;} const d=await r.json(); const el=document.getElementById('cards'); if(!d.meetings.length){el.innerHTML='<div class="empty">No meetings.</div>'; return;}
el.innerHTML=d.meetings.map(m=>`<div class="mcard" onclick="openDetail('${esc(m.meet_code)}')">
<div class="mcard-top"><span class="mcard-title">${esc(m.title)}</span>${badge(m.status)}</div>
<div class="mcard-meta"><span>${fmtDate(m.scheduled_start_utc)} &middot; ${fmtTime(m.scheduled_start_utc)}${m.scheduled_end_utc?'-'+fmtTime(m.scheduled_end_utc):''}</span><span>${esc(m.organizer||'')}</span></div>
</div>`).join('');}
function showList(){document.getElementById('detailView').style.display='none'; document.getElementById('listView').style.display='';}
function openDetail(code,push=true){if(push)history.pushState({code},'','?meeting='+encodeURIComponent(code)); renderDetail(code);}
async function renderDetail(code){document.getElementById('listView').style.display='none'; document.getElementById('detailView').style.display=''; document.getElementById('detailCode').textContent=code; document.getElementById('detail').innerHTML='<div class="empty">Loading...</div>'; window.scrollTo(0,0);
const r=await fetch('/api/meetings/'+encodeURIComponent(code),{cache:'no-store'}); if(r.status===401){window.location='/login'; return;} const d=await r.json(); if(d.error){document.getElementById('detail').innerHTML=`<div class="empty">${esc(d.error)}</div>`; return;} const m=d.meeting;
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
${block('Meeting Minutes',m.meeting_minutes)}${block('Summary',m.summary)}${block('Transcript',m.transcript)}
${!m.meeting_minutes&&!m.summary&&!m.transcript?'<div class="empty">No content yet.</div>':''}`;}
function clearFilters(){for(const id of ['searchTitle','dateFrom','dateTo','attendeeFilter'])document.getElementById(id).value=''; loadMeetings();}
window.addEventListener('popstate',()=>{const code=new URLSearchParams(location.search).get('meeting'); if(code)renderDetail(code); else showList();});
const initial=new URLSearchParams(location.search).get('meeting');
loadMeetings().then(()=>{if(initial)openDetail(initial,false);});
"""
