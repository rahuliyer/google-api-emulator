from __future__ import annotations

from dataclasses import dataclass, field

from google_api_emulator.config import Settings
from google_api_emulator.db import Database
from google_api_emulator.fixtures import (
    load_allowed_tokens,
    load_calendar_fixture,
    load_gmail_fixture,
    load_people_fixture,
    load_places_fixture,
    load_routes_fixture,
    seed_calendar,
    seed_gmail,
    seed_people,
    seed_places,
    seed_routes,
)


@dataclass
class EmulatorState:
    settings: Settings
    db: Database
    allowed_tokens: set[str] | None = None
    default_user_id: str | None = None

    def reset(self) -> None:
        self.db.reset_schema()
        fixture = load_people_fixture(self.settings.fixtures_dir)
        seed_people(self.db, fixture)
        seed_gmail(self.db, load_gmail_fixture(self.settings.fixtures_dir))
        seed_calendar(self.db, load_calendar_fixture(self.settings.fixtures_dir))
        seed_places(self.db, load_places_fixture(self.settings.fixtures_dir))
        seed_routes(self.db, load_routes_fixture(self.settings.fixtures_dir))
        self.allowed_tokens = load_allowed_tokens(self.settings.fixtures_dir)
        self.default_user_id = fixture.users[0].id if fixture.users else None
