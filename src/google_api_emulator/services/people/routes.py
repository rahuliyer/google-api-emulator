from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from google_api_emulator.auth import User, require_user
from google_api_emulator.errors import GoogleAPIError, invalid_argument
from google_api_emulator.services.people.pagination import paginate
from google_api_emulator.services.people.person import validate_mask_fields
from google_api_emulator.services.people.search import person_matches
from google_api_emulator.services.people.store import PeopleStore, masked
from google_api_emulator.state import EmulatorState

router = APIRouter(prefix="/services/people", dependencies=[Depends(require_user)])


def _state(request: Request) -> EmulatorState:
    return request.app.state.emulator


def _store(request: Request) -> PeopleStore:
    return PeopleStore(_state(request).db)


def _connections_page_size(page_size: int | None) -> int:
    if page_size is None or page_size == 0:
        return 100
    if page_size < 1:
        raise invalid_argument("pageSize must be at least 1.")
    return min(page_size, 1000)


def _search_page_size(page_size: int | None) -> int:
    if page_size is None or page_size == 0:
        return 10
    if page_size < 1:
        raise invalid_argument("pageSize must be at least 1.")
    return min(page_size, 30)


@router.get("/v1/people/me/connections")
def list_connections(
    request: Request,
    user: User = Depends(require_user),
    personFields: str | None = Query(default=None),
    pageSize: int | None = Query(default=None),
    pageToken: str | None = Query(default=None),
    sources: list[str] | None = Query(default=None),
) -> dict[str, Any]:
    del sources
    validate_mask_fields(personFields or "", required=True, name="personFields")
    store = _store(request)
    contacts = store.list_contacts(user)
    page, next_token = paginate(contacts, _connections_page_size(pageSize), pageToken)
    body: dict[str, Any] = {
        "connections": [masked(person, personFields) for person in page],
        "totalPeople": len(contacts),
        "totalItems": len(contacts),
    }
    if next_token:
        body["nextPageToken"] = next_token
    return body


@router.get("/v1/people:batchGet")
def batch_get(
    request: Request,
    user: User = Depends(require_user),
    resourceNames: list[str] | None = Query(default=None),
    personFields: str | None = Query(default=None),
    sources: list[str] | None = Query(default=None),
) -> dict[str, Any]:
    del sources
    validate_mask_fields(personFields or "", required=True, name="personFields")
    names = resourceNames or []
    if not names:
        raise invalid_argument("resourceNames is required.")
    if len(names) > 200:
        raise invalid_argument("resourceNames exceeds the maximum of 200.")
    store = _store(request)
    responses = []
    for name in names:
        try:
            person = store.get(user, name)
            responses.append(
                {
                    "requestedResourceName": name,
                    "httpStatusCode": 200,
                    "person": masked(person, personFields),
                }
            )
        except GoogleAPIError as exc:
            if exc.status != "NOT_FOUND":
                raise
            responses.append(
                {
                    "requestedResourceName": name,
                    "httpStatusCode": 404,
                    "status": {"code": 5, "message": exc.message},
                }
            )
    return {"responses": responses}


@router.post("/v1/people:createContact")
def create_contact(
    request: Request,
    body: dict[str, Any],
    user: User = Depends(require_user),
    personFields: str | None = Query(default=None),
    sources: list[str] | None = Query(default=None),
) -> dict[str, Any]:
    del sources
    if personFields:
        validate_mask_fields(personFields, required=False, name="personFields")
    person = _store(request).create_contact(user, body)
    return masked(person, personFields)


@router.get("/v1/people:searchContacts")
def search_contacts(
    request: Request,
    user: User = Depends(require_user),
    query: str | None = Query(default=None),
    readMask: str | None = Query(default=None),
    pageSize: int | None = Query(default=None),
    sources: list[str] | None = Query(default=None),
) -> dict[str, Any]:
    del sources
    if query is None:
        raise invalid_argument("query is required.")
    validate_mask_fields(readMask or "", required=True, name="readMask")
    matches = [
        person
        for person in _store(request).list_contacts(user)
        if person_matches(person, query, include_organizations=True)
    ]
    page, _ = paginate(matches, _search_page_size(pageSize), None)
    return {"results": [{"person": masked(person, readMask)} for person in page]}


@router.get("/v1/otherContacts")
def list_other_contacts(
    request: Request,
    user: User = Depends(require_user),
    readMask: str | None = Query(default=None),
    pageSize: int | None = Query(default=None),
    pageToken: str | None = Query(default=None),
) -> dict[str, Any]:
    validate_mask_fields(readMask or "", required=True, name="readMask")
    contacts = _store(request).list_other_contacts(user)
    page, next_token = paginate(contacts, _connections_page_size(pageSize), pageToken)
    body: dict[str, Any] = {
        "otherContacts": [masked(person, readMask) for person in page],
    }
    if next_token:
        body["nextPageToken"] = next_token
    return body


@router.get("/v1/otherContacts:search")
def search_other_contacts(
    request: Request,
    user: User = Depends(require_user),
    query: str | None = Query(default=None),
    readMask: str | None = Query(default=None),
    pageSize: int | None = Query(default=None),
) -> dict[str, Any]:
    if query is None:
        raise invalid_argument("query is required.")
    validate_mask_fields(readMask or "", required=True, name="readMask")
    matches = [
        person
        for person in _store(request).list_other_contacts(user)
        if person_matches(person, query, include_organizations=False)
    ]
    page, _ = paginate(matches, _search_page_size(pageSize), None)
    return {"results": [{"person": masked(person, readMask)} for person in page]}


@router.get("/v1/people/me")
def get_me(
    request: Request,
    user: User = Depends(require_user),
    personFields: str | None = Query(default=None),
    sources: list[str] | None = Query(default=None),
) -> dict[str, Any]:
    del sources
    validate_mask_fields(personFields or "", required=True, name="personFields")
    person = _store(request).get(user, "people/me")
    return masked(person, personFields)


@router.get("/v1/people/{person_id}")
def get_person(
    request: Request,
    person_id: str,
    user: User = Depends(require_user),
    personFields: str | None = Query(default=None),
    sources: list[str] | None = Query(default=None),
) -> dict[str, Any]:
    del sources
    validate_mask_fields(personFields or "", required=True, name="personFields")
    person = _store(request).get(user, f"people/{person_id}")
    return masked(person, personFields)


@router.patch("/v1/people/{person_id}:updateContact")
def update_contact(
    request: Request,
    person_id: str,
    body: dict[str, Any],
    user: User = Depends(require_user),
    updatePersonFields: str | None = Query(default=None),
    personFields: str | None = Query(default=None),
    sources: list[str] | None = Query(default=None),
) -> dict[str, Any]:
    del sources
    fields = validate_mask_fields(updatePersonFields or "", required=True, name="updatePersonFields")
    if personFields:
        validate_mask_fields(personFields, required=False, name="personFields")
    person = _store(request).update_contact(user, f"people/{person_id}", body, fields)
    return masked(person, personFields)


@router.delete("/v1/people/{person_id}:deleteContact")
def delete_contact(
    request: Request,
    person_id: str,
    user: User = Depends(require_user),
) -> dict[str, Any]:
    _store(request).delete_contact(user, f"people/{person_id}")
    return {}
