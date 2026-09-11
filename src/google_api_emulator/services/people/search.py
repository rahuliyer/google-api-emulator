from __future__ import annotations

from typing import Any


def prefix_match(query: str, text: str) -> bool:
    q = query.casefold()
    t = text.casefold()
    if not q or not t:
        return False
    if t.startswith(q):
        return True
    return any(word.startswith(q) for word in t.split())


def _values(items: list[Any] | None, *keys: str) -> list[str]:
    texts: list[str] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        for key in keys:
            value = item.get(key)
            if isinstance(value, str) and value:
                texts.append(value)
    return texts


def searchable_texts(person: dict[str, Any], *, include_organizations: bool) -> list[str]:
    texts = []
    texts.extend(
        _values(
            person.get("names"),
            "displayName",
            "givenName",
            "familyName",
            "middleName",
            "unstructuredName",
            "displayNameLastFirst",
        )
    )
    texts.extend(_values(person.get("nicknames"), "value"))
    texts.extend(_values(person.get("emailAddresses"), "value"))
    texts.extend(_values(person.get("phoneNumbers"), "value"))
    if include_organizations:
        texts.extend(_values(person.get("organizations"), "name", "title"))
    return texts


def person_matches(person: dict[str, Any], query: str, *, include_organizations: bool) -> bool:
    if query == "":
        return False
    return any(prefix_match(query, text) for text in searchable_texts(person, include_organizations=include_organizations))
