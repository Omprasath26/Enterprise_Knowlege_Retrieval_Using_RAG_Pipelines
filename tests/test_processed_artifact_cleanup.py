
import pytest

from pathlib import Path
from types import SimpleNamespace

from app.services import processed_artifact_cleanup as cleanup


DOCUMENT_ID = "2f0b9698-d872-4c83-b26c-6e7bb0e839d7"


@pytest.fixture
def cleanup_environment(tmp_path, monkeypatch):
    """Prepare isolated storage and a registered document."""

    monkeypatch.setattr(
        cleanup,
        "get_settings",
        lambda: SimpleNamespace(storage_root=tmp_path),
    )

    monkeypatch.setattr(
        cleanup,
        "get_document_by_id",
        lambda document_id: {
            "document_id": document_id,
            "status": "FAILED",
        },
    )

    parsed_directory = (
        tmp_path / "processed" / "parsed" / DOCUMENT_ID
    )
    chunks_file = (
        tmp_path / "processed" / "chunks" / f"{DOCUMENT_ID}.jsonl"
    )

    parsed_directory.mkdir(parents=True)
    chunks_file.parent.mkdir(parents=True)

    (parsed_directory / "content.md").write_text(
        "Sample content",
        encoding="utf-8",
    )

    (parsed_directory / "metadata.json").write_text(
        "{}",
        encoding="utf-8",
    )

    chunks_file.write_text(
        '{"chunk_index": 0}\n',
        encoding="utf-8",
    )

    return tmp_path, parsed_directory, chunks_file


def test_cleanup_removes_processed_artifacts(cleanup_environment):
    _, parsed_directory, chunks_file = cleanup_environment

    result = cleanup.cleanup_incomplete_processed_artifacts(
        DOCUMENT_ID
    )

    assert result.parsed_artifacts_removed is True
    assert result.chunk_artifact_removed is True
    assert not parsed_directory.exists()
    assert not chunks_file.exists()


def test_repeated_cleanup_is_safe(cleanup_environment):
    _, parsed_directory, chunks_file = cleanup_environment

    cleanup.cleanup_incomplete_processed_artifacts(DOCUMENT_ID)

    result = cleanup.cleanup_incomplete_processed_artifacts(
        DOCUMENT_ID
    )

    assert result.parsed_artifacts_removed is False
    assert result.chunk_artifact_removed is False
    assert not parsed_directory.exists()
    assert not chunks_file.exists()


def test_invalid_document_uuid_rejected():
    with pytest.raises(cleanup.ProcessedArtifactCleanupError):
        cleanup.cleanup_incomplete_processed_artifacts(
            "invalid-uuid"
        )


def test_unregistered_document_rejected(monkeypatch):
    monkeypatch.setattr(
        cleanup,
        "get_document_by_id",
        lambda document_id: None,
    )

    with pytest.raises(cleanup.ProcessedArtifactCleanupError):
        cleanup.cleanup_incomplete_processed_artifacts(
            DOCUMENT_ID
        )


def test_completed_document_artifacts_are_protected(
    cleanup_environment,
    monkeypatch,
):
    _, parsed_directory, chunks_file = cleanup_environment

    monkeypatch.setattr(
        cleanup,
        "get_document_by_id",
        lambda document_id: {
            "document_id": document_id,
            "status": "COMPLETED",
        },
    )

    with pytest.raises(cleanup.ProcessedArtifactCleanupError):
        cleanup.cleanup_incomplete_processed_artifacts(
            DOCUMENT_ID
        )

    assert parsed_directory.exists()
    assert chunks_file.exists()


def test_uploaded_document_artifacts_are_protected(
    cleanup_environment,
    monkeypatch,
):
    _, parsed_directory, chunks_file = cleanup_environment

    monkeypatch.setattr(
        cleanup,
        "get_document_by_id",
        lambda document_id: {
            "document_id": document_id,
            "status": "UPLOADED",
        },
    )

    with pytest.raises(cleanup.ProcessedArtifactCleanupError):
        cleanup.cleanup_incomplete_processed_artifacts(
            DOCUMENT_ID
        )

    assert parsed_directory.exists()
    assert chunks_file.exists()
