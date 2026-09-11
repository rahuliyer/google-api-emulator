from __future__ import annotations

import argparse

import uvicorn

from google_api_emulator.app import create_app
from google_api_emulator.config import Settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Google API emulator for local agent tests")
    parser.add_argument("--host", default=None, help="Bind host (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=None, help="Bind port (default 8080)")
    parser.add_argument(
        "--fixtures-dir",
        default=None,
        help="Directory of per-API fixture JSON files (GOOGLE_EMULATOR_FIXTURES_DIR)",
    )
    parser.add_argument(
        "--db-path",
        default=None,
        help="SQLite file path (GOOGLE_EMULATOR_DB, default emulator.sqlite)",
    )
    args = parser.parse_args()
    settings = Settings.from_env(
        fixtures_dir=args.fixtures_dir,
        db_path=args.db_path,
        host=args.host,
        port=args.port,
    )
    app = create_app(settings)
    uvicorn.run(app, host=settings.host, port=settings.port, workers=1)
