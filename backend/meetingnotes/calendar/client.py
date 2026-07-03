"""Read-only calendar access for meeting detection and attendee pre-fill.

The protocol has no write surface at all, so the read-only guarantee is
structural. The Google implementation talks to the Calendar REST API with a
bearer token; the contract tests run against a fake client."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

import httpx


@dataclass
class CalendarAttendee:
    name: str
    email: str | None = None


@dataclass
class CalendarEvent:
    title: str
    start: datetime
    end: datetime
    attendees: list[CalendarAttendee] = field(default_factory=list)


class CalendarClient(Protocol):
    def events_between(self, start: datetime, end: datetime) -> list[CalendarEvent]: ...


class GoogleCalendarClient:
    """GET-only against the Google Calendar v3 API."""

    def __init__(self, access_token: str, calendar_id: str = "primary",
                 http: httpx.Client | None = None):
        self._token = access_token
        self._calendar_id = calendar_id
        self._http = http or httpx.Client(timeout=30)

    def events_between(self, start: datetime, end: datetime) -> list[CalendarEvent]:
        response = self._http.get(
            f"https://www.googleapis.com/calendar/v3/calendars/{self._calendar_id}/events",
            params={
                "timeMin": start.isoformat(),
                "timeMax": end.isoformat(),
                "singleEvents": "true",
                "orderBy": "startTime",
            },
            headers={"Authorization": f"Bearer {self._token}"},
        )
        response.raise_for_status()
        events = []
        for item in response.json().get("items", []):
            start_raw = item.get("start", {}).get("dateTime")
            end_raw = item.get("end", {}).get("dateTime")
            if not start_raw or not end_raw:
                continue  # all-day entries are not meetings to record
            events.append(CalendarEvent(
                title=item.get("summary", "Meeting"),
                start=datetime.fromisoformat(start_raw),
                end=datetime.fromisoformat(end_raw),
                attendees=[
                    CalendarAttendee(
                        name=a.get("displayName") or a.get("email", "Unknown"),
                        email=a.get("email"),
                    )
                    for a in item.get("attendees", [])
                ],
            ))
        return events
