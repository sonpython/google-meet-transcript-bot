from pathlib import Path

PROMPT_PATH = Path(__file__).parent / "prompts" / "summarize_vn_v1.md"


class Summarizer:
    def __init__(self, client) -> None:
        self.client = client

    async def summarize(self, transcript: str, title: str) -> str:
        prompt = PROMPT_PATH.read_text()
        prompt = prompt.replace("{meeting_title}", title or "Không rõ")
        prompt = f"{prompt}\n\n# Transcript\n\n{transcript}"
        return await self.client.generate_text(prompt)
