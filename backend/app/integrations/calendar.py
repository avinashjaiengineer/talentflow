from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Protocol
from zoneinfo import ZoneInfo

from ..config import get_settings
from .graph import GraphClient

BUSY = {"busy", "tentative", "oof"}


@dataclass
class Meeting:
    event_id: str | None
    join_url: str | None
    provider: str


class Calendar(Protocol):
    name: str

    def free_slots(self, attendees: list[str], *, count: int, duration: timedelta, now: datetime | None = None) -> list[datetime]: ...

    def create_meeting(
        self, *, subject: str, body: str, start: datetime, duration: timedelta, attendees: list[tuple[str, str]]
    ) -> Meeting: ...


def candidate_starts(now: datetime, duration: timedelta, days: int = 10) -> list[datetime]:
    """Every half hour in working hours on business days, starting tomorrow, in TIMEZONE."""
    s = get_settings()
    tz = ZoneInfo(s.timezone)
    day = now.astimezone(tz).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    starts = []
    for _ in range(days):
        if day.weekday() < 5:
            t = day.replace(hour=s.working_hours_start)
            end_of_day = day.replace(hour=s.working_hours_end)
            while t + duration <= end_of_day:
                starts.append(t)
                t += timedelta(minutes=30)
        day += timedelta(days=1)
    return starts


def spread(starts: list[datetime], count: int) -> list[datetime]:
    """Pick up to `count` slots, one per day where possible, varying the time of day."""
    by_day: dict = {}
    for t in starts:
        by_day.setdefault(t.date(), []).append(t)
    picked = []
    for i, day in enumerate(sorted(by_day)):
        options = by_day[day]
        picked.append(options[(i * 4) % len(options)])  # rotate through morning/afternoon
        if len(picked) == count:
            return picked
    for t in starts:  # fewer free days than slots wanted: fill from what's left
        if len(picked) == count:
            break
        if t not in picked:
            picked.append(t)
    return sorted(picked)


class LocalCalendar:
    """Default: no real calendar. Proposes working-hours slots; meetings are recorded only."""

    name = "local"

    def free_slots(self, attendees, *, count, duration, now=None):
        return spread(candidate_starts(now or datetime.now(UTC), duration), count)

    def create_meeting(self, *, subject, body, start, duration, attendees):
        return Meeting(event_id=None, join_url=None, provider=self.name)


class GraphCalendar:
    """Outlook free/busy for the interviewers, and Teams meetings on the sender's calendar."""

    name = "graph"

    def __init__(self, client: GraphClient):
        self.client = client

    def busy_periods(self, attendees: list[str], start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
        r = self.client.request(
            "POST",
            f"/users/{self.client.sender}/calendar/getSchedule",
            json={
                "schedules": attendees,
                "startTime": {"dateTime": _utc_naive(start), "timeZone": "UTC"},
                "endTime": {"dateTime": _utc_naive(end), "timeZone": "UTC"},
                "availabilityViewInterval": 30,
            },
            headers={"Prefer": 'outlook.timezone="UTC"'},
        )
        periods = []
        for schedule in r.json().get("value", []):
            for item in schedule.get("scheduleItems", []):
                if item.get("status") in BUSY:
                    periods.append((_parse_utc(item["start"]["dateTime"]), _parse_utc(item["end"]["dateTime"])))
        return periods

    def free_slots(self, attendees, *, count, duration, now=None):
        starts = candidate_starts(now or datetime.now(UTC), duration)
        if not starts:
            return []
        busy = self.busy_periods(attendees or [self.client.sender], starts[0], starts[-1] + duration)
        free = [t for t in starts if not any(t < b_end and t + duration > b_start for b_start, b_end in busy)]
        return spread(free, count)

    def create_meeting(self, *, subject, body, start, duration, attendees):
        r = self.client.request(
            "POST",
            f"/users/{self.client.sender}/events",
            json={
                "subject": subject,
                "body": {"contentType": "Text", "content": body},
                "start": {"dateTime": _utc_naive(start), "timeZone": "UTC"},
                "end": {"dateTime": _utc_naive(start + duration), "timeZone": "UTC"},
                "attendees": [
                    {"emailAddress": {"address": email, "name": name}, "type": "required"} for email, name in attendees
                ],
                "isOnlineMeeting": True,
                "onlineMeetingProvider": "teamsForBusiness",
                "allowNewTimeProposals": True,
            },
        )
        event = r.json()
        # Exchange emails the invitation (with the Teams link) to every attendee automatically.
        return Meeting(event_id=event.get("id"), join_url=(event.get("onlineMeeting") or {}).get("joinUrl"), provider=self.name)


def _utc_naive(t: datetime) -> str:
    return t.astimezone(UTC).replace(tzinfo=None).isoformat(timespec="seconds")


def _parse_utc(value: str) -> datetime:
    # Graph returns e.g. "2019-03-15T12:00:00.0000000" (7 fractional digits) in the requested zone.
    return datetime.fromisoformat(value[:19]).replace(tzinfo=UTC)


@lru_cache
def get_calendar() -> Calendar:
    s = get_settings()
    return GraphCalendar(GraphClient(s)) if s.calendar_provider == "graph" else LocalCalendar()
