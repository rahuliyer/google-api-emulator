from __future__ import annotations

import copy
import hashlib
import json
import uuid
from typing import Any

PERSON_FIELDS = frozenset(
    {
        "addresses",
        "ageRanges",
        "biographies",
        "birthdays",
        "calendarUrls",
        "clientData",
        "coverPhotos",
        "emailAddresses",
        "events",
        "externalIds",
        "genders",
        "imClients",
        "interests",
        "locales",
        "locations",
        "memberships",
        "metadata",
        "miscKeywords",
        "names",
        "nicknames",
        "occupations",
        "organizations",
        "phoneNumbers",
        "photos",
        "relations",
        "sipAddresses",
        "skills",
        "urls",
        "userDefined",
    }
)

MASK_ALWAYS = frozenset({"resourceName", "etag", "metadata"})
SINGLETON_FIELDS = ("names", "birthdays", "genders", "biographies")
MY_CONTACTS = {
    "contactGroupMembership": {
        "contactGroupId": "myContacts",
        "contactGroupResourceName": "contactGroups/myContacts",
    }
}


def new_etag() -> str:
    raw = uuid.uuid4().bytes
    return hashlib.sha256(raw).hexdigest()[:22]


def new_contact_resource_name() -> str:
    return f"people/c{uuid.uuid4().hex[:16]}"


def new_other_contact_resource_name() -> str:
    return f"otherContacts/{uuid.uuid4().hex[:16]}"


def _source_id(resource_name: str) -> str:
    return resource_name.rsplit("/", 1)[-1]


def _source_type(kind: str) -> str:
    if kind == "profile":
        return "PROFILE"
    if kind == "other_contact":
        return "OTHER_CONTACT"
    return "CONTACT"


def ensure_person(person: dict[str, Any], *, kind: str, resource_name: str | None = None) -> dict[str, Any]:
    data = copy.deepcopy(person)
    if resource_name:
        data["resourceName"] = resource_name
    elif not data.get("resourceName"):
        if kind == "other_contact":
            data["resourceName"] = new_other_contact_resource_name()
        elif kind == "profile":
            data["resourceName"] = f"people/{_source_id(data.get('resourceName') or 'me')}"
            if data["resourceName"] == "people/me":
                data["resourceName"] = f"people/{uuid.uuid4().hex[:16]}"
        else:
            data["resourceName"] = new_contact_resource_name()

    etag = data.get("etag") or new_etag()
    data["etag"] = etag
    source_id = _source_id(data["resourceName"])
    metadata = dict(data.get("metadata") or {})
    sources = metadata.get("sources")
    if not sources:
        sources = [{"type": _source_type(kind), "id": source_id, "etag": etag}]
    else:
        sources = [dict(s) for s in sources]
        sources[0]["etag"] = etag
        sources[0].setdefault("type", _source_type(kind))
        sources[0].setdefault("id", source_id)
    metadata["sources"] = sources
    metadata.setdefault("objectType", "PERSON")
    data["metadata"] = metadata

    if kind == "contact" and not data.get("memberships"):
        data["memberships"] = [copy.deepcopy(MY_CONTACTS)]
    return data


def apply_field_mask(person: dict[str, Any], mask: str | None) -> dict[str, Any]:
    if not mask:
        return copy.deepcopy(person)
    fields = {part.strip() for part in mask.split(",") if part.strip()}
    keep = MASK_ALWAYS | fields
    return {key: value for key, value in person.items() if key in keep}


def parse_mask(mask: str | None) -> list[str]:
    if not mask:
        return []
    return [part.strip() for part in mask.split(",") if part.strip()]


def validate_mask_fields(mask: str, *, required: bool, name: str) -> list[str]:
    fields = parse_mask(mask)
    if required and not fields:
        raise_missing_mask(name)
    unknown = [field for field in fields if field not in PERSON_FIELDS]
    if unknown:
        from google_api_emulator.errors import invalid_argument

        raise invalid_argument(
            f"Invalid {name}: {', '.join(unknown)}. Valid fields: {', '.join(sorted(PERSON_FIELDS))}"
        )
    return fields


def raise_missing_mask(name: str) -> None:
    from google_api_emulator.errors import invalid_argument

    raise invalid_argument(f"{name} is required")


def validate_singletons(person: dict[str, Any]) -> None:
    from google_api_emulator.errors import invalid_argument

    for field in SINGLETON_FIELDS:
        value = person.get(field)
        if isinstance(value, list) and len(value) > 1:
            raise invalid_argument(
                f"Singleton field {field} cannot have more than one value."
            )


def dump_person(person: dict[str, Any]) -> str:
    return json.dumps(person, separators=(",", ":"), ensure_ascii=False)


def load_person(raw: str) -> dict[str, Any]:
    return json.loads(raw)
