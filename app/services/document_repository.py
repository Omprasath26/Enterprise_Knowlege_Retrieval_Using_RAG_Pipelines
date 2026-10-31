
import sqlite3

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from app.core.config import get_settings


class DuplicateChecksumError(Exception):
    """Raised when a document checksum already exists in the database."""


class DocumentRepositoryError(Exception):
    """Raised when a database operation fails."""


class DocumentNotFoundError(DocumentRepositoryError):
    """Raised when the requested document does not exist."""


class InvalidDocumentStatusTransitionError(DocumentRepositoryError):
    """Raised when a document status transition is not permitted."""


def get_database_path() -> Path:
    """Return the configured SQLite database path."""

    return Path(get_settings().storage_root) / "metadata" / "documents.db"


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    """Create, manage transactions, and reliably close a SQLite connection."""

    database_path = get_database_path()
    database_path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(
        database_path,
        timeout=30,
    )

    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")

        yield connection

        connection.commit()

    except BaseException:
        connection.rollback()
        raise

    finally:
        connection.close()


def initialize_database() -> None:
    """Create the document metadata table if it does not exist."""

    try:
        with get_connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    document_id TEXT PRIMARY KEY,
                    filename TEXT NOT NULL,
                    file_type TEXT NOT NULL,
                    file_size INTEGER NOT NULL CHECK (file_size > 0),
                    checksum TEXT NOT NULL UNIQUE,
                    storage_path TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'UPLOADED'
                        CHECK (
                            status IN (
                                'UPLOADED',
                                'PROCESSING',
                                'COMPLETED',
                                'FAILED'
                            )
                        ),
                    uploaded_at TEXT NOT NULL
                )
                """
            )

            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_documents_uploaded_at
                ON documents(uploaded_at)
                """
            )

    except sqlite3.Error as exc:
        raise DocumentRepositoryError(
            "Failed to initialize the document database."
        ) from exc


def register_document(
    document_id: str,
    filename: str,
    file_type: str,
    file_size: int,
    checksum: str,
    storage_path: str,
) -> dict[str, Any]:
    """Register document metadata using an immediate transaction."""

    uploaded_at = datetime.now(timezone.utc).isoformat()

    try:
        with get_connection() as connection:
            connection.execute("BEGIN IMMEDIATE")

            existing = connection.execute(
                """
                SELECT document_id
                FROM documents
                WHERE checksum = ?
                """,
                (checksum,),
            ).fetchone()

            if existing:
                raise DuplicateChecksumError(
                    "A document with identical content already exists."
                )

            connection.execute(
                """
                INSERT INTO documents (
                    document_id,
                    filename,
                    file_type,
                    file_size,
                    checksum,
                    storage_path,
                    status,
                    uploaded_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document_id,
                    filename,
                    file_type,
                    file_size,
                    checksum,
                    storage_path,
                    "UPLOADED",
                    uploaded_at,
                ),
            )

            return {
                "document_id": document_id,
                "filename": filename,
                "file_type": file_type,
                "file_size": file_size,
                "checksum": checksum,
                "storage_path": storage_path,
                "status": "UPLOADED",
                "uploaded_at": uploaded_at,
            }

    except DuplicateChecksumError:
        raise

    except sqlite3.IntegrityError as exc:
        if "checksum" in str(exc).lower():
            raise DuplicateChecksumError(
                "A document with identical content already exists."
            ) from exc

        raise DocumentRepositoryError(
            "Document metadata violates a database constraint."
        ) from exc

    except sqlite3.Error as exc:
        raise DocumentRepositoryError(
            "Failed to register document metadata."
        ) from exc


def get_document_by_id(document_id: str) -> dict[str, Any] | None:
    """Retrieve a document using its unique ID."""

    try:
        with get_connection() as connection:
            row = connection.execute(
                "SELECT * FROM documents WHERE document_id = ?",
                (document_id,),
            ).fetchone()

            return dict(row) if row else None

    except sqlite3.Error as exc:
        raise DocumentRepositoryError(
            "Failed to retrieve document metadata."
        ) from exc


def get_document_by_checksum(checksum: str) -> dict[str, Any] | None:
    """Retrieve a document using its SHA-256 checksum."""

    try:
        with get_connection() as connection:
            row = connection.execute(
                "SELECT * FROM documents WHERE checksum = ?",
                (checksum,),
            ).fetchone()

            return dict(row) if row else None

    except sqlite3.Error as exc:
        raise DocumentRepositoryError(
            "Failed to retrieve document metadata."
        ) from exc


def update_document_status(
    document_id: str,
    new_status: str,
) -> dict[str, Any]:
    """Update document status using validated, atomic transitions."""

    allowed_statuses = {
        "UPLOADED",
        "PROCESSING",
        "COMPLETED",
        "FAILED",
    }

    allowed_transitions = {
        "UPLOADED": {"PROCESSING"},
        "PROCESSING": {"COMPLETED", "FAILED"},
        "FAILED": {"PROCESSING"},
        "COMPLETED": set(),
    }

    if new_status not in allowed_statuses:
        raise InvalidDocumentStatusTransitionError(
            f"Unsupported document status: {new_status}"
        )

    try:
        with get_connection() as connection:
            connection.execute("BEGIN IMMEDIATE")

            row = connection.execute(
                """
                SELECT *
                FROM documents
                WHERE document_id = ?
                """,
                (document_id,),
            ).fetchone()

            if row is None:
                raise DocumentNotFoundError(
                    f"Document not found: {document_id}"
                )

            current_status = row["status"]

            # Repeated updates to the same status are idempotent.
            if current_status == new_status:
                return dict(row)

            if new_status not in allowed_transitions[current_status]:
                raise InvalidDocumentStatusTransitionError(
                    f"Cannot transition document from "
                    f"{current_status} to {new_status}."
                )

            connection.execute(
                """
                UPDATE documents
                SET status = ?
                WHERE document_id = ?
                """,
                (new_status, document_id),
            )

            updated_row = connection.execute(
                """
                SELECT *
                FROM documents
                WHERE document_id = ?
                """,
                (document_id,),
            ).fetchone()

            return dict(updated_row)

    except (
        DocumentNotFoundError,
        InvalidDocumentStatusTransitionError,
    ):
        raise

    except sqlite3.Error as exc:
        raise DocumentRepositoryError(
            "Failed to update document status."
        ) from exc
