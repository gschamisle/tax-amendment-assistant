# -*- coding: utf-8 -*-
"""상대참조(같은 법/같은 조)·부칙 인용 해석 회귀 테스트.

2026-06-13 실데이터에서 발견된 4건의 오탐을 고정한다. 전부 조특법 조문이
조특법 제29조를 인용하는 것으로 잘못 잡혔던 케이스다:
  - 제106조: 「온실가스…법률」 제2조 … 같은 법 제29조제1항  → 온실가스법(조특법 아님)
  - 제104조의7: 「법인세법」(같은 법 제29조는 제외한다)       → 법인세법(조특법 아님)
  - 제74조: 「법인세법」 제29조 … 같은 조 제1항제2호          → 법인세법(조특법 아님)
  - 제133조: 법률 제6538호 부칙 제29조                       → 부칙(본문 조문 아님)
"""
from __future__ import annotations

import sys

from core.citation_parser import effective_law_name, parse_citations


def _eff(text: str, source_law: str):
    """text의 인용들을 (조, source 기준 해석 법령) 목록으로."""
    return [
        (c.jo, effective_law_name(c, source_law))
        for c in parse_citations(text)
        if c.jo
    ]


def test_same_law_resolves_to_antecedent() -> None:
    # 「온실가스…법률」 제2조 … 같은 법 제29조제1항 → 같은 법 = 온실가스법
    text = "「온실가스 배출권의 할당 및 거래에 관한 법률」 제2조제3호의 배출권과 같은 법 제29조제1항에 따른 외부사업"
    pairs = _eff(text, "조세특례제한법")
    laws_29 = [law for jo, law in pairs if jo == "29"]
    assert laws_29, pairs
    assert all("조세특례제한법" not in law for law in laws_29), pairs
    assert any("온실가스" in law for law in laws_29), pairs


def test_same_law_in_parenthetical() -> None:
    # 「법인세법」(같은 법 제29조는 제외한다) → 같은 법 = 법인세법
    text = "비영리내국법인으로 보아 「법인세법」(같은 법 제29조는 제외한다)을 적용한다."
    pairs = _eff(text, "조세특례제한법")
    laws_29 = [law for jo, law in pairs if jo == "29"]
    assert laws_29, pairs
    assert all(law == "법인세법" for law in laws_29), pairs


def test_same_jo_resolves_to_antecedent_law() -> None:
    # 「법인세법」 제29조를 적용하는 경우 같은 조 제1항제2호 → 같은 조 = 법인세법 제29조
    text = "「법인세법」 제29조를 적용하는 경우 같은 조 제1항제2호에도 불구하고 해당 법인의"
    pairs = _eff(text, "조세특례제한법")
    # 모든 제29조 인용이 법인세법으로 귀속 (조특법 아님)
    laws_29 = [law for jo, law in pairs if jo == "29"]
    assert laws_29, pairs
    assert all(law == "법인세법" for law in laws_29), pairs


def test_buchik_reference_excluded() -> None:
    # 법률 제6538호 부칙 제29조 → 본문 제29조로 잡히면 안 됨
    text = "제33조, 제43조, 제70조 또는 법률 제6538호 부칙 제29조에 따라 감면받을 양도소득세액"
    jos = [c.jo for c in parse_citations(text)]
    assert "29" not in jos, f"부칙 제29조가 본문 인용으로 잡힘: {jos}"
    # 본문 조문(33, 43, 70)은 정상 탐지
    assert "33" in jos and "43" in jos and "70" in jos, jos


def test_same_law_falls_back_when_no_antecedent() -> None:
    # 선행 명시 법령이 없으면 출처 법령으로 폴백 (기존 동작 유지)
    text = "같은 법 제29조에 따라 공제한다."
    pairs = _eff(text, "조세특례제한법")
    laws_29 = [law for jo, law in pairs if jo == "29"]
    assert laws_29 == ["조세특례제한법"], pairs


def main() -> int:
    test_same_law_resolves_to_antecedent()
    test_same_law_in_parenthetical()
    test_same_jo_resolves_to_antecedent_law()
    test_buchik_reference_excluded()
    test_same_law_falls_back_when_no_antecedent()
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
