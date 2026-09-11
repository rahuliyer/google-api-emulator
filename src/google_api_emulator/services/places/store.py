from __future__ import annotations

import json
import math
from typing import Any

from google_api_emulator.db import Database
from google_api_emulator.errors import invalid_argument, not_found
from google_api_emulator.services.people.search import prefix_match


def dump_json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def load_json(raw: str) -> Any:
    return json.loads(raw)


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * radius * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def parse_circle(container: dict[str, Any] | None) -> tuple[float, float, float] | None:
    if not container:
        return None
    circle = container.get("circle") or {}
    center = circle.get("center") or {}
    lat = center.get("latitude")
    lng = center.get("longitude")
    radius = circle.get("radius")
    if lat is None or lng is None or radius is None:
        return None
    return float(lat), float(lng), float(radius)


def place_location(place: dict[str, Any]) -> tuple[float, float] | None:
    location = place.get("location") or {}
    lat = location.get("latitude")
    lng = location.get("longitude")
    if lat is None or lng is None:
        return None
    return float(lat), float(lng)


def display_name(place: dict[str, Any]) -> str:
    name = place.get("displayName") or {}
    if isinstance(name, dict):
        return str(name.get("text") or "")
    return str(name or "")


class PlacesStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    def upsert(self, place: dict[str, Any]) -> dict[str, Any]:
        place_id = place["id"]
        payload = dict(place)
        payload["id"] = place_id
        payload["name"] = place.get("name") or f"places/{place_id}"
        self.db.execute(
            "INSERT INTO maps_places (place_id, place_json) VALUES (?, ?) "
            "ON CONFLICT(place_id) DO UPDATE SET place_json = excluded.place_json",
            (place_id, dump_json(payload)),
        )
        return payload

    def list_places(self) -> list[dict[str, Any]]:
        rows = self.db.fetchall("SELECT place_json FROM maps_places ORDER BY place_id")
        return [load_json(row["place_json"]) for row in rows]

    def get(self, place_id: str) -> dict[str, Any]:
        resolved = place_id.removeprefix("places/")
        row = self.db.fetchone(
            "SELECT place_json FROM maps_places WHERE place_id = ?",
            (resolved,),
        )
        if row is None:
            raise not_found(f"Place {place_id} was not found.")
        return load_json(row["place_json"])

    def search_text(self, body: dict[str, Any]) -> list[dict[str, Any]]:
        query = ((body or {}).get("textQuery") or "").strip()
        if not query:
            raise invalid_argument("textQuery is required.")
        included_type = (body or {}).get("includedType")
        max_results = self._max_results((body or {}).get("maxResultCount"), default=20, cap=20)
        restriction = parse_circle((body or {}).get("locationRestriction"))
        bias = parse_circle((body or {}).get("locationBias"))
        matches: list[tuple[float, dict[str, Any]]] = []
        needle = query.casefold()
        for place in self.list_places():
            if included_type and included_type not in (place.get("types") or []) and place.get("primaryType") != included_type:
                continue
            if not self._text_matches(place, needle):
                continue
            coords = place_location(place)
            if restriction:
                if coords is None or haversine_m(restriction[0], restriction[1], coords[0], coords[1]) > restriction[2]:
                    continue
            distance = 0.0
            if bias and coords:
                distance = haversine_m(bias[0], bias[1], coords[0], coords[1])
            matches.append((distance, place))
        if bias:
            matches.sort(key=lambda item: item[0])
        return [place for _, place in matches[:max_results]]

    def search_nearby(self, body: dict[str, Any]) -> list[dict[str, Any]]:
        restriction = parse_circle((body or {}).get("locationRestriction"))
        if restriction is None:
            raise invalid_argument("locationRestriction.circle is required.")
        max_results = self._max_results((body or {}).get("maxResultCount"), default=20, cap=20, nearby=True)
        included_types = (body or {}).get("includedTypes") or []
        included_primary = (body or {}).get("includedPrimaryTypes") or []
        matches: list[tuple[float, dict[str, Any]]] = []
        for place in self.list_places():
            coords = place_location(place)
            if coords is None:
                continue
            distance = haversine_m(restriction[0], restriction[1], coords[0], coords[1])
            if distance > restriction[2]:
                continue
            types = place.get("types") or []
            if included_types and not any(item in types for item in included_types):
                continue
            if included_primary and place.get("primaryType") not in included_primary:
                continue
            matches.append((distance, place))
        matches.sort(key=lambda item: item[0])
        return [place for _, place in matches[:max_results]]

    def autocomplete(self, body: dict[str, Any]) -> list[dict[str, Any]]:
        query = ((body or {}).get("input") or "").strip()
        if not query:
            return []
        suggestions: list[dict[str, Any]] = []
        for place in self.list_places():
            texts = [display_name(place), place.get("formattedAddress") or ""]
            if not any(prefix_match(query, text) for text in texts if text):
                continue
            suggestions.append(
                {
                    "placePrediction": {
                        "place": place.get("name") or f"places/{place['id']}",
                        "placeId": place["id"],
                        "text": {"text": display_name(place) or place["id"]},
                    }
                }
            )
        return suggestions

    def _text_matches(self, place: dict[str, Any], needle: str) -> bool:
        haystacks = [
            display_name(place),
            place.get("formattedAddress") or "",
            place.get("primaryType") or "",
            *(place.get("types") or []),
        ]
        return any(needle in str(text).casefold() for text in haystacks)

    def _max_results(self, value: Any, *, default: int, cap: int, nearby: bool = False) -> int:
        if value is None:
            return default
        try:
            count = int(value)
        except (TypeError, ValueError) as exc:
            raise invalid_argument("maxResultCount must be an integer.") from exc
        if nearby and (count < 1 or count > cap):
            raise invalid_argument("maxResultCount must be between 1 and 20.")
        if count < 1:
            raise invalid_argument("maxResultCount must be at least 1.")
        return min(count, cap)
