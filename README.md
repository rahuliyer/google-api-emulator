# Google API Emulator

Local stand-in for Google APIs so you can test an agent without hitting production. Point the agent’s **People API base URL** at this process; request paths, JSON, field masks, etags, and errors stay Google-shaped.

People API is implemented first. Gmail and Calendar can mount the same way later.

## Run

```bash
uv sync
uv run google-api-emulator --port 8080 --fixtures-dir fixtures --db-path emulator.sqlite
```

- `--fixtures-dir` / `GOOGLE_EMULATOR_FIXTURES_DIR` (default `fixtures/`)
- `--db-path` / `GOOGLE_EMULATOR_DB` (default `emulator.sqlite`)

Startup (and `POST /reset`) wipe the SQLite file and reload fixtures. The database is a working copy you can inspect with the `sqlite3` CLI, not a long-lived account.

Run a single worker. `/health` and `POST /reset` do not require a token.

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

Calendar client libraries that replace `rootUrl + servicePath` should set `api_endpoint` to `http://127.0.0.1:8080/services/calendar/calendar/v3`.

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

One JSON file per API. People seed: [`fixtures/people.json`](fixtures/people.json).

`POST /reset` reloads every fixture file in the directory (including `allowed_tokens.json` if you add it).

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

## Tests

```bash
uv run pytest
```
