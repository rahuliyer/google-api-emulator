from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, Query, Request, Response

from google_api_emulator.auth import User, require_user
from google_api_emulator.errors import invalid_argument
from google_api_emulator.services.calendar.store import CalendarStore


def _store(request: Request) -> CalendarStore:
    return CalendarStore(request.app.state.emulator.db)


def _max_results(value: int | None, default: int, cap: int) -> int:
    if value is None or value == 0:
        return default
    if value < 1:
        raise invalid_argument("maxResults must be at least 1.")
    return min(value, cap)


def _calendar_router(prefix: str) -> APIRouter:
    router = APIRouter(prefix=prefix, dependencies=[Depends(require_user)])

    @router.get("/users/me/calendarList")
    def list_calendar_list(
        request: Request,
        user: User = Depends(require_user),
        maxResults: int | None = Query(default=None),
        pageToken: str | None = Query(default=None),
    ) -> dict[str, Any]:
        return _store(request).list_calendar_list(
            user,
            max_results=_max_results(maxResults, 100, 250),
            page_token=pageToken,
        )

    @router.get("/users/me/calendarList/{calendar_id}")
    def get_calendar_list_entry(
        request: Request,
        calendar_id: str,
        user: User = Depends(require_user),
    ) -> dict[str, Any]:
        return _store(request).get_calendar_list_entry(user, calendar_id)

    @router.post("/calendars")
    def insert_calendar(
        request: Request,
        body: dict[str, Any],
        user: User = Depends(require_user),
    ) -> dict[str, Any]:
        return _store(request).create_calendar(user, body)

    @router.get("/calendars/{calendar_id}")
    def get_calendar(
        request: Request,
        calendar_id: str,
        user: User = Depends(require_user),
    ) -> dict[str, Any]:
        return _store(request).get_calendar(user, calendar_id)

    @router.patch("/calendars/{calendar_id}")
    def patch_calendar(
        request: Request,
        calendar_id: str,
        body: dict[str, Any],
        user: User = Depends(require_user),
        if_match: str | None = Header(default=None, alias="If-Match"),
    ) -> dict[str, Any]:
        return _store(request).patch_calendar(user, calendar_id, body, if_match)

    @router.put("/calendars/{calendar_id}")
    def update_calendar(
        request: Request,
        calendar_id: str,
        body: dict[str, Any],
        user: User = Depends(require_user),
        if_match: str | None = Header(default=None, alias="If-Match"),
    ) -> dict[str, Any]:
        return _store(request).patch_calendar(user, calendar_id, body, if_match)

    @router.delete("/calendars/{calendar_id}")
    def delete_calendar(
        request: Request,
        calendar_id: str,
        user: User = Depends(require_user),
    ) -> Response:
        _store(request).delete_calendar(user, calendar_id)
        return Response(status_code=204)

    @router.post("/calendars/{calendar_id}/clear")
    def clear_calendar(
        request: Request,
        calendar_id: str,
        user: User = Depends(require_user),
    ) -> Response:
        _store(request).clear_calendar(user, calendar_id)
        return Response(status_code=204)

    @router.get("/calendars/{calendar_id}/events")
    def list_events(
        request: Request,
        calendar_id: str,
        user: User = Depends(require_user),
        maxResults: int | None = Query(default=None),
        pageToken: str | None = Query(default=None),
        timeMin: str | None = Query(default=None),
        timeMax: str | None = Query(default=None),
        q: str | None = Query(default=None),
        showDeleted: bool = Query(default=False),
        orderBy: str | None = Query(default=None),
        singleEvents: bool | None = Query(default=None),
    ) -> dict[str, Any]:
        del singleEvents
        return _store(request).list_events(
            user,
            calendar_id,
            max_results=_max_results(maxResults, 250, 2500),
            page_token=pageToken,
            time_min=timeMin,
            time_max=timeMax,
            query=q,
            show_deleted=showDeleted,
            order_by=orderBy,
        )

    @router.post("/calendars/{calendar_id}/events")
    def insert_event(
        request: Request,
        calendar_id: str,
        body: dict[str, Any],
        user: User = Depends(require_user),
        sendUpdates: str | None = Query(default=None),
        conferenceDataVersion: int | None = Query(default=None),
    ) -> dict[str, Any]:
        del sendUpdates, conferenceDataVersion
        return _store(request).insert_event(user, calendar_id, body)

    @router.get("/calendars/{calendar_id}/events/{event_id}")
    def get_event(
        request: Request,
        calendar_id: str,
        event_id: str,
        user: User = Depends(require_user),
    ) -> dict[str, Any]:
        return _store(request).get_event(user, calendar_id, event_id)

    @router.patch("/calendars/{calendar_id}/events/{event_id}")
    def patch_event(
        request: Request,
        calendar_id: str,
        event_id: str,
        body: dict[str, Any],
        user: User = Depends(require_user),
        if_match: str | None = Header(default=None, alias="If-Match"),
        sendUpdates: str | None = Query(default=None),
    ) -> dict[str, Any]:
        del sendUpdates
        return _store(request).patch_event(user, calendar_id, event_id, body, if_match, replace=False)

    @router.put("/calendars/{calendar_id}/events/{event_id}")
    def update_event(
        request: Request,
        calendar_id: str,
        event_id: str,
        body: dict[str, Any],
        user: User = Depends(require_user),
        if_match: str | None = Header(default=None, alias="If-Match"),
        sendUpdates: str | None = Query(default=None),
    ) -> dict[str, Any]:
        del sendUpdates
        return _store(request).patch_event(user, calendar_id, event_id, body, if_match, replace=True)

    @router.delete("/calendars/{calendar_id}/events/{event_id}")
    def delete_event(
        request: Request,
        calendar_id: str,
        event_id: str,
        user: User = Depends(require_user),
        if_match: str | None = Header(default=None, alias="If-Match"),
        sendUpdates: str | None = Query(default=None),
    ) -> Response:
        del sendUpdates
        _store(request).delete_event(user, calendar_id, event_id, if_match)
        return Response(status_code=204)

    @router.post("/freeBusy")
    def query_free_busy(
        request: Request,
        body: dict[str, Any],
        user: User = Depends(require_user),
    ) -> dict[str, Any]:
        return _store(request).free_busy(user, body)

    return router


# Host swap: www.googleapis.com → /services/calendar, then Google’s /calendar/v3/...
router = _calendar_router("/services/calendar/calendar/v3")
# google-api-python-client replaces baseUrl (already includes /calendar/v3).
client_router = _calendar_router("/services/calendar")
