from __future__ import annotations

import math
import re
from typing import Any

LATLNG_TOLERANCE = 0.01

DRIVE_MODES = frozenset({"DRIVE", "TWO_WHEELER"})
TRAVEL_MODES = frozenset({"DRIVE", "WALK", "BICYCLE", "TWO_WHEELER", "TRANSIT"})
TRAVEL_MODE_BY_NUMBER = {
    0: "DRIVE",
    1: "DRIVE",
    2: "BICYCLE",
    3: "WALK",
    4: "TWO_WHEELER",
    5: "TRANSIT",
}
ROUTING_PREFERENCE_BY_NUMBER = {
    0: "ROUTING_PREFERENCE_UNSPECIFIED",
    1: "TRAFFIC_UNAWARE",
    2: "TRAFFIC_AWARE",
    3: "TRAFFIC_AWARE_OPTIMAL",
}
UNITS_BY_NUMBER = {0: "METRIC", 1: "METRIC", 2: "IMPERIAL"}
POLYLINE_ENCODING_BY_NUMBER = {0: "ENCODED_POLYLINE", 1: "ENCODED_POLYLINE", 2: "GEO_JSON_LINESTRING"}
REQUEST_ALIASES = {
    "travel_mode": "travelMode",
    "routing_preference": "routingPreference",
    "polyline_quality": "polylineQuality",
    "polyline_encoding": "polylineEncoding",
    "departure_time": "departureTime",
    "arrival_time": "arrivalTime",
    "compute_alternative_routes": "computeAlternativeRoutes",
    "route_modifiers": "routeModifiers",
    "language_code": "languageCode",
    "region_code": "regionCode",
    "optimize_waypoint_order": "optimizeWaypointOrder",
    "requested_reference_routes": "requestedReferenceRoutes",
    "extra_computations": "extraComputations",
    "traffic_model": "trafficModel",
    "transit_preferences": "transitPreferences",
}
SPEED_MPS = {
    "DRIVE": 13.4,
    "TWO_WHEELER": 11.0,
    "BICYCLE": 4.2,
    "WALK": 1.4,
    "TRANSIT": 8.0,
}


def compact(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: compact(item) for key, item in value.items() if item is not None}
    if isinstance(value, list):
        return [compact(item) for item in value]
    return value


def normalize_address(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def lat_lng(waypoint: dict[str, Any] | None) -> tuple[float, float] | None:
    if not waypoint:
        return None
    location = waypoint.get("location") or {}
    coords = location.get("latLng") or location.get("latlng") or {}
    lat = coords.get("latitude")
    lng = coords.get("longitude")
    if lat is None or lng is None:
        return None
    return float(lat), float(lng)


def location_obj(point: tuple[float, float]) -> dict[str, Any]:
    return {"latLng": {"latitude": point[0], "longitude": point[1]}}


def haversine_meters(start: tuple[float, float], end: tuple[float, float]) -> int:
    radius = 6_371_000
    lat1, lon1 = math.radians(start[0]), math.radians(start[1])
    lat2, lon2 = math.radians(end[0]), math.radians(end[1])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return int(2 * radius * math.asin(math.sqrt(a)))


def duration_seconds(meters: int, travel_mode: str) -> int:
    speed = SPEED_MPS.get(travel_mode, SPEED_MPS["DRIVE"])
    return max(1, int(round(meters / speed)))


def protobuf_duration(seconds: int) -> str:
    return f"{int(seconds)}s"


def coerce_enum(value: Any, by_number: dict[int, str] | None = None) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, int):
        if by_number is None:
            return str(value)
        return by_number.get(value, str(value))
    return str(value).strip()


def normalize_travel_mode(value: Any) -> str:
    mode = coerce_enum(value, TRAVEL_MODE_BY_NUMBER)
    if not mode or mode in {"TRAVEL_MODE_UNSPECIFIED"}:
        return "DRIVE"
    return mode


def normalize_routing_preference(value: Any) -> str | None:
    return coerce_enum(value, ROUTING_PREFERENCE_BY_NUMBER)


def normalize_units(value: Any) -> str:
    units = coerce_enum(value, UNITS_BY_NUMBER)
    if not units or units in {"UNITS_UNSPECIFIED"}:
        return "METRIC"
    return units


def normalize_polyline_encoding(value: Any) -> str | None:
    return coerce_enum(value, POLYLINE_ENCODING_BY_NUMBER)


def camelize_request(body: dict[str, Any] | None) -> dict[str, Any]:
    request = dict(body or {})
    for snake, camel in REQUEST_ALIASES.items():
        if snake in request and camel not in request:
            request[camel] = request[snake]
    return request


def waypoints_compatible(request_wp: dict[str, Any] | None, fixture_wp: dict[str, Any] | None) -> bool:
    if not request_wp or not fixture_wp:
        return False
    req_place = request_wp.get("placeId")
    fix_place = fixture_wp.get("placeId")
    if req_place and fix_place and req_place == fix_place:
        return True
    req_addr = request_wp.get("address")
    fix_addr = fixture_wp.get("address")
    if req_addr and fix_addr and normalize_address(req_addr) == normalize_address(fix_addr):
        return True
    req_ll = lat_lng(request_wp)
    fix_ll = lat_lng(fixture_wp)
    if req_ll and fix_ll:
        return (
            abs(req_ll[0] - fix_ll[0]) <= LATLNG_TOLERANCE
            and abs(req_ll[1] - fix_ll[1]) <= LATLNG_TOLERANCE
        )
    return False


def intermediates_compatible(request_list: list[dict[str, Any]], fixture_list: list[dict[str, Any]]) -> bool:
    if len(request_list) != len(fixture_list):
        return False
    return all(waypoints_compatible(left, right) for left, right in zip(request_list, fixture_list, strict=True))
