from __future__ import annotations

import base64
import json
import re
import uuid
from email import policy
from email.message import EmailMessage, Message
from email.parser import BytesParser
from email.utils import format_datetime, parsedate_to_datetime
from datetime import datetime, timezone
from typing import Any

SYSTEM_LABELS = (
    ("INBOX", "INBOX"),
    ("SENT", "SENT"),
    ("TRASH", "TRASH"),
    ("SPAM", "SPAM"),
    ("DRAFT", "DRAFT"),
    ("UNREAD", "UNREAD"),
    ("STARRED", "STARRED"),
    ("IMPORTANT", "IMPORTANT"),
    ("CATEGORY_PERSONAL", "CATEGORY_PERSONAL"),
)


def new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:16]}"


def b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def b64url_decode(value: str) -> bytes:
    pad = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + pad)


def dump_json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def load_json(raw: str) -> Any:
    return json.loads(raw)


def _header_addresses(values: list[str] | str | None) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        return [values]
    return list(values)


def decode_attachment_bytes(*, text: str | None = None, data: str | None = None) -> bytes:
    if text is not None:
        return text.encode("utf-8")
    if not data:
        return b""
    pad = "=" * (-len(data) % 4)
    try:
        return base64.urlsafe_b64decode(data + pad)
    except Exception:
        return base64.b64decode(data + pad)


def _add_attachments(msg: EmailMessage, attachments: list[dict[str, Any]] | None) -> None:
    for attachment in attachments or []:
        filename = attachment.get("filename") or "attachment.bin"
        mime_type = attachment.get("mimeType") or "application/octet-stream"
        maintype, _, subtype = mime_type.partition("/")
        if not subtype:
            maintype, subtype = "application", "octet-stream"
        payload = decode_attachment_bytes(text=attachment.get("text"), data=attachment.get("data"))
        msg.add_attachment(payload, maintype=maintype, subtype=subtype, filename=filename)


def build_rfc822(
    *,
    from_addr: str,
    to: list[str] | str | None,
    subject: str = "",
    body: str = "",
    date: datetime | None = None,
    cc: list[str] | str | None = None,
    bcc: list[str] | str | None = None,
    message_id: str | None = None,
    in_reply_to: str | None = None,
    references: str | None = None,
    extra_headers: dict[str, str] | None = None,
    attachments: list[dict[str, Any]] | None = None,
) -> bytes:
    msg = EmailMessage()
    msg["From"] = from_addr
    to_list = _header_addresses(to)
    if to_list:
        msg["To"] = ", ".join(to_list)
    cc_list = _header_addresses(cc)
    if cc_list:
        msg["Cc"] = ", ".join(cc_list)
    bcc_list = _header_addresses(bcc)
    if bcc_list:
        msg["Bcc"] = ", ".join(bcc_list)
    msg["Subject"] = subject
    when = date or datetime.now(timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    msg["Date"] = format_datetime(when)
    msg["Message-ID"] = message_id or f"<{new_id()}@emulator.local>"
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    if references:
        msg["References"] = references
    for key, value in (extra_headers or {}).items():
        msg[key] = value
    msg.set_content(body or "")
    _add_attachments(msg, attachments)
    return msg.as_bytes()


def parse_rfc822(raw: bytes) -> Message:
    return BytesParser(policy=policy.default).parsebytes(raw)


def _header_list(message: Message) -> list[dict[str, str]]:
    headers = []
    for name, value in message.items():
        headers.append({"name": name, "value": str(value)})
    return headers


def _walk_payload(message: Message, message_id: str, part_index: list[int]) -> dict[str, Any]:
    mime_type = message.get_content_type()
    filename = message.get_filename() or ""
    node: dict[str, Any] = {
        "mimeType": mime_type,
        "filename": filename,
        "headers": _header_list(message),
    }
    if message.is_multipart():
        parts = []
        for part in message.iter_parts():
            parts.append(_walk_payload(part, message_id, part_index))
        node["body"] = {"size": 0}
        node["parts"] = parts
        return node

    payload = message.get_content()
    if isinstance(payload, str):
        data = payload.encode(message.get_content_charset() or "utf-8")
    elif isinstance(payload, bytes):
        data = payload
    else:
        data = bytes(payload) if payload else b""

    disposition = (message.get_content_disposition() or "").lower()
    is_attachment = disposition == "attachment" or bool(filename)
    body: dict[str, Any] = {"size": len(data)}
    if is_attachment:
        part_index[0] += 1
        body["attachmentId"] = f"{message_id}_{part_index[0]}"
    else:
        body["data"] = b64url_encode(data)
    node["body"] = body
    return node


def gmail_payload(raw: bytes, message_id: str) -> dict[str, Any]:
    parsed = parse_rfc822(raw)
    return _walk_payload(parsed, message_id, [0])


def header_value(raw: bytes, name: str) -> str:
    parsed = parse_rfc822(raw)
    value = parsed.get(name)
    return str(value) if value is not None else ""


def extract_addresses(raw: bytes, *names: str) -> list[str]:
    parsed = parse_rfc822(raw)
    found: list[str] = []
    for name in names:
        value = parsed.get(name)
        if not value:
            continue
        for match in re.findall(r"[\w.+\-]+@[\w.\-]+", str(value)):
            found.append(match.lower())
    return found


def snippet_from_raw(raw: bytes, limit: int = 100) -> str:
    parsed = parse_rfc822(raw)
    text = ""
    if message_is_multipart := parsed.is_multipart():
        for part in parsed.walk():
            if part.get_content_type() == "text/plain" and not part.get_filename():
                content = part.get_content()
                if isinstance(content, str):
                    text = content
                    break
    else:
        content = parsed.get_content()
        if isinstance(content, str):
            text = content
    del message_is_multipart
    compact = " ".join(text.split())
    return compact[:limit]


def internal_date_ms(raw: bytes, fallback: datetime | None = None) -> int:
    parsed = parse_rfc822(raw)
    date_header = parsed.get("Date")
    when = fallback or datetime.now(timezone.utc)
    if date_header:
        try:
            parsed_date = parsedate_to_datetime(str(date_header))
            if parsed_date.tzinfo is None:
                parsed_date = parsed_date.replace(tzinfo=timezone.utc)
            when = parsed_date
        except (TypeError, ValueError, IndexError):
            pass
    return int(when.timestamp() * 1000)


def find_attachment_bytes(raw: bytes, message_id: str, attachment_id: str) -> bytes | None:
    parsed = parse_rfc822(raw)
    index = [0]

    def walk(message: Message) -> bytes | None:
        if message.is_multipart():
            for part in message.iter_parts():
                found = walk(part)
                if found is not None:
                    return found
            return None
        filename = message.get_filename() or ""
        disposition = (message.get_content_disposition() or "").lower()
        is_attachment = disposition == "attachment" or bool(filename)
        if not is_attachment:
            return None
        index[0] += 1
        current = f"{message_id}_{index[0]}"
        if current != attachment_id:
            return None
        payload = message.get_content()
        if isinstance(payload, str):
            return payload.encode(message.get_content_charset() or "utf-8")
        if isinstance(payload, bytes):
            return payload
        return bytes(payload) if payload else b""

    return walk(parsed)


def build_message_resource(
    *,
    message_id: str,
    thread_id: str,
    label_ids: list[str],
    raw: bytes,
    history_id: int,
    internal_date: int | None = None,
) -> dict[str, Any]:
    payload = gmail_payload(raw, message_id)
    date_ms = internal_date if internal_date is not None else internal_date_ms(raw)
    return {
        "id": message_id,
        "threadId": thread_id,
        "labelIds": list(label_ids),
        "snippet": snippet_from_raw(raw),
        "historyId": str(history_id),
        "internalDate": str(date_ms),
        "sizeEstimate": len(raw),
        "payload": payload,
    }


def format_message(resource: dict[str, Any], raw: bytes, fmt: str) -> dict[str, Any]:
    fmt = (fmt or "full").lower()
    base = {
        "id": resource["id"],
        "threadId": resource["threadId"],
        "labelIds": list(resource.get("labelIds") or []),
    }
    if fmt == "minimal":
        return base
    extra = {
        "snippet": resource.get("snippet", ""),
        "historyId": resource.get("historyId"),
        "internalDate": resource.get("internalDate"),
        "sizeEstimate": resource.get("sizeEstimate", len(raw)),
    }
    if fmt == "raw":
        return {**base, **extra, "raw": b64url_encode(raw)}
    if fmt == "metadata":
        payload = resource.get("payload") or {}
        return {
            **base,
            **extra,
            "payload": {
                "mimeType": payload.get("mimeType"),
                "headers": payload.get("headers") or [],
            },
        }
    result = {**base, **extra, "payload": resource.get("payload")}
    return result


def parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        return None
