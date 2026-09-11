# AGENTS.md

Guidance for coding agents working in this repository.

## What this is

A local Google API emulator for testing agents. Swap the Google host for this process; keep official REST paths, camelCase JSON, field masks, etags, and Google error envelopes.

People API is implemented. Gmail and Calendar are planned, not implemented.

## Commands

```bash
uv sync
uv run pytest
uv run google-api-emulator --port 8080 --fixtures-dir fixtures --db-path emulator.sqlite
```

Python ≥ 3.12. Package manager is **uv**. Do not add Poetry/pipenv.

## Verification

`uv run pytest` is not enough after People (or other Google) route changes. Start uvicorn and drive it with `google-api-python-client`. `TestClient` never hits colon-method URLs the way the official client does (`people:batchGet`, `alt=json`, Bearer from `Credentials`).

### 1. Fixture in `/tmp`

Write a dedicated seed, not the repo `fixtures/` dir:

```bash
mkdir -p /tmp/google_api_emulator_fixtures
```

`/tmp/google_api_emulator_fixtures/people.json` should include at least: one user with `tokens`, a `profile`, two contacts with names/emails, and one `otherContacts` entry.

### 2. Start the emulator

```bash
uv run google-api-emulator \
  --host 127.0.0.1 \
  --port 18080 \
  --fixtures-dir /tmp/google_api_emulator_fixtures \
  --db-path /tmp/google_api_emulator.sqlite
```

Confirm `GET http://127.0.0.1:18080/health` returns `{"status":"ok"}`. `/health` and `POST /reset` do not need a token.

### 3. Official Python client

```bash
uv run --with google-api-python-client --with google-auth --with google-auth-httplib2 python
```

```python
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

people = build(
    "people",
    "v1",
    credentials=Credentials(token="verify-token"),  # must send Bearer; AnonymousCredentials will 401
    client_options={"api_endpoint": "http://127.0.0.1:18080/services/people"},
)
```

`api_endpoint` with or without a trailing slash both work. Do not use `AnonymousCredentials` — the emulator requires `Authorization: Bearer`.

### 4. Checks that must pass

- `people.people().connections().list(resourceName="people/me", personFields="names,emailAddresses")` returns fixture contacts
- `people.people().get(resourceName="people/me", personFields="names")` is the fixture profile
- `people.people().getBatchGet(resourceNames=["people/me", "people/<id>", "people/missing"], personFields="names")` — 200, 200, 404 item in `responses`
- `people.people().searchContacts(query="", readMask="names")` warmup is empty; a prefix query hits a fixture name
- `people.otherContacts().list(readMask="names,emailAddresses")`
- `createContact` → `updateContact` with returned etag → stale etag is `HttpError` 400 → `deleteContact` → `get` is 404
- Request without `Authorization` to `/services/people/v1/people/me?personFields=names` is 401 `UNAUTHENTICATED`

Stop the server when done. Do not leave uvicorn on 18080.

For a new API, repeat this with that API’s `googleapiclient` service and `/services/{name}` endpoint.

## Layout

- `src/google_api_emulator/` — app, auth, SQLite, fixture loader, admin (`/health`, `POST /reset`)
- `src/google_api_emulator/services/people/` — People routes, store, field masks, search
- `fixtures/people.json` — People seed (one file per API: `fixtures/{api}.json`)
- `tests/` — pytest + httpx `TestClient`

New Google APIs go in `services/{name}/` and mount at `/services/{name}` with Google’s published path after that prefix:

| API | Mount (replaces this host) | Path after mount |
| --- | --- | --- |
| People | `/services/people` (`people.googleapis.com`) | `/v1/...` |
| Gmail | `/services/gmail` (`gmail.googleapis.com`) | `/gmail/v1/...` |
| Calendar | `/services/calendar` (`www.googleapis.com`) | `/calendar/v3/...` |

Do not flatten everything to `/v1/...`.

## Contract rules

- Wire JSON is proto-JSON **camelCase**. Never snake_case on `/services/...` responses.
- Errors: `{"error": {"code": 401, "message": "...", "status": "UNAUTHENTICATED"}}`
- `/services/...` requires `Authorization: Bearer <token>`. `/health` and `POST /reset` do not.
- `fixtures/allowed_tokens.json` is optional. Absent → accept any token. Present → only those tokens. Empty list → reject all.
- Token listed on a `people.json` user selects that user; otherwise the first fixture user.
- Startup and `POST /reset` drop SQLite and reload fixtures. The DB file is a working copy, not durable account state.
- People: honor required `personFields` / `readMask` / `updatePersonFields`; generate etags; `updateContact` must 400 on missing or mismatched etag; `people/me` is the authenticated profile; search is prefix-phrase match; empty search `query` is a warmup and returns no results.

Out of scope unless asked: OAuth/OIDC, discovery docs, quotas, contact groups, directory, photos, sync tokens, batch mutate, multi-worker.

## Adding an API

1. Add `fixtures/{api}.json` and a loader in `fixtures.py` (or a sibling) called from `EmulatorState.reset()`.
2. Add `services/{api}/` routes mounted under `/services/{name}` with official paths.
3. Reuse `auth.require_user`, `errors.GoogleAPIError`, and the SQLite `Database`.
4. pytest for the Google shape, then the **Verification** section against a running server.
