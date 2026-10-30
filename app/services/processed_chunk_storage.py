
import json
import os
import tempfile

from dataclasses import asdict
from pathlib import Path
from uuid import UUID

from app.core.config import get_settings
from app.services.chunking import DocumentChunk


class ProcessedChunkStorageError(Exception):
    """Raised when processed chunks cannot be persisted."""


def _validate_document_id(document_id: str) -> str:
    """Validate and normalize a document UUID."""

    try:
        return str(UUID(document_id))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ProcessedChunkStorageError(
            "A valid document UUID is required."
        ) from exc


def _validate_chunks(
    document_id: str,
    chunks: list[DocumentChunk],
) -> None:
    """Validate chunk ownership, identity and sequence."""

    if not chunks:
        raise ProcessedChunkStorageError(
            "Cannot persist an empty chunk collection."
        )

    seen_chunk_ids = set()

    for expected_index, chunk in enumerate(chunks):
        if not isinstance(chunk, DocumentChunk):
            raise ProcessedChunkStorageError(
                "Every item must be a DocumentChunk."
            )

        if chunk.document_id != document_id:
            raise ProcessedChunkStorageError(
                "Chunk document ID does not match the requested document ID."
            )

        if chunk.chunk_index != expected_index:
            raise ProcessedChunkStorageError(
                "Chunk indexes must be sequential, starting at zero."
            )

        try:
            normalized_chunk_id = str(UUID(chunk.chunk_id))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ProcessedChunkStorageError(
                "Every chunk must have a valid UUID."
            ) from exc

        if normalized_chunk_id in seen_chunk_ids:
            raise ProcessedChunkStorageError(
                "Duplicate chunk IDs are not allowed."
            )

        seen_chunk_ids.add(normalized_chunk_id)

        if not isinstance(chunk.text, str) or not chunk.text.strip():
            raise ProcessedChunkStorageError(
                "Chunk original text cannot be empty."
            )

        if (
            not isinstance(chunk.contextualized_text, str)
            or not chunk.contextualized_text.strip()
        ):
            raise ProcessedChunkStorageError(
                "Chunk contextualized text cannot be empty."
            )

        if (
            not isinstance(chunk.token_count, int)
            or isinstance(chunk.token_count, bool)
            or chunk.token_count < 0
        ):
            raise ProcessedChunkStorageError(
                "Chunk token count must be a non-negative integer."
            )


def save_processed_chunks(
    document_id: str,
    chunks: list[DocumentChunk],
) -> Path:
    """
    Persist document chunks as JSON Lines.

    Each line represents one chunk. A temporary file is written first,
    then published atomically without overwriting an existing file.
    """

    normalized_id = _validate_document_id(document_id)
    _validate_chunks(normalized_id, chunks)

    settings = get_settings()

    chunks_directory = (
        Path(settings.storage_root)
        / "processed"
        / "chunks"
    )

    final_path = chunks_directory / f"{normalized_id}.jsonl"
    temporary_path = None

    try:
        chunks_directory.mkdir(parents=True, exist_ok=True)

        if final_path.exists():
            raise ProcessedChunkStorageError(
                "Processed chunks already exist for this document."
            )

        file_descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{normalized_id}_",
            suffix=".tmp",
            dir=str(chunks_directory),
        )

        temporary_path = Path(temporary_name)

        with os.fdopen(file_descriptor, "w", encoding="utf-8") as file:
            for chunk in chunks:
                record = asdict(chunk)

                json_line = json.dumps(
                    record,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )

                file.write(json_line + "\n")

            file.flush()
            os.fsync(file.fileno())

        # Atomic publication. Creating a hard link fails if the
        # destination already exists, preventing accidental overwrite.
        os.link(temporary_path, final_path)

        temporary_path.unlink()
        temporary_path = None

        return final_path

    except ProcessedChunkStorageError:
        raise

    except (OSError, TypeError, ValueError) as exc:
        raise ProcessedChunkStorageError(
            "Failed to persist processed document chunks."
        ) from exc

    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
