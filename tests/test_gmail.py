from __future__ import annotations

from email.message import EmailMessage

from fastapi.testclient import TestClient

from google_api_emulator.services.gmail.mime import b64url_decode, b64url_encode

AUTH = {"Authorization": "Bearer test-token"}
GMAIL = "/services/gmail/gmail/v1/users/me"


def test_profile(client: TestClient):
    response = client.get(f"{GMAIL}/profile", headers=AUTH)
    assert response.status_code == 200
    body = response.json()
    assert body["emailAddress"] == "alice@example.com"
    assert body["messagesTotal"] >= 2
    assert "historyId" in body


def test_other_user_id_forbidden(client: TestClient):
    response = client.get(
        "/services/gmail/gmail/v1/users/bob@example.com/profile",
        headers=AUTH,
    )
    assert response.status_code == 403
    assert response.json()["error"]["status"] == "PERMISSION_DENIED"


def test_list_and_get_formats(client: TestClient):
    listed = client.get(f"{GMAIL}/messages", headers=AUTH)
    assert listed.status_code == 200
    ids = {m["id"] for m in listed.json()["messages"]}
    assert "m1" in ids
    assert set(listed.json()["messages"][0].keys()) <= {"id", "threadId"}

    full = client.get(f"{GMAIL}/messages/m1", headers=AUTH)
    assert full.status_code == 200
    assert full.json()["snippet"].startswith("Hi Alice")
    assert full.json()["payload"]["headers"]
    assert "payload" in full.json()

    minimal = client.get(f"{GMAIL}/messages/m1", params={"format": "minimal"}, headers=AUTH)
    assert "payload" not in minimal.json()
    assert "labelIds" in minimal.json()

    raw = client.get(f"{GMAIL}/messages/m1", params={"format": "raw"}, headers=AUTH)
    decoded = b64url_decode(raw.json()["raw"])
    assert b"Hi Alice" in decoded

    missing = client.get(f"{GMAIL}/messages/nope", headers=AUTH)
    assert missing.status_code == 404


def test_query_and_labels(client: TestClient):
    unread = client.get(f"{GMAIL}/messages", params={"q": "is:unread"}, headers=AUTH)
    assert {m["id"] for m in unread.json()["messages"]} == {"m1"}
    from_bob = client.get(f"{GMAIL}/messages", params={"q": "from:bob"}, headers=AUTH)
    assert {"m1", "m3"} <= {m["id"] for m in from_bob.json()["messages"]}
    lunch = client.get(f"{GMAIL}/messages", params={"q": "lunch"}, headers=AUTH)
    assert lunch.json()["messages"][0]["id"] == "m2"
    inbox = client.get(
        f"{GMAIL}/messages",
        params={"labelIds": "INBOX"},
        headers=AUTH,
    )
    assert len(inbox.json()["messages"]) >= 2


def test_trash_untrash_modify_delete(client: TestClient):
    trashed = client.post(f"{GMAIL}/messages/m2/trash", headers=AUTH)
    assert "TRASH" in trashed.json()["labelIds"]
    assert "INBOX" not in trashed.json()["labelIds"]
    listed = client.get(f"{GMAIL}/messages", headers=AUTH)
    assert "m2" not in {m["id"] for m in listed.json().get("messages", [])}
    with_trash = client.get(f"{GMAIL}/messages", params={"includeSpamTrash": True}, headers=AUTH)
    assert "m2" in {m["id"] for m in with_trash.json()["messages"]}
    client.post(f"{GMAIL}/messages/m2/untrash", headers=AUTH)
    starred = client.post(
        f"{GMAIL}/messages/m2/modify",
        json={"addLabelIds": ["STARRED"]},
        headers=AUTH,
    )
    assert "STARRED" in starred.json()["labelIds"]
    client.delete(f"{GMAIL}/messages/m2", headers=AUTH)
    assert client.get(f"{GMAIL}/messages/m2", headers=AUTH).status_code == 404


def test_send_and_reset(client: TestClient):
    msg = EmailMessage()
    msg["From"] = "alice@example.com"
    msg["To"] = "bob@example.com"
    msg["Subject"] = "Ping"
    msg.set_content("Hello from Alice")
    sent = client.post(
        f"{GMAIL}/messages/send",
        json={"raw": b64url_encode(msg.as_bytes())},
        headers=AUTH,
    )
    assert sent.status_code == 200
    assert "SENT" in sent.json()["labelIds"]
    client.post("/reset")
    listed = client.get(f"{GMAIL}/messages", headers=AUTH)
    ids = {m["id"] for m in listed.json()["messages"]}
    assert {"m1", "m2", "m3"} <= ids
    assert sent.json()["id"] not in ids


def test_labels_and_threads(client: TestClient):
    labels = client.get(f"{GMAIL}/labels", headers=AUTH)
    names = {label["name"] for label in labels.json()["labels"]}
    assert "INBOX" in names
    assert "Ops" in names
    created = client.post(f"{GMAIL}/labels", json={"name": "Later"}, headers=AUTH)
    assert created.status_code == 200
    label_id = created.json()["id"]
    got = client.get(f"{GMAIL}/labels/{label_id}", headers=AUTH)
    assert got.json()["name"] == "Later"
    client.patch(f"{GMAIL}/labels/{label_id}", json={"name": "Soon"}, headers=AUTH)
    assert client.get(f"{GMAIL}/labels/{label_id}", headers=AUTH).json()["name"] == "Soon"
    client.delete(f"{GMAIL}/labels/{label_id}", headers=AUTH)
    assert client.get(f"{GMAIL}/labels/{label_id}", headers=AUTH).status_code == 404
    system = client.delete(f"{GMAIL}/labels/INBOX", headers=AUTH)
    assert system.status_code == 400

    threads = client.get(f"{GMAIL}/threads", headers=AUTH)
    assert threads.status_code == 200
    thread = client.get(f"{GMAIL}/threads/t1", headers=AUTH)
    assert thread.json()["messages"][0]["id"] == "m1"


def test_fixture_attachment(client: TestClient):
    full = client.get(f"{GMAIL}/messages/m3", headers=AUTH)
    assert full.status_code == 200

    def find_attachment(node):
        body = node.get("body") or {}
        if body.get("attachmentId") and node.get("filename") == "note.txt":
            return body["attachmentId"]
        for part in node.get("parts") or []:
            found = find_attachment(part)
            if found:
                return found
        return None

    attachment_id = find_attachment(full.json()["payload"])
    assert attachment_id
    fetched = client.get(
        f"{GMAIL}/messages/m3/attachments/{attachment_id}",
        headers=AUTH,
    )
    assert fetched.status_code == 200
    assert b64url_decode(fetched.json()["data"]) == b"hello from fixture"


def test_send_with_attachment(client: TestClient):
    msg = EmailMessage()
    msg["From"] = "alice@example.com"
    msg["To"] = "alice@example.com"
    msg["Subject"] = "File"
    msg.set_content("See attached")
    msg.add_attachment(b"hello-bytes", maintype="text", subtype="plain", filename="note.txt")
    sent = client.post(
        f"{GMAIL}/messages/send",
        json={"raw": b64url_encode(msg.as_bytes())},
        headers=AUTH,
    )
    assert sent.status_code == 200
    full = client.get(f"{GMAIL}/messages/{sent.json()['id']}", headers=AUTH).json()

    def find_attachment(node):
        body = node.get("body") or {}
        if body.get("attachmentId"):
            return body["attachmentId"]
        for part in node.get("parts") or []:
            found = find_attachment(part)
            if found:
                return found
        return None

    attachment_id = find_attachment(full["payload"])
    assert attachment_id
    fetched = client.get(
        f"{GMAIL}/messages/{sent.json()['id']}/attachments/{attachment_id}",
        headers=AUTH,
    )
    assert fetched.status_code == 200
    assert b64url_decode(fetched.json()["data"]) == b"hello-bytes"


def test_drafts(client: TestClient):
    listed = client.get(f"{GMAIL}/drafts", headers=AUTH)
    assert listed.status_code == 200
    assert listed.json()["drafts"][0]["id"] == "r-draft1"
    msg = EmailMessage()
    msg["From"] = "alice@example.com"
    msg["To"] = "carol@example.com"
    msg["Subject"] = "Drafted"
    msg.set_content("Soon")
    created = client.post(
        f"{GMAIL}/drafts",
        json={"message": {"raw": b64url_encode(msg.as_bytes())}},
        headers=AUTH,
    )
    assert created.status_code == 200
    draft_id = created.json()["id"]
    sent = client.post(f"{GMAIL}/drafts/send", json={"id": draft_id}, headers=AUTH)
    assert sent.status_code == 200
    assert "SENT" in sent.json()["labelIds"]
    assert client.get(f"{GMAIL}/drafts/{draft_id}", headers=AUTH).status_code == 404
