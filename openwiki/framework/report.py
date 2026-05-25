"""Report generation helpers."""
from __future__ import annotations

import datetime
import json
import pathlib
from collections import defaultdict

from openwiki.framework.judge import AnswerScore, RetrievalScore


def _avg(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def build_report(
    dataset: dict,
    provider_name: str,
    provider_stats: dict,
    retrieval_scores: list[RetrievalScore],
    answer_scores: list[AnswerScore],
    run_id: str,
    questions: list[dict],
) -> dict:
    by_type_retrieval: dict[str, list[RetrievalScore]] = defaultdict(list)
    by_type_answer: dict[str, list[AnswerScore]] = defaultdict(list)
    for score in retrieval_scores:
        by_type_retrieval[score.question_type].append(score)
    question_type_map = {question["id"]: question["question_type"] for question in questions}
    for score in answer_scores:
        by_type_answer[question_type_map.get(score.question_id, "unknown")].append(score)

    def retrieval_metrics(scores: list[RetrievalScore]) -> dict:
        return {
            "count": len(scores),
            "recall_at_1": _avg([float(score.hit_at_1) for score in scores]),
            "recall_at_3": _avg([float(score.hit_at_3) for score in scores]),
            "recall_at_5": _avg([float(score.hit_at_5) for score in scores]),
            "mrr": _avg([score.mrr for score in scores]),
            "ndcg_at_5": _avg([score.ndcg_at_5 for score in scores]),
        }

    def answer_metrics(scores: list[AnswerScore]) -> dict:
        return {
            "count": len(scores),
            "accuracy": _avg([score.score for score in scores]),
            "correct": sum(1 for score in scores if score.label == "correct"),
            "partial": sum(1 for score in scores if score.label == "partial"),
            "incorrect": sum(1 for score in scores if score.label == "incorrect"),
        }

    overall_retrieval = retrieval_metrics(retrieval_scores)
    overall_answer = answer_metrics(answer_scores)
    return {
        "run_id": run_id,
        "provider": provider_name,
        "provider_stats": provider_stats,
        "benchmark": dataset["id"],
        "dataset": dataset,
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "summary": {
            "total_questions": len(retrieval_scores),
            "retrieval": overall_retrieval,
            "answer": overall_answer,
            "memscore": (
                f"{overall_answer['accuracy']*100:.1f}% accuracy | "
                f"Recall@5={overall_retrieval['recall_at_5']:.2f} | "
                f"MRR={overall_retrieval['mrr']:.2f}"
            ),
        },
        "by_question_type": {
            question_type: {
                "retrieval": retrieval_metrics(by_type_retrieval.get(question_type, [])),
                "answer": answer_metrics(by_type_answer.get(question_type, [])),
            }
            for question_type in sorted(set(by_type_retrieval) | set(by_type_answer))
        },
        "detailed_results": [
            {
                "question_id": retrieval.question_id,
                "question": next((question["question"] for question in questions if question["id"] == retrieval.question_id), ""),
                "question_type": retrieval.question_type,
                "capabilities": next((question.get("capabilities", []) for question in questions if question["id"] == retrieval.question_id), []),
                "retrieval": {
                    "hit_at_1": retrieval.hit_at_1,
                    "hit_at_3": retrieval.hit_at_3,
                    "hit_at_5": retrieval.hit_at_5,
                    "mrr": round(retrieval.mrr, 3),
                    "ndcg_at_5": round(retrieval.ndcg_at_5, 3),
                    "top_result": pathlib.Path(retrieval.top_result_path).name if retrieval.top_result_path else "",
                    "top_score": round(retrieval.top_result_score, 3),
                },
                "answer": next(
                    (
                        {
                            "score": round(answer.score, 3),
                            "label": answer.label,
                            "explanation": answer.explanation,
                            "generated": answer.generated_answer[:240],
                        }
                        for answer in answer_scores
                        if answer.question_id == retrieval.question_id
                    ),
                    {},
                ),
            }
            for retrieval in retrieval_scores
        ],
    }


def write_report(report: dict, out_dir: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "results.json"
    md_path = out_dir / "results.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = report["summary"]
    retrieval = summary["retrieval"]
    answer = summary["answer"]
    lines = [
        f"# OpenWiki Report — {report['dataset']['title']}",
        "",
        f"**Dataset**: `{report['dataset']['id']}`  ",
        f"**Provider**: `{report['provider']}`  ",
        f"**Run ID**: `{report['run_id']}`  ",
        f"**Generated**: {report['generated_at']}  ",
        f"**Indexed docs**: {report['provider_stats'].get('indexed_docs', '?')} ({report['provider_stats'].get('scope', '')})",
        "",
        "## MemScore",
        "",
        f"> {summary['memscore']}",
        "",
        "## Overall Metrics",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Questions | {summary['total_questions']} |",
        f"| Answer Accuracy | {answer['accuracy']*100:.1f}% |",
        f"| Correct | {answer['correct']} |",
        f"| Partial | {answer['partial']} |",
        f"| Incorrect | {answer['incorrect']} |",
        f"| Recall@1 | {retrieval['recall_at_1']:.3f} |",
        f"| Recall@3 | {retrieval['recall_at_3']:.3f} |",
        f"| Recall@5 | {retrieval['recall_at_5']:.3f} |",
        f"| MRR | {retrieval['mrr']:.3f} |",
        f"| NDCG@5 | {retrieval['ndcg_at_5']:.3f} |",
        "",
        "## Detailed Results",
        "",
        "| ID | Type | R@5 | MRR | Answer | Label | Top Retrieved |",
        "|----|------|-----|-----|--------|-------|----------------|",
    ]
    for result in report["detailed_results"]:
        retrieval_row = result["retrieval"]
        answer_row = result["answer"]
        lines.append(
            f"| {result['question_id']} | {result['question_type']} | "
            f"{'✓' if retrieval_row['hit_at_5'] else '✗'} | "
            f"{retrieval_row['mrr']:.2f} | "
            f"{answer_row.get('score', 0)*100:.0f}% | "
            f"{answer_row.get('label', '-')} | "
            f"`{retrieval_row['top_result'][:40]}` |"
        )
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path

