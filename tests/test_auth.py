from pathlib import Path

from fastapi.testclient import TestClient

from google_api_emulator.app import create_app
from google_api_emulator.config import Settings


def test_health_does_not_require_auth(client):
    response = client.get("/health")
    assert response.status_code == 200


def test_reset_does_not_require_auth(client):
    response = client.post("/reset")
    assert response.status_code == 200


def test_missing_bearer_is_unauthenticated(client):
    response = client.get("/services/people/v1/people/me/connections", params={"personFields": "names"})
    assert response.status_code == 401
    body = response.json()["error"]
    assert body["status"] == "UNAUTHENTICATED"
    assert body["code"] == 401


def test_non_bearer_header_is_unauthenticated(client):
    response = client.get(
        "/services/people/v1/people/me/connections",
        params={"personFields": "names"},
        headers={"Authorization": "Basic abc"},
    )
    assert response.status_code == 401


def test_any_token_accepted_without_allowlist(client):
    response = client.get(
        "/services/people/v1/people/me/connections",
        params={"personFields": "names"},
        headers={"Authorization": "Bearer anything"},
    )
    assert response.status_code == 200


def test_fixture_token_maps_to_user(client):
    response = client.get(
        "/services/people/v1/people/me",
        params={"personFields": "names,emailAddresses"},
        headers={"Authorization": "Bearer alice-token"},
    )
    assert response.status_code == 200
    assert response.json()["names"][0]["givenName"] == "Alice"


def test_allowlist_rejects_unknown_token(tmp_path: Path, fixtures_dir: Path):
    fixtures_dir.joinpath("allowed_tokens.json").write_text(
        '{"tokens": ["alice-token"]}'
    )
    app = create_app(
        Settings(fixtures_dir=fixtures_dir, db_path=tmp_path / "emulator.sqlite")
    )
    client = TestClient(app)
    denied = client.get(
        "/services/people/v1/people/me/connections",
        params={"personFields": "names"},
        headers={"Authorization": "Bearer nope"},
    )
    assert denied.status_code == 401
    allowed = client.get(
        "/services/people/v1/people/me/connections",
        params={"personFields": "names"},
        headers={"Authorization": "Bearer alice-token"},
    )
    assert allowed.status_code == 200


def test_empty_allowlist_rejects_all(tmp_path: Path, fixtures_dir: Path):
    fixtures_dir.joinpath("allowed_tokens.json").write_text('{"tokens": []}')
    app = create_app(
        Settings(fixtures_dir=fixtures_dir, db_path=tmp_path / "allow.sqlite")
    )
    client = TestClient(app)
    response = client.get(
        "/services/people/v1/people/me/connections",
        params={"personFields": "names"},
        headers={"Authorization": "Bearer alice-token"},
    )
    assert response.status_code == 401


def test_reset_reloads_allowlist(tmp_path: Path, fixtures_dir: Path):
    app = create_app(
        Settings(fixtures_dir=fixtures_dir, db_path=tmp_path / "reset.sqlite")
    )
    client = TestClient(app)
    assert (
        client.get(
            "/services/people/v1/people/me/connections",
            params={"personFields": "names"},
            headers={"Authorization": "Bearer later-token"},
        ).status_code
        == 200
    )
    fixtures_dir.joinpath("allowed_tokens.json").write_text(
        '{"tokens": ["alice-token"]}'
    )
    client.post("/reset")
    assert (
        client.get(
            "/services/people/v1/people/me/connections",
            params={"personFields": "names"},
            headers={"Authorization": "Bearer later-token"},
        ).status_code
        == 401
    )
