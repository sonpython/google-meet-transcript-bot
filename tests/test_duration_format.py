from src.duration_format import format_duration


def test_format_duration_uses_hours_minutes_seconds() -> None:
    assert format_duration(3484) == "58m 4s"
    assert format_duration(3661) == "1h 1m 1s"
    assert format_duration(42) == "42s"
