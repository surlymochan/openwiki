"""Generic mem0-backed provider for OpenWiki."""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import time
import urllib.request
from typing import Any

from openwiki.bm25 import BM25Index
from openwiki.framework.provider import BaseProvider, SearchResult
from openwiki.memory_manifest import MemoryItem, build_memory_items, read_manifest


class Mem0Provider(BaseProvider):
    name = "mem0"
    description = "Retrieve from a mem0 backend using public markdown memory items"

    def __init__(self, docs_root: pathlib.Path, exclude_dirs: set[str] | None = None) -> None:
        self.docs_root = docs_root.resolve()
        self.exclude_dirs = exclude_dirs or {".git", ".obsidian", "node_modules", "__pycache__"}
        self._index = BM25Index()
        self._items: list[MemoryItem] = []
        configured_backend = os.getenv("OPENWIKI_MEM0_BACKEND", "").strip().lower()
        self._allow_local_fallback = os.getenv("OPENWIKI_MEM0_ALLOW_LOCAL_FALLBACK", "").strip().lower() in {"1", "true", "yes"}
        self._ssh_host = os.getenv("OPENWIKI_MEM0_SSH_HOST", "").strip()
        self._remote_api_url = os.getenv("OPENWIKI_MEM0_API_URL", "").strip()
        self._backend = configured_backend or ("remote" if (self._ssh_host or self._remote_api_url) else "local-fallback")
        self._remote_api_port = int(os.getenv("OPENWIKI_MEM0_API_PORT", "8787"))
        self._remote_timeout_s = int(os.getenv("OPENWIKI_MEM0_TIMEOUT_S", "25"))
        self._user_id = os.getenv("OPENWIKI_MEM0_USER_ID", "openwiki-demo")
        self._manifest_path = pathlib.Path(
            os.getenv(
                "OPENWIKI_MEM0_MANIFEST",
                str(pathlib.Path(__file__).resolve().parents[2] / "data" / "memory_manifest.jsonl"),
            )
        )

    def build_index(self) -> int:
        if self._manifest_path.exists():
            self._items = read_manifest(self._manifest_path)
        else:
            self._items = build_memory_items(self.docs_root, exclude_dirs=self.exclude_dirs)
        docs = [item.to_document() for item in self._items]
        self._index.add_documents(docs)
        return len(self._items)

    def search(self, query: str, top_k: int = 5, question_meta: dict | None = None) -> list[SearchResult]:
        meta = question_meta or {}
        if self._backend == "remote":
            try:
                return self._remote_search(query, top_k=top_k, meta=meta)
            except Exception:
                if not self._allow_local_fallback:
                    raise
                self._backend = "local-fallback"

        hits = self._index.search(query, top_k=max(top_k * 3, top_k))
        item_map = {item.id: item for item in self._items}
        ranked = []
        for rank, (doc, score) in enumerate(hits, start=1):
            item = item_map.get(doc.doc_id)
            if not item:
                continue
            boosted = _metadata_rerank(item, score, meta)
            ranked.append((boosted, rank, item))
        ranked.sort(key=lambda row: (-row[0], row[1]))
        return [
            SearchResult(
                doc_id=item.id,
                path=item.source_path,
                content=item.text[:900],
                score=score,
                rank=out_rank,
            )
            for out_rank, (score, _, item) in enumerate(ranked[:top_k], start=1)
        ]

    def stats(self) -> dict:
        return {
            "provider": self.name,
            "indexed_docs": len(self._items),
            "scope": f"mem0:{self.docs_root.name}",
            "backend": self._backend,
        }

    def _remote_search(self, query: str, top_k: int, meta: dict[str, Any]) -> list[SearchResult]:
        payload = build_mem0_search_payload(query, top_k, self._user_id)
        response = remote_mem0_search(
            payload,
            api_url=self._remote_api_url,
            ssh_host=self._ssh_host,
            api_port=self._remote_api_port,
            timeout_s=self._remote_timeout_s,
        )
        results = response.get("results", [])
        item_map = {item.id: item for item in self._items}
        ranked: list[tuple[float, int, MemoryItem, dict[str, Any]]] = []
        if not results:
            return []
        max_score = max(float(row.get("score", 0.0)) for row in results) or 1.0
        for rank, row in enumerate(results, start=1):
            metadata = row.get("metadata") or {}
            doc_id = str(metadata.get("doc_id") or "")
            item = item_map.get(doc_id) or _remote_hit_to_item(row)
            boosted = _metadata_rerank(item, float(row.get("score", 0.0)) / max_score, meta)
            ranked.append((boosted, rank, item, row))
        ranked.sort(key=lambda hit: (-hit[0], hit[1]))
        return [
            SearchResult(
                doc_id=item.id,
                path=item.source_path,
                content=(row.get("memory") or item.text)[:900],
                score=score,
                rank=out_rank,
            )
            for out_rank, (score, _, item, row) in enumerate(ranked[:top_k], start=1)
        ]


def _metadata_rerank(item: MemoryItem, score: float, meta: dict[str, Any]) -> float:
    hints = meta.get("source_hints", [])
    boosted = score
    if any(hint.lower() in item.source_path.lower() for hint in hints):
        boosted += 0.35
    if meta.get("question_type") == "policy_boundary" and item.source_type == "policy":
        boosted += 0.2
    if meta.get("question_type") == "temporal_reasoning" and "runbook" in item.source_path.lower():
        boosted += 0.15
    return boosted


def _remote_hit_to_item(hit: dict[str, Any]) -> MemoryItem:
    normalized = normalize_remote_hit(hit)
    return MemoryItem(
        id=normalized["doc_id"],
        text=normalized["memory"],
        source_path=normalized["source_path"],
        source_type=normalized["source_type"],
        tags=normalized["tags"],
    )


def build_mem0_search_payload(
    query: str,
    top_k: int,
    user_id: str,
    filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "query": query,
        "limit": max(top_k * 3, top_k),
        "user_id": user_id,
        "filters": mem0_scope_filters(filters or {}),
    }


def mem0_scope_filters(filters: dict[str, Any]) -> dict[str, Any] | None:
    scope = filters.get("scope")
    if not scope or scope == "hybrid":
        return None
    if scope == "source":
        return {"is_compiled": False}
    if scope == "compiled":
        return {"is_compiled": True}
    if scope == "diary":
        return {"source_type": "diary"}
    return None


def remote_mem0_search(
    payload: dict[str, Any],
    *,
    api_url: str = "",
    ssh_host: str = "",
    api_port: int = 8787,
    timeout_s: int = 25,
) -> dict[str, Any]:
    if api_url:
        request = urllib.request.Request(
            api_url.rstrip("/") + "/search",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            return json.loads(response.read().decode("utf-8"))

    if not ssh_host:
        raise RuntimeError("api_url or ssh_host is required for remote mem0")

    last_error: Exception | None = None
    for attempt in range(3):
        try:
            completed = subprocess.run(
                [
                    "ssh",
                    ssh_host,
                    (
                        "curl -fsS --max-time "
                        f"{timeout_s} "
                        "-H 'Content-Type: application/json' "
                        f"-X POST http://127.0.0.1:{api_port}/search "
                        "--data-binary @-"
                    ),
                ],
                input=json.dumps(payload, ensure_ascii=False),
                text=True,
                capture_output=True,
                check=True,
                timeout=timeout_s + 5,
            )
            return json.loads(completed.stdout.strip() or "{}")
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            last_error = exc
            if attempt == 2:
                break
            time.sleep(0.5 * (attempt + 1))
    if isinstance(last_error, subprocess.CalledProcessError):
        stderr = (last_error.stderr or "").strip()
        raise RuntimeError(f"remote mem0 search failed: {stderr or 'ssh/curl returned non-zero'}") from last_error
    raise RuntimeError("remote mem0 search timed out after retries") from last_error


def normalize_remote_hit(hit: dict[str, Any]) -> dict[str, Any]:
    metadata = hit.get("metadata") or {}
    tags = metadata.get("tags") or []
    return {
        "id": str(hit.get("id") or metadata.get("doc_id") or ""),
        "doc_id": str(metadata.get("doc_id") or hit.get("id") or ""),
        "memory": str(hit.get("memory") or ""),
        "score": float(hit.get("score", 0.0)),
        "metadata": metadata,
        "source_path": str(metadata.get("source_path") or ""),
        "source_type": str(metadata.get("source_type") or "source"),
        "tags": list(tags) if isinstance(tags, list) else [str(tags)],
    }
