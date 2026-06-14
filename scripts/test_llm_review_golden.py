# -*- coding: utf-8 -*-
"""LLM 검토 골든 회귀 테스트 — 라이브, 로컬 전용.

정책 특정 값(대상 법령·신설 범위·기대 분류 등)은 git에 올리지 않는다. 모두
data/golden_review_expected.json(gitignore)에서 읽고, 그 파일이 없으면 SKIP한다.
따라서 이 커밋된 코드 자체에는 어떤 개정안의 내용도 드러나지 않는다.

  uv run python -m scripts.test_llm_review_golden

기대값 JSON 형식:
  {
    "draft_file": "uploaded_draft.txt",   // data/ 기준 상대경로
    "law_name": "...",
    "range": "...",                        // 예: "29, 29의2, 29의3"
    "proxy": "24",
    "expected_range": ["...", ...],        // 구조 해석 신설_조번호에 '반드시 포함'(부분집합)
    "must_not_조치불요": [["법령명","조번호"], ...],
    "stale_missing_law_jos": ["...", ...], // 누락이어야 할 조번호들
    "stale_missing_min": 4,
    "opinion_must_mention": ["127"]
  }
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

_DATA = Path(__file__).resolve().parents[1] / "data"
_EXPECTED = _DATA / "golden_review_expected.json"


def main() -> int:
    if not _EXPECTED.is_file():
        print(f"SKIP: {_EXPECTED.name} 없음 (정책 특정 기대값 — 로컬 전용, git 미추적)")
        return 0

    spec = json.loads(_EXPECTED.read_text(encoding="utf-8"))
    draft_path = _DATA / spec["draft_file"]
    if not draft_path.is_file():
        print(f"SKIP: {draft_path.name} 없음 (내부자료 — git 미추적)")
        return 0

    from config import ANTHROPIC_API_KEY

    if not ANTHROPIC_API_KEY:
        print("SKIP: ANTHROPIC_API_KEY 미설정")
        return 0

    from core.draft_bill_parser import compare_review, find_amendment_body
    from core.llm_review import run_llm_review

    law, body = find_amendment_body(draft_path.read_text(encoding="utf-8"))
    cmp = compare_review(
        spec.get("law_name") or law, spec["range"], body, spec.get("proxy", "")
    )
    result = run_llm_review(cmp, body)

    # 1. 구조 해석: 신설 범위. expected_range는 '반드시 포함'(부분집합) 기준이다 —
    #    개정안이 별개로 신설하는 다른 조문(예: 세액감면 한도·환류)을 함께 잡는 것은
    #    회귀가 아니라 정상이므로 동일성이 아니라 포함 여부만 본다.
    inferred = set(result["구조"]["신설_조번호"])
    must = set(spec["expected_range"])
    assert must <= inferred, f"신설 범위 누락 회귀: {sorted(must - inferred)} (전체 {sorted(inferred)})"

    review = result["검토"]
    by_jo = {(it["법령명"], it["조번호"]): it["구분"] for it in review["항목"]}

    # 2. 특정 조문이 '조치불요'로 빠지면 회귀
    for law_name, jo in spec.get("must_not_조치불요", []):
        cls = by_jo.get((law_name, jo))
        assert cls != "조치불요", f"{law_name} 제{jo}조가 조치불요로 분류됨 — 회귀"

    # 3. 잔존 인용 누락 분류 최소 개수
    stale_jos = spec.get("stale_missing_law_jos", [])
    law0 = spec.get("law_name") or law
    stale_missing = sum(1 for jo in stale_jos if by_jo.get((law0, jo)) == "누락")
    assert stale_missing >= spec.get("stale_missing_min", 0), (
        f"잔존 인용 누락 분류 {stale_missing}/{len(stale_jos)} — 회귀 의심"
    )

    # 4. 종합의견
    opinion = str(review["종합의견"])
    assert len(opinion) > 100, "종합의견이 비정상적으로 짧음"
    for needle in spec.get("opinion_must_mention", []):
        assert needle in opinion, f"종합의견이 '{needle}'를 언급하지 않음"

    print("GOLDEN OK")
    print(f"  신설 범위: {sorted(inferred)}")
    print(f"  잔존 누락 분류: {stale_missing}/{len(stale_jos)}건")
    return 0


if __name__ == "__main__":
    sys.exit(main())
