from __future__ import annotations

from fastapi.testclient import TestClient

KEY = {"X-Goog-Api-Key": "test-token"}
MASK_SEARCH = {"X-Goog-FieldMask": "places.id,places.displayName"}
MASK_DETAIL = {"X-Goog-FieldMask": "id,displayName,formattedAddress"}
PLACES = "/services/places/v1"


def test_places_requires_auth(client: TestClient):
    response = client.post(
        f"{PLACES}/places:searchText",
        json={"textQuery": "coffee"},
        headers=MASK_SEARCH,
    )
    assert response.status_code == 401
    assert response.json()["error"]["status"] == "UNAUTHENTICATED"


def test_places_accepts_api_key_and_bearer(client: TestClient):
    by_key = client.get(
        f"{PLACES}/places/ChIJCafe1",
        headers={**KEY, **MASK_DETAIL},
    )
    assert by_key.status_code == 200
    assert by_key.json()["id"] == "ChIJCafe1"
    assert by_key.json()["displayName"]["text"] == "Blue Bottle Coffee"

    by_bearer = client.get(
        f"{PLACES}/places/ChIJCafe1",
        headers={"Authorization": "Bearer test-token", **MASK_DETAIL},
    )
    assert by_bearer.status_code == 200


def test_places_requires_field_mask(client: TestClient):
    response = client.post(
        f"{PLACES}/places:searchText",
        json={"textQuery": "coffee"},
        headers=KEY,
    )
    assert response.status_code == 400
    assert "FieldMask" in response.json()["error"]["message"]


def test_search_text(client: TestClient):
    response = client.post(
        f"{PLACES}/places:searchText",
        json={"textQuery": "coffee"},
        headers={**KEY, **MASK_SEARCH},
    )
    assert response.status_code == 200
    ids = {place["id"] for place in response.json()["places"]}
    assert ids == {"ChIJCafe1"}
    assert "formattedAddress" not in response.json()["places"][0]

    missing_query = client.post(
        f"{PLACES}/places:searchText",
        json={},
        headers={**KEY, **MASK_SEARCH},
    )
    assert missing_query.status_code == 400


def test_search_nearby(client: TestClient):
    nearby = client.post(
        f"{PLACES}/places:searchNearby",
        json={
            "includedTypes": ["cafe"],
            "locationRestriction": {
                "circle": {
                    "center": {"latitude": 37.7955, "longitude": -122.3937},
                    "radius": 500.0,
                }
            },
        },
        headers={**KEY, **MASK_SEARCH},
    )
    assert nearby.status_code == 200
    assert {place["id"] for place in nearby.json()["places"]} == {"ChIJCafe1"}

    far = client.post(
        f"{PLACES}/places:searchNearby",
        json={
            "locationRestriction": {
                "circle": {
                    "center": {"latitude": 40.0, "longitude": -74.0},
                    "radius": 100.0,
                }
            }
        },
        headers={**KEY, **MASK_SEARCH},
    )
    assert far.json()["places"] == []

    missing_circle = client.post(
        f"{PLACES}/places:searchNearby",
        json={},
        headers={**KEY, **MASK_SEARCH},
    )
    assert missing_circle.status_code == 400


def test_get_and_autocomplete(client: TestClient):
    missing = client.get(
        f"{PLACES}/places/missing",
        headers={**KEY, **MASK_DETAIL},
    )
    assert missing.status_code == 404

    suggestions = client.post(
        f"{PLACES}/places:autocomplete",
        json={"input": "Blue"},
        headers={**KEY, "X-Goog-FieldMask": "suggestions.placePrediction.placeId"},
    )
    assert suggestions.status_code == 200
    ids = {
        item["placePrediction"]["placeId"]
        for item in suggestions.json()["suggestions"]
    }
    assert ids == {"ChIJCafe1"}

    warmup = client.post(
        f"{PLACES}/places:autocomplete",
        json={"input": ""},
        headers={**KEY, "X-Goog-FieldMask": "*"},
    )
    assert suggestions_empty(warmup.json())


def test_places_reset(client: TestClient):
    client.post(
        f"{PLACES}/places:searchText",
        json={"textQuery": "coffee"},
        headers={**KEY, **MASK_SEARCH},
    )
    client.post("/reset")
    listed = client.get(
        f"{PLACES}/places/ChIJPark3",
        headers={**KEY, "X-Goog-FieldMask": "id,displayName"},
    )
    assert listed.json()["displayName"]["text"] == "Golden Gate Park"


def suggestions_empty(body: dict) -> bool:
    return not body.get("suggestions")
