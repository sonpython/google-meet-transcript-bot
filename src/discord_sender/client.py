from pathlib import Path

import httpx


class DiscordClient:
    def __init__(self, bot_token: str, channel_id: str) -> None:
        self.auth_header = _authorization_header(bot_token)
        self.channel_id = channel_id
        self.base_url = "https://discord.com/api/v10"

    async def send_text(self, text: str) -> None:
        async with httpx.AsyncClient(timeout=30) as client:
            for chunk in _chunks(text, 1900):
                response = await client.post(
                    f"{self.base_url}/channels/{self.channel_id}/messages",
                    headers={
                        "Authorization": self.auth_header,
                        "User-Agent": "DiscordBot (meeting-assistant 0.1)",
                    },
                    json={"content": chunk},
                )
                response.raise_for_status()

    async def send_document(self, path: Path, caption: str | None = None) -> None:
        async with httpx.AsyncClient(timeout=60) as client:
            with path.open("rb") as handle:
                files = {"files[0]": (path.name, handle, "text/markdown")}
                data = {"payload_json": _payload_json(caption or "Full meeting notes")}
                response = await client.post(
                    f"{self.base_url}/channels/{self.channel_id}/messages",
                    headers={
                        "Authorization": self.auth_header,
                        "User-Agent": "DiscordBot (meeting-assistant 0.1)",
                    },
                    data=data,
                    files=files,
                )
                response.raise_for_status()


def _authorization_header(token: str) -> str:
    stripped = token.strip()
    if stripped.lower().startswith(("bot ", "bearer ")):
        return stripped
    return f"Bot {stripped}"


def _chunks(text: str, limit: int) -> list[str]:
    if not text:
        return [""]
    return [text[index : index + limit] for index in range(0, len(text), limit)]


def _payload_json(content: str) -> str:
    import json

    return json.dumps({"content": content[:1900]})
