from __future__ import annotations

from fastapi import APIRouter, Request

from google_api_emulator.state import EmulatorState

router = APIRouter()


def _state(request: Request) -> EmulatorState:
    return request.app.state.emulator


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/reset")
def reset(request: Request) -> dict[str, bool]:
    _state(request).reset()
    return {"ok": True}
