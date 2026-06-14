"""개정법률안 템플릿 파서 오프라인 테스트."""
from __future__ import annotations

import sys

from core.draft_bill_parser import (
    compare_review,
    find_amendment_body,
    manual_amendment_targets,
    new_range_block,
)
from core.new_article_scanner import parse_jo_tokens

TEMPLATE = """\
1. 의결주문
 조세특례제한법 일부개정법률안을 별지와 같이 의결한다.
2. 제안이유
 없음

법률 제 호

조세특례제한법 일부개정법률안

조세특례제한법 일부를 다음과 같이 개정한다.
제2조제1항에 제10호의4를 다음과 같이 신설한다.
 10의4. "예시"란 ...을 말한다.
제29조의 제목 "(사회기반시설채권의 이자소득에 대한 분리과세)"를 "(○○세액공제)"로 하고, 같은 조에 제2항을 다음과 같이 신설한다.
제29조(○○세액공제) ① 내국인이 「소득세법」 제19조에 따른 사업소득이 있는 경우 제24조에 따른 공제와 중복하여 적용하지 아니한다.
 ② 제1항에 따른 세액은 「법인세법」 제64조에 따라 납부하여야 할 세액으로 본다.
제144조제1항 중 "제29조의2부터 제29조의5까지"를 "제29조"로 한다.

신ㆍ구조문대비표

현행 | 개정안
제29조(사회기반시설채권...) | 제29조(○○세액공제)
"""


def test_find_body() -> None:
    law, body = find_amendment_body(TEMPLATE)
    assert law == "조세특례제한법", law
    assert body.startswith("조세특례제한법 일부를")
    assert "신ㆍ구조문대비표" not in body
    assert "현행 | 개정안" not in body

    # 템플릿이 아니면 빈 결과
    assert find_amendment_body("그냥 텍스트") == ("", "")


def test_manual_targets() -> None:
    _, body = find_amendment_body(TEMPLATE)
    targets = manual_amendment_targets(body)
    assert targets == ["2", "29", "144"], targets


def test_new_range_block() -> None:
    _, body = find_amendment_body(TEMPLATE)
    block = new_range_block(body, parse_jo_tokens("29"))
    assert "○○세액공제" in block
    assert "「소득세법」 제19조" in block
    assert "제144조제1항" not in block  # 다른 지시문 블록은 제외
    assert "제10호의4" not in block


def test_compare_review() -> None:
    _, body = find_amendment_body(TEMPLATE)
    r = compare_review("조세특례제한법", "29", body, "24")

    ext_refs = {(row["법령명"], row["조문"]) for row in r["forward"]["external"]}
    assert ("소득세법", "제19조") in ext_refs, ext_refs
    assert ("법인세법", "제64조") in ext_refs
    assert ("조세특례제한법", "제24조") in ext_refs

    # 잔존 인용: 제146조의2는 조특법 제29조를 인용하며 수기 개정에 없으므로 missing
    covered = {row["조번호"] for row in r["stale"]["covered"]}
    missing = {row["조번호"] for row in r["stale"]["missing"]}
    assert "144" in covered or "144" not in missing
    assert "146의2" in missing, missing
    # 상대참조 해석 수정(2026-06-13) 후: 제106조(온실가스법 '같은 법')·제104조의7/제74조
    # (법인세법)·제133조(부칙)는 조특법 제29조 인용이 아니므로 missing에서 제외되어야 한다
    for false_positive in ("106", "104의7", "74", "133"):
        assert false_positive not in missing, f"{false_positive} 오탐 재발: {missing}"
    # 시행령 잔존은 별도 분류
    assert all(row["법령명"] != "조세특례제한법" for row in r["stale"]["decree"])

    # 프록시(제24조): 제127조는 수기에 없으므로 missing에 있어야 함
    px_missing = {(row["법령명"], row["조번호"]) for row in r["proxy"]["missing"]}
    assert ("조세특례제한법", "127") in px_missing, px_missing


def main() -> int:
    test_find_body()
    test_manual_targets()
    test_new_range_block()
    test_compare_review()
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
