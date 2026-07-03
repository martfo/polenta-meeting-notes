"""AC-2.2-a [contract-mock]: titles and attendees are read from the calendar,
read-only. The real Google client runs against a fake transport that rejects
anything but GET; the client protocol has no write surface at all."""

from datetime import datetime, timezone

import httpx

from meetingnotes.calendar.client import CalendarClient, GoogleCalendarClient

START = datetime(2026, 7, 3, 8, 0, tzinfo=timezone.utc)
END = datetime(2026, 7, 3, 18, 0, tzinfo=timezone.utc)


def test_ac_2_2_a_calendar_read_only_contract():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.method == "GET", "read-only: no write is ever attempted"
        assert "calendar/v3/calendars/primary/events" in str(request.url)
        assert request.headers["Authorization"] == "Bearer test-token"
        return httpx.Response(200, json={"items": [
            {
                "summary": "Client review",
                "start": {"dateTime": "2026-07-03T14:00:00+00:00"},
                "end": {"dateTime": "2026-07-03T15:00:00+00:00"},
                "attendees": [
                    {"displayName": "Ben Adams", "email": "ben@example.com"},
                    {"email": "roger@example.com"},
                ],
            },
            {"summary": "All-day thing", "start": {"date": "2026-07-03"}, "end": {"date": "2026-07-04"}},
        ]})

    client = GoogleCalendarClient(
        "test-token", http=httpx.Client(transport=httpx.MockTransport(handler)))
    events = client.events_between(START, END)

    assert len(requests) == 1
    assert len(events) == 1, "all-day entries are not meetings"
    assert events[0].title == "Client review"
    assert [(a.name, a.email) for a in events[0].attendees] == [
        ("Ben Adams", "ben@example.com"),
        ("roger@example.com", "roger@example.com"),
    ]

    # The protocol itself has no write methods: read-only is structural.
    write_like = [name for name in dir(CalendarClient)
                  if any(verb in name.lower() for verb in ("create", "update", "delete", "insert", "write", "patch"))]
    assert write_like == []
