"""Optional structured LLM helpers for benchmark orchestration.

The benchmark framework works without this module. These helpers return
``None`` or an empty list when the configured local LLM command is unavailable.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
import tempfile
import threading

from openwiki.framework.provider import SearchResult


MODEL = os.environ.get("OPENWIKI_LLM_MODEL", "gpt-5.4")
EFFORT = os.environ.get("OPENWIKI_LLM_EFFORT", "medium")
_LOCK = threading.Lock()


def generate_query_variants(question_meta: dict, timeout_s: int = 45) -> list[str]:
    schema = {
        "type": "object",
        "properties": {
            "queries": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "maxItems": 4,
            }
        },
        "required": ["queries"],
        "additionalProperties": False,
    }
    prompt = (
        "Return only JSON matching the schema.\n"
        "Generate short retrieval-oriented query variants.\n"
        "Preserve the user's intent exactly and do not assume private filenames.\n\n"
        f"Question: {question_meta.get('question', '')}\n"
        f"Question type: {question_meta.get('question_type', '')}\n"
        f"Source hints: {json.dumps(question_meta.get('source_hints', []), ensure_ascii=False)}\n"
    )
    payload = _run_structured_llm(prompt, schema, timeout_s=timeout_s)
    queries = payload.get("queries", []) if isinstance(payload, dict) else []
    normalized: list[str] = []
    for query in queries:
        if not isinstance(query, str):
            continue
        for part in _split_suspicious_combined_query(query.strip()):
            if part:
                normalized.append(part)
    return _dedupe(normalized)


def synthesize_answer(
    question: str,
    results: list[SearchResult],
    question_meta: dict | None = None,
    draft_answer: str = "",
    timeout_s: int = 60,
) -> dict | None:
    schema = {
        "type": "object",
        "properties": {
            "answer": {"type": "string"},
            "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
            "used_paths": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 5,
            },
        },
        "required": ["answer", "confidence", "used_paths"],
        "additionalProperties": False,
    }
    question_type = (question_meta or {}).get("question_type", "")
    prompt = (
        "Return only JSON matching the schema.\n"
        "You are an evidence-grounded answer editor for a benchmark.\n"
        "Use only the evidence and preserve precise facts from the draft when supported.\n"
        "Answer in the same language as the question.\n\n"
        f"Question: {question}\n"
        f"Question type: {question_type}\n\n"
        f"Draft answer:\n{draft_answer or '(empty)'}\n\n"
        f"Evidence:\n{_format_results(results)}\n"
    )
    payload = _run_structured_llm(prompt, schema, timeout_s=timeout_s)
    if payload and isinstance(payload.get("answer"), str):
        payload["answer"] = _unwrap_nested_json_answer(payload["answer"])
    return payload


def judge_answer(
    question: str,
    generated: str,
    ground_truth: str,
    question_type: str,
    results: list[SearchResult] | None = None,
    timeout_s: int = 60,
) -> dict | None:
    schema = {
        "type": "object",
        "properties": {
            "score": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            "label": {"type": "string", "enum": ["correct", "partial", "incorrect"]},
            "explanation": {"type": "string"},
        },
        "required": ["score", "label", "explanation"],
        "additionalProperties": False,
    }
    prompt = (
        "Return only JSON matching the schema.\n"
        "Judge semantic correctness against the ground truth, not exact wording.\n\n"
        f"Question: {question}\n"
        f"Question type: {question_type}\n"
        f"Ground truth: {ground_truth}\n"
        f"Candidate answer: {generated}\n\n"
        f"Evidence:\n{_format_results(results or [])}\n"
    )
    return _run_structured_llm(prompt, schema, timeout_s=timeout_s)


def classify_route(question_meta: dict, timeout_s: int = 60) -> dict | None:
    from openwiki.routing import llm_route_schema

    schema = _route_output_schema()
    route_schema = llm_route_schema()
    question = question_meta.get("question", "")
    question_type = question_meta.get("question_type", "")
    source_hints = question_meta.get("source_hints", [])
    prompt = (
        "Return only JSON matching the schema.\n"
        "Classify the retrieval intent for a benchmark question.\n"
        "The intents object must contain exactly these keys and no others: "
        "stable_fact, recency, knowledge_update, conflict_check, multi_hop.\n"
        f"Allowed preferred_sources: {route_schema['preferred_sources']}.\n\n"
        f"Question: {question}\n"
        f"Question type: {question_type}\n"
        f"Source hints: {source_hints}\n"
    )
    payload = _run_structured_llm(prompt, schema, timeout_s=timeout_s)
    if payload is None:
        return None
    return _normalize_route_payload(payload)


def _run_structured_llm(prompt: str, schema: dict, timeout_s: int) -> dict | None:
    if os.environ.get("OPENWIKI_LLM_DISABLED", "").lower() in {"1", "true", "yes"}:
        return None
    with _LOCK:
        with tempfile.TemporaryDirectory(prefix="openwiki-llm-") as tmpdir:
            tmp = pathlib.Path(tmpdir)
            schema_path = tmp / "schema.json"
            output_path = tmp / "result.json"
            schema_path.write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")
            cmd = [
                "codex",
                "exec",
                "--model",
                MODEL,
                "-c",
                f'model_reasoning_effort="{EFFORT}"',
                "--sandbox",
                "read-only",
                "--skip-git-repo-check",
                "--ephemeral",
                "--color",
                "never",
                "--output-schema",
                str(schema_path),
                "--output-last-message",
                str(output_path),
                "-C",
                str(pathlib.Path.cwd()),
                "-",
            ]
            try:
                subprocess.run(cmd, input=prompt, text=True, capture_output=True, timeout=timeout_s, check=False)
            except (OSError, subprocess.TimeoutExpired):
                return None
            if not output_path.exists():
                return None
            try:
                return _parse_json_object(output_path.read_text(encoding="utf-8"))
            except Exception:
                return None


def _format_results(results: list[SearchResult]) -> str:
    if not results:
        return "(no evidence)"
    blocks: list[str] = []
    for result in results[:5]:
        content = _read_result_content(result).replace("\n", " ")
        blocks.append(f"- rank={result.rank} path={result.path}\n  evidence={content[:700]}")
    return "\n".join(blocks)


def _route_output_schema() -> dict:
    from openwiki.routing import llm_route_schema

    route_schema = llm_route_schema()
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "intents": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    key: {"type": "number", "minimum": 0, "maximum": 1}
                    for key in route_schema["intents"].keys()
                },
                "required": list(route_schema["intents"].keys()),
            },
            "preferred_sources": {
                "type": "array",
                "items": {"type": "string", "enum": route_schema["preferred_sources"]},
            },
            "time_sensitive": {"type": "boolean"},
            "needs_latest": {"type": "boolean"},
            "needs_cross_source_comparison": {"type": "boolean"},
            "reason": {"type": "string"},
        },
        "required": [
            "intents",
            "preferred_sources",
            "time_sensitive",
            "needs_latest",
            "needs_cross_source_comparison",
            "reason",
        ],
    }


def _normalize_route_payload(payload: dict) -> dict:
    from openwiki.routing import llm_route_schema

    intents = payload.get("intents", {})
    return {
        "intents": {
            "stable_fact": _clamp01(intents.get("stable_fact", 0.0)),
            "recency": _clamp01(intents.get("recency", 0.0)),
            "knowledge_update": _clamp01(intents.get("knowledge_update", 0.0)),
            "conflict_check": _clamp01(intents.get("conflict_check", 0.0)),
            "multi_hop": _clamp01(intents.get("multi_hop", 0.0)),
        },
        "preferred_sources": [
            source for source in payload.get("preferred_sources", [])
            if source in llm_route_schema()["preferred_sources"]
        ],
        "time_sensitive": bool(payload.get("time_sensitive", False)),
        "needs_latest": bool(payload.get("needs_latest", False)),
        "needs_cross_source_comparison": bool(payload.get("needs_cross_source_comparison", False)),
        "reason": str(payload.get("reason", ""))[:200],
    }


def _clamp01(value: object) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _read_result_content(result: SearchResult) -> str:
    try:
        return pathlib.Path(result.path).read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return result.content


def _parse_json_object(text: str) -> dict | None:
    text = text.strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _unwrap_nested_json_answer(answer: str) -> str:
    parsed = _parse_json_object(answer)
    if parsed and isinstance(parsed.get("answer"), str):
        return parsed["answer"]
    return answer


def _split_suspicious_combined_query(text: str) -> list[str]:
    if not text:
        return []
    separators = ["；", ";", "\n"]
    parts = [text]
    for separator in separators:
        next_parts: list[str] = []
        for part in parts:
            next_parts.extend(part.split(separator))
        parts = next_parts
    return [part.strip() for part in parts if part.strip()]


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
