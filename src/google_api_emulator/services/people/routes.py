from __future__ import annotations

from fastapi import APIRouter, Depends

from google_api_emulator.auth import User, require_user

router = APIRouter(prefix="/services/people", dependencies=[Depends(require_user)])


@router.get("/v1/_auth_check")
def auth_check(user: User = Depends(require_user)) -> dict[str, str]:
    return {"userId": user.id, "email": user.email}
