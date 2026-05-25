"""CLI entrypoint for OpenWiki benchmarks."""
from __future__ import annotations

import argparse
import datetime
import json
import pathlib

from openwiki.framework.dataset import load_dataset_evaluator, load_dataset_manifest, load_dataset_questions
from openwiki.framework.judge import build_answer_from_context, evaluate_answer, evaluate_retrieval
from openwiki.framework.report import build_report, write_report
from openwiki.providers.filesystem import FilesystemProvider
from openwiki.providers.mem0 import Mem0Provider
from openwiki.providers.system import OpenWikiSystemProvider


def filter_questions(questions: list[dict], question_ids: list[str]) -> list[dict]:
    wanted = {question_id.strip() for question_id in question_ids if question_id.strip()}
    if not wanted:
        return questions
    return [question for question in questions if question.get("id") in wanted]


def run_provider(provider, questions: list[dict], top_k: int, evaluator=None) -> dict:
    indexed_docs = provider.build_index()
    print(f"[ingest/index] {indexed_docs} docs", flush=True)
    retrieval_scores = []
    answer_scores = []
    for question in questions:
        qid = question["id"]
        results = provider.search(question["question"], top_k=top_k, question_meta=question)
        retrieval = evaluate_retrieval(
            qid,
            question["question_type"],
            question.get("source_hints", []),
            results,
            question.get("requires_all_sources", False),
        )
        answer = build_answer_from_context(question["question"], results, question_meta=question, evaluator=evaluator)
        judged = evaluate_answer(
            qid,
            answer,
            question["ground_truth"],
            question["question_type"],
            question=question,
            results=results,
            evaluator=evaluator,
        )
        retrieval_scores.append(retrieval)
        answer_scores.append(judged)
        print(
            f"  {qid} [{question['question_type'][:10]:10s}] "
            f"R@5={'✓' if retrieval.hit_at_5 else '✗'} "
            f"MRR={retrieval.mrr:.2f} "
            f"Ans={judged.score:.2f}({judged.label[:4]})",
            flush=True,
        )
    return {
        "retrieval_scores": retrieval_scores,
        "answer_scores": answer_scores,
        "provider_stats": provider.stats(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="OpenWiki benchmark runner")
    parser.add_argument("--dataset", default="demo_wiki", help="Dataset id under openwiki/datasets/")
    parser.add_argument("--provider", choices=["filesystem", "mem0", "system", "components", "all"], default="system")
    parser.add_argument("--docs-root", required=True, help="Root directory containing markdown docs")
    parser.add_argument("--wiki-root", default="", help="Optional LLM-generated wiki/compiled docs root")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--question-ids", default="", help="Comma-separated subset of question ids")
    parser.add_argument("--runs-dir", default="runs", help="Directory where reports are written")
    args = parser.parse_args()

    dataset = load_dataset_manifest(args.dataset)
    questions = load_dataset_questions(args.dataset)
    evaluator = load_dataset_evaluator(args.dataset)
    if args.question_ids.strip():
        questions = filter_questions(questions, args.question_ids.split(","))
    print(f"Loaded {len(questions)} questions from dataset {dataset['id']}", flush=True)

    run_ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    providers = []
    wiki_root = pathlib.Path(args.wiki_root) if args.wiki_root else None
    if args.provider in {"system", "all"}:
        providers.append(OpenWikiSystemProvider(pathlib.Path(args.docs_root), wiki_root=wiki_root))
    if args.provider in {"filesystem", "components", "all"}:
        providers.append(FilesystemProvider(pathlib.Path(args.docs_root)))
    if args.provider in {"mem0", "components", "all"}:
        providers.append(Mem0Provider(pathlib.Path(args.docs_root)))

    reports = []
    for provider in providers:
        result = run_provider(provider, questions, args.top_k, evaluator=evaluator)
        run_id = f"{run_ts}-{provider.name}"
        report = build_report(
            dataset=dataset,
            provider_name=provider.name,
            provider_stats=result["provider_stats"],
            retrieval_scores=result["retrieval_scores"],
            answer_scores=result["answer_scores"],
            run_id=run_id,
            questions=questions,
        )
        out_dir = pathlib.Path(args.runs_dir) / run_id
        json_path, md_path = write_report(report, out_dir)
        print(f"[report] {json_path}", flush=True)
        print(f"[report] {md_path}", flush=True)
        reports.append(report)

    comparison_path = pathlib.Path(args.runs_dir) / f"{run_ts}-comparison.json"
    comparison_path.write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")
    if len(reports) > 1:
        comparison_md = pathlib.Path(args.runs_dir) / f"{run_ts}-comparison.md"
        lines = [
            f"# OpenWiki Comparison — {dataset['title']}",
            "",
            "| Provider | Accuracy | Recall@1 | Recall@3 | Recall@5 | MRR | Correct | Partial | Incorrect |",
            "|----------|----------|----------|----------|----------|-----|---------|---------|-----------|",
        ]
        for report in reports:
            summary = report["summary"]
            ret = summary["retrieval"]
            ans = summary["answer"]
            lines.append(
                f"| {report['provider']} | {ans['accuracy']*100:.1f}% | "
                f"{ret['recall_at_1']:.3f} | {ret['recall_at_3']:.3f} | {ret['recall_at_5']:.3f} | "
                f"{ret['mrr']:.3f} | {ans['correct']} | {ans['partial']} | {ans['incorrect']} |"
            )
        lines.extend(
            [
                "",
                "## By Question Type",
                "",
                "| Provider | Type | Count | Accuracy | Recall@1 | Recall@3 | Recall@5 | MRR |",
                "|----------|------|-------|----------|----------|----------|----------|-----|",
            ]
        )
        for report in reports:
            for question_type, metrics in sorted(report["by_question_type"].items()):
                ret = metrics["retrieval"]
                ans = metrics["answer"]
                lines.append(
                    f"| {report['provider']} | {question_type} | {ret['count']} | "
                    f"{ans['accuracy']*100:.1f}% | {ret['recall_at_1']:.3f} | {ret['recall_at_3']:.3f} | "
                    f"{ret['recall_at_5']:.3f} | {ret['mrr']:.3f} |"
                )
        comparison_md.write_text("\n".join(lines), encoding="utf-8")
        print(f"[report] {comparison_md}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
