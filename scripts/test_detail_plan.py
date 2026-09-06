# -*- coding: utf-8 -*-
"""상세본 파싱·대조 오프라인 테스트."""
from __future__ import annotations

import sys

sys.stdout.reconfigure(encoding="utf-8")

from core.detail_plan import parse_items, parse_refs, scan, to_full_law
from core.parallel_omission import Bill

_PLAN = """목 차
(1) 국내생산세액공제 신설 ······················· 1
① 국내생산세액공제 요건 및 적용기한(조특법) ··· 1

Ⅰ. 잠재성장률 반등 지원

1. 미래성장동력 확충

(1) 국내생산세액공제 신설

- ① 국내생산세액공제 요건 및 적용기한(조특법 §29①)

|현행|개정안|
| --- | --- |
| <신 설> | □ 요건 … |

<개정이유> 국내생산 취약품목의 국내생산 지원

<적용시기> ’27.1.1. 이후 개시하는 과세연도부터 적용

- ② 업무용승용차 한도 조정(소득법 §33의2, 법인법 §27의2)

<개정이유> 과세 형평

- ③ 조문 표기가 없는 항목(조특법·령)

<개정이유> 정비
"""


def test_to_full_law() -> None:
    assert to_full_law("조특령") == "조세특례제한법 시행령"
    assert to_full_law("국조법") == "국제조세조정에 관한 법률"
    assert to_full_law("소득칙") == "소득세법 시행규칙"
    assert to_full_law("듣보법") == "듣보법"        # 모르면 원문 유지
    print("  약칭 → 정식 법령명 OK")


def test_parse_refs() -> None:
    """표기가 흔들린다 — 항 기호·가운뎃점·쉼표·복수 § 를 모두 받아야 한다."""
    assert parse_refs("조특법 §29①") == [("조세특례제한법", "29")]
    assert parse_refs("조특법 §29③·④·⑤") == [("조세특례제한법", "29")]
    assert parse_refs("조특법 §132·§144") == [
        ("조세특례제한법", "132"), ("조세특례제한법", "144")]
    assert parse_refs("소득법 §33의2, 법인법 §27의2") == [
        ("소득세법", "33의2"), ("법인세법", "27의2")]
    assert parse_refs("조특법 §71의3 신설") == [("조세특례제한법", "71의3")]
    assert parse_refs("조특법·령") == []            # § 없으면 조문 표기가 아니다
    print("  조문 표기 파싱 OK")


def test_parse_items_skips_toc() -> None:
    """목차는 본문과 같은 번호 체계를 써서 그냥 두면 항목으로 섞인다."""
    items = parse_items(_PLAN)
    titles = [i.title for i in items]
    assert not any("···" in t for t in titles), titles
    assert any(t.startswith("국내생산세액공제 요건") for t in titles), titles

    first = next(i for i in items if i.title.startswith("국내생산세액공제 요건"))
    assert first.refs == [("조세특례제한법", "29")], first.refs
    assert first.reason.startswith("국내생산 취약품목"), first.reason
    assert first.timing.startswith("’27.1.1."), first.timing

    no_ref = next(i for i in items if "표기가 없는" in i.title)
    assert not no_ref.has_refs and no_ref.reason == "정비"
    print("  항목 파싱·목차 제외 OK")


def test_scan_statuses() -> None:
    items = parse_items(_PLAN)
    bills = [
        Bill(law_name="조세특례제한법", targets={"29"}, directives={"29": "제29조 …"}),
        Bill(law_name="소득세법", targets={"99"}),      # 33의2를 안 건드림
    ]
    result = scan(items, bills)
    got = {(r["법령명"], r["조번호"]): r["상태"] for r in result["rows"] if r["법령명"]}
    assert got[("조세특례제한법", "29")] == "covered", got
    assert got[("소득세법", "33의2")] == "missing_in_bill", got
    assert got[("법인세법", "27의2")] == "no_bill", got      # 법인세법안이 묶음에 없음
    assert any(r["상태"] == "no_refs" for r in result["rows"])

    # 공표 자료에 없는 개정 — '누락'이 아니라 '비공개 정비'일 수 있다
    undisclosed = {(e["법령명"], e["조번호"]) for e in result["undisclosed"]}
    assert ("소득세법", "99") in undisclosed, undisclosed
    assert ("조세특례제한법", "29") not in undisclosed
    print("  대조 판정 OK")


def main() -> int:
    tests = [fn for name, fn in sorted(globals().items())
             if name.startswith("test_") and callable(fn)]
    for fn in tests:
        fn()
    print(f"ALL OK (detail_plan, {len(tests)} tests)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
