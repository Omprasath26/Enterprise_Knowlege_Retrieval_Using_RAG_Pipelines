
from types import SimpleNamespace

import pytest

from fastapi.testclient import TestClient

from app.main import app
from app.services import document_repository


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Create an isolated API test client without real Celery jobs."""

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

    # Never submit real background jobs during API tests.
    monkeypatch.setattr(
        "app.api.routes.documents._queue_document_ingestion",
        lambda document_id: "test-task-id",
    )

    test_database_path = tmp_path / "metadata" / "documents.db"

    monkeypatch.setattr(
        document_repository,
        "get_database_path",
        lambda: test_database_path,
    )

    document_repository.initialize_database()

    return TestClient(app)


def upload_txt(client, filename="sample.txt", content=b"API test document"):
    """Upload a text document and return its response."""

    return client.post(
        "/api/v1/documents/upload",
        files={"file": (filename, content, "text/plain")},
    )


def test_upload_valid_pdf_returns_201(client, tmp_path):
    """A valid PDF should be stored and queued successfully."""

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
    assert data["task_id"] == "test-task-id"
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
    assert data["task_id"] == "test-task-id"


def test_duplicate_upload_returns_409(client):
    """Identical content must be rejected even with another filename."""

    content = b"Duplicate API test document"

    first_response = upload_txt(
        client,
        "first.txt",
        content,
    )

    second_response = upload_txt(
        client,
        "second.txt",
        content,
    )

    assert first_response.status_code == 201
    assert second_response.status_code == 409

    assert second_response.json()["detail"] == (
        "A document with identical content already exists."
    )


def test_upload_registers_metadata_in_sqlite(client):
    """A successful API upload must create a SQLite metadata record."""

    content = b"API and SQLite integration test"

    response = upload_txt(
        client,
        "company_policy.txt",
        content,
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


def test_upload_queue_failure_keeps_document_uploaded(
    client,
    monkeypatch,
):
    """A queue failure must not lose the successfully stored document."""

    monkeypatch.setattr(
        "app.api.routes.documents._queue_document_ingestion",
        lambda document_id: None,
    )

    response = upload_txt(
        client,
        "queue_failure.txt",
        b"Queue failure test",
    )

    assert response.status_code == 201

    data = response.json()

    assert data["status"] == "UPLOADED"
    assert data["task_id"] is None
    assert "could not be queued" in data["message"]

    metadata = document_repository.get_document_by_id(
        data["document_id"]
    )

    assert metadata is not None
    assert metadata["status"] == "UPLOADED"


def test_get_document_status_returns_200(client):
    """The status endpoint should return the SQLite document status."""

    upload_response = upload_txt(client)

    document_id = upload_response.json()["document_id"]

    response = client.get(
        f"/api/v1/documents/{document_id}"
    )

    assert response.status_code == 200

    data = response.json()

    assert data["document_id"] == document_id
    assert data["filename"] == "sample.txt"
    assert data["status"] == "UPLOADED"
    assert "awaiting processing" in data["message"]


def test_get_unknown_document_status_returns_404(client):
    """Unknown document IDs should return 404."""

    response = client.get(
        "/api/v1/documents/00000000-0000-0000-0000-000000000000"
    )

    assert response.status_code == 404


def test_retry_uploaded_document_returns_task_id(client):
    """An uploaded document can be submitted for ingestion."""

    upload_response = upload_txt(client)

    document_id = upload_response.json()["document_id"]

    response = client.post(
        f"/api/v1/documents/{document_id}/process"
    )

    assert response.status_code == 200

    data = response.json()

    assert data["document_id"] == document_id
    assert data["task_id"] == "test-task-id"
    assert data["status"] == "UPLOADED"


def test_retry_unknown_document_returns_404(client):
    """Unknown documents cannot be submitted for processing."""

    response = client.post(
        "/api/v1/documents/00000000-0000-0000-0000-000000000000/process"
    )

    assert response.status_code == 404


def test_retry_completed_document_returns_409(client):
    """Completed documents cannot be submitted again."""

    upload_response = upload_txt(client)

    document_id = upload_response.json()["document_id"]

    document_repository.update_document_status(
        document_id,
        "PROCESSING",
    )

    document_repository.update_document_status(
        document_id,
        "COMPLETED",
    )

    response = client.post(
        f"/api/v1/documents/{document_id}/process"
    )

    assert response.status_code == 409


def test_retry_queue_failure_returns_503(client, monkeypatch):
    """Queue submission failure during retry should return 503."""

    upload_response = upload_txt(client)

    document_id = upload_response.json()["document_id"]

    monkeypatch.setattr(
        "app.api.routes.documents._queue_document_ingestion",
        lambda document_id: None,
    )

    response = client.post(
        f"/api/v1/documents/{document_id}/process"
    )

    assert response.status_code == 503

    metadata = document_repository.get_document_by_id(
        document_id
    )

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
        files={
            "file": (
                "fake.pdf",
                b"This is not a PDF",
                "application/pdf",
            )
        },
    )

    assert response.status_code == 400
