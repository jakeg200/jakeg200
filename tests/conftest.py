from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# The suite must never reach for the network or an API key, whatever the developer has
# set in their shell. Determinism is a property of the tests, not of the environment.
os.environ["WARRANT_LLM_MODE"] = "off"
os.environ.pop("ANTHROPIC_API_KEY", None)


@pytest.fixture
def session(tmp_path: Path) -> Iterator[object]:
    from sqlmodel import Session

    from warrant import db
    from warrant.config import settings
    from warrant.seed import seed

    settings.database_url = f"sqlite:///{tmp_path / 'test.db'}"
    db.reset_engine()
    db.create_all()
    with Session(db.engine()) as session:
        seed(session)
        yield session


@pytest.fixture
def client(tmp_path: Path) -> Iterator[object]:
    from fastapi.testclient import TestClient

    from warrant import db
    from warrant.api.main import app
    from warrant.config import settings

    settings.database_url = f"sqlite:///{tmp_path / 'api.db'}"
    db.reset_engine()
    with TestClient(app) as client:
        yield client
