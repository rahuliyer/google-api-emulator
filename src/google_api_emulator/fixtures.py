from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from google_api_emulator.db import Database
from google_api_emulator.services.gmail.mime import build_rfc822, parse_date
from google_api_emulator.services.people.person import dump_person, ensure_person


class UserFixture(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str
    email: str
    tokens: list[str] = Field(default_factory=list)
    profile: dict[str, Any] = Field(default_factory=dict)
    contacts: list[dict[str, Any]] = Field(default_factory=list)
    otherContacts: list[dict[str, Any]] = Field(default_factory=list)


class PeopleFixtureFile(BaseModel):
    users: list[UserFixture]


class AllowedTokensFile(BaseModel):
    tokens: list[str] = Field(default_factory=list)


class GmailAttachmentFixture(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    filename: str
    mimeType: str = "application/octet-stream"
    text: str | None = None
    data: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "filename": self.filename,
            "mimeType": self.mimeType,
            "text": self.text,
            "data": self.data,
        }


class GmailMessageFixture(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str | None = None
    threadId: str | None = None
    labelIds: list[str] = Field(default_factory=lambda: ["INBOX"])
    from_: str = Field(default="noreply@example.com", alias="from")
    to: list[str] | str = Field(default_factory=list)
    cc: list[str] | str | None = None
    bcc: list[str] | str | None = None
    subject: str = ""
    body: str = ""
    date: str | None = None
    attachments: list[GmailAttachmentFixture] = Field(default_factory=list)


class GmailDraftFixture(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str | None = None
    from_: str | None = Field(default=None, alias="from")
    to: list[str] | str | None = None
    subject: str = ""
    body: str = ""
    attachments: list[GmailAttachmentFixture] = Field(default_factory=list)


class GmailLabelFixture(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str | None = None
    name: str


class GmailUserFixture(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    email: str
    labels: list[GmailLabelFixture] = Field(default_factory=list)
    messages: list[GmailMessageFixture] = Field(default_factory=list)
    drafts: list[GmailDraftFixture] = Field(default_factory=list)


class GmailFixtureFile(BaseModel):
    users: list[GmailUserFixture] = Field(default_factory=list)


class CalendarEventFixture(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str | None = None
    summary: str = ""
    description: str | None = None
    location: str | None = None
    start: dict[str, Any]
    end: dict[str, Any]
    attendees: list[dict[str, Any]] = Field(default_factory=list)
    status: str | None = None
    transparency: str | None = None

    def as_body(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "summary": self.summary,
            "description": self.description,
            "location": self.location,
            "start": self.start,
            "end": self.end,
            "attendees": self.attendees,
            "status": self.status,
            "transparency": self.transparency,
        }


class CalendarCalendarFixture(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str | None = None
    summary: str = "Primary"
    timeZone: str = "America/Los_Angeles"
    description: str | None = None
    location: str | None = None
    events: list[CalendarEventFixture] = Field(default_factory=list)


class CalendarUserFixture(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    email: str
    calendars: list[CalendarCalendarFixture] = Field(default_factory=list)


class CalendarFixtureFile(BaseModel):
    users: list[CalendarUserFixture] = Field(default_factory=list)


def load_allowed_tokens(fixtures_dir: Path) -> set[str] | None:
    path = fixtures_dir / "allowed_tokens.json"
    if not path.is_file():
        return None
    payload = AllowedTokensFile.model_validate_json(path.read_text())
    return set(payload.tokens)


def load_people_fixture(fixtures_dir: Path) -> PeopleFixtureFile:
    path = fixtures_dir / "people.json"
    if not path.is_file():
        raise FileNotFoundError(f"People fixture not found: {path}")
    return PeopleFixtureFile.model_validate_json(path.read_text())


def seed_people(db: Database, fixture: PeopleFixtureFile) -> None:
    with db.locked() as conn:
        for user in fixture.users:
            profile = ensure_person(user.profile, kind="profile")
            profile_name = profile["resourceName"]
            conn.execute(
                "INSERT INTO users (id, email, profile_json) VALUES (?, ?, ?)",
                (user.id, user.email, dump_person(profile)),
            )
            conn.execute(
                """
                INSERT INTO people (resource_name, user_id, kind, etag, person_json, deleted)
                VALUES (?, ?, ?, ?, ?, 0)
                """,
                (profile_name, user.id, "profile", profile["etag"], dump_person(profile)),
            )
            for token in user.tokens:
                conn.execute(
                    "INSERT INTO tokens (token, user_id) VALUES (?, ?)",
                    (token, user.id),
                )
            for contact in user.contacts:
                person = ensure_person(contact, kind="contact")
                conn.execute(
                    """
                    INSERT INTO people (resource_name, user_id, kind, etag, person_json, deleted)
                    VALUES (?, ?, ?, ?, ?, 0)
                    """,
                    (person["resourceName"], user.id, "contact", person["etag"], dump_person(person)),
                )
            for other in user.otherContacts:
                person = ensure_person(other, kind="other_contact")
                conn.execute(
                    """
                    INSERT INTO people (resource_name, user_id, kind, etag, person_json, deleted)
                    VALUES (?, ?, ?, ?, ?, 0)
                    """,
                    (person["resourceName"], user.id, "other_contact", person["etag"], dump_person(person)),
                )
        conn.commit()


def load_gmail_fixture(fixtures_dir: Path) -> GmailFixtureFile | None:
    path = fixtures_dir / "gmail.json"
    if not path.is_file():
        return None
    return GmailFixtureFile.model_validate_json(path.read_text())


def seed_gmail(db: Database, fixture: GmailFixtureFile | None) -> None:
    from google_api_emulator.services.gmail.store import GmailStore

    store = GmailStore(db)
    users = db.fetchall("SELECT id, email FROM users")
    by_email = {row["email"].lower(): row["id"] for row in users}
    for user in users:
        store.ensure_mailbox(user["id"])
    if fixture is None:
        return
    for mailbox in fixture.users:
        user_id = by_email.get(mailbox.email.lower())
        if user_id is None:
            continue
        store.ensure_mailbox(user_id)
        for label in mailbox.labels:
            body: dict = {"name": label.name}
            if label.id:
                body["id"] = label.id
            store.create_label(user_id, body)
        for message in mailbox.messages:
            raw = build_rfc822(
                from_addr=message.from_,
                to=message.to,
                subject=message.subject,
                body=message.body,
                date=parse_date(message.date),
                cc=message.cc,
                bcc=message.bcc,
                attachments=[item.as_dict() for item in message.attachments],
            )
            store.insert_message(
                user_id,
                raw=raw,
                label_ids=list(message.labelIds),
                thread_id=message.threadId,
                message_id=message.id,
            )
        for draft in mailbox.drafts:
            raw = build_rfc822(
                from_addr=draft.from_ or mailbox.email,
                to=draft.to or [],
                subject=draft.subject,
                body=draft.body,
                attachments=[item.as_dict() for item in draft.attachments],
            )
            resource = store.insert_message(
                user_id,
                raw=raw,
                label_ids=["DRAFT"],
            )
            draft_id = draft.id or f"r-{resource_id(resource)}"
            db.execute(
                "INSERT INTO gmail_drafts (id, user_id, message_id) VALUES (?, ?, ?)",
                (draft_id, user_id, resource["id"]),
            )


def load_calendar_fixture(fixtures_dir: Path) -> CalendarFixtureFile | None:
    path = fixtures_dir / "calendar.json"
    if not path.is_file():
        return None
    return CalendarFixtureFile.model_validate_json(path.read_text())


def seed_calendar(db: Database, fixture: CalendarFixtureFile | None) -> None:
    from google_api_emulator.auth import User
    from google_api_emulator.services.calendar.store import CalendarStore

    store = CalendarStore(db)
    users = db.fetchall("SELECT id, email FROM users")
    by_email = {row["email"].lower(): row for row in users}
    for user in users:
        store.ensure_primary(user["id"], user["email"])
    if fixture is None:
        return
    for mailbox in fixture.users:
        row = by_email.get(mailbox.email.lower())
        if row is None:
            continue
        owner = User(id=row["id"], email=row["email"], profile_resource_name="", token="")
        for calendar in mailbox.calendars:
            requested_id = calendar.id or "primary"
            resolved = store.resolve_calendar_id(owner, requested_id)
            existing = db.fetchone(
                "SELECT calendar_id FROM calendar_calendars WHERE user_id = ? AND calendar_id = ?",
                (owner.id, resolved),
            )
            fields = {
                "summary": calendar.summary,
                "timeZone": calendar.timeZone,
                "description": calendar.description,
                "location": calendar.location,
            }
            if existing is None:
                body = dict(fields)
                if requested_id not in {"primary", owner.email}:
                    body["id"] = requested_id
                store.create_calendar(owner, body)
            else:
                store.patch_calendar(owner, resolved, fields, None)
            for event in calendar.events:
                store.insert_event(owner, resolved, event.as_body())


def resource_id(resource: dict) -> str:
    return resource["id"][:12]


class PlaceFixture(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    id: str
    name: str | None = None

    def as_place(self) -> dict[str, Any]:
        data = self.model_dump(exclude_none=True)
        data["id"] = self.id
        data["name"] = self.name or f"places/{self.id}"
        return data


class PlacesFixtureFile(BaseModel):
    places: list[PlaceFixture] = Field(default_factory=list)


def load_places_fixture(fixtures_dir: Path) -> PlacesFixtureFile | None:
    path = fixtures_dir / "places.json"
    if not path.is_file():
        return None
    return PlacesFixtureFile.model_validate_json(path.read_text())


def seed_places(db: Database, fixture: PlacesFixtureFile | None) -> None:
    if fixture is None:
        return
    from google_api_emulator.services.places.store import PlacesStore

    store = PlacesStore(db)
    for place in fixture.places:
        store.upsert(place.as_place())


class RouteFixture(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    id: str
    origin: dict[str, Any]
    destination: dict[str, Any]
    travelMode: str | None = None
    route: dict[str, Any]
    alternatives: list[dict[str, Any]] = Field(default_factory=list)

    def as_record(self) -> dict[str, Any]:
        return self.model_dump(exclude_none=True)


class RoutesFixtureFile(BaseModel):
    routes: list[RouteFixture] = Field(default_factory=list)


def load_routes_fixture(fixtures_dir: Path) -> RoutesFixtureFile | None:
    path = fixtures_dir / "routes.json"
    if not path.is_file():
        return None
    return RoutesFixtureFile.model_validate_json(path.read_text())


def seed_routes(db: Database, fixture: RoutesFixtureFile | None) -> None:
    if fixture is None:
        return
    from google_api_emulator.services.routes.store import RoutesStore

    store = RoutesStore(db)
    for record in fixture.routes:
        store.upsert(record.as_record())
