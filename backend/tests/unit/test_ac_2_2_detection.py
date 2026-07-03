"""Section 2.2: calendar-aware meeting detection. Unit tier."""

from datetime import datetime, timedelta, timezone

from meetingnotes.calendar.client import CalendarAttendee, CalendarEvent
from meetingnotes.calendar.detection import (
    RecordingPrompt,
    call_app_prompt,
    due_meeting_prompts,
    prefill_attendees,
)
from meetingnotes.storage import meetings as m
from tests.conftest import make_meeting

NOW = datetime(2026, 7, 3, 14, 0, tzinfo=timezone.utc)


def event(minutes_from_now: int, title="Client review") -> CalendarEvent:
    start = NOW + timedelta(minutes=minutes_from_now)
    return CalendarEvent(
        title=title, start=start, end=start + timedelta(hours=1),
        attendees=[
            CalendarAttendee("Ben Adams", "ben@example.com"),
            CalendarAttendee("Roger Neel", "roger@example.com"),
        ],
    )


def test_ac_2_2_b_due_meeting_prompts_never_records():
    """A due meeting emits a prompt to start recording and never starts one
    on its own: detection can only return prompt values."""
    prompts = due_meeting_prompts([event(1)], now=NOW)
    assert len(prompts) == 1
    assert isinstance(prompts[0], RecordingPrompt)
    assert "Client review" in prompts[0].reason
    # A prompt is inert data: it has no way to start anything.
    assert not any(callable(getattr(prompts[0], f)) for f in vars(prompts[0]))

    assert due_meeting_prompts([event(45)], now=NOW) == [], "not due yet"
    assert due_meeting_prompts([event(-30)], now=NOW) == [], "long started"


def test_ac_2_2_c_calendar_attendees_prefill(conn, vault):
    """Attendees from the calendar event pre-fill the meeting's attendee
    list, which is what speaker naming offers as candidates."""
    meeting_id = make_meeting(conn, vault)
    added = prefill_attendees(conn, meeting_id, event(0))

    attendees = m.list_attendees(conn, meeting_id)
    assert added == 2
    assert [(a["name"], a["email"], a["from_calendar"]) for a in attendees] == [
        ("Ben Adams", "ben@example.com", 1),
        ("Roger Neel", "roger@example.com", 1),
    ]


def test_ac_2_2_d_call_app_secondary_trigger():
    """A call app in a call is a secondary trigger, from a process-list
    fixture, and it too is only ever a prompt."""
    in_call = ["Finder", "Safari", "zoom.us", "Dock"]
    prompt = call_app_prompt(in_call)
    assert isinstance(prompt, RecordingPrompt)
    assert "zoom.us" in prompt.reason

    assert call_app_prompt(["Finder", "Safari", "Dock"]) is None
