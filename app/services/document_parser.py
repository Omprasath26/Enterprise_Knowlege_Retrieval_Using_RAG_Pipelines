
import logging

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from docling.datamodel.base_models import ConversionStatus
from docling.document_converter import DocumentConverter
from docling_core.types.io import DocumentStream

from app.core.config import get_settings


logger = logging.getLogger(__name__)

SUPPORTED_FORMATS = {
    ".pdf",
    ".docx",
    ".xlsx",
    ".xls",
    ".html",
    ".csv",
    ".txt",
    ".md",
}

MAX_NUM_PAGES = 100


class DocumentParsingError(Exception):
    """Raised when a document cannot be parsed successfully."""


@dataclass(frozen=True)
class ParsedDocument:
    """Structured output returned after document parsing."""

    filename: str
    file_type: str
    markdown_content: str
    page_count: int
    status: str
    errors: tuple[str, ...]
    document: Any


_converter: DocumentConverter | None = None


def get_converter() -> DocumentConverter:
    """Initialize the Docling converter only when required."""

    global _converter

    if _converter is None:
        _converter = DocumentConverter()

    return _converter


def reset_converter() -> None:
    """Reset the cached converter, primarily for testing."""

    global _converter
    _converter = None


def _validate_source(file_path: Path) -> None:
    """Validate the source document before parsing."""

    if not file_path.exists():
        raise DocumentParsingError("The source document does not exist.")

    if not file_path.is_file():
        raise DocumentParsingError("The source path is not a file.")

    if file_path.suffix.lower() not in SUPPORTED_FORMATS:
        raise DocumentParsingError(
            f"Unsupported document format: {file_path.suffix}"
        )

    if file_path.stat().st_size == 0:
        raise DocumentParsingError("The source document is empty.")

    settings = get_settings()
    max_size_bytes = settings.max_upload_size_mb * 1024 * 1024

    if file_path.stat().st_size > max_size_bytes:
        raise DocumentParsingError(
            "The source document exceeds the configured size limit."
        )


def _convert_document(file_path: Path):
    """Convert a document using the appropriate Docling input."""

    converter = get_converter()

    if file_path.suffix.lower() == ".txt":
        try:
            text_content = file_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise DocumentParsingError(
                "Unable to read the TXT document as UTF-8."
            ) from exc

        if not text_content.strip():
            raise DocumentParsingError(
                "The TXT document contains no readable text."
            )

        source = DocumentStream(
            name=f"{file_path.stem}.md",
            stream=__import__("io").BytesIO(
                text_content.encode("utf-8")
            ),
        )
    else:
        source = file_path

    try:
        return converter.convert(
            source,
            raises_on_error=False,
            max_num_pages=MAX_NUM_PAGES,
            max_file_size=get_settings().max_upload_size_mb * 1024 * 1024,
        )

    except Exception as exc:
        logger.exception("Docling conversion failed for %s", file_path.name)

        raise DocumentParsingError(
            "Document conversion failed."
        ) from exc


def parse_document(file_path: str | Path) -> ParsedDocument:
    """Parse a stored document and return structured content."""

    source_path = Path(file_path)

    _validate_source(source_path)

    conversion_result = _convert_document(source_path)

    status = conversion_result.status
    error_messages = tuple(
        error.error_message
        for error in conversion_result.errors
    )

    if status == ConversionStatus.FAILURE:
        raise DocumentParsingError(
            "; ".join(error_messages)
            if error_messages
            else "Docling could not parse the document."
        )

    try:
        markdown_content = (
            conversion_result.document.export_to_markdown()
        )
    except Exception as exc:
        raise DocumentParsingError(
            "Unable to export the parsed document to Markdown."
        ) from exc

    if not markdown_content.strip():
        raise DocumentParsingError(
            "The document did not contain extractable text."
        )

    return ParsedDocument(
        filename=source_path.name,
        file_type=source_path.suffix.lower().lstrip("."),
        markdown_content=markdown_content,
        page_count=len(conversion_result.pages),
        status=status.value,
        errors=error_messages,
        document=conversion_result.document,
    )
