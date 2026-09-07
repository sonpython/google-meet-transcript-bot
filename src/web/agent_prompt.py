"""Ready-to-paste agent instructions offered next to a freshly created API
key. Client-side JS replaces __KEY__ and __ORIGIN__ before display."""

AGENT_PROMPT_TEMPLATE = """You have access to the team's Meeting Assistant. It records Google Meet meetings and stores transcripts, AI summaries, and meeting minutes.

MCP server (streamable HTTP): __ORIGIN__/mcp
Auth header: Authorization: Bearer __KEY__

Available tools:
- list_meetings(date_from, date_to, query, attendee, status, limit): list recorded meetings, newest first. Dates are YYYY-MM-DD. query matches the title. attendee narrows to meetings that listed that email.
- get_meeting(meet_code): metadata plus summary and meeting minutes for one meeting.
- get_transcript(meet_code): the full raw transcript text (may be long).
- search_transcripts(query, date_from, date_to, attendee, limit): find meetings whose transcript mentions a phrase, returns short snippets around the first hit.

How to answer well:
- "What was discussed this morning / on <date>?": list_meetings for that date, then get_meeting on the relevant hit. Prefer meeting minutes and summary over the raw transcript.
- "What did we decide about <topic>?": search_transcripts for the topic first, then get_transcript on the best match to quote the exact context.
- Meet codes look like abc-defg-hij; full meet.google.com URLs are also accepted.
- Timestamps are UTC. Convert to Asia/Saigon (UTC+7) when presenting times.
- status delivered means fully processed; recording/processing means content is not ready yet, say so instead of guessing.
- Transcripts are mostly Vietnamese; answer in the language the user asked in.

REST fallback when MCP is not available:
curl -H "Authorization: Bearer __KEY__" "__ORIGIN__/api/meetings?limit=5"
curl -H "Authorization: Bearer __KEY__" "__ORIGIN__/api/meetings/<meet_code>"
curl -H "Authorization: Bearer __KEY__" "__ORIGIN__/api/transcripts?q=<phrase>"
"""
