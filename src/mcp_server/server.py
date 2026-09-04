"""MCP server exposing meeting transcripts over streamable HTTP.

Runs as a second process next to the main service (deployment starts it),
sharing the SQLite file read-only. Auth is a personal API key or the
ADMIN_TOKEN in an Authorization: Bearer header, enforced by BearerAuthASGI.
Visibility is deliberately org-wide: every authenticated user can read every
meeting; the attendee argument is a filter, not an access control.
"""

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from src.config import load_settings
from src.mcp_server import queries
from src.mcp_server.bearer_auth import BearerAuthASGI


def build_server() -> MCPServer:
    server = MCPServer(name="meeting-assistant")
    db_path = load_settings().db_path

    @server.tool()
    def list_meetings(
        date_from: str = "",
        date_to: str = "",
        query: str = "",
        attendee: str = "",
        status: str = "",
        limit: int = 20,
    ) -> list[dict]:
        """List recorded meetings, newest first, metadata only.

        date_from/date_to accept YYYY-MM-DD or ISO datetimes. query matches
        the meeting title. attendee narrows to meetings listing that email as
        attendee or organizer (convenience filter, every user can see every
        meeting). status is one of scheduled, joining, recording, recorded,
        processing, delivered, failed, no_one_joined, cancelled.
        """
        return queries.list_meetings(
            db_path, date_from=date_from, date_to=date_to, query=query,
            attendee=attendee, status=status, limit=limit,
        )

    @server.tool()
    def get_meeting(meet_code: str) -> dict:
        """Get one meeting by Meet code (e.g. abc-defg-hij or a full Meet
        URL): metadata plus summary and meeting minutes when available. Use
        get_transcript for the raw transcript text."""
        return queries.get_meeting(db_path, meet_code)

    @server.tool()
    def get_transcript(meet_code: str) -> str:
        """Get the full transcript text of one meeting by Meet code. Very
        long transcripts are truncated with a visible marker."""
        return queries.read_transcript(db_path, meet_code)

    @server.tool()
    def search_transcripts(
        query: str,
        date_from: str = "",
        date_to: str = "",
        attendee: str = "",
        limit: int = 10,
    ) -> list[dict]:
        """Search transcript contents for a phrase (case-insensitive) and
        return matching meetings with a short snippet around the first hit.
        Use get_transcript on a hit's meet_code for the full text."""
        return queries.search_transcripts(
            db_path, query, date_from=date_from, date_to=date_to, attendee=attendee, limit=limit
        )

    return server


def build_app():
    settings = load_settings()
    server = build_server()
    app = server.streamable_http_app(
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=False,
        # Behind cloudflared the Host header is the public hostname, which the
        # SDK's loopback rebinding guard would reject; auth is our bearer
        # middleware, not host matching.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    return BearerAuthASGI(app, settings.db_path, settings.admin_token or "")
