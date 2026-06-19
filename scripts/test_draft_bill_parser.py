"""개정법률안 템플릿 파서 오프라인 테스트."""
from __future__ import annotations

import sys

from core.draft_bill_parser import (
    _only_unamended_hang,
    amended_scope,
    compare_review,
    find_amendment_body,
    manual_amendment_targets,
    new_article_targets,
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


def test_new_article_targets() -> None:
    body = (
        "제134조를 다음과 같이 신설한다.\n"
        "제134조(감면한도) ① ...\n"
        "제29조의2부터 제29조의5까지를 다음과 같이 신설한다.\n"
        "제2조제1항에 제10호의4를 다음과 같이 신설한다.\n"   # 호 신설 → 제외
        "제29조 앞에 절 번호 및 제목을 다음과 같이 신설한다.\n"  # 절 신설 → 제외
    )
    got = new_article_targets(body)
    assert ("134", "") in got, got
    assert ("29", "2") in got and ("29", "5") in got, got   # 범위 전개
    assert ("2", "") not in got, got                          # 호 신설 제외


def test_amended_scope() -> None:
    # 내용개정(항 명시) → 그 항만 좁히기 가능, 번호 밀림 없음
    sc = amended_scope('제63조제1항 중 "100분의 10"을 "100분의 15"로 한다.')
    assert sc["63"]["hangs"] == {"1"} and sc["63"]["shift_from"] is None, sc
    assert sc["63"]["whole"] is False

    # 조 전체/제목 개정(항 미지정) → whole
    sc = amended_scope("제63조를 다음과 같이 한다.")
    assert sc["63"]["whole"] is True, sc

    # 항 신설 → 그 번호 이상 밀림(shift_from)
    sc = amended_scope("제63조에 제4항을 다음과 같이 신설한다.")
    assert sc["63"]["shift_from"] == 4 and sc["63"]["whole"] is False, sc

    # 실제 케이스: 제9항~제12항 삭제 + 제13항 내용개정 (따옴표 치환텍스트 무시)
    sc = amended_scope(
        '제63조제9항부터 제12항까지를 각각 삭제하고, 같은 조 제13항 중 "제12항"을 "제8항"으로 한다.'
    )
    assert sc["63"]["shift_from"] == 9, sc
    assert "13" in sc["63"]["hangs"] and "8" not in sc["63"]["hangs"], sc  # 따옴표 속 8 제외


def test_only_unamended_hang() -> None:
    # 제9항부터 삭제 → shift_from=9, 명시항 {9,12,13}
    scope = {"63": {"hangs": {"9", "12", "13"}, "shift_from": 9, "whole": False}}
    # 삭제 경계 아래의 미개정 항(3항) 인용 → 강등(True)
    assert _only_unamended_hang({"항인용": {"63": {"3"}}}, scope) is True
    # 경계 이상(번호 밀림) 항(10항) → 유지(False)
    assert _only_unamended_hang({"항인용": {"63": {"10"}}}, scope) is False
    # 명시된 개정 항(13항) → 유지
    assert _only_unamended_hang({"항인용": {"63": {"13"}}}, scope) is False
    # 조 전체 인용('') → 유지
    assert _only_unamended_hang({"항인용": {"63": {""}}}, scope) is False

    # 순수 내용개정(shift 없음): 제1항만 개정
    content = {"63": {"hangs": {"1"}, "shift_from": None, "whole": False}}
    assert _only_unamended_hang({"항인용": {"63": {"3"}}}, content) is True   # 3항 안전
    assert _only_unamended_hang({"항인용": {"63": {"1"}}}, content) is False  # 1항 개정

    # scope에 없는 조 / whole / 다중대상 / 빈 항인용 → 유지(보수적)
    assert _only_unamended_hang({"항인용": {"99": {"3"}}}, content) is False
    assert _only_unamended_hang(
        {"항인용": {"63": {"3"}}}, {"63": {"hangs": set(), "shift_from": None, "whole": True}}
    ) is False
    assert _only_unamended_hang({"항인용": {"63": {"3"}, "10": {""}}}, content) is False
    assert _only_unamended_hang({}, content) is False


def test_compare_review_hang_split() -> None:
    # 제29조는 '신설' 지시문 포함 → whole → 잔존 인용 조 단위 유지(146의2 missing)
    _, body = find_amendment_body(TEMPLATE)
    r = compare_review("조세특례제한법", "29", body, "24")
    assert "missing_hang" in r["stale"]
    missing = {row["조번호"] for row in r["stale"]["missing"]}
    hang_only = {row["조번호"] for row in r["stale"]["missing_hang"]}
    # 신설로 whole이므로 146의2는 정식 missing(항 강등 아님)
    assert "146의2" in missing and "146의2" not in hang_only, (missing, hang_only)


def test_compare_review_auto_and_mismatch() -> None:
    _, body = find_amendment_body(TEMPLATE)
    # 범위 미입력 → 감지된 개정 대상 전체 자동 적용, 일치 True
    auto = compare_review("조세특례제한법", "", body, "")
    assert auto["auto_range"] and auto["range_matched"], auto
    keys = {f"{j}의{s}" if s else j for j, s in auto["jo_list"]}
    assert keys == set(auto["manual_targets"]), (keys, auto["manual_targets"])
    assert auto["forward"]["external"], "자동 범위로도 forward가 잡혀야 한다"

    # 엉뚱한 범위 → 불일치 플래그(가짜 정상 방지)
    bad = compare_review("조세특례제한법", "999", body, "")
    assert not bad["range_matched"], bad


def main() -> int:
    test_find_body()
    test_manual_targets()
    test_new_range_block()
    test_compare_review()
    test_new_article_targets()
    test_amended_scope()
    test_only_unamended_hang()
    test_compare_review_hang_split()
    test_compare_review_auto_and_mismatch()
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
