
from types import SimpleNamespace

import pytest

from app.services.metadata_extractor import (
    ExtractedDocumentMetadata,
    HeadingMetadata,
    MetadataExtractionError,
    extract_metadata,
)


def create_parsed_document():
    """Create a mock Docling document for metadata testing."""

    title = SimpleNamespace(
        label=SimpleNamespace(value="title"),
        text="Employee Handbook",
        prov=[
            SimpleNamespace(page_no=1)
        ],
    )

    heading = SimpleNamespace(
        label=SimpleNamespace(value="section_header"),
        text="Introduction",
        prov=[
            SimpleNamespace(page_no=2)
        ],
    )

    second_heading = SimpleNamespace(
        label=SimpleNamespace(value="section_header"),
        text="Company Policies",
        prov=[
            SimpleNamespace(page_no=3)
        ],
    )

    paragraph = SimpleNamespace(
        label=SimpleNamespace(value="text"),
        text="This is regular document content.",
        prov=[
            SimpleNamespace(page_no=1)
        ],
    )

    docling_document = SimpleNamespace(
        texts=[
            title,
            heading,
            second_heading,
            paragraph,
        ],
        tables=[SimpleNamespace()],
        pictures=[SimpleNamespace(), SimpleNamespace()],
    )

    return SimpleNamespace(
        filename="employee_handbook.pdf",
        file_type="pdf",
        markdown_content=(
            "# Employee Handbook\n\n"
            "Introduction\n\n"
            "Company Policies"
        ),
        page_count=3,
        status="success",
        errors=(),
        document=docling_document,
    )


def test_extract_metadata_success():
    parsed = create_parsed_document()

    metadata = extract_metadata(
        parsed,
        document_id="test-document-123",
    )

    assert isinstance(metadata, ExtractedDocumentMetadata)
    assert metadata.document_id == "test-document-123"
    assert metadata.filename == "employee_handbook.pdf"
    assert metadata.file_type == "pdf"
    assert metadata.page_count == 3
    assert metadata.parsing_status == "success"


def test_extract_document_title():
    metadata = extract_metadata(create_parsed_document())

    assert metadata.title == "Employee Handbook"


def test_extract_headings_and_page_numbers():
    metadata = extract_metadata(create_parsed_document())

    assert metadata.headings == (
        HeadingMetadata("Introduction", 2),
        HeadingMetadata("Company Policies", 3),
    )


def test_extract_table_and_image_counts():
    metadata = extract_metadata(create_parsed_document())

    assert metadata.table_count == 1
    assert metadata.image_count == 2


def test_extract_word_and_character_counts():
    parsed = create_parsed_document()

    metadata = extract_metadata(parsed)

    assert metadata.word_count == len(
        parsed.markdown_content.split()
    )

    assert metadata.character_count == len(
        parsed.markdown_content
    )


def test_document_id_is_optional():
    metadata = extract_metadata(create_parsed_document())

    assert metadata.document_id is None


def test_parsing_errors_are_preserved():
    parsed = create_parsed_document()

    parsed.errors = ("One page could not be processed.",)
    parsed.status = "partial_success"

    metadata = extract_metadata(parsed)

    assert metadata.parsing_status == "partial_success"
    assert metadata.errors == (
        "One page could not be processed.",
    )


def test_missing_document_structure_is_rejected():
    parsed = create_parsed_document()
    parsed.document = None

    with pytest.raises(MetadataExtractionError):
        extract_metadata(parsed)


def test_invalid_markdown_content_is_rejected():
    parsed = create_parsed_document()
    parsed.markdown_content = None

    with pytest.raises(MetadataExtractionError):
        extract_metadata(parsed)
