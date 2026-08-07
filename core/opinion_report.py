"""군집 결과 → 보고서(Markdown) · CSV.

리포트는 두 가지를 동시에 만족해야 한다:
  * 읽는 사람: 상위 X개 군집의 "주요내용"만 봐도 여론 지형이 잡힐 것
  * 검증하는 사람: 군집 판정이 타당한지 표본으로 감사할 수 있을 것

그래서 Markdown 본문(요약)과 members.csv(전 건의 군집 배정·유사 근거)를 함께 낸다.
LLM 요약이 없거나 실패해도 결정적 라벨로 같은 구조의 리포트가 나온다.
"""
from __future__ import annotations

import csv
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from core.opinion_cluster import Cluster, ClusterResult
from core.opinion_source import OpinionRecord
from core.opinion_tagging import (
    article_distribution,
    classify_stance,
    deterministic_label,
    issue_distribution,
    related_articles,
)

_SNIPPET = 200


@dataclass
class ClusterView:
    """리포트 렌더링에 필요한 것만 모은 군집 1개."""
    cluster: Cluster
    share: float
    label: str
    stance: str
    demand: str
    articles: list[tuple[str, int]] = field(default_factory=list)
    issues: list[tuple[str, int]] = field(default_factory=list)
    summary: dict[str, Any] | None = None

    @property
    def size(self) -> int:
        return self.cluster.size

    @property
    def rank(self) -> int:
        return self.cluster.cluster_id


def _majority(counter: Counter[str], *, ignore: str = "불명") -> str:
    ranked = [(v, k) for k, v in counter.items() if k != ignore]
    if not ranked:
        return ignore
    ranked.sort(key=lambda kv: (-kv[0], kv[1]))
    return ranked[0][1]


def build_views(
    result: ClusterResult,
    records: Sequence[OpinionRecord],
    *,
    default_law: str = "",
    top_articles: int = 5,
    top_issues: int = 5,
) -> list[ClusterView]:
    """군집 + 원 의견 → 리포트용 뷰. 조문·찬반·쟁점을 군집 단위로 집계한다."""
    by_id = {r.opinion_id: r for r in records}
    views: list[ClusterView] = []

    for cluster in result.clusters:
        texts = [by_id[mid].body for mid in cluster.member_ids if mid in by_id]
        tags = [classify_stance(t) for t in texts]
        stances = Counter(tag.stance for tag in tags)
        demands = Counter(tag.demand for tag in tags)
        views.append(
            ClusterView(
                cluster=cluster,
                share=cluster.size / result.total if result.total else 0.0,
                label=deterministic_label(cluster.medoid_text, cluster.top_terms),
                stance=_majority(stances),
                demand=_majority(demands),
                articles=article_distribution(texts, default_law).most_common(top_articles),
                issues=issue_distribution(texts).most_common(top_issues),
            )
        )
    return views


def attach_summaries(views: Sequence[ClusterView], summaries: dict[int, dict[str, Any]]) -> None:
    for view in views:
        summary = summaries.get(view.rank)
        if summary and "_error" not in summary:
            view.summary = summary


# ── Markdown ──────────────────────────────────────────────────────────────────

def _fmt_pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _bullet_counts(pairs: Sequence[tuple[str, int]], empty: str = "—") -> str:
    if not pairs:
        return empty
    return ", ".join(f"{name}({count})" for name, count in pairs)


def render_markdown(
    result: ClusterResult,
    views: Sequence[ClusterView],
    *,
    bill_id: str,
    law_name: str = "",
    top: int = 20,
    collected_at: str = "",
    llm_used: bool = False,
    article_totals: Counter[str] | None = None,
    issue_totals: Counter[str] | None = None,
) -> str:
    total = result.total
    head = views[:top]
    lines: list[str] = []

    title = f"{law_name} 입법예고 의견 분석" if law_name else f"입법예고 의견 분석 (bill {bill_id})"
    lines += [
        f"# {title}",
        "",
        f"- 대상 입법예고: `{bill_id}`" + (f" ({law_name})" if law_name else ""),
        f"- 총 의견: **{total:,}건** (서로 다른 본문 {result.unique_texts:,}종)",
        f"- 군집: **{len(result.clusters):,}개** (유사도 임계값 {result.threshold})",
        f"- 상위 {len(head)}개 군집이 전체의 **{_fmt_pct(result.coverage(top))}** 를 차지",
        f"- 요약 생성: {'Claude 요약 적용' if llm_used else '결정적 라벨만 (--no-llm)'}",
    ]
    if collected_at:
        lines.append(f"- 수집 시각: {collected_at}")
    lines += ["", "> 군집은 규칙·유사도로 결정적으로 만들어졌고, LLM은 상위 군집의 문장 정리에만 "
              "관여합니다. 건수·비율은 LLM과 무관합니다.", ""]

    # 전체 분포
    stance_total: Counter[str] = Counter()
    for view in views:
        stance_total[view.stance] += view.size
    # 전체 분포는 의견 단위 집계(article_totals)를 쓰는 게 정확하다. 넘어오지 않았을 때만
    # 군집별 상위 항목을 합산한 근사치로 채운다.
    article_total = article_totals if article_totals is not None else Counter()
    issue_total = issue_totals if issue_totals is not None else Counter()
    if article_totals is None or issue_totals is None:
        for view in views:
            if article_totals is None:
                for name, count in view.articles:
                    article_total[name] += count
            if issue_totals is None:
                for name, count in view.issues:
                    issue_total[name] += count

    lines += [
        "## 전체 분포",
        "",
        "| 구분 | 내용 |",
        "|------|------|",
        f"| 찬반(군집 다수의견 기준) | {_bullet_counts(stance_total.most_common())} |",
        f"| 많이 언급된 조문 | {_bullet_counts(article_total.most_common(8))} |",
        f"| 많이 언급된 쟁점 | {_bullet_counts(issue_total.most_common(8))} |",
        "",
    ]

    # 상위 군집 요약표
    lines += [
        f"## 상위 {len(head)}개 군집 요약",
        "",
        "| 순위 | 건수 | 비율 | 쟁점 | 스탠스 | 요구 |",
        "|-----:|-----:|-----:|------|--------|------|",
    ]
    for view in head:
        name = (view.summary or {}).get("쟁점명") or view.label
        name = name.replace("|", "\\|")
        lines.append(
            f"| {view.rank} | {view.size:,} | {_fmt_pct(view.share)} | {name} | "
            f"{(view.summary or {}).get('스탠스') or view.stance} | {view.demand} |"
        )
    lines.append("")

    # 군집별 상세
    lines += ["## 군집별 주요내용", ""]
    for view in head:
        summary = view.summary or {}
        name = summary.get("쟁점명") or view.label
        lines += [
            f"### {view.rank}. {name}",
            "",
            f"- **의견 수**: {view.size:,}건 ({_fmt_pct(view.share)}) "
            f"— 동일 문구 최대 {view.cluster.exact_dup_max:,}건, 변형 {view.cluster.variant_count:,}종",
            f"- **스탠스**: {summary.get('스탠스') or view.stance} / **요구**: {view.demand}",
            f"- **관련 조문**: {_bullet_counts(view.articles)}",
            f"- **쟁점 태그**: {_bullet_counts(view.issues)}",
            f"- **핵심 키워드**: {', '.join(view.cluster.top_terms) or '—'}",
            f"- **응집도**: {view.cluster.cohesion}",
            "",
        ]
        if summary.get("주요내용"):
            lines += ["**주요내용**", "", summary["주요내용"], ""]
        if summary.get("요구사항"):
            lines += ["**요구사항**", ""]
            lines += [f"- {item}" for item in summary["요구사항"]]
            lines.append("")

        quote = summary.get("대표인용") or _snippet(view.cluster.medoid_text, 300)
        lines += ["**대표 의견 발췌**", "", f"> {quote.strip()}", ""]

    # 롱테일
    tail = views[top:]
    if tail:
        tail_size = sum(v.size for v in tail)
        lines += [
            "## 그 밖의 의견 (롱테일)",
            "",
            f"상위 {len(head)}개 밖의 군집 {len(tail):,}개 · {tail_size:,}건 "
            f"({_fmt_pct(tail_size / total if total else 0)}).",
            "",
            "| 순위 | 건수 | 라벨 |",
            "|-----:|-----:|------|",
        ]
        for view in tail[:30]:
            label = view.label.replace("|", "\\|")
            lines.append(f"| {view.rank} | {view.size:,} | {label} |")
        if len(tail) > 30:
            lines.append(f"| … | … | 이하 {len(tail) - 30:,}개 군집 생략 (clusters.csv 참조) |")
        lines.append("")

    failed = [v.rank for v in head if v.summary is None and llm_used]
    if failed:
        lines += [
            "## 비고",
            "",
            f"- LLM 요약이 생성되지 않은 군집: {', '.join(str(r) for r in failed)} "
            "(결정적 라벨로 대체 표시)",
            "",
        ]

    lines += [
        "---",
        "",
        "생성: `scripts/analyze_opinions.py` · 군집 판정 근거는 `*-members.csv`에서 전 건 확인 가능",
        "",
    ]
    return "\n".join(lines)


def _snippet(text: str, limit: int = _SNIPPET) -> str:
    cleaned = " ".join(str(text or "").split())
    return cleaned if len(cleaned) <= limit else cleaned[: limit - 1] + "…"


# ── CSV ───────────────────────────────────────────────────────────────────────

def write_clusters_csv(path: Path | str, views: Sequence[ClusterView]) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow([
            "순위", "의견수", "비율", "쟁점명", "스탠스", "요구", "관련조문", "쟁점태그",
            "핵심키워드", "응집도", "변형수", "최대동일문구", "대표의견ID", "대표의견발췌",
        ])
        for view in views:
            summary = view.summary or {}
            writer.writerow([
                view.rank,
                view.size,
                f"{view.share * 100:.2f}%",
                summary.get("쟁점명") or view.label,
                summary.get("스탠스") or view.stance,
                view.demand,
                "; ".join(f"{n}({c})" for n, c in view.articles),
                "; ".join(f"{n}({c})" for n, c in view.issues),
                "; ".join(view.cluster.top_terms),
                view.cluster.cohesion,
                view.cluster.variant_count,
                view.cluster.exact_dup_max,
                view.cluster.medoid_id,
                _snippet(view.cluster.medoid_text, 300),
            ])
    return target


def write_members_csv(
    path: Path | str,
    views: Sequence[ClusterView],
    records: Sequence[OpinionRecord],
    *,
    default_law: str = "",
) -> Path:
    """전 건의 군집 배정 결과. 군집 판정이 타당한지 사람이 감사하기 위한 표다."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    by_id = {r.opinion_id: r for r in records}
    with target.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow([
            "의견ID", "군집순위", "군집쟁점명", "등록일", "작성자(마스킹)", "찬반",
            "요구", "관련조문", "본문발췌",
        ])
        for view in views:
            name = (view.summary or {}).get("쟁점명") or view.label
            for member_id in view.cluster.member_ids:
                record = by_id.get(member_id)
                if record is None:
                    continue
                tag = classify_stance(record.body)
                writer.writerow([
                    record.opinion_id,
                    view.rank,
                    name,
                    record.posted_at,
                    record.author_masked,
                    tag.stance,
                    tag.demand,
                    "; ".join(related_articles(record.body, default_law)[:5]),
                    _snippet(record.body),
                ])
    return target
