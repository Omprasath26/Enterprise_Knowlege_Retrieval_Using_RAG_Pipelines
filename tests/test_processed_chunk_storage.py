
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services import processed_chunk_storage as storage
from app.services.chunking import DocumentChunk


DOCUMENT_ID = "2f0b9698-d872-4c83-b26c-6e7bb0e839d7"


def make_chunk(
    index=0,
    document_id=DOCUMENT_ID,
    chunk_id=None,
):
    return DocumentChunk(
        chunk_id=chunk_id or str(uuid4()),
        document_id=document_id,
        source_filename="sample.pdf",
        chunk_index=index,
        text=f"Original chunk text {index}",
        contextualized_text=f"Contextualized chunk text {index}",
        token_count=12,
        headings=("Introduction",),
        page_numbers=(1,),
    )


@pytest.fixture
def storage_root(tmp_path, monkeypatch):
    monkeypatch.setattr(
        storage,
        "get_settings",
        lambda: SimpleNamespace(storage_root=tmp_path),
    )
    return tmp_path


def test_save_chunks_creates_jsonl_file(storage_root):
    chunks = [make_chunk(0), make_chunk(1)]

    result = storage.save_processed_chunks(DOCUMENT_ID, chunks)

    assert result.exists()
    assert result.name == f"{DOCUMENT_ID}.jsonl"


def test_save_chunks_writes_one_json_record_per_line(storage_root):
    chunks = [make_chunk(0), make_chunk(1)]

    result = storage.save_processed_chunks(DOCUMENT_ID, chunks)

    lines = result.read_text(encoding="utf-8").splitlines()

    assert len(lines) == 2

    records = [json.loads(line) for line in lines]

    assert records[0]["chunk_index"] == 0
    assert records[1]["chunk_index"] == 1


def test_save_chunks_preserves_all_chunk_fields(storage_root):
    chunk = make_chunk()

    result = storage.save_processed_chunks(DOCUMENT_ID, [chunk])

    record = json.loads(result.read_text(encoding="utf-8"))

    assert record["chunk_id"] == chunk.chunk_id
    assert record["document_id"] == DOCUMENT_ID
    assert record["source_filename"] == "sample.pdf"
    assert record["text"] == chunk.text
    assert record["contextualized_text"] == chunk.contextualized_text
    assert record["token_count"] == 12
    assert record["headings"] == ["Introduction"]
    assert record["page_numbers"] == [1]


def test_save_chunks_rejects_invalid_document_uuid(storage_root):
    with pytest.raises(
        storage.ProcessedChunkStorageError,
        match="valid document UUID",
    ):
        storage.save_processed_chunks("invalid-id", [make_chunk()])


def test_save_chunks_rejects_empty_collection(storage_root):
    with pytest.raises(
        storage.ProcessedChunkStorageError,
        match="empty chunk collection",
    ):
        storage.save_processed_chunks(DOCUMENT_ID, [])


def test_save_chunks_rejects_mismatched_document_id(storage_root):
    other_id = "ea052a3d-1f69-4d66-ae7a-a9fb41bc4244"

    with pytest.raises(
        storage.ProcessedChunkStorageError,
        match="does not match",
    ):
        storage.save_processed_chunks(
            DOCUMENT_ID,
            [make_chunk(document_id=other_id)],
        )


def test_save_chunks_rejects_non_sequential_indexes(storage_root):
    with pytest.raises(
        storage.ProcessedChunkStorageError,
        match="sequential",
    ):
        storage.save_processed_chunks(
            DOCUMENT_ID,
            [make_chunk(index=1)],
        )


def test_save_chunks_rejects_duplicate_chunk_ids(storage_root):
    duplicate_id = str(uuid4())

    chunks = [
        make_chunk(0, chunk_id=duplicate_id),
        make_chunk(1, chunk_id=duplicate_id),
    ]

    with pytest.raises(
        storage.ProcessedChunkStorageError,
        match="Duplicate chunk IDs",
    ):
        storage.save_processed_chunks(DOCUMENT_ID, chunks)



def test_save_chunks_rejects_existing_file(storage_root):
    chunks = [make_chunk()]

    first_path = storage.save_processed_chunks(DOCUMENT_ID, chunks)

    with pytest.raises(
        storage.ProcessedChunkStorageError,
        match="already exist",
    ):
        storage.save_processed_chunks(DOCUMENT_ID, chunks)

    assert first_path.exists()



def test_save_chunks_cleans_temporary_file_on_failure(
    storage_root,
    monkeypatch,
):
    def fail_json(*args, **kwargs):
        raise TypeError("Simulated serialization failure")

    monkeypatch.setattr(storage.json, "dumps", fail_json)

    with pytest.raises(
        storage.ProcessedChunkStorageError,
        match="Failed to persist",
    ):
        storage.save_processed_chunks(
            DOCUMENT_ID,
            [make_chunk()],
        )

    chunks_directory = storage_root / "processed" / "chunks"

    assert list(chunks_directory.iterdir()) == []
