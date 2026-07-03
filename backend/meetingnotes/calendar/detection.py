"""Meeting detection. A due calendar meeting, or a call app in a call, emits
a prompt to start recording. It is always a prompt: recording never starts
without the user's say-so, which is structural here because detection only
ever returns prompt values."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta

from meetingnotes.calendar.client import CalendarEvent
from meetingnotes.storage import meetings as m


@dataclass
class RecordingPrompt:
    """An offer shown to the user. Nothing here can start a recording."""
    title: str
    reason: str
    attendees: list[tuple[str, str | None]]


def due_meeting_prompts(
    events: list[CalendarEvent], now: datetime,
    lead: timedelta = timedelta(minutes=2), grace: timedelta = timedelta(minutes=10),
) -> list[RecordingPrompt]:
    """Meetings starting about now, offered as prompts."""
    prompts = []
    for event in events:
        if event.start - lead <= now <= event.start + grace:
            prompts.append(RecordingPrompt(
                title=event.title,
                reason=f"{event.title} is due in your calendar.",
                attendees=[(a.name, a.email) for a in event.attendees],
            ))
    return prompts


# Process names that mean a call is probably happening. A secondary trigger
# only; it produces the same prompt, never a recording.
CALL_PROCESS_NAMES = {
    "zoom.us",
    "Microsoft Teams",
    "Teams",
    "Slack",
    "FaceTime",
    "webexmta",
}


def call_app_prompt(process_names: list[str]) -> RecordingPrompt | None:
    running = sorted(set(process_names) & CALL_PROCESS_NAMES)
    if not running:
        return None
    return RecordingPrompt(
        title="Meeting",
        reason=f"{running[0]} looks like it is in a call.",
        attendees=[],
    )


def prefill_attendees(conn: sqlite3.Connection, meeting_id: str, event: CalendarEvent) -> int:
    """Attendees from the calendar event, marked as such, feeding the same
    attendee list Phase 1 uses for speaker assignment."""
    for attendee in event.attendees:
        m.add_attendee(conn, meeting_id, attendee.name, attendee.email, from_calendar=True)
    return len(event.attendees)
