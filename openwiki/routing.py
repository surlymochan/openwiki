"""Generic route planning and reranking primitives."""
from __future__ import annotations

import dataclasses
import re
from collections.abc import Callable

from openwiki.framework.provider import SearchResult


@dataclasses.dataclass
class IntentScores:
    stable_fact: float = 0.0
    recency: float = 0.0
    knowledge_update: float = 0.0
    conflict_check: float = 0.0
    multi_hop: float = 0.0


@dataclasses.dataclass
class LLMRouteDecision:
    intents: IntentScores
    preferred_sources: list[str]
    time_sensitive: bool
    needs_latest: bool
    needs_cross_source_comparison: bool
    reason: str = ""


@dataclasses.dataclass
class PlannedRoute:
    name: str
    weight: float
    top_k: int
    filters: dict[str, str]


@dataclasses.dataclass
class RoutePlan:
    routes: list[PlannedRoute]
    intents: IntentScores
    time_sensitive: bool
    needs_latest: bool
    needs_cross_source_comparison: bool
    reason: str


MetadataBoostFn = Callable[[str, dict, RoutePlan, list[str]], float]


def llm_route_schema() -> dict:
    return {
        "intents": {
            "stable_fact": "0.0-1.0",
            "recency": "0.0-1.0",
            "knowledge_update": "0.0-1.0",
            "conflict_check": "0.0-1.0",
            "multi_hop": "0.0-1.0",
        },
        "preferred_sources": ["compiled", "source", "diary", "weeknote"],
        "time_sensitive": True,
        "needs_latest": True,
        "needs_cross_source_comparison": False,
        "reason": "one sentence",
    }


def parse_llm_route_decision(payload: dict | None) -> LLMRouteDecision | None:
    if not payload:
        return None
    intents = payload.get("intents", {})
    return LLMRouteDecision(
        intents=IntentScores(
            stable_fact=float(intents.get("stable_fact", 0.0)),
            recency=float(intents.get("recency", 0.0)),
            knowledge_update=float(intents.get("knowledge_update", 0.0)),
            conflict_check=float(intents.get("conflict_check", 0.0)),
            multi_hop=float(intents.get("multi_hop", 0.0)),
        ),
        preferred_sources=list(payload.get("preferred_sources", [])),
        time_sensitive=bool(payload.get("time_sensitive", False)),
        needs_latest=bool(payload.get("needs_latest", False)),
        needs_cross_source_comparison=bool(payload.get("needs_cross_source_comparison", False)),
        reason=str(payload.get("reason", "")),
    )


def build_route_plan(question_meta: dict, llm_payload: dict | None = None) -> RoutePlan:
    query = question_meta.get("question", "")
    question_type = question_meta.get("question_type", "")
    rule = _rule_intents(query, question_type)
    llm = parse_llm_route_decision(llm_payload)

    intents = _merge_intents(rule, llm.intents if llm else None)
    time_sensitive = rule.recency > 0.4 or rule.knowledge_update > 0.4
    needs_latest = "最新" in query or "最近" in query or rule.recency > 0.6
    needs_cross_source = rule.conflict_check > 0.4 or rule.multi_hop > 0.6

    if llm:
        time_sensitive = time_sensitive or llm.time_sensitive
        needs_latest = needs_latest or llm.needs_latest
        needs_cross_source = needs_cross_source or llm.needs_cross_source_comparison

    routes = _fixed_dual_recall_routes(intents, question_meta)

    return RoutePlan(
        routes=routes,
        intents=intents,
        time_sensitive=time_sensitive,
        needs_latest=needs_latest,
        needs_cross_source_comparison=needs_cross_source,
        reason=llm.reason if llm and llm.reason else _reason_from_intents(intents),
    )


def rerank_results(
    query: str,
    question_meta: dict,
    route_plan: RoutePlan,
    route_results: dict[str, list[SearchResult]],
    top_k: int,
    metadata_boost_fn: MetadataBoostFn | None = None,
) -> list[SearchResult]:
    hints = question_meta.get("source_hints", [])
    path_scores: dict[str, float] = {}
    path_results: dict[str, SearchResult] = {}

    route_weight = {route.name: route.weight for route in route_plan.routes}
    for route_name, results in route_results.items():
        if not results:
            continue
        max_score = max(result.score for result in results) or 1.0
        for result in results:
            path_results.setdefault(result.path, result)
            normalized = result.score / max_score
            score = normalized * route_weight.get(route_name, 1.0)
            score += _generic_metadata_boost(result.path, question_meta, route_plan, hints)
            if metadata_boost_fn is not None:
                score += metadata_boost_fn(result.path, question_meta, route_plan, hints)
            path_scores[result.path] = max(path_scores.get(result.path, 0.0), score)

    ranked = sorted(path_scores.items(), key=lambda item: item[1], reverse=True)
    merged: list[SearchResult] = []
    for rank, (path, score) in enumerate(ranked[:top_k], start=1):
        result = path_results[path]
        merged.append(
            SearchResult(
                doc_id=result.doc_id,
                path=result.path,
                content=result.content,
                score=score,
                rank=rank,
            )
        )
    return merged


def _fixed_dual_recall_routes(intents: IntentScores, question_meta: dict) -> list[PlannedRoute]:
    question_type = question_meta.get("question_type", "")
    needs_all_sources = bool(question_meta.get("requires_all_sources"))

    bm25_compiled_weight = 0.95
    bm25_source_weight = 0.95
    mem0_compiled_weight = 0.85
    mem0_source_weight = 0.85
    compiled_top_k = 10
    source_top_k = 12

    if intents.stable_fact >= 0.6 and intents.recency < 0.5 and intents.knowledge_update < 0.5:
        bm25_compiled_weight += 0.20
        mem0_compiled_weight += 0.20
        bm25_source_weight -= 0.20
        mem0_source_weight -= 0.20

    if intents.recency >= 0.5 or intents.knowledge_update >= 0.5:
        bm25_source_weight += 0.25
        mem0_source_weight += 0.30
        bm25_compiled_weight -= 0.20
        mem0_compiled_weight -= 0.15
        source_top_k = 16

    if intents.conflict_check >= 0.5 or intents.multi_hop >= 0.5 or needs_all_sources:
        bm25_source_weight += 0.10
        mem0_source_weight += 0.10
        bm25_compiled_weight += 0.05
        mem0_compiled_weight += 0.05
        compiled_top_k = 12
        source_top_k = 16

    if question_type == "boundary_definition":
        bm25_compiled_weight += 0.15
        mem0_compiled_weight += 0.10

    return [
        PlannedRoute("bm25_compiled", max(bm25_compiled_weight, 0.2), compiled_top_k, {"scope": "compiled"}),
        PlannedRoute("bm25_source", max(bm25_source_weight, 0.2), source_top_k, {"scope": "source"}),
        PlannedRoute("mem0_compiled", max(mem0_compiled_weight, 0.2), compiled_top_k, {"scope": "compiled"}),
        PlannedRoute("mem0_source", max(mem0_source_weight, 0.2), source_top_k, {"scope": "source"}),
    ]


def _rule_intents(query: str, question_type: str) -> IntentScores:
    scores = IntentScores()
    if question_type in {"fact_recall", "preference", "temporal_reasoning"}:
        scores.stable_fact = 0.8
    if question_type == "knowledge_update":
        scores.knowledge_update = 1.0
        scores.recency = 0.7
    if question_type == "recency_preference":
        scores.recency = 1.0
    if question_type in {"conflict_detection", "principle_vs_reality"}:
        scores.conflict_check = 1.0
        scores.multi_hop = 0.8
    if question_type == "multi_hop_reasoning":
        scores.multi_hop = 0.8

    if re.search(r"(最近|最新|这次|那天|今天|昨天|刚刚|目前最新)", query):
        scores.recency = max(scores.recency, 0.8)
    if re.search(r"(更新|变化|覆盖|现在.*以前|最新记录)", query):
        scores.knowledge_update = max(scores.knowledge_update, 0.8)
    if re.search(r"(原则|画像|定义|偏好|长期|一贯)", query):
        scores.stable_fact = max(scores.stable_fact, 0.7)
    if re.search(r"(一致|冲突|矛盾|落差|现实)", query):
        scores.conflict_check = max(scores.conflict_check, 0.8)
    return scores


def _merge_intents(rule: IntentScores, llm: IntentScores | None) -> IntentScores:
    if llm is None:
        return rule
    return IntentScores(
        stable_fact=max(rule.stable_fact, llm.stable_fact),
        recency=max(rule.recency, llm.recency),
        knowledge_update=max(rule.knowledge_update, llm.knowledge_update),
        conflict_check=max(rule.conflict_check, llm.conflict_check),
        multi_hop=max(rule.multi_hop, llm.multi_hop),
    )


def _reason_from_intents(intents: IntentScores) -> str:
    if intents.knowledge_update >= 0.5:
        return "knowledge_update -> compiled/source dual recall, source-weighted"
    if intents.recency >= 0.5:
        return "recency -> compiled/source dual recall, source-weighted"
    if intents.conflict_check >= 0.5 or intents.multi_hop >= 0.5:
        return "cross-source reasoning -> compiled/source dual recall"
    return "stable fact -> compiled/source dual recall, compiled-weighted"


def _generic_metadata_boost(path: str, question_meta: dict, route_plan: RoutePlan, hints: list[str]) -> float:
    del route_plan
    lower_path = path.lower()
    score = 0.0
    if any(hint.lower() in lower_path for hint in hints):
        score += 0.35
    question_type = question_meta.get("question_type", "")
    if question_type == "boundary_definition":
        overview_markers = ["定义", "readme", "index", "总图", "总览", "概览"]
        if any(marker in path for marker in overview_markers):
            score += 0.30
    return score
