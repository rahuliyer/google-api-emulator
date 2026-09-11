from __future__ import annotations

import copy
from typing import Any

from google_api_emulator.db import Database
from google_api_emulator.errors import GoogleAPIError, invalid_argument
from google_api_emulator.services.places.store import PlacesStore, dump_json, haversine_m, load_json

MATCH_RADIUS_M = 50.0
SPEED_MPS = {
    "DRIVE": 13.9,
    "TWO_WHEELER": 13.9,
    "BICYCLE": 4.0,
    "WALK": 1.4,
    "TRANSIT": 8.0,
}


def encode_polyline(coords: list[tuple[float, float]]) -> str:
    result: list[str] = []
    prev_lat = prev_lng = 0

    def encode_signed(value: int) -> str:
        value = ~(value << 1) if value < 0 else value << 1
        chunks: list[str] = []
        while value >= 0x20:
            chunks.append(chr((0x20 | (value & 0x1F)) + 63))
            value >>= 5
        chunks.append(chr(value + 63))
        return "".join(chunks)

    for lat, lng in coords:
        lat_i = int(round(lat * 1e5))
        lng_i = int(round(lng * 1e5))
        result.append(encode_signed(lat_i - prev_lat))
        result.append(encode_signed(lng_i - prev_lng))
        prev_lat, prev_lng = lat_i, lng_i
    return "".join(result)


def duration_json(seconds: float) -> str:
    return f"{max(1, int(round(seconds)))}s"


def waypoint_place_id(waypoint: dict[str, Any] | None) -> str | None:
    if not waypoint:
        return None
    value = waypoint.get("placeId")
    return str(value) if value else None


def waypoint_address(waypoint: dict[str, Any] | None) -> str | None:
    if not waypoint:
        return None
    value = waypoint.get("address")
    return str(value) if value else None


def waypoint_latlng(waypoint: dict[str, Any] | None) -> tuple[float, float] | None:
    if not waypoint:
        return None
    location = waypoint.get("location") or {}
    latlng = location.get("latLng") or {}
    lat = latlng.get("latitude")
    lng = latlng.get("longitude")
    if lat is None or lng is None:
        return None
    return float(lat), float(lng)


def unwrap_matrix_waypoint(item: dict[str, Any] | None) -> dict[str, Any]:
    item = item or {}
    if "waypoint" in item:
        return item.get("waypoint") or {}
    return item


class RoutesStore:
    def __init__(self, db: Database) -> None:
        self.db = db
        self.places = PlacesStore(db)

    def upsert(self, record: dict[str, Any]) -> None:
        route_id = record.get("id") or f"route-{len(self.list_records()) + 1}"
        payload = dict(record)
        payload["id"] = route_id
        self.db.execute(
            "INSERT INTO maps_routes (id, route_json) VALUES (?, ?) "
            "ON CONFLICT(id) DO UPDATE SET route_json = excluded.route_json",
            (route_id, dump_json(payload)),
        )

    def list_records(self) -> list[dict[str, Any]]:
        rows = self.db.fetchall("SELECT route_json FROM maps_routes ORDER BY id")
        return [load_json(row["route_json"]) for row in rows]

    def compute_routes(self, body: dict[str, Any], field_paths: list[str]) -> dict[str, Any]:
        origin = (body or {}).get("origin")
        destination = (body or {}).get("destination")
        if not origin or not destination:
            raise invalid_argument("origin and destination are required.")
        travel_mode = (body or {}).get("travelMode") or "DRIVE"
        routing_preference = (body or {}).get("routingPreference")
        if routing_preference and travel_mode not in {"DRIVE", "TWO_WHEELER"}:
            raise invalid_argument("routingPreference is only valid for DRIVE or TWO_WHEELER.")
        if (body or {}).get("optimizeWaypointOrder"):
            if "*" not in field_paths and "routes.optimizedIntermediateWaypointIndex" not in field_paths:
                raise invalid_argument(
                    "Requests with optimizeWaypointOrder set to true also need to request for "
                    "routes.optimizedIntermediateWaypointIndex in the fieldmask."
                )
        routes = self._routes_for(origin, destination, travel_mode, body or {})
        return {"routes": routes}

    def compute_route_matrix(self, body: dict[str, Any]) -> list[dict[str, Any]]:
        origins = (body or {}).get("origins") or []
        destinations = (body or {}).get("destinations") or []
        if not origins or not destinations:
            raise invalid_argument("origins and destinations are required.")
        travel_mode = (body or {}).get("travelMode") or "DRIVE"
        routing_preference = (body or {}).get("routingPreference")
        if routing_preference and travel_mode not in {"DRIVE", "TWO_WHEELER"}:
            raise invalid_argument("routingPreference is only valid for DRIVE or TWO_WHEELER.")
        elements: list[dict[str, Any]] = []
        for i, origin_item in enumerate(origins):
            for j, dest_item in enumerate(destinations):
                origin = unwrap_matrix_waypoint(origin_item)
                destination = unwrap_matrix_waypoint(dest_item)
                route = self._routes_for(origin, destination, travel_mode, body or {})[0]
                elements.append(
                    {
                        "originIndex": i,
                        "destinationIndex": j,
                        "status": {},
                        "condition": "ROUTE_EXISTS",
                        "distanceMeters": route.get("distanceMeters"),
                        "duration": route.get("duration"),
                    }
                )
        return elements

    def _routes_for(
        self,
        origin: dict[str, Any],
        destination: dict[str, Any],
        travel_mode: str,
        body: dict[str, Any],
    ) -> list[dict[str, Any]]:
        matched = self._match_fixture(origin, destination, travel_mode)
        if matched:
            routes = [copy.deepcopy(matched["route"])]
            if body.get("computeAlternativeRoutes"):
                for extra in matched.get("alternatives") or []:
                    routes.append(copy.deepcopy(extra))
            return routes
        return [self._geodesic_route(origin, destination, travel_mode)]

    def _match_fixture(
        self,
        origin: dict[str, Any],
        destination: dict[str, Any],
        travel_mode: str,
    ) -> dict[str, Any] | None:
        for record in self.list_records():
            fixture_mode = record.get("travelMode")
            if fixture_mode and fixture_mode != travel_mode:
                continue
            if self._waypoint_matches(origin, record.get("origin") or {}) and self._waypoint_matches(
                destination, record.get("destination") or {}
            ):
                return record
        return None

    def _waypoint_matches(self, request: dict[str, Any], fixture: dict[str, Any]) -> bool:
        req_id = waypoint_place_id(request)
        fix_id = waypoint_place_id(fixture)
        if req_id and fix_id and req_id == fix_id:
            return True
        req_addr = waypoint_address(request)
        fix_addr = waypoint_address(fixture)
        if req_addr and fix_addr and req_addr.casefold() in fix_addr.casefold():
            return True
        if req_addr and fix_addr and fix_addr.casefold() in req_addr.casefold():
            return True
        req_ll = self._resolve_latlng(request)
        fix_ll = self._resolve_latlng(fixture)
        if req_ll and fix_ll and haversine_m(req_ll[0], req_ll[1], fix_ll[0], fix_ll[1]) <= MATCH_RADIUS_M:
            return True
        return False

    def _resolve_latlng(self, waypoint: dict[str, Any]) -> tuple[float, float] | None:
        coords = waypoint_latlng(waypoint)
        if coords:
            return coords
        place_id = waypoint_place_id(waypoint)
        if not place_id:
            return None
        try:
            place = self.places.get(place_id)
        except GoogleAPIError:
            return None
        location = place.get("location") or {}
        lat = location.get("latitude")
        lng = location.get("longitude")
        if lat is None or lng is None:
            return None
        return float(lat), float(lng)

    def _geodesic_route(
        self,
        origin: dict[str, Any],
        destination: dict[str, Any],
        travel_mode: str,
    ) -> dict[str, Any]:
        start = self._resolve_latlng(origin)
        end = self._resolve_latlng(destination)
        if start is None or end is None:
            raise invalid_argument("Waypoints must include location.latLng, placeId, or a fixture address.")
        distance = max(1, int(round(haversine_m(start[0], start[1], end[0], end[1]))))
        speed = SPEED_MPS.get(travel_mode, SPEED_MPS["DRIVE"])
        seconds = distance / speed
        duration = duration_json(seconds)
        start_loc = {"latLng": {"latitude": start[0], "longitude": start[1]}}
        end_loc = {"latLng": {"latitude": end[0], "longitude": end[1]}}
        return {
            "distanceMeters": distance,
            "duration": duration,
            "staticDuration": duration,
            "polyline": {"encodedPolyline": encode_polyline([start, end])},
            "legs": [
                {
                    "distanceMeters": distance,
                    "duration": duration,
                    "staticDuration": duration,
                    "startLocation": start_loc,
                    "endLocation": end_loc,
                }
            ],
        }
