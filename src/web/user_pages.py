"""HTML for the regular-user pages: login form and the read-only meeting app.

The app is a two-view mobile-first page: a card list of meetings, and a
detail view opened per meeting (history-aware so the phone back button
works). It must never render meeting-mutating controls (delete, rejoin,
force-out, regenerate) and reads the existing /api/* endpoints with the
session cookie.
"""

import html

from src.web.styles import CSS
from src.web.user_app_script import APP_JS

# Overrides the shared admin stylesheet for the user app: single-column,
# card-based, no fixed grid columns that overflow on narrow screens.
_APP_CSS = """<style>
main{max-width:760px;margin:0 auto;padding:14px;display:flex;flex-direction:column;gap:12px}
header{position:sticky;top:0;z-index:5}
.searchbar{display:flex;gap:8px}
.searchbar input{flex:1;min-width:0}
.filter-row{display:grid;grid-template-columns:84px 1fr;align-items:center;gap:8px;margin-bottom:8px}
.filter-row label{color:#94a3b8;font-size:13px}
.filter-row input{width:100%;min-width:0;max-width:100%}
/* iOS Safari gives date inputs an intrinsic width that ignores width:100%
   unless the native appearance is disabled */
.filter-row input[type=date]{-webkit-appearance:none;appearance:none;display:block;box-sizing:border-box;padding:0 8px;font-size:14px;line-height:30px;color:#e5e7eb;background:#182235}
#filterBtn.active{background:#0c4a6e;border-color:#0284c7;color:#e0f2fe}
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
.chips{display:flex;flex-wrap:wrap;gap:6px;margin:10px 0}
.keyrow{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:8px 0;border-bottom:1px solid #1d2736}
.menu{position:relative}
#gearBtn{font-size:17px;width:38px;padding:0}
.menu-panel{position:absolute;right:0;top:40px;z-index:30;display:flex;flex-direction:column;gap:6px;min-width:200px;background:#0f172a;border:1px solid #334155;border-radius:8px;padding:10px;box-shadow:0 14px 40px rgba(0,0,0,.4)}
.menu-panel button{width:100%;text-align:left}
.menu-email{font-size:12px;padding:2px 4px 6px;border-bottom:1px solid #263244;overflow-wrap:anywhere}
.chip{height:30px;padding:0 10px;border-radius:999px;font-size:12px;display:inline-flex;align-items:center;gap:5px}
.chip span{color:#94a3b8;font-family:ui-monospace,Menlo,monospace;font-size:10px}
.chip.active{background:#0c4a6e;border-color:#0284c7;color:#e0f2fe}
.chip.active span{color:#bae6fd}
.shots{display:flex;gap:8px;overflow-x:auto;padding:10px 12px;scroll-snap-type:x mandatory}
.shot{flex:0 0 150px;height:92px;padding:0;border-radius:7px;overflow:hidden;position:relative;background:#050914;border:1px solid #334155;scroll-snap-align:start;cursor:pointer}
.shot img{width:100%;height:100%;object-fit:cover;display:block}
.shot span{position:absolute;left:6px;bottom:6px;min-width:22px;height:18px;display:inline-flex;align-items:center;justify-content:center;border-radius:999px;background:rgba(15,23,42,.78);color:#e5e7eb;font-size:11px}
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
<body><header><h1>Meetings</h1>
<div class="menu"><button id="gearBtn" onclick="toggleMenu(event)" aria-label="Menu">&#9881;</button>
<div id="menuPanel" class="menu-panel" style="display:none">
<div class="menu-email muted">{email}</div>
<button onclick="openPage('keys')">API keys</button>
<button onclick="openPage('password')">Change password</button>
<form method="post" action="/logout-user" style="margin:0"><button class="danger" type="submit" style="width:100%">Logout</button></form>
</div></div></header>

<main id="listView">
<div class="searchbar">
<input id="searchTitle" placeholder="Search title..." autocomplete="off" oninput="debouncedLoad()">
<button id="filterBtn" onclick="toggleFilters()">Filters</button>
</div>
<section id="filterPanel" class="panel" style="display:none;padding:12px 14px">
<div class="filter-row"><label for="attendeeFilter">Attendee</label>
<input id="attendeeFilter" placeholder="Email (empty = everyone's meetings)" value="{email}" autocomplete="off" oninput="debouncedLoad();updateFilterBtn()"></div>
<div class="filter-row"><label for="dateFrom">From</label><input id="dateFrom" type="date" onchange="loadMeetings();updateFilterBtn()"></div>
<div class="filter-row"><label for="dateTo">To</label><input id="dateTo" type="date" onchange="loadMeetings();updateFilterBtn()"></div>
<div class="chips" style="margin-bottom:0">
<button onclick="setAttendee('{email}')">My meetings</button>
<button onclick="setAttendee('')">Everyone</button>
<button class="danger" onclick="clearFilters()">Clear all</button>
</div>
</section>
<div id="cards"><div class="empty">Loading...</div></div>
<div id="moreSentinel" style="height:1px"></div><div id="moreStatus" class="empty"></div>
</main>

<main id="detailView" style="display:none">
<div class="backbar"><button onclick="history.back()">&#8592; Back</button><span id="detailCode" class="muted"></span></div>
<div id="detail"></div>
</main>

<main id="keysView" style="display:none">
<div class="backbar"><button onclick="history.back()">&#8592; Back</button><h2 style="margin:0">API keys</h2></div>
<section class="panel" style="padding:12px 14px">
<p class="muted" style="font-size:12px;margin:6px 0">Personal keys for Claude Code, Codex, or the REST API. A key is shown once at creation. Revoking cuts access immediately.</p>
<div id="keysList"></div>
<div class="chips" style="align-items:center">
<input id="keyName" placeholder="Key name (e.g. laptop, codex)" autocomplete="off" style="flex:1;min-width:140px">
<select id="keyExpiry" style="height:32px;background:#182235;color:#e5e7eb;border:1px solid #334155;border-radius:6px">
<option value="">Never expires</option>
<option value="7">7 days</option>
<option value="30">30 days</option>
<option value="90">90 days</option>
</select>
<button onclick="createKey()">Create key</button>
</div>
<div id="newKeyOut"></div>
</section>
</main>

<main id="passwordView" style="display:none">
<div class="backbar"><button onclick="history.back()">&#8592; Back</button><h2 style="margin:0">Change password</h2></div>
<section class="panel" style="padding:14px">
<form method="post" action="/account/password" style="display:flex;flex-direction:column;gap:10px;max-width:420px">
<input name="current_password" type="password" placeholder="Current password" autocomplete="current-password" required>
<input name="new_password" type="password" placeholder="New password (min 10 chars)" autocomplete="new-password" minlength="10" required>
<button type="submit">Change password</button>
</form>
</section>
</main>
<script>{APP_JS}</script></body></html>"""

