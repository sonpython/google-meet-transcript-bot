from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class JoinResult:
    status: str
    joined_at: datetime | None = None
    error_msg: str | None = None

    @property
    def admitted(self) -> bool:
        return self.status == "admitted"
