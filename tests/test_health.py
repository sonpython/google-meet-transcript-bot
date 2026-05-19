import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from src.health.alerter import FailureAlerter
from src.health.daily_check import DailyHealthCheck, next_health_check_time
from src.state.db import connect


def test_failure_alerter_threshold(tmp_path) -> None:
    alerter = FailureAlerter(connect(tmp_path / "state.db"), threshold=3)

    assert not alerter.record_failure("gemini")
    assert not alerter.record_failure("gemini")
    assert alerter.record_failure("gemini")
    alerter.record_success("gemini")
    assert not alerter.record_failure("gemini")


def test_next_health_check_time_is_morning() -> None:
    now = datetime(2026, 5, 20, 9, 30, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))

    scheduled = next_health_check_time(now)

    assert scheduled.date().isoformat() == "2026-05-21"
    assert 5 <= scheduled.hour <= 8


def test_daily_health_check_runs_clients() -> None:
    calls = []

    class Gemini:
        async def generate_text(self, prompt: str) -> str:
            calls.append(("gemini", prompt))
            return "OK"

    class Telegram:
        async def send_text(self, text: str) -> None:
            calls.append(("telegram", text))

    assert asyncio.run(DailyHealthCheck(Telegram(), Gemini()).run())
    assert calls == [("gemini", "Return OK"), ("telegram", "Daily health check pass")]
