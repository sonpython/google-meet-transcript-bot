import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

import structlog

Sleep = Callable[[float], Awaitable[None]]

SPEAKER_TIMELINE_SUFFIX = ".speakers.json"


class SpeakerActivityRecorder:
    def __init__(
        self,
        page,
        meet_code: str,
        ignored_names: tuple[str, ...] = (),
        poll_seconds: float = 1.0,
        sleep: Sleep | None = None,
    ) -> None:
        self.page = page
        self.meet_code = meet_code
        self.ignored_names = {name.strip().lower() for name in ignored_names if name.strip()}
        self.poll_seconds = max(0.2, poll_seconds)
        self.sleep = sleep or asyncio.sleep
        self.log = structlog.get_logger(__name__)
        self._task: asyncio.Task | None = None
        self._segment: _SegmentTimeline | None = None

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        self.finish_segment()

    def start_segment(self, audio_path: Path) -> None:
        self.finish_segment()
        self._segment = _SegmentTimeline(
            meet_code=self.meet_code,
            audio_path=audio_path,
            started_at=time.monotonic(),
            poll_interval_seconds=self.poll_seconds,
        )

    def finish_segment(self) -> Path | None:
        if not self._segment:
            return None
        self._segment.close_current(time.monotonic())
        path = speaker_timeline_path(self._segment.audio_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self._segment.payload(), ensure_ascii=False, indent=2), encoding="utf-8")
        self.log.info(
            "speaker_activity_timeline_written",
            meet_code=self.meet_code,
            path=str(path),
            events=len(self._segment.events),
        )
        self._segment = None
        return path

    async def _run(self) -> None:
        while True:
            if self._segment:
                try:
                    names = await active_speaker_names(self.page, self.ignored_names)
                    self._segment.set_active(names, time.monotonic())
                except Exception as exc:
                    self.log.debug("speaker_activity_poll_failed", meet_code=self.meet_code, error=str(exc))
            await self.sleep(self.poll_seconds)


class _SegmentTimeline:
    def __init__(self, meet_code: str, audio_path: Path, started_at: float, poll_interval_seconds: float) -> None:
        self.meet_code = meet_code
        self.audio_path = audio_path
        self.started_at = started_at
        self.poll_interval_seconds = poll_interval_seconds
        self.events: list[dict] = []
        self._active: tuple[str, ...] = ()
        self._active_started_at: float | None = None

    def set_active(self, names: tuple[str, ...], now: float) -> None:
        names = tuple(dict.fromkeys(name.strip() for name in names if name.strip()))
        if names == self._active:
            return
        self.close_current(now)
        self._active = names
        self._active_started_at = now if names else None

    def close_current(self, now: float) -> None:
        if not self._active or self._active_started_at is None:
            self._active = ()
            self._active_started_at = None
            return
        start = max(0.0, self._active_started_at - self.started_at)
        end = max(start, now - self.started_at)
        if end > start:
            for name in self._active:
                self.events.append(
                    {
                        "start": round(start, 2),
                        "end": round(end, 2),
                        "speaker": name,
                        "source": "meet_dom",
                        "confidence": 0.65,
                    }
                )
        self._active = ()
        self._active_started_at = None

    def payload(self) -> dict:
        return {
            "version": 1,
            "meet_code": self.meet_code,
            "audio_path": str(self.audio_path),
            "poll_interval_seconds": self.poll_interval_seconds,
            "events": self.events,
        }


async def active_speaker_names(page, ignored_names: set[str] | None = None) -> tuple[str, ...]:
    ignored = ignored_names or set()
    names = await page.evaluate(_ACTIVE_SPEAKER_SCRIPT)
    cleaned = []
    for raw in names or []:
        name = _clean_name(str(raw))
        if name and name.lower() not in ignored and name not in cleaned:
            cleaned.append(name)
    return tuple(cleaned)


def speaker_timeline_path(audio_path: Path) -> Path:
    return audio_path.with_suffix(f"{audio_path.suffix}{SPEAKER_TIMELINE_SUFFIX}")


def _clean_name(value: str) -> str:
    name = " ".join(value.replace("\n", " ").split())
    replacements = (
        "is speaking",
        "speaking",
        "is talking",
        "talking",
        "đang nói",
        "presenting",
    )
    lowered = name.lower()
    for marker in replacements:
        if marker in lowered:
            index = lowered.find(marker)
            name = (name[:index] + name[index + len(marker) :]).strip(" -:,.")
            lowered = name.lower()
    return name[:120]


_ACTIVE_SPEAKER_SCRIPT = r"""
() => {
  const speakingPattern = /(speaking|talking|is-speaking|active-speaker|audio-level|đang nói|dang noi)/i;
  const nameAttrs = ["data-self-name", "data-name", "aria-label", "title"];
  const candidates = new Set();

  function signature(node) {
    if (!node || node.nodeType !== Node.ELEMENT_NODE) return "";
    const attrs = Array.from(node.attributes || []).map(attr => `${attr.name}=${attr.value}`).join(" ");
    return `${node.className || ""} ${attrs || ""}`;
  }

  function contextSignature(el) {
    const pieces = [signature(el)];
    let parent = el.parentElement;
    for (let i = 0; parent && i < 4; i += 1, parent = parent.parentElement) {
      pieces.push(signature(parent));
    }
    return pieces.join(" ");
  }

  function extractName(el) {
    for (const attr of nameAttrs) {
      const value = el.getAttribute(attr);
      if (value && value.trim()) return value.trim();
    }
    const text = (el.innerText || el.textContent || "").trim().split("\n").map(s => s.trim()).filter(Boolean);
    return text[0] || "";
  }

  const nodes = Array.from(document.querySelectorAll("[data-participant-id], [data-self-name], [aria-label]"));
  for (const el of nodes) {
    const haystack = contextSignature(el);
    if (!speakingPattern.test(haystack)) continue;
    const name = extractName(el);
    if (name) candidates.add(name);
  }
  return Array.from(candidates);
}
"""
