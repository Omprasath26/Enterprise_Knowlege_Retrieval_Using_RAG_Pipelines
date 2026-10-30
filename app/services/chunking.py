
import logging
from dataclasses import dataclass
from uuid import uuid4

from docling.chunking import HybridChunker

from app.services.document_parser import ParsedDocument


logger = logging.getLogger(__name__)


class DocumentChunkingError(Exception):
    """Raised when a parsed document cannot be chunked."""


@dataclass(frozen=True)
class DocumentChunk:
    """A document chunk with retrieval and citation metadata."""

    chunk_id: str
    document_id: str | None
    source_filename: str
    chunk_index: int
    text: str
    contextualized_text: str
    token_count: int
    headings: tuple[str, ...]
    page_numbers: tuple[int, ...]


_chunker: HybridChunker | None = None


def get_chunker() -> HybridChunker:
    """Create the HybridChunker lazily and reuse it."""

    global _chunker

    if _chunker is None:
        _chunker = HybridChunker()

    return _chunker


def reset_chunker() -> None:
    """Reset the cached chunker. Primarily useful for testing."""

    global _chunker
    _chunker = None


def _extract_headings(chunk) -> tuple[str, ...]:
    """Extract heading context from a Docling chunk."""

    headings = getattr(chunk.meta, "headings", None) or []

    return tuple(
        heading.strip()
        for heading in headings
        if isinstance(heading, str) and heading.strip()
    )


def _extract_page_numbers(chunk) -> tuple[int, ...]:
    """Extract unique, ordered page numbers from chunk provenance."""

    page_numbers = set()

    doc_items = getattr(chunk.meta, "doc_items", None) or []

    for item in doc_items:
        provenance = getattr(item, "prov", None) or []

        for reference in provenance:
            page_number = getattr(reference, "page_no", None)

            if (
                isinstance(page_number, int)
                and not isinstance(page_number, bool)
                and page_number > 0
            ):
                page_numbers.add(page_number)

    return tuple(sorted(page_numbers))


def chunk_document(
    parsed_document: ParsedDocument,
    document_id: str | None = None,
    chunker: HybridChunker | None = None,
) -> list[DocumentChunk]:
    """
    Split a parsed Docling document into retrieval-ready chunks.

    The original Docling chunk text and its contextualized representation
    are both retained. No embeddings or vector database operations occur here.
    """

    if parsed_document.document is None:
        raise DocumentChunkingError(
            "The parsed document does not contain a Docling document."
        )

    active_chunker = chunker or get_chunker()

    try:
        docling_chunks = active_chunker.chunk(parsed_document.document)

        results: list[DocumentChunk] = []

        for index, source_chunk in enumerate(docling_chunks):
            original_text = source_chunk.text

            if not isinstance(original_text, str) or not original_text.strip():
                continue

            contextualized_text = active_chunker.contextualize(source_chunk)

            if (
                not isinstance(contextualized_text, str)
                or not contextualized_text.strip()
            ):
                raise DocumentChunkingError(
                    f"Chunk {index} produced empty contextualized text."
                )

            token_count = active_chunker.tokenizer.count_tokens(
                contextualized_text
            )

            results.append(
                DocumentChunk(
                    chunk_id=str(uuid4()),
                    document_id=document_id,
                    source_filename=parsed_document.filename,
                    chunk_index=len(results),
                    text=original_text,
                    contextualized_text=contextualized_text,
                    token_count=token_count,
                    headings=_extract_headings(source_chunk),
                    page_numbers=_extract_page_numbers(source_chunk),
                )
            )

        if not results:
            raise DocumentChunkingError(
                "The document did not produce any usable chunks."
            )

        return results

    except DocumentChunkingError:
        raise

    except Exception as exc:
        logger.exception(
            "Chunking failed for document: %s",
            parsed_document.filename,
        )
        raise DocumentChunkingError(
            f"Failed to chunk document: {parsed_document.filename}"
        ) from exc
