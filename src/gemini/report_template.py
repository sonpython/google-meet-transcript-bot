from datetime import UTC, datetime


def document_header(title: str, meet_code: str, generated_at: datetime | None = None) -> str:
    return f"{document_title(title)}\n\n{document_marker(meet_code, generated_at)}"


def document_title(title: str) -> str:
    return f"# Meeting Minutes - {title}"


def document_marker(meet_code: str, generated_at: datetime | None = None) -> str:
    timestamp = (generated_at or datetime.now(UTC)).strftime("%Y-%m-%d %H:%M:%S UTC")
    return f"## Generated {timestamp}\nMeet code: {meet_code}\n"
