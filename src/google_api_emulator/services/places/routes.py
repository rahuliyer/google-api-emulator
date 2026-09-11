from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from google_api_emulator.auth import require_maps_credential
from google_api_emulator.services.places.mask import apply_field_mask, place_paths, require_field_mask
from google_api_emulator.services.places.store import PlacesStore

router = APIRouter(prefix="/services/places", dependencies=[Depends(require_maps_credential)])


def _store(request: Request) -> PlacesStore:
    return PlacesStore(request.app.state.emulator.db)


@router.post("/v1/places:searchText")
def search_text(
    request: Request,
    body: dict[str, Any],
    _: str = Depends(require_maps_credential),
) -> dict[str, Any]:
    paths = place_paths(require_field_mask(request))
    places = [_masked_place(place, paths) for place in _store(request).search_text(body or {})]
    return {"places": places}


@router.post("/v1/places:searchNearby")
def search_nearby(
    request: Request,
    body: dict[str, Any],
    _: str = Depends(require_maps_credential),
) -> dict[str, Any]:
    paths = place_paths(require_field_mask(request))
    places = [_masked_place(place, paths) for place in _store(request).search_nearby(body or {})]
    return {"places": places}


@router.post("/v1/places:autocomplete")
def autocomplete(
    request: Request,
    body: dict[str, Any],
    _: str = Depends(require_maps_credential),
) -> dict[str, Any]:
    paths = require_field_mask(request)
    suggestions = _store(request).autocomplete(body or {})
    return apply_field_mask({"suggestions": suggestions}, paths)


@router.get("/v1/places/{place_id}")
def get_place(
    request: Request,
    place_id: str,
    _: str = Depends(require_maps_credential),
) -> dict[str, Any]:
    paths = require_field_mask(request)
    place = _store(request).get(place_id)
    return apply_field_mask(place, paths)


def _masked_place(place: dict[str, Any], paths: list[str]) -> dict[str, Any]:
    return apply_field_mask(place, paths)
