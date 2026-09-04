"""HTML for the regular-user pages: login form and the read-only meeting app.

The app page is read-only by design: it must never render meeting-mutating
controls (delete, rejoin, force-out, regenerate). It reads the existing
/api/* endpoints with the session cookie.
"""

import html

from src.web.styles import CSS


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
<title>Meeting Assistant</title>{CSS}</head>
<body><header><h1>Meeting Assistant</h1><div class="header-actions"><span class="muted">{email}</span>
<button onclick="const b=document.getElementById('pwBox'); b.style.display=b.style.display==='none'?'':'none'">Password</button>
<form method="post" action="/logout-user" style="margin:0"><button class="danger" type="submit">Logout</button></form></div></header>
<main>
<section id="pwBox" class="panel settings-panel" style="display:none">
<div class="panel-head"><h2>Change password</h2></div>
<form class="settings-row" method="post" action="/account/password">
<label for="currentPassword">Current password</label>
<input id="currentPassword" name="current_password" type="password" autocomplete="current-password" required>
<label for="newPassword">New password (min 10 chars)</label>
<input id="newPassword" name="new_password" type="password" autocomplete="new-password" minlength="10" required>
<button type="submit">Change</button><span></span>
</form></section>
<section class="grid"><div class="panel history-panel">
<h2>History</h2>
<div class="filters">
<label class="sr-only" for="searchTitle">Search title</label><input id="searchTitle" placeholder="Search title..." autocomplete="off" oninput="debouncedLoad()">
<label class="sr-only" for="dateFrom">From date</label><input id="dateFrom" type="date" onchange="loadMeetings()">
<label class="sr-only" for="dateTo">To date</label><input id="dateTo" type="date" onchange="loadMeetings()">
<button onclick="clearFilters()">Clear</button>
</div>
<div class="filters" style="grid-template-columns:minmax(0,1fr) auto">
<label class="sr-only" for="attendeeFilter">Attendee email</label>
<input id="attendeeFilter" placeholder="Filter by attendee email..." value="{email}" autocomplete="off" oninput="debouncedLoad()">
<button onclick="document.getElementById('attendeeFilter').value='';loadMeetings()">All meetings</button>
</div>
<div id="meetings" class="timeline"></div></div>
<div class="panel detail"><h2>Meeting Detail</h2><div id="detail" class="empty-detail">Select a meeting.</div></div>
</section></main>
<script>{_APP_JS}</script></body></html>"""


_APP_JS = r"""
function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function fmt(v){if(!v)return ''; try{const d=new Date(v); return `${d.toLocaleTimeString([],{hour:'numeric',minute:'2-digit'})} - ${d.toLocaleDateString()}`;}catch{return v;}}
function badge(s){const labels={delivered:'Done',failed:'Fail',scheduled:'Sched',joining:'Join',recording:'Rec',recorded:'Saved',processing:'Proc',no_one_joined:'Empty',cancelled:'Cancel'}; return `<span class="status ${esc(s)}">${esc(labels[s]||s)}</span>`;}
let debounceTimer=null;
function debouncedLoad(){clearTimeout(debounceTimer); debounceTimer=setTimeout(loadMeetings,300);}
function params(){const p=new URLSearchParams(); const q=document.getElementById('searchTitle').value.trim(); const from=document.getElementById('dateFrom').value; const to=document.getElementById('dateTo').value; const attendee=document.getElementById('attendeeFilter').value.trim(); if(q)p.set('q',q); if(from)p.set('from',from); if(to)p.set('to',to); if(attendee)p.set('attendee',attendee); p.set('limit','200'); return p.toString();}
async function loadMeetings(){const r=await fetch('/api/meetings?'+params(),{cache:'no-store'}); if(r.status===401){window.location='/login'; return;} const d=await r.json(); const el=document.getElementById('meetings'); if(!d.meetings.length){el.innerHTML='<div class="timeline-empty">No meetings.</div>'; return;} el.innerHTML=d.meetings.map(m=>`<div class="timeline-row" onclick="loadDetail('${esc(m.meet_code)}')"><div class="timeline-dot empty"></div><div class="timeline-time">${fmt(m.scheduled_start_utc)}</div><div class="timeline-main"><div class="timeline-title-row"><div class="timeline-title">${esc(m.title)}</div><span>${badge(m.status)}</span></div><div class="timeline-meta-row"><div class="timeline-range">${esc(m.organizer||'')}</div></div></div></div>`).join('');}
async function loadDetail(code){document.getElementById('detail').innerHTML='<div class="detail-loading"><div class="loader">Loading...</div></div>'; const r=await fetch('/api/meetings/'+encodeURIComponent(code),{cache:'no-store'}); if(r.status===401){window.location='/login'; return;} const d=await r.json(); const m=d.meeting; const kv=(k,v)=>`<div class="kv"><div class="muted">${k}</div><div>${v}</div></div>`; const block=(title,content)=>content?`<div class="code-block"><div class="code-head"><h3>${title}</h3></div><pre>${esc(content)}</pre></div>`:''; document.getElementById('detail').innerHTML=`<div class="detail-body"><h3>${esc(m.title)}</h3><div class="meta-grid">${kv('Status',badge(m.status))}${kv('Meet code',esc(m.meet_code))}${kv('Host',esc(m.organizer||''))}${kv('Attendees',(m.metadata.attendees||[]).map(esc).join('<br>')||'missing')}${kv('Start',fmt(m.scheduled_start_utc))}${kv('End',fmt(m.scheduled_end_utc))}</div>${block('Meeting Minutes',m.meeting_minutes)}${block('Summary',m.summary)}${block('Transcript',m.transcript)}</div>`;}
function clearFilters(){for(const id of ['searchTitle','dateFrom','dateTo'])document.getElementById(id).value=''; loadMeetings();}
loadMeetings();
"""
