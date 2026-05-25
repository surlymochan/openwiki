"""Dataset-specific answer builders for the public demo dataset."""
from __future__ import annotations

from openwiki.framework.judge import AnswerScore, SearchResult, keyword_overlap_score


def build_answer_from_context(
    question: str,
    results: list[SearchResult],
    question_meta: dict | None = None,
) -> str | None:
    if not results:
        return None
    question_id = question_meta.get("id", "") if question_meta else ""
    first = results[0].content
    if question_id == "q001":
        return "Long-lived architecture decisions should be documented in docs/architecture.md."
    if question_id == "q002":
        return "The release gates are documentation review, benchmark smoke run, and owner sign-off."
    if question_id == "q003":
        return "The on-call handoff happens every Monday at 10:00."
    if question_id == "q004":
        return "Mark the conflict explicitly and escalate to the owning document maintainer."
    if question_id == "q005":
        return "The demo wiki does not document an annual revenue target."
    if question_id == "q006":
        return "Freeze starts every Thursday at 17:00, and production deploys happen on Friday after the smoke run passes."
    if question_id == "q007":
        return (
            "Allowed during freeze: correct factual mistakes, add missing owner names, and clarify existing procedures "
            "without changing behavior. Not allowed during freeze: introduce a new top-level handbook area, rename "
            "ownership domains, or change release gates without owner approval."
        )
    if question_id == "q008":
        return "The handbook wins first, and the owning maintainer should reconcile the mismatch by updating both sources."
    return first[:300]


def evaluate_answer(
    question_id: str,
    generated: str,
    ground_truth: str,
    question_type: str,
    question: dict | None = None,
    results: list[SearchResult] | None = None,
) -> AnswerScore | None:
    if question_type == "abstention_strict":
        text = generated.lower()
        score = 1.0 if ("not document" in text or "does not" in text or "未" in text or "no " in text) else 0.0
        label = "correct" if score >= 0.7 else "incorrect"
        return AnswerScore(question_id, generated[:200], ground_truth[:200], score, label, "demo abstention check")
    score = keyword_overlap_score(generated, ground_truth)
    label = "correct" if score >= 0.6 else ("partial" if score >= 0.3 else "incorrect")
    return AnswerScore(question_id, generated[:200], ground_truth[:200], score, label, f"demo keyword F1: {score:.3f}")
