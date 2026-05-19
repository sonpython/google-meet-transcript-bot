import random
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


def next_health_check_time(now: datetime | None = None) -> datetime:
    tz = ZoneInfo("Asia/Ho_Chi_Minh")
    current = now.astimezone(tz) if now else datetime.now(tz)
    hour = random.randint(5, 8)
    minute = random.randint(0, 59)
    candidate = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= current:
        candidate = candidate + timedelta(days=1)
    return candidate


class DailyHealthCheck:
    def __init__(self, telegram_client=None, gemini_client=None) -> None:
        self.telegram_client = telegram_client
        self.gemini_client = gemini_client

    async def run(self) -> bool:
        if self.gemini_client:
            await self.gemini_client.generate_text("Return OK")
        if self.telegram_client:
            await self.telegram_client.send_text("Daily health check pass")
        return True
