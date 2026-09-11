from __future__ import annotations

from fastapi import FastAPI

from google_api_emulator.admin import router as admin_router
from google_api_emulator.config import Settings
from google_api_emulator.db import Database
from google_api_emulator.errors import GoogleAPIError, google_api_error_handler
from google_api_emulator.services.gmail.routes import router as gmail_router
from google_api_emulator.services.people.routes import router as people_router
from google_api_emulator.state import EmulatorState


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    db = Database(settings.db_path)
    state = EmulatorState(settings=settings, db=db)
    state.reset()

    app = FastAPI(title="Google API Emulator", docs_url=None, redoc_url=None)
    app.state.emulator = state
    app.add_exception_handler(GoogleAPIError, google_api_error_handler)
    app.include_router(admin_router)
    app.include_router(people_router)
    app.include_router(gmail_router)
    return app
