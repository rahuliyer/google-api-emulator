from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from google_api_emulator.app import create_app
from google_api_emulator.config import Settings

AUTH = {"Authorization": "Bearer test-token"}


@pytest.fixture
def fixtures_dir(tmp_path: Path) -> Path:
    src = Path(__file__).resolve().parents[1] / "fixtures" / "people.json"
    dest = tmp_path / "fixtures"
    dest.mkdir()
    dest.joinpath("people.json").write_text(src.read_text())
    return dest


@pytest.fixture
def client(tmp_path: Path, fixtures_dir: Path) -> TestClient:
    settings = Settings(
        fixtures_dir=fixtures_dir,
        db_path=tmp_path / "emulator.sqlite",
    )
    app = create_app(settings)
    return TestClient(app)
