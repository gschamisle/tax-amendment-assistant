"""입법예고 의견 분석 — 유사 의견 군집화 후 상위 X개 주요내용 리포트.

사용:
  uv run python scripts/analyze_opinions.py --bill 87936 --law 종합부동산세법 --top 20
  uv run python scripts/analyze_opinions.py --bill 87936 --top 20 --no-llm
  uv run python scripts/analyze_opinions.py --bill 87936 --threshold 0.5 --dump-pairs 20

산출물(output/):
  opinions-{bill}.md           보고서 — 상위 X개 군집의 주요내용·요구사항·관련조문
  opinions-{bill}-clusters.csv 군집 요약표
  opinions-{bill}-members.csv  전 건의 군집 배정 (판정 감사용)

군집화는 API 키 없이 돌아간다. `--no-llm`이면 Claude 호출 없이 결정적 라벨로 리포트를
완성하고, 기본 모드에서는 상위 X개 군집에 한해서만 요약을 생성한다.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from core.opinion_cluster import (  # noqa: E402
    DEFAULT_DUP_THRESHOLD,
    DEFAULT_THRESHOLD,
    OpinionDoc,
    cluster_opinions,
)
from core.opinion_normalize import boilerplate_sentences, strip_boilerplate  # noqa: E402
from core.opinion_report import (  # noqa: E402
    attach_summaries,
    build_views,
    render_markdown,
    write_clusters_csv,
    write_members_csv,
)
from core.opinion_source import OPINION_DIR, cache_path, load_from_files, load_records  # noqa: E402
from core.opinion_summary import ClusterBrief, summarize_clusters  # noqa: E402
from core.opinion_tagging import article_distribution, issue_distribution  # noqa: E402


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="입법예고 의견 군집화·요약 리포트")
    parser.add_argument("--bill", required=True, help="입법예고 ID")
    parser.add_argument("--law", default="", help="대상 법률명 (예: 종합부동산세법) — 조문 해석·리포트 제목에 사용")
    parser.add_argument("--top", type=int, default=20, help="주요내용을 정리할 상위 군집 수")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD, help="유사도 임계값")
    parser.add_argument("--dup-threshold", type=float, default=DEFAULT_DUP_THRESHOLD, help="근사중복 Jaccard 임계값")
    parser.add_argument("--no-llm", action="store_true", help="Claude 요약 없이 결정적 라벨만 사용")
    parser.add_argument("--no-boilerplate-strip", action="store_true", help="상투구 제거 생략")
    parser.add_argument("--dump-pairs", type=int, default=0, metavar="N", help="임계값 경계 근처 쌍 N개 출력")
    parser.add_argument("--from-files", nargs="+", metavar="PATH", help="수집 캐시 대신 파일에서 직접 읽기")
    parser.add_argument("--out", default=str(ROOT / "output"), help="출력 디렉터리")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    bill_id = str(args.bill)

    # 1) 의견 로드
    try:
        records = load_from_files([Path(p) for p in args.from_files], bill_id) if args.from_files \
            else load_records(bill_id)
    except Exception as exc:
        print(f"의견 로드 실패: {exc}", file=sys.stderr)
        return 1
    records = [r for r in records if r.body and r.body.strip()]
    if not records:
        print("분석할 의견이 없습니다.", file=sys.stderr)
        return 1
    print(f"의견 {len(records):,}건 로드")

    # 2) 상투구 제거 → 군집 입력
    bodies = [r.body for r in records]
    if args.no_boilerplate_strip:
        boiler: set[str] = set()
    else:
        boiler = boilerplate_sentences(bodies)
        if boiler:
            print(f"상투구 {len(boiler)}종 제거 (예: {', '.join(sorted(boiler)[:3])})")
    docs = [
        OpinionDoc(doc_id=r.opinion_id, text=strip_boilerplate(r.body, boiler) if boiler else r.body)
        for r in records
    ]

    # 3) 군집화
    result = cluster_opinions(
        docs,
        threshold=args.threshold,
        dup_threshold=args.dup_threshold,
        collect_borderline=args.dump_pairs,
    )
    print(
        f"군집 {len(result.clusters):,}개 (고유 본문 {result.unique_texts:,}종) · "
        f"상위 {args.top}개 커버리지 {result.coverage(args.top) * 100:.1f}%"
    )

    if args.dump_pairs and result.borderline_pairs:
        print(f"\n임계값({args.threshold}) 경계 쌍 표본:")
        for a, b, sim in result.borderline_pairs[: args.dump_pairs]:
            print(f"  {sim:.3f}  {a} ↔ {b}")
        print()

    # 4) 뷰 구성 + 상위 군집 요약
    views = build_views(result, records, default_law=args.law)
    llm_used = False
    if not args.no_llm:
        briefs = _briefs(views[: args.top], records)

        def progress(i: int, total: int, cached: bool) -> None:
            mark = "cache" if cached else "call "
            print(f"  요약 {i:>3}/{total} [{mark}]")

        print(f"상위 {len(briefs)}개 군집 요약 생성 중…")
        try:
            summaries = summarize_clusters(
                briefs,
                law_name=args.law,
                cache_file=OPINION_DIR / f"{bill_id}-summary.json",
                progress=progress,
            )
            attach_summaries(views, summaries)
            llm_used = True
            failed = [cid for cid, s in summaries.items() if "_error" in s]
            if failed:
                print(f"[경고] 요약 실패 군집: {failed} — 결정적 라벨로 대체합니다", file=sys.stderr)
        except Exception as exc:
            print(f"[경고] 요약 단계를 건너뜁니다: {exc}", file=sys.stderr)

    # 5) 출력
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    collected_at = _collected_at(bill_id) if not args.from_files else datetime.now().isoformat(timespec="seconds")

    md_path = out_dir / f"opinions-{bill_id}.md"
    md_path.write_text(
        render_markdown(
            result,
            views,
            bill_id=bill_id,
            law_name=args.law,
            top=args.top,
            collected_at=collected_at,
            llm_used=llm_used,
            article_totals=article_distribution(bodies, args.law),
            issue_totals=issue_distribution(bodies),
        ),
        encoding="utf-8",
    )
    clusters_csv = write_clusters_csv(out_dir / f"opinions-{bill_id}-clusters.csv", views)
    members_csv = write_members_csv(
        out_dir / f"opinions-{bill_id}-members.csv", views, records, default_law=args.law
    )

    print("\n생성 완료:")
    for path in (md_path, clusters_csv, members_csv):
        print(f"  {path}")

    print(f"\n상위 {min(args.top, len(views))}개 군집:")
    for view in views[: args.top]:
        name = (view.summary or {}).get("쟁점명") or view.label
        print(f"  {view.rank:>3}. {view.size:>5,}건 ({view.share * 100:>5.1f}%) {name}")
    return 0


def _briefs(views, records) -> list[ClusterBrief]:
    by_id = {r.opinion_id: r for r in records}
    briefs: list[ClusterBrief] = []
    for view in views:
        cluster = view.cluster
        samples = [
            by_id[mid].body
            for mid in cluster.exemplar_ids
            if mid in by_id and mid != cluster.medoid_id
        ]
        briefs.append(
            ClusterBrief(
                cluster_id=view.rank,
                size=view.size,
                share=view.share,
                representative=cluster.medoid_text,
                samples=samples,
                top_terms=cluster.top_terms,
                articles=[name for name, _ in view.articles],
                stance_hint=view.stance,
                demand_hint=view.demand,
            )
        )
    return briefs


def _collected_at(bill_id: str) -> str:
    path = cache_path(bill_id)
    if not path.exists():
        return ""
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("meta", {}).get("collected_at", "")
    except (json.JSONDecodeError, OSError):
        return ""


if __name__ == "__main__":
    sys.exit(main())
