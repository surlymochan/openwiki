"""Lightweight query rewrite helpers."""
from __future__ import annotations

import re


def build_query_variants(query: str, question_meta: dict | None = None) -> list[str]:
    meta = question_meta or {}
    question_type = str(meta.get("question_type", ""))
    entities = _extract_entities(query)
    variants = [query]

    if question_type == "policy_boundary":
        variants.append(_join_parts(query, ["policy", "rule", "allow", "forbid"]))
    elif question_type == "temporal_reasoning":
        variants.append(_join_parts(query, ["date", "time", "when"]))
    elif question_type == "multi_hop_reasoning" and entities:
        variants.append(_join_parts(query, entities))

    return _dedupe(variants)


def _extract_entities(query: str) -> list[str]:
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9_\-]{1,}", query)
    unique: list[str] = []
    seen = set()
    for token in tokens:
        lowered = token.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        unique.append(token)
    return unique


def _join_parts(*parts) -> str:
    values: list[str] = []
    seen = set()
    for part in parts:
        items = [part] if isinstance(part, str) else list(part)
        for item in items:
            normalized = str(item).strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            values.append(normalized)
    return " ".join(values)


def _dedupe(values: list[str]) -> list[str]:
    unique: list[str] = []
    seen = set()
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique.append(normalized)
    return unique

