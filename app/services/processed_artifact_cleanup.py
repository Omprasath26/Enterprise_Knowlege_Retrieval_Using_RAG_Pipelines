import shutil

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from app.core.config import get_settings
from app.services.document_repository import get_document_by_id


class ProcessedArtifactCleanupError(Exception):
    """Raised when incomplete processed artifacts cannot be cleaned safely."""


@dataclass(frozen=True)
class CleanupResult:
    """Summary of the processed artifacts cleanup operation."""

    document_id: str
    parsed_artifacts_removed: bool
    chunk_artifact_removed: bool


def _validate_document_id(document_id: str) -> str:
    """Validate and normalize a document UUID."""

    try:
        return str(UUID(document_id))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ProcessedArtifactCleanupError(
            "A valid document UUID is required."
        ) from exc


def _remove_path(path: Path) -> bool:
    """Remove one exact file, directory, or symbolic link."""

    if path.is_symlink() or path.is_file():
        path.unlink()
        return True

    if path.is_dir():
        shutil.rmtree(path)
        return True

    return False


def cleanup_incomplete_processed_artifacts(
    document_id: str,
) -> CleanupResult:
    """
    Remove published processed artifacts for a document being retried.

    Only documents currently marked FAILED or PROCESSING can be cleaned.
    COMPLETED documents are never modified.
    """

    normalized_id = _validate_document_id(document_id)

    try:
        document = get_document_by_id(normalized_id)

        if document is None:
            raise ProcessedArtifactCleanupError(
                "Cannot clean artifacts for an unregistered document."
            )

        current_status = document["status"]

        if current_status not in {"FAILED", "PROCESSING"}:
            raise ProcessedArtifactCleanupError(
                f"Cannot clean artifacts when document status is "
                f"{current_status}."
            )

        storage_root = Path(get_settings().storage_root)

        processed_root = storage_root / "processed"

        parsed_directory = (
            processed_root / "parsed" / normalized_id
        )

        chunks_file = (
            processed_root / "chunks" / f"{normalized_id}.jsonl"
        )

        parsed_removed = _remove_path(parsed_directory)
        chunks_removed = _remove_path(chunks_file)

        return CleanupResult(
            document_id=normalized_id,
            parsed_artifacts_removed=parsed_removed,
            chunk_artifact_removed=chunks_removed,
        )

    except ProcessedArtifactCleanupError:
        raise

    except OSError as exc:
        raise ProcessedArtifactCleanupError(
            "Failed to clean incomplete processed artifacts."
        ) from exc