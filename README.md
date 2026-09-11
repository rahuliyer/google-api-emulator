# Google API Emulator

Local stand-in for Google APIs so you can test an agent without hitting production. Swap the Google host for this process; request paths, JSON, field masks, etags, and errors stay Google-shaped.

People, Gmail, and Calendar are implemented.

## Run

```bash
uv sync
uv run google-api-emulator --port 8080 --fixtures-dir fixtures --db-path emulator.sqlite
```

- `--fixtures-dir` / `GOOGLE_EMULATOR_FIXTURES_DIR` (default `fixtures/`)
- `--db-path` / `GOOGLE_EMULATOR_DB` (default `emulator.sqlite`)

Startup (and `POST /reset`) wipe the SQLite file and reload fixtures. The database is a working copy you can inspect with the `sqlite3` CLI, not a long-lived account.

Run a single worker. `/health` and `POST /reset` do not require a token.

## Point an agent at Gmail

Replace `https://gmail.googleapis.com` with:

```text
http://127.0.0.1:8080/services/gmail
```

```python
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

gmail = build(
    "gmail",
    "v1",
    credentials=Credentials(token="any-token"),
    client_options={"api_endpoint": "http://127.0.0.1:8080/services/gmail"},
)
gmail.users().messages().list(userId="me").execute()
```

```http
GET /services/gmail/gmail/v1/users/me/messages
Authorization: Bearer any-token
```

## Point an agent at Calendar

Replace `https://www.googleapis.com` with:

```text
http://127.0.0.1:8080/services/calendar
```

```python
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

calendar = build(
    "calendar",
    "v3",
    credentials=Credentials(token="any-token"),
    client_options={"api_endpoint": "http://127.0.0.1:8080/services/calendar"},
)
calendar.events().list(calendarId="primary").execute()
```

```http
GET /services/calendar/calendar/v3/calendars/primary/events
Authorization: Bearer any-token
```

## Point an agent at People

Replace `https://people.googleapis.com` with:

```text
http://127.0.0.1:8080/services/people
```

With `google-api-python-client`:

```python
from google.api_core.client_options import ClientOptions
from googleapiclient.discovery import build

service = build(
    "people",
    "v1",
    credentials=credentials,  # any credentials object; the emulator only checks Bearer
    client_options=ClientOptions(api_endpoint="http://127.0.0.1:8080/services/people"),
)
```

Example call (same as production):

```http
GET /services/people/v1/people/me/connections?personFields=names,emailAddresses
Authorization: Bearer any-token
```

Later APIs keep Google’s published path after `/services/{name}`:

| API | Agent base URL | Example path |
| --- | --- | --- |
| People | `http://127.0.0.1:8080/services/people` | `/services/people/v1/people/me/connections` |
| Gmail | `http://127.0.0.1:8080/services/gmail` | `/services/gmail/gmail/v1/users/me/messages` |
| Calendar | `http://127.0.0.1:8080/services/calendar` | `/services/calendar/calendar/v3/calendars/primary/events` |

Calendar client libraries that replace `rootUrl + servicePath` (`google-api-python-client`) should set `api_endpoint` to `http://127.0.0.1:8080/services/calendar`. Host-swap HTTP still uses `/services/calendar/calendar/v3/...`.

## Auth

Every `/services/...` route requires `Authorization: Bearer <token>`. Missing or non-Bearer credentials return Google’s `UNAUTHENTICATED` error body.

- If `fixtures/allowed_tokens.json` is **absent**, any non-empty token is accepted.
- If it is **present**, only listed tokens are accepted.

```json
{
  "tokens": ["alice-token", "bob-token"]
}
```

If the token appears on a user in `fixtures/people.json`, that user’s contacts are used; otherwise the first fixture user is used.

## Fixtures

One JSON file per API: [`fixtures/people.json`](fixtures/people.json), [`fixtures/gmail.json`](fixtures/gmail.json), [`fixtures/calendar.json`](fixtures/calendar.json). Gmail mailboxes and Calendar accounts are keyed by email and must match a People user.

`POST /reset` reloads every fixture file in the directory (including `allowed_tokens.json` if you add it).

Gmail messages and drafts can include `attachments`. Use `text` for UTF-8, or `data` for base64 / base64url bytes:

```json
"attachments": [
  { "filename": "note.txt", "mimeType": "text/plain", "text": "hello" },
  { "filename": "photo.png", "mimeType": "image/png", "data": "iVBORw0KGgo..." }
]
```

Calendar events use Google’s `start`/`end` objects (`dateTime` or all-day `date`):

```json
{
  "id": "evt1",
  "summary": "Lunch with Bob",
  "start": { "dateTime": "2026-01-15T12:00:00-08:00" },
  "end": { "dateTime": "2026-01-15T13:00:00-08:00" }
}
```

## People API coverage

| Method | Path |
| --- | --- |
| GET | `/services/people/v1/people/me/connections` |
| GET | `/services/people/v1/people:batchGet` |
| GET | `/services/people/v1/people:searchContacts` |
| POST | `/services/people/v1/people:createContact` |
| GET | `/services/people/v1/people/me` |
| GET | `/services/people/v1/people/{id}` |
| PATCH | `/services/people/v1/people/{id}:updateContact` |
| DELETE | `/services/people/v1/people/{id}:deleteContact` |
| GET | `/services/people/v1/otherContacts` |
| GET | `/services/people/v1/otherContacts:search` |

Not in this slice: contact groups, directory people, photos, sync tokens, batch mutate, OAuth.

## Gmail API coverage

| Method | Path |
| --- | --- |
| GET | `/services/gmail/gmail/v1/users/{userId}/profile` |
| GET | `/services/gmail/gmail/v1/users/{userId}/messages` |
| GET | `/services/gmail/gmail/v1/users/{userId}/messages/{id}` |
| POST | `/services/gmail/gmail/v1/users/{userId}/messages/send` |
| POST | `/services/gmail/gmail/v1/users/{userId}/messages/{id}/modify` |
| POST | `/services/gmail/gmail/v1/users/{userId}/messages/{id}/trash` |
| POST | `/services/gmail/gmail/v1/users/{userId}/messages/{id}/untrash` |
| DELETE | `/services/gmail/gmail/v1/users/{userId}/messages/{id}` |
| GET | `/services/gmail/gmail/v1/users/{userId}/messages/{id}/attachments/{id}` |
| GET/POST/DELETE | `/services/gmail/gmail/v1/users/{userId}/threads...` |
| GET/POST/PATCH/PUT/DELETE | `/services/gmail/gmail/v1/users/{userId}/labels...` |
| GET/POST/PUT/DELETE | `/services/gmail/gmail/v1/users/{userId}/drafts...` |

`userId` is `me` or the authenticated user’s email. Not in this slice: settings, CSE, watch, history, import/insert, media upload URIs.

## Calendar API coverage

| Method | Path |
| --- | --- |
| GET | `/services/calendar/calendar/v3/users/me/calendarList` |
| GET | `/services/calendar/calendar/v3/users/me/calendarList/{calendarId}` |
| GET | `/services/calendar/calendar/v3/calendars/{calendarId}` |
| POST | `/services/calendar/calendar/v3/calendars` |
| PATCH/PUT | `/services/calendar/calendar/v3/calendars/{calendarId}` |
| DELETE | `/services/calendar/calendar/v3/calendars/{calendarId}` |
| POST | `/services/calendar/calendar/v3/calendars/{calendarId}/clear` |
| GET | `/services/calendar/calendar/v3/calendars/{calendarId}/events` |
| POST | `/services/calendar/calendar/v3/calendars/{calendarId}/events` |
| GET | `/services/calendar/calendar/v3/calendars/{calendarId}/events/{eventId}` |
| PATCH/PUT | `/services/calendar/calendar/v3/calendars/{calendarId}/events/{eventId}` |
| DELETE | `/services/calendar/calendar/v3/calendars/{calendarId}/events/{eventId}` |
| POST | `/services/calendar/calendar/v3/freeBusy` |

`calendarId` is `primary` or the calendar id (the primary id is the user’s email). Not in this slice: ACL, watch, settings, colors, recurring instance expansion, import/move/quickAdd.

## Tests

```bash
uv run pytest
```
