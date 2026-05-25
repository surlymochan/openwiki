"""Lightweight query rewrite helpers."""
from __future__ import annotations

import re


def build_query_variants(query: str, question_meta: dict | None = None) -> list[str]:
    meta = question_meta or {}
    question_type = str(meta.get("question_type", ""))
    rewritten = rewrite_query(query, meta)
    variants = [query]
    if rewritten != query:
        variants.append(rewritten)

    entities = _extract_entities(query)
    if question_type == "boundary_definition" and entities:
        variants.append(_join_parts(f"{' 和 '.join(entities[:3])} 的定义和分工", ["定义", "职责", "边界"]))
        for entity in entities[:3]:
            variants.append(_join_parts([f"{entity} 是什么", f"{entity} 定义", f"{entity} 职责"]))

    if question_type == "negative_constraints" and entities:
        variants.append(_join_parts(entities, ["它不是", "边界", "定义"]))

    variants.extend(str(value) for value in meta.get("llm_query_variants", []) if str(value).strip())
    return _dedupe(variants)


def rewrite_query(query: str, question_meta: dict | None = None) -> str:
    meta = question_meta or {}
    question_type = str(meta.get("question_type", ""))
    entities = _extract_entities(query)

    if question_type == "negative_constraints":
        return _join_parts(query, entities, ["它不是", "定义", "边界", "定位"])

    if question_type == "boundary_definition":
        parts = [query]
        if entities:
            parts.append(" ".join(f"{entity} 是什么" for entity in entities[:3]))
        parts.extend(["定义", "分层", "职责", "边界"])
        return _join_parts(*parts)

    if question_type == "policy_boundary":
        return _join_parts(query, ["policy", "rule", "allow", "forbid", "规则", "允许", "禁止", "例外"])

    if question_type == "temporal_reasoning":
        return _join_parts(query, ["date", "time", "when"])

    if question_type == "multi_hop_reasoning" and entities:
        return _join_parts(query, entities)

    if question_type == "compiled_conclusion":
        return _join_parts(query, ["结论", "总结", "原则", "实际"])

    if question_type == "raw_evidence_retrieval":
        return _join_parts(query, ["原始证据", "记录", "来源"])

    return query


def _extract_entities(query: str) -> list[str]:
    backticked = re.findall(r"`([^`]+)`", query)
    ascii_words = re.findall(r"[A-Za-z][A-Za-z0-9_\-]{1,}", query)
    unique: list[str] = []
    seen = set()
    for token in backticked + ascii_words:
        cleaned = token.strip()
        lowered = cleaned.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        unique.append(cleaned)
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
