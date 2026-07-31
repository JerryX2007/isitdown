import pytest
from fastapi.testclient import TestClient

import database


@pytest.fixture
def client(tmp_path, monkeypatch):
    test_database = tmp_path / "test.db"
    monkeypatch.setattr(database, "DATABASE", test_database)
    database.init_db()

    from main import app

    with TestClient(app) as test_client:
        yield test_client
