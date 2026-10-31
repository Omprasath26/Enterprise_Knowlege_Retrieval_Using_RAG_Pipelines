
import logging

from fastapi import APIRouter, File, HTTPException, UploadFile, status

from app.core.config import get_settings
from app.schemas.document import (
    DocumentStatusResponse,
    DocumentUploadResponse,
)
from app.services.document_repository import (
    get_document_by_id,
)
from app.services.document_storage import (
    DocumentStorageError,
    DuplicateDocumentError,
    store_document,
)
from app.services.document_validator import (
    DocumentTooLargeError,
    DocumentValidationError,
    UnsupportedDocumentTypeError,
)
from app.workers.ingestion_tasks import process_document


logger = logging.getLogger(__name__)

router = APIRouter()


def _queue_document_ingestion(document_id: str) -> str | None:
    """Submit a document ingestion task to Celery."""

    try:
        task = process_document.delay(document_id)
        return task.id

    except Exception:
        logger.exception(
            "Unable to queue document ingestion: %s",
            document_id,
        )
        return None


def _get_status_message(document_status: str) -> str:
    """Return a readable message for the current document status."""

    messages = {
        "UPLOADED": "Document uploaded. Ingestion is awaiting processing.",
        "PROCESSING": "Document ingestion is in progress.",
        "COMPLETED": "Document ingestion completed successfully.",
        "FAILED": "Document ingestion failed. A retry may be submitted.",
    }

    return messages.get(
        document_status,
        "Document status is unavailable.",
    )


@router.post(
    "/upload",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Documents"],
    summary="Upload a document",
)
async def upload_document(
    file: UploadFile = File(...),
) -> DocumentUploadResponse:
    """Validate, store, and queue an uploaded document."""

    settings = get_settings()
    max_size_bytes = settings.max_upload_size_mb * 1024 * 1024

    try:
        content = await file.read(max_size_bytes + 1)

        stored_document = store_document(
            filename=file.filename or "",
            content=content,
        )

        task_id = _queue_document_ingestion(
            stored_document.document_id
        )

        if task_id is None:
            message = (
                "Document uploaded successfully, but ingestion "
                "could not be queued. Submit a processing retry."
            )
        else:
            message = "Document uploaded and ingestion queued."

        return DocumentUploadResponse(
            document_id=stored_document.document_id,
            filename=stored_document.filename,
            file_type=stored_document.file_type,
            file_size=stored_document.file_size,
            checksum=stored_document.checksum,
            status="UPLOADED",
            task_id=task_id,
            message=message,
        )

    except UnsupportedDocumentTypeError as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=str(exc),
        ) from exc

    except DocumentTooLargeError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=str(exc),
        ) from exc

    except DuplicateDocumentError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    except DocumentValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    except DocumentStorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Document storage failed.",
        ) from exc

    finally:
        await file.close()


@router.get(
    "/{document_id}",
    response_model=DocumentStatusResponse,
    tags=["Documents"],
    summary="Get document processing status",
)
def get_document_status(document_id: str) -> DocumentStatusResponse:
    """Retrieve the current document status from SQLite."""

    document = get_document_by_id(document_id)

    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )

    return DocumentStatusResponse(
        document_id=document["document_id"],
        filename=document["filename"],
        file_type=document["file_type"],
        file_size=document["file_size"],
        status=document["status"],
        uploaded_at=document["uploaded_at"],
        message=_get_status_message(document["status"]),
    )


@router.post(
    "/{document_id}/process",
    tags=["Documents"],
    summary="Submit or retry document ingestion",
)
def retry_document_ingestion(document_id: str) -> dict:
    """Submit an eligible document for ingestion."""

    document = get_document_by_id(document_id)

    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )

    current_status = document["status"]

    if current_status not in {"UPLOADED", "FAILED"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Document cannot be submitted for processing "
                f"while its status is {current_status}."
            ),
        )

    task_id = _queue_document_ingestion(document_id)

    if task_id is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Document remains registered, but the ingestion "
                "task could not be queued. Please retry later."
            ),
        )

    return {
        "document_id": document_id,
        "task_id": task_id,
        "status": current_status,
        "message": "Document ingestion task queued successfully.",
    }
