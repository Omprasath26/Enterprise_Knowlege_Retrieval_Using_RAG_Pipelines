
from types import SimpleNamespace

import pytest

from fastapi.testclient import TestClient

from app.main import app
from app.services import document_repository


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Create a test client with isolated file and database storage."""

    settings = SimpleNamespace(
        storage_root=tmp_path,
        max_upload_size_mb=1,
    )

    monkeypatch.setattr(
        "app.api.routes.documents.get_settings",
        lambda: settings,
    )

    monkeypatch.setattr(
        "app.services.document_storage.get_settings",
        lambda: settings,
    )

    monkeypatch.setattr(
        "app.services.document_validator.get_settings",
        lambda: settings,
    )

    # Keep API test metadata separate from the real project database.
    test_database_path = tmp_path / "metadata" / "documents.db"

    monkeypatch.setattr(
        document_repository,
        "get_database_path",
        lambda: test_database_path,
    )

    document_repository.initialize_database()

    return TestClient(app)


def test_upload_valid_pdf_returns_201(client, tmp_path):
    """A valid PDF should be uploaded successfully."""

    content = b"%PDF-1.4\nTest PDF document content"

    response = client.post(
        "/api/v1/documents/upload",
        files={"file": ("sample.pdf", content, "application/pdf")},
    )

    assert response.status_code == 201

    data = response.json()

    assert data["filename"] == "sample.pdf"
    assert data["file_type"] == "pdf"
    assert data["status"] == "UPLOADED"
    assert len(data["checksum"]) == 64

    stored_files = list(
        (tmp_path / "uploads" / "originals").glob("*.pdf")
    )

    assert len(stored_files) == 1
    assert stored_files[0].read_bytes() == content


def test_upload_valid_txt_returns_201(client):
    """A valid text document should be uploaded successfully."""

    content = b"Enterprise RAG upload API test"

    response = client.post(
        "/api/v1/documents/upload",
        files={"file": ("sample.txt", content, "text/plain")},
    )

    assert response.status_code == 201

    data = response.json()

    assert data["filename"] == "sample.txt"
    assert data["file_type"] == "txt"
    assert data["file_size"] == len(content)


def test_duplicate_upload_returns_409(client):
    """Identical content must be rejected even with another filename."""

    content = b"Duplicate API test document"

    first_response = client.post(
        "/api/v1/documents/upload",
        files={"file": ("first.txt", content, "text/plain")},
    )

    second_response = client.post(
        "/api/v1/documents/upload",
        files={"file": ("second.txt", content, "text/plain")},
    )

    assert first_response.status_code == 201
    assert second_response.status_code == 409

    assert second_response.json()["detail"] == (
        "A document with identical content already exists."
    )


def test_upload_registers_metadata_in_sqlite(client):
    """A successful API upload must create a SQLite metadata record."""

    content = b"API and SQLite integration test"

    response = client.post(
        "/api/v1/documents/upload",
        files={"file": ("company_policy.txt", content, "text/plain")},
    )

    assert response.status_code == 201

    data = response.json()

    metadata = document_repository.get_document_by_id(
        data["document_id"]
    )

    assert metadata is not None
    assert metadata["document_id"] == data["document_id"]
    assert metadata["filename"] == "company_policy.txt"
    assert metadata["file_type"] == "txt"
    assert metadata["file_size"] == len(content)
    assert metadata["checksum"] == data["checksum"]
    assert metadata["status"] == "UPLOADED"


def test_unsupported_extension_returns_415(client):
    """Unsupported file extensions must be rejected."""

    response = client.post(
        "/api/v1/documents/upload",
        files={
            "file": (
                "sample.exe",
                b"test content",
                "application/octet-stream",
            )
        },
    )

    assert response.status_code == 415


def test_oversized_upload_returns_413(client):
    """Files exceeding the configured limit must be rejected."""

    content = b"A" * (1024 * 1024 + 1)

    response = client.post(
        "/api/v1/documents/upload",
        files={"file": ("large.txt", content, "text/plain")},
    )

    assert response.status_code == 413


def test_invalid_pdf_returns_400(client):
    """A PDF extension with invalid content must be rejected."""

    response = client.post(
        "/api/v1/documents/upload",
        files={"file": ("fake.pdf", b"This is not a PDF", "application/pdf")},
    )

    assert response.status_code == 400
