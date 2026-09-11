from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from google_api_emulator.db import Database
from google_api_emulator.services.people.person import dump_person, ensure_person


class UserFixture(BaseModel):
    model_config = ConfigDict(extra="ignore")

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
