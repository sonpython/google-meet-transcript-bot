"""Admin user management: the /admin/users page and /admin/api/users handlers.

Handlers return JSON-serializable dicts and never include password_hash or
api_key_hash. A rotated API key's plaintext appears exactly once, in the
rotate response.
"""

from pathlib import Path

from src.auth.session_store import SessionStore
from src.auth.user_store import UserStore
from src.state.db import connect
from src.web.styles import CSS


def list_users(db_path: Path) -> dict:
    conn = connect(db_path)
    try:
        rows = UserStore(conn).list_users()
        return {"users": [_public_user(row) for row in rows]}
    finally:
        conn.close()


def create_user(db_path: Path, payload: dict) -> dict:
    email = str(payload.get("email", "")).strip()
    if not email or "@" not in email:
        return {"error": "valid email required"}
    password = str(payload.get("password", "") or "")
    conn = connect(db_path)
    try:
        store = UserStore(conn)
        try:
            user_id = store.create_user(
                email,
                display_name=str(payload.get("display_name", "") or "") or None,
                password=password or None,
                is_admin=bool(payload.get("is_admin", False)),
            )
        except ValueError as exc:
            return {"error": str(exc)}
        return {"ok": True, "user": _public_user(store.get_by_id(user_id))}
    finally:
        conn.close()


def set_password(db_path: Path, user_id: int, payload: dict) -> dict:
    password = str(payload.get("password", "") or "")
    if len(password) < 10:
        return {"error": "password must be at least 10 characters"}
    conn = connect(db_path)
    try:
        store = UserStore(conn)
        if store.get_by_id(user_id) is None:
            return {"error": "user not found"}
        store.set_password(user_id, password)
        # Admin reset kills existing sessions: the holder of the old
        # password must not stay logged in.
        SessionStore(conn).delete_for_user(user_id)
        return {"ok": True}
    finally:
        conn.close()


def rotate_key(db_path: Path, user_id: int) -> dict:
    conn = connect(db_path)
    try:
        store = UserStore(conn)
        if store.get_by_id(user_id) is None:
            return {"error": "user not found"}
        return {"ok": True, "api_key": store.rotate_api_key(user_id)}
    finally:
        conn.close()


def revoke_key(db_path: Path, user_id: int) -> dict:
    conn = connect(db_path)
    try:
        store = UserStore(conn)
        if store.get_by_id(user_id) is None:
            return {"error": "user not found"}
        store.revoke_api_key(user_id)
        return {"ok": True}
    finally:
        conn.close()


def set_active(db_path: Path, user_id: int, payload: dict) -> dict:
    active = bool(payload.get("active", True))
    conn = connect(db_path)
    try:
        store = UserStore(conn)
        if store.get_by_id(user_id) is None:
            return {"error": "user not found"}
        store.set_active(user_id, active)
        if not active:
            SessionStore(conn).delete_for_user(user_id)
        return {"ok": True}
    finally:
        conn.close()


def _public_user(row) -> dict:
    return {
        "id": row["id"],
        "email": row["email"],
        "display_name": row["display_name"],
        "is_admin": bool(row["is_admin"]),
        "is_active": bool(row["is_active"]),
        "has_password": row["password_hash"] is not None,
        "has_api_key": row["api_key_hash"] is not None,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def page_html() -> str:
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Meeting Assistant Users</title>{CSS}</head>
<body><header><h1>Users</h1><div class="header-actions"><a class="button-link" href="/admin">Dashboard</a></div></header>
<main>
<section class="panel settings-panel"><div class="panel-head"><h2>Create user</h2></div>
<div class="settings-row" style="grid-template-columns:1fr 1fr 1fr auto">
<input id="newEmail" placeholder="email@domain.com" autocomplete="off">
<input id="newName" placeholder="Display name" autocomplete="off">
<input id="newPassword" placeholder="Temp password (min 10)" autocomplete="off">
<button onclick="createUser()">Create</button>
</div></section>
<section class="panel"><div class="panel-head"><h2>All users</h2><span id="msg" class="muted" aria-live="polite"></span></div>
<div id="users" style="padding:12px 14px"></div></section>
</main>
<script>{_USERS_JS}</script></body></html>"""


_USERS_JS = r"""
function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
async function api(path,opts={}){const r=await fetch('/admin/api/'+path,{cache:'no-store',...opts}); if(!r.ok)throw new Error(await r.text()); const d=await r.json(); if(d.error)throw new Error(d.error); return d;}
function say(text){const el=document.getElementById('msg'); el.textContent=text; setTimeout(()=>el.textContent='',6000);}
async function loadUsers(){const d=await api('users'); document.getElementById('users').innerHTML=`<table style="width:100%;border-collapse:collapse">`+
`<tr><th align="left">Email</th><th align="left">Name</th><th>Admin</th><th>Active</th><th>Password</th><th>API key</th><th align="left">Actions</th></tr>`+
d.users.map(u=>`<tr style="border-top:1px solid #263244"><td>${esc(u.email)}</td><td>${esc(u.display_name||'')}</td><td align="center">${u.is_admin?'yes':''}</td><td align="center">${u.is_active?'yes':'no'}</td><td align="center">${u.has_password?'set':'-'}</td><td align="center">${u.has_api_key?'set':'-'}</td><td>
<button onclick="resetPassword(${u.id})">Reset pw</button>
<button onclick="rotateKey(${u.id})">New API key</button>
${u.has_api_key?`<button onclick="revokeKey(${u.id})">Revoke key</button>`:''}
<button class="danger" onclick="setActive(${u.id},${u.is_active?'false':'true'})">${u.is_active?'Deactivate':'Activate'}</button>
</td></tr>`).join('')+`</table>`;}
async function createUser(){const email=document.getElementById('newEmail').value.trim(); const name=document.getElementById('newName').value.trim(); const pw=document.getElementById('newPassword').value; try{await api('users',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email,display_name:name,password:pw})}); say('User created'); for(const id of ['newEmail','newName','newPassword'])document.getElementById(id).value=''; await loadUsers();}catch(e){say('Error: '+e.message);}}
async function resetPassword(id){const pw=prompt('New temp password (min 10 chars):'); if(!pw)return; try{await api(`users/${id}/password`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({password:pw})}); say('Password set');}catch(e){say('Error: '+e.message);}}
async function rotateKey(id){try{const d=await api(`users/${id}/rotate-key`,{method:'POST'}); prompt('API key (shown once, copy now):',d.api_key); await loadUsers();}catch(e){say('Error: '+e.message);}}
async function revokeKey(id){if(!confirm('Revoke this API key?'))return; try{await api(`users/${id}/revoke-key`,{method:'POST'}); say('Key revoked'); await loadUsers();}catch(e){say('Error: '+e.message);}}
async function setActive(id,active){try{await api(`users/${id}/active`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({active})}); await loadUsers();}catch(e){say('Error: '+e.message);}}
loadUsers();
"""
