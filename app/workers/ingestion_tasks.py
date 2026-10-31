
import logging
from pathlib import Path

import redis

from app.core.config import get_settings
from app.services.document_repository import (
    DocumentNotFoundError,
    get_document_by_id,
    update_document_status,
)
from app.services.document_parser import parse_document
from app.services.metadata_extractor import extract_metadata
from app.services.chunking import chunk_document
from app.services.processed_document_storage import (
    save_processed_document,
)
from app.services.processed_chunk_storage import (
    save_processed_chunks,
)
from app.services.processed_artifact_cleanup import (
    cleanup_incomplete_processed_artifacts,
)
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

LOCK_TIMEOUT_SECONDS = 21600


@celery_app.task(
    bind=True,
    name="app.workers.ingestion_tasks.process_document",
)
def process_document(self, document_id: str) -> dict:
    """
    Process an uploaded document asynchronously.

    Workflow:
    1. Acquire a Redis distributed lock.
    2. Retrieve document metadata.
    3. Claim the document for processing.
    4. Remove incomplete previous artifacts.
    5. Parse the original document.
    6. Extract document metadata.
    7. Generate retrieval-ready chunks.
    8. Persist parsed content and chunks.
    9. Mark the document COMPLETED.
    """

    settings = get_settings()

    redis_client = None
    document_lock = None
    lock_acquired = False
    processing_claimed = False

    try:
        # --------------------------------------------------
        # 1. Connect to Redis and acquire document lock
        # --------------------------------------------------
        redis_client = redis.Redis.from_url(
            settings.celery_broker_url
        )

        document_lock = redis_client.lock(
            name=f"document_ingestion:{document_id}",
            timeout=LOCK_TIMEOUT_SECONDS,
            blocking_timeout=0,
        )

        lock_acquired = document_lock.acquire(blocking=False)

        if not lock_acquired:
            logger.info(
                "Skipping document %s because another worker "
                "currently owns its lock.",
                document_id,
            )

            return {
                "document_id": document_id,
                "status": "SKIPPED",
                "message": "Another worker is processing this document.",
            }

        # --------------------------------------------------
        # 2. Retrieve document metadata
        # --------------------------------------------------
        document = get_document_by_id(document_id)

        if document is None:
            raise DocumentNotFoundError(
                f"Document not found: {document_id}"
            )

        current_status = document["status"]

        # --------------------------------------------------
        # 3. Handle document status
        # --------------------------------------------------
        if current_status == "COMPLETED":
            logger.info(
                "Document %s is already completed.",
                document_id,
            )

            return {
                "document_id": document_id,
                "filename": document["filename"],
                "status": "COMPLETED",
                "message": "Document was already processed.",
            }

        if current_status in {"UPLOADED", "FAILED"}:
            update_document_status(
                document_id,
                "PROCESSING",
            )

            processing_claimed = True

        elif current_status == "PROCESSING":
            # Allow recovery of an interrupted processing attempt.
            processing_claimed = True

        else:
            raise ValueError(
                f"Document {document_id} has an unsupported "
                f"processing status: {current_status}"
            )

        # --------------------------------------------------
        # 4. Remove incomplete previous artifacts
        # --------------------------------------------------
        cleanup_incomplete_processed_artifacts(document_id)

        # --------------------------------------------------
        # 5. Resolve original uploaded file
        # --------------------------------------------------
        source_path = Path(document["storage_path"])

        if not source_path.exists():
            raise FileNotFoundError(
                f"Stored source document does not exist: {source_path}"
            )

        # --------------------------------------------------
        # 6. Parse document
        # Preserve the original uploaded filename.
        # --------------------------------------------------
        parsed_document = parse_document(
            source_path,
            original_filename=document["filename"],
        )

        # --------------------------------------------------
        # 7. Extract document metadata
        # --------------------------------------------------
        metadata = extract_metadata(
            parsed_document,
            document_id=document_id,
        )

        # --------------------------------------------------
        # 8. Generate document chunks
        # --------------------------------------------------
        chunks = chunk_document(
            parsed_document,
            document_id=document_id,
        )

        # --------------------------------------------------
        # 9. Save parsed content and metadata
        # --------------------------------------------------
        save_processed_document(
            document_id=document_id,
            parsed_document=parsed_document,
            metadata=metadata,
        )

        # --------------------------------------------------
        # 10. Save processed chunks
        # --------------------------------------------------
        save_processed_chunks(
            document_id=document_id,
            chunks=chunks,
        )

        # --------------------------------------------------
        # 11. Mark ingestion as completed
        # --------------------------------------------------
        update_document_status(
            document_id,
            "COMPLETED",
        )

        logger.info(
            "Document ingestion completed successfully: %s",
            document_id,
        )

        return {
            "document_id": document_id,
            "filename": document["filename"],
            "status": "COMPLETED",
            "page_count": parsed_document.page_count,
            "chunk_count": len(chunks),
            "message": "Document ingestion completed successfully.",
        }

    except Exception:
        logger.exception(
            "Document ingestion failed: %s",
            document_id,
        )

        # Mark the document FAILED only if this task claimed
        # or recovered a PROCESSING document.
        if processing_claimed:
            try:
                update_document_status(
                    document_id,
                    "FAILED",
                )
            except Exception:
                logger.exception(
                    "Could not mark document %s as FAILED.",
                    document_id,
                )

        raise

    finally:
        # --------------------------------------------------
        # 12. Release lock and close Redis connection
        # --------------------------------------------------
        if lock_acquired and document_lock is not None:
            try:
                document_lock.release()
            except Exception:
                logger.exception(
                    "Failed to release Redis lock for document %s.",
                    document_id,
                )

        if redis_client is not None:
            try:
                redis_client.close()
            except Exception:
                logger.exception(
                    "Failed to close Redis connection for document %s.",
                    document_id,
                )
