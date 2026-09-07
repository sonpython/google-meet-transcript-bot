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
.chips{display:flex;flex-wrap:wrap;gap:6px;margin:10px 0}
.chip{height:30px;padding:0 10px;border-radius:999px;font-size:12px;display:inline-flex;align-items:center;gap:5px}
.chip span{color:#94a3b8;font-family:ui-monospace,Menlo,monospace;font-size:10px}
.chip.active{background:#0c4a6e;border-color:#0284c7;color:#e0f2fe}
.chip.active span{color:#bae6fd}
.shots{display:flex;gap:8px;overflow-x:auto;padding:10px 12px;scroll-snap-type:x mandatory}
.shot{flex:0 0 150px;height:92px;padding:0;border-radius:7px;overflow:hidden;position:relative;background:#050914;border:1px solid #334155;scroll-snap-align:start;cursor:pointer}
.shot img{width:100%;height:100%;object-fit:cover;display:block}
.shot span{position:absolute;left:6px;bottom:6px;min-width:22px;height:18px;display:inline-flex;align-items:center;justify-content:center;border-radius:999px;background:rgba(15,23,42,.78);color:#e5e7eb;font-size:11px}
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
<script>{APP_JS}</script></body></html>"""

