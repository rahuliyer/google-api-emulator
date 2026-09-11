from __future__ import annotations

from typing import Any

from fastapi import Request

from google_api_emulator.errors import invalid_argument


FIELD_MASK_ERROR = "FieldMask is a required parameter."


def parse_mask(mask: str | None) -> list[str]:
    if not mask:
        return []
    return [part.strip() for part in mask.split(",") if part.strip()]


def read_field_mask(request: Request) -> str:
    return (
        request.headers.get("X-Goog-FieldMask")
        or request.query_params.get("fields")
        or request.query_params.get("$fields")
        or ""
    ).strip()


def require_field_mask(request: Request) -> list[str]:
    paths = parse_mask(read_field_mask(request))
    if not paths:
        raise invalid_argument(FIELD_MASK_ERROR)
    return paths


def place_paths(paths: list[str]) -> list[str]:
    return nested_paths(paths, "places")


def nested_paths(paths: list[str], prefix: str) -> list[str]:
    if "*" in paths:
        return ["*"]
    stripped: list[str] = []
    for path in paths:
        if path == prefix:
            return ["*"]
        if path.startswith(f"{prefix}."):
            stripped.append(path.removeprefix(f"{prefix}."))
        else:
            stripped.append(path)
    return stripped


def apply_field_mask(data: Any, paths: list[str]) -> Any:
    if "*" in paths:
        return data
    if not isinstance(data, dict):
        return data
    result: dict[str, Any] = {}
    for path in paths:
        parts = [part for part in path.split(".") if part]
        if parts:
            _copy_path(data, result, parts)
    return result


def _copy_path(src: Any, dest: dict[str, Any], parts: list[str]) -> None:
    if not parts or not isinstance(src, dict):
        return
    key = parts[0]
    if key not in src:
        return
    value = src[key]
    if len(parts) == 1:
        dest[key] = value
        return
    if isinstance(value, dict):
        child = dest.setdefault(key, {})
        if isinstance(child, dict):
            _copy_path(value, child, parts[1:])
    elif isinstance(value, list):
        dest[key] = [
            apply_field_mask(item, [".".join(parts[1:])]) if isinstance(item, dict) else item
            for item in value
        ]
