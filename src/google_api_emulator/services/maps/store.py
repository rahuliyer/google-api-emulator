from __future__ import annotations

import copy
import json
from typing import Any

from google_api_emulator.db import Database
from google_api_emulator.errors import invalid_argument
from google_api_emulator.services.maps.fieldmask import apply_field_mask, mask_includes
from google_api_emulator.services.maps.polyline import encode_polyline
from google_api_emulator.services.maps.waypoints import (
    DRIVE_MODES,
    TRAVEL_MODES,
    camelize_request,
    compact,
    duration_seconds,
    haversine_meters,
    intermediates_compatible,
    lat_lng,
    location_obj,
    normalize_polyline_encoding,
    normalize_routing_preference,
    normalize_travel_mode,
    normalize_units,
    protobuf_duration,
    waypoints_compatible,
)

MAX_INTERMEDIATES = 25
MAX_MATRIX_ELEMENTS = 625
MAX_TRAFFIC_OPTIMAL_ELEMENTS = 100
MAX_TRANSIT_ELEMENTS = 100
MAX_ADDRESS_PLACE_WAYPOINTS = 50


def dump_json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def load_json(raw: str) -> Any:
    return json.loads(raw)


def format_distance(meters: int, units: str) -> str:
    if units == "IMPERIAL":
        miles = meters / 1609.344
        if miles < 0.1:
            return f"{max(1, int(round(meters * 3.28084)))} ft"
        if miles < 10:
            return f"{miles:.1f} mi"
        return f"{miles:.0f} mi"
    if meters < 1000:
        return f"{meters} m"
    km = meters / 1000
    if km < 10:
        return f"{km:.1f} km"
    return f"{km:.0f} km"


def format_duration_text(seconds: int) -> str:
    hours, rem = divmod(max(0, seconds), 3600)
    minutes = rem // 60
    if hours and minutes:
        return f"{hours} hour{'s' if hours != 1 else ''} {minutes} min"
    if hours:
        return f"{hours} hour{'s' if hours != 1 else ''}"
    if minutes:
        return f"{minutes} min"
    return "1 min"


def localized_text(text: str, language: str) -> dict[str, str]:
    return {"text": text, "languageCode": language}


class MapsStore:
    def __init__(self, db: Database | None = None) -> None:
        self.db = db

    def insert_route_fixture(
        self,
        *,
        origin: dict[str, Any],
        destination: dict[str, Any],
        intermediates: list[dict[str, Any]],
        travel_mode: str,
        response: dict[str, Any],
    ) -> None:
        assert self.db is not None
        self.db.execute(
            """
            INSERT INTO maps_routes
                (origin_json, destination_json, intermediates_json, travel_mode, response_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                dump_json(origin),
                dump_json(destination),
                dump_json(intermediates),
                travel_mode,
                dump_json(response),
            ),
        )

    def insert_matrix_fixture(
        self,
        *,
        origins: list[dict[str, Any]],
        destinations: list[dict[str, Any]],
        travel_mode: str,
        elements: list[dict[str, Any]],
    ) -> None:
        assert self.db is not None
        self.db.execute(
            """
            INSERT INTO maps_matrices
                (origins_json, destinations_json, travel_mode, elements_json)
            VALUES (?, ?, ?, ?)
            """,
            (dump_json(origins), dump_json(destinations), travel_mode, dump_json(elements)),
        )

    def compute_routes(self, body: dict[str, Any] | None, field_mask: str) -> dict[str, Any]:
        request = camelize_request(body)
        origin = request.get("origin")
        destination = request.get("destination")
        if not origin or not destination:
            raise invalid_argument("origin and destination are required.")
        self._validate_terminal_waypoint(origin, "origin")
        self._validate_terminal_waypoint(destination, "destination")
        intermediates = list(request.get("intermediates") or [])
        if len(intermediates) > MAX_INTERMEDIATES:
            raise invalid_argument(f"At most {MAX_INTERMEDIATES} intermediate waypoints are supported.")
        travel_mode = self._validate_travel_mode(request)
        routing_preference = normalize_routing_preference(request.get("routingPreference"))
        self._validate_routing_preference(travel_mode, routing_preference)
        self._validate_times(request, travel_mode)
        self._validate_extra_computations(request.get("extraComputations") or [])
        self._validate_reference_routes(request.get("requestedReferenceRoutes") or [])
        if request.get("optimizeWaypointOrder"):
            if any(item.get("via") for item in intermediates):
                raise invalid_argument("via intermediate waypoints cannot be used with optimizeWaypointOrder.")
            if not mask_includes(field_mask, "routes.optimizedIntermediateWaypointIndex"):
                raise invalid_argument(
                    "optimizeWaypointOrder requires routes.optimizedIntermediateWaypointIndex in the field mask."
                )
        units = normalize_units(request.get("units"))
        language = request.get("languageCode") or "en-US"

        matched = self._match_route(origin, destination, intermediates, travel_mode)
        if matched is not None:
            response = copy.deepcopy(matched)
        else:
            response = self._synthesize_routes_response(
                origin,
                destination,
                intermediates,
                travel_mode,
                language,
                units,
            )
        routes = list(response.get("routes") or [])
        if not request.get("computeAlternativeRoutes"):
            routes = [route for route in routes if "DEFAULT_ROUTE_ALTERNATE" not in (route.get("routeLabels") or [])]
            if routes:
                routes = routes[:1]
        if routing_preference == "TRAFFIC_UNAWARE":
            for route in routes:
                if route.get("staticDuration"):
                    route["duration"] = route["staticDuration"]
                for leg in route.get("legs") or []:
                    if leg.get("staticDuration"):
                        leg["duration"] = leg["staticDuration"]
        if request.get("optimizeWaypointOrder") and intermediates:
            for route in routes:
                route["optimizedIntermediateWaypointIndex"] = list(range(len(intermediates)))
        if normalize_polyline_encoding(request.get("polylineEncoding")) == "GEO_JSON_LINESTRING":
            for route in routes:
                self._to_geojson(route)
        if routing_preference in {"TRAFFIC_AWARE", "TRAFFIC_AWARE_OPTIMAL"}:
            for route in routes:
                route.setdefault("routeToken", "emulator-route-token")
        response["routes"] = routes
        return apply_field_mask(compact(response), field_mask)

    def compute_route_matrix(self, body: dict[str, Any] | None, field_mask: str) -> list[dict[str, Any]]:
        request = camelize_request(body)
        origins = list(request.get("origins") or [])
        destinations = list(request.get("destinations") or [])
        if not origins or not destinations:
            raise invalid_argument("origins and destinations are required.")
        origin_waypoints = [self._matrix_waypoint(item, "origin") for item in origins]
        destination_waypoints = [self._matrix_waypoint(item, "destination") for item in destinations]
        travel_mode = self._validate_travel_mode(request)
        routing_preference = normalize_routing_preference(request.get("routingPreference"))
        self._validate_routing_preference(travel_mode, routing_preference)
        self._validate_times(request, travel_mode)
        self._validate_extra_computations(request.get("extraComputations") or [])
        product = len(origin_waypoints) * len(destination_waypoints)
        if product > MAX_MATRIX_ELEMENTS:
            raise invalid_argument("The product of origins and destinations must be no greater than 625.")
        if routing_preference == "TRAFFIC_AWARE_OPTIMAL" and product > MAX_TRAFFIC_OPTIMAL_ELEMENTS:
            raise invalid_argument("TRAFFIC_AWARE_OPTIMAL matrices are limited to 100 elements.")
        if travel_mode == "TRANSIT" and product > MAX_TRANSIT_ELEMENTS:
            raise invalid_argument("TRANSIT matrices are limited to 100 elements.")
        address_or_place = 0
        for waypoint in origin_waypoints + destination_waypoints:
            if waypoint.get("placeId") or waypoint.get("address"):
                address_or_place += 1
        if address_or_place > MAX_ADDRESS_PLACE_WAYPOINTS:
            raise invalid_argument("At most 50 origins and destinations may be specified as placeId or address.")

        units = normalize_units(request.get("units"))
        language = request.get("languageCode") or "en-US"
        matched = self._match_matrix(origin_waypoints, destination_waypoints, travel_mode)
        if matched is not None:
            elements = copy.deepcopy(matched)
        else:
            elements = self._compose_matrix(origin_waypoints, destination_waypoints, travel_mode, language, units)
        if routing_preference == "TRAFFIC_UNAWARE":
            for element in elements:
                if element.get("staticDuration"):
                    element["duration"] = element["staticDuration"]
        return apply_field_mask(compact(elements), field_mask)

    def _matrix_waypoint(self, item: dict[str, Any], label: str) -> dict[str, Any]:
        waypoint = (item or {}).get("waypoint")
        if not waypoint:
            raise invalid_argument(f"Each {label} requires a waypoint.")
        self._validate_terminal_waypoint(waypoint, label)
        return waypoint

    def _validate_terminal_waypoint(self, waypoint: dict[str, Any], name: str) -> None:
        if waypoint.get("via"):
            raise invalid_argument(f"{name} cannot be a via waypoint.")
        if not waypoint.get("placeId") and not waypoint.get("address") and lat_lng(waypoint) is None:
            raise invalid_argument(f"{name} must include location, placeId, or address.")

    def _validate_travel_mode(self, request: dict[str, Any]) -> str:
        mode = normalize_travel_mode(request.get("travelMode"))
        if mode not in TRAVEL_MODES:
            raise invalid_argument(f"Unsupported travelMode: {mode}.")
        if request.get("transitPreferences") and mode != "TRANSIT":
            raise invalid_argument("transitPreferences can only be set when travelMode is TRANSIT.")
        return mode

    def _validate_routing_preference(self, travel_mode: str, routing_preference: str | None) -> None:
        if not routing_preference or routing_preference == "ROUTING_PREFERENCE_UNSPECIFIED":
            return
        if travel_mode not in DRIVE_MODES:
            raise invalid_argument("routingPreference can only be set when travelMode is DRIVE or TWO_WHEELER.")

    def _validate_times(self, request: dict[str, Any], travel_mode: str) -> None:
        if request.get("departureTime") and request.get("arrivalTime"):
            raise invalid_argument("Specify either departureTime or arrivalTime, not both.")
        if request.get("arrivalTime") and travel_mode != "TRANSIT":
            raise invalid_argument("arrivalTime can only be set when travelMode is TRANSIT.")

    def _validate_extra_computations(self, extras: list[Any]) -> None:
        for extra in extras:
            name = extra if isinstance(extra, str) else str(extra)
            if name in {"EXTRA_COMPUTATION_UNSPECIFIED", "0", 0}:
                raise invalid_argument("extraComputations cannot include EXTRA_COMPUTATION_UNSPECIFIED.")

    def _validate_reference_routes(self, routes: list[Any]) -> None:
        for route in routes:
            name = route if isinstance(route, str) else str(route)
            if name in {"REFERENCE_ROUTE_UNSPECIFIED", "0", 0}:
                raise invalid_argument("requestedReferenceRoutes cannot include REFERENCE_ROUTE_UNSPECIFIED.")

    def _match_route(
        self,
        origin: dict[str, Any],
        destination: dict[str, Any],
        intermediates: list[dict[str, Any]],
        travel_mode: str,
    ) -> dict[str, Any] | None:
        assert self.db is not None
        rows = self.db.fetchall(
            """
            SELECT origin_json, destination_json, intermediates_json, travel_mode, response_json
            FROM maps_routes
            """
        )
        for row in rows:
            if row["travel_mode"] != travel_mode:
                continue
            if not waypoints_compatible(origin, load_json(row["origin_json"])):
                continue
            if not waypoints_compatible(destination, load_json(row["destination_json"])):
                continue
            if not intermediates_compatible(intermediates, load_json(row["intermediates_json"])):
                continue
            return load_json(row["response_json"])
        return None

    def _match_matrix(
        self,
        origins: list[dict[str, Any]],
        destinations: list[dict[str, Any]],
        travel_mode: str,
    ) -> list[dict[str, Any]] | None:
        assert self.db is not None
        rows = self.db.fetchall(
            """
            SELECT origins_json, destinations_json, travel_mode, elements_json
            FROM maps_matrices
            """
        )
        for row in rows:
            if row["travel_mode"] != travel_mode:
                continue
            fixture_origins = load_json(row["origins_json"])
            fixture_destinations = load_json(row["destinations_json"])
            if not intermediates_compatible(origins, fixture_origins):
                continue
            if not intermediates_compatible(destinations, fixture_destinations):
                continue
            return load_json(row["elements_json"])
        return None

    def _compose_matrix(
        self,
        origins: list[dict[str, Any]],
        destinations: list[dict[str, Any]],
        travel_mode: str,
        language: str,
        units: str,
    ) -> list[dict[str, Any]]:
        elements: list[dict[str, Any]] = []
        for origin_index, origin in enumerate(origins):
            for destination_index, destination in enumerate(destinations):
                matched = self._match_route(origin, destination, [], travel_mode)
                if matched and matched.get("routes"):
                    route = matched["routes"][0]
                    element = {
                        "originIndex": origin_index,
                        "destinationIndex": destination_index,
                        "status": {},
                        "condition": "ROUTE_EXISTS",
                        "distanceMeters": route.get("distanceMeters"),
                        "duration": route.get("duration"),
                        "staticDuration": route.get("staticDuration"),
                        "localizedValues": route.get("localizedValues"),
                    }
                    elements.append(element)
                    continue
                synthesized = self._synthesize_element(origin, destination, travel_mode, language, units)
                element = {
                    "originIndex": origin_index,
                    "destinationIndex": destination_index,
                    **synthesized,
                }
                elements.append(element)
        return elements

    def _synthesize_routes_response(
        self,
        origin: dict[str, Any],
        destination: dict[str, Any],
        intermediates: list[dict[str, Any]],
        travel_mode: str,
        language: str,
        units: str,
    ) -> dict[str, Any]:
        points: list[tuple[float, float]] = []
        origin_ll = lat_lng(origin)
        dest_ll = lat_lng(destination)
        if origin_ll is None or dest_ll is None:
            return {"routes": []}
        points.append(origin_ll)
        via_points: list[tuple[float, float]] = []
        for item in intermediates:
            point = lat_lng(item)
            if point is None:
                return {"routes": []}
            via_points.append(point)
            points.append(point)
        points.append(dest_ll)
        stops = [origin_ll, *via_points, dest_ll]
        legs = []
        total_distance = 0
        total_static = 0
        for start, end in zip(stops, stops[1:]):
            leg = self._build_leg(start, end, travel_mode, language, units)
            total_distance += int(leg["distanceMeters"])
            total_static += int(str(leg["staticDuration"]).rstrip("s"))
            legs.append(leg)
        traffic = max(1, int(round(total_static * 1.08)))
        encoded = encode_polyline(points)
        route = compact(
            {
                "routeLabels": ["DEFAULT_ROUTE"],
                "legs": legs,
                "distanceMeters": total_distance,
                "duration": protobuf_duration(traffic),
                "staticDuration": protobuf_duration(total_static),
                "polyline": {"encodedPolyline": encoded},
                "description": "Emulator route",
                "viewport": {
                    "low": {
                        "latitude": min(p[0] for p in points),
                        "longitude": min(p[1] for p in points),
                    },
                    "high": {
                        "latitude": max(p[0] for p in points),
                        "longitude": max(p[1] for p in points),
                    },
                },
                "localizedValues": self._localized_values(total_distance, traffic, total_static, language, units),
            }
        )
        return {"routes": [route]}

    def _synthesize_element(
        self,
        origin: dict[str, Any],
        destination: dict[str, Any],
        travel_mode: str,
        language: str,
        units: str,
    ) -> dict[str, Any]:
        origin_ll = lat_lng(origin)
        dest_ll = lat_lng(destination)
        if origin_ll is None or dest_ll is None:
            return {"status": {}, "condition": "ROUTE_NOT_FOUND"}
        meters = max(1, haversine_meters(origin_ll, dest_ll))
        static = duration_seconds(meters, travel_mode)
        traffic = max(1, int(round(static * 1.08)))
        return {
            "status": {},
            "condition": "ROUTE_EXISTS",
            "distanceMeters": meters,
            "duration": protobuf_duration(traffic),
            "staticDuration": protobuf_duration(static),
            "localizedValues": self._localized_values(meters, traffic, static, language, units),
        }

    def _build_leg(
        self,
        start: tuple[float, float],
        end: tuple[float, float],
        travel_mode: str,
        language: str,
        units: str,
    ) -> dict[str, Any]:
        meters = max(1, haversine_meters(start, end))
        static = duration_seconds(meters, travel_mode)
        traffic = max(1, int(round(static * 1.08)))
        encoded = encode_polyline([start, end])
        return compact(
            {
                "distanceMeters": meters,
                "duration": protobuf_duration(traffic),
                "staticDuration": protobuf_duration(static),
                "polyline": {"encodedPolyline": encoded},
                "startLocation": location_obj(start),
                "endLocation": location_obj(end),
                "steps": [
                    {
                        "distanceMeters": meters,
                        "staticDuration": protobuf_duration(static),
                        "polyline": {"encodedPolyline": encoded},
                        "startLocation": location_obj(start),
                        "endLocation": location_obj(end),
                        "navigationInstruction": {
                            "maneuver": "DEPART",
                            "instructions": "Head toward the destination",
                        },
                        "localizedValues": {
                            "distance": localized_text(format_distance(meters, units), language),
                            "staticDuration": localized_text(format_duration_text(static), language),
                        },
                        "travelMode": travel_mode,
                    }
                ],
                "localizedValues": self._localized_values(meters, traffic, static, language, units),
            }
        )

    def _localized_values(
        self,
        meters: int,
        duration: int,
        static: int,
        language: str,
        units: str,
    ) -> dict[str, Any]:
        return {
            "distance": localized_text(format_distance(meters, units), language),
            "duration": localized_text(format_duration_text(duration), language),
            "staticDuration": localized_text(format_duration_text(static), language),
        }

    def _to_geojson(self, route: dict[str, Any]) -> None:
        def convert(obj: dict[str, Any] | None) -> None:
            if not obj:
                return
            polyline = obj.get("polyline") or {}
            encoded = polyline.get("encodedPolyline")
            if not encoded:
                return
            start = (obj.get("startLocation") or {}).get("latLng") or {}
            end = (obj.get("endLocation") or {}).get("latLng") or {}
            coords: list[list[float]] = []
            if start.get("longitude") is not None:
                coords.append([start["longitude"], start["latitude"]])
            if end.get("longitude") is not None:
                coords.append([end["longitude"], end["latitude"]])
            obj["polyline"] = {
                "geoJsonLinestring": {"type": "LineString", "coordinates": coords or [[0, 0], [0, 0]]}
            }

        convert(route)
        for leg in route.get("legs") or []:
            convert(leg)
            for step in leg.get("steps") or []:
                convert(step)


def build_fixture_route(
    origin: dict[str, Any],
    destination: dict[str, Any],
    intermediates: list[dict[str, Any]],
    travel_mode: str,
    body: dict[str, Any],
) -> dict[str, Any]:
    if body.get("response"):
        return copy.deepcopy(body["response"])
    if body.get("routes"):
        return {"routes": copy.deepcopy(body["routes"])}
    store = MapsStore()
    language = body.get("languageCode") or "en-US"
    units = body.get("units") or "METRIC"
    response = store._synthesize_routes_response(
        origin,
        destination,
        intermediates,
        travel_mode,
        language,
        units,
    )
    if not response.get("routes"):
        raise invalid_argument("Fixture route needs location coordinates or a full response.")
    route = response["routes"][0]
    if body.get("distanceMeters") is not None:
        route["distanceMeters"] = body["distanceMeters"]
        if route.get("legs"):
            route["legs"][0]["distanceMeters"] = body["distanceMeters"]
    if body.get("duration"):
        route["duration"] = body["duration"]
    if body.get("staticDuration"):
        route["staticDuration"] = body["staticDuration"]
    if body.get("description"):
        route["description"] = body["description"]
    if body.get("routeLabels"):
        route["routeLabels"] = body["routeLabels"]
    if body.get("polyline"):
        route["polyline"] = body["polyline"]
    extras = body.get("alternateRoutes") or []
    for extra in extras:
        alt = copy.deepcopy(route)
        alt["routeLabels"] = extra.get("routeLabels") or ["DEFAULT_ROUTE_ALTERNATE"]
        if extra.get("distanceMeters") is not None:
            alt["distanceMeters"] = extra["distanceMeters"]
        if extra.get("duration"):
            alt["duration"] = extra["duration"]
        if extra.get("staticDuration"):
            alt["staticDuration"] = extra["staticDuration"]
        if extra.get("description"):
            alt["description"] = extra["description"]
        response["routes"].append(alt)
    return response
