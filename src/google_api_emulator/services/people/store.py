from __future__ import annotations

from typing import Any

from google_api_emulator.auth import User
from google_api_emulator.db import Database
from google_api_emulator.errors import invalid_argument, not_found
from google_api_emulator.services.people.person import (
    apply_field_mask,
    dump_person,
    ensure_person,
    load_person,
    new_etag,
    validate_singletons,
)


class PeopleStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    def resolve_resource_name(self, user: User, resource_name: str) -> str:
        if resource_name in {"people/me", "me"}:
            return user.profile_resource_name
        return resource_name

    def list_contacts(self, user: User) -> list[dict[str, Any]]:
        rows = self.db.fetchall(
            """
            SELECT person_json FROM people
            WHERE user_id = ? AND kind = 'contact' AND deleted = 0
            ORDER BY resource_name
            """,
            (user.id,),
        )
        return [load_person(row["person_json"]) for row in rows]

    def list_other_contacts(self, user: User) -> list[dict[str, Any]]:
        rows = self.db.fetchall(
            """
            SELECT person_json FROM people
            WHERE user_id = ? AND kind = 'other_contact' AND deleted = 0
            ORDER BY resource_name
            """,
            (user.id,),
        )
        return [load_person(row["person_json"]) for row in rows]

    def get(self, user: User, resource_name: str) -> dict[str, Any]:
        resolved = self.resolve_resource_name(user, resource_name)
        row = self.db.fetchone(
            """
            SELECT person_json FROM people
            WHERE user_id = ? AND resource_name = ? AND deleted = 0
            """,
            (user.id, resolved),
        )
        if row is None:
            raise not_found(f"Resource name {resource_name} was not found.")
        return load_person(row["person_json"])

    def create_contact(self, user: User, body: dict[str, Any]) -> dict[str, Any]:
        validate_singletons(body)
        person = ensure_person(body, kind="contact")
        self.db.execute(
            """
            INSERT INTO people (resource_name, user_id, kind, etag, person_json, deleted)
            VALUES (?, ?, 'contact', ?, ?, 0)
            """,
            (person["resourceName"], user.id, person["etag"], dump_person(person)),
        )
        return person

    def update_contact(
        self,
        user: User,
        resource_name: str,
        body: dict[str, Any],
        update_fields: list[str],
    ) -> dict[str, Any]:
        current = self.get(user, resource_name)
        incoming_etag = body.get("etag") or ((body.get("metadata") or {}).get("sources") or [{}])[0].get("etag")
        if not incoming_etag:
            raise invalid_argument("etag is required.")
        if incoming_etag != current["etag"]:
            raise invalid_argument("The person etag does not match.")
        if "memberships" in update_fields and not body.get("memberships"):
            raise invalid_argument("memberships must include at least one contact group membership.")
        for field in update_fields:
            if field in body:
                current[field] = body[field]
            else:
                current.pop(field, None)
        validate_singletons(current)
        etag = new_etag()
        current["etag"] = etag
        metadata = dict(current.get("metadata") or {})
        sources = [dict(s) for s in metadata.get("sources") or []]
        if sources:
            sources[0]["etag"] = etag
        metadata["sources"] = sources
        current["metadata"] = metadata
        resolved = current["resourceName"]
        self.db.execute(
            """
            UPDATE people SET etag = ?, person_json = ?
            WHERE user_id = ? AND resource_name = ?
            """,
            (etag, dump_person(current), user.id, resolved),
        )
        return current

    def delete_contact(self, user: User, resource_name: str) -> None:
        person = self.get(user, resource_name)
        if person["resourceName"] == user.profile_resource_name:
            raise invalid_argument("Cannot delete the authenticated user profile.")
        self.db.execute(
            "DELETE FROM people WHERE user_id = ? AND resource_name = ? AND kind = 'contact'",
            (user.id, person["resourceName"]),
        )


def masked(person: dict[str, Any], mask: str | None) -> dict[str, Any]:
    return apply_field_mask(person, mask)
