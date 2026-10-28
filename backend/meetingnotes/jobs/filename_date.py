"""Reading a recording's date and time out of its filename.

Imported recordings are usually named for when they were made
('2026-08-19 14-30-00.m4a', 'Recording 20260819_143000.mp3',
'Meeting 19-08-2026 2.30pm.wav'). When a date can be read from the name it is
used as the meeting's recorded date, so it files under the day it happened
rather than the moment it was imported. Ambiguous day/month order is read
day-first (British), except where one value can only be a day.
"""

from __future__ import annotations

import re
from datetime import datetime

# Run-together date+time: YYYYMMDDHHMMSS and YYYYMMDDHHMM.
_FULL14 = re.compile(r"(?<!\d)(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})(?!\d)")
_FULL12 = re.compile(r"(?<!\d)(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(?!\d)")
# Date only; a time is looked for immediately after it.
_ISO = re.compile(r"(?<!\d)(\d{4})[-_.](\d{1,2})[-_.](\d{1,2})(?!\d)")       # YYYY-MM-DD
_COMPACT = re.compile(r"(?<!\d)(\d{4})(\d{2})(\d{2})(?!\d)")                 # YYYYMMDD
_DMY = re.compile(r"(?<!\d)(\d{1,2})[-_.](\d{1,2})[-_.](\d{4})(?!\d)")      # DD-MM-YYYY

# A time right after the date: 14:30, 14-30-00, 14.30, 2.30pm.
_TIME = re.compile(
    r"^[ tT_@.\-]*(?:at[ _]*)?(\d{1,2})[:.h\-](\d{2})(?:[:.\-](\d{2}))?\s*([ap]m)?",
    re.IGNORECASE)
# A run-together time after a compact date: _143000, 1430.
_TIME_COMPACT = re.compile(r"^[ _\-]?(\d{2})(\d{2})(\d{2})?(?!\d)")


def datetime_from_filename(name: str) -> datetime | None:
    """A local, timezone-aware datetime read from the filename, or None."""
    for regex in (_FULL14, _FULL12):
        m = regex.search(name)
        if m:
            g = [int(x) for x in m.groups()]
            dt = _build(g[0], g[1], g[2], g[3], g[4], g[5] if len(g) > 5 else 0)
            if dt:
                return dt

    for regex, day_first in ((_ISO, False), (_COMPACT, False), (_DMY, True)):
        m = regex.search(name)
        if not m:
            continue
        a, b, c = (int(x) for x in m.groups())
        if day_first:
            year = c
            if a > 12 and b <= 12:
                day, month = a, b
            elif b > 12 and a <= 12:
                month, day = a, b
            else:
                day, month = a, b  # ambiguous: British day-first
        else:
            year, month, day = a, b, c
        hour, minute, second = _time_after(name[m.end():])
        dt = _build(year, month, day, hour, minute, second)
        if dt:
            return dt
    return None


def _time_after(rest: str) -> tuple[int, int, int]:
    m = _TIME.match(rest)
    if m:
        hour, minute = int(m.group(1)), int(m.group(2))
        second = int(m.group(3)) if m.group(3) else 0
        ap = (m.group(4) or "").lower()
        if ap == "pm" and hour < 12:
            hour += 12
        elif ap == "am" and hour == 12:
            hour = 0
        return hour, minute, second
    m = _TIME_COMPACT.match(rest)
    if m:
        return int(m.group(1)), int(m.group(2)), int(m.group(3)) if m.group(3) else 0
    return 0, 0, 0


def _build(year, month, day, hour, minute, second) -> datetime | None:
    try:
        return datetime(year, month, day, hour, minute, second).astimezone()
    except ValueError:
        return None
