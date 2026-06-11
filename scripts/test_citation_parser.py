"""인용 파서 오프라인 테스트 — 지시적(법/영/규칙 제X조) 참조 중심."""
from __future__ import annotations

import sys

from core.citation_parser import (
    Citation,
    base_law_name,
    effective_law_name,
    find_back_citations,
    parse_citations,
    resolve_deictic_law,
)
from core.law_network import _citation_matches


def _one(text: str, **attrs) -> Citation:
    cites = parse_citations(text)
    matched = [c for c in cites if all(getattr(c, k) == v for k, v in attrs.items())]
    assert matched, f"{attrs} not found in {[(c.raw, c.law_name, c.relative) for c in cites]}"
    return matched[0]


def test_deictic_parsing() -> None:
    # 시행령 → 모법: "법 제127조제1항제3호"
    c = _one("법 제127조제1항제3호에서 \"대통령령으로 정하는 사업소득\"이란 ...", jo="127")
    assert c.relative == "법" and c.law_name == "법", (c.law_name, c.relative)
    assert (c.hang, c.ho) == ("1", "3")

    # 시행규칙 → 시행령: "영 제184조"
    c = _one("영 제184조에 따른 소득을 말한다.", jo="184")
    assert c.relative == "영"

    # 자기 참조: "이 영 제15조의2"
    c = _one("이 영 제15조의2를 준용한다.", jo="15")
    assert c.relative == "이영" and c.jo_sub == "2"

    # 명시 법령명은 지시적으로 오인하지 않는다 (끝글자 '법')
    c = _one("소득세법 제127조에 따라 ...", jo="127")
    assert c.law_name == "소득세법" and c.relative == "", (c.law_name, c.relative)
    assert not any(x.relative == "법" for x in parse_citations("소득세법 제127조"))

    # 낫표 인용도 그대로
    c = _one("「부가가치세법」 제26조제1항제5호 ...", jo="26")
    assert c.law_name == "부가가치세법" and c.relative == ""

    # '같은 법'은 기존 SAME_LAW 경로 유지
    c = _one("「소득세법」 제20조 및 같은 법 제27조 ...", jo="27")
    assert c.relative == "같은법" and c.law_name == "소득세법"


def test_deictic_resolution() -> None:
    assert base_law_name("소득세법 시행령") == "소득세법"
    assert base_law_name("소득세법 시행규칙") == "소득세법"
    assert base_law_name("소득세법") == "소득세법"

    assert resolve_deictic_law("법", "소득세법 시행령") == "소득세법"
    assert resolve_deictic_law("법", "소득세법") == "소득세법"
    assert resolve_deictic_law("영", "소득세법 시행규칙") == "소득세법 시행령"
    assert resolve_deictic_law("이영", "소득세법 시행령") == "소득세법 시행령"
    assert resolve_deictic_law("규칙", "소득세법 시행령") == "소득세법 시행규칙"

    c = parse_citations("법 제129조제1항에 따라 ...")[0]
    assert effective_law_name(c, "소득세법 시행령") == "소득세법"


def test_citation_matches_cross_law() -> None:
    c = parse_citations("법 제129조제1항의 세율을 적용한다.")[0]
    # 시행령 조문 안의 '법 제129조' → 소득세법 제129조 인용으로 매칭
    assert _citation_matches(c, "소득세법 시행령", "소득세법", "129", "", "1")
    # 시행령 자신의 제129조 인용으로는 매칭되지 않아야 한다
    assert not _citation_matches(c, "소득세법 시행령", "소득세법 시행령", "129")


def test_find_back_citations_deictic() -> None:
    decree = {
        "법령명": "소득세법 시행령",
        "조문목록": [
            {"조번호": "184", "제목": "사업소득", "내용": "법 제127조제1항제3호에 따른 소득."},
            {"조번호": "20", "제목": "내부인용", "내용": "제5조제1항을 준용한다."},
        ],
    }
    # '법 제127조'는 모법 인용 — 시행령 내부 127조 역인용으로 잡히면 안 됨
    assert find_back_citations(decree, "127") == []
    # 내부 인용은 그대로 탐지
    hits = find_back_citations(decree, "5")
    assert len(hits) == 1 and hits[0]["조번호"] == "20"

    law = {
        "법령명": "소득세법",
        "조문목록": [
            {"조번호": "144", "제목": "원천징수", "내용": "제129조에 따른 원천징수세율을 적용한다."},
            {"조번호": "90", "제목": "타법", "내용": "「법인세법」 제129조에 따른다."},
        ],
    }
    hits = find_back_citations(law, "129")
    # 명시 타법(법인세법) 인용은 제외, 본법 내부 인용만
    assert [h["조번호"] for h in hits] == ["144"], hits


def main() -> int:
    test_deictic_parsing()
    test_deictic_resolution()
    test_citation_matches_cross_law()
    test_find_back_citations_deictic()
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
