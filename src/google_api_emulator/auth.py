from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from google_api_emulator.errors import unauthenticated
from google_api_emulator.state import EmulatorState


@dataclass(frozen=True)
class User:
    id: str
    email: str
    profile_resource_name: str
    token: str


def _state(request: Request) -> EmulatorState:
    return request.app.state.emulator


def bearer_token(request: Request) -> str:
    header = request.headers.get("Authorization")
    if not header or not header.startswith("Bearer "):
        raise unauthenticated("Request is missing required authentication credential.")
    token = header.removeprefix("Bearer ").strip()
    if not token:
        raise unauthenticated("Request is missing required authentication credential.")
    return token


def maps_token(request: Request) -> str:
    header = request.headers.get("Authorization")
    if header and header.startswith("Bearer "):
        token = header.removeprefix("Bearer ").strip()
        if token:
            return token
        raise unauthenticated("Request is missing required authentication credential.")
    api_key = (request.headers.get("x-goog-api-key") or "").strip()
    if api_key:
        return api_key
    raise unauthenticated("Request is missing required authentication credential.")


def require_user(request: Request) -> User:
    return user_from_token(request, bearer_token(request))


def require_maps_user(request: Request) -> User:
    return user_from_token(request, maps_token(request))


def user_from_token(request: Request, token: str) -> User:
    state = _state(request)
    if state.allowed_tokens is not None and token not in state.allowed_tokens:
        raise unauthenticated("Request had invalid authentication credentials.")

    row = state.db.fetchone(
        """
        SELECT users.id, users.email, people.resource_name
        FROM tokens
        JOIN users ON users.id = tokens.user_id
        JOIN people ON people.user_id = users.id AND people.kind = 'profile'
        WHERE tokens.token = ?
        """,
        (token,),
    )
    if row is not None:
        return User(
            id=row["id"],
            email=row["email"],
            profile_resource_name=row["resource_name"],
            token=token,
        )

    if state.default_user_id is None:
        raise unauthenticated("Request had invalid authentication credentials.")

    default = state.db.fetchone(
        """
        SELECT users.id, users.email, people.resource_name
        FROM users
        JOIN people ON people.user_id = users.id AND people.kind = 'profile'
        WHERE users.id = ?
        """,
        (state.default_user_id,),
    )
    if default is None:
        raise unauthenticated("Request had invalid authentication credentials.")
    return User(
        id=default["id"],
        email=default["email"],
        profile_resource_name=default["resource_name"],
        token=token,
    )


def require_places_credential(request: Request) -> str:
    header = request.headers.get("Authorization")
    token = ""
    if header and header.startswith("Bearer "):
        token = header.removeprefix("Bearer ").strip()
    if not token:
        token = (request.headers.get("X-Goog-Api-Key") or "").strip()
    if not token:
        token = (request.query_params.get("key") or "").strip()
    if not token:
        raise unauthenticated("Request is missing required authentication credential.")

    state = _state(request)
    if state.allowed_tokens is not None and token not in state.allowed_tokens:
        raise unauthenticated("Request had invalid authentication credentials.")
    return token
