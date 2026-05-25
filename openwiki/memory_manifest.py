"""Build generic memory items from markdown docs for external backends."""
from __future__ import annotations

import dataclasses
import json
import pathlib
import re
from typing import Iterable

from openwiki.bm25 import Document, load_markdown_files


@dataclasses.dataclass
class MemoryItem:
    id: str
    text: str
    source_path: str
    source_type: str
    tags: list[str]

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    def to_document(self) -> Document:
        metadata_lines = [
            f"source_type: {self.source_type}",
            f"path: {self.source_path}",
            f"tags: {' '.join(self.tags)}",
        ]
        return Document(
            doc_id=self.id,
            path=self.source_path,
            content="\n".join(metadata_lines) + "\n\n" + self.text,
            bucket=self.source_type,
        )


def build_memory_items(docs_root: pathlib.Path, exclude_dirs: set[str] | None = None) -> list[MemoryItem]:
    docs = load_markdown_files(docs_root, exclude_dirs=exclude_dirs or set(), use_cache=False)
    items = [document_to_memory_item(doc, docs_root) for doc in docs]
    return [item for item in items if item.text.strip()]


def document_to_memory_item(doc: Document, docs_root: pathlib.Path) -> MemoryItem:
    rel_path = pathlib.Path(doc.path).resolve().relative_to(docs_root.resolve())
    return MemoryItem(
        id=doc.doc_id,
        text=_strip_frontmatter(doc.content).strip()[:1800],
        source_path=str(rel_path),
        source_type=_source_type(rel_path),
        tags=_extract_tags(doc.content),
    )


def write_manifest(path: pathlib.Path, items: Iterable[MemoryItem]) -> int:
    count = 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for item in items:
            handle.write(json.dumps(item.to_dict(), ensure_ascii=False) + "\n")
            count += 1
    return count


def read_manifest(path: pathlib.Path) -> list[MemoryItem]:
    items: list[MemoryItem] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            items.append(MemoryItem(**json.loads(line)))
    return items


def _strip_frontmatter(text: str) -> str:
    if text.startswith("---\n"):
        parts = text.split("\n---\n", 1)
        if len(parts) == 2:
            return parts[1]
    return text


def _extract_tags(text: str) -> list[str]:
    match = re.search(r"tags:\n((?:\s*-\s.*\n?)*)", text)
    if not match:
        return []
    tags: list[str] = []
    for line in match.group(1).splitlines():
        line = line.strip()
        if line.startswith("- "):
            tags.append(line[2:].strip())
    return tags


def _source_type(path: pathlib.Path) -> str:
    lowered = str(path).lower()
    if "policy" in lowered or "governance" in lowered or "runbook" in lowered:
        return "policy"
    if "architecture" in lowered:
        return "architecture"
    return "source"

