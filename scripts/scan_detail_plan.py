# -*- coding: utf-8 -*-
"""상세본 대조 CLI — 세제개편안 상세본과 법률안을 맞춰 본다.

  uv run python -m scripts.scan_detail_plan "docs/세법개정 세트/2. *상세본.pdf" \
      --bills "docs/입법예고/*.pdf"

번호 밀림·병행개정 스캐너가 못 보는 각도를 연다 — 상세본은 '어느 조문을 왜'
바꾸는지 입안자가 직접 적어 둔 문서라, 법률안과 대조하면 정책과 조문의 어긋남이
드러난다.
"""
from __future__ import annotations

import argparse
import glob
import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from core import law_abbrev
from core.detail_plan import parse_items, scan
from core.document_text import extract as extract_document
from core.parallel_omission import load_bill

_LABEL = {
    "missing_in_bill": "⚠️ 상세본에 있는데 법률안에 없음 — 반영 누락 후보",
    "no_refs": "· 조문 표기 없음 (사람 확인 필요)",
    "no_bill": "· 그 법 법률안이 묶음에 없음 — 판단 보류",
    "covered": "✓ 법률안이 그 조를 개정함",
}


def _read(path: Path) -> str:
    return extract_document(path)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("plan", help="상세본 파일 (.pdf/.md)")
    ap.add_argument("--bills", nargs="+", required=True, help="법률안 파일/글롭")
    ap.add_argument("--all", action="store_true", help="확인된 건·보류 건도 표시")
    ap.add_argument("--undisclosed", action="store_true",
                    help="공표 자료에 없는 개정 조문 목록도 출력")
    args = ap.parse_args()

    plan_path = Path(args.plan)
    if not plan_path.is_file():
        print(f"상세본을 찾지 못했습니다: {plan_path}")
        return 1
    items = parse_items(_read(plan_path))
    if not items:
        print("상세본에서 개정 항목을 찾지 못했습니다 — 문서 형식을 확인하세요.")
        return 1

    paths = sorted({Path(p) for pat in args.bills for p in glob.glob(pat)})
    bills = [b for b in (load_bill(_read(p), str(p)) for p in paths) if b]
    if not bills:
        print("법률안을 읽지 못했습니다.")
        return 1

    result = scan(items, bills)
    rows = result["rows"]
    counts = Counter(r["상태"] for r in rows)

    print("=" * 78)
    print(f"상세본 항목 {result['item_count']}개 / 법률안 {len(bills)}건 "
          f"({', '.join(law_abbrev.law(b.law_name) for b in bills)})")
    print(f"조문 대조 {len(rows)}건 — "
          f"반영됨 {counts['covered']} / 반영 누락 후보 {counts['missing_in_bill']} / "
          f"판단 보류 {counts['no_bill']} / 조문 표기 없음 {counts['no_refs']}")

    shown = rows if args.all else [r for r in rows if r["상태"] == "missing_in_bill"]
    for r in shown:
        print("\n" + "-" * 78)
        print(f"{_LABEL.get(r['상태'], r['상태'])}")
        if r["법령명"]:
            print(f"  {law_abbrev.law(r['법령명'])} {law_abbrev.jo_key(r['조번호'])}"
                  f"   (표기: {r['raw']})")
        print(f"  항목: {r['제목']}")
        if r["개정이유"]:
            print(f"  개정이유: {r['개정이유']}")
        if r["적용시기"]:
            print(f"  적용시기: {r['적용시기']}")

    if args.undisclosed:
        extra = result["undisclosed"]
        print("\n" + "=" * 78)
        print(f"공표 자료(상세본)에 나오지 않는 개정 조문 {len(extra)}건")
        print("이것은 '누락'이 아니다 — 단순 조문 정비나 조용히 바로잡는 오류 수정은")
        print("애초에 발표 대상이 아니다. 다만 내부 검토에서는 먼저 볼 값이 있다.")
        for e in extra:
            head = (e.get("지시문") or "").replace("\n", " ")[:96]
            print(f"  {law_abbrev.law(e['법령명'])} {law_abbrev.jo_key(e['조번호'])}"
                  + (f"  — {head}" if head else ""))

    print("\n" + "=" * 78)
    print("상세본은 사람이 쓰고 보고 과정에서 표기가 흔들린다(항목 대비 조문 표기가 적다).")
    print("'조문 표기 없음'이 많은 것은 문서의 성질이지 파싱 실패가 아니다 —")
    print("자세한 한계는 docs/세제개편안-상세본-구조.md 참조.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
