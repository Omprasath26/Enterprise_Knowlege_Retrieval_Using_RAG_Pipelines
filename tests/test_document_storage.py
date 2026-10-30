
import hashlib
import uuid

from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from app.services import document_repository
from app.services import document_storage

from app.services.document_repository import (
    DocumentRepositoryError,
)
from app.services.document_storage import (
    DuplicateDocumentError,
    DocumentStorageError,
    store_document,
)


@pytest.fixture
def storage_environment(tmp_path, monkeypatch):
    """Set up isolated filesystem storage and SQLite database."""

    settings = SimpleNamespace(
        storage_root=tmp_path,
        max_upload_size_mb=25,
    )

    monkeypatch.setattr(
        document_storage,
        "get_settings",
        lambda: settings,
    )

    database_path = tmp_path / "metadata" / "documents.db"

    monkeypatch.setattr(
        document_repository,
        "get_database_path",
        lambda: database_path,
    )

    document_repository.initialize_database()

    return tmp_path


def test_document_is_stored_successfully(storage_environment):
    content = b"Automated storage test"

    result = store_document("sample.txt", content)

    assert result.filename == "sample.txt"
    assert result.file_type == "txt"
    assert result.file_size == len(content)
    assert result.storage_path.exists()
    assert result.storage_path.read_bytes() == content


def test_document_id_is_a_valid_uuid(storage_environment):
    result = store_document("sample.txt", b"UUID test")

    parsed_id = uuid.UUID(result.document_id)

    assert str(parsed_id) == result.document_id


def test_sha256_checksum_is_correct(storage_environment):
    content = b"Checksum verification"

    result = store_document("checksum.txt", content)

    expected_checksum = hashlib.sha256(content).hexdigest()

    assert result.checksum == expected_checksum


def test_identical_content_is_rejected_even_with_different_filename(
    storage_environment,
):
    content = b"Duplicate detection test"

    store_document("first.txt", content)

    with pytest.raises(DuplicateDocumentError):
        store_document("second.txt", content)


def test_different_content_is_accepted(storage_environment):
    first = store_document("first.txt", b"First document")
    second = store_document("second.txt", b"Second document")

    assert first.document_id != second.document_id
    assert first.checksum != second.checksum
    assert first.storage_path.exists()
    assert second.storage_path.exists()


def test_document_metadata_is_registered_in_sqlite(storage_environment):
    content = b"SQLite metadata integration"

    result = store_document("policy.txt", content)

    metadata = document_repository.get_document_by_id(
        result.document_id
    )

    assert metadata is not None
    assert metadata["filename"] == "policy.txt"
    assert metadata["file_type"] == "txt"
    assert metadata["file_size"] == len(content)
    assert metadata["checksum"] == result.checksum
    assert metadata["status"] == "UPLOADED"


def test_duplicate_in_sqlite_is_rejected(
    storage_environment,
    monkeypatch,
):
    content = b"Existing database document"
    checksum = hashlib.sha256(content).hexdigest()

    document_repository.register_document(
        document_id="existing-document",
        filename="existing.txt",
        file_type="txt",
        file_size=len(content),
        checksum=checksum,
        storage_path="legacy/existing.txt",
    )

    # Simulate a file not being present in the originals directory.
    monkeypatch.setattr(
        document_storage,
        "_check_duplicate",
        lambda directory, value: False,
    )

    with pytest.raises(DuplicateDocumentError):
        store_document("duplicate.txt", content)


def test_database_failure_removes_newly_stored_file(
    storage_environment,
    monkeypatch,
):
    def fail_registration(**kwargs):
        raise DocumentRepositoryError(
            "Simulated database failure"
        )

    monkeypatch.setattr(
        document_repository,
        "register_document",
        fail_registration,
    )

    with pytest.raises(DocumentStorageError):
        store_document("database_failure.txt", b"Database failure test")

    originals_directory = (
        storage_environment / "uploads" / "originals"
    )

    remaining_files = list(originals_directory.iterdir())

    assert remaining_files == []


def test_concurrent_duplicate_uploads_register_only_once(
    storage_environment,
):
    content = b"Concurrent duplicate upload test"

    def upload_document(index):
        try:
            result = store_document(
                f"concurrent_{index}.txt",
                content,
            )
            return ("success", result.document_id)

        except DuplicateDocumentError:
            return ("duplicate", None)

    with ThreadPoolExecutor(max_workers=5) as executor:
        results = list(
            executor.map(upload_document, range(5))
        )

    successful_uploads = [
        result for result in results
        if result[0] == "success"
    ]

    duplicate_uploads = [
        result for result in results
        if result[0] == "duplicate"
    ]

    assert len(successful_uploads) == 1
    assert len(duplicate_uploads) == 4

    stored_metadata = document_repository.get_document_by_checksum(
        hashlib.sha256(content).hexdigest()
    )

    assert stored_metadata is not None
