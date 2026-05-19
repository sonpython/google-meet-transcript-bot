from datetime import UTC, datetime
from sqlite3 import Connection


class FailureAlerter:
    def __init__(self, conn: Connection, threshold: int = 3) -> None:
        self.conn = conn
        self.threshold = threshold

    def record_failure(self, component: str) -> bool:
        row = self.conn.execute("SELECT count FROM failures WHERE component=?", (component,)).fetchone()
        count = (row["count"] if row else 0) + 1
        self.conn.execute(
            """
            INSERT INTO failures (component, count, last_at)
            VALUES (?, ?, ?)
            ON CONFLICT(component) DO UPDATE SET count=excluded.count, last_at=excluded.last_at
            """,
            (component, count, datetime.now(UTC).isoformat()),
        )
        self.conn.commit()
        return count == self.threshold

    def record_success(self, component: str) -> None:
        self.conn.execute(
            """
            INSERT INTO failures (component, count, last_at)
            VALUES (?, 0, ?)
            ON CONFLICT(component) DO UPDATE SET count=0, last_at=excluded.last_at
            """,
            (component, datetime.now(UTC).isoformat()),
        )
        self.conn.commit()
