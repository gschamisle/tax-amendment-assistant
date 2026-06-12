# -*- coding: utf-8 -*-
"""업로드된 개정법률안 분석 CLI — core.draft_bill_parser 래퍼.

사용 예:
  uv run python -m scripts.analyze_uploaded_draft <파일.hwpx|.hwp|.txt> --range "29, 29의2, 29의3" --proxy 24
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from core.draft_bill_parser import compare_review, find_amendment_body
from core.hwp_reader import extract_text


def _jo_label(key: str) -> str:
    parts = str(key).split("의")
    return f"제{parts[0]}조" + (f"의{parts[1]}" if len(parts) > 1 else "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", help="개정안 파일 (.hwpx/.hwp/.txt)")
    ap.add_argument("--range", required=True, help='신설 조번호 범위 (예: "29, 29의2, 29의3")')
    ap.add_argument("--proxy", default="", help='유사 제도 조문 (예: "24")')
    args = ap.parse_args()

    p = Path(args.path)
    text = p.read_text(encoding="utf-8") if p.suffix.lower() == ".txt" else extract_text(p)
    law_name, body = find_amendment_body(text)
    if not body:
        print("개정문 본문을 찾지 못했습니다 (…일부를 다음과 같이 개정한다).")
        return 1

    r = compare_review(law_name, args.range, body, args.proxy)

    print("=" * 70)
    print(f"대상 법령: {r['law_name']} / 수기 병행개정 {len(r['manual_targets'])}건")
    print("  ", ", ".join(_jo_label(j) for j in r["manual_targets"]))

    print("\n" + "=" * 70)
    ext, internal = r["forward"]["external"], r["forward"]["internal"]
    print(f"① 신설 본문 순방향 인용 — 외부 {len(ext)}건 / 내부 {len(internal)}건")
    for row in ext:
        print(f"   {row['법령명']} {row['조문']}  ← \"{row['인용 원문']}\"")

    print("\n" + "=" * 70)
    s = r["stale"]
    print(f"② 잔존 인용 — 수기 반영 {len(s['covered'])} / 미반영 {len(s['missing'])} / 시행령 {len(s['decree'])}")
    if s["missing"]:
        print("   ⚠️ 수기 개정안에 없는 잔존 인용:")
        for row in s["missing"]:
            print(f"      제{row['조번호']}조 {row['제목']} — 대상: {', '.join(row['대상'])}")
    if s["decree"]:
        print("   시행령 후속개정 목록:")
        for row in s["decree"]:
            print(f"      {row['법령명']} 제{row['조번호']}조 {row['제목']}")

    print("\n" + "=" * 70)
    px = r["proxy"]
    print(f"③ 프록시 체크리스트 — 수기 반영 {len(px['covered'])} / 미반영 {len(px['missing'])}")
    if px["missing"]:
        print("   ⚠️ 신설 조번호 추가 여부 검토:")
        for row in px["missing"]:
            print(f"      {row['법령명']} 제{row['조번호']}조 {row['제목']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
