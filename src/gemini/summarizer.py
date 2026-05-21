from pathlib import Path

PROMPT_PATH = Path(__file__).parent / "prompts" / "summarize_vn_v1.md"
MINUTES_PROMPT_PATH = Path(__file__).parent / "prompts" / "minutes_vn_v1.md"


class Summarizer:
    def __init__(self, client) -> None:
        self.client = client

    async def summarize(self, transcript: str, title: str, admin_instruction: str = "") -> str:
        prompt = PROMPT_PATH.read_text()
        prompt = prompt.replace("{meeting_title}", title or "Không rõ")
        if admin_instruction.strip():
            prompt = f"{prompt}\n\n## Admin instruction for this meeting\n{admin_instruction.strip()}"
        prompt = f"{prompt}\n\n# Transcript\n\n{transcript}"
        return await self.client.generate_text(prompt)

    async def minutes(self, transcript: str, title: str, admin_instruction: str = "") -> str:
        prompt = MINUTES_PROMPT_PATH.read_text()
        prompt = prompt.replace("{meeting_title}", title or "Không rõ")
        if admin_instruction.strip():
            prompt = f"{prompt}\n\n## Admin instruction for this meeting\n{admin_instruction.strip()}"
        prompt = f"{prompt}\n\n# Transcript\n\n{transcript}"
        return sanitize_minutes(await self.client.generate_text(prompt))


def sanitize_minutes(content: str) -> str:
    lines = content.strip().splitlines()
    while lines and _is_meta_minutes_line(lines[0]):
        lines.pop(0)
        while lines and not lines[0].strip():
            lines.pop(0)
    cleaned = "\n".join(lines).strip()
    marker = "## Thông Tin Cuộc Họp"
    if marker in cleaned and not cleaned.startswith(marker):
        cleaned = cleaned[cleaned.index(marker) :].strip()
    return cleaned


def _is_meta_minutes_line(line: str) -> bool:
    normalized = line.strip().lower()
    if not normalized:
        return True
    meta_phrases = (
        "chắc chắn rồi",
        "dưới đây là",
        "sau đây là",
        "đây là biên bản",
        "biên bản cuộc họp từ transcript",
        "từ transcript bạn",
        "transcript bạn đã cung cấp",
        "tôi đã",
        "mình đã",
    )
    return any(phrase in normalized for phrase in meta_phrases)
