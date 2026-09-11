from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, Query, Request

from google_api_emulator.auth import require_routes_user
from google_api_emulator.services.routes.fieldmask import parse_field_mask
from google_api_emulator.services.routes.store import RoutesStore


def _store(request: Request) -> RoutesStore:
    return RoutesStore(request.app.state.emulator.db)


def _routes_router(prefix: str) -> APIRouter:
    router = APIRouter(prefix=prefix, dependencies=[Depends(require_routes_user)])

    @router.post("/directions/v2:computeRoutes")
    def compute_routes(
        request: Request,
        body: dict[str, Any],
        x_goog_field_mask: str | None = Header(default=None, alias="X-Goog-FieldMask"),
        fields: str | None = Query(default=None),
        dollar_fields: str | None = Query(default=None, alias="$fields"),
    ) -> dict[str, Any]:
        mask = parse_field_mask(x_goog_field_mask, fields, dollar_fields)
        return _store(request).compute_routes(body, mask)

    @router.post("/distanceMatrix/v2:computeRouteMatrix")
    def compute_route_matrix(
        request: Request,
        body: dict[str, Any],
        x_goog_field_mask: str | None = Header(default=None, alias="X-Goog-FieldMask"),
        fields: str | None = Query(default=None),
        dollar_fields: str | None = Query(default=None, alias="$fields"),
    ) -> list[dict[str, Any]]:
        mask = parse_field_mask(x_goog_field_mask, fields, dollar_fields)
        return _store(request).compute_route_matrix(body, mask)

    return router


# Host swap: routes.googleapis.com → /services/routes, then Google’s /directions/v2:...
router = _routes_router("/services/routes")
