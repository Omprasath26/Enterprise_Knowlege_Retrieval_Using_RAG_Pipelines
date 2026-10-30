
import hashlib
import os
import tempfile
import time
import uuid

from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from app.core.config import get_settings
from app.services import document_repository
from app.services.document_repository import (
    DocumentRepositoryError,
    DuplicateChecksumError,
)
from app.services.document_validator import validate_document


class DuplicateDocumentError(Exception):
    """Raised when identical document content already exists."""


class DocumentStorageError(Exception):
    """Raised when document storage fails."""


@dataclass(frozen=True)
class StoredDocument:
    """Metadata returned after successfully storing a document."""

    document_id: str
    filename: str
    file_type: str
    file_size: int
    checksum: str
    storage_path: Path


# Prevent simultaneous storage operations within this application process.
_storage_lock = Lock()


def calculate_checksum(content: bytes) -> str:
    """Generate a SHA-256 checksum for document content."""

    return hashlib.sha256(content).hexdigest()


def _calculate_file_checksum(file_path: Path) -> str:
    """Calculate SHA-256 without loading the entire file into memory."""

    sha256 = hashlib.sha256()

    with file_path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            sha256.update(chunk)

    return sha256.hexdigest()


def _check_duplicate(
    originals_directory: Path,
    checksum: str,
) -> bool:
    """Check completed stored documents for duplicate content."""

    if not originals_directory.exists():
        return False

    for existing_file in originals_directory.iterdir():
        if not existing_file.is_file():
            continue

        # Temporary upload files are not completed documents.
        if existing_file.name.startswith(".upload_"):
            continue

        try:
            if _calculate_file_checksum(existing_file) == checksum:
                return True

        except OSError as exc:
            raise DocumentStorageError(
                "Unable to verify an existing stored document."
            ) from exc

    return False


def _remove_stored_file(file_path: Path) -> None:
    """Remove a newly stored file after metadata registration fails."""

    try:
        file_path.unlink(missing_ok=True)

    except OSError as exc:
        raise DocumentStorageError(
            "Database registration failed and the stored file "
            "could not be removed."
        ) from exc


def _write_file_atomically(
    content: bytes,
    originals_directory: Path,
    final_path: Path,
) -> None:
    """Write a file atomically, with retries for transient Windows locks."""

    file_descriptor, temporary_path = tempfile.mkstemp(
        prefix=".upload_",
        suffix=".tmp",
        dir=str(originals_directory),
    )

    try:
        with os.fdopen(file_descriptor, "wb") as temporary_file:
            temporary_file.write(content)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())

        # Windows antivirus or indexing services can briefly lock files.
        for attempt in range(5):
            try:
                os.replace(temporary_path, final_path)
                return

            except PermissionError:
                if attempt == 4:
                    raise

                time.sleep(0.1 * (attempt + 1))

    except Exception:
        try:
            Path(temporary_path).unlink(missing_ok=True)
        except OSError:
            pass

        raise


def _store_document(
    filename: str,
    content: bytes,
) -> StoredDocument:
    """Validate, store and register document metadata in SQLite."""

    validated = validate_document(filename, content)
    settings = get_settings()

    originals_directory = (
        Path(settings.storage_root) / "uploads" / "originals"
    )

    checksum = calculate_checksum(content)

    try:
        originals_directory.mkdir(parents=True, exist_ok=True)

        # Check SQLite for already registered documents.
        try:
            existing_document = (
                document_repository.get_document_by_checksum(checksum)
            )
        except DocumentRepositoryError as exc:
            raise DocumentStorageError(
                "Unable to check existing document metadata."
            ) from exc

        if existing_document is not None:
            raise DuplicateDocumentError(
                "A document with identical content already exists."
            )

        # Check legacy files that may not yet have database records.
        if _check_duplicate(originals_directory, checksum):
            raise DuplicateDocumentError(
                "A document with identical content already exists."
            )

        document_id = str(uuid.uuid4())
        final_path = (
            originals_directory
            / f"{document_id}.{validated.file_type}"
        )

        _write_file_atomically(
            content,
            originals_directory,
            final_path,
        )

        # Register metadata only after the file has been stored.
        try:
            document_repository.register_document(
                document_id=document_id,
                filename=validated.filename,
                file_type=validated.file_type,
                file_size=validated.file_size,
                checksum=checksum,
                storage_path=str(final_path),
            )

        except DuplicateChecksumError as exc:
            _remove_stored_file(final_path)

            raise DuplicateDocumentError(
                "A document with identical content already exists."
            ) from exc

        except DocumentRepositoryError as exc:
            _remove_stored_file(final_path)

            raise DocumentStorageError(
                "Document metadata registration failed."
            ) from exc

        return StoredDocument(
            document_id=document_id,
            filename=validated.filename,
            file_type=validated.file_type,
            file_size=validated.file_size,
            checksum=checksum,
            storage_path=final_path,
        )

    except (
        DuplicateDocumentError,
        DocumentStorageError,
    ):
        raise

    except OSError as exc:
        raise DocumentStorageError(
            "Failed to store the uploaded document."
        ) from exc


def store_document(
    filename: str,
    content: bytes,
) -> StoredDocument:
    """Serialize local storage operations and store a document."""

    with _storage_lock:
        return _store_document(filename, content)
