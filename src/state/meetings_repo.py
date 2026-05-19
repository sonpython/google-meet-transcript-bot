from datetime import UTC, datetime
import json
from sqlite3 import Connection

from src.models.meeting_event import MeetingEvent

TERMINAL_STATUSES = {"delivered", "failed", "cancelled", "no_one_joined"}


class MeetingsRepo:
    def __init__(self, conn: Connection) -> None:
        self.conn = conn

    def upsert(self, meeting: MeetingEvent) -> bool:
        existing = self.get(meeting.meet_code)
        if existing and existing["status"] in TERMINAL_STATUSES:
            return False
        if existing:
            self.conn.execute(
                """
                UPDATE meetings
                SET event_id=?, scheduled_start_utc=?, title=?, organizer=?, attendees=?, updated_at=CURRENT_TIMESTAMP
                WHERE meet_code=?
                """,
                (
                    meeting.event_id,
                    meeting.start_utc.isoformat(),
                    meeting.title,
                    meeting.organizer,
                    json.dumps(list(meeting.attendees), ensure_ascii=False),
                    meeting.meet_code,
                ),
            )
            self.conn.commit()
            return False
        self.conn.execute(
            """
            INSERT INTO meetings (meet_code, event_id, scheduled_start_utc, title, organizer, attendees, status)
            VALUES (?, ?, ?, ?, ?, ?, 'scheduled')
            """,
            (
                meeting.meet_code,
                meeting.event_id,
                meeting.start_utc.isoformat(),
                meeting.title,
                meeting.organizer,
                json.dumps(list(meeting.attendees), ensure_ascii=False),
            ),
        )
        self.conn.commit()
        return True

    def get(self, meet_code: str):
        cur = self.conn.execute("SELECT * FROM meetings WHERE meet_code=?", (meet_code,))
        return cur.fetchone()

    def get_pending(self) -> list:
        cur = self.conn.execute(
            """
            SELECT * FROM meetings
            WHERE status IN ('scheduled', 'joining', 'recording', 'processing')
            ORDER BY scheduled_start_utc
            """
        )
        return list(cur.fetchall())

    def mark_status(self, meet_code: str, status: str, error: str | None = None, **fields) -> None:
        assignments = ["status=?", "last_error=?", "updated_at=CURRENT_TIMESTAMP"]
        values = [status, error]
        for key, value in fields.items():
            assignments.append(f"{key}=?")
            values.append(value)
        values.append(meet_code)
        self.conn.execute(
            f"UPDATE meetings SET {', '.join(assignments)} WHERE meet_code=?",
            tuple(values),
        )
        self.conn.commit()

    def mark_delivered(self, meet_code: str, notes_path: str, **fields) -> None:
        self.mark_status(
            meet_code,
            "delivered",
            notes_path=notes_path,
            delivered_at=datetime.now(UTC).isoformat(),
            **fields,
        )

    def request_rejoin(self, meet_code: str) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO admin_commands (command, meet_code, status)
            VALUES ('rejoin', ?, 'pending')
            """,
            (meet_code,),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def request_force_out(self, meet_code: str) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO admin_commands (command, meet_code, status)
            VALUES ('force_out', ?, 'pending')
            """,
            (meet_code,),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def claim_pending_force_out(self, meet_code: str):
        row = self.conn.execute(
            """
            SELECT * FROM admin_commands
            WHERE command='force_out' AND meet_code=? AND status='pending'
            ORDER BY created_at
            LIMIT 1
            """,
            (meet_code,),
        ).fetchone()
        if row:
            self.conn.execute(
                "UPDATE admin_commands SET status='running', updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (row["id"],),
            )
            self.conn.commit()
        return row

    def claim_pending_rejoins(self, limit: int = 5) -> list:
        rows = list(
            self.conn.execute(
                """
                SELECT * FROM admin_commands
                WHERE command='rejoin' AND status='pending'
                ORDER BY created_at
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        )
        for row in rows:
            self.conn.execute(
                "UPDATE admin_commands SET status='running', updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (row["id"],),
            )
        self.conn.commit()
        return rows

    def complete_command(self, command_id: int, status: str = "done", error: str | None = None) -> None:
        self.conn.execute(
            """
            UPDATE admin_commands
            SET status=?, error=?, updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (status, error, command_id),
        )
        self.conn.commit()

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        row = self.conn.execute("SELECT value FROM app_settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        self.conn.execute(
            """
            INSERT INTO app_settings (key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=CURRENT_TIMESTAMP
            """,
            (key, value),
        )
        self.conn.commit()

    def get_audio_retention_days(self, default: int = 10) -> int:
        value = self.get_setting("audio_retention_days", str(default))
        try:
            return max(0, int(value or default))
        except ValueError:
            return default
