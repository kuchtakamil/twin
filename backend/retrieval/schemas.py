from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DocumentChunk:
    id: str
    source: str
    title: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    keywords: list[str] = field(default_factory=list)
    priority: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source,
            "title": self.title,
            "content": self.content,
            "metadata": self.metadata,
            "keywords": self.keywords,
            "priority": self.priority,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DocumentChunk":
        return cls(
            id=str(data["id"]),
            source=str(data["source"]),
            title=str(data["title"]),
            content=str(data["content"]),
            metadata=dict(data.get("metadata", {})),
            keywords=[str(keyword) for keyword in data.get("keywords", [])],
            priority=int(data.get("priority", 0)),
        )


@dataclass(frozen=True)
class RetrievedChunk:
    chunk: DocumentChunk
    score: float
    matched_terms: list[str] = field(default_factory=list)

    def to_source_dict(self) -> dict[str, Any]:
        return {
            "id": self.chunk.id,
            "source": self.chunk.source,
            "title": self.chunk.title,
            "score": round(self.score, 3),
            "metadata": self.chunk.metadata,
        }
