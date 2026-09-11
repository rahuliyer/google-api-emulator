from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    fixtures_dir: Path
    db_path: Path
    host: str = "127.0.0.1"
    port: int = 8080

    @classmethod
    def from_env(
        cls,
        *,
        fixtures_dir: str | os.PathLike[str] | None = None,
        db_path: str | os.PathLike[str] | None = None,
        host: str | None = None,
        port: int | None = None,
    ) -> Settings:
        fixtures = Path(
            fixtures_dir
            or os.environ.get("GOOGLE_EMULATOR_FIXTURES_DIR", "fixtures")
        )
        database = Path(db_path or os.environ.get("GOOGLE_EMULATOR_DB", "emulator.sqlite"))
        return cls(
            fixtures_dir=fixtures,
            db_path=database,
            host=host or os.environ.get("GOOGLE_EMULATOR_HOST", "127.0.0.1"),
            port=port if port is not None else int(os.environ.get("GOOGLE_EMULATOR_PORT", "8080")),
        )
