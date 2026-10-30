
import json
import os
import shutil
import tempfile

from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import UUID

from app.core.config import get_settings
from app.services.document_parser import ParsedDocument
from app.services.metadata_extractor import ExtractedDocumentMetadata


class ProcessedDocumentStorageError(Exception):
    """Raised when processed document data cannot be persisted."""


@dataclass(frozen=True)
class ProcessedDocumentPaths:
    """Paths to the persisted document artifacts."""

    document_id: str
    directory: Path
    content_path: Path
    metadata_path: Path


def _validate_document_id(document_id: str) -> str:
    """Validate and normalize a document UUID."""

    try:
        return str(UUID(document_id))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ProcessedDocumentStorageError(
            "A valid document UUID is required."
        ) from exc


def _write_json(path: Path, data: dict) -> None:
    """Write JSON data to a file."""

    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
        file.write("\n")
        file.flush()
        os.fsync(file.fileno())


def save_processed_document(
    document_id: str,
    parsed_document: ParsedDocument,
    metadata: ExtractedDocumentMetadata,
) -> ProcessedDocumentPaths:
    """
    Persist parsed Markdown and extracted metadata.

    Both artifacts are written to a temporary directory first.
    The completed directory is then renamed to its final location.
    """

    normalized_id = _validate_document_id(document_id)

    if not isinstance(parsed_document.markdown_content, str):
        raise ProcessedDocumentStorageError(
            "Parsed Markdown content must be a string."
        )

    if not parsed_document.markdown_content.strip():
        raise ProcessedDocumentStorageError(
            "Cannot persist an empty parsed document."
        )

    if metadata.document_id not in (None, normalized_id):
        raise ProcessedDocumentStorageError(
            "Metadata document ID does not match the requested document ID."
        )

    settings = get_settings()

    parsed_root = (
        Path(settings.storage_root)
        / "processed"
        / "parsed"
    )

    final_directory = parsed_root / normalized_id

    temporary_directory = None

    try:
        parsed_root.mkdir(parents=True, exist_ok=True)

        if final_directory.exists():
            raise ProcessedDocumentStorageError(
                "Processed artifacts already exist for this document."
            )

        temporary_directory = Path(
            tempfile.mkdtemp(
                prefix=f".{normalized_id}_",
                dir=str(parsed_root),
            )
        )

        content_path = temporary_directory / "content.md"
        metadata_path = temporary_directory / "metadata.json"

        with content_path.open("w", encoding="utf-8") as file:
            file.write(parsed_document.markdown_content)
            file.flush()
            os.fsync(file.fileno())

        metadata_data = asdict(metadata)
        metadata_data["document_id"] = normalized_id
        metadata_data["schema_version"] = 1

        _write_json(metadata_path, metadata_data)

        # Publish both files together by renaming the completed directory.
        temporary_directory.rename(final_directory)
        temporary_directory = None

        return ProcessedDocumentPaths(
            document_id=normalized_id,
            directory=final_directory,
            content_path=final_directory / "content.md",
            metadata_path=final_directory / "metadata.json",
        )

    except ProcessedDocumentStorageError:
        raise

    except (OSError, TypeError, ValueError) as exc:
        raise ProcessedDocumentStorageError(
            "Failed to persist processed document artifacts."
        ) from exc

    finally:
        if temporary_directory is not None:
            shutil.rmtree(temporary_directory, ignore_errors=True)
