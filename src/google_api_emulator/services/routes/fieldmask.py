from __future__ import annotations

from typing import Any

from google_api_emulator.errors import invalid_argument


def parse_field_mask(
    header: str | None,
    fields: str | None,
    dollar_fields: str | None,
) -> str:
    mask = header or fields or dollar_fields
    if mask is None or not str(mask).strip():
        raise invalid_argument(
            "FieldMask is a required parameter. See https://cloud.google.com/apis/docs/system-parameters#definitions."
        )
    return str(mask).strip()


def mask_includes(mask: str, path: str) -> bool:
    if mask.strip() == "*":
        return True
    wanted = path.casefold()
    for part in mask.split(","):
        item = part.strip().strip("`")
        if not item:
            continue
        if item == "*" or item.casefold() == wanted:
            return True
        if wanted.startswith(item.casefold() + ".") or item.casefold().startswith(wanted + "."):
            return True
    return False


def apply_field_mask(value: Any, mask: str) -> Any:
    if mask.strip() == "*":
        return value
    tree: dict[str, Any] = {}
    for raw in mask.split(","):
        path = [part.strip().strip("`") for part in raw.split(".") if part.strip().strip("`")]
        if not path:
            continue
        cursor = tree
        for part in path:
            cursor = cursor.setdefault(part, {})
    return _filter(value, tree)


def _filter(value: Any, tree: dict[str, Any]) -> Any:
    if not tree:
        return value
    if isinstance(value, list):
        return [_filter(item, tree) for item in value]
    if not isinstance(value, dict):
        return value
    out: dict[str, Any] = {}
    for key, subtree in tree.items():
        if key in value:
            out[key] = _filter(value[key], subtree)
    return out
