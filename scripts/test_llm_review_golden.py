# -*- coding: utf-8 -*-
"""LLM 검토 골든 회귀 테스트 — ○○세액공제 개정안 (라이브, 로컬 전용).

오프라인 스위트에 포함하지 않는다: ANTHROPIC_API_KEY + 내부자료(data/uploaded_draft.txt,
git 미추적)가 필요하다. 프롬프트·모델·스키마를 바꿀 때마다 수동 실행해 회귀를 확인한다.

  uv run python -m scripts.test_llm_review_golden

골든 기준 (2026-06-12 전문가 수동 분석과 합치 확인된 사실들):
  - 신설 범위는 29, 29의2, 29의3 (29~29의8 전체가 아님)
  - 제127조(중복지원 배제)는 개정안에 없으며 '누락' 또는 최소 '판단필요' — '조치불요'면 회귀
  - 잔존 인용 7건(72, 74, 104의7, 106, 30의4, 133, 146의2) 중 과반이 '누락'
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

DRAFT = Path(__file__).resolve().parents[1] / "data" / "uploaded_draft.txt"
STALE_SEVEN = {"72", "74", "104의7", "106", "30의4", "133", "146의2"}


def main() -> int:
    if not DRAFT.is_file():
        print("SKIP: data/uploaded_draft.txt 없음 (내부자료 — 로컬 전용 테스트)")
        return 0

    from config import ANTHROPIC_API_KEY

    if not ANTHROPIC_API_KEY:
        print("SKIP: ANTHROPIC_API_KEY 미설정")
        return 0

    from core.draft_bill_parser import compare_review, find_amendment_body
    from core.llm_review import run_llm_review

    text = DRAFT.read_text(encoding="utf-8")
    law, body = find_amendment_body(text)
    cmp = compare_review(law, "29, 29의2, 29의3", body, "24")
    result = run_llm_review(cmp, body)

    # 1. 구조 해석: 신설 범위
    inferred = set(result["구조"]["신설_조번호"])
    assert inferred == {"29", "29의2", "29의3"}, f"신설 범위 회귀: {inferred}"

    review = result["검토"]
    by_jo = {
        (it["법령명"], it["조번호"]): it["구분"]
        for it in review["항목"]
    }

    # 2. 제127조 — 가장 중요한 쟁점. '조치불요'로 빠지면 회귀
    cls_127 = by_jo.get(("조세특례제한법", "127"))
    assert cls_127 in ("누락", "판단필요"), f"제127조 분류 회귀: {cls_127}"

    # 3. 잔존 인용 7건 중 과반이 누락
    stale_missing = sum(
        1 for jo in STALE_SEVEN if by_jo.get(("조세특례제한법", jo)) == "누락"
    )
    assert stale_missing >= 4, f"잔존 인용 누락 분류 {stale_missing}/7 — 회귀 의심"

    # 4. 종합의견 존재 + 127조 언급
    opinion = str(review["종합의견"])
    assert len(opinion) > 100, "종합의견이 비정상적으로 짧음"
    assert "127" in opinion, "종합의견이 제127조 쟁점을 언급하지 않음"

    print("GOLDEN OK")
    print(f"  신설 범위: {sorted(inferred)}")
    print(f"  제127조: {cls_127}")
    print(f"  잔존 7건 중 누락 분류: {stale_missing}건")
    return 0


if __name__ == "__main__":
    sys.exit(main())
