from __future__ import annotations

from fastapi.testclient import TestClient

KEY = {"X-Goog-Api-Key": "test-token"}
MASK_ROUTES = {"X-Goog-FieldMask": "routes.duration,routes.distanceMeters,routes.polyline.encodedPolyline"}
MASK_MATRIX = {"X-Goog-FieldMask": "originIndex,destinationIndex,duration,distanceMeters,status,condition"}
ROUTES = "/services/routes"

FERRY_TO_ZUNI = {
    "origin": {"placeId": "ChIJCafe1"},
    "destination": {"placeId": "ChIJRest2"},
    "travelMode": "DRIVE",
}


def test_routes_requires_auth(client: TestClient):
    response = client.post(
        f"{ROUTES}/directions/v2:computeRoutes",
        json=FERRY_TO_ZUNI,
        headers=MASK_ROUTES,
    )
    assert response.status_code == 401
    assert response.json()["error"]["status"] == "UNAUTHENTICATED"


def test_routes_accepts_api_key_and_bearer(client: TestClient):
    by_key = client.post(
        f"{ROUTES}/directions/v2:computeRoutes",
        json=FERRY_TO_ZUNI,
        headers={**KEY, **MASK_ROUTES},
    )
    assert by_key.status_code == 200
    assert by_key.json()["routes"][0]["distanceMeters"] == 4200

    by_bearer = client.post(
        f"{ROUTES}/directions/v2:computeRoutes",
        json=FERRY_TO_ZUNI,
        headers={"Authorization": "Bearer test-token", **MASK_ROUTES},
    )
    assert by_bearer.status_code == 200


def test_routes_requires_field_mask(client: TestClient):
    response = client.post(
        f"{ROUTES}/directions/v2:computeRoutes",
        json=FERRY_TO_ZUNI,
        headers=KEY,
    )
    assert response.status_code == 400
    assert "FieldMask" in response.json()["error"]["message"]


def test_compute_routes_fixture(client: TestClient):
    response = client.post(
        f"{ROUTES}/directions/v2:computeRoutes",
        json=FERRY_TO_ZUNI,
        headers={**KEY, **MASK_ROUTES},
    )
    assert response.status_code == 200
    route = response.json()["routes"][0]
    assert route["duration"] == "720s"
    assert route["distanceMeters"] == 4200
    assert route["polyline"]["encodedPolyline"] == "_p~iF~ps|U_ulLnnqC"
    assert "legs" not in route

    by_address = client.post(
        f"{ROUTES}/directions/v2:computeRoutes",
        json={
            "origin": {"address": "1 Ferry Building"},
            "destination": {"address": "1658 Market St"},
        },
        headers={**KEY, **MASK_ROUTES},
    )
    assert by_address.status_code == 200
    assert by_address.json()["routes"][0]["distanceMeters"] == 4200


def test_compute_routes_missing_origin_destination(client: TestClient):
    missing = client.post(
        f"{ROUTES}/directions/v2:computeRoutes",
        json={"destination": {"placeId": "ChIJRest2"}},
        headers={**KEY, **MASK_ROUTES},
    )
    assert missing.status_code == 400
    assert missing.json()["error"]["status"] == "INVALID_ARGUMENT"


def test_compute_routes_routing_preference_requires_drive(client: TestClient):
    response = client.post(
        f"{ROUTES}/directions/v2:computeRoutes",
        json={
            **FERRY_TO_ZUNI,
            "travelMode": "WALK",
            "routingPreference": "TRAFFIC_AWARE",
        },
        headers={**KEY, **MASK_ROUTES},
    )
    assert response.status_code == 400
    assert response.json()["error"]["status"] == "INVALID_ARGUMENT"


def test_compute_routes_optimize_requires_mask_field(client: TestClient):
    response = client.post(
        f"{ROUTES}/directions/v2:computeRoutes",
        json={**FERRY_TO_ZUNI, "optimizeWaypointOrder": True},
        headers={**KEY, **MASK_ROUTES},
    )
    assert response.status_code == 400
    assert "optimizedIntermediateWaypointIndex" in response.json()["error"]["message"]


def test_compute_routes_geodesic_fallback(client: TestClient):
    response = client.post(
        f"{ROUTES}/directions/v2:computeRoutes",
        json={
            "origin": {"location": {"latLng": {"latitude": 37.0, "longitude": -122.0}}},
            "destination": {"location": {"latLng": {"latitude": 37.1, "longitude": -122.0}}},
            "travelMode": "DRIVE",
        },
        headers={**KEY, **MASK_ROUTES},
    )
    assert response.status_code == 200
    route = response.json()["routes"][0]
    assert route["distanceMeters"] > 10_000
    assert route["duration"].endswith("s")
    assert route["polyline"]["encodedPolyline"]


def test_compute_route_matrix(client: TestClient):
    response = client.post(
        f"{ROUTES}/distanceMatrix/v2:computeRouteMatrix",
        json={
            "origins": [{"waypoint": {"placeId": "ChIJCafe1"}}],
            "destinations": [
                {"waypoint": {"placeId": "ChIJRest2"}},
                {"waypoint": {"location": {"latLng": {"latitude": 37.1, "longitude": -122.0}}}},
            ],
            "travelMode": "DRIVE",
        },
        headers={**KEY, **MASK_MATRIX},
    )
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    assert len(body) == 2
    assert body[0]["originIndex"] == 0
    assert body[0]["destinationIndex"] == 0
    assert body[0]["condition"] == "ROUTE_EXISTS"
    assert body[0]["status"] == {}
    assert body[0]["distanceMeters"] == 4200
    assert body[0]["duration"] == "720s"
    assert body[1]["destinationIndex"] == 1
    assert body[1]["distanceMeters"] > 1000
