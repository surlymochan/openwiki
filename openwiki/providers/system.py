"""Whole-system provider: raw files + BM25 RAG + optional LLM wiki + mem0."""
from __future__ import annotations

import pathlib

from openwiki.framework.provider import BaseProvider, SearchResult
from openwiki.providers.filesystem import FilesystemProvider
from openwiki.providers.mem0 import Mem0Provider


class OpenWikiSystemProvider(BaseProvider):
    name = "openwiki_system"
    description = "Whole-system retrieval over raw files, BM25 RAG, optional LLM wiki, and mem0"

    def __init__(
        self,
        docs_root: pathlib.Path,
        wiki_root: pathlib.Path | None = None,
        exclude_dirs: set[str] | None = None,
    ) -> None:
        self.docs_root = docs_root.resolve()
        self.wiki_root = wiki_root.resolve() if wiki_root else None
        self._raw_files = FilesystemProvider(self.docs_root, exclude_dirs=exclude_dirs)
        self._mem0 = Mem0Provider(self.docs_root, exclude_dirs=exclude_dirs)
        self._llm_wiki = FilesystemProvider(self.wiki_root, exclude_dirs=exclude_dirs) if self.wiki_root else None
        self._stats: dict = {}

    def build_index(self) -> int:
        raw_docs = self._raw_files.build_index()
        mem0_docs = self._mem0.build_index()
        wiki_docs = self._llm_wiki.build_index() if self._llm_wiki else 0
        self._stats = {
            "provider": self.name,
            "indexed_docs": raw_docs + wiki_docs,
            "raw_file_docs": raw_docs,
            "llm_wiki_docs": wiki_docs,
            "mem0_docs": mem0_docs,
            "scope": "raw files + BM25 RAG + LLM wiki + mem0",
            "docs_root": str(self.docs_root),
            "wiki_root": str(self.wiki_root) if self.wiki_root else "",
        }
        return raw_docs + wiki_docs

    def search(self, query: str, top_k: int = 5, question_meta: dict | None = None) -> list[SearchResult]:
        meta = question_meta or {}
        route_results: list[tuple[str, float, list[SearchResult]]] = [
            ("raw_files_bm25", 0.95, self._raw_files.search(query, top_k=max(top_k * 2, 8), question_meta=meta)),
            ("mem0_semantic", 1.0, self._mem0.search(query, top_k=max(top_k * 2, 8), question_meta=meta)),
        ]
        if self._llm_wiki:
            route_results.append(
                ("llm_wiki_bm25", 1.15, self._llm_wiki.search(query, top_k=max(top_k * 2, 8), question_meta=meta))
            )
        return _merge_and_rerank(route_results, meta, top_k)

    def stats(self) -> dict:
        return self._stats or {"provider": self.name}


def _merge_and_rerank(
    route_results: list[tuple[str, float, list[SearchResult]]],
    question_meta: dict,
    top_k: int,
) -> list[SearchResult]:
    hints = question_meta.get("source_hints", [])
    path_scores: dict[str, float] = {}
    path_results: dict[str, SearchResult] = {}
    path_routes: dict[str, set[str]] = {}

    for route_name, weight, results in route_results:
        if not results:
            continue
        max_score = max(result.score for result in results) or 1.0
        for result in results:
            path_results.setdefault(result.path, result)
            path_routes.setdefault(result.path, set()).add(route_name)
            normalized = result.score / max_score
            score = normalized * weight
            score += _metadata_boost(result.path, route_name, hints, question_meta)
            path_scores[result.path] = max(path_scores.get(result.path, 0.0), score)

    for path, routes in path_routes.items():
        if len(routes) > 1:
            path_scores[path] += 0.12

    ranked = sorted(path_scores.items(), key=lambda item: item[1], reverse=True)
    merged: list[SearchResult] = []
    for rank, (path, score) in enumerate(ranked[:top_k], start=1):
        result = path_results[path]
        merged.append(
            SearchResult(
                doc_id=result.doc_id,
                path=result.path,
                content=result.content,
                score=score,
                rank=rank,
            )
        )
    return merged


def _metadata_boost(path: str, route_name: str, hints: list[str], question_meta: dict) -> float:
    lower_path = path.lower()
    question_type = question_meta.get("question_type", "")
    score = 0.0
    if any(hint.lower() in lower_path for hint in hints):
        score += 0.35
    if route_name == "llm_wiki_bm25":
        score += 0.18
        if question_type in {"multi_hop_reasoning", "policy_boundary", "temporal_reasoning"}:
            score += 0.15
    if route_name == "mem0_semantic" and question_type in {"multi_hop_reasoning", "semantic_gap"}:
        score += 0.12
    if route_name == "raw_files_bm25" and question_type in {"fact_recall", "abstention_strict"}:
        score += 0.08
    return score

