
import re
import zipfile

from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePath

from app.core.config import get_settings


ALLOWED_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".xlsx",
    ".xls",
    ".html",
    ".csv",
    ".txt",
    ".md",
}

PDF_SIGNATURE = b"%PDF-"
XLS_SIGNATURE = bytes.fromhex("D0CF11E0A1B11AE1")


class DocumentValidationError(ValueError):
    """Raised when an uploaded document fails validation."""


class UnsupportedDocumentTypeError(DocumentValidationError):
    """Raised when the uploaded document has an unsupported extension."""


class DocumentTooLargeError(DocumentValidationError):
    """Raised when the uploaded document exceeds the size limit."""


@dataclass(frozen=True)
class ValidatedDocument:
    """Basic information about a successfully validated document."""

    filename: str
    file_type: str
    file_size: int


def validate_filename(filename: str) -> None:
    """Reject empty filenames, path traversal and unsafe path characters."""

    if not filename or not filename.strip():
        raise DocumentValidationError("Filename cannot be empty.")

    if filename != filename.strip():
        raise DocumentValidationError(
            "Filename cannot contain surrounding spaces."
        )

    if "\x00" in filename or any(ord(char) < 32 for char in filename):
        raise DocumentValidationError(
            "Filename contains invalid characters."
        )

    if "/" in filename or "\\" in filename:
        raise DocumentValidationError(
            "Path separators are not allowed in filenames."
        )

    if filename in {".", ".."} or PurePath(filename).name != filename:
        raise DocumentValidationError("Invalid filename.")

    extension = PurePath(filename).suffix.lower()

    if extension not in ALLOWED_EXTENSIONS:
        raise UnsupportedDocumentTypeError(
            f"Unsupported file extension: {extension or 'none'}."
        )


def _validate_ooxml(content: bytes, extension: str) -> None:
    """Check DOCX and XLSX files for expected ZIP entries."""

    try:
        with zipfile.ZipFile(BytesIO(content)) as archive:
            entries = set(archive.namelist())

            if extension == ".docx":
                required_entries = {
                    "[Content_Types].xml",
                    "word/document.xml",
                }
            else:
                required_entries = {
                    "[Content_Types].xml",
                    "xl/workbook.xml",
                }

            if not required_entries.issubset(entries):
                raise DocumentValidationError(
                    f"The uploaded content is not a valid {extension} document."
                )

    except zipfile.BadZipFile as exc:
        raise DocumentValidationError(
            f"The uploaded content is not a valid {extension} document."
        ) from exc


def _validate_text_file(content: bytes, extension: str) -> None:
    """Check that text-based documents contain readable text."""

    if b"\x00" in content:
        raise DocumentValidationError(
            "The uploaded file appears to contain binary data."
        )

    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise DocumentValidationError(
            "Text documents must use UTF-8 encoding."
        ) from exc

    if not text.strip():
        raise DocumentValidationError(
            "The uploaded document is empty."
        )

    if extension == ".html":
        if not re.search(
            r"<\s*(html|!doctype|head|body)\b",
            text,
            re.IGNORECASE,
        ):
            raise DocumentValidationError(
                "The uploaded content does not appear to be an HTML document."
            )


def validate_document(
    filename: str,
    content: bytes,
) -> ValidatedDocument:
    """Validate filename, file size and document content."""

    validate_filename(filename)

    if not isinstance(content, bytes):
        raise DocumentValidationError(
            "Document content must be bytes."
        )

    if not content:
        raise DocumentValidationError(
            "The uploaded document is empty."
        )

    settings = get_settings()
    max_size_bytes = settings.max_upload_size_mb * 1024 * 1024

    if len(content) > max_size_bytes:
        raise DocumentTooLargeError(
            f"File exceeds the maximum upload size of "
            f"{settings.max_upload_size_mb} MB."
        )

    extension = PurePath(filename).suffix.lower()

    if extension == ".pdf":
        if not content.startswith(PDF_SIGNATURE):
            raise DocumentValidationError(
                "The uploaded content is not a valid PDF."
            )

    elif extension == ".xls":
        if not content.startswith(XLS_SIGNATURE):
            raise DocumentValidationError(
                "The uploaded content is not a valid XLS file."
            )

    elif extension in {".docx", ".xlsx"}:
        _validate_ooxml(content, extension)

    else:
        _validate_text_file(content, extension)

    return ValidatedDocument(
        filename=filename,
        file_type=extension.lstrip("."),
        file_size=len(content),
    )
