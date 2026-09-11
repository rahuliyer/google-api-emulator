from __future__ import annotations

import re
import shlex
from typing import Any

from google_api_emulator.auth import User
from google_api_emulator.db import Database
from google_api_emulator.errors import invalid_argument, not_found, permission_denied
from google_api_emulator.services.gmail.mime import (
    SYSTEM_LABELS,
    b64url_decode,
    b64url_encode,
    build_message_resource,
    dump_json,
    extract_addresses,
    find_attachment_bytes,
    format_message,
    header_value,
    load_json,
    new_id,
    snippet_from_raw,
)

HIDDEN_BY_DEFAULT = {"SPAM", "TRASH"}


class GmailStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    def resolve_user_id(self, user: User, user_id: str) -> str:
        if user_id in {"me", user.email, user.id}:
            return user.id
        raise permission_denied(f"User {user_id} is not authorized.")

    def bump_history(self, user_id: str) -> int:
        row = self.db.fetchone(
            "SELECT history_id FROM gmail_mailboxes WHERE user_id = ?",
            (user_id,),
        )
        if row is None:
            self.db.execute(
                "INSERT INTO gmail_mailboxes (user_id, history_id) VALUES (?, 1)",
                (user_id,),
            )
            current = 1
        else:
            current = int(row["history_id"]) + 1
            self.db.execute(
                "UPDATE gmail_mailboxes SET history_id = ? WHERE user_id = ?",
                (current, user_id),
            )
        return current

    def history_id(self, user_id: str) -> int:
        row = self.db.fetchone(
            "SELECT history_id FROM gmail_mailboxes WHERE user_id = ?",
            (user_id,),
        )
        return int(row["history_id"]) if row else 1

    def ensure_mailbox(self, user_id: str) -> None:
        existing = self.db.fetchone(
            "SELECT user_id FROM gmail_mailboxes WHERE user_id = ?",
            (user_id,),
        )
        if existing is None:
            self.db.execute(
                "INSERT INTO gmail_mailboxes (user_id, history_id) VALUES (?, 1)",
                (user_id,),
            )
        for label_id, name in SYSTEM_LABELS:
            if self.db.fetchone(
                "SELECT id FROM gmail_labels WHERE user_id = ? AND id = ?",
                (user_id, label_id),
            ):
                continue
            self.db.execute(
                "INSERT INTO gmail_labels (id, user_id, type, label_json) VALUES (?, ?, 'system', ?)",
                (label_id, user_id, dump_json(_system_label(label_id, name))),
            )

    def profile(self, user: User) -> dict[str, Any]:
        messages = self._message_rows(user.id)
        thread_ids = {row["thread_id"] for row in messages}
        return {
            "emailAddress": user.email,
            "messagesTotal": len(messages),
            "threadsTotal": len(thread_ids),
            "historyId": str(self.history_id(user.id)),
        }

    def _message_rows(self, user_id: str) -> list[Any]:
        return self.db.fetchall(
            "SELECT * FROM gmail_messages WHERE user_id = ? ORDER BY internal_date DESC, id",
            (user_id,),
        )

    def _load_message(self, row: Any) -> tuple[dict[str, Any], bytes]:
        return load_json(row["message_json"]), row["raw"].encode("utf-8") if isinstance(row["raw"], str) else row["raw"]

    def get_message(self, user_id: str, message_id: str, fmt: str = "full") -> dict[str, Any]:
        row = self.db.fetchone(
            "SELECT * FROM gmail_messages WHERE user_id = ? AND id = ?",
            (user_id, message_id),
        )
        if row is None:
            raise not_found(f"Message {message_id} was not found.")
        resource, raw = self._load_message(row)
        return format_message(resource, raw, fmt)

    def get_attachment(self, user_id: str, message_id: str, attachment_id: str) -> dict[str, Any]:
        row = self.db.fetchone(
            "SELECT raw FROM gmail_messages WHERE user_id = ? AND id = ?",
            (user_id, message_id),
        )
        if row is None:
            raise not_found(f"Message {message_id} was not found.")
        raw = row["raw"].encode("utf-8") if isinstance(row["raw"], str) else row["raw"]
        data = find_attachment_bytes(raw, message_id, attachment_id)
        if data is None:
            raise not_found(f"Attachment {attachment_id} was not found.")
        return {"size": len(data), "data": b64url_encode(data)}

    def list_messages(
        self,
        user_id: str,
        *,
        max_results: int,
        page_token: str | None,
        query: str | None,
        label_ids: list[str] | None,
        include_spam_trash: bool,
    ) -> dict[str, Any]:
        from google_api_emulator.services.people.pagination import paginate

        matches = self._filter_messages(
            user_id,
            query=query,
            label_ids=label_ids,
            include_spam_trash=include_spam_trash,
        )
        page, next_token = paginate(matches, max_results, page_token)
        body: dict[str, Any] = {
            "messages": [{"id": m["id"], "threadId": m["threadId"]} for m in page],
            "resultSizeEstimate": len(matches),
        }
        if next_token:
            body["nextPageToken"] = next_token
        if not body["messages"]:
            body.pop("messages")
        return body

    def _filter_messages(
        self,
        user_id: str,
        *,
        query: str | None,
        label_ids: list[str] | None,
        include_spam_trash: bool,
        skip_drafts_only: bool = False,
    ) -> list[dict[str, Any]]:
        results = []
        for row in self._message_rows(user_id):
            resource, raw = self._load_message(row)
            labels = set(resource.get("labelIds") or [])
            if not include_spam_trash and (labels & HIDDEN_BY_DEFAULT):
                if not (label_ids and set(label_ids) & HIDDEN_BY_DEFAULT) and not _query_includes_hidden(query):
                    continue
            if label_ids and not set(label_ids).issubset(labels):
                continue
            if skip_drafts_only and "DRAFT" in labels:
                continue
            if query and not message_matches_query(resource, raw, query):
                continue
            results.append(resource)
        return results

    def insert_message(
        self,
        user_id: str,
        *,
        raw: bytes,
        label_ids: list[str],
        thread_id: str | None = None,
        message_id: str | None = None,
    ) -> dict[str, Any]:
        history_id = self.bump_history(user_id)
        mid = message_id or new_id()
        tid = thread_id or self._thread_for_raw(user_id, raw) or new_id()
        resource = build_message_resource(
            message_id=mid,
            thread_id=tid,
            label_ids=label_ids,
            raw=raw,
            history_id=history_id,
        )
        self.db.execute(
            """
            INSERT INTO gmail_messages
            (id, user_id, thread_id, label_ids, internal_date, history_id, raw, message_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                mid,
                user_id,
                tid,
                dump_json(label_ids),
                int(resource["internalDate"]),
                history_id,
                raw.decode("utf-8", errors="replace"),
                dump_json(resource),
            ),
        )
        return resource

    def _thread_for_raw(self, user_id: str, raw: bytes) -> str | None:
        in_reply = header_value(raw, "In-Reply-To").strip()
        refs = header_value(raw, "References")
        candidates = [in_reply] if in_reply else []
        candidates.extend(token for token in refs.split() if token)
        for candidate in candidates:
            for row in self._message_rows(user_id):
                other_raw = row["raw"].encode("utf-8") if isinstance(row["raw"], str) else row["raw"]
                if header_value(other_raw, "Message-ID").strip() == candidate:
                    return row["thread_id"]
        return None

    def send(self, user: User, body: dict[str, Any]) -> dict[str, Any]:
        raw_b64 = body.get("raw")
        if not raw_b64:
            raise invalid_argument("raw is required.")
        try:
            raw = b64url_decode(raw_b64)
        except Exception as exc:
            raise invalid_argument("raw must be base64url-encoded RFC822.") from exc
        labels = ["SENT"]
        recipients = extract_addresses(raw, "To", "Cc", "Bcc")
        if user.email.lower() in recipients:
            labels.append("INBOX")
        resource = self.insert_message(
            user.id,
            raw=raw,
            label_ids=labels,
            thread_id=body.get("threadId"),
        )
        self._deliver_local_copies(user, raw, resource["threadId"])
        return format_message(resource, raw, "minimal") | {
            "labelIds": resource["labelIds"],
            "snippet": resource["snippet"],
            "historyId": resource["historyId"],
            "internalDate": resource["internalDate"],
            "sizeEstimate": resource["sizeEstimate"],
        }

    def _deliver_local_copies(self, sender: User, raw: bytes, thread_id: str) -> None:
        recipients = extract_addresses(raw, "To", "Cc", "Bcc")
        for email in dict.fromkeys(recipients):
            if email == sender.email.lower():
                continue
            row = self.db.fetchone("SELECT id FROM users WHERE lower(email) = ?", (email,))
            if row is None:
                continue
            self.ensure_mailbox(row["id"])
            self.insert_message(
                row["id"],
                raw=raw,
                label_ids=["INBOX", "UNREAD"],
                thread_id=new_id(),
            )

    def modify_message(self, user_id: str, message_id: str, add: list[str] | None, remove: list[str] | None) -> dict[str, Any]:
        row = self.db.fetchone(
            "SELECT * FROM gmail_messages WHERE user_id = ? AND id = ?",
            (user_id, message_id),
        )
        if row is None:
            raise not_found(f"Message {message_id} was not found.")
        resource, raw = self._load_message(row)
        labels = set(resource.get("labelIds") or [])
        labels |= set(add or [])
        labels -= set(remove or [])
        return self._save_labels(user_id, resource, raw, sorted(labels))

    def trash_message(self, user_id: str, message_id: str) -> dict[str, Any]:
        return self.modify_message(user_id, message_id, add=["TRASH"], remove=["INBOX"])

    def untrash_message(self, user_id: str, message_id: str) -> dict[str, Any]:
        return self.modify_message(user_id, message_id, add=["INBOX"], remove=["TRASH"])

    def delete_message(self, user_id: str, message_id: str) -> None:
        row = self.db.fetchone(
            "SELECT id FROM gmail_messages WHERE user_id = ? AND id = ?",
            (user_id, message_id),
        )
        if row is None:
            raise not_found(f"Message {message_id} was not found.")
        self.db.execute(
            "DELETE FROM gmail_drafts WHERE user_id = ? AND message_id = ?",
            (user_id, message_id),
        )
        self.db.execute(
            "DELETE FROM gmail_messages WHERE user_id = ? AND id = ?",
            (user_id, message_id),
        )
        self.bump_history(user_id)

    def _save_labels(self, user_id: str, resource: dict[str, Any], raw: bytes, labels: list[str]) -> dict[str, Any]:
        history_id = self.bump_history(user_id)
        resource["labelIds"] = labels
        resource["historyId"] = str(history_id)
        self.db.execute(
            """
            UPDATE gmail_messages
            SET label_ids = ?, history_id = ?, message_json = ?
            WHERE user_id = ? AND id = ?
            """,
            (dump_json(labels), history_id, dump_json(resource), user_id, resource["id"]),
        )
        return format_message(resource, raw, "minimal") | {"labelIds": labels}

    def list_threads(
        self,
        user_id: str,
        *,
        max_results: int,
        page_token: str | None,
        query: str | None,
        label_ids: list[str] | None,
        include_spam_trash: bool,
    ) -> dict[str, Any]:
        from google_api_emulator.services.people.pagination import paginate

        messages = self._filter_messages(
            user_id,
            query=query,
            label_ids=label_ids,
            include_spam_trash=include_spam_trash,
        )
        threads: dict[str, dict[str, Any]] = {}
        for message in messages:
            tid = message["threadId"]
            if tid not in threads:
                threads[tid] = {
                    "id": tid,
                    "snippet": message.get("snippet", ""),
                    "historyId": message.get("historyId"),
                }
        items = list(threads.values())
        page, next_token = paginate(items, max_results, page_token)
        body: dict[str, Any] = {"threads": page, "resultSizeEstimate": len(items)}
        if next_token:
            body["nextPageToken"] = next_token
        if not body["threads"]:
            body.pop("threads")
        return body

    def get_thread(self, user_id: str, thread_id: str, fmt: str = "full") -> dict[str, Any]:
        rows = self.db.fetchall(
            "SELECT * FROM gmail_messages WHERE user_id = ? AND thread_id = ? ORDER BY internal_date, id",
            (user_id, thread_id),
        )
        if not rows:
            raise not_found(f"Thread {thread_id} was not found.")
        messages = []
        history_id = "1"
        snippet = ""
        for row in rows:
            resource, raw = self._load_message(row)
            messages.append(format_message(resource, raw, fmt))
            history_id = resource.get("historyId", history_id)
            snippet = resource.get("snippet", snippet)
        return {"id": thread_id, "historyId": history_id, "messages": messages, "snippet": snippet}

    def modify_thread(self, user_id: str, thread_id: str, add: list[str] | None, remove: list[str] | None) -> dict[str, Any]:
        rows = self.db.fetchall(
            "SELECT id FROM gmail_messages WHERE user_id = ? AND thread_id = ?",
            (user_id, thread_id),
        )
        if not rows:
            raise not_found(f"Thread {thread_id} was not found.")
        for row in rows:
            self.modify_message(user_id, row["id"], add, remove)
        return self.get_thread(user_id, thread_id, "minimal")

    def trash_thread(self, user_id: str, thread_id: str) -> dict[str, Any]:
        return self.modify_thread(user_id, thread_id, add=["TRASH"], remove=["INBOX"])

    def untrash_thread(self, user_id: str, thread_id: str) -> dict[str, Any]:
        return self.modify_thread(user_id, thread_id, add=["INBOX"], remove=["TRASH"])

    def delete_thread(self, user_id: str, thread_id: str) -> None:
        rows = self.db.fetchall(
            "SELECT id FROM gmail_messages WHERE user_id = ? AND thread_id = ?",
            (user_id, thread_id),
        )
        if not rows:
            raise not_found(f"Thread {thread_id} was not found.")
        for row in rows:
            self.delete_message(user_id, row["id"])

    def list_labels(self, user_id: str) -> dict[str, Any]:
        rows = self.db.fetchall(
            "SELECT * FROM gmail_labels WHERE user_id = ? ORDER BY type, id",
            (user_id,),
        )
        return {"labels": [self._label_with_counts(user_id, load_json(row["label_json"])) for row in rows]}

    def get_label(self, user_id: str, label_id: str) -> dict[str, Any]:
        row = self.db.fetchone(
            "SELECT * FROM gmail_labels WHERE user_id = ? AND id = ?",
            (user_id, label_id),
        )
        if row is None:
            raise not_found(f"Label {label_id} was not found.")
        return self._label_with_counts(user_id, load_json(row["label_json"]))

    def create_label(self, user_id: str, body: dict[str, Any]) -> dict[str, Any]:
        name = body.get("name")
        if not name:
            raise invalid_argument("name is required.")
        label_id = body.get("id") or f"Label_{new_id()[:8]}"
        if self.db.fetchone(
            "SELECT id FROM gmail_labels WHERE user_id = ? AND id = ?",
            (user_id, label_id),
        ):
            raise invalid_argument(f"Label {label_id} already exists.")
        label = {
            "id": label_id,
            "name": name,
            "type": "user",
            "messageListVisibility": body.get("messageListVisibility", "show"),
            "labelListVisibility": body.get("labelListVisibility", "labelShow"),
        }
        if body.get("color"):
            label["color"] = body["color"]
        self.db.execute(
            "INSERT INTO gmail_labels (id, user_id, type, label_json) VALUES (?, ?, 'user', ?)",
            (label_id, user_id, dump_json(label)),
        )
        self.bump_history(user_id)
        return self._label_with_counts(user_id, label)

    def update_label(self, user_id: str, label_id: str, body: dict[str, Any]) -> dict[str, Any]:
        row = self.db.fetchone(
            "SELECT * FROM gmail_labels WHERE user_id = ? AND id = ?",
            (user_id, label_id),
        )
        if row is None:
            raise not_found(f"Label {label_id} was not found.")
        label = load_json(row["label_json"])
        for key in ("name", "messageListVisibility", "labelListVisibility", "color"):
            if key in body:
                label[key] = body[key]
        self.db.execute(
            "UPDATE gmail_labels SET label_json = ? WHERE user_id = ? AND id = ?",
            (dump_json(label), user_id, label_id),
        )
        self.bump_history(user_id)
        return self._label_with_counts(user_id, label)

    def delete_label(self, user_id: str, label_id: str) -> None:
        row = self.db.fetchone(
            "SELECT type FROM gmail_labels WHERE user_id = ? AND id = ?",
            (user_id, label_id),
        )
        if row is None:
            raise not_found(f"Label {label_id} was not found.")
        if row["type"] == "system":
            raise invalid_argument("System labels cannot be deleted.")
        for message_row in self._message_rows(user_id):
            resource, raw = self._load_message(message_row)
            if label_id in (resource.get("labelIds") or []):
                labels = [lid for lid in resource["labelIds"] if lid != label_id]
                self._save_labels(user_id, resource, raw, labels)
        self.db.execute(
            "DELETE FROM gmail_labels WHERE user_id = ? AND id = ?",
            (user_id, label_id),
        )

    def _label_with_counts(self, user_id: str, label: dict[str, Any]) -> dict[str, Any]:
        label_id = label["id"]
        messages = []
        unread = 0
        threads: set[str] = set()
        unread_threads: set[str] = set()
        for row in self._message_rows(user_id):
            resource, _raw = self._load_message(row)
            labels = set(resource.get("labelIds") or [])
            if label_id not in labels:
                continue
            messages.append(resource)
            threads.add(resource["threadId"])
            if "UNREAD" in labels:
                unread += 1
                unread_threads.add(resource["threadId"])
        return {
            **label,
            "messagesTotal": len(messages),
            "messagesUnread": unread,
            "threadsTotal": len(threads),
            "threadsUnread": len(unread_threads),
        }

    def list_drafts(self, user_id: str, max_results: int, page_token: str | None) -> dict[str, Any]:
        from google_api_emulator.services.people.pagination import paginate

        rows = self.db.fetchall(
            "SELECT * FROM gmail_drafts WHERE user_id = ? ORDER BY id",
            (user_id,),
        )
        drafts = [self.get_draft(user_id, row["id"]) for row in rows]
        page, next_token = paginate(drafts, max_results, page_token)
        body: dict[str, Any] = {"drafts": page, "resultSizeEstimate": len(drafts)}
        if next_token:
            body["nextPageToken"] = next_token
        if not body["drafts"]:
            body.pop("drafts")
        return body

    def get_draft(self, user_id: str, draft_id: str) -> dict[str, Any]:
        row = self.db.fetchone(
            "SELECT * FROM gmail_drafts WHERE user_id = ? AND id = ?",
            (user_id, draft_id),
        )
        if row is None:
            raise not_found(f"Draft {draft_id} was not found.")
        message = self.get_message(user_id, row["message_id"], "full")
        return {"id": draft_id, "message": message}

    def create_draft(self, user: User, body: dict[str, Any]) -> dict[str, Any]:
        message_body = body.get("message") or {}
        raw_b64 = message_body.get("raw")
        if not raw_b64:
            raise invalid_argument("message.raw is required.")
        try:
            raw = b64url_decode(raw_b64)
        except Exception as exc:
            raise invalid_argument("raw must be base64url-encoded RFC822.") from exc
        resource = self.insert_message(
            user.id,
            raw=raw,
            label_ids=["DRAFT"],
            thread_id=message_body.get("threadId"),
        )
        draft_id = f"r-{new_id()[:12]}"
        self.db.execute(
            "INSERT INTO gmail_drafts (id, user_id, message_id) VALUES (?, ?, ?)",
            (draft_id, user.id, resource["id"]),
        )
        return {"id": draft_id, "message": self.get_message(user.id, resource["id"], "full")}

    def update_draft(self, user: User, draft_id: str, body: dict[str, Any]) -> dict[str, Any]:
        row = self.db.fetchone(
            "SELECT * FROM gmail_drafts WHERE user_id = ? AND id = ?",
            (user.id, draft_id),
        )
        if row is None:
            raise not_found(f"Draft {draft_id} was not found.")
        self.delete_message(user.id, row["message_id"])
        self.db.execute(
            "DELETE FROM gmail_drafts WHERE user_id = ? AND id = ?",
            (user.id, draft_id),
        )
        created = self.create_draft(user, body)
        self.db.execute(
            "UPDATE gmail_drafts SET id = ? WHERE user_id = ? AND id = ?",
            (draft_id, user.id, created["id"]),
        )
        created["id"] = draft_id
        return created

    def send_draft(self, user: User, body: dict[str, Any]) -> dict[str, Any]:
        draft_id = body.get("id")
        if not draft_id:
            raise invalid_argument("id is required.")
        draft = self.get_draft(user.id, draft_id)
        message_id = draft["message"]["id"]
        sent = self.modify_message(user.id, message_id, add=["SENT"], remove=["DRAFT"])
        raw_row = self.db.fetchone(
            "SELECT raw FROM gmail_messages WHERE user_id = ? AND id = ?",
            (user.id, message_id),
        )
        raw = raw_row["raw"].encode("utf-8") if isinstance(raw_row["raw"], str) else raw_row["raw"]
        self._deliver_local_copies(user, raw, draft["message"]["threadId"])
        self.db.execute(
            "DELETE FROM gmail_drafts WHERE user_id = ? AND id = ?",
            (user.id, draft_id),
        )
        return sent

    def delete_draft(self, user_id: str, draft_id: str) -> None:
        row = self.db.fetchone(
            "SELECT message_id FROM gmail_drafts WHERE user_id = ? AND id = ?",
            (user_id, draft_id),
        )
        if row is None:
            raise not_found(f"Draft {draft_id} was not found.")
        self.delete_message(user_id, row["message_id"])


def _system_label(label_id: str, name: str) -> dict[str, Any]:
    return {
        "id": label_id,
        "name": name,
        "type": "system",
        "messageListVisibility": "hide" if label_id in {"UNREAD", "IMPORTANT"} else "show",
        "labelListVisibility": "labelShow" if label_id in {"INBOX", "SENT", "TRASH", "SPAM", "DRAFT", "STARRED"} else "labelHide",
    }


def _query_includes_hidden(query: str | None) -> bool:
    if not query:
        return False
    lowered = query.lower()
    return "in:trash" in lowered or "in:spam" in lowered or "is:trash" in lowered


def message_matches_query(resource: dict[str, Any], raw: bytes, query: str) -> bool:
    labels = set(resource.get("labelIds") or [])
    subject = header_value(raw, "Subject").lower()
    from_addr = header_value(raw, "From").lower()
    to_addr = header_value(raw, "To").lower()
    cc_addr = header_value(raw, "Cc").lower()
    body = snippet_from_raw(raw, 10_000).lower()
    haystack = " ".join([subject, from_addr, to_addr, cc_addr, body])
    try:
        tokens = shlex.split(query)
    except ValueError:
        tokens = query.split()
    for token in tokens:
        lowered = token.lower()
        if lowered.startswith("from:"):
            if lowered.split(":", 1)[1] not in from_addr:
                return False
        elif lowered.startswith("to:"):
            if lowered.split(":", 1)[1] not in to_addr and lowered.split(":", 1)[1] not in cc_addr:
                return False
        elif lowered.startswith("subject:"):
            if lowered.split(":", 1)[1] not in subject:
                return False
        elif lowered.startswith("label:"):
            wanted = lowered.split(":", 1)[1]
            names = {lid.lower() for lid in labels}
            if wanted not in names:
                return False
        elif lowered == "is:unread":
            if "UNREAD" not in labels:
                return False
        elif lowered == "is:starred":
            if "STARRED" not in labels:
                return False
        elif lowered == "in:inbox":
            if "INBOX" not in labels:
                return False
        elif lowered == "in:sent":
            if "SENT" not in labels:
                return False
        elif lowered in {"in:trash", "is:trash"}:
            if "TRASH" not in labels:
                return False
        elif lowered == "in:draft":
            if "DRAFT" not in labels:
                return False
        elif lowered not in haystack:
            return False
    return True
