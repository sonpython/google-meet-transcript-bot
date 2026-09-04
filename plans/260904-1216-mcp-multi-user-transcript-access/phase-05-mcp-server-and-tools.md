# Phase 05 - MCP server and tools

## Context Links

- Design: brainstorm Phase C and decisions D3, D5
- Reusable query helpers from phase 02: `src/state/meeting_queries.py`
- Auth primitives from phase 01: `src/auth/api_key.py`, `src/auth/user_store.py`
- DB connect and WAL: `src/state/db.py:60-66`
- Existing payload shape to mirror: `src/health_server.py:379` (`_api_meeting_payload`)
- Dependency list: `pyproject.toml:7-19`

## Overview

- Priority: P2
- Status: done
- Effort: 3h
- A second process serving MCP over streamable HTTP on port 18081, four read-only tools, per-user API key auth in front of the ASGI app. No writes to the database, ever.

## Key Insights, verified against the mcp 2.1.1 wheel

- `mcp` latest on PyPI is 2.1.1 and requires Python 3.10 or newer. It pulls `starlette`, `uvicorn`, `sse-starlette`, `pydantic>=2.12`, `httpx2`, `pyjwt[crypto]`, `jsonschema`, `python-multipart`, `opentelemetry-api`, `mcp-types` as direct dependencies. Uvicorn needs no extra.
- FastMCP no longer exists under that name in v2. `mcp/server/fastmcp.py` in the wheel raises `ModuleNotFoundError` with a migration message: the class is now `from mcp.server.mcpserver import MCPServer`. Every v1 snippet found online will not import. This is a rename of the same component chosen in D5, not a design change.
- `MCPServer.streamable_http_app(...)` returns a Starlette app whose lifespan runs the session manager (`mcp/server/lowlevel/server.py:823-829`). Any wrapper must pass `scope["type"] == "lifespan"` through untouched or the server will not start.
- Trap: `streamable_http_app` defaults to `host="127.0.0.1"`, and when the host is a loopback name it auto-enables DNS rebinding protection with `allowed_hosts=["127.0.0.1:*", "localhost:*", "[::1]:*"]` (`mcp/server/lowlevel/server.py:734-740`). Behind cloudflared the `Host` header is the public hostname, so requests would be rejected. Pass `transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False)` explicitly.
- Trap: passing `token_verifier=` without `auth=AuthSettings(...)` produces a server that answers 401 to everything. The bearer backend is only installed when `auth` is truthy (`mcp/server/lowlevel/server.py:762-773`), while the route is still wrapped in `RequireAuthMiddleware`, which rejects any request whose scope has no authenticated user (`mcp/server/auth/middleware/bearer_auth.py:93-99`). And `AuthSettings` requires `issuer_url` and `resource_server_url`, which drags in OAuth metadata that D3 does not want. Conclusion: do not use the SDK auth parameters. Wrap the returned app in our own ASGI middleware.
- Request bodies are capped at 4 MiB (`DEFAULT_MAX_REQUEST_BODY_SIZE`, `mcp/server/transport_security.py:16`). Responses are not capped there, but a full transcript should still be bounded so a single tool call cannot flood a client context.
- Two processes on one SQLite file is safe here because WAL is already enabled at `src/state/db.py:64` and the MCP process opens `file:<path>?mode=ro` and never writes.

## Requirements

Functional:
- Tools: `list_meetings`, `get_meeting`, `get_transcript`, `search_transcripts`.
- Auth: `Authorization: Bearer <key>` where the key is an active user's API key or `ADMIN_TOKEN`. Anything else is 401.
- Every user sees every meeting (D2). `attendee` is a filter argument only.
- The process serves at path `/mcp` and binds host and port from the environment.

Non-functional:
- Read-only database access enforced at the connection level.
- Reuses `src/state/meeting_queries.py` instead of duplicating filter SQL.
- Each module under 200 lines.

## Architecture

```
client (Claude Desktop/Code, Cursor)
  │  POST https://<host>/mcp   Authorization: Bearer <api key>
cloudflared ──> 127.0.0.1:18081
  │
BearerAuthASGI          # our middleware: http scope only, lifespan passes through
  │  401 on missing or unknown key
Starlette app from MCPServer.streamable_http_app(...)
  │
tool functions ──> mcp_server/queries.py ──> sqlite3 "file:<db>?mode=ro" (read only)
                                        └──> transcript and summary files on disk
```

Tool signatures. `from` and `import` are Python keywords, so the design's `from` and `to` become `date_from` and `date_to`:

```python
list_meetings(date_from: str = "", date_to: str = "", query: str = "",
              attendee: str = "", status: str = "", limit: int = 20) -> list[dict]
get_meeting(meet_code: str) -> dict          # metadata, summary, minutes, no raw transcript
get_transcript(meet_code: str) -> str        # transcript text, truncated with a marker past the cap
search_transcripts(query: str, date_from: str = "", date_to: str = "",
                   attendee: str = "", limit: int = 10) -> list[dict]   # snippets, not full text
```

`list_meetings` returns the metadata block only, mirroring the keys in `src/health_server.py:382-405`, so REST and MCP describe a meeting identically.

## Related Code Files

Create:
- `src/mcp_server/__init__.py`
- `src/mcp_server/queries.py` - `read_only_connect(db_path)`, `list_meetings`, `get_meeting`, `read_transcript`, `search_transcripts`. Builds its WHERE clause with `meeting_filter_sql` from `src/state/meeting_queries.py` and resolves file paths with `resolve_meeting_paths`.
- `src/mcp_server/bearer_auth.py` - `BearerAuthASGI(app, db_path, admin_token)` plus `verify_key(key, db_path, admin_token) -> bool`.
- `src/mcp_server/server.py` - `build_server()` registering the four tools, `build_app()` returning the wrapped ASGI app.
- `src/mcp_server/__main__.py` - reads `MCP_HOST`, `MCP_PORT`, runs uvicorn.

Modify:
- `pyproject.toml` - add `"mcp>=2.1.1,<3"` to `dependencies`.

Tests:
- `tests/test_mcp_queries.py`, `tests/test_mcp_bearer_auth.py`, `tests/test_mcp_tools.py`

## Implementation Steps

1. Add the dependency and run `uv sync --dev`. Confirm `from mcp.server.mcpserver import MCPServer` imports.
2. `src/mcp_server/queries.py`:
   - `read_only_connect(db_path)` returns `sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)` with `row_factory = sqlite3.Row`. Never call `src.state.db.connect` here, it would run the schema script and take a write lock.
   - Reuse `meeting_filter_sql` by building the same `params` shape it expects, so `query`, `attendee`, `status`, `date_from`, `date_to` behave exactly like the REST filters.
   - `read_transcript` resolves the path through `resolve_meeting_paths`, reads with `errors="replace"`, truncates at `MAX_TRANSCRIPT_CHARS = 400_000` and appends a visible truncation marker.
   - `search_transcripts` filters by metadata first, then scans each transcript for a case-insensitive match and returns `{meet_code, title, scheduled_start_utc, snippet}` with roughly 400 characters of context per hit, one hit per meeting, capped by `limit`.
   - Raise `ValueError("meeting not found")` for an unknown meet code and let the tool convert it to a readable message.
3. `src/mcp_server/bearer_auth.py`:
   ```python
   class BearerAuthASGI:
       def __init__(self, app, db_path, admin_token): ...
       async def __call__(self, scope, receive, send):
           if scope["type"] != "http":
               await self.app(scope, receive, send)
               return
           header = dict(scope.get("headers") or {}).get(b"authorization", b"").decode()
           token = header.removeprefix("Bearer ").strip() if header.startswith("Bearer ") else ""
           if not token or not verify_key(token, self.db_path, self.admin_token):
               await self._unauthorized(send)
               return
           await self.app(scope, receive, send)
   ```
   `verify_key` compares against `ADMIN_TOKEN` with `hmac.compare_digest` when the token is set, then looks the key hash up through a read-only connection filtered on `is_active = 1`. The 401 response body is JSON and carries a `WWW-Authenticate: Bearer` header.
4. `src/mcp_server/server.py`:
   - `build_server()` creates `MCPServer(name="meeting-assistant")` and registers the four tools with `@server.tool()`, each with a docstring, because the docstring is what the client model reads.
   - `build_app()` calls
     `server.streamable_http_app(streamable_http_path="/mcp", stateless_http=True, json_response=False, transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))`
     and wraps it in `BearerAuthASGI`.
   - `stateless_http=True` because the tools are read-only and the tunnel may not pin a client to one process.
5. `src/mcp_server/__main__.py`: `uvicorn.run(build_app(), host=os.getenv("MCP_HOST", "127.0.0.1"), port=int(os.getenv("MCP_PORT", "18081")), log_level="info")`. Environment reads mirror `src/health_server.py:1172-1173`.
6. Tests, then `uv run pytest` and `uv run python -m compileall src tests`.

## Todo List

- [x] `mcp>=2.1.1,<3` in `pyproject.toml`, `uv sync --dev`
- [x] `src/mcp_server/queries.py`
- [x] `src/mcp_server/bearer_auth.py`
- [x] `src/mcp_server/server.py`
- [x] `src/mcp_server/__main__.py`
- [x] `tests/test_mcp_queries.py`
- [x] `tests/test_mcp_bearer_auth.py`
- [x] `tests/test_mcp_tools.py`
- [x] Manual smoke test with curl and with a real client
- [x] Full test suite green

## Test Matrix

| Level | Case | Expectation |
|-------|------|-------------|
| Unit | `read_only_connect` then an INSERT | `sqlite3.OperationalError`, database is read only |
| Unit | `list_meetings` with no arguments | newest first, default limit 20 |
| Unit | `list_meetings` with `query`, `attendee`, `status`, date range | same rows the REST filter returns for the same inputs |
| Unit | `get_meeting` unknown code | `ValueError` surfaced as a readable tool error |
| Unit | `get_meeting` known code | metadata plus summary and minutes, no raw transcript field |
| Unit | `get_transcript` when the file is missing | clear message, no traceback |
| Unit | `get_transcript` over the cap | truncated at the cap with the marker present |
| Unit | `search_transcripts` hit and miss | snippet contains the term, miss returns an empty list |
| Unit | `search_transcripts` limit | never exceeds the limit |
| Unit | middleware, no Authorization header | 401 |
| Unit | middleware, wrong scheme such as Basic | 401 |
| Unit | middleware, unknown bearer | 401 |
| Unit | middleware, valid user API key | request passes through |
| Unit | middleware, deactivated user API key | 401 |
| Unit | middleware, `ADMIN_TOKEN` | passes |
| Unit | middleware, `ADMIN_TOKEN` unset and an empty bearer sent | 401 |
| Unit | middleware, lifespan scope | forwarded untouched |
| Integration | `await server.call_tool("list_meetings", {...})` on a seeded temp DB | expected rows, exercises the real registration path |
| Integration | writer process appends a meeting while the MCP connection is open | reader sees it on the next query, no lock error |

Middleware tests drive `__call__` directly with a constructed scope and a capturing `send`, so no live socket is needed and nothing is mocked away.

## Success Criteria

- `curl -s -o /dev/null -w '%{http_code}' -X POST http://127.0.0.1:18081/mcp` returns 401 without a key.
- The same call with a valid key and a proper MCP initialize body returns 200.
- Claude Desktop or Claude Code connected with a Bearer header lists the four tools and returns a real transcript.
- `uv run pytest` green.
- The database file is never modified by the MCP process, checked by comparing the mtime after a tool run.

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| A copied v1 FastMCP snippet fails to import | High | Low | Documented rename to `MCPServer` at the top of this phase |
| SDK auth parameters produce a permanent 401 | High if used | High | Do not pass `auth` or `token_verifier`, use the custom middleware |
| DNS rebinding protection rejects tunnel traffic | High if defaulted | High | Explicit `TransportSecuritySettings(enable_dns_rebinding_protection=False)` |
| Middleware swallows the lifespan and the app never starts | Med | High | Non-http scopes pass through, covered by a test |
| Read-only connect fails against a WAL database | Low | Med | Same container and same uid as the writer, so the shm lock works; covered by the concurrent test |
| A huge transcript floods the client | Med | Low | Cap at 400k characters and return snippets from search |
| The new dependency tree bloats the image | Med | Low | Official SDK only, no extras, accepted |

## Security Considerations

- Auth is enforced before any MCP protocol handling, so an unauthenticated caller never reaches a tool.
- Keys are compared by hash, and `ADMIN_TOKEN` with `hmac.compare_digest`.
- The process opens the database read-only, so a tool bug cannot corrupt state.
- Bind to `127.0.0.1` by default. Only the container override sets `0.0.0.0`, and the published port stays bound to the host loopback.
- Everyone sees everything is deliberate (D2). The tool docstrings say so, so nobody mistakes the attendee argument for an access control.

## Rollback

Revert the commit. The process is not started by anything until phase 06, so a rollback here has no runtime effect.

## Next Steps

Phase 06 starts and supervises this process, publishes the port, and adds the tunnel route.
