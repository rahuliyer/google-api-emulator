from __future__ import annotations

import base64
from typing import Any

from google_api_emulator.errors import invalid_argument


def encode_page_token(offset: int) -> str:
    return base64.urlsafe_b64encode(str(offset).encode()).decode().rstrip("=")


def decode_page_token(token: str | None) -> int:
    if not token:
        return 0
    try:
        pad = "=" * (-len(token) % 4)
        return int(base64.urlsafe_b64decode(token + pad))
    except (ValueError, TypeError) as exc:
        raise invalid_argument("Invalid pageToken.") from exc


def paginate(items: list[Any], page_size: int, page_token: str | None) -> tuple[list[Any], str | None]:
    offset = decode_page_token(page_token)
    if offset < 0 or offset > len(items):
        raise invalid_argument("Invalid pageToken.")
    page = items[offset : offset + page_size]
    next_offset = offset + len(page)
    next_token = encode_page_token(next_offset) if next_offset < len(items) else None
    return page, next_token
