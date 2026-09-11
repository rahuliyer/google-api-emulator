from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from google_api_emulator.auth import User, require_user
from google_api_emulator.errors import invalid_argument
from google_api_emulator.services.gmail.store import GmailStore
from google_api_emulator.state import EmulatorState

router = APIRouter(prefix="/services/gmail", dependencies=[Depends(require_user)])


def _store(request: Request) -> GmailStore:
    return GmailStore(request.app.state.emulator.db)


def _max_results(value: int | None, default: int = 100, cap: int = 500) -> int:
    if value is None or value == 0:
        return default
    if value < 1:
        raise invalid_argument("maxResults must be at least 1.")
    return min(value, cap)


@router.get("/gmail/v1/users/{user_id}/profile")
def get_profile(request: Request, user_id: str, user: User = Depends(require_user)) -> dict[str, Any]:
    store = _store(request)
    store.resolve_user_id(user, user_id)
    return store.profile(user)


@router.post("/gmail/v1/users/{user_id}/messages/send")
def send_message(
    request: Request,
    user_id: str,
    body: dict[str, Any],
    user: User = Depends(require_user),
) -> dict[str, Any]:
    store = _store(request)
    store.resolve_user_id(user, user_id)
    return store.send(user, body)


@router.get("/gmail/v1/users/{user_id}/messages")
def list_messages(
    request: Request,
    user_id: str,
    user: User = Depends(require_user),
    maxResults: int | None = Query(default=None),
    pageToken: str | None = Query(default=None),
    q: str | None = Query(default=None),
    labelIds: list[str] | None = Query(default=None),
    includeSpamTrash: bool = Query(default=False),
) -> dict[str, Any]:
    store = _store(request)
    uid = store.resolve_user_id(user, user_id)
    return store.list_messages(
        uid,
        max_results=_max_results(maxResults),
        page_token=pageToken,
        query=q,
        label_ids=labelIds,
        include_spam_trash=includeSpamTrash,
    )


@router.get("/gmail/v1/users/{user_id}/messages/{message_id}/attachments/{attachment_id}")
def get_attachment(
    request: Request,
    user_id: str,
    message_id: str,
    attachment_id: str,
    user: User = Depends(require_user),
) -> dict[str, Any]:
    store = _store(request)
    uid = store.resolve_user_id(user, user_id)
    return store.get_attachment(uid, message_id, attachment_id)


@router.post("/gmail/v1/users/{user_id}/messages/{message_id}/modify")
def modify_message(
    request: Request,
    user_id: str,
    message_id: str,
    body: dict[str, Any],
    user: User = Depends(require_user),
) -> dict[str, Any]:
    store = _store(request)
    uid = store.resolve_user_id(user, user_id)
    return store.modify_message(
        uid,
        message_id,
        add=body.get("addLabelIds"),
        remove=body.get("removeLabelIds"),
    )


@router.post("/gmail/v1/users/{user_id}/messages/{message_id}/trash")
def trash_message(
    request: Request,
    user_id: str,
    message_id: str,
    user: User = Depends(require_user),
) -> dict[str, Any]:
    store = _store(request)
    uid = store.resolve_user_id(user, user_id)
    return store.trash_message(uid, message_id)


@router.post("/gmail/v1/users/{user_id}/messages/{message_id}/untrash")
def untrash_message(
    request: Request,
    user_id: str,
    message_id: str,
    user: User = Depends(require_user),
) -> dict[str, Any]:
    store = _store(request)
    uid = store.resolve_user_id(user, user_id)
    return store.untrash_message(uid, message_id)


@router.get("/gmail/v1/users/{user_id}/messages/{message_id}")
def get_message(
    request: Request,
    user_id: str,
    message_id: str,
    user: User = Depends(require_user),
    format: str | None = Query(default="full"),
) -> dict[str, Any]:
    store = _store(request)
    uid = store.resolve_user_id(user, user_id)
    return store.get_message(uid, message_id, fmt=format or "full")


@router.delete("/gmail/v1/users/{user_id}/messages/{message_id}")
def delete_message(
    request: Request,
    user_id: str,
    message_id: str,
    user: User = Depends(require_user),
) -> dict[str, Any]:
    store = _store(request)
    uid = store.resolve_user_id(user, user_id)
    store.delete_message(uid, message_id)
    return {}


@router.get("/gmail/v1/users/{user_id}/threads")
def list_threads(
    request: Request,
    user_id: str,
    user: User = Depends(require_user),
    maxResults: int | None = Query(default=None),
    pageToken: str | None = Query(default=None),
    q: str | None = Query(default=None),
    labelIds: list[str] | None = Query(default=None),
    includeSpamTrash: bool = Query(default=False),
) -> dict[str, Any]:
    store = _store(request)
    uid = store.resolve_user_id(user, user_id)
    return store.list_threads(
        uid,
        max_results=_max_results(maxResults),
        page_token=pageToken,
        query=q,
        label_ids=labelIds,
        include_spam_trash=includeSpamTrash,
    )


@router.post("/gmail/v1/users/{user_id}/threads/{thread_id}/modify")
def modify_thread(
    request: Request,
    user_id: str,
    thread_id: str,
    body: dict[str, Any],
    user: User = Depends(require_user),
) -> dict[str, Any]:
    store = _store(request)
    uid = store.resolve_user_id(user, user_id)
    return store.modify_thread(
        uid,
        thread_id,
        add=body.get("addLabelIds"),
        remove=body.get("removeLabelIds"),
    )


@router.post("/gmail/v1/users/{user_id}/threads/{thread_id}/trash")
def trash_thread(
    request: Request,
    user_id: str,
    thread_id: str,
    user: User = Depends(require_user),
) -> dict[str, Any]:
    store = _store(request)
    uid = store.resolve_user_id(user, user_id)
    return store.trash_thread(uid, thread_id)


@router.post("/gmail/v1/users/{user_id}/threads/{thread_id}/untrash")
def untrash_thread(
    request: Request,
    user_id: str,
    thread_id: str,
    user: User = Depends(require_user),
) -> dict[str, Any]:
    store = _store(request)
    uid = store.resolve_user_id(user, user_id)
    return store.untrash_thread(uid, thread_id)


@router.get("/gmail/v1/users/{user_id}/threads/{thread_id}")
def get_thread(
    request: Request,
    user_id: str,
    thread_id: str,
    user: User = Depends(require_user),
    format: str | None = Query(default="full"),
) -> dict[str, Any]:
    store = _store(request)
    uid = store.resolve_user_id(user, user_id)
    return store.get_thread(uid, thread_id, fmt=format or "full")


@router.delete("/gmail/v1/users/{user_id}/threads/{thread_id}")
def delete_thread(
    request: Request,
    user_id: str,
    thread_id: str,
    user: User = Depends(require_user),
) -> dict[str, Any]:
    store = _store(request)
    uid = store.resolve_user_id(user, user_id)
    store.delete_thread(uid, thread_id)
    return {}


@router.get("/gmail/v1/users/{user_id}/labels")
def list_labels(request: Request, user_id: str, user: User = Depends(require_user)) -> dict[str, Any]:
    store = _store(request)
    uid = store.resolve_user_id(user, user_id)
    return store.list_labels(uid)


@router.post("/gmail/v1/users/{user_id}/labels")
def create_label(
    request: Request,
    user_id: str,
    body: dict[str, Any],
    user: User = Depends(require_user),
) -> dict[str, Any]:
    store = _store(request)
    uid = store.resolve_user_id(user, user_id)
    return store.create_label(uid, body)


@router.get("/gmail/v1/users/{user_id}/labels/{label_id}")
def get_label(
    request: Request,
    user_id: str,
    label_id: str,
    user: User = Depends(require_user),
) -> dict[str, Any]:
    store = _store(request)
    uid = store.resolve_user_id(user, user_id)
    return store.get_label(uid, label_id)


@router.put("/gmail/v1/users/{user_id}/labels/{label_id}")
@router.patch("/gmail/v1/users/{user_id}/labels/{label_id}")
def update_label(
    request: Request,
    user_id: str,
    label_id: str,
    body: dict[str, Any],
    user: User = Depends(require_user),
) -> dict[str, Any]:
    store = _store(request)
    uid = store.resolve_user_id(user, user_id)
    return store.update_label(uid, label_id, body)


@router.delete("/gmail/v1/users/{user_id}/labels/{label_id}")
def delete_label(
    request: Request,
    user_id: str,
    label_id: str,
    user: User = Depends(require_user),
) -> dict[str, Any]:
    store = _store(request)
    uid = store.resolve_user_id(user, user_id)
    store.delete_label(uid, label_id)
    return {}


@router.post("/gmail/v1/users/{user_id}/drafts/send")
def send_draft(
    request: Request,
    user_id: str,
    body: dict[str, Any],
    user: User = Depends(require_user),
) -> dict[str, Any]:
    store = _store(request)
    store.resolve_user_id(user, user_id)
    return store.send_draft(user, body)


@router.get("/gmail/v1/users/{user_id}/drafts")
def list_drafts(
    request: Request,
    user_id: str,
    user: User = Depends(require_user),
    maxResults: int | None = Query(default=None),
    pageToken: str | None = Query(default=None),
) -> dict[str, Any]:
    store = _store(request)
    uid = store.resolve_user_id(user, user_id)
    return store.list_drafts(uid, _max_results(maxResults), pageToken)


@router.post("/gmail/v1/users/{user_id}/drafts")
def create_draft(
    request: Request,
    user_id: str,
    body: dict[str, Any],
    user: User = Depends(require_user),
) -> dict[str, Any]:
    store = _store(request)
    store.resolve_user_id(user, user_id)
    return store.create_draft(user, body)


@router.get("/gmail/v1/users/{user_id}/drafts/{draft_id}")
def get_draft(
    request: Request,
    user_id: str,
    draft_id: str,
    user: User = Depends(require_user),
) -> dict[str, Any]:
    store = _store(request)
    uid = store.resolve_user_id(user, user_id)
    return store.get_draft(uid, draft_id)


@router.put("/gmail/v1/users/{user_id}/drafts/{draft_id}")
def update_draft(
    request: Request,
    user_id: str,
    draft_id: str,
    body: dict[str, Any],
    user: User = Depends(require_user),
) -> dict[str, Any]:
    store = _store(request)
    store.resolve_user_id(user, user_id)
    return store.update_draft(user, draft_id, body)


@router.delete("/gmail/v1/users/{user_id}/drafts/{draft_id}")
def delete_draft(
    request: Request,
    user_id: str,
    draft_id: str,
    user: User = Depends(require_user),
) -> dict[str, Any]:
    store = _store(request)
    uid = store.resolve_user_id(user, user_id)
    store.delete_draft(uid, draft_id)
    return {}
