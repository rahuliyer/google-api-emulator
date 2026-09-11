from __future__ import annotations

from fastapi.testclient import TestClient

AUTH = {"Authorization": "Bearer test-token"}
FIELD_MASK = {
    **AUTH,
    "X-Goog-FieldMask": "routes.duration,routes.distanceMeters,routes.polyline.encodedPolyline,routes.description,routes.legs,routes.routeLabels",
}
MATRIX_MASK = {
    **AUTH,
    "X-Goog-FieldMask": "originIndex,destinationIndex,status,condition,distanceMeters,duration,staticDuration",
}
MAPS = "/services/maps"


def test_compute_routes_fixture_by_address(client: TestClient):
    response = client.post(
        f"{MAPS}/directions/v2:computeRoutes",
        json={
            "origin": {"address": "San Francisco, CA"},
            "destination": {"address": "Los Angeles, CA"},
            "travelMode": "DRIVE",
        },
        headers=FIELD_MASK,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["routes"][0]["distanceMeters"] == 615337
    assert body["routes"][0]["duration"] == "19812s"
    assert body["routes"][0]["description"] == "I-5 S"
    assert "encodedPolyline" in body["routes"][0]["polyline"]
    assert "warnings" not in body["routes"][0]


def test_compute_routes_field_mask_and_alternates(client: TestClient):
    primary = client.post(
        f"{MAPS}/directions/v2:computeRoutes",
        json={
            "origin": {"address": "san francisco, ca"},
            "destination": {"address": "Los Angeles, CA"},
        },
        headers=FIELD_MASK,
    )
    assert len(primary.json()["routes"]) == 1

    alts = client.post(
        f"{MAPS}/directions/v2:computeRoutes",
        json={
            "origin": {"address": "San Francisco, CA"},
            "destination": {"address": "Los Angeles, CA"},
            "computeAlternativeRoutes": True,
        },
        headers=FIELD_MASK,
    )
    labels = [route.get("routeLabels") for route in alts.json()["routes"]]
    assert len(alts.json()["routes"]) == 2
    assert ["DEFAULT_ROUTE"] in labels
    assert ["DEFAULT_ROUTE_ALTERNATE"] in labels


def test_compute_routes_place_id_and_latlng(client: TestClient):
    by_place = client.post(
        f"{MAPS}/directions/v2:computeRoutes",
        json={
            "origin": {"placeId": "ChIJIQBpAG2ahYAR_6128GcTUEo"},
            "destination": {"placeId": "ChIJ9T_5iuTKj4ARe3GfygqMnbk"},
        },
        headers=FIELD_MASK,
    )
    assert by_place.json()["routes"][0]["distanceMeters"] == 76320

    by_latlng = client.post(
        f"{MAPS}/directions/v2:computeRoutes",
        json={
            "origin": {"location": {"latLng": {"latitude": 37.7749, "longitude": -122.4194}}},
            "destination": {"location": {"latLng": {"latitude": 37.3382, "longitude": -121.8863}}},
        },
        headers=FIELD_MASK,
    )
    assert by_latlng.json()["routes"][0]["description"] == "US-101 S"


def test_compute_routes_synthetic_latlng(client: TestClient):
    response = client.post(
        f"{MAPS}/directions/v2:computeRoutes",
        json={
            "origin": {"location": {"latLng": {"latitude": 37.419734, "longitude": -122.0827784}}},
            "destination": {"location": {"latLng": {"latitude": 37.417670, "longitude": -122.079595}}},
            "travelMode": "WALK",
        },
        headers=FIELD_MASK,
    )
    assert response.status_code == 200
    route = response.json()["routes"][0]
    assert route["distanceMeters"] > 0
    assert route["duration"].endswith("s")
    assert route["legs"][0]["steps"][0]["travelMode"] == "WALK"


def test_unknown_address_is_empty_routes(client: TestClient):
    response = client.post(
        f"{MAPS}/directions/v2:computeRoutes",
        json={
            "origin": {"address": "Unknown Origin"},
            "destination": {"address": "Unknown Destination"},
        },
        headers=FIELD_MASK,
    )
    assert response.status_code == 200
    assert response.json()["routes"] == []


def test_traffic_unaware_uses_static_duration(client: TestClient):
    response = client.post(
        f"{MAPS}/directions/v2:computeRoutes",
        json={
            "origin": {"address": "San Francisco, CA"},
            "destination": {"address": "Los Angeles, CA"},
            "travelMode": "DRIVE",
            "routingPreference": "TRAFFIC_UNAWARE",
        },
        headers=FIELD_MASK,
    )
    route = response.json()["routes"][0]
    assert route["duration"] == "18600s"


def test_compute_routes_validation(client: TestClient):
    missing_mask = client.post(
        f"{MAPS}/directions/v2:computeRoutes",
        json={"origin": {"address": "A"}, "destination": {"address": "B"}},
        headers=AUTH,
    )
    assert missing_mask.status_code == 400
    assert missing_mask.json()["error"]["status"] == "INVALID_ARGUMENT"

    missing_origin = client.post(
        f"{MAPS}/directions/v2:computeRoutes",
        json={"destination": {"address": "Los Angeles, CA"}},
        headers=FIELD_MASK,
    )
    assert missing_origin.status_code == 400

    via = client.post(
        f"{MAPS}/directions/v2:computeRoutes",
        json={
            "origin": {"address": "San Francisco, CA", "via": True},
            "destination": {"address": "Los Angeles, CA"},
        },
        headers=FIELD_MASK,
    )
    assert via.status_code == 400

    walk_pref = client.post(
        f"{MAPS}/directions/v2:computeRoutes",
        json={
            "origin": {"location": {"latLng": {"latitude": 1.0, "longitude": 2.0}}},
            "destination": {"location": {"latLng": {"latitude": 1.1, "longitude": 2.1}}},
            "travelMode": "WALK",
            "routingPreference": "TRAFFIC_AWARE",
        },
        headers=FIELD_MASK,
    )
    assert walk_pref.status_code == 400


def test_fields_query_param(client: TestClient):
    response = client.post(
        f"{MAPS}/directions/v2:computeRoutes",
        params={"fields": "routes.distanceMeters"},
        json={
            "origin": {"address": "San Francisco, CA"},
            "destination": {"address": "Los Angeles, CA"},
        },
        headers=AUTH,
    )
    assert response.status_code == 200
    route = response.json()["routes"][0]
    assert route == {"distanceMeters": 615337}


def test_compute_route_matrix(client: TestClient):
    response = client.post(
        f"{MAPS}/distanceMatrix/v2:computeRouteMatrix",
        json={
            "origins": [{"waypoint": {"address": "San Francisco, CA"}}],
            "destinations": [
                {"waypoint": {"address": "Los Angeles, CA"}},
                {"waypoint": {"address": "San Jose, CA"}},
            ],
            "travelMode": "DRIVE",
        },
        headers=MATRIX_MASK,
    )
    assert response.status_code == 200
    elements = response.json()
    assert isinstance(elements, list)
    assert len(elements) == 2
    by_dest = {item["destinationIndex"]: item for item in elements}
    assert by_dest[0]["distanceMeters"] == 615337
    assert by_dest[0]["condition"] == "ROUTE_EXISTS"
    assert by_dest[1]["distanceMeters"] == 76320
    assert by_dest[0]["status"] == {}


def test_matrix_not_found_and_synthetic(client: TestClient):
    missing = client.post(
        f"{MAPS}/distanceMatrix/v2:computeRouteMatrix",
        json={
            "origins": [{"waypoint": {"address": "Nowhere"}}],
            "destinations": [{"waypoint": {"address": "Also Nowhere"}}],
        },
        headers=MATRIX_MASK,
    )
    assert missing.json()[0]["condition"] == "ROUTE_NOT_FOUND"

    synthetic = client.post(
        f"{MAPS}/distanceMatrix/v2:computeRouteMatrix",
        json={
            "origins": [
                {"waypoint": {"location": {"latLng": {"latitude": 37.42, "longitude": -122.08}}}}
            ],
            "destinations": [
                {"waypoint": {"location": {"latLng": {"latitude": 37.41, "longitude": -122.07}}}}
            ],
        },
        headers=MATRIX_MASK,
    )
    assert synthetic.json()[0]["condition"] == "ROUTE_EXISTS"
    assert synthetic.json()[0]["distanceMeters"] > 0


def test_maps_requires_auth(client: TestClient):
    response = client.post(
        f"{MAPS}/directions/v2:computeRoutes",
        json={
            "origin": {"address": "San Francisco, CA"},
            "destination": {"address": "Los Angeles, CA"},
        },
        headers={"X-Goog-FieldMask": "*"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["status"] == "UNAUTHENTICATED"


def test_maps_accepts_api_key(client: TestClient):
    response = client.post(
        f"{MAPS}/directions/v2:computeRoutes",
        json={
            "origin": {"address": "San Francisco, CA"},
            "destination": {"address": "Los Angeles, CA"},
        },
        headers={"X-Goog-Api-Key": "test-token", "X-Goog-FieldMask": "routes.distanceMeters"},
    )
    assert response.status_code == 200
    assert response.json()["routes"][0]["distanceMeters"] == 615337


def test_reset_reloads_maps_fixtures(client: TestClient):
    client.post(
        f"{MAPS}/directions/v2:computeRoutes",
        json={
            "origin": {"location": {"latLng": {"latitude": 10.0, "longitude": 10.0}}},
            "destination": {"location": {"latLng": {"latitude": 10.1, "longitude": 10.1}}},
        },
        headers=FIELD_MASK,
    )
    client.post("/reset")
    listed = client.post(
        f"{MAPS}/directions/v2:computeRoutes",
        json={
            "origin": {"address": "San Francisco, CA"},
            "destination": {"address": "Los Angeles, CA"},
        },
        headers=FIELD_MASK,
    )
    assert listed.json()["routes"][0]["distanceMeters"] == 615337
