
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.services import document_repository as repository


@pytest.fixture
def database(tmp_path, monkeypatch):
    """Create an isolated temporary database for each test."""

    database_path = tmp_path / "metadata" / "documents.db"

    monkeypatch.setattr(
        repository,
        "get_database_path",
        lambda: database_path,
    )

    repository.initialize_database()

    return database_path


def register_sample_document(
    document_id="doc-001",
    checksum="a" * 64,
):
    """Register a sample document."""

    return repository.register_document(
        document_id=document_id,
        filename="employee_policy.pdf",
        file_type="pdf",
        file_size=1024,
        checksum=checksum,
        storage_path="storage/uploads/originals/doc-001.pdf",
    )


# --------------------------------------------------
# EXISTING REPOSITORY TESTS
# --------------------------------------------------

def test_database_initialization(database):
    """Verify that the documents table is created."""

    with repository.get_connection() as connection:
        tables = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
            """
        ).fetchall()

    assert "documents" in [row["name"] for row in tables]


def test_document_registration(database):
    """Verify successful document metadata registration."""

    result = register_sample_document()

    assert result["document_id"] == "doc-001"
    assert result["filename"] == "employee_policy.pdf"
    assert result["file_type"] == "pdf"
    assert result["file_size"] == 1024
    assert result["status"] == "UPLOADED"


def test_retrieve_document_by_id(database):
    """Verify document retrieval using its unique ID."""

    register_sample_document()

    result = repository.get_document_by_id("doc-001")

    assert result is not None
    assert result["document_id"] == "doc-001"
    assert result["filename"] == "employee_policy.pdf"


def test_duplicate_checksum_rejected(database):
    """Verify that identical document content cannot be registered twice."""

    register_sample_document()

    with pytest.raises(repository.DuplicateChecksumError):
        register_sample_document(
            document_id="doc-002",
        )


def test_document_persistence_after_reconnection(database):
    """Verify metadata remains available after reconnecting."""

    register_sample_document()

    result = repository.get_document_by_id("doc-001")

    assert result is not None
    assert result["document_id"] == "doc-001"

    assert database.exists()


def test_concurrent_duplicate_registration(database):
    """Verify concurrent registrations cannot create duplicate checksums."""

    def attempt_registration(index):
        try:
            register_sample_document(
                document_id=f"doc-{index}",
                checksum="b" * 64,
            )
            return "success"

        except repository.DuplicateChecksumError:
            return "duplicate"

    with ThreadPoolExecutor(max_workers=5) as executor:
        results = list(executor.map(attempt_registration, range(5)))

    assert results.count("success") == 1
    assert results.count("duplicate") == 4


# --------------------------------------------------
# NEW DOCUMENT STATUS TESTS
# --------------------------------------------------

def test_document_status_uploaded_to_processing(database):
    register_sample_document()

    result = repository.update_document_status(
        "doc-001",
        "PROCESSING",
    )

    assert result["status"] == "PROCESSING"


def test_document_status_processing_to_completed(database):
    register_sample_document()

    repository.update_document_status("doc-001", "PROCESSING")

    result = repository.update_document_status(
        "doc-001",
        "COMPLETED",
    )

    assert result["status"] == "COMPLETED"


def test_document_status_processing_to_failed(database):
    register_sample_document()

    repository.update_document_status("doc-001", "PROCESSING")

    result = repository.update_document_status(
        "doc-001",
        "FAILED",
    )

    assert result["status"] == "FAILED"


def test_failed_document_can_be_retried(database):
    register_sample_document()

    repository.update_document_status("doc-001", "PROCESSING")
    repository.update_document_status("doc-001", "FAILED")

    result = repository.update_document_status(
        "doc-001",
        "PROCESSING",
    )

    assert result["status"] == "PROCESSING"


def test_repeated_status_update_is_idempotent(database):
    register_sample_document()

    repository.update_document_status("doc-001", "PROCESSING")

    result = repository.update_document_status(
        "doc-001",
        "PROCESSING",
    )

    assert result["status"] == "PROCESSING"


def test_completed_document_cannot_be_reprocessed(database):
    register_sample_document()

    repository.update_document_status("doc-001", "PROCESSING")
    repository.update_document_status("doc-001", "COMPLETED")

    with pytest.raises(
        repository.InvalidDocumentStatusTransitionError
    ):
        repository.update_document_status(
            "doc-001",
            "PROCESSING",
        )


def test_nonexistent_document_status_update(database):
    with pytest.raises(repository.DocumentNotFoundError):
        repository.update_document_status(
            "missing-document",
            "PROCESSING",
        )


def test_unsupported_document_status_rejected(database):
    register_sample_document()

    with pytest.raises(
        repository.InvalidDocumentStatusTransitionError
    ):
        repository.update_document_status(
            "doc-001",
            "INVALID",
        )
