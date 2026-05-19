from datetime import UTC, datetime, timedelta

import pytest

from src.bot.meet_monitor import MeetMonitor


class FakeParticipants:
    def __init__(self, snapshots: list[list[str]]) -> None:
        self.snapshots = snapshots
        self.index = 0

    async def get_participants(self, page) -> list[str]:
        if self.index >= len(self.snapshots):
            return self.snapshots[-1]
        value = self.snapshots[self.index]
        self.index += 1
        return value


class FakeDetector:
    async def check_exit_signal(self, page, participant_count=None) -> str | None:
        return "alone_signal" if participant_count == 1 else None


class FakeClock:
    def __init__(self, start: datetime) -> None:
        self.current = start

    def now(self) -> datetime:
        return self.current

    async def sleep(self, seconds: int) -> None:
        self.current += timedelta(seconds=seconds)


def _monitor(participants: list[list[str]], clock: FakeClock) -> MeetMonitor:
    monitor = MeetMonitor(
        page=None,
        poll_seconds=60,
        alone_after_seconds=5 * 60,
        no_one_joined_timeout_seconds=30 * 60,
        post_company_min_duration_seconds=10 * 60,
        clock=clock.now,
        sleep=clock.sleep,
    )
    monitor.participants = FakeParticipants(participants)
    monitor.detector = FakeDetector()
    return monitor


@pytest.mark.anyio
async def test_no_one_joined_times_out_after_30_minutes() -> None:
    clock = FakeClock(datetime(2026, 5, 20, tzinfo=UTC))
    monitor = _monitor([["bot"]] * 40, clock)

    reason, participants, duration = await monitor.run_until_exit()

    assert reason == "no_one_joined"
    assert participants == ("bot",)
    assert duration == 30 * 60


@pytest.mark.anyio
async def test_alone_timeout_starts_after_10_minutes_when_people_left() -> None:
    clock = FakeClock(datetime(2026, 5, 20, tzinfo=UTC))
    participants = [["bot", "An"]] * 2 + [["bot"]] * 20
    monitor = _monitor(participants, clock)

    reason, participants, duration = await monitor.run_until_exit()

    assert reason == "alone"
    assert participants == ("bot",)
    assert duration == 15 * 60


@pytest.mark.anyio
async def test_alone_timeout_after_10_minutes_waits_5_minutes() -> None:
    clock = FakeClock(datetime(2026, 5, 20, tzinfo=UTC))
    participants = [["bot", "An"]] * 12 + [["bot"]] * 10
    monitor = _monitor(participants, clock)

    reason, participants, duration = await monitor.run_until_exit()

    assert reason == "alone"
    assert participants == ("bot",)
    assert duration == 17 * 60


@pytest.mark.anyio
async def test_force_exit_returns_immediately() -> None:
    clock = FakeClock(datetime(2026, 5, 20, tzinfo=UTC))
    monitor = _monitor([["bot", "An"]], clock)
    monitor.should_force_exit = lambda: True

    reason, participants, duration = await monitor.run_until_exit()

    assert reason == "force_out"
    assert participants == ("bot", "An")
    assert duration == 0
