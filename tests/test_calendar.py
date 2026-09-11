from __future__ import annotations

from fastapi.testclient import TestClient

AUTH = {"Authorization": "Bearer test-token"}
CAL = "/services/calendar/calendar/v3"


def test_calendar_list_and_primary(client: TestClient):
    listed = client.get(f"{CAL}/users/me/calendarList", headers=AUTH)
    assert listed.status_code == 200
    items = listed.json()["items"]
    assert items[0]["id"] == "alice@example.com"
    assert items[0]["primary"] is True
    assert items[0]["summary"] == "Alice"

    primary = client.get(f"{CAL}/calendars/primary", headers=AUTH)
    assert primary.status_code == 200
    assert primary.json()["id"] == "alice@example.com"
    assert primary.json()["timeZone"] == "America/Los_Angeles"

    by_email = client.get(f"{CAL}/calendars/alice@example.com", headers=AUTH)
    assert by_email.json()["id"] == "alice@example.com"

    missing = client.get(f"{CAL}/calendars/missing", headers=AUTH)
    assert missing.status_code == 404


def test_list_and_get_events(client: TestClient):
    listed = client.get(f"{CAL}/calendars/primary/events", headers=AUTH)
    assert listed.status_code == 200
    ids = {item["id"] for item in listed.json()["items"]}
    assert ids == {"evt1", "evt2"}
    assert listed.json()["kind"] == "calendar#events"

    lunch = client.get(f"{CAL}/calendars/primary/events/evt1", headers=AUTH)
    assert lunch.status_code == 200
    body = lunch.json()
    assert body["summary"] == "Lunch with Bob"
    assert body["start"]["dateTime"] == "2026-01-15T12:00:00-08:00"
    assert body["attendees"][0]["email"] == "bob@example.com"
    assert "etag" in body

    allday = client.get(f"{CAL}/calendars/primary/events/evt2", headers=AUTH)
    assert allday.json()["start"]["date"] == "2026-01-16"


def test_event_query_and_time_bounds(client: TestClient):
    lunch = client.get(f"{CAL}/calendars/primary/events", params={"q": "bob"}, headers=AUTH)
    assert {item["id"] for item in lunch.json()["items"]} == {"evt1"}

    window = client.get(
        f"{CAL}/calendars/primary/events",
        params={"timeMin": "2026-01-15T00:00:00-08:00", "timeMax": "2026-01-15T23:59:59-08:00"},
        headers=AUTH,
    )
    assert {item["id"] for item in window.json()["items"]} == {"evt1"}

    later = client.get(
        f"{CAL}/calendars/primary/events",
        params={"timeMin": "2026-01-18T00:00:00Z"},
        headers=AUTH,
    )
    assert later.json()["items"] == []


def test_insert_patch_etag_delete(client: TestClient):
    created = client.post(
        f"{CAL}/calendars/primary/events",
        json={
            "summary": "Focus time",
            "start": {"dateTime": "2026-01-20T10:00:00-08:00"},
            "end": {"dateTime": "2026-01-20T11:00:00-08:00"},
        },
        headers=AUTH,
    )
    assert created.status_code == 200
    event_id = created.json()["id"]
    etag = created.json()["etag"]
    assert created.json()["status"] == "confirmed"

    patched = client.patch(
        f"{CAL}/calendars/primary/events/{event_id}",
        json={"summary": "Deep work", "etag": etag},
        headers=AUTH,
    )
    assert patched.status_code == 200
    assert patched.json()["summary"] == "Deep work"
    assert patched.json()["etag"] != etag

    stale = client.patch(
        f"{CAL}/calendars/primary/events/{event_id}",
        json={"summary": "stale"},
        headers={**AUTH, "If-Match": etag},
    )
    assert stale.status_code == 412
    assert stale.json()["error"]["status"] == "FAILED_PRECONDITION"

    deleted = client.delete(f"{CAL}/calendars/primary/events/{event_id}", headers=AUTH)
    assert deleted.status_code == 204
    listed = client.get(f"{CAL}/calendars/primary/events", headers=AUTH)
    assert event_id not in {item["id"] for item in listed.json()["items"]}
    with_deleted = client.get(
        f"{CAL}/calendars/primary/events",
        params={"showDeleted": True},
        headers=AUTH,
    )
    cancelled = next(item for item in with_deleted.json()["items"] if item["id"] == event_id)
    assert cancelled["status"] == "cancelled"
    got = client.get(f"{CAL}/calendars/primary/events/{event_id}", headers=AUTH)
    assert got.json()["status"] == "cancelled"


def test_secondary_calendar_and_reset(client: TestClient):
    created = client.post(f"{CAL}/calendars", json={"summary": "Work"}, headers=AUTH)
    assert created.status_code == 200
    calendar_id = created.json()["id"]
    listed = client.get(f"{CAL}/users/me/calendarList", headers=AUTH)
    ids = {item["id"] for item in listed.json()["items"]}
    assert calendar_id in ids
    client.post(
        f"{CAL}/calendars/{calendar_id}/events",
        json={
            "summary": "Standup",
            "start": {"dateTime": "2026-02-01T09:00:00-08:00"},
            "end": {"dateTime": "2026-02-01T09:30:00-08:00"},
        },
        headers=AUTH,
    )
    primary_delete = client.delete(f"{CAL}/calendars/primary", headers=AUTH)
    assert primary_delete.status_code == 400
    client.delete(f"{CAL}/calendars/{calendar_id}", headers=AUTH)
    assert client.get(f"{CAL}/calendars/{calendar_id}", headers=AUTH).status_code == 404

    client.post("/reset")
    listed = client.get(f"{CAL}/calendars/primary/events", headers=AUTH)
    assert {item["id"] for item in listed.json()["items"]} == {"evt1", "evt2"}


def test_free_busy(client: TestClient):
    response = client.post(
        f"{CAL}/freeBusy",
        json={
            "timeMin": "2026-01-15T00:00:00-08:00",
            "timeMax": "2026-01-15T23:59:59-08:00",
            "items": [{"id": "primary"}, {"id": "missing@example.com"}],
        },
        headers=AUTH,
    )
    assert response.status_code == 200
    calendars = response.json()["calendars"]
    assert calendars["alice@example.com"]["busy"]
    assert calendars["alice@example.com"]["busy"][0]["start"]
    assert calendars["missing@example.com"]["errors"][0]["reason"] == "notFound"


def test_calendar_requires_auth(client: TestClient):
    response = client.get(f"{CAL}/calendars/primary/events")
    assert response.status_code == 401
    assert response.json()["error"]["status"] == "UNAUTHENTICATED"


def test_python_client_base_url(client: TestClient):
    listed = client.get("/services/calendar/users/me/calendarList", headers=AUTH)
    assert listed.status_code == 200
    assert listed.json()["items"][0]["id"] == "alice@example.com"
