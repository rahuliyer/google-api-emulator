from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse


class GoogleAPIError(Exception):
    def __init__(self, code: int, status: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.status = status
        self.message = message

    def body(self) -> dict[str, object]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "status": self.status,
            }
        }


def unauthenticated(message: str = "Request is missing required authentication credential.") -> GoogleAPIError:
    return GoogleAPIError(401, "UNAUTHENTICATED", message)


def invalid_argument(message: str) -> GoogleAPIError:
    return GoogleAPIError(400, "INVALID_ARGUMENT", message)


def not_found(message: str) -> GoogleAPIError:
    return GoogleAPIError(404, "NOT_FOUND", message)


def failed_precondition(message: str) -> GoogleAPIError:
    return GoogleAPIError(400, "FAILED_PRECONDITION", message)


def permission_denied(message: str) -> GoogleAPIError:
    return GoogleAPIError(403, "PERMISSION_DENIED", message)


def precondition_failed(message: str = "Precondition Failed") -> GoogleAPIError:
    return GoogleAPIError(412, "FAILED_PRECONDITION", message)


async def google_api_error_handler(_request: Request, exc: GoogleAPIError) -> JSONResponse:
    return JSONResponse(status_code=exc.code, content=exc.body())
