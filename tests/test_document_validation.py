
import io
import zipfile

import pytest

from app.services.document_validator import (
    DocumentTooLargeError,
    DocumentValidationError,
    UnsupportedDocumentTypeError,
    validate_document,
)


@pytest.fixture
def configure_test_settings(monkeypatch):
    """Use a 1 MB limit for isolated validation tests."""

    from types import SimpleNamespace

    settings = SimpleNamespace(max_upload_size_mb=1)

    monkeypatch.setattr(
        "app.services.document_validator.get_settings",
        lambda: settings,
    )


def create_ooxml_file(extension: str) -> bytes:
    """Create a minimal ZIP-based DOCX or XLSX validation fixture."""

    buffer = io.BytesIO()

    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types></Types>")

        if extension == "docx":
            archive.writestr("word/document.xml", "<document></document>")
        else:
            archive.writestr("xl/workbook.xml", "<workbook></workbook>")

    return buffer.getvalue()


@pytest.mark.parametrize(
    "filename,content",
    [
        ("sample.pdf", b"%PDF-1.4\nTest PDF"),
        ("sample.docx", create_ooxml_file("docx")),
        ("sample.xlsx", create_ooxml_file("xlsx")),
        ("sample.xls", bytes.fromhex("D0CF11E0A1B11AE1") + b"test"),
        ("sample.html", b"<html><body>Test</body></html>"),
        ("sample.csv", b"name,department\nJohn,IT"),
        ("sample.txt", b"Enterprise document validation"),
        ("sample.md", b"# Enterprise Knowledge Retrieval"),
    ],
)
def test_all_supported_formats_are_accepted(
    configure_test_settings,
    filename,
    content,
):
    result = validate_document(filename, content)

    assert result.filename == filename
    assert result.file_type == filename.rsplit(".", 1)[1]
    assert result.file_size == len(content)


@pytest.mark.parametrize(
    "filename",
    [
        "sample.exe",
        "sample.zip",
        "sample",
        "sample.json",
    ],
)
def test_unsupported_extensions_are_rejected(
    configure_test_settings,
    filename,
):
    with pytest.raises(UnsupportedDocumentTypeError):
        validate_document(filename, b"test content")


@pytest.mark.parametrize(
    "filename,content",
    [
        ("sample.pdf", b"Not a PDF"),
        ("sample.xls", b"Not an XLS file"),
        ("sample.docx", b"Not a DOCX archive"),
        ("sample.xlsx", b"Not an XLSX archive"),
    ],
)
def test_invalid_file_signatures_are_rejected(
    configure_test_settings,
    filename,
    content,
):
    with pytest.raises(DocumentValidationError):
        validate_document(filename, content)


@pytest.mark.parametrize(
    "filename",
    [
        "",
        "../unsafe.txt",
        "folder\\unsafe.txt",
        "invalid\nname.txt",
        " sample.txt",
    ],
)
def test_unsafe_filenames_are_rejected(
    configure_test_settings,
    filename,
):
    with pytest.raises(DocumentValidationError):
        validate_document(filename, b"test content")


@pytest.mark.parametrize(
    "filename,content",
    [
        ("empty.txt", b""),
        ("empty.csv", b""),
        ("empty.md", b""),
        ("empty.html", b""),
    ],
)
def test_empty_documents_are_rejected(
    configure_test_settings,
    filename,
    content,
):
    with pytest.raises(DocumentValidationError):
        validate_document(filename, content)


def test_binary_content_in_text_file_is_rejected(
    configure_test_settings,
):
    with pytest.raises(DocumentValidationError):
        validate_document("sample.txt", b"invalid\x00binary")


def test_invalid_utf8_text_is_rejected(
    configure_test_settings,
):
    with pytest.raises(DocumentValidationError):
        validate_document("sample.txt", b"\xff\xfe\xfa")


def test_invalid_html_content_is_rejected(
    configure_test_settings,
):
    with pytest.raises(DocumentValidationError):
        validate_document("sample.html", b"This is not HTML")


def test_oversized_document_is_rejected(
    configure_test_settings,
):
    content = b"A" * (1024 * 1024 + 1)

    with pytest.raises(DocumentTooLargeError):
        validate_document("large.txt", content)
