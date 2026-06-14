# -*- coding: utf-8 -*-
"""준용(is_junyo) 태깅 회귀 테스트."""
from __future__ import annotations

import sys

from core.citation_parser import parse_citations


def _by_jo(text: str):
    return {(c.jo, c.jo_sub): c for c in parse_citations(text) if c.jo}


def test_basic_junyo() -> None:
    m = _by_jo("이 경우 제27조를 준용한다.")
    assert m[("27", "")].is_junyo is True


def test_junyo_with_regulation_phrase() -> None:
    m = _by_jo("제30조의2의 규정을 준용한다.")
    assert m[("30", "2")].is_junyo is True


def test_range_junyo() -> None:
    cites = parse_citations("제20조부터 제25조까지를 준용한다.")
    rng = [c for c in cites if c.is_range and c.jo == "20"]
    assert rng and rng[0].is_junyo is True


def test_plain_citation_not_junyo() -> None:
    # 단순 인용 — 준용 아님
    m = _by_jo("제24조에 따라 계산한 금액을 공제한다.")
    assert m[("24", "")].is_junyo is False


def test_junyo_does_not_leak_across_sentence() -> None:
    # 앞 문장 인용은 뒷 문장의 '준용'에 물들지 않는다
    m = _by_jo("제5조에 따라 신고한다. 제9조를 준용한다.")
    assert m[("5", "")].is_junyo is False
    assert m[("9", "")].is_junyo is True


def test_nearest_citation_scoping() -> None:
    # '준용'은 바로 앞 인용(제30조)에 귀속, 멀리 있는 제27조는 아님
    m = _by_jo("제27조에 따라 산정한 후 제30조를 준용한다.")
    assert m[("30", "")].is_junyo is True
    assert m[("27", "")].is_junyo is False


def main() -> int:
    test_basic_junyo()
    test_junyo_with_regulation_phrase()
    test_range_junyo()
    test_plain_citation_not_junyo()
    test_junyo_does_not_leak_across_sentence()
    test_nearest_citation_scoping()
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
