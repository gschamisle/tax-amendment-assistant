# -*- coding: utf-8 -*-
"""병행개정 누락 검토 CLI — 개정안 묶음을 받아 대응 조문 미개정 후보를 뽑는다.

사용 예:
  uv run python -m scripts.scan_parallel_omissions "docs/입법예고/*.pdf"
  uv run python -m scripts.scan_parallel_omissions bills/*.hwpx --all

번호 밀림 검토(scan_renumber_omissions)와 짝이다. 그쪽이 기계적으로 확정되는
인용 정비 누락을 잡고, 이쪽은 판단이 필요한 병행개정 후보를 추린다.
"""
from __future__ import annotations

import argparse
import glob
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from core.hwp_reader import extract_text
from core.parallel_omission import (
    Bill,
    group_by_source_article,
    laws_with_parallel_relations,
    load_bill,
    scan,
)

_STATUS_LABEL = {
    "missing": "⚠️ 대응 조문 미개정 — 검토 필요",
    "pending": "→ 그 법 개정안이 이번 묶음에 없음 — 판단 보류",
    "covered": "✓ 대응 조문도 함께 개정됨",
}
_SOURCE_LABEL = {
    "golden_manual": "매뉴얼 확정",
    "bridge_confirmed": "다리 도출",
    "semantic_llm": "쌍별 판별",
    "code_hint": "코드 힌트",
    "related_hint": "연관 힌트",
}


def _read(path: Path) -> str:
    if path.suffix.lower() in (".md", ".txt"):
        return path.read_text(encoding="utf-8")
    return extract_text(path)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("patterns", nargs="+", help="개정안 파일/글롭 (.pdf/.hwpx/.hwp/.md/.txt)")
    ap.add_argument("--all", action="store_true", help="함께 개정된 건·보류 건도 표시")
    ap.add_argument("--directive-chars", type=int, default=180, help="지시문 표시 길이")
    args = ap.parse_args()

    paths = sorted({Path(p) for pat in args.patterns for p in glob.glob(pat)})
    if not paths:
        print("대상 파일이 없습니다.")
        return 1

    bills: list[Bill] = []
    for path in paths:
        bill = load_bill(_read(path), str(path))
        if bill is None:
            print(f"[skip] {path.name} — 개정문 본문을 찾지 못했습니다.")
            continue
        bills.append(bill)
    if not bills:
        print("개정문을 읽은 파일이 없습니다.")
        return 1

    result = scan(bills)
    if not result["matrix_ok"]:
        print("병행 매트릭스가 없습니다 — scripts/build_parallel_matrix.py 먼저 실행하세요.")
        return 1

    with_parallel = laws_with_parallel_relations()
    outside = sorted({b.law_name for b in bills if b.law_name not in with_parallel})

    print("=" * 78)
    print(f"개정안 {len(bills)}건 / 매트릭스 {result['matrix_meta'].get('built_at', '?')} 빌드")
    if outside:
        print(f"※ 병행 상대가 등록되지 않은 법령 — 대조 대상 없음: {', '.join(outside)}")
        print("  (병행개정은 '같은 위계·같은 취지' 관계입니다. 예컨대 종합부동산세법의 상대는")
        print("   재산세(지방세법)라 추적 범위 밖이고, 국세기본법·국세징수법은 절차법입니다.)")

    rows = result["rows"]
    shown = rows if args.all else [r for r in rows if r["상태"] == "missing"]
    counts = {s: sum(1 for r in rows if r["상태"] == s) for s in ("missing", "covered", "pending")}
    print(f"검토 후보 {counts['missing']}건 / 함께 개정 {counts['covered']}건 "
          f"/ 판단 보류 {counts['pending']}건")

    for group in group_by_source_article(shown):
        print("\n" + "-" * 78)
        print(f"■ {group['법령명']} {group['조문']}")
        directive = group["개정지시문"]
        if directive:
            head = directive[: args.directive_chars]
            print(f"   개정: {head}{'…' if len(directive) > args.directive_chars else ''}")
        for m in group["대응"]:
            label = _STATUS_LABEL.get(m["상태"], m["상태"])
            src = _SOURCE_LABEL.get(m["근거"], m["근거"])
            print(f"   → {m['대상법령']} {m['대상조문']}  [{src}]  {label}")

    print("\n" + "=" * 78)
    print("이 목록은 '누락'이 아니라 '검토 후보'입니다. 관계는 매트릭스가 확정한 것이지만,")
    print("이번 개정 내용에도 대응이 필요한지는 지시문을 보고 판단해야 합니다")
    print("(약칭 정리처럼 파급이 없는 개정이 상당수 섞입니다).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
