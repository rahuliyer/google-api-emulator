from __future__ import annotations

import copy
import hashlib
import json
import uuid
from datetime import date, datetime, time, timezone
from typing import Any
from urllib.parse import unquote
from zoneinfo import ZoneInfo

from google_api_emulator.auth import User
from google_api_emulator.db import Database
from google_api_emulator.errors import invalid_argument, not_found, precondition_failed
from google_api_emulator.services.people.pagination import paginate

DEFAULT_TZ = "America/Los_Angeles"
DEFAULT_REMINDERS = [{"method": "popup", "minutes": 10}]
EVENT_PATCH_FIELDS = frozenset(
    {
        "summary",
        "description",
        "location",
        "start",
        "end",
        "attendees",
        "status",
        "transparency",
        "visibility",
        "recurrence",
        "reminders",
        "colorId",
        "extendedProperties",
        "conferenceData",
        "hangoutLink",
    }
)
CALENDAR_PATCH_FIELDS = frozenset({"summary", "description", "location", "timeZone"})


def dump_json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def load_json(raw: str) -> Any:
    return json.loads(raw)


def new_etag() -> str:
    return f'"{hashlib.sha256(uuid.uuid4().bytes).hexdigest()[:16]}"'


def new_event_id() -> str:
    return uuid.uuid4().hex[:26]


def new_calendar_id() -> str:
    return f"{uuid.uuid4().hex[:16]}@group.calendar.google.com"


def compact(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: compact(item) for key, item in value.items() if item is not None}
    if isinstance(value, list):
        return [compact(item) for item in value]
    return value


def normalize_etag(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip().strip('"')


def rfc3339(value: datetime) -> str:
    dt = value.astimezone(timezone.utc).replace(microsecond=0)
    return dt.isoformat().replace("+00:00", "Z")


def parse_rfc3339(value: str, fallback_tz: str) -> datetime:
    text = value.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as exc:
        raise invalid_argument(f"Invalid RFC3339 datetime: {value}") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(fallback_tz))
    return dt


def event_bounds(start: dict[str, Any], end: dict[str, Any], calendar_tz: str) -> tuple[int, int]:
    start_has_date = "date" in start
    end_has_date = "date" in end
    start_has_dt = "dateTime" in start
    end_has_dt = "dateTime" in end
    if start_has_date != end_has_date or start_has_dt != end_has_dt or start_has_date == start_has_dt:
        raise invalid_argument("Event start and end must both be date or both be dateTime.")
    tz_name = start.get("timeZone") or end.get("timeZone") or calendar_tz
    if start_has_date:
        start_d = date.fromisoformat(start["date"])
        end_d = date.fromisoformat(end["date"])
        tz = ZoneInfo(tz_name)
        start_dt = datetime.combine(start_d, time.min, tzinfo=tz)
        end_dt = datetime.combine(end_d, time.min, tzinfo=tz)
    else:
        start_dt = parse_rfc3339(start["dateTime"], tz_name)
        end_dt = parse_rfc3339(end["dateTime"], tz_name)
    if end_dt <= start_dt:
        raise invalid_argument("Event end must be after start.")
    return int(start_dt.timestamp() * 1000), int(end_dt.timestamp() * 1000)


def parse_bound(value: str | None, calendar_tz: str) -> int | None:
    if not value:
        return None
    return int(parse_rfc3339(value, calendar_tz).timestamp() * 1000)


class CalendarStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    def resolve_calendar_id(self, user: User, calendar_id: str) -> str:
        decoded = unquote(calendar_id)
        if decoded in {"primary", user.email}:
            return user.email
        return decoded

    def _calendar_row(self, user_id: str, calendar_id: str):
        row = self.db.fetchone(
            """
            SELECT calendar_id, etag, primary_cal, calendar_json, list_json
            FROM calendar_calendars
            WHERE user_id = ? AND calendar_id = ?
            """,
            (user_id, calendar_id),
        )
        if row is None:
            raise not_found(f"Not Found")
        return row

    def get_calendar(self, user: User, calendar_id: str) -> dict[str, Any]:
        resolved = self.resolve_calendar_id(user, calendar_id)
        return load_json(self._calendar_row(user.id, resolved)["calendar_json"])

    def get_calendar_list_entry(self, user: User, calendar_id: str) -> dict[str, Any]:
        resolved = self.resolve_calendar_id(user, calendar_id)
        return load_json(self._calendar_row(user.id, resolved)["list_json"])

    def list_calendar_list(self, user: User, max_results: int, page_token: str | None) -> dict[str, Any]:
        rows = self.db.fetchall(
            """
            SELECT list_json FROM calendar_calendars
            WHERE user_id = ?
            ORDER BY primary_cal DESC, calendar_id
            """,
            (user.id,),
        )
        items = [load_json(row["list_json"]) for row in rows]
        page, next_token = paginate(items, max_results, page_token)
        body: dict[str, Any] = {
            "kind": "calendar#calendarList",
            "etag": new_etag(),
            "items": page,
        }
        if next_token:
            body["nextPageToken"] = next_token
        return body

    def ensure_primary(self, user_id: str, email: str, summary: str = "Primary", time_zone: str = DEFAULT_TZ) -> None:
        existing = self.db.fetchone(
            "SELECT calendar_id FROM calendar_calendars WHERE user_id = ? AND primary_cal = 1",
            (user_id,),
        )
        if existing is not None:
            return
        self._insert_calendar(
            user_id,
            calendar_id=email,
            summary=summary,
            time_zone=time_zone,
            primary=True,
        )

    def create_calendar(self, user: User, body: dict[str, Any]) -> dict[str, Any]:
        summary = (body or {}).get("summary")
        if not summary:
            raise invalid_argument("Missing calendar summary.")
        calendar_id = body.get("id") or new_calendar_id()
        if calendar_id in {"primary", user.email}:
            raise invalid_argument("Cannot create another primary calendar.")
        return self._insert_calendar(
            user.id,
            calendar_id=calendar_id,
            summary=summary,
            description=body.get("description"),
            location=body.get("location"),
            time_zone=body.get("timeZone") or DEFAULT_TZ,
            primary=False,
        )

    def patch_calendar(self, user: User, calendar_id: str, body: dict[str, Any], if_match: str | None) -> dict[str, Any]:
        resolved = self.resolve_calendar_id(user, calendar_id)
        row = self._calendar_row(user.id, resolved)
        self._check_etag(row["etag"], if_match, body)
        calendar = load_json(row["calendar_json"])
        entry = load_json(row["list_json"])
        for field in CALENDAR_PATCH_FIELDS:
            if field in (body or {}):
                calendar[field] = body[field]
                entry[field] = body[field]
        return self._save_calendar(user.id, resolved, calendar, entry, primary=bool(row["primary_cal"]))

    def delete_calendar(self, user: User, calendar_id: str) -> None:
        resolved = self.resolve_calendar_id(user, calendar_id)
        row = self._calendar_row(user.id, resolved)
        if row["primary_cal"]:
            raise invalid_argument("Cannot delete the primary calendar.")
        self.db.execute(
            "DELETE FROM calendar_events WHERE user_id = ? AND calendar_id = ?",
            (user.id, resolved),
        )
        self.db.execute(
            "DELETE FROM calendar_calendars WHERE user_id = ? AND calendar_id = ?",
            (user.id, resolved),
        )

    def clear_calendar(self, user: User, calendar_id: str) -> None:
        resolved = self.resolve_calendar_id(user, calendar_id)
        self._calendar_row(user.id, resolved)
        self.db.execute(
            "DELETE FROM calendar_events WHERE user_id = ? AND calendar_id = ?",
            (user.id, resolved),
        )

    def list_events(
        self,
        user: User,
        calendar_id: str,
        *,
        max_results: int,
        page_token: str | None,
        time_min: str | None,
        time_max: str | None,
        query: str | None,
        show_deleted: bool,
        order_by: str | None,
    ) -> dict[str, Any]:
        resolved = self.resolve_calendar_id(user, calendar_id)
        calendar = load_json(self._calendar_row(user.id, resolved)["calendar_json"])
        tz_name = calendar.get("timeZone") or DEFAULT_TZ
        min_ms = parse_bound(time_min, tz_name)
        max_ms = parse_bound(time_max, tz_name)
        rows = self.db.fetchall(
            """
            SELECT event_json, status, start_ms, end_ms FROM calendar_events
            WHERE user_id = ? AND calendar_id = ?
            """,
            (user.id, resolved),
        )
        events: list[dict[str, Any]] = []
        for row in rows:
            if not show_deleted and row["status"] == "cancelled":
                continue
            if min_ms is not None and int(row["end_ms"]) <= min_ms:
                continue
            if max_ms is not None and int(row["start_ms"]) >= max_ms:
                continue
            event = load_json(row["event_json"])
            if query and not self._event_matches(event, query):
                continue
            events.append(event)
        if (order_by or "startTime") == "updated":
            events.sort(key=lambda item: item.get("updated") or "")
        else:
            events.sort(key=lambda item: (item.get("start", {}).get("dateTime") or item.get("start", {}).get("date") or "", item["id"]))
        page, next_token = paginate(events, max_results, page_token)
        body: dict[str, Any] = {
            "kind": "calendar#events",
            "etag": new_etag(),
            "summary": calendar.get("summary"),
            "timeZone": tz_name,
            "updated": rfc3339(datetime.now(timezone.utc)),
            "accessRole": "owner",
            "defaultReminders": DEFAULT_REMINDERS,
            "items": page,
        }
        if next_token:
            body["nextPageToken"] = next_token
        return compact(body)

    def get_event(self, user: User, calendar_id: str, event_id: str) -> dict[str, Any]:
        resolved = self.resolve_calendar_id(user, calendar_id)
        row = self.db.fetchone(
            """
            SELECT event_json FROM calendar_events
            WHERE user_id = ? AND calendar_id = ? AND event_id = ?
            """,
            (user.id, resolved, event_id),
        )
        if row is None:
            raise not_found("Not Found")
        return load_json(row["event_json"])

    def insert_event(self, user: User, calendar_id: str, body: dict[str, Any]) -> dict[str, Any]:
        resolved = self.resolve_calendar_id(user, calendar_id)
        calendar = load_json(self._calendar_row(user.id, resolved)["calendar_json"])
        event_id = body.get("id") or new_event_id()
        existing = self.db.fetchone(
            "SELECT event_id FROM calendar_events WHERE user_id = ? AND calendar_id = ? AND event_id = ?",
            (user.id, resolved, event_id),
        )
        if existing is not None:
            raise invalid_argument(f"Event {event_id} already exists.")
        event = self._build_event(user, calendar, body, event_id=event_id, created=True)
        start_ms, end_ms = event_bounds(event["start"], event["end"], calendar.get("timeZone") or DEFAULT_TZ)
        self.db.execute(
            """
            INSERT INTO calendar_events
                (user_id, calendar_id, event_id, etag, status, start_ms, end_ms, event_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (user.id, resolved, event["id"], event["etag"], event["status"], start_ms, end_ms, dump_json(event)),
        )
        return event

    def patch_event(
        self,
        user: User,
        calendar_id: str,
        event_id: str,
        body: dict[str, Any],
        if_match: str | None,
        replace: bool,
    ) -> dict[str, Any]:
        resolved = self.resolve_calendar_id(user, calendar_id)
        calendar = load_json(self._calendar_row(user.id, resolved)["calendar_json"])
        row = self.db.fetchone(
            """
            SELECT etag, event_json FROM calendar_events
            WHERE user_id = ? AND calendar_id = ? AND event_id = ?
            """,
            (user.id, resolved, event_id),
        )
        if row is None:
            raise not_found("Not Found")
        self._check_etag(row["etag"], if_match, body)
        current = load_json(row["event_json"])
        if replace:
            merged = self._build_event(
                user,
                calendar,
                body,
                event_id=event_id,
                created=False,
                existing=current,
            )
        else:
            patch = {key: value for key, value in (body or {}).items() if key in EVENT_PATCH_FIELDS}
            merged_body = copy.deepcopy(current)
            merged_body.update(patch)
            merged = self._build_event(
                user,
                calendar,
                merged_body,
                event_id=event_id,
                created=False,
                existing=current,
            )
        start_ms, end_ms = event_bounds(merged["start"], merged["end"], calendar.get("timeZone") or DEFAULT_TZ)
        self.db.execute(
            """
            UPDATE calendar_events
            SET etag = ?, status = ?, start_ms = ?, end_ms = ?, event_json = ?
            WHERE user_id = ? AND calendar_id = ? AND event_id = ?
            """,
            (merged["etag"], merged["status"], start_ms, end_ms, dump_json(merged), user.id, resolved, event_id),
        )
        return merged

    def delete_event(self, user: User, calendar_id: str, event_id: str, if_match: str | None) -> None:
        resolved = self.resolve_calendar_id(user, calendar_id)
        row = self.db.fetchone(
            """
            SELECT etag, event_json FROM calendar_events
            WHERE user_id = ? AND calendar_id = ? AND event_id = ?
            """,
            (user.id, resolved, event_id),
        )
        if row is None:
            raise not_found("Not Found")
        self._check_etag(row["etag"], if_match, None)
        event = load_json(row["event_json"])
        event["status"] = "cancelled"
        event["etag"] = new_etag()
        event["updated"] = rfc3339(datetime.now(timezone.utc))
        event["sequence"] = int(event.get("sequence") or 0) + 1
        self.db.execute(
            """
            UPDATE calendar_events
            SET etag = ?, status = 'cancelled', event_json = ?
            WHERE user_id = ? AND calendar_id = ? AND event_id = ?
            """,
            (event["etag"], dump_json(event), user.id, resolved, event_id),
        )

    def free_busy(self, user: User, body: dict[str, Any]) -> dict[str, Any]:
        time_min = (body or {}).get("timeMin")
        time_max = (body or {}).get("timeMax")
        if not time_min or not time_max:
            raise invalid_argument("timeMin and timeMax are required.")
        items = (body or {}).get("items") or []
        calendars: dict[str, Any] = {}
        for item in items:
            requested = (item or {}).get("id")
            if not requested:
                continue
            try:
                resolved = self.resolve_calendar_id(user, requested)
                calendar = load_json(self._calendar_row(user.id, resolved)["calendar_json"])
            except Exception:
                calendars[requested] = {"errors": [{"domain": "calendar", "reason": "notFound"}]}
                continue
            tz_name = calendar.get("timeZone") or DEFAULT_TZ
            min_ms = parse_bound(time_min, tz_name)
            max_ms = parse_bound(time_max, tz_name)
            rows = self.db.fetchall(
                """
                SELECT event_json, status, start_ms, end_ms FROM calendar_events
                WHERE user_id = ? AND calendar_id = ?
                """,
                (user.id, resolved),
            )
            busy = []
            for row in rows:
                event = load_json(row["event_json"])
                if row["status"] == "cancelled" or event.get("transparency") == "transparent":
                    continue
                if min_ms is not None and int(row["end_ms"]) <= min_ms:
                    continue
                if max_ms is not None and int(row["start_ms"]) >= max_ms:
                    continue
                start = event["start"].get("dateTime") or self._date_as_datetime(event["start"]["date"], tz_name, end=False)
                end = event["end"].get("dateTime") or self._date_as_datetime(event["end"]["date"], tz_name, end=True)
                busy.append({"start": start, "end": end})
            calendars[resolved] = {"busy": busy}
        return {
            "kind": "calendar#freeBusy",
            "timeMin": time_min,
            "timeMax": time_max,
            "calendars": calendars,
        }

    def _date_as_datetime(self, value: str, calendar_tz: str, *, end: bool) -> str:
        day = date.fromisoformat(value)
        dt = datetime.combine(day, time.min, tzinfo=ZoneInfo(calendar_tz))
        return rfc3339(dt)

    def _event_matches(self, event: dict[str, Any], query: str) -> bool:
        needle = query.casefold()
        haystacks = [
            event.get("summary") or "",
            event.get("description") or "",
            event.get("location") or "",
        ]
        for attendee in event.get("attendees") or []:
            haystacks.append(attendee.get("email") or "")
            haystacks.append(attendee.get("displayName") or "")
        return any(needle in text.casefold() for text in haystacks)

    def _check_etag(self, current: str, if_match: str | None, body: dict[str, Any] | None) -> None:
        current_n = normalize_etag(current)
        if if_match and if_match.strip() != "*":
            if normalize_etag(if_match) != current_n:
                raise precondition_failed("Precondition Failed")
            return
        if body and body.get("etag") and normalize_etag(str(body["etag"])) != current_n:
            raise precondition_failed("Precondition Failed")

    def _insert_calendar(
        self,
        user_id: str,
        *,
        calendar_id: str,
        summary: str,
        time_zone: str,
        primary: bool,
        description: str | None = None,
        location: str | None = None,
    ) -> dict[str, Any]:
        etag = new_etag()
        calendar = compact(
            {
                "kind": "calendar#calendar",
                "etag": etag,
                "id": calendar_id,
                "summary": summary,
                "description": description,
                "location": location,
                "timeZone": time_zone,
            }
        )
        entry = compact(
            {
                "kind": "calendar#calendarListEntry",
                "etag": etag,
                "id": calendar_id,
                "summary": summary,
                "description": description,
                "location": location,
                "timeZone": time_zone,
                "accessRole": "owner",
                "primary": True if primary else None,
                "selected": True,
                "defaultReminders": DEFAULT_REMINDERS,
            }
        )
        self.db.execute(
            """
            INSERT INTO calendar_calendars
                (user_id, calendar_id, etag, primary_cal, calendar_json, list_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user_id, calendar_id, etag, 1 if primary else 0, dump_json(calendar), dump_json(entry)),
        )
        return calendar

    def _save_calendar(
        self,
        user_id: str,
        calendar_id: str,
        calendar: dict[str, Any],
        entry: dict[str, Any],
        *,
        primary: bool,
    ) -> dict[str, Any]:
        etag = new_etag()
        calendar["etag"] = etag
        entry["etag"] = etag
        calendar = compact(calendar)
        entry = compact(entry)
        self.db.execute(
            """
            UPDATE calendar_calendars
            SET etag = ?, primary_cal = ?, calendar_json = ?, list_json = ?
            WHERE user_id = ? AND calendar_id = ?
            """,
            (etag, 1 if primary else 0, dump_json(calendar), dump_json(entry), user_id, calendar_id),
        )
        return calendar

    def _build_event(
        self,
        user: User,
        calendar: dict[str, Any],
        body: dict[str, Any],
        *,
        event_id: str,
        created: bool,
        existing: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        start = (body or {}).get("start")
        end = (body or {}).get("end")
        if not start or not end:
            raise invalid_argument("Missing start or end.")
        now = rfc3339(datetime.now(timezone.utc))
        created_at = (existing or {}).get("created") or now
        sequence = int((existing or {}).get("sequence") or 0)
        if not created:
            sequence += 1
        attendees = []
        for attendee in body.get("attendees") or []:
            item = dict(attendee)
            email = item.get("email")
            if email and email.lower() == user.email.lower():
                item["self"] = True
            item.setdefault("responseStatus", "needsAction")
            attendees.append(compact(item))
        event = compact(
            {
                "kind": "calendar#event",
                "etag": new_etag(),
                "id": event_id,
                "status": body.get("status") or "confirmed",
                "htmlLink": f"https://www.google.com/calendar/event?eid={event_id}",
                "created": created_at,
                "updated": now,
                "summary": body.get("summary"),
                "description": body.get("description"),
                "location": body.get("location"),
                "colorId": body.get("colorId"),
                "creator": (existing or {}).get("creator")
                or {"email": user.email, "self": True},
                "organizer": (existing or {}).get("organizer")
                or {"email": user.email, "self": True, "displayName": calendar.get("summary")},
                "start": start,
                "end": end,
                "transparency": body.get("transparency"),
                "visibility": body.get("visibility"),
                "iCalUID": (existing or {}).get("iCalUID") or f"{event_id}@google.com",
                "sequence": sequence,
                "attendees": attendees or None,
                "reminders": body.get("reminders") or {"useDefault": True},
                "recurrence": body.get("recurrence"),
                "extendedProperties": body.get("extendedProperties"),
                "conferenceData": body.get("conferenceData"),
            }
        )
        event_bounds(event["start"], event["end"], calendar.get("timeZone") or DEFAULT_TZ)
        return event
