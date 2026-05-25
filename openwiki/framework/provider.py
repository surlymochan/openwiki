"""Abstract provider interface."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class SearchResult:
    doc_id: str
    path: str
    content: str
    score: float
    rank: int


class BaseProvider(ABC):
    name: str = "base"
    description: str = ""

    @abstractmethod
    def build_index(self) -> int:
        """Index the data source."""

    @abstractmethod
    def search(self, query: str, top_k: int = 5, question_meta: dict | None = None) -> list[SearchResult]:
        """Retrieve relevant content."""

    def stats(self) -> dict:
        return {"provider": self.name}

