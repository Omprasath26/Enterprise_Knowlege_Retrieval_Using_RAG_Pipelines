
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.workers import ingestion_tasks


class FakeLock:
    """Mock Redis distributed lock."""

    def __init__(self, acquired=True):
        self.acquired = acquired
        self.released = False

    def acquire(self, blocking=False):
        return self.acquired

    def release(self):
        self.released = True


class FakeRedis:
    """Mock Redis client."""

    def __init__(self, lock):
        self.test_lock = lock
        self.closed = False

    def lock(self, name, timeout, blocking_timeout):
        return self.test_lock

    def close(self):
        self.closed = True



@pytest.fixture
def task_environment(tmp_path, monkeypatch):
    """Set up isolated dependencies for ingestion task tests."""

    document_id = str(uuid4())

    # Create a real temporary source document for the worker.
    source_directory = tmp_path / "uploads" / "originals"
    source_directory.mkdir(parents=True)

    source_file = source_directory / "test.txt"
    source_file.write_text(
        "Enterprise knowledge retrieval test document.",
        encoding="utf-8",
    )

    document = {
        "document_id": document_id,
        "filename": "test_document.txt",
        "file_type": "txt",
        "file_size": source_file.stat().st_size,
        "checksum": "a" * 64,
        "storage_path": str(source_file),
        "status": "UPLOADED",
    }

    lock = FakeLock()
    redis_client = FakeRedis(lock)

    parsed_document = SimpleNamespace(page_count=1)
    metadata = SimpleNamespace(document_id=document_id)
    chunks = [SimpleNamespace(chunk_id=str(uuid4()))]

    status_updates = []

    def fake_update_status(doc_id, new_status):
        assert doc_id == document_id

        document["status"] = new_status
        status_updates.append(new_status)

        return document.copy()

    monkeypatch.setattr(
        ingestion_tasks,
        "get_settings",
        lambda: SimpleNamespace(
            celery_broker_url="redis://localhost:6379/0"
        ),
    )

    monkeypatch.setattr(
        ingestion_tasks.redis.Redis,
        "from_url",
        lambda *args, **kwargs: redis_client,
    )

    monkeypatch.setattr(
        ingestion_tasks,
        "get_document_by_id",
        lambda doc_id: document.copy(),
    )

    monkeypatch.setattr(
        ingestion_tasks,
        "update_document_status",
        fake_update_status,
    )

    monkeypatch.setattr(
        ingestion_tasks,
        "cleanup_incomplete_processed_artifacts",
        lambda doc_id: None,
    )

    monkeypatch.setattr(
        ingestion_tasks,
        "parse_document",
        lambda path, original_filename=None: parsed_document
    )

    monkeypatch.setattr(
        ingestion_tasks,
        "extract_metadata",
        lambda parsed, document_id=None: metadata,
    )

    monkeypatch.setattr(
        ingestion_tasks,
        "chunk_document",
        lambda parsed, document_id=None: chunks,
    )

    monkeypatch.setattr(
        ingestion_tasks,
        "save_processed_document",
        lambda **kwargs: None,
    )

    monkeypatch.setattr(
        ingestion_tasks,
        "save_processed_chunks",
        lambda **kwargs: None,
    )

    return {
        "document_id": document_id,
        "document": document,
        "lock": lock,
        "redis_client": redis_client,
        "status_updates": status_updates,
        "parsed_document": parsed_document,
        "chunks": chunks,
        "source_file": source_file,
    }


def test_process_document_success(task_environment):
    """A successful ingestion should mark the document COMPLETED."""

    document_id = task_environment["document_id"]

    result = ingestion_tasks.process_document.run(document_id)

    assert result["document_id"] == document_id
    assert result["status"] == "COMPLETED"
    assert result["chunk_count"] == 1
    assert result["page_count"] == 1

    assert task_environment["status_updates"] == [
        "PROCESSING",
        "COMPLETED",
    ]

    assert task_environment["document"]["status"] == "COMPLETED"
    assert task_environment["lock"].released is True
    assert task_environment["redis_client"].closed is True


def test_completed_document_is_not_processed_again(
    task_environment,
):
    """An already completed document should be returned without processing."""

    document_id = task_environment["document_id"]

    task_environment["document"]["status"] = "COMPLETED"

    result = ingestion_tasks.process_document.run(document_id)

    assert result["status"] == "COMPLETED"
    assert task_environment["status_updates"] == []

    assert task_environment["lock"].released is True
    assert task_environment["redis_client"].closed is True


def test_duplicate_task_is_skipped_when_lock_is_unavailable(
    task_environment,
):
    """A task should be skipped if another worker owns the lock."""

    document_id = task_environment["document_id"]

    task_environment["lock"].acquired = False

    result = ingestion_tasks.process_document.run(document_id)

    assert result["document_id"] == document_id
    assert result["status"] == "SKIPPED"

    assert task_environment["status_updates"] == []
    assert task_environment["lock"].released is False
    assert task_environment["redis_client"].closed is True


def test_processing_failure_marks_document_failed(
    task_environment,
    monkeypatch,
):
    """A parsing failure should mark the document FAILED."""

    document_id = task_environment["document_id"]

    def fail_parsing(path, original_filename=None):
        raise RuntimeError("Simulated parser failure")

    monkeypatch.setattr(
        ingestion_tasks,
        "parse_document",
        fail_parsing,
    )

    with pytest.raises(
        RuntimeError,
        match="Simulated parser failure",
    ):
        ingestion_tasks.process_document.run(document_id)

    assert task_environment["status_updates"] == [
        "PROCESSING",
        "FAILED",
    ]

    assert task_environment["document"]["status"] == "FAILED"
    assert task_environment["lock"].released is True
    assert task_environment["redis_client"].closed is True
