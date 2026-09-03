"""Reading the recorded date out of an imported recording's filename."""

from __future__ import annotations

from meetingnotes.jobs.filename_date import datetime_from_filename


def _dt(name):
    d = datetime_from_filename(name)
    return None if d is None else (d.year, d.month, d.day, d.hour, d.minute, d.second)


def test_iso_date_and_time_variants():
    assert _dt("2026-08-19 14-30-00.m4a") == (2026, 8, 19, 14, 30, 0)
    assert _dt("2026-08-19_1430.mp3") == (2026, 8, 19, 14, 30, 0)
    assert _dt("2026-08-19T14:30:05.wav") == (2026, 8, 19, 14, 30, 5)
    assert _dt("call 2026-08-19.mp3") == (2026, 8, 19, 0, 0, 0)  # date only -> midnight


def test_compact_and_run_together():
    assert _dt("Recording 20260819_143000.mp3") == (2026, 8, 19, 14, 30, 0)
    assert _dt("20260819143000.wav") == (2026, 8, 19, 14, 30, 0)  # 14 digits, no seps
    assert _dt("audio-20260819-1430.m4a") == (2026, 8, 19, 14, 30, 0)


def test_am_pm():
    assert _dt("New Recording 2026-08-19 at 2.30pm.m4a") == (2026, 8, 19, 14, 30, 0)
    assert _dt("2026-08-19 12.05am.mp3") == (2026, 8, 19, 0, 5, 0)


def test_day_first_and_month_first():
    assert _dt("19-08-2026 09.15.wav") == (2026, 8, 19, 9, 15, 0)   # day-first (British)
    assert _dt("08-19-2026.mp3") == (2026, 8, 19, 0, 0, 0)          # 19 can only be a day
    assert _dt("05-06-2026.mp3") == (2026, 6, 5, 0, 0, 0)           # ambiguous -> day-first


def test_no_date_returns_none():
    assert _dt("voice memo.m4a") is None
    assert _dt("client call.mp3") is None
    assert _dt("Q3 2026 planning.mp3") is None  # a lone year is not a date


def test_impossible_dates_are_rejected():
    assert _dt("2026-13-45.mp3") is None       # month 13, day 45
    assert _dt("2026-02-30 10-00.mp3") is None  # 30 February
