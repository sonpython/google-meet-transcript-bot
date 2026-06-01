import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SpeakerHint:
    start: float
    end: float
    speaker: str
    source: str = "meet_dom"
    confidence: float = 0.65


def load_speaker_hints(path: Path | None, max_duration_seconds: int | None = None) -> tuple[SpeakerHint, ...]:
    if not path or not path.exists():
        return ()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ()
    hints = []
    for raw in payload.get("events", []):
        if not isinstance(raw, dict):
            continue
        speaker = str(raw.get("speaker") or "").strip()
        if not speaker:
            continue
        try:
            start = float(raw.get("start", 0))
            end = float(raw.get("end", 0))
            confidence = float(raw.get("confidence", 0.65))
        except (TypeError, ValueError):
            continue
        if max_duration_seconds is not None:
            if start >= max_duration_seconds:
                continue
            end = min(end, float(max_duration_seconds))
        if end <= start:
            continue
        hints.append(
            SpeakerHint(
                start=max(0.0, start),
                end=end,
                speaker=speaker,
                source=str(raw.get("source") or "meet_dom"),
                confidence=max(0.0, min(1.0, confidence)),
            )
        )
    return tuple(hints)


def format_chunk_speaker_hints(
    hints: tuple[SpeakerHint, ...],
    chunk_start_seconds: int,
    chunk_end_seconds: int,
    limit: int = 24,
) -> str:
    relevant = []
    for hint in hints:
        if hint.end <= chunk_start_seconds or hint.start >= chunk_end_seconds:
            continue
        start = max(hint.start, float(chunk_start_seconds)) - chunk_start_seconds
        end = min(hint.end, float(chunk_end_seconds)) - chunk_start_seconds
        if end <= start:
            continue
        relevant.append((start, end, hint))
    if not relevant:
        return ""
    lines = [
        "## Speaker activity hints",
        "These are low-confidence Google Meet UI hints. Prefer the audio if it conflicts. If uncertain, use Người nói A/B instead of forcing a name.",
    ]
    for start, end, hint in _merge_adjacent(relevant)[:limit]:
        lines.append(
            f"- [{_fmt(start)}-{_fmt(end)}] likely {hint.speaker} "
            f"(source={hint.source}, confidence={hint.confidence:.2f})"
        )
    if len(relevant) > limit:
        lines.append(f"- {len(relevant) - limit} additional short hint(s) omitted.")
    return "\n".join(lines)


def _merge_adjacent(items: list[tuple[float, float, SpeakerHint]]) -> list[tuple[float, float, SpeakerHint]]:
    merged: list[tuple[float, float, SpeakerHint]] = []
    for start, end, hint in sorted(items, key=lambda item: (item[0], item[2].speaker)):
        if merged:
            prev_start, prev_end, prev_hint = merged[-1]
            if hint.speaker == prev_hint.speaker and hint.source == prev_hint.source and start - prev_end <= 1.5:
                merged[-1] = (prev_start, max(prev_end, end), hint)
                continue
        merged.append((start, end, hint))
    return merged


def _fmt(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    minutes = total // 60
    secs = total % 60
    return f"{minutes:02d}:{secs:02d}"
