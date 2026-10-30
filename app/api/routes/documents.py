
from fastapi import APIRouter, File, HTTPException, UploadFile, status

from app.core.config import get_settings
from app.schemas.document import DocumentUploadResponse
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

router = APIRouter()


@router.post(
    "/upload",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Documents"],
    summary="Upload a document",
)
async def upload_document(file: UploadFile = File(...)) -> DocumentUploadResponse:
    """Validate and store an uploaded document."""

    settings = get_settings()
    max_size_bytes = settings.max_upload_size_mb * 1024 * 1024

    try:
        # Read at most one byte beyond the configured upload limit.
        content = await file.read(max_size_bytes + 1)

        stored_document = store_document(
            filename=file.filename or "",
            content=content,
        )

        return DocumentUploadResponse(
            document_id=stored_document.document_id,
            filename=stored_document.filename,
            file_type=stored_document.file_type,
            file_size=stored_document.file_size,
            checksum=stored_document.checksum,
            status="UPLOADED",
            message="Document uploaded successfully",
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
