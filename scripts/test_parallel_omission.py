# -*- coding: utf-8 -*-
"""병행개정 누락 검토 오프라인 테스트."""
from __future__ import annotations

import sys

sys.stdout.reconfigure(encoding="utf-8")

from core.parallel_omission import (
    Bill,
    PARALLEL_SOURCES,
    group_by_source_article,
    load_bill,
    ref_to_jo_key,
    scan,
)


def test_ref_to_jo_key() -> None:
    """대응 조문 표기에서 조 단위 키를 뽑는다 — 항·호가 붙어도 조로 비교한다."""
    for ref, expected in [
        ("제34조", "34"),
        ("제104조의31제1항", "104의31"),
        ("제127조제1항제3호", "127"),
        ("제 12 조 의 2", "12의2"),
        ("별표 1", ""),
        ("", ""),
    ]:
        assert ref_to_jo_key(ref) == expected, (ref, ref_to_jo_key(ref))
    print("  대상 조문 키 정규화 OK")


def test_load_bill() -> None:
    bill = load_bill(
        "법인세법 일부를 다음과 같이 개정한다.\n"
        "제24조제2항제1호마목14)를 15)로 하고, 같은 목에 14)를 다음과 같이 신설한다.\n"
        "제53조제1항 중 “조약”을 “조세조약”으로 한다.\n"
    )
    assert bill is not None
    assert bill.law_name == "법인세법", bill.law_name
    assert bill.targets == {"24", "53"}, bill.targets
    assert "마목14)" in bill.directives["24"], bill.directives
    assert load_bill("이것은 개정문이 아닙니다.") is None
    print("  개정안 파싱 OK")


def test_scan_statuses(monkey=None) -> None:
    """세 상태를 가른다 — 함께 개정 / 미개정 / 그 법 개정안 없음."""
    import core.parallel_omission as mod

    fake = {
        ("법인세법", "24"): [
            {"target_law": "소득세법", "target_article": "제34조",
             "source": "golden_manual", "reason": "기부금 병행"},
            {"target_law": "소득세법", "target_article": "제99조",
             "source": "semantic_llm", "reason": "함께 개정된 쪽"},
            {"target_law": "부가가치세법", "target_article": "제10조",
             "source": "semantic_llm", "reason": "묶음에 없는 법"},
            {"target_law": "소득세법", "target_article": "제77조",
             "source": "citation", "reason": "인용 — 병행 아님"},
        ],
    }
    orig = mod.parallel_hits
    mod.parallel_hits = lambda law, jo: fake.get((law, jo), [])
    try:
        rows = scan([
            Bill(law_name="법인세법", targets={"24"}, directives={"24": "제24조 … 신설한다."}),
            Bill(law_name="소득세법", targets={"99"}),
        ])["rows"]
    finally:
        mod.parallel_hits = orig

    got = {(r["대상법령"], r["대상조문"]): r["상태"] for r in rows}
    assert got == {
        ("소득세법", "제34조"): "missing",
        ("소득세법", "제99조"): "covered",
        ("부가가치세법", "제10조"): "pending",
    }, got                                   # citation은 제외돼야 한다
    assert "citation" not in PARALLEL_SOURCES

    # 미개정이 맨 앞, 그중 매뉴얼 확정이 먼저
    assert rows[0]["상태"] == "missing" and rows[0]["근거"] == "golden_manual", rows[0]
    # 지시문이 함께 실린다 — 판단하려면 무엇을 고쳤는지 봐야 한다
    assert rows[0]["개정지시문"].startswith("제24조"), rows[0]["개정지시문"]
    print("  상태 판정·정렬·인용 제외 OK")


def test_group_by_source_article() -> None:
    rows = [
        {"법령명": "소득세법", "조번호": "45", "조문": "제45조", "개정지시문": "d",
         "대상법령": "법인세법", "대상조문": "제13조", "근거": "golden_manual",
         "상태": "missing", "사유": ""},
        {"법령명": "소득세법", "조번호": "45", "조문": "제45조", "개정지시문": "d",
         "대상법령": "법인세법", "대상조문": "제14조", "근거": "semantic_llm",
         "상태": "missing", "사유": ""},
    ]
    groups = group_by_source_article(rows)
    assert len(groups) == 1 and len(groups[0]["대응"]) == 2, groups
    print("  원 조문 묶기 OK")


def main() -> int:
    tests = [fn for name, fn in sorted(globals().items())
             if name.startswith("test_") and callable(fn)]
    for fn in tests:
        fn()
    print(f"ALL OK (parallel_omission, {len(tests)} tests)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
