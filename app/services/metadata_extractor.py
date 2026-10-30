
from dataclasses import dataclass

from app.services.document_parser import ParsedDocument


class MetadataExtractionError(Exception):
    """Raised when document metadata extraction fails."""


@dataclass(frozen=True)
class HeadingMetadata:
    """Represents a document heading and its page reference."""

    text: str
    page_number: int | None


@dataclass(frozen=True)
class ExtractedDocumentMetadata:
    """Structured metadata extracted from a parsed document."""

    document_id: str | None
    filename: str
    file_type: str
    page_count: int
    title: str | None
    headings: tuple[HeadingMetadata, ...]
    table_count: int
    image_count: int
    word_count: int
    character_count: int
    parsing_status: str
    errors: tuple[str, ...]


def _get_label_value(item) -> str:
    """Return a normalized Docling item label."""

    label = getattr(item, "label", None)

    if label is None:
        return ""

    return getattr(label, "value", str(label))


def _get_page_number(item) -> int | None:
    """Extract the first available page number from item provenance."""

    provenance = getattr(item, "prov", None) or []

    if not provenance:
        return None

    return getattr(provenance[0], "page_no", None)


def extract_metadata(
    parsed_document: ParsedDocument,
    document_id: str | None = None,
) -> ExtractedDocumentMetadata:
    """Extract document-level metadata from a Docling parser result."""

    try:
        document = parsed_document.document
        markdown_content = parsed_document.markdown_content

        if document is None:
            raise MetadataExtractionError(
                "Parsed document structure is missing."
            )

        if not isinstance(markdown_content, str):
            raise MetadataExtractionError(
                "Parsed Markdown content must be a string."
            )

        title = None
        headings = []

        for item in document.texts:
            label = _get_label_value(item)
            item_text = getattr(item, "text", None)

            if not isinstance(item_text, str) or not item_text.strip():
                continue

            if label == "title" and title is None:
                title = item_text.strip()

            elif label == "section_header":
                headings.append(
                    HeadingMetadata(
                        text=item_text.strip(),
                        page_number=_get_page_number(item),
                    )
                )

        word_count = len(markdown_content.split())
        character_count = len(markdown_content)

        return ExtractedDocumentMetadata(
            document_id=document_id,
            filename=parsed_document.filename,
            file_type=parsed_document.file_type,
            page_count=parsed_document.page_count,
            title=title,
            headings=tuple(headings),
            table_count=len(document.tables),
            image_count=len(document.pictures),
            word_count=word_count,
            character_count=character_count,
            parsing_status=parsed_document.status,
            errors=parsed_document.errors,
        )

    except MetadataExtractionError:
        raise

    except (AttributeError, TypeError, ValueError) as exc:
        raise MetadataExtractionError(
            "Failed to extract document metadata."
        ) from exc
