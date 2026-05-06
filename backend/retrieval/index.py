from __future__ import annotations

import json
import os
from collections import Counter
from functools import lru_cache
from pathlib import Path

from .schemas import DocumentChunk, RetrievedChunk
from .scoring import chunk_terms, score_chunk


DEFAULT_INDEX_PATH = Path(__file__).resolve().parents[1] / "data" / "search_index.json"


class SearchIndex:
    def __init__(self, chunks: list[DocumentChunk]):
        self.chunks = chunks
        self.document_count = len(chunks)
        self.document_frequency = self._build_document_frequency(chunks)

    @staticmethod
    def _build_document_frequency(chunks: list[DocumentChunk]) -> dict[str, int]:
        document_frequency: Counter[str] = Counter()
        for chunk in chunks:
            document_frequency.update(set(chunk_terms(chunk)))
        return dict(document_frequency)

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        max_chars: int = 10_000,
    ) -> list[RetrievedChunk]:
        scored: list[RetrievedChunk] = []
        for chunk in self.chunks:
            score, matched_terms = score_chunk(
                query=query,
                chunk=chunk,
                document_frequency=self.document_frequency,
                document_count=self.document_count,
            )
            if score > 0:
                scored.append(RetrievedChunk(chunk=chunk, score=score, matched_terms=matched_terms))

        scored.sort(key=lambda result: (-result.score, result.chunk.source, result.chunk.id))

        selected: list[RetrievedChunk] = []
        used_chars = 0
        for result in scored:
            next_chars = len(result.chunk.content)
            if selected and used_chars + next_chars > max_chars:
                continue
            selected.append(result)
            used_chars += next_chars
            if len(selected) >= top_k:
                break

        return selected


def read_index_file(path: Path) -> list[DocumentChunk]:
    with path.open("r", encoding="utf-8") as index_file:
        payload = json.load(index_file)

    if payload.get("schema_version") != 1:
        raise ValueError(f"Unsupported search index schema version: {payload.get('schema_version')}")

    return [DocumentChunk.from_dict(chunk) for chunk in payload.get("chunks", [])]


@lru_cache(maxsize=1)
def load_search_index(index_path: str | None = None) -> SearchIndex:
    configured_path = index_path or os.getenv("SEARCH_INDEX_PATH")
    path = Path(configured_path) if configured_path else DEFAULT_INDEX_PATH
    return SearchIndex(read_index_file(path))
