from pathlib import Path

from telegram import Bot


class TelegramClient:
    def __init__(self, token: str, chat_id: str) -> None:
        self.bot = Bot(token)
        self.chat_id = chat_id

    async def send_text(self, text: str) -> None:
        await self.bot.send_message(chat_id=self.chat_id, text=text, parse_mode="MarkdownV2")

    async def send_document(self, path: Path, caption: str | None = None) -> None:
        with path.open("rb") as handle:
            await self.bot.send_document(chat_id=self.chat_id, document=handle, caption=caption)
