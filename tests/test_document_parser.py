
from pathlib import Path
from types import SimpleNamespace

import pytest

from docling.datamodel.base_models import ConversionStatus
from docling_core.types.io import DocumentStream

from app.services import document_parser
from app.services.document_parser import (
    DocumentParsingError,
    ParsedDocument,
    parse_document,
)


@pytest.fixture
def parser_settings(monkeypatch, tmp_path):
    settings = SimpleNamespace(max_upload_size_mb=1)

    monkeypatch.setattr(
        document_parser,
        "get_settings",
        lambda: settings,
    )

    return tmp_path


def create_conversion_result(
    status=ConversionStatus.SUCCESS,
    errors=None,
    page_count=2,
):
    parsed_document = SimpleNamespace(
        export_to_markdown=lambda: "# Employee Policy\n\nTest content."
    )

    return SimpleNamespace(
        status=status,
        errors=errors or [],
        pages=[SimpleNamespace() for _ in range(page_count)],
        document=parsed_document,
    )


def test_parse_document_success(parser_settings, monkeypatch):
    file_path = parser_settings / "policy.md"
    file_path.write_text("# Policy", encoding="utf-8")

    result = create_conversion_result()

    fake_converter = SimpleNamespace(
        convert=lambda *args, **kwargs: result
    )

    monkeypatch.setattr(
        document_parser,
        "get_converter",
        lambda: fake_converter,
    )

    parsed = parse_document(file_path)

    assert isinstance(parsed, ParsedDocument)
    assert parsed.filename == "policy.md"
    assert parsed.file_type == "md"
    assert parsed.markdown_content.startswith("# Employee Policy")
    assert parsed.page_count == 2
    assert parsed.status == "success"
    assert parsed.errors == ()


def test_missing_document_is_rejected(parser_settings):
    file_path = parser_settings / "missing.pdf"

    with pytest.raises(DocumentParsingError):
        parse_document(file_path)


def test_unsupported_format_is_rejected(parser_settings):
    file_path = parser_settings / "sample.exe"
    file_path.write_bytes(b"sample")

    with pytest.raises(DocumentParsingError):
        parse_document(file_path)


def test_empty_document_is_rejected(parser_settings):
    file_path = parser_settings / "empty.txt"
    file_path.write_bytes(b"")

    with pytest.raises(DocumentParsingError):
        parse_document(file_path)


def test_oversized_document_is_rejected(parser_settings):
    file_path = parser_settings / "large.txt"
    file_path.write_bytes(b"A" * (1024 * 1024 + 1))

    with pytest.raises(DocumentParsingError):
        parse_document(file_path)


def test_txt_uses_document_stream(parser_settings, monkeypatch):
    file_path = parser_settings / "notes.txt"
    file_path.write_text("Employee information", encoding="utf-8")

    captured = {}

    def fake_convert(source, **kwargs):
        captured["source"] = source
        captured["kwargs"] = kwargs
        return create_conversion_result()

    fake_converter = SimpleNamespace(convert=fake_convert)

    monkeypatch.setattr(
        document_parser,
        "get_converter",
        lambda: fake_converter,
    )

    parsed = parse_document(file_path)

    assert isinstance(captured["source"], DocumentStream)
    assert captured["source"].name == "notes.md"
    assert parsed.file_type == "txt"


def test_conversion_failure_is_rejected(parser_settings, monkeypatch):
    file_path = parser_settings / "failed.pdf"
    file_path.write_bytes(b"%PDF-1.4 sample")

    result = create_conversion_result(
        status=ConversionStatus.FAILURE
    )

    fake_converter = SimpleNamespace(
        convert=lambda *args, **kwargs: result
    )

    monkeypatch.setattr(
        document_parser,
        "get_converter",
        lambda: fake_converter,
    )

    with pytest.raises(DocumentParsingError):
        parse_document(file_path)


def test_partial_conversion_preserves_errors(
    parser_settings,
    monkeypatch,
):
    file_path = parser_settings / "partial.pdf"
    file_path.write_bytes(b"%PDF-1.4 sample")

    error = SimpleNamespace(
        error_message="One page could not be processed."
    )

    result = create_conversion_result(
        status=ConversionStatus.PARTIAL_SUCCESS,
        errors=[error],
        page_count=1,
    )

    fake_converter = SimpleNamespace(
        convert=lambda *args, **kwargs: result
    )

    monkeypatch.setattr(
        document_parser,
        "get_converter",
        lambda: fake_converter,
    )

    parsed = parse_document(file_path)

    assert parsed.status == "partial_success"
    assert parsed.errors == (
        "One page could not be processed.",
    )
    assert parsed.page_count == 1


def test_empty_markdown_is_rejected(parser_settings, monkeypatch):
    file_path = parser_settings / "empty_content.md"
    file_path.write_text("# Empty", encoding="utf-8")

    parsed_document = SimpleNamespace(
        export_to_markdown=lambda: ""
    )

    result = SimpleNamespace(
        status=ConversionStatus.SUCCESS,
        errors=[],
        pages=[],
        document=parsed_document,
    )

    fake_converter = SimpleNamespace(
        convert=lambda *args, **kwargs: result
    )

    monkeypatch.setattr(
        document_parser,
        "get_converter",
        lambda: fake_converter,
    )

    with pytest.raises(DocumentParsingError):
        parse_document(file_path)
