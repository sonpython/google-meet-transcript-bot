import asyncio
import time
from pathlib import Path
from typing import Iterable

from google import genai


class GeminiClient:
    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.5-pro",
        fallback_models: Iterable[str] | None = None,
    ) -> None:
        self.models = tuple(
            dict.fromkeys((model, *(fallback_models or ("gemini-2.5-flash", "gemini-2.5-flash-lite"))))
        )
        self.client = genai.Client(api_key=api_key)

    async def generate_from_audio(self, audio_path: Path, prompt: str) -> str:
        return await asyncio.to_thread(self._generate_from_audio_sync, audio_path, prompt)

    async def generate_text(self, prompt: str) -> str:
        return await asyncio.to_thread(self._generate_text_sync, prompt)

    def _generate_from_audio_sync(self, audio_path: Path, prompt: str) -> str:
        uploaded = self.client.files.upload(file=str(audio_path))
        return self._generate_with_retry([prompt, uploaded])

    def _generate_text_sync(self, prompt: str) -> str:
        return self._generate_with_retry([prompt])

    def _generate_with_retry(self, contents: list) -> str:
        last_error: Exception | None = None
        delays = (5, 15, 30, 60)
        for attempt in range(len(delays) + 1):
            for model in self.models:
                try:
                    response = self.client.models.generate_content(model=model, contents=contents)
                    return response.text or ""
                except Exception as exc:
                    last_error = exc
                    if not _is_retryable(exc):
                        raise
            if attempt < len(delays):
                time.sleep(delays[attempt])
        if last_error:
            raise last_error
        raise RuntimeError("Gemini request failed without an exception")


def _is_retryable(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(token in text for token in ("503", "unavailable", "overload", "rate", "quota", "timeout"))
