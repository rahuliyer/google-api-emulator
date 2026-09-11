from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from google_api_emulator.auth import require_maps_credential
from google_api_emulator.services.places.mask import apply_field_mask, nested_paths, require_field_mask
from google_api_emulator.services.routes.store import RoutesStore

router = APIRouter(prefix="/services/routes", dependencies=[Depends(require_maps_credential)])


def _store(request: Request) -> RoutesStore:
    return RoutesStore(request.app.state.emulator.db)


@router.post("/directions/v2:computeRoutes")
def compute_routes(
    request: Request,
    body: dict[str, Any],
    _: str = Depends(require_maps_credential),
) -> dict[str, Any]:
    paths = require_field_mask(request)
    payload = _store(request).compute_routes(body or {}, paths)
    route_paths = nested_paths(paths, "routes")
    return {"routes": [apply_field_mask(route, route_paths) for route in payload["routes"]]}


@router.post("/distanceMatrix/v2:computeRouteMatrix")
def compute_route_matrix(
    request: Request,
    body: dict[str, Any],
    _: str = Depends(require_maps_credential),
) -> list[dict[str, Any]]:
    paths = require_field_mask(request)
    elements = _store(request).compute_route_matrix(body or {})
    return [apply_field_mask(element, paths) for element in elements]
