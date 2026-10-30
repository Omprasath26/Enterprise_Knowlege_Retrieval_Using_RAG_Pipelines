
import json
from types import SimpleNamespace

import pytest

from app.services import processed_document_storage as storage
from app.services.document_parser import ParsedDocument
from app.services.metadata_extractor import (
    ExtractedDocumentMetadata,
    HeadingMetadata,
)


DOCUMENT_ID = "2f0b9698-d872-4c83-b26c-6e7bb0e839d7"


def make_parsed_document():
    return ParsedDocument(
        filename="sample.pdf",
        file_type="pdf",
        markdown_content="# Sample Document\n\nThis is test content.",
        page_count=1,
        status="success",
        errors=(),
        document=object(),
    )


def make_metadata(document_id=None):
    return ExtractedDocumentMetadata(
        document_id=document_id,
        filename="sample.pdf",
        file_type="pdf",
        page_count=1,
        title="Sample Document",
        headings=(
            HeadingMetadata(
                text="Introduction",
                page_number=1,
            ),
        ),
        table_count=0,
        image_count=0,
        word_count=7,
        character_count=42,
        parsing_status="success",
        errors=(),
    )


@pytest.fixture
def storage_root(tmp_path, monkeypatch):
    monkeypatch.setattr(
        storage,
        "get_settings",
        lambda: SimpleNamespace(storage_root=tmp_path),
    )
    return tmp_path


def test_save_processed_document_creates_expected_files(storage_root):
    result = storage.save_processed_document(
        DOCUMENT_ID,
        make_parsed_document(),
        make_metadata(),
    )

    assert result.directory.exists()
    assert result.content_path.exists()
    assert result.metadata_path.exists()

    assert result.content_path.name == "content.md"
    assert result.metadata_path.name == "metadata.json"


def test_save_processed_document_preserves_markdown(storage_root):
    parsed = make_parsed_document()

    result = storage.save_processed_document(
        DOCUMENT_ID,
        parsed,
        make_metadata(),
    )

    assert result.content_path.read_text(encoding="utf-8") == (
        parsed.markdown_content
    )


def test_save_processed_document_serializes_metadata(storage_root):
    result = storage.save_processed_document(
        DOCUMENT_ID,
        make_parsed_document(),
        make_metadata(),
    )

    metadata = json.loads(
        result.metadata_path.read_text(encoding="utf-8")
    )

    assert metadata["document_id"] == DOCUMENT_ID
    assert metadata["filename"] == "sample.pdf"
    assert metadata["title"] == "Sample Document"
    assert metadata["schema_version"] == 1
    assert metadata["headings"][0]["text"] == "Introduction"
    assert metadata["headings"][0]["page_number"] == 1


def test_save_processed_document_rejects_invalid_uuid(storage_root):
    with pytest.raises(
        storage.ProcessedDocumentStorageError,
        match="valid document UUID",
    ):
        storage.save_processed_document(
            "invalid-id",
            make_parsed_document(),
            make_metadata(),
        )


def test_save_processed_document_rejects_empty_markdown(storage_root):
    parsed = make_parsed_document()
    parsed = ParsedDocument(
        filename=parsed.filename,
        file_type=parsed.file_type,
        markdown_content="   ",
        page_count=parsed.page_count,
        status=parsed.status,
        errors=parsed.errors,
        document=parsed.document,
    )

    with pytest.raises(
        storage.ProcessedDocumentStorageError,
        match="empty parsed document",
    ):
        storage.save_processed_document(
            DOCUMENT_ID,
            parsed,
            make_metadata(),
        )


def test_save_processed_document_rejects_mismatched_metadata_id(
    storage_root,
):
    other_id = "ea052a3d-1f69-4d66-ae7a-a9fb41bc4244"

    with pytest.raises(
        storage.ProcessedDocumentStorageError,
        match="does not match",
    ):
        storage.save_processed_document(
            DOCUMENT_ID,
            make_parsed_document(),
            make_metadata(document_id=other_id),
        )


def test_save_processed_document_rejects_existing_directory(storage_root):
    existing_directory = (
        storage_root / "processed" / "parsed" / DOCUMENT_ID
    )
    existing_directory.mkdir(parents=True)

    with pytest.raises(
        storage.ProcessedDocumentStorageError,
        match="already exist",
    ):
        storage.save_processed_document(
            DOCUMENT_ID,
            make_parsed_document(),
            make_metadata(),
        )


def test_save_processed_document_cleans_temporary_directory_on_failure(
    storage_root,
    monkeypatch,
):
    def fail_json_write(path, data):
        raise OSError("Simulated disk failure")

    monkeypatch.setattr(storage, "_write_json", fail_json_write)

    with pytest.raises(
        storage.ProcessedDocumentStorageError,
        match="Failed to persist",
    ):
        storage.save_processed_document(
            DOCUMENT_ID,
            make_parsed_document(),
            make_metadata(),
        )

    parsed_root = storage_root / "processed" / "parsed"

    assert list(parsed_root.iterdir()) == []
