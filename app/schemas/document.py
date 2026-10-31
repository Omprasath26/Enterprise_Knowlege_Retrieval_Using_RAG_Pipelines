
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


DocumentStatus = Literal[
    "UPLOADED",
    "PROCESSING",
    "COMPLETED",
    "FAILED",
]


class DocumentUploadResponse(BaseModel):
    """Response returned after a document upload."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "document_id": "550e8400-e29b-41d4-a716-446655440000",
                "filename": "employee_policy.pdf",
                "file_type": "pdf",
                "file_size": 125000,
                "checksum": "a" * 64,
                "status": "UPLOADED",
                "task_id": "example-celery-task-id",
                "message": "Document uploaded and ingestion queued.",
            }
        }
    )

    document_id: str = Field(description="Unique document identifier")
    filename: str = Field(description="Original uploaded filename")
    file_type: str = Field(description="Document extension without the dot")
    file_size: int = Field(ge=1, description="Document size in bytes")
    checksum: str = Field(
        pattern=r"^[a-fA-F0-9]{64}$",
        description="SHA-256 checksum",
    )
    status: DocumentStatus = "UPLOADED"
    task_id: str | None = Field(
        default=None,
        description="Celery task ID, if ingestion was queued",
    )
    message: str = "Document uploaded successfully"


class DocumentMetadata(BaseModel):
    """Document metadata stored in SQLite."""

    document_id: str
    filename: str
    file_type: str
    file_size: int
    checksum: str
    status: DocumentStatus
    uploaded_at: datetime


class DocumentStatusResponse(BaseModel):
    """Response returned when checking document processing status."""

    document_id: str
    filename: str
    file_type: str
    file_size: int
    status: DocumentStatus
    uploaded_at: datetime
    message: str
