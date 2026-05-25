"""Pure-Python BM25 indexing and markdown loading."""
from __future__ import annotations

import hashlib
import json
import math
import os
import pathlib
import re
from dataclasses import dataclass, field


@dataclass
class Document:
    doc_id: str
    path: str
    content: str
    tokens: list[str] = field(default_factory=list)
    bucket: str = ""


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for word in re.findall(r"[a-zA-Z0-9_\-\.]+", text.lower()):
        if len(word) >= 2:
            tokens.append(word)
    cjk = re.findall(r"[\u4e00-\u9fff\u3400-\u4dbf]", text)
    tokens.extend(cjk)
    for i in range(len(cjk) - 1):
        tokens.append(cjk[i] + cjk[i + 1])
    return tokens


class BM25Index:
    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self.docs: list[Document] = []
        self.df: dict[str, int] = {}
        self.avg_dl: float = 0.0
        self._built = False

    def add_documents(self, docs: list[Document]) -> None:
        self.docs = docs
        for doc in docs:
            if not doc.tokens:
                doc.tokens = tokenize(doc.content)
        self._build()

    def _build(self) -> None:
        self.df = {}
        total_len = 0
        for doc in self.docs:
            total_len += len(doc.tokens)
            for term in set(doc.tokens):
                self.df[term] = self.df.get(term, 0) + 1
        self.avg_dl = total_len / max(len(self.docs), 1)
        self._built = True

    def to_payload(self) -> dict:
        assert self._built, "Call add_documents first"
        return {
            "k1": self.k1,
            "b": self.b,
            "df": self.df,
            "avg_dl": self.avg_dl,
            "docs": [
                {
                    "doc_id": doc.doc_id,
                    "path": doc.path,
                    "content": doc.content,
                    "tokens": doc.tokens,
                    "bucket": doc.bucket,
                }
                for doc in self.docs
            ],
        }

    @classmethod
    def from_payload(cls, payload: dict) -> "BM25Index":
        index = cls(k1=float(payload.get("k1", 1.5)), b=float(payload.get("b", 0.75)))
        index.docs = [
            Document(
                doc_id=row["doc_id"],
                path=row["path"],
                content=row["content"],
                tokens=list(row.get("tokens", [])),
                bucket=row.get("bucket", ""),
            )
            for row in payload.get("docs", [])
        ]
        index.df = {str(key): int(value) for key, value in (payload.get("df") or {}).items()}
        index.avg_dl = float(payload.get("avg_dl", 0.0))
        index._built = True
        return index

    def search(self, query: str, top_k: int = 5) -> list[tuple[Document, float]]:
        assert self._built, "Call add_documents first"
        q_tokens = tokenize(query)
        total_docs = len(self.docs)
        scores: list[tuple[int, float]] = []
        for idx, doc in enumerate(self.docs):
            doc_len = len(doc.tokens)
            score = 0.0
            tf_map: dict[str, int] = {}
            for term in doc.tokens:
                tf_map[term] = tf_map.get(term, 0) + 1
            for term in q_tokens:
                if term not in self.df:
                    continue
                tf = tf_map.get(term, 0)
                if tf == 0:
                    continue
                idf = math.log((total_docs - self.df[term] + 0.5) / (self.df[term] + 0.5) + 1)
                tf_norm = (tf * (self.k1 + 1)) / (
                    tf + self.k1 * (1 - self.b + self.b * doc_len / self.avg_dl)
                )
                score += idf * tf_norm
            scores.append((idx, score))
        scores.sort(key=lambda row: row[1], reverse=True)
        return [(self.docs[i], score) for i, score in scores[:top_k] if score > 0]


def load_markdown_files(
    root: pathlib.Path,
    exclude_dirs: set[str] | None = None,
    include_only_dirs: set[str] | None = None,
    max_chunk_chars: int = 2000,
    use_cache: bool = True,
) -> list[Document]:
    if exclude_dirs is None:
        exclude_dirs = set()
    root = root.resolve()
    cache_path = _cache_path(root, exclude_dirs, include_only_dirs, max_chunk_chars)
    candidates = _collect_markdown_candidates(root, exclude_dirs, include_only_dirs)
    fingerprint = _fingerprint_candidates(root, candidates, max_chunk_chars)
    if use_cache:
        cached = _load_cached_docs(cache_path, fingerprint)
        if cached is not None:
            return cached

    docs: list[Document] = []
    for fpath, parts in candidates:
        try:
            text = fpath.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        rel_path = str(fpath.relative_to(root))
        bucket = parts[0] if parts else "root"
        if len(text) <= max_chunk_chars:
            docs.append(
                Document(
                    doc_id=rel_path,
                    path=str(fpath),
                    content=text,
                    tokens=tokenize(text),
                    bucket=bucket,
                )
            )
            continue

        stride = max(max_chunk_chars // 2, 1)
        for chunk_index, start in enumerate(range(0, len(text), stride)):
            chunk = text[start : start + max_chunk_chars]
            docs.append(
                Document(
                    doc_id=f"{rel_path}::chunk{chunk_index}",
                    path=str(fpath),
                    content=chunk,
                    tokens=tokenize(chunk),
                    bucket=bucket,
                )
            )

    if use_cache:
        _write_cached_docs(cache_path, fingerprint, docs)
    return docs


def _collect_markdown_candidates(
    root: pathlib.Path,
    exclude_dirs: set[str],
    include_only_dirs: set[str] | None = None,
) -> list[tuple[pathlib.Path, list[str]]]:
    candidates: list[tuple[pathlib.Path, list[str]]] = []
    for dirpath, dirnames, filenames in os.walk(root):
        rel = pathlib.Path(dirpath).relative_to(root)
        parts = list(rel.parts)
        top = parts[0] if parts else ""
        if include_only_dirs is not None and top not in include_only_dirs:
            dirnames[:] = []
            continue
        if set(parts) & exclude_dirs:
            dirnames[:] = []
            continue
        for fname in filenames:
            if fname.lower().endswith(".md"):
                candidates.append((pathlib.Path(dirpath) / fname, parts))
    return candidates


def _bm25_cache_root() -> pathlib.Path:
    configured = os.environ.get("OPENWIKI_BM25_CACHE_ROOT", "")
    cache_root = pathlib.Path(configured).expanduser() if configured else pathlib.Path(__file__).resolve().parents[1] / "data" / "cache"
    cache_root.mkdir(parents=True, exist_ok=True)
    return cache_root


def _cache_path(
    root: pathlib.Path,
    exclude_dirs: set[str],
    include_only_dirs: set[str] | None,
    max_chunk_chars: int,
) -> pathlib.Path:
    cache_root = _bm25_cache_root()
    payload = {
        "root": str(root),
        "exclude": sorted(exclude_dirs),
        "include": sorted(include_only_dirs) if include_only_dirs else [],
        "max_chunk_chars": max_chunk_chars,
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    return cache_root / f"docs-{digest}.json"


def index_cache_path(name: str) -> pathlib.Path:
    cache_root = _bm25_cache_root()
    safe = re.sub(r"[^a-zA-Z0-9_.-]+", "-", name)
    return cache_root / f"bm25-{safe}.json"


def markdown_fingerprint(
    root: pathlib.Path,
    exclude_dirs: set[str] | None = None,
    include_only_dirs: set[str] | None = None,
    max_chunk_chars: int = 2000,
) -> str:
    if exclude_dirs is None:
        exclude_dirs = set()
    root = root.resolve()
    candidates = _collect_markdown_candidates(root, exclude_dirs, include_only_dirs)
    return _fingerprint_candidates(root, candidates, max_chunk_chars)


def _fingerprint_candidates(
    root: pathlib.Path,
    candidates: list[tuple[pathlib.Path, list[str]]],
    max_chunk_chars: int,
) -> str:
    hasher = hashlib.sha256()
    hasher.update(str(root).encode("utf-8"))
    hasher.update(str(max_chunk_chars).encode("utf-8"))
    for fpath, _parts in candidates:
        try:
            stat = fpath.stat()
        except OSError:
            continue
        hasher.update(str(fpath.relative_to(root)).encode("utf-8"))
        hasher.update(str(stat.st_size).encode("utf-8"))
        hasher.update(str(stat.st_mtime_ns).encode("utf-8"))
    return hasher.hexdigest()


def _load_cached_docs(cache_path: pathlib.Path, fingerprint: str) -> list[Document] | None:
    if not cache_path.exists():
        return None
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if payload.get("fingerprint") != fingerprint:
        return None
    docs: list[Document] = []
    for row in payload.get("docs", []):
        docs.append(
            Document(
                doc_id=row["doc_id"],
                path=row["path"],
                content=row["content"],
                tokens=list(row.get("tokens", [])),
                bucket=row.get("bucket", ""),
            )
        )
    return docs


def _write_cached_docs(cache_path: pathlib.Path, fingerprint: str, docs: list[Document]) -> None:
    payload = {
        "fingerprint": fingerprint,
        "docs": [
            {
                "doc_id": doc.doc_id,
                "path": doc.path,
                "content": doc.content,
                "tokens": doc.tokens,
                "bucket": doc.bucket,
            }
            for doc in docs
        ],
    }
    cache_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
