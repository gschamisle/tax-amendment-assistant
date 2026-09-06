# -*- coding: utf-8 -*-
"""번호 밀림 검토 오프라인 테스트 — PDF 개행 복원 + 이동 추출 + 정비 확인."""
from __future__ import annotations

import sys

sys.stdout.reconfigure(encoding="utf-8")

from core.draft_bill_parser import find_amendment_body, manual_amendment_targets
from core.pdf_bill_text import unwrap
from core.renumber_scan import (
    citation_fixed,
    directive_texts,
    renumber_events,
)


def _events(body: str):
    return {(e.jo_key, e.unit): e.moved for e in renumber_events(body)}


def test_unwrap_restores_directive() -> None:
    """PDF 강제 개행으로 서술어가 다음 줄로 밀려도 지시문 한 줄로 복원된다."""
    pdf_like = (
        "소득세법 일부를 다음과 같이 개정한다.\n"
        "\n"
        "제17조제3항에 제1호의2를 다음과 같이 신설하고, 같은 조 제5항및제6항을\n"
        "\n"
        "각각 제6항및제7항으로 하며, 같은 조에 제5항을 다음과 같이 신설한다.\n"
    )
    law, body = find_amendment_body(unwrap(pdf_like))
    assert law == "소득세법", law
    assert manual_amendment_targets(body) == ["17"], manual_amendment_targets(body)
    assert _events(body)[("17", "항")] == {"5": "6", "6": "7"}, _events(body)


def test_opening_allows_spaced_suffix() -> None:
    """'…에 관한 법률'처럼 접미가 띄어 쓰인 법령명도 개정문 시작으로 인식한다."""
    law, body = find_amendment_body(
        "국제조세조정에 관한 법률 일부를 다음과 같이 개정한다.\n제5조제2항을 삭제한다.\n"
    )
    assert law == "국제조세조정에 관한 법률", law
    assert body


def test_range_move_expands() -> None:
    """'제2항부터 제10항까지를 각각 제3항부터 제11항까지로' → 항별 대응으로 전개."""
    body = (
        "상속세 및 증여세법 일부를 다음과 같이 개정한다.\n"
        "제18조의2제2항부터 제10항까지를 각각 제3항부터 제11항까지로 한다.\n"
    )
    moved = _events(body)[("18의2", "항")]
    assert moved == {str(n): str(n + 1) for n in range(2, 11)}, moved


def test_spaced_unit_token() -> None:
    """PDF 개행 복원이 남긴 '제2 항' 공백도 이동으로 읽는다."""
    body = (
        "조세특례제한법 일부를 다음과 같이 개정한다.\n"
        "제24조제1항을 다음과 같이 하고, 같은 조 제2 항부터 제5항까지를 "
        "각각 제4항부터 제7항까지로 한다.\n"
    )
    moved = _events(body)[("24", "항")]
    assert moved == {"2": "4", "3": "5", "4": "6", "5": "7"}, moved


def test_mok_move() -> None:
    body = (
        "국세기본법 일부를 다음과 같이 개정한다.\n"
        "제48조제2항제2호가목부터 다목까지를 각각 나목부터 라목까지로 한다.\n"
    )
    moved = _events(body)[("48", "목")]
    assert moved == {"가": "나", "나": "다", "다": "라"}, moved


def test_quoted_replacement_is_not_a_move() -> None:
    """문구 치환("제20조"을 "제20조, 제21조"로)은 번호 이동이 아니다."""
    body = (
        "소득세법 일부를 다음과 같이 개정한다.\n"
        "제12조제3호처목1) 중 “제20조”를 “제20조, 제21조”로 한다.\n"
    )
    assert not renumber_events(body), renumber_events(body)


def test_new_article_body_is_not_a_move() -> None:
    """신설 조문 '본문'의 '제7항을 …로 한다'는 지시문이 아니다."""
    body = (
        "소득세법 일부를 다음과 같이 개정한다.\n"
        "제104조에 제8항을 다음과 같이 신설한다.\n"
        "⑧ 제7항을 적용할 때 보유기간이 2년 미만인 경우에는 제7항 본문에 "
        "따른 세율을 적용하여 계산한 금액으로 한다.\n"
    )
    assert not renumber_events(body), renumber_events(body)


def test_citation_fixed_requires_both_refs() -> None:
    """구·신 표기가 함께 있어야 정비로 본다 — 조만 건드린 건 정비가 아니다."""
    body = (
        "조세특례제한법 일부를 다음과 같이 개정한다.\n"
        "제70조의2제1항 중 “양도한”을 “2029년 12월 31일까지 양도한”으로 하고, "
        "같은 조 제2항각호 외의 부분 중 “「소득세법」 제95조제4항”을 "
        "“「소득세법」 제95조제11항”으로 한다.\n"
    )
    d = directive_texts(body)["70의2"]
    assert citation_fixed(d, "95", "항", "4", "11")
    assert not citation_fixed(d, "95", "항", "3", "10")   # 정비 안 된 다른 항
    assert not citation_fixed("제70조의2제1항 중 “양도한”을 “…”으로 한다.",
                              "95", "항", "4", "11")


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        fn()
    print(f"ALL OK (renumber_scan, {len(tests)} tests)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
