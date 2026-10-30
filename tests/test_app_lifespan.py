
import sqlite3

from fastapi.testclient import TestClient

from app.main import app
from app.services import document_repository


def test_startup_initializes_document_database(tmp_path, monkeypatch):
    """Verify that application startup creates the SQLite database."""

    test_database_path = tmp_path / "metadata" / "documents.db"

    monkeypatch.setattr(
        document_repository,
        "get_database_path",
        lambda: test_database_path,
    )

    with TestClient(app) as client:
        response = client.get("/api/v1/health")

        assert response.status_code == 200

    assert test_database_path.exists()

    with sqlite3.connect(test_database_path) as connection:
        result = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
            AND name = 'documents'
            """
        ).fetchone()

    assert result is not None
    assert result[0] == "documents"
