"""Dataset-specific answer scoring for the public demo dataset."""
from __future__ import annotations

from openwiki.framework.judge import AnswerScore, SearchResult, keyword_overlap_score


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
