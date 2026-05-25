"""Filesystem markdown provider."""
from __future__ import annotations

import json
import pathlib

from openwiki.bm25 import BM25Index, load_markdown_files
from openwiki.framework.provider import BaseProvider, SearchResult
from openwiki.query_rewrite import build_query_variants


class FilesystemProvider(BaseProvider):
    name = "filesystem"
    description = "Index all markdown files under a docs root"

    def __init__(self, docs_root: pathlib.Path, exclude_dirs: set[str] | None = None) -> None:
        self.docs_root = docs_root.resolve()
        self.exclude_dirs = exclude_dirs or {".git", ".obsidian", "node_modules", "__pycache__"}
        self._index = BM25Index()
        self._doc_count = 0

    def build_index(self) -> int:
        docs = load_markdown_files(self.docs_root, exclude_dirs=self.exclude_dirs)
        self._index.add_documents(docs)
        self._doc_count = len(docs)
        return self._doc_count

    def search(self, query: str, top_k: int = 5, question_meta: dict | None = None) -> list[SearchResult]:
        variants = build_query_variants(query, question_meta)
        merged: dict[str, SearchResult] = {}
        for variant_index, variant in enumerate(variants):
            hits = self._index.search(variant, top_k=max(top_k * 2, 8))
            variant_penalty = 1.0 - variant_index * 0.08
            for rank, (doc, score) in enumerate(hits, start=1):
                adjusted = score * max(variant_penalty, 0.7)
                current = merged.get(doc.path)
                if current is None or adjusted > current.score:
                    merged[doc.path] = SearchResult(
                        doc_id=doc.doc_id,
                        path=doc.path,
                        content=doc.content[:900],
                        score=adjusted,
                        rank=rank,
                    )
        ranked = sorted(merged.values(), key=lambda item: item.score, reverse=True)[:top_k]
        return [
            SearchResult(
                doc_id=result.doc_id,
                path=result.path,
                content=result.content,
                score=result.score,
                rank=index,
            )
            for index, result in enumerate(ranked, start=1)
        ]

    def stats(self) -> dict:
        return {
            "provider": self.name,
            "indexed_docs": self._doc_count,
            "scope": str(self.docs_root),
            "exclude_dirs": sorted(self.exclude_dirs),
        }

    def to_json(self) -> str:
        return json.dumps(self.stats(), ensure_ascii=False)

