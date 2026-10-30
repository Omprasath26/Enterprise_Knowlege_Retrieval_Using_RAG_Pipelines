
from types import SimpleNamespace

import pytest

from app.services.chunking import (
    DocumentChunkingError,
    chunk_document,
)
from app.services.document_parser import ParsedDocument


class FakeTokenizer:
    def count_tokens(self, text: str) -> int:
        return len(text.split())


class FakeChunker:
    def __init__(self, chunks):
        self.chunks = chunks
        self.tokenizer = FakeTokenizer()

    def chunk(self, document):
        return iter(self.chunks)

    def contextualize(self, chunk):
        return f"{' / '.join(chunk.meta.headings)}\n{chunk.text}"


def make_source_chunk(
    text="Example document text",
    headings=None,
    page_numbers=None,
):
    headings = headings or []
    page_numbers = page_numbers or []

    doc_items = [
        SimpleNamespace(
            prov=[SimpleNamespace(page_no=page_number)]
        )
        for page_number in page_numbers
    ]

    metadata = SimpleNamespace(
        headings=headings,
        doc_items=doc_items,
    )

    return SimpleNamespace(text=text, meta=metadata)


def make_parsed_document(document=None):
    return ParsedDocument(
        filename="sample.pdf",
        file_type="pdf",
        markdown_content="Example document text",
        page_count=1,
        status="success",
        errors=(),
        document=document if document is not None else object(),
    )


def test_chunk_document_returns_chunk_metadata():
    source_chunk = make_source_chunk(
        text="Machine learning improves prediction accuracy",
        headings=["Technical Overview"],
        page_numbers=[2, 1, 2],
    )

    result = chunk_document(
        parsed_document=make_parsed_document(),
        document_id="document-123",
        chunker=FakeChunker([source_chunk]),
    )

    assert len(result) == 1

    chunk = result[0]

    assert chunk.document_id == "document-123"
    assert chunk.source_filename == "sample.pdf"
    assert chunk.chunk_index == 0
    assert chunk.text == "Machine learning improves prediction accuracy"
    assert chunk.contextualized_text.startswith("Technical Overview")
    assert chunk.token_count == len(chunk.contextualized_text.split())
    assert chunk.headings == ("Technical Overview",)
    assert chunk.page_numbers == (1, 2)


def test_chunk_document_generates_unique_chunk_ids():
    chunks = [
        make_source_chunk("First chunk"),
        make_source_chunk("Second chunk"),
    ]

    result = chunk_document(
        make_parsed_document(),
        chunker=FakeChunker(chunks),
    )

    assert len(result) == 2
    assert result[0].chunk_id != result[1].chunk_id


def test_chunk_document_assigns_sequential_indexes():
    chunks = [
        make_source_chunk("First chunk"),
        make_source_chunk("Second chunk"),
        make_source_chunk("Third chunk"),
    ]

    result = chunk_document(
        make_parsed_document(),
        chunker=FakeChunker(chunks),
    )

    assert [chunk.chunk_index for chunk in result] == [0, 1, 2]


def test_chunk_document_supports_missing_document_id():
    result = chunk_document(
        make_parsed_document(),
        chunker=FakeChunker([make_source_chunk()]),
    )

    assert result[0].document_id is None


def test_chunk_document_skips_empty_source_chunks():
    chunks = [
        make_source_chunk("   "),
        make_source_chunk("Valid chunk"),
    ]

    result = chunk_document(
        make_parsed_document(),
        chunker=FakeChunker(chunks),
    )

    assert len(result) == 1
    assert result[0].chunk_index == 0
    assert result[0].text == "Valid chunk"


def test_chunk_document_raises_when_no_chunks_are_produced():
    with pytest.raises(
        DocumentChunkingError,
        match="did not produce any usable chunks",
    ):
        chunk_document(
            make_parsed_document(),
            chunker=FakeChunker([]),
        )


def test_chunk_document_rejects_missing_docling_document():
    parsed_document = make_parsed_document(document=None)

    with pytest.raises(DocumentChunkingError):
        chunk_document(
            parsed_document,
            chunker=FakeChunker([]),
        )


def test_chunk_document_rejects_empty_contextualized_text():
    class EmptyContextChunker(FakeChunker):
        def contextualize(self, chunk):
            return "   "

    with pytest.raises(
        DocumentChunkingError,
        match="empty contextualized text",
    ):
        chunk_document(
            make_parsed_document(),
            chunker=EmptyContextChunker(
                [make_source_chunk("Valid source text")]
            ),
        )


def test_chunk_document_wraps_unexpected_errors():
    class BrokenChunker:
        tokenizer = FakeTokenizer()

        def chunk(self, document):
            raise RuntimeError("Unexpected failure")

    with pytest.raises(
        DocumentChunkingError,
        match="Failed to chunk document",
    ):
        chunk_document(
            make_parsed_document(),
            chunker=BrokenChunker(),
        )
