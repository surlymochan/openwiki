"""Generic retrieval and answer scoring."""
from __future__ import annotations

import math
import pathlib
import re
from dataclasses import dataclass
from types import ModuleType

from openwiki.framework.provider import SearchResult


@dataclass
class RetrievalScore:
    question_id: str
    question_type: str
    hit_at_1: bool
    hit_at_3: bool
    hit_at_5: bool
    mrr: float
    ndcg_at_5: float
    top_result_path: str
    top_result_score: float


@dataclass
class AnswerScore:
    question_id: str
    generated_answer: str
    ground_truth: str
    score: float
    label: str
    explanation: str


def _hint_in_path(result_path: str, hint: str) -> bool:
    return hint.lower() in result_path.lower()


def _any_hint(result_path: str, hints: list[str]) -> bool:
    return any(_hint_in_path(result_path, hint) for hint in hints)


def _first_hint_rank(results: list[SearchResult], hints: list[str]) -> int | None:
    for result in results:
        if _any_hint(result.path, hints):
            return result.rank
    return None


def _hints_covered_at_k(results: list[SearchResult], hints: list[str], top_k: int) -> bool:
    found = set()
    for result in results[:top_k]:
        for hint in hints:
            if _hint_in_path(result.path, hint):
                found.add(hint)
    return len(found) == len(hints)


def _all_hints_coverage_rank(results: list[SearchResult], hints: list[str]) -> int | None:
    found = set()
    for result in results:
        for hint in hints:
            if _hint_in_path(result.path, hint):
                found.add(hint)
        if len(found) == len(hints):
            return result.rank
    return None


def evaluate_retrieval(
    question_id: str,
    question_type: str,
    source_hints: list[str],
    results: list[SearchResult],
    requires_all_sources: bool = False,
) -> RetrievalScore:
    top_path = results[0].path if results else ""
    top_score = results[0].score if results else 0.0

    if question_type in {"abstention_strict", "abstention"}:
        hit = top_score < 2.0
        return RetrievalScore(question_id, question_type, hit, hit, hit, 1.0 if hit else 0.0, 1.0 if hit else 0.0, top_path, top_score)

    if requires_all_sources and source_hints:
        hit_at_1 = _hints_covered_at_k(results, source_hints, 1)
        hit_at_3 = _hints_covered_at_k(results, source_hints, 3)
        hit_at_5 = _hints_covered_at_k(results, source_hints, 5)
        coverage_rank = _all_hints_coverage_rank(results, source_hints)
        mrr = 1.0 / coverage_rank if coverage_rank else 0.0
        ideal_dcg = sum(1.0 / math.log2(i + 2) for i in range(len(source_hints)))
        dcg = 0.0
        for result in results[:5]:
            if _any_hint(result.path, source_hints):
                dcg += 1.0 / math.log2(result.rank + 1)
        ndcg = min(dcg / ideal_dcg, 1.0) if ideal_dcg > 0 else 0.0
        return RetrievalScore(question_id, question_type, hit_at_1, hit_at_3, hit_at_5, mrr, ndcg, top_path, top_score)

    hit_rank = _first_hint_rank(results, source_hints)
    hit_at_1 = hit_rank == 1
    hit_at_3 = hit_rank is not None and hit_rank <= 3
    hit_at_5 = hit_rank is not None and hit_rank <= 5
    mrr = 1.0 / hit_rank if hit_rank else 0.0
    dcg = 0.0
    for result in results[:5]:
        if _any_hint(result.path, source_hints):
            dcg += 1.0 / math.log2(result.rank + 1)
    ndcg = min(dcg, 1.0)
    return RetrievalScore(question_id, question_type, hit_at_1, hit_at_3, hit_at_5, mrr, ndcg, top_path, top_score)


def _cjk_tokens(text: str) -> set[str]:
    chars = re.findall(r"[\u4e00-\u9fff]", text)
    bigrams = {chars[i] + chars[i + 1] for i in range(len(chars) - 1)}
    words = set(re.findall(r"[a-zA-Z0-9\-\.]+", text.lower()))
    return set(chars) | bigrams | words


def keyword_overlap_score(generated: str, ground_truth: str) -> float:
    truth_tokens = _cjk_tokens(ground_truth)
    generated_tokens = _cjk_tokens(generated)
    if not truth_tokens:
        return 1.0 if not generated_tokens else 0.0
    if not generated_tokens:
        return 0.0
    overlap = truth_tokens & generated_tokens
    precision = len(overlap) / len(generated_tokens)
    recall = len(overlap) / len(truth_tokens)
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def _strip_frontmatter(text: str) -> str:
    if text.startswith("---\n"):
        parts = text.split("\n---\n", 1)
        if len(parts) == 2:
            return parts[1]
    return text


def _select_relevant_lines(question: str, content: str, max_lines: int = 3) -> list[str]:
    query_tokens = _cjk_tokens(question)
    lines = [line.strip() for line in _strip_frontmatter(content).splitlines() if line.strip()]
    if not lines:
        return []
    scored: list[tuple[int, int, str]] = []
    for idx, line in enumerate(lines):
        overlap = len(_cjk_tokens(line) & query_tokens)
        if overlap > 0:
            scored.append((overlap, -idx, line))
    if not scored:
        return lines[:max_lines]
    scored.sort(reverse=True)
    selected: list[str] = []
    seen = set()
    for _, neg_idx, _ in scored[:max_lines]:
        idx = -neg_idx
        for candidate_idx in (idx, idx + 1):
            if candidate_idx >= len(lines) or candidate_idx in seen:
                continue
            seen.add(candidate_idx)
            selected.append(lines[candidate_idx])
    return selected[: max_lines + 1]


def build_default_answer_from_context(
    question: str,
    results: list[SearchResult],
    question_meta: dict | None = None,
) -> str:
    if not results:
        return "No relevant information found."
    question_type = question_meta.get("question_type", "") if question_meta else ""
    source_hints = question_meta.get("source_hints", []) if question_meta else []
    if question_type in {"abstention_strict", "abstention"} and not source_hints and results[0].score < 2.0:
        return "No relevant information found in the benchmark wiki."
    prioritized_results = list(results)
    if source_hints:
        prioritized_results.sort(key=lambda row: (0 if _any_hint(row.path, source_hints) else 1, row.rank))
    snippets: list[str] = []
    seen = set()
    for result in prioritized_results[:3]:
        if result.path in seen:
            continue
        seen.add(result.path)
        source = pathlib.Path(result.path).stem
        snippets.extend(f"[{source}] {line}" for line in _select_relevant_lines(question, result.content))
        if len("\n".join(snippets)) >= 500:
            break
    return "\n".join(snippets)[:500].strip()


def build_answer_from_context(
    question: str,
    results: list[SearchResult],
    question_meta: dict | None = None,
    evaluator: ModuleType | None = None,
) -> str:
    if evaluator and hasattr(evaluator, "build_answer_from_context"):
        draft = evaluator.build_answer_from_context(question, results, question_meta)
        if draft is not None:
            return str(draft)[:500].strip()
    return build_default_answer_from_context(question, results, question_meta)


_UNCERTAINTY_SIGNALS = ["没有", "不知道", "无法", "未记录", "not found", "unknown", "not documented"]


def evaluate_default_answer(
    question_id: str,
    generated: str,
    ground_truth: str,
    question_type: str,
) -> AnswerScore:
    if question_type in {"abstention_strict", "abstention"}:
        has_uncertainty = any(signal in generated.lower() for signal in _UNCERTAINTY_SIGNALS)
        score = 1.0 if has_uncertainty else 0.0
        label = "correct" if score >= 0.7 else "incorrect"
        return AnswerScore(question_id, generated[:200], ground_truth[:200], score, label, "abstention signal check")
    score = keyword_overlap_score(generated, ground_truth)
    label = "correct" if score >= 0.6 else ("partial" if score >= 0.3 else "incorrect")
    return AnswerScore(question_id, generated[:200], ground_truth[:200], score, label, f"keyword F1 overlap: {score:.3f}")


def evaluate_answer(
    question_id: str,
    generated: str,
    ground_truth: str,
    question_type: str,
    question: dict | None = None,
    results: list[SearchResult] | None = None,
    evaluator: ModuleType | None = None,
) -> AnswerScore:
    if evaluator and hasattr(evaluator, "evaluate_answer"):
        scored = evaluator.evaluate_answer(question_id, generated, ground_truth, question_type, question, results)
        if scored is not None:
            return scored
    return evaluate_default_answer(question_id, generated, ground_truth, question_type)
